"""Per-interval bounded solving with cyclical prior injection for track_runner.

Splits the video timeline into seed-to-seed intervals, solves each interval
using forward/backward propagation and competitor hypothesis tracking, and
stitches results into a full trajectory.
"""

# Standard Library
import math
import time
import multiprocessing
import concurrent.futures

# PIP3 modules
import numpy
import scipy.interpolate
import rich.progress

# local repo modules
import propagator
import hypothesis
import scoring
import state_io

# module-level shared counter for parallel workers
# set by _init_worker() via ProcessPoolExecutor initializer
_FRAME_COUNTER = None


#============================================
def _init_worker(shared_counter: multiprocessing.Value) -> None:
	"""Initialize worker process with a shared frame counter.

	Called by ProcessPoolExecutor as the initializer for each worker.
	Stores the shared counter as a module-level global so
	_solve_interval_worker() can increment it per-frame.

	Args:
		shared_counter: multiprocessing.Value('i') shared across workers.
	"""
	global _FRAME_COUNTER
	_FRAME_COUNTER = shared_counter


#============================================
# Agreement tolerance: Dice coefficient threshold for FWD/BWD agreement.
# Any overlap is meaningful for this method, so a low threshold is used.
AGREE_DICE_THRESHOLD = 0.3
# Minimum number of frames for cyclical prior detection
# retained for potential future bbox area refinement
CYCLICAL_MIN_FRAMES = 900   # ~30s at 30fps
# Expected lap period range in seconds for track events
CYCLICAL_PERIOD_MIN_S = 25.0
CYCLICAL_PERIOD_MAX_S = 60.0


#============================================
def fuse_tracks(
	forward_track: list,
	backward_track: list,
) -> list:
	"""Fuse forward and backward tracking passes frame by frame.

	Where both tracks agree (center within tolerance, scale within tolerance),
	produces a confidence-weighted average position. Where they disagree,
	picks the higher-confidence track and flags the frame. Never averages
	two mediocre conflicting paths into a false consensus.

	Args:
		forward_track: List of tracking state dicts from propagate_forward().
			Index 0 is the seed frame.
		backward_track: List of tracking state dicts from propagate_backward().
			Already reversed so index 0 is the seed frame.

	Returns:
		List of fused tracking state dicts, one per frame. Source field is
		"merged" when both agreed, "propagated" when one was picked over the
		other. A "fuse_flag" key is added when the tracks disagreed.
	"""
	n = min(len(forward_track), len(backward_track))
	fused = []

	for i in range(n):
		fwd = forward_track[i]
		bwd = backward_track[i]

		fwd_cx = float(fwd["cx"])
		fwd_cy = float(fwd["cy"])
		fwd_h = float(fwd["h"])
		fwd_conf = float(fwd["conf"])

		bwd_cx = float(bwd["cx"])
		bwd_cy = float(bwd["cy"])
		bwd_h = float(bwd["h"])
		bwd_conf = float(bwd["conf"])

		# compute Dice coefficient between FWD and BWD boxes
		fwd_box = {"cx": fwd_cx, "cy": fwd_cy, "w": float(fwd["w"]), "h": fwd_h}
		bwd_box = {"cx": bwd_cx, "cy": bwd_cy, "w": float(bwd["w"]), "h": bwd_h}
		dice = scoring._compute_dice_coefficient(fwd_box, bwd_box)

		# any meaningful overlap counts as agreement
		agree = dice >= AGREE_DICE_THRESHOLD

		if agree:
			# confidence-weighted average: stronger track pulls position more
			total_conf = fwd_conf + bwd_conf
			if total_conf <= 0.0:
				w_fwd = 0.5
			else:
				w_fwd = fwd_conf / total_conf
			w_bwd = 1.0 - w_fwd

			merged_cx = w_fwd * fwd_cx + w_bwd * bwd_cx
			merged_cy = w_fwd * fwd_cy + w_bwd * bwd_cy
			merged_w = w_fwd * fwd["w"] + w_bwd * bwd["w"]
			merged_h = w_fwd * fwd_h + w_bwd * bwd_h
			# scale confidence by overlap quality
			merged_conf = dice * max(fwd_conf, bwd_conf)

			state = {
				"cx": merged_cx,
				"cy": merged_cy,
				"w": merged_w,
				"h": merged_h,
				"conf": merged_conf,
				"source": "merged",
				"fuse_flag": False,
			}
		else:
			# disagreement: pick the higher-confidence track
			if fwd_conf >= bwd_conf:
				winner = dict(fwd)
				winner["source"] = "propagated"
			else:
				winner = dict(bwd)
				winner["source"] = "propagated"
			winner["fuse_flag"] = True
			state = winner

		fused.append(state)

	return fused


