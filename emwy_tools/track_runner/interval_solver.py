"""Per-interval bounded solving with cyclical prior injection for track_runner.

Splits the video timeline into seed-to-seed intervals, solves each interval
using forward/backward propagation and competitor hypothesis tracking, and
stitches results into a full trajectory.
"""

# Standard Library
import math

# PIP3 modules
import numpy

# local repo modules
import propagator
import hypothesis
import scoring


#============================================
# Agreement tolerance: forward/backward centers within this fraction
# of torso height are considered "agreeing"
AGREE_CENTER_FRACTION = 0.3
# Scale agreement tolerance: height ratio difference
AGREE_SCALE_FRACTION = 0.15
# Minimum number of frames for cyclical prior detection
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
		fwd_conf = float(fwd.get("conf", 0.1))

		bwd_cx = float(bwd["cx"])
		bwd_cy = float(bwd["cy"])
		bwd_h = float(bwd["h"])
		bwd_conf = float(bwd.get("conf", 0.1))

		# use mean height as tolerance reference
		mean_h = max(1.0, (fwd_h + bwd_h) / 2.0)

		# center distance normalized by mean height
		center_dist = math.sqrt(
			(fwd_cx - bwd_cx) ** 2 + (fwd_cy - bwd_cy) ** 2
		) / mean_h

		# scale difference as fraction of mean
		scale_diff = abs(fwd_h - bwd_h) / mean_h

		agree = (
			center_dist <= AGREE_CENTER_FRACTION
			and scale_diff <= AGREE_SCALE_FRACTION
		)

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
			merged_conf = max(fwd_conf, bwd_conf)

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
def solve_interval(
	reader: object,
	seed_start: dict,
	seed_end: dict,
	detector: object,
	appearance_model: dict,
	cyclical_prior: dict | None = None,
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
		cyclical_prior: Optional dict with period estimate from _detect_cyclical_prior().
			Currently reserved for future use; not yet applied.

	Returns:
		Dict with keys: start_frame, end_frame, fused_track, forward_track,
		backward_track, interval_score, identity_scores, competitor_margins.
	"""
	start_frame = int(seed_start["frame_index"])
	end_frame = int(seed_end["frame_index"])

	# build start and end propagator states from seeds
	start_state = propagator.make_seed_state(
		cx=float(seed_start["cx"]),
		cy=float(seed_start["cy"]),
		w=float(seed_start["w"]),
		h=float(seed_start["h"]),
		conf=float(seed_start.get("conf", 1.0)),
	)
	end_state = propagator.make_seed_state(
		cx=float(seed_end["cx"]),
		cy=float(seed_end["cy"]),
		w=float(seed_end["w"]),
		h=float(seed_end["h"]),
		conf=float(seed_end.get("conf", 1.0)),
	)

	# propagate forward from start to end
	forward_track = propagator.propagate_forward(
		reader, start_frame, start_state, end_frame, appearance_model,
	)

	# propagate backward from end to start; result is [end_frame..start_frame]
	backward_raw = propagator.propagate_backward(
		reader, end_frame, end_state, start_frame, appearance_model,
	)
	# backward_raw index 0 = start_frame (earliest), last = end_frame
	# align length with forward_track
	n = min(len(forward_track), len(backward_raw))
	forward_track = forward_track[:n]
	backward_aligned = backward_raw[:n]

	# compute per-frame identity scores and competitor margins
	identity_scores = []
	competitor_margins = []
	competitors = []

	for i in range(n):
		frame_idx = start_frame + i
		frame = reader.read_frame(frame_idx)
		if frame is None:
			identity_scores.append(0.5)
			competitor_margins.append(0.5)
			continue

		# use forward state as the target for this frame
		target = forward_track[i]

		# run detector to get new detections
		detections = detector.detect(frame) if detector is not None else []

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

	# fuse forward and backward tracks
	fused_track = fuse_tracks(forward_track, backward_aligned)

	# score the interval using the scoring module
	interval_score = scoring.score_interval(
		forward_track,
		backward_aligned,
		identity_scores,
		competitor_margins,
	)

	result = {
		"start_frame": start_frame,
		"end_frame": end_frame,
		"fused_track": fused_track,
		"forward_track": forward_track,
		"backward_track": backward_aligned,
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
def solve_all_intervals(
	reader: object,
	seeds: list,
	detector: object,
	config: dict,
) -> dict:
	"""Solve all seed-to-seed intervals and stitch into a full trajectory.

	Splits the seed list into consecutive pairs, solves each interval,
	stitches results, and returns a diagnostics-format dict with per-interval
	scoring and the full trajectory.

	Console output is emitted for each interval in the format:
		interval  150- 450 (10.0s)  agree=0.92  margin=0.71  identity=0.88  [TRUST]

	Args:
		reader: VideoReader with read_frame() and get_info() methods.
		seeds: List of seed dicts sorted by frame_index. Each seed must have
			cx, cy, w, h, frame_index keys. Non-visible seeds are skipped.
		detector: Person detector with a detect(frame) method.
		config: Project configuration dict (currently unused; reserved).

	Returns:
		Dict with keys:
			- "intervals": list of interval result dicts
			- "trajectory": full frame-by-frame tracking state list
			- "cyclical_prior": optional prior dict or None
	"""
	info = reader.get_info()
	fps = float(info.get("fps", 30.0))

	# filter to visible seeds only
	visible_seeds = [
		s for s in seeds
		if s.get("status", "visible") == "visible"
	]

	if len(visible_seeds) < 2:
		print("  interval_solver: need at least 2 visible seeds to solve intervals")
		return {"intervals": [], "trajectory": [], "cyclical_prior": None}

	# sort by frame_index to ensure consecutive pairs are correct
	visible_seeds_sorted = sorted(visible_seeds, key=lambda s: int(s["frame_index"]))

	# build appearance model from the first visible seed
	first_seed = visible_seeds_sorted[0]
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

	interval_results = []
	cyclical_prior = None

	for pair_idx in range(len(visible_seeds_sorted) - 1):
		seed_start = visible_seeds_sorted[pair_idx]
		seed_end = visible_seeds_sorted[pair_idx + 1]

		start_frame = int(seed_start["frame_index"])
		end_frame = int(seed_end["frame_index"])
		duration_s = (end_frame - start_frame) / fps

		# detect cyclical prior from trajectory built so far
		if interval_results and cyclical_prior is None:
			partial_trajectory = stitch_trajectories(interval_results)
			cyclical_prior = _detect_cyclical_prior(partial_trajectory, fps)
			if cyclical_prior is not None:
				print(
					f"  cyclical prior detected: "
					f"period={cyclical_prior['period_s']:.1f}s "
					f"(corr={cyclical_prior['correlation']:.2f})"
				)

		result = solve_interval(
			reader, seed_start, seed_end, detector, appearance_model, cyclical_prior,
		)
		interval_results.append(result)

		# extract scores for console output
		score = result["interval_score"]
		agree = score["agreement_score"]
		margin = score["competitor_margin"]
		identity = score["identity_score"]
		confidence = score["confidence"]
		reasons = score["failure_reasons"]

		# format label: TRUST or WEAK with reason list
		if confidence == "high":
			label = "[TRUST]"
		else:
			reason_str = ", ".join(reasons) if reasons else "low_confidence"
			label = f"[WEAK: {reason_str}]"

		print(
			f"  interval {start_frame:5d}-{end_frame:5d} "
			f"({duration_s:.1f}s)  "
			f"agree={agree:.2f}  "
			f"margin={margin:.2f}  "
			f"identity={identity:.2f}  "
			f"{label}"
		)

	# stitch all intervals into full trajectory
	trajectory = stitch_trajectories(interval_results)

	output = {
		"intervals": interval_results,
		"trajectory": trajectory,
		"cyclical_prior": cyclical_prior,
	}
	return output
