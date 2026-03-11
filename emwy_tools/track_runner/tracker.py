"""Bidirectional tracking loop for track_runner.

Orchestrates Kalman prediction, YOLO detection, candidate scoring,
and crop control. Detection runs once; Kalman runs forward and backward
from seeds; per-frame results are merged by confidence.
"""

# Standard Library
import concurrent.futures

# PIP3 modules
import cv2

# local repo modules
import kalman
import scoring
import crop
import detection

# confidence decay factor when no detection matches
CONFIDENCE_DECAY = 0.95
# minimum confidence floor to prevent crop from going haywire
CONFIDENCE_FLOOR = 0.1


#============================================
def _bbox_topleft_to_center(bbox: list) -> tuple:
	"""Convert a top-left bounding box to center format.

	Args:
		bbox: List of [x, y, w, h] where x,y is the top-left corner.

	Returns:
		Tuple of (cx, cy, w, h) in center format.
	"""
	x, y, w, h = bbox
	cx = x + w / 2.0
	cy = y + h / 2.0
	result = (cx, cy, w, h)
	return result


#============================================
def _build_seed_lookup(seeds: list) -> dict:
	"""Build a dict mapping frame_index to seed for quick lookup.

	Args:
		seeds: List of seed dicts with frame_index key.

	Returns:
		Dict mapping frame_index (int) to seed dict.
	"""
	lookup = {}
	for seed in seeds:
		fi = int(seed["frame_index"])
		lookup[fi] = seed
	return lookup


#============================================
def _reinit_kalman_from_seed(seed: dict) -> dict:
	"""Create a fresh Kalman state from a seed's full_person_box.

	Args:
		seed: Seed dict with full_person_box key (cx, cy, w, h).

	Returns:
		New Kalman state dict.
	"""
	bbox = tuple(seed["full_person_box"])
	kf_state = kalman.create_kalman(bbox)
	return kf_state