#============================================
# retained for potential future bbox area refinement
def _detect_cyclical_prior(
	trajectory: list,
	fps: float,
) -> dict | None:
	"""Detect a repeating position pattern in a completed trajectory.

	Looks for a period in [CYCLICAL_PERIOD_MIN_S, CYCLICAL_PERIOD_MAX_S]
	by computing autocorrelation of the x-coordinate signal. Returns a
	soft prior dict if a clear period is found, else None.

	Args:
		trajectory: List of tracking state dicts for completed frames.
		fps: Video frame rate in frames per second.

	Returns:
		Dict with "period_frames" and "period_s" if detected, else None.
	"""
	if len(trajectory) < CYCLICAL_MIN_FRAMES:
		return None

	# extract cx signal, replacing None entries with interpolated values
	cx_vals = []
	for state in trajectory:
		if state is not None:
			cx_vals.append(float(state["cx"]))
		elif cx_vals:
			cx_vals.append(cx_vals[-1])
		else:
			cx_vals.append(0.0)

	cx_arr = numpy.array(cx_vals, dtype=float)
	# detrend by subtracting mean
	cx_arr -= numpy.mean(cx_arr)

	# compute normalized autocorrelation
	# restrict to lags in the expected period range
	min_lag = int(CYCLICAL_PERIOD_MIN_S * fps)
	max_lag = int(CYCLICAL_PERIOD_MAX_S * fps)
	max_lag = min(max_lag, len(cx_arr) // 2)

	if min_lag >= max_lag:
		return None

	n = len(cx_arr)
	# variance for normalization
	variance = float(numpy.var(cx_arr))
	if variance < 1e-6:
		return None

	# compute autocorrelation at each lag in range
	best_corr = 0.0
	best_lag = -1
	for lag in range(min_lag, max_lag + 1):
		corr = float(numpy.mean(cx_arr[:n - lag] * cx_arr[lag:])) / variance
		if corr > best_corr:
			best_corr = corr
			best_lag = lag

	# require reasonably strong correlation to trust the period
	if best_corr < 0.4 or best_lag < 0:
		return None

	period_s = best_lag / fps
	prior = {
		"period_frames": best_lag,
		"period_s": period_s,
		"correlation": best_corr,
	}
	return prior


#============================================
def refine_interval(
	reader: object,
	start_frame: int,
	end_frame: int,
	start_state: dict,
	end_state: dict,
	fused_track: list,
	appearance_model: dict,
	backward_reader: object = None,
	debug: bool = False,
) -> list:
	"""Re-propagate an interval using the first-pass fused track as soft prior.

	Converts fused_track into a dict keyed by absolute frame index, then
	re-runs forward and backward propagation with prior_track so that each
	frame's position is gently pulled toward the fused reference. Re-fuses
	the refined passes and returns the result.

	This does NOT re-run competitor/identity scoring (preserves first-pass
	diagnostic signal for seed recommendation).

	Args:
		reader: VideoReader with read_frame() and get_info().
		start_frame: First frame index of the interval.
		end_frame: Last frame index of the interval.
		start_state: Propagator seed state at start_frame.
		end_state: Propagator seed state at end_frame.
		fused_track: First-pass fused track list (index 0 = start_frame).
		appearance_model: Appearance model from propagator.build_appearance_model().
		backward_reader: Optional second VideoReader for concurrent backward pass.
		debug: If True, print propagation heartbeats.

	Returns:
		Refined fused track list, same length and indexing as fused_track.
	"""
	# build prior dict keyed by absolute frame index
	prior_dict = {}
	for i, state in enumerate(fused_track):
		if state is not None:
			prior_dict[start_frame + i] = state

	# re-propagate with fused track as soft prior
	if backward_reader is not None:
		# concurrent forward + backward
		with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
			fwd_future = pool.submit(
				propagator.propagate_forward,
				reader, start_frame, start_state, end_frame, appearance_model,
				debug, prior_track=prior_dict,
			)
			bwd_future = pool.submit(
				propagator.propagate_backward,
				backward_reader, end_frame, end_state, start_frame,
				appearance_model, debug, prior_track=prior_dict,
			)
			refined_fwd = fwd_future.result()
			refined_bwd_raw = bwd_future.result()
	else:
		# sequential
		refined_fwd = propagator.propagate_forward(
			reader, start_frame, start_state, end_frame, appearance_model,
			debug=debug, prior_track=prior_dict,
		)
		refined_bwd_raw = propagator.propagate_backward(
			reader, end_frame, end_state, start_frame, appearance_model,
			debug=debug, prior_track=prior_dict,
		)

	# align lengths
	n = min(len(refined_fwd), len(refined_bwd_raw))
	refined_fwd = refined_fwd[:n]
	refined_bwd = refined_bwd_raw[:n]

	# re-fuse the refined passes
	refined_fused = fuse_tracks(refined_fwd, refined_bwd)
	return refined_fused


#============================================
def solve_interval(
	reader: object,
	seed_start: dict,
	seed_end: dict,
	detector: object,
	appearance_model: dict,
	show_progress: bool = False,
	frame_counter: object = None,
	backward_reader: object = None,
	debug: bool = False,
) -> dict:
	"""Solve one interval between two seed frames.

	Propagates forward from seed_start and backward from seed_end, generates
	competitor hypotheses, computes per-frame identity scores and competitor
	margins, fuses the two tracks, and scores the interval.

	Args:
		reader: VideoReader with read_frame() and get_info() methods.
		seed_start: Seed state dict at the start of the interval. Must have
			cx, cy, w, h, conf, and frame_index keys.
		seed_end: Seed state dict at the end of the interval.
		detector: Person detector with a detect(frame) method.
		appearance_model: Appearance model from propagator.build_appearance_model().
		show_progress: If True, show a rich progress bar for per-frame processing.
		frame_counter: Optional multiprocessing.Value('i') shared counter.
			Incremented after each frame is processed for progress reporting.
		backward_reader: Optional second VideoReader for backward propagation.
			When provided, forward and backward passes run concurrently in threads.
			When None, both passes use `reader` sequentially.
		debug: If True, print per-frame debug info (detection count, confidence).

	Returns:
		Dict with keys: start_frame, end_frame, fused_track, forward_track,
		backward_track, interval_score, identity_scores, competitor_margins.
	"""
	start_frame = int(seed_start["frame_index"])
	end_frame = int(seed_end["frame_index"])

	# reject degenerate intervals where start equals or exceeds end
	if start_frame >= end_frame:
		raise RuntimeError(
			f"degenerate interval: start_frame={start_frame} >= end_frame={end_frame}. "
			f"Seeds likely have duplicate frame_index values."
		)

	# build start and end propagator states from seeds
	start_state = propagator.make_seed_state(
		cx=float(seed_start["cx"]),
		cy=float(seed_start["cy"]),
		w=float(seed_start["w"]),
		h=float(seed_start["h"]),
		# None means unscored human seed, treat as full confidence
		conf=1.0 if seed_start["conf"] is None else float(seed_start["conf"]),
		seed_status=seed_start.get("status", ""),
	)
	end_state = propagator.make_seed_state(
		cx=float(seed_end["cx"]),
		cy=float(seed_end["cy"]),
		w=float(seed_end["w"]),
		h=float(seed_end["h"]),
		# None means unscored human seed, treat as full confidence
		conf=1.0 if seed_end["conf"] is None else float(seed_end["conf"]),
		seed_status=seed_end.get("status", ""),
	)

	# propagate forward from start to end, and backward from end to start
	n_frames = end_frame - start_frame

	if backward_reader is not None:
		# run forward and backward concurrently using threads
		# OpenCV releases the GIL during frame reads so threads give real parallelism
		if debug:
			print(f"    propagating forward+backward {n_frames} frames concurrently...", flush=True)
		with concurrent.futures.ThreadPoolExecutor(max_workers=2) as thread_pool:
			fwd_future = thread_pool.submit(
				propagator.propagate_forward,
				reader, start_frame, start_state, end_frame, appearance_model,
				debug,
			)
			bwd_future = thread_pool.submit(
				propagator.propagate_backward,
				backward_reader, end_frame, end_state, start_frame, appearance_model,
				debug,
			)
			forward_track = fwd_future.result()
			backward_raw = bwd_future.result()
		if debug:
			print(f"    forward+backward done ({len(forward_track)}+{len(backward_raw)} states)", flush=True)
	else:
		# sequential path: single reader for both passes
		if debug:
			print(f"    propagating forward {n_frames} frames ({start_frame}-{end_frame})...", flush=True)
		forward_track = propagator.propagate_forward(
			reader, start_frame, start_state, end_frame, appearance_model,
			debug=debug,
		)
		if debug:
			print(f"    forward done ({len(forward_track)} states)", flush=True)
		if debug:
			print(f"    propagating backward {n_frames} frames ({end_frame}-{start_frame})...", flush=True)
		backward_raw = propagator.propagate_backward(
			reader, end_frame, end_state, start_frame, appearance_model,
			debug=debug,
		)
		if debug:
			print(f"    backward done ({len(backward_raw)} states)", flush=True)
	# backward_raw index 0 = start_frame (earliest), last = end_frame
	# align length with forward_track
	n = min(len(forward_track), len(backward_raw))
	forward_track = forward_track[:n]
	backward_aligned = backward_raw[:n]

	# compute per-frame identity scores and competitor margins
	identity_scores = []
	competitor_margins = []
	competitors = []

	# optional rich progress bar for per-frame debug output
	progress_ctx = None
	progress_task = None
	if show_progress:
		progress_ctx = rich.progress.Progress(
			rich.progress.TextColumn("{task.description}"),
			rich.progress.BarColumn(),
			rich.progress.TaskProgressColumn(),
			rich.progress.TimeRemainingColumn(),
		)
		progress_ctx.start()
		progress_task = progress_ctx.add_task(
			f"  solving {start_frame}-{end_frame}", total=n,
		)

	for i in range(n):
		frame_idx = start_frame + i
		frame = reader.read_frame(frame_idx)
		if frame is None:
			identity_scores.append(0.5)
			competitor_margins.append(0.5)
			continue

		# use forward state as the target for this frame
		target = forward_track[i]

		# run detector: use ROI crop on frames after the first (where we
		# have a predicted position), full-frame on the first frame
		if detector is None:
			detections = []
		elif i == 0:
			# first frame: no prior prediction, run full-frame detection
			detections = detector.detect(frame)
		else:
			# frames 1+: crop around predicted position for better resolution
			roi_center = (float(target["cx"]), float(target["cy"]))
			roi_size = (float(target["w"]), float(target["h"]))
			detections = detector.detect_roi(
				frame, roi_center, roi_size,
			)

		# generate competitors from new detections
		if i == 0:
			competitors = hypothesis.generate_competitors(
				frame, target, detections, appearance_model,
			)
		else:
			prev_frame = reader.read_frame(frame_idx - 1)
			if prev_frame is not None:
				competitors = hypothesis.maintain_paths(
					competitors, frame, prev_frame, detections,
				)
			else:
				competitors = hypothesis.generate_competitors(
					frame, target, detections, appearance_model,
				)

		# compute identity score for the target
		id_score = hypothesis.compute_identity_score(frame, target, appearance_model)
		identity_scores.append(id_score)

		# update target identity_score for margin computation
		target_with_id = dict(target)
		target_with_id["identity_score"] = id_score
		for comp in competitors:
			if "identity_score" not in comp:
				comp["identity_score"] = hypothesis.compute_identity_score(
					frame, comp, appearance_model,
				)

		margin = hypothesis.compute_competitor_margin(target_with_id, competitors)
		competitor_margins.append(margin)

		# update rich progress bar when active
		if progress_ctx is not None:
			progress_ctx.update(progress_task, advance=1)

		# increment shared frame counter for parallel progress reporting
		if frame_counter is not None:
			with frame_counter.get_lock():
				frame_counter.value += 1

		# debug: print per-frame status
		if debug and progress_ctx is not None:
			det_count = len(detections)
			comp_count = len(competitors)
			progress_ctx.console.print(
				f"    frame {frame_idx}: "
				f"dets={det_count} comps={comp_count} "
				f"id={id_score:.2f} margin={margin:.2f}"
			)

	# stop rich progress bar when active
	if progress_ctx is not None:
		progress_ctx.stop()

	# fuse forward and backward tracks
	fused_track = fuse_tracks(forward_track, backward_aligned)

	# score the FIRST-PASS fused track (diagnostic: raw uncertainty)
	# this preserves FWD/BWD disagreement signal for seed recommendation
	interval_score = scoring.score_interval(
		forward_track,
		backward_aligned,
		identity_scores,
		competitor_margins,
	)

	# refinement pass: re-propagate with fused track as soft prior
	refined_track = refine_interval(
		reader, start_frame, end_frame,
		start_state, end_state, fused_track, appearance_model,
		backward_reader=backward_reader, debug=debug,
	)

	result = {
		"start_frame": start_frame,
		"end_frame": end_frame,
		# refined fused track used for crop/output
		"fused_track": refined_track,
		# first-pass tracks preserved for diagnostics
		"forward_track": forward_track,
		"backward_track": backward_aligned,
		# interval_score from first-pass (diagnostic, not refined)
		"interval_score": interval_score,
		"identity_scores": identity_scores,
		"competitor_margins": competitor_margins,
	}
	return result


#============================================
def stitch_trajectories(
	interval_results: list,
) -> list:
	"""Concatenate interval trajectories into a full video trajectory.

	At interval boundaries (seed frames), uses the seed state from the
	start of the next interval (higher confidence). Gaps between intervals
	(if any) are left as None.

	Args:
		interval_results: List of interval result dicts from solve_interval(),
			sorted by start_frame.

	Returns:
		List of tracking state dicts indexed by frame number. Frames not
		covered by any interval are None.
	"""
	if not interval_results:
		return []

	# find total frame span
	last_end = max(r["end_frame"] for r in interval_results)
	trajectory = [None] * (last_end + 1)

	for result in interval_results:
		start = result["start_frame"]
		fused = result["fused_track"]
		for i, state in enumerate(fused):
			frame_idx = start + i
			if 0 <= frame_idx <= last_end:
				trajectory[frame_idx] = state

	return trajectory


#============================================
#============================================
def _solve_interval_worker(
	video_path: str,
	seed_start: dict,
	seed_end: dict,
	appearance_data: dict,
	config: dict,
	worker_id: int,
) -> dict:
	"""Worker function for parallel interval solving.

	Creates its own VideoReader pair and detector, solves one interval
	with concurrent forward/backward propagation, then closes resources.
	Must be a module-level function for pickling.

	Args:
		video_path: Path to input video file.
		seed_start: Seed state dict for interval start.
		seed_end: Seed state dict for interval end.
		appearance_data: Serializable appearance model dict.
		config: Project configuration dict.
		worker_id: Worker identifier for progress display.

	Returns:
		Interval result dict from solve_interval().
	"""
	# each worker creates its own VideoReader pair and detector
	import encoder as _enc
	import detection as _det
	reader = _enc.VideoReader(video_path)
	backward_reader = _enc.VideoReader(video_path)
	detector = _det.create_detector(config)
	# use the module-level shared counter set by _init_worker()
	result = solve_interval(
		reader, seed_start, seed_end, detector, appearance_data,
		show_progress=False, frame_counter=_FRAME_COUNTER,
		backward_reader=backward_reader,
	)
	reader.close()
	backward_reader.close()
	return result


#============================================
def _format_interval_result(result: dict, fps: float) -> str:
	"""Format a single interval result as a summary string.

	Args:
		result: Interval result dict from solve_interval().
		fps: Video frame rate for duration calculation.

	Returns:
		Formatted string with interval metrics.
	"""
	start_frame = result["start_frame"]
	end_frame = result["end_frame"]
	duration_s = (end_frame - start_frame) / fps
	score = result["interval_score"]
	agree = score["agreement_score"]
	margin = score["competitor_margin"]
	identity = score["identity_score"]
	confidence = score["confidence"]
	reasons = score["failure_reasons"]
	# format label by confidence tier
	_confidence_labels = {
		"high": "TRUST", "good": "GOOD", "fair": "FAIR", "low": "WEAK",
	}
	tag = _confidence_labels.get(confidence, "WEAK")
	if confidence in ("high", "good"):
		label = f"[{tag}]"
	else:
		reason_str = ", ".join(reasons) if reasons else "low_confidence"
		label = f"[{tag}: {reason_str}]"
	line = (
		f"  interval {start_frame:5d}-{end_frame:5d} "
		f"({duration_s:.1f}s)  "
		f"agree={agree:.2f}  "
		f"margin={margin:.2f}  "
		f"identity={identity:.2f}  "
		f"{label}"
	)
	return line


#============================================
def _print_interval_result(result: dict, fps: float) -> None:
	"""Print a single interval result summary line.

	Args:
		result: Interval result dict from solve_interval().
		fps: Video frame rate for duration calculation.
	"""
	print(_format_interval_result(result, fps))


#============================================
def _print_interval_result_rich(
	result: dict,
	fps: float,
	progress: rich.progress.Progress,
) -> None:
	"""Print an interval result line through rich console.

	Uses progress.console.print() so the output does not conflict
	with the live progress bar display.

	Args:
		result: Interval result dict from solve_interval().
		fps: Video frame rate for duration calculation.
		progress: Active rich Progress instance.
	"""
	progress.console.print(_format_interval_result(result, fps))


#============================================
def _stamp_seed_confidence(
	trajectory: list,
	seeds: list,
) -> list:
	"""Stamp seed confidence and status onto trajectory at seed frames.

	Ensures seed frames have the correct confidence regardless of what
	fuse_tracks() computed. Visible and partial seeds get conf=1.0
	(precise position known). Approx seeds get conf=0.3 (uncertain).

	Also propagates seed_status into the trajectory state for downstream
	consumers (crop, encoder) to know which frames have human-verified
	positions.

	Args:
		trajectory: List of tracking state dicts indexed by frame number.
		seeds: List of all seed dicts.

	Returns:
		The modified trajectory list (same object, modified in place).
	"""
	n = len(trajectory)
	stamped = 0
	for seed in seeds:
		frame_idx = int(seed["frame_index"])
		if frame_idx < 0 or frame_idx >= n:
			continue
		if trajectory[frame_idx] is None:
			continue
		status = seed.get("status", "")
		# visible and partial seeds have precise position
		if status in ("visible", "partial"):
			trajectory[frame_idx]["conf"] = 1.0
			trajectory[frame_idx]["seed_status"] = status
			stamped += 1
		# approx seeds have uncertain but useful position
		elif status in ("approximate", "obstructed"):
			trajectory[frame_idx]["conf"] = 0.3
			trajectory[frame_idx]["seed_status"] = status
			stamped += 1
	if stamped > 0:
		print(f"  stamped confidence on {stamped} seed frames")
	return trajectory


# erase radius in seconds for trajectory erasure
APPROX_ERASE_RADIUS_S = 0.5     # seconds to erase around approx seeds
NOT_IN_FRAME_ERASE_RADIUS_S = 1.0  # seconds to erase around not_in_frame seeds


#============================================
def _apply_trajectory_erasure(
	trajectory: list,
	seeds: list,
	fps: float,
) -> list:
	"""Erase trajectory near seeds that lack accurate position data.

	Callers pass ALL seeds; this function decides what to erase based
	on the four drawing modes:

	- visible: precise torso box, fully visible runner. NO erasure.
	- partial: precise torso box, partially hidden but position known.
	  NO erasure.
	- approximate: larger approx area where the runner is believed to
	  be (fully hidden behind obstruction). Erase within
	  APPROX_ERASE_RADIUS_S. Position is uncertain.
	- not_in_frame: runner completely outside the frame. Erase within
	  NOT_IN_FRAME_ERASE_RADIUS_S. No position data at all.

	Legacy seeds with status "obstructed" are treated the same as
	"approximate".

	Args:
		trajectory: List of tracking state dicts (or None) indexed by frame.
		seeds: List of all seed dicts (any status).
		fps: Video frame rate for converting seconds to frames.

	Returns:
		The modified trajectory list (same object, modified in place).
	"""
	n = len(trajectory)
	erase_count = 0
	for seed in seeds:
		status = seed.get("status", "")
		# visible: precise torso box, fully visible -- keep
		if status == "visible":
			continue
		# partial: precise torso box, position known -- keep
		if status == "partial":
			continue
		# approximate (or legacy "obstructed"): uncertain position -- erase
		if status in ("approximate", "obstructed"):
			radius_frames = int(round(APPROX_ERASE_RADIUS_S * fps))
		# not_in_frame: runner off-screen -- erase
		elif status == "not_in_frame":
			radius_frames = int(round(NOT_IN_FRAME_ERASE_RADIUS_S * fps))
		else:
			# unknown status, skip safely
			continue
		erase_count += 1
		seed_frame = int(seed["frame_index"])
		# erase frames within the radius
		erase_start = max(0, seed_frame - radius_frames)
		erase_end = min(n - 1, seed_frame + radius_frames)
		for fi in range(erase_start, erase_end + 1):
			if status in ("approximate", "obstructed"):
				# use the approx seed position as a low-confidence hint
				# instead of None which becomes a center-frame fallback
				trajectory[fi] = {
					"cx": float(seed["cx"]),
					"cy": float(seed["cy"]),
					"w": float(seed["w"]),
					"h": float(seed["h"]),
					"conf": 0.3,
					"source": "approx_seed_hint",
				}
			else:
				# not_in_frame: runner truly off-screen, erase to None
				trajectory[fi] = None
	if erase_count > 0:
		print(f"  erasing trajectory near {erase_count} seeds")
	return trajectory


# anchor interpolation constants
ANCHOR_PROXIMITY_SKIP = 7        # frames near seeds to skip (~0.23s at 30fps)
ANCHOR_BLEND_SCALE_XY = 0.5     # max blend for cx/cy at zero confidence
ANCHOR_BLEND_SCALE_WH = 0.3     # max blend for w/h (weaker, avoid zoom pumping)
ANCHOR_MAX_DISP_XY = 0.25       # fraction of box dimension for cx/cy cap
ANCHOR_MAX_DISP_WH = 0.15       # fraction of dimension for w/h cap
ANCHOR_WINDOW_SEEDS = 4         # max seeds to include on each side of target


#============================================
def _collect_anchor_knots(
	seeds: list,
) -> list:
	"""Collect trusted knots from seeds for anchor interpolation.

	Filters to visible/partial seeds with valid torso_box, extracts
	(frame_index, cx, cy, w, h, status) tuples, deduplicates by
	frame_index preferring visible over partial and larger area.

	Args:
		seeds: List of all seed dicts.

	Returns:
		List of knot tuples sorted by frame_index, deduplicated.
	"""
	raw_knots = []
	for seed in seeds:
		status = seed.get("status", "")
		if status not in ("visible", "partial"):
			continue
		# use the seed's center coordinates (cx, cy) directly;
		# torso_box stores [x, y, w, h] (top-left), not center
		seed_cx = seed.get("cx")
		seed_cy = seed.get("cy")
		seed_w = seed.get("w")
		seed_h = seed.get("h")
		if seed_cx is None or seed_cy is None:
			# fall back to torso_box and convert to center
			torso_box = seed.get("torso_box")
			if torso_box is None:
				continue
			seed_cx = float(torso_box[0]) + float(torso_box[2]) / 2.0
			seed_cy = float(torso_box[1]) + float(torso_box[3]) / 2.0
			seed_w = float(torso_box[2])
			seed_h = float(torso_box[3])
		cx = float(seed_cx)
		cy = float(seed_cy)
		w = float(seed_w)
		h = float(seed_h)
		# skip invalid dimensions
		if w <= 0 or h <= 0:
			continue
		fi = int(seed["frame_index"])
		raw_knots.append((fi, cx, cy, w, h, status))

	# sort by frame_index
	raw_knots.sort(key=lambda k: k[0])

	# deduplicate by frame_index:
	# prefer visible over partial; among same status, prefer larger area
	deduped = {}
	for knot in raw_knots:
		fi = knot[0]
		status = knot[5]
		area = knot[3] * knot[4]
		if fi not in deduped:
			deduped[fi] = knot
		else:
			existing = deduped[fi]
			existing_status = existing[5]
			existing_area = existing[3] * existing[4]
			# prefer visible over partial
			if status == "visible" and existing_status != "visible":
				deduped[fi] = knot
			elif status == existing_status and area > existing_area:
				deduped[fi] = knot

	# return sorted list
	result = sorted(deduped.values(), key=lambda k: k[0])
	return result


#============================================
def _build_local_fit(
	knots: list,
	center_frame: int,
	window_seeds: int,
) -> tuple:
	"""Build local interpolators from a subset of knots near center_frame.

	Selects up to window_seeds knots on each side of center_frame.
	Builds CubicSpline for cx/cy and PchipInterpolator for log(w)/log(h).
	Falls back to numpy.interp (linear) when only 2 knots are available.

	Args:
		knots: Full sorted list of knot tuples (fi, cx, cy, w, h, status).
		center_frame: Frame index to center the window around.
		window_seeds: Max seeds to include on each side.

	Returns:
		Tuple of (interpolators_dict, knot_frame_tuple) or None if < 2 knots.
		interpolators_dict has keys: cx_interp, cy_interp, logw_interp, logh_interp.
		Each value is either a callable or a tuple (frames, values) for linear fallback.
	"""
	# find knots before and after center_frame
	before = []
	after = []
	for knot in knots:
		if knot[0] < center_frame:
			before.append(knot)
		elif knot[0] > center_frame:
			after.append(knot)
		else:
			# knot at center_frame goes to both sides conceptually
			before.append(knot)
			after.append(knot)

	# take nearest window_seeds from each side
	selected_before = before[-window_seeds:]
	selected_after = after[:window_seeds]

	# combine and deduplicate by frame index
	combined = {}
	for knot in selected_before + selected_after:
		combined[knot[0]] = knot
	local_knots = sorted(combined.values(), key=lambda k: k[0])

	if len(local_knots) < 2:
		return None

	frames = numpy.array([k[0] for k in local_knots], dtype=float)
	cx_vals = numpy.array([k[1] for k in local_knots], dtype=float)
	cy_vals = numpy.array([k[2] for k in local_knots], dtype=float)
	w_vals = numpy.array([k[3] for k in local_knots], dtype=float)
	h_vals = numpy.array([k[4] for k in local_knots], dtype=float)

	# log-space for w and h
	logw_vals = numpy.array([math.log(v) for v in w_vals], dtype=float)
	logh_vals = numpy.array([math.log(v) for v in h_vals], dtype=float)

	interps = {}
	knot_frames = tuple(int(k[0]) for k in local_knots)

	if len(local_knots) == 2:
		# linear fallback: store arrays for numpy.interp
		interps["cx_interp"] = (frames, cx_vals)
		interps["cy_interp"] = (frames, cy_vals)
		interps["logw_interp"] = (frames, logw_vals)
		interps["logh_interp"] = (frames, logh_vals)
	else:
		# CubicSpline for cx, cy
		interps["cx_interp"] = scipy.interpolate.CubicSpline(
			frames, cx_vals, bc_type="natural",
		)
		interps["cy_interp"] = scipy.interpolate.CubicSpline(
			frames, cy_vals, bc_type="natural",
		)
		# PCHIP for log(w), log(h) to avoid overshoot
		interps["logw_interp"] = scipy.interpolate.PchipInterpolator(
			frames, logw_vals,
		)
		interps["logh_interp"] = scipy.interpolate.PchipInterpolator(
			frames, logh_vals,
		)

	return (interps, knot_frames)


#============================================
def _eval_fit(interps: dict, frame: float) -> tuple:
	"""Evaluate interpolators at a given frame index.

	Handles both callable (CubicSpline/PCHIP) and tuple (linear) forms.

	Args:
		interps: Dict with cx_interp, cy_interp, logw_interp, logh_interp.
		frame: Frame index to evaluate at.

	Returns:
		Tuple of (ref_cx, ref_cy, ref_w, ref_h).
	"""
	# evaluate cx
	cx_obj = interps["cx_interp"]
	if callable(cx_obj):
		ref_cx = float(cx_obj(frame))
	else:
		ref_cx = float(numpy.interp(frame, cx_obj[0], cx_obj[1]))

	# evaluate cy
	cy_obj = interps["cy_interp"]
	if callable(cy_obj):
		ref_cy = float(cy_obj(frame))
	else:
		ref_cy = float(numpy.interp(frame, cy_obj[0], cy_obj[1]))

	# evaluate w in log-space, exponentiate
	logw_obj = interps["logw_interp"]
	if callable(logw_obj):
		ref_w = math.exp(float(logw_obj(frame)))
	else:
		ref_w = math.exp(float(numpy.interp(frame, logw_obj[0], logw_obj[1])))

	# evaluate h in log-space, exponentiate
	logh_obj = interps["logh_interp"]
	if callable(logh_obj):
		ref_h = math.exp(float(logh_obj(frame)))
	else:
		ref_h = math.exp(float(numpy.interp(frame, logh_obj[0], logh_obj[1])))

	return (ref_cx, ref_cy, ref_w, ref_h)


#============================================
def _segment_by_knot_window(
	frame_range: range,
	knots: list,
	window_seeds: int,
) -> list:
	"""Group consecutive frames into segments sharing the same knot window.

	For each frame, determines which knots fall in the local window.
	Consecutive frames with identical knot sets are grouped into segments.

	Args:
		frame_range: Range of frame indices to segment.
		knots: Full sorted list of knot tuples.
		window_seeds: Max seeds on each side of each frame.

	Returns:
		List of (start_frame, end_frame, knot_subset) tuples.
		end_frame is inclusive.
	"""
	if not knots:
		return []

	segments = []
	current_key = None
	current_start = None
	current_knots = None

	for fi in frame_range:
		# find nearest window_seeds knots on each side
		before = []
		after = []
		for knot in knots:
			if knot[0] < fi:
				before.append(knot)
			elif knot[0] > fi:
				after.append(knot)
			else:
				before.append(knot)
				after.append(knot)

		selected_before = before[-window_seeds:]
		selected_after = after[:window_seeds]

		# combine and deduplicate
		combined = {}
		for knot in selected_before + selected_after:
			combined[knot[0]] = knot
		local_knots = sorted(combined.values(), key=lambda k: k[0])
		# key is the tuple of frame indices in this window
		key = tuple(k[0] for k in local_knots)

		if key != current_key:
			# start a new segment
			if current_key is not None:
				segments.append((current_start, fi - 1, current_knots))
			current_key = key
			current_start = fi
			current_knots = local_knots
		# else: extend current segment

	# close the last segment
	if current_key is not None:
		last_frame = frame_range[-1] if frame_range else current_start
		segments.append((current_start, last_frame, current_knots))

	return segments


#============================================
def anchor_to_seeds(
	trajectory: list,
	seeds: list,
) -> list:
	"""Apply multi-seed anchored interpolation to a stitched trajectory.

	Corrects drift in fused trajectories by fitting local splines through
	seed positions and blending corrections toward the reference path.
	Visible seeds are hard-pinned; partial seeds guide the fit but are
	not forced to exact values.

	This is a weak kinematic prior: runners move smoothly over short
	windows. Confidence-modulated blending improves tracking stability
	without hiding real motion.

	Args:
		trajectory: List of tracking state dicts indexed by frame number.
		seeds: List of all seed dicts.

	Returns:
		The corrected trajectory list (same length).
	"""
	# guard: check if already applied
	first_state = None
	for state in trajectory:
		if state is not None:
			first_state = state
			break
	if first_state is None:
		return trajectory
	if first_state.get("_anchor_applied"):
		return trajectory

	# collect trusted knots from seeds
	knots = _collect_anchor_knots(seeds)
	if len(knots) < 2:
		return trajectory

	# correction range: first knot frame to last knot frame
	first_knot_frame = knots[0][0]
	last_knot_frame = knots[-1][0]

	# build set of all knot frame indices for proximity check
	knot_frame_set = set(k[0] for k in knots)

	# build dicts of seed knots by status for pinning and source restoration
	visible_knots = {}
	partial_knots = {}
	for knot in knots:
		if knot[5] == "visible":
			visible_knots[knot[0]] = knot
		elif knot[5] == "partial":
			partial_knots[knot[0]] = knot

	# segment the correction range by knot window
	correction_range = range(first_knot_frame, last_knot_frame + 1)
	segments = _segment_by_knot_window(
		correction_range, knots, ANCHOR_WINDOW_SEEDS,
	)

	n = len(trajectory)
	corrected_count = 0

	for seg_start, seg_end, seg_knots in segments:
		# build one fit for this segment
		# use the midpoint of the segment as center_frame for the fit
		seg_mid = (seg_start + seg_end) // 2
		fit_result = _build_local_fit(knots, seg_mid, ANCHOR_WINDOW_SEEDS)
		if fit_result is None:
			continue
		interps, _ = fit_result

		for fi in range(seg_start, seg_end + 1):
			if fi < 0 or fi >= n:
				continue
			state = trajectory[fi]
			if state is None:
				continue

			# proximity skip: do not correct frames near any knot
			near_seed = False
			for kf in knot_frame_set:
				if abs(fi - kf) <= ANCHOR_PROXIMITY_SKIP:
					near_seed = True
					break
			if near_seed:
				continue

			# current tracker values
			cur_cx = float(state["cx"])
			cur_cy = float(state["cy"])
			cur_w = float(state["w"])
			cur_h = float(state["h"])
			conf = float(state.get("conf", 0.5))

			# evaluate reference from fit
			ref_cx, ref_cy, ref_w, ref_h = _eval_fit(interps, float(fi))

			# compute blend factors (stronger correction at low confidence)
			blend_xy = ANCHOR_BLEND_SCALE_XY * (1.0 - conf) ** 2
			blend_wh = ANCHOR_BLEND_SCALE_WH * (1.0 - conf) ** 2

			# compute raw displacements
			dx = ref_cx - cur_cx
			dy = ref_cy - cur_cy
			dw = ref_w - cur_w
			dh = ref_h - cur_h

			# clamp displacements by axis-appropriate caps
			max_dx = ANCHOR_MAX_DISP_XY * cur_w
			max_dy = ANCHOR_MAX_DISP_XY * cur_h
			max_dw = ANCHOR_MAX_DISP_WH * cur_w
			max_dh = ANCHOR_MAX_DISP_WH * cur_h

			dx = max(-max_dx, min(max_dx, dx))
			dy = max(-max_dy, min(max_dy, dy))
			dw = max(-max_dw, min(max_dw, dw))
			dh = max(-max_dh, min(max_dh, dh))

			# apply blended corrections
			new_cx = cur_cx + blend_xy * dx
			new_cy = cur_cy + blend_xy * dy
			new_w = cur_w + blend_wh * dw
			new_h = cur_h + blend_wh * dh

			# ensure positive dimensions
			if new_w > 0 and new_h > 0:
				state["cx"] = new_cx
				state["cy"] = new_cy
				state["w"] = new_w
				state["h"] = new_h
				corrected_count += 1

	# hard-pin visible seed frames to exact seed positions
	# also restore source/seed_status so the color system routes correctly
	pinned_count = 0
	for fi, knot in visible_knots.items():
		if fi < 0 or fi >= n:
			continue
		state = trajectory[fi]
		if state is None:
			continue
		state["cx"] = knot[1]
		state["cy"] = knot[2]
		state["w"] = knot[3]
		state["h"] = knot[4]
		# restore seed identity so overlay color uses seed_status palette
		state["source"] = "seed"
		state["seed_status"] = knot[5]
		pinned_count += 1

	# restore source/seed_status on partial seed frames (not hard-pinned,
	# but need correct color in debug overlay)
	for fi, knot in partial_knots.items():
		if fi < 0 or fi >= n:
			continue
		state = trajectory[fi]
		if state is None:
			continue
		state["source"] = "seed"
		state["seed_status"] = knot[5]

	if corrected_count > 0 or pinned_count > 0:
		print(
			f"  anchor_to_seeds: corrected {corrected_count} frames, "
			f"pinned {pinned_count} visible seeds"
		)

	# stamp guard flag on first non-None state
	for state in trajectory:
		if state is not None:
			state["_anchor_applied"] = True
			break

	return trajectory


#============================================
def _prepare_usable_seed(seed: dict) -> dict:
	"""Copy seed and set default conf=0.3 for approx seeds.

	When a runner is fully hidden, the user draws a larger approx area
	indicating the general region. This guides the solver through the
	gap but confidence is low because the exact position is unknown.

	Args:
		seed: Seed dict, possibly with status "approximate" or legacy
			"obstructed".

	Returns:
		Original seed if not approx, or a copy with conf=0.3 if
		approx and conf was not already set.
	"""
	if seed["status"] in ("approximate", "obstructed") and seed.get("conf") is None:
		prepared = dict(seed)
		# approx area, uncertain position -- lower confidence
		prepared["conf"] = 0.3
		return prepared
	return seed


#============================================
def solve_all_intervals(
	reader: object,
	seeds: list,
	detector: object,
	config: dict,
	num_workers: int = 1,
	debug: bool = False,
	on_interval_complete: object = None,
	prior_intervals: dict = None,
	on_interval_solved: object = None,
) -> dict:
	"""Solve all seed-to-seed intervals and stitch into a full trajectory.

	Splits the seed list into consecutive pairs, solves each interval,
	stitches results, and returns a diagnostics-format dict with per-interval
	scoring and the full trajectory.

	When num_workers > 1, intervals are solved in parallel using separate
	processes, each with its own VideoReader and detector instance.

	Console output is emitted for each interval in the format:
		interval  150- 450 (10.0s)  agree=0.92  margin=0.71  identity=0.88  [TRUST]

	Args:
		reader: VideoReader with read_frame() and get_info() methods.
		seeds: List of seed dicts sorted by frame_index. Each seed must have
			cx, cy, w, h, frame_index keys. Non-visible seeds are skipped.
		detector: Person detector with a detect(frame) method.
		config: Project configuration dict (currently unused; reserved).
		num_workers: Number of parallel workers for solving. Default 1 (sequential).
		debug: If True, show per-frame debug output and progress bars.
		on_interval_complete: Optional callback called with each interval result
			dict as intervals finish. Used for interactive seed requesting.
		prior_intervals: Optional dict of fingerprint->result for reusing
			previously solved intervals. Keys are from state_io.interval_fingerprint().
		on_interval_solved: Optional callback(fingerprint, result) called when
			a new interval is solved, for persisting to the solved-intervals file.

	Returns:
		Dict with keys:
			- "intervals": list of interval result dicts
			- "trajectory": full frame-by-frame tracking state list
	"""
	info = reader.get_info()
	fps = float(info.get("fps", 30.0))

	# filter to usable seeds for interval endpoint solving:
	# - visible: precise torso box, fully visible runner
	# - partial: precise torso box, partially hidden but position known
	# - approximate (or legacy obstructed with torso_box): uncertain position,
	#   guides solver through gap as weak endpoint
	# not_in_frame and legacy obstructed without torso_box are excluded
	usable_seeds = [
		_prepare_usable_seed(s) for s in seeds
		if s["status"] in ("visible", "partial", "approximate")
		or (s["status"] == "obstructed" and s.get("torso_box") is not None)
	]

	if len(usable_seeds) < 2:
		print("  interval_solver: need at least 2 usable seeds to solve intervals")
		return {"intervals": [], "trajectory": []}

	# sort by frame_index to ensure consecutive pairs are correct
	usable_seeds_sorted = sorted(usable_seeds, key=lambda s: int(s["frame_index"]))

	# validate required fields on each seed - fail loud, never default to 0
	required_fields = ("cx", "cy", "w", "h", "frame_index")
	for seed_idx, seed in enumerate(usable_seeds_sorted):
		for field in required_fields:
			if field not in seed:
				raise RuntimeError(
					f"seed {seed_idx} missing required field '{field}': {seed}"
				)
			val = seed[field]
			if val is None or (isinstance(val, (int, float)) and val == 0
				and field in ("w", "h")):
				raise RuntimeError(
					f"seed {seed_idx} has invalid value for '{field}': {val}"
				)

	# deduplicate seeds by frame_index: keep latest pass when collisions exist
	seen_frames = {}
	for seed in usable_seeds_sorted:
		fi = int(seed["frame_index"])
		if fi in seen_frames:
			existing = seen_frames[fi]
			# keep the seed from the latest pass
			if int(seed["pass"]) >= int(existing["pass"]):
				print(f"  WARNING: duplicate seed at frame {fi}, "
					f"keeping pass {seed['pass']} over pass {existing['pass']}")
				seen_frames[fi] = seed
			else:
				print(f"  WARNING: duplicate seed at frame {fi}, "
					f"keeping pass {existing['pass']} over pass {seed['pass']}")
		else:
			seen_frames[fi] = seed
	if len(seen_frames) < len(usable_seeds_sorted):
		dropped = len(usable_seeds_sorted) - len(seen_frames)
		print(f"  deduplicated {dropped} seeds with duplicate frame_index values")
		usable_seeds_sorted = sorted(seen_frames.values(), key=lambda s: int(s["frame_index"]))

	# build appearance model from the first visible seed
	# prefer visible seeds over partial (partial has unreliable appearance)
	visible_only = [s for s in usable_seeds_sorted if s["status"] == "visible"]
	if visible_only:
		first_seed = visible_only[0]
	else:
		# fallback to partial if no visible seeds exist
		first_seed = usable_seeds_sorted[0]
	first_frame = reader.read_frame(int(first_seed["frame_index"]))
	if first_frame is None:
		raise RuntimeError(
			f"Cannot read seed frame {first_seed['frame_index']} for appearance model"
		)

	# construct a temporary bbox dict for build_appearance_model
	seed_bbox = {
		"cx": float(first_seed["cx"]),
		"cy": float(first_seed["cy"]),
		"w": float(first_seed["w"]),
		"h": float(first_seed["h"]),
	}
	appearance_model = propagator.build_appearance_model(first_frame, seed_bbox)

	total_intervals = len(usable_seeds_sorted) - 1
	interval_results = []
	t_start = time.time()

	# build all interval pairs and compute fingerprints for reuse lookup
	all_pairs = []
	all_fingerprints = []
	for pair_idx in range(total_intervals):
		s_start = usable_seeds_sorted[pair_idx]
		s_end = usable_seeds_sorted[pair_idx + 1]
		all_pairs.append((s_start, s_end))
		fp = state_io.interval_fingerprint(s_start, s_end)
		all_fingerprints.append(fp)

	# separate prior results from intervals that need solving
	prior_results = [None] * total_intervals
	new_indices = []
	reused_count = 0
	if prior_intervals:
		for pair_idx in range(total_intervals):
			fp = all_fingerprints[pair_idx]
			if fp in prior_intervals:
				prior_results[pair_idx] = prior_intervals[fp]
				reused_count += 1
			else:
				new_indices.append(pair_idx)
	else:
		new_indices = list(range(total_intervals))

	if reused_count > 0:
		print(f"  {reused_count}/{total_intervals} intervals reused from prior solve")
		# print prior interval results
		for pair_idx in range(total_intervals):
			if prior_results[pair_idx] is not None:
				result = prior_results[pair_idx]
				line = _format_interval_result(result, fps)
				print(f"{line}  [PRIOR]")
				if on_interval_complete is not None:
					on_interval_complete(result)

	# helper to persist a newly solved interval to disk
	def _persist_and_notify(pair_idx: int, result: dict) -> None:
		"""Store a saveable subset of the result and call on_interval_solved."""
		if on_interval_solved is not None:
			# keep forward/backward tracks so refinement GUI can show FWD/BWD prediction boxes
			saveable = {
				"start_frame": result["start_frame"],
				"end_frame": result["end_frame"],
				"fused_track": result["fused_track"],
				"forward_track": result["forward_track"],
				"backward_track": result["backward_track"],
				"interval_score": result["interval_score"],
				"identity_scores": result["identity_scores"],
				"competitor_margins": result["competitor_margins"],
			}
			fp = all_fingerprints[pair_idx]
			on_interval_solved(fp, saveable)

	new_count = len(new_indices)

	# parallel solving path: only new intervals dispatched to the pool
	if num_workers > 1 and new_count > 1:
		# get video_path from reader for spawning worker readers
		video_path = reader.video_path
		# cap actual workers to new interval count
		actual_workers = min(num_workers, new_count)
		print(f"  solving {new_count} intervals ({actual_workers} workers)...")
		# create shared frame counter for cross-worker progress
		frame_counter = multiprocessing.Value("i", 0)
		# map futures to their original pair index for ordered stitching
		future_to_pair_idx = {}
		with concurrent.futures.ProcessPoolExecutor(
			max_workers=actual_workers,
			initializer=_init_worker,
			initargs=(frame_counter,),
		) as pool:
			for w_idx, ui in enumerate(new_indices):
				s_start, s_end = all_pairs[ui]
				future = pool.submit(
					_solve_interval_worker,
					video_path, s_start, s_end,
					appearance_model, config, w_idx,
				)
				future_to_pair_idx[future] = ui
			# track progress by intervals completed (not frames)
			# frame-level tracking has off-by-one issues with 1-frame intervals
			# because propagator includes both endpoints
			parallel_results = {}
			collected = set()
			done_count = 0
			with rich.progress.Progress(
				rich.progress.TextColumn("{task.description}"),
				rich.progress.BarColumn(),
				rich.progress.TaskProgressColumn(),
				rich.progress.TimeRemainingColumn(),
			) as progress:
				interval_task = progress.add_task(
					"  intervals solved", total=new_count,
				)
				last_wall_print = time.time()
				try:
					while done_count < new_count:
						# check for newly completed futures (non-blocking)
						for future in list(future_to_pair_idx):
							if future.done() and future not in collected:
								collected.add(future)
								pair_idx = future_to_pair_idx[future]
								result = future.result()
								parallel_results[pair_idx] = result
								done_count += 1
								# persist to disk
								_persist_and_notify(pair_idx, result)
								# print interval result
								_print_interval_result_rich(result, fps, progress)
								if on_interval_complete is not None:
									on_interval_complete(result)
								if debug:
									elapsed = time.time() - t_start
									n_frames = result["end_frame"] - result["start_frame"]
									progress.console.print(
										f"    interval {result['start_frame']}-"
										f"{result['end_frame']} done "
										f"({n_frames} frames, {elapsed:.1f}s wall)"
									)
								# update interval-level progress bar
								progress.update(
									interval_task, completed=done_count,
								)
						# print wall time and throughput every 30 seconds
						now = time.time()
						if now - last_wall_print >= 30.0:
							elapsed = now - t_start
							current_frames = frame_counter.value
							fps_rate = current_frames / max(0.1, elapsed)
							progress.console.print(
								f"  wall time {elapsed:.0f}s  "
								f"intervals={done_count}/{new_count}  "
								f"frames={current_frames}  "
								f"({fps_rate:.1f} frames/s)"
							)
							last_wall_print = now
						# brief sleep to avoid busy-waiting
						time.sleep(0.2)
				except KeyboardInterrupt:
					# cancel pending futures and kill workers immediately
					print("\n  interrupted: cancelling workers...", flush=True)
					for future in future_to_pair_idx:
						future.cancel()
					pool.shutdown(wait=False, cancel_futures=True)
					raise
				# all futures collected: set progress to 100%
				progress.update(
					interval_task, completed=new_count,
				)
		# merge prior and newly solved results in original order
		for pair_idx in range(total_intervals):
			if prior_results[pair_idx] is not None:
				interval_results.append(prior_results[pair_idx])
			else:
				interval_results.append(parallel_results[pair_idx])
	elif new_count > 0:
		# sequential solving path with rich progress bar
		with rich.progress.Progress(
			rich.progress.TextColumn("{task.description}"),
			rich.progress.BarColumn(),
			rich.progress.TaskProgressColumn(),
			rich.progress.TimeRemainingColumn(),
		) as progress:
			task = progress.add_task(
				"  solving intervals", total=new_count,
			)
			for ui in new_indices:
				seed_start, seed_end = all_pairs[ui]

				start_frame = int(seed_start["frame_index"])
				end_frame = int(seed_end["frame_index"])

				progress.console.print(
					f"  solving interval {ui + 1}/{total_intervals} "
					f"(frames {start_frame}-{end_frame})"
				)

				result = solve_interval(
					reader, seed_start, seed_end, detector, appearance_model,
					show_progress=debug, debug=debug,
				)
				prior_results[ui] = result
				# persist to disk
				_persist_and_notify(ui, result)
				_print_interval_result_rich(result, fps, progress)
				if on_interval_complete is not None:
					on_interval_complete(result)
				progress.update(task, advance=1)
		# merge all results in original order
		for pair_idx in range(total_intervals):
			interval_results.append(prior_results[pair_idx])
	else:
		# all intervals reused from prior solve, no new solving needed
		for pair_idx in range(total_intervals):
			interval_results.append(prior_results[pair_idx])

	# stitch all intervals into full trajectory
	trajectory = stitch_trajectories(interval_results)

	# apply multi-seed anchored interpolation to reduce drift
	trajectory = anchor_to_seeds(trajectory, seeds)

	# stamp seed confidence onto trajectory at seed frames
	# must happen before erasure so approx seeds get correct conf first
	trajectory = _stamp_seed_confidence(trajectory, seeds)

	# erase trajectory near absence seeds (function decides which seeds to erase)
	trajectory = _apply_trajectory_erasure(trajectory, seeds, fps)

	output = {
		"intervals": interval_results,
		"trajectory": trajectory,
	}
	return output