#============================================
def _detection_worker(
	video_path: str, start_frame: int, end_frame: int,
	config: dict, detect_interval: int,
) -> tuple:
	"""Process a chunk of frames for detection in a worker process.

	Each worker creates its own VideoCapture and detector instance
	so there is no shared mutable state across processes.

	Args:
		video_path: Path to the input video file.
		start_frame: First frame index to process (inclusive).
		end_frame: Last frame index to process (exclusive).
		config: Project configuration dict for creating detector.
		detect_interval: Run detection every N frames.

	Returns:
		Tuple of (start_frame, detections_list) where detections_list
		contains one detection list per frame in [start_frame, end_frame).
	"""
	# each worker creates its own detector and video capture
	det = detection.create_detector(config)
	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		raise RuntimeError(f"Worker cannot open video: {video_path}")
	# seek to start frame
	cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
	chunk_size = end_frame - start_frame
	report_interval = max(1, chunk_size // 5)
	detections_list = []
	for i in range(chunk_size):
		ret, frame = cap.read()
		if not ret:
			# pad remaining frames with empty detections
			detections_list.append([])
			continue
		frame_idx = start_frame + i
		if frame_idx % detect_interval == 0:
			dets = det.detect(frame)
		else:
			dets = []
		detections_list.append(dets)
		if i % report_interval == 0 and i > 0:
			pct = 100.0 * i / chunk_size
			print(
				f"  worker [{start_frame}-{end_frame}]: "
				f"{i}/{chunk_size} ({pct:.0f}%)"
			)
	cap.release()
	result = (start_frame, detections_list)
	return result


#============================================
def _run_detection_pass(
	video_path: str, total_frames: int, detector: object,
	detect_interval: int, num_workers: int = 1,
) -> list:
	"""Read the video once and cache per-frame detections.

	When num_workers > 1, splits the frame range across multiple
	worker processes, each with its own VideoCapture and detector.

	Args:
		video_path: Path to the input video file.
		total_frames: Expected number of frames.
		detector: Person detector with a detect(frame) method.
		detect_interval: Run detection every N frames.
		num_workers: Number of parallel detection workers.

	Returns:
		List of detection lists, one per frame. Frames where
		detection did not run get an empty list.
	"""
	if num_workers <= 1:
		# sequential path: use existing detector directly
		return _run_detection_pass_sequential(
			video_path, total_frames, detector, detect_interval,
		)
	# parallel path: split frame range across workers
	# build config dict from the detector for worker processes
	# (detector object cannot be pickled, workers create their own)
	# we need the config to create detectors in workers
	print(f"  using {num_workers} detection workers")
	# compute chunk boundaries
	chunk_size = total_frames // num_workers
	chunks = []
	for i in range(num_workers):
		start = i * chunk_size
		# last worker gets remaining frames
		end = (i + 1) * chunk_size if i < num_workers - 1 else total_frames
		chunks.append((start, end))
	# launch workers with ProcessPoolExecutor
	# pass the config stored on the detector for worker detector creation
	det_config = getattr(detector, "_config", None)
	if det_config is None:
		# fallback: build a minimal config that create_detector can use
		det_config = {"settings": {"detection": {"kind": "hog"}}}
	futures = []
	with concurrent.futures.ProcessPoolExecutor(
		max_workers=num_workers
	) as executor:
		for start, end in chunks:
			future = executor.submit(
				_detection_worker,
				video_path, start, end, det_config, detect_interval,
			)
			futures.append(future)
		# gather results in order
		results_by_start = {}
		for future in concurrent.futures.as_completed(futures):
			start_frame, dets_list = future.result()
			results_by_start[start_frame] = dets_list
	# concatenate in frame order
	all_detections = []
	for start, end in chunks:
		all_detections.extend(results_by_start[start])
	print(f"  detection pass complete: {len(all_detections)} frames")
	return all_detections


#============================================
def _run_detection_pass_sequential(
	video_path: str, total_frames: int, detector: object,
	detect_interval: int,
) -> list:
	"""Sequential single-process detection pass.

	Args:
		video_path: Path to the input video file.
		total_frames: Expected number of frames.
		detector: Person detector with a detect(frame) method.
		detect_interval: Run detection every N frames.

	Returns:
		List of detection lists, one per frame.
	"""
	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		raise RuntimeError(f"Cannot open video: {video_path}")
	report_interval = max(1, total_frames // 10)
	all_detections = []
	for frame_idx in range(total_frames):
		ret, frame = cap.read()
		if not ret:
			break
		if frame_idx % detect_interval == 0:
			dets = detector.detect(frame)
		else:
			dets = []
		all_detections.append(dets)
		if frame_idx % report_interval == 0 and frame_idx > 0:
			pct = 100.0 * frame_idx / total_frames
			print(f"  detecting: {frame_idx}/{total_frames} ({pct:.0f}%)")
	cap.release()
	print(f"  detection pass complete: {len(all_detections)} frames")
	return all_detections


#============================================
def _run_kalman_pass(
	all_detections: list,
	seeds: list,
	config: dict,
	total_frames: int,
	direction: str,
) -> list:
	"""Run a single-direction Kalman tracking pass.

	Uses cached detections so no video I/O is needed.

	Args:
		all_detections: Per-frame detection lists from _run_detection_pass.
		seeds: List of seed dicts sorted by frame_index.
		config: Project configuration dict.
		total_frames: Total number of frames.
		direction: "forward" or "backward".

	Returns:
		List of per-frame state dicts indexed by frame_index.
		Each has keys: frame_index, source, confidence, bbox.
	"""
	settings = config.get("settings", {})
	tracking_cfg = settings.get("tracking", {})
	max_vy_fraction = float(tracking_cfg.get("max_vy_fraction", 0.03))
	velocity_freeze_streak = int(tracking_cfg.get("velocity_freeze_streak", 3))

	# build seed lookup
	seed_lookup = _build_seed_lookup(seeds)

	# filter to visible seeds for appearance and init selection
	visible_seeds = [
		s for s in seeds if s.get("status", "visible") == "visible"
	]
	if not visible_seeds:
		raise RuntimeError(
			"no visible seeds found; need at least one seed "
			"with a drawn bounding box"
		)

	# build appearance dict from first visible seed for scoring
	appearance_seed = visible_seeds[0]
	appearance = {
		"jersey_hsv": appearance_seed.get("jersey_hsv"),
		"color_histogram": appearance_seed.get("color_histogram"),
	}

	# determine frame iteration order and which seed to init from
	if direction == "forward":
		frame_order = list(range(total_frames))
		init_seed = visible_seeds[0]
	else:
		frame_order = list(range(total_frames - 1, -1, -1))
		init_seed = visible_seeds[-1]

	# initialize Kalman from the starting seed
	kf_state = _reinit_kalman_from_seed(init_seed)

	# pre-allocate results indexed by frame_index
	results = [None] * total_frames
	confidence = 1.0
	missed_streak = 0
	report_interval = max(1, total_frames // 20)
	frames_processed = 0

	for frame_idx in frame_order:
		# re-initialize Kalman at seed frames
		if frame_idx in seed_lookup:
			seed = seed_lookup[frame_idx]
			seed_status = seed.get("status", "visible")
			if seed_status == "not_in_frame":
				# runner is gone; drop confidence, bump missed streak
				confidence = CONFIDENCE_FLOOR
				missed_streak = velocity_freeze_streak + 1
				tracked_bbox = kalman.get_bbox(kf_state)
				results[frame_idx] = {
					"frame_index": frame_idx,
					"source": "absent",
					"confidence": confidence,
					"bbox": tracked_bbox,
				}
				continue
			elif seed_status == "obstructed":
				# runner is roughly there but hidden; keep predicting
				missed_streak = max(missed_streak, 2)
			elif seed is not init_seed:
				# visible seed: reinit Kalman as before
				kf_state = _reinit_kalman_from_seed(seed)
				confidence = 1.0
				missed_streak = 0

		# predict Kalman state
		kf_state = kalman.predict(kf_state)

		# clamp vertical velocity to prevent upward drift
		pred_h_for_cap = kalman.get_bbox(kf_state)[3]
		max_vy = max(1.0, pred_h_for_cap * max_vy_fraction)
		vy = float(kf_state["x"][5])
		if abs(vy) > max_vy:
			kf_state["x"][5] = max_vy if vy > 0 else -max_vy

		# clamp size velocity to prevent runaway bbox growth
		max_v_log_h = float(tracking_cfg.get("max_v_log_h", 0.05))
		v_log_h = float(kf_state["x"][6])
		if abs(v_log_h) > max_v_log_h:
			kf_state["x"][6] = max_v_log_h if v_log_h > 0 else -max_v_log_h

		# freeze velocity after consecutive missed detections
		if missed_streak > velocity_freeze_streak:
			kf_state["x"][4] = 0.0  # zero vx
			kf_state["x"][5] = 0.0  # zero vy
			kf_state["x"][6] = 0.0  # zero v_log_h

		# try to match cached detections
		source = "predicted"
		detections = all_detections[frame_idx]
		if len(detections) > 0:
			# apply hard gates
			gated = scoring.apply_hard_gates(
				detections, kf_state, config,
				missed_streak=missed_streak,
			)
			if len(gated) > 0:
				scored = scoring.score_candidates(
					gated, kf_state, appearance, config
				)
				best = scoring.select_best(scored)
				if best is not None:
					det_bbox = _bbox_topleft_to_center(best["bbox"])
					meas = kalman.measurement_from_bbox(det_bbox)
					kf_state = kalman.update(kf_state, meas)
					confidence = best["score"]
					source = "detected"
					missed_streak = 0

		# decay confidence when no detection matched
		if source == "predicted":
			missed_streak += 1
			confidence = max(CONFIDENCE_FLOOR, confidence * CONFIDENCE_DECAY)

		tracked_bbox = kalman.get_bbox(kf_state)

		results[frame_idx] = {
			"frame_index": frame_idx,
			"source": source,
			"confidence": confidence,
			"bbox": tracked_bbox,
		}

		# progress reporting
		frames_processed += 1
		if frames_processed % report_interval == 0:
			pct = 100.0 * frames_processed / total_frames
			print(
				f"  {direction}: {frames_processed}/{total_frames} "
				f"({pct:.0f}%) conf={confidence:.2f} "
				f"streak={missed_streak}"
			)

	return results


#============================================
def _merge_passes(forward: list, backward: list) -> list:
	"""Merge forward and backward tracking passes by confidence.

	For each frame, picks the result with higher confidence.

	Args:
		forward: Per-frame state dicts from forward pass.
		backward: Per-frame state dicts from backward pass.

	Returns:
		Merged list of per-frame state dicts.
	"""
	merged = []
	fwd_wins = 0
	bwd_wins = 0
	for idx in range(len(forward)):
		fwd = forward[idx]
		bwd = backward[idx]
		if fwd is None and bwd is None:
			# should not happen, but handle gracefully
			merged.append(None)
			continue
		if fwd is None:
			merged.append(bwd)
			bwd_wins += 1
			continue
		if bwd is None:
			merged.append(fwd)
			fwd_wins += 1
			continue
		# pick the one with higher confidence
		if fwd["confidence"] >= bwd["confidence"]:
			# tag the source to show it came from forward pass
			fwd["pass"] = "forward"
			merged.append(fwd)
			fwd_wins += 1
		else:
			bwd["pass"] = "backward"
			merged.append(bwd)
			bwd_wins += 1
	print(f"  merge: forward won {fwd_wins}, backward won {bwd_wins}")
	return merged


#============================================
def _interpolate_predicted_gaps(merged: list) -> list:
	"""Linearly interpolate bbox through predicted-only stretches.

	When the tracker loses detection for a stretch of frames, both
	forward and backward passes produce decaying predictions that
	freeze in place. This function finds those gaps and replaces them
	with smooth linear interpolation between the last detected frame
	before the gap and the first detected frame after the gap.

	Args:
		merged: List of per-frame state dicts from _merge_passes.

	Returns:
		Same list, with predicted-gap bboxes replaced by interpolated values.
	"""
	total = len(merged)
	# minimum gap length to trigger interpolation (very short gaps
	# are handled well enough by Kalman prediction)
	min_gap = 3
	gaps_filled = 0
	frames_interpolated = 0

	idx = 0
	while idx < total:
		state = merged[idx]
		# skip detected frames and None frames
		if state is None or state["source"] == "detected":
			idx += 1
			continue

		# found start of a predicted/absent gap; find its extent
		gap_start = idx
		while idx < total and merged[idx] is not None and merged[idx]["source"] in ("predicted", "absent"):
			idx += 1
		gap_end = idx  # exclusive; first frame that is detected or None

		gap_length = gap_end - gap_start
		if gap_length < min_gap:
			continue

		# skip interpolation if any frame in the gap is marked absent
		has_absent = False
		for scan in range(gap_start, gap_end):
			if merged[scan] is not None and merged[scan]["source"] == "absent":
				has_absent = True
				break
		if has_absent:
			continue

		# find anchor A: last detected frame before the gap
		anchor_a = None
		for scan in range(gap_start - 1, -1, -1):
			if merged[scan] is not None and merged[scan]["source"] == "detected":
				anchor_a = merged[scan]
				break

		# find anchor B: first detected frame after the gap
		anchor_b = None
		for scan in range(gap_end, total):
			if merged[scan] is not None and merged[scan]["source"] == "detected":
				anchor_b = merged[scan]
				break

		# need both anchors for interpolation
		if anchor_a is None or anchor_b is None:
			continue

		# linearly interpolate bbox (cx, cy, w, h) through the gap
		a_bbox = anchor_a["bbox"]
		b_bbox = anchor_b["bbox"]
		for gi in range(gap_length):
			# t goes from just-past-0 to just-before-1
			t = (gi + 1) / (gap_length + 1)
			interp_bbox = tuple(
				a_bbox[c] + t * (b_bbox[c] - a_bbox[c])
				for c in range(4)
			)
			frame_idx = gap_start + gi
			merged[frame_idx]["bbox"] = interp_bbox
			merged[frame_idx]["source"] = "interpolated"
			# interpolated confidence ramps: low in middle, higher near anchors
			# use minimum of distance-to-each-anchor confidence
			conf_a = anchor_a["confidence"] * (1.0 - t)
			conf_b = anchor_b["confidence"] * t
			merged[frame_idx]["confidence"] = conf_a + conf_b

		gaps_filled += 1
		frames_interpolated += gap_length

	if gaps_filled > 0:
		print(
			f"  interpolation: {gaps_filled} gaps, "
			f"{frames_interpolated} frames smoothed"
		)
	else:
		print("  interpolation: no gaps needed smoothing")
	return merged


#============================================
def find_jerk_regions(
	frame_states: list,
	config: dict | None = None,
	min_streak: int = 3,
	max_targets: int = 24,
) -> list:
	"""Detect sudden bbox jumps between consecutive detected frames.

	A large displacement between two detected frames (relative to person
	height and frame gap) suggests the tracker locked onto a different
	person. These jerk regions are flagged for --add-seeds review.

	Args:
		frame_states: List of per-frame state dicts from the tracker.
		config: Optional project config dict for jerk_threshold.
		min_streak: Jerk frames within this distance are grouped.
		max_targets: Maximum number of regions to return.

	Returns:
		List of (start_frame, length) tuples sorted by length descending.
	"""
	# read jerk threshold from config
	jerk_threshold = 0.3
	if config is not None:
		tracking_cfg = config.get("settings", {}).get("tracking", {})
		jerk_threshold = float(tracking_cfg.get("jerk_threshold", 0.3))

	# walk frame_states and find jerk frames
	jerk_frames = []
	prev_detected = None
	prev_detected_idx = None
	for state in frame_states:
		if state is None:
			continue
		if state["source"] != "detected":
			continue
		if prev_detected is not None:
			# compute center displacement
			cx, cy = state["bbox"][0], state["bbox"][1]
			pcx, pcy = prev_detected["bbox"][0], prev_detected["bbox"][1]
			displacement = ((cx - pcx) ** 2 + (cy - pcy) ** 2) ** 0.5
			# person height from current frame
			person_height = max(1.0, state["bbox"][3])
			# frame gap between consecutive detections
			frame_gap = max(1, state["frame_index"] - prev_detected_idx)
			# normalize by height and gap
			relative_jerk = displacement / (person_height * frame_gap)
			if relative_jerk > jerk_threshold:
				jerk_frames.append(state["frame_index"])
		prev_detected = state
		prev_detected_idx = state["frame_index"]

	if not jerk_frames:
		return []

	# group jerk frames within min_streak of each other into regions
	regions = []
	region_start = jerk_frames[0]
	region_end = jerk_frames[0]
	for fi in jerk_frames[1:]:
		if fi - region_end <= min_streak:
			region_end = fi
		else:
			# close current region
			length = region_end - region_start + 1
			regions.append((region_start, length))
			region_start = fi
			region_end = fi
	# close final region
	length = region_end - region_start + 1
	regions.append((region_start, length))

	# sort by length descending, cap at max_targets
	regions.sort(key=lambda x: x[1], reverse=True)
	return regions[:max_targets]


#============================================
def run_tracker(
	video_path: str,
	seeds: list,
	config: dict,
	detector: object,
	video_info: dict,
	duration: float,
	num_workers: int = 1,
) -> tuple:
	"""Run bidirectional tracking over the video.

	Detections are cached in a single video read. Then Kalman
	tracking runs forward and backward from seeds. Per-frame
	results are merged by confidence and fed to the crop controller.

	Args:
		video_path: Path to the input video file.
		seeds: List of seed dicts from seeding module.
		config: Project configuration dict.
		detector: Person detector with a detect(frame) method.
		video_info: Dict with keys: width, height, fps, frame_count.
		duration: Video duration in seconds.
		num_workers: Number of parallel workers for detection pass.

	Returns:
		Tuple of (crop_rects, frame_states, forward_states, backward_states):
			crop_rects: list of (x, y, w, h) tuples, one per frame
			frame_states: list of per-frame state dicts
			forward_states: list of per-frame state dicts from forward pass
			backward_states: list of per-frame state dicts from backward pass
	"""
	settings = config.get("settings", {})
	detect_cfg = settings.get("detection", {})
	detect_interval = int(detect_cfg.get("detect_interval", 1))

	frame_width = video_info["width"]
	frame_height = video_info["height"]
	total_frames = video_info["frame_count"]

	# store frame dimensions in config so scoring gates can use them
	config["frame_width"] = frame_width
	config["frame_height"] = frame_height

	# sort seeds by frame index
	sorted_seeds = sorted(seeds, key=lambda s: int(s["frame_index"]))

	# phase 1: run detection once, cache all results
	if num_workers > 1:
		print(f"  phase 1: detection pass ({num_workers} workers)...")
	else:
		print("  phase 1: detection pass...")
	all_detections = _run_detection_pass(
		video_path, total_frames, detector, detect_interval,
		num_workers=num_workers,
	)

	# phase 2+3: forward and backward Kalman passes (parallel)
	if num_workers > 1:
		print("  phase 2+3: bidirectional tracking (parallel)...")
		with concurrent.futures.ThreadPoolExecutor(
			max_workers=2
		) as executor:
			fwd_future = executor.submit(
				_run_kalman_pass,
				all_detections, sorted_seeds, config,
				total_frames, "forward",
			)
			bwd_future = executor.submit(
				_run_kalman_pass,
				all_detections, sorted_seeds, config,
				total_frames, "backward",
			)
			forward_states = fwd_future.result()
			backward_states = bwd_future.result()
	else:
		# sequential path
		print("  phase 2: forward tracking pass...")
		forward_states = _run_kalman_pass(
			all_detections, sorted_seeds, config, total_frames, "forward",
		)
		print("  phase 3: backward tracking pass...")
		backward_states = _run_kalman_pass(
			all_detections, sorted_seeds, config, total_frames, "backward",
		)

	# phase 4: merge by confidence
	print("  phase 4: merging passes...")
	merged_states = _merge_passes(forward_states, backward_states)

	# phase 5: interpolate through predicted gaps for smooth transitions
	print("  phase 5: interpolating gaps...")
	merged_states = _interpolate_predicted_gaps(merged_states)

	# phase 6: compute crop rects from merged tracking
	crop_ctrl = crop.create_crop_controller(config, frame_width, frame_height)
	frame_size = (frame_width, frame_height)
	crop_rects = []
	for state in merged_states:
		if state is None:
			# fallback: center crop
			crop_rect = crop_ctrl.update(
				(frame_width / 2, frame_height / 2, 100, 200),
				CONFIDENCE_FLOOR, frame_size,
			)
		else:
			crop_rect = crop_ctrl.update(
				state["bbox"], state["confidence"], frame_size,
			)
		crop_rects.append(crop_rect)
		# store crop_rect back into state for diagnostics
		if state is not None:
			state["crop_rect"] = crop_rect

	result = (crop_rects, merged_states, forward_states, backward_states)
	return result
