"""Pre-encode crop-path stability analysis for track_runner.

Computes motion-stability metrics from crop rects and trajectory data
to diagnose visible instability (jitter, drift, zoom pumping) before
encoding. Also extracts solver-quality context from interval results.

The analysis is diagnostic: it tells you where problems live and what
kind they are. It does not auto-configure encode settings.
"""

# Standard Library
import math
import os
import statistics

# PIP3 modules
import yaml


# instability region cause categories (heuristic labels)
CAUSE_BBOX_NOISE = "bbox_noise"
CAUSE_CONFIDENCE_GAP = "confidence_gap"
CAUSE_SMOOTHING_LAG = "smoothing_lag"
CAUSE_SIZE_INSTABILITY = "size_instability"

# confidence threshold for low-confidence classification
LOW_CONF_THRESHOLD = 0.5

# sliding window size for quantization chatter detection
CHATTER_WINDOW = 5

# minimum consecutive unstable frames to form a region
MIN_REGION_LENGTH = 3


#============================================
def _compute_center_velocities(
	cx_list: list,
	cy_list: list,
) -> tuple:
	"""Compute per-frame 2D velocity vectors for crop center.

	Args:
		cx_list: List of crop center x coordinates per frame.
		cy_list: List of crop center y coordinates per frame.

	Returns:
		Tuple of (vx_list, vy_list) where each is a list of floats.
		First element is 0.0 (no velocity at frame 0).
	"""
	n = len(cx_list)
	vx_list = [0.0] * n
	vy_list = [0.0] * n
	for i in range(1, n):
		vx_list[i] = cx_list[i] - cx_list[i - 1]
		vy_list[i] = cy_list[i] - cy_list[i - 1]
	return (vx_list, vy_list)


#============================================
def _compute_center_jerk(
	vx_list: list,
	vy_list: list,
) -> list:
	"""Compute per-frame 2D vector jerk (velocity change magnitude).

	Jerk captures both acceleration and direction change in one number.
	A crop path that reverses direction sharply has high jerk even if
	speed magnitude changes modestly.

	Args:
		vx_list: Per-frame x velocity.
		vy_list: Per-frame y velocity.

	Returns:
		List of jerk magnitudes. First two elements are 0.0.
	"""
	n = len(vx_list)
	jerk = [0.0] * n
	for i in range(2, n):
		dvx = vx_list[i] - vx_list[i - 1]
		dvy = vy_list[i] - vy_list[i - 1]
		jerk[i] = math.hypot(dvx, dvy)
	return jerk


#============================================
def _compute_height_jerk(
	heights: list,
) -> tuple:
	"""Compute per-frame height velocity and jerk (1D scalar).

	Args:
		heights: List of crop heights per frame.

	Returns:
		Tuple of (h_vel, h_jerk) lists.
	"""
	n = len(heights)
	h_vel = [0.0] * n
	h_jerk = [0.0] * n
	for i in range(1, n):
		h_vel[i] = heights[i] - heights[i - 1]
	for i in range(2, n):
		h_jerk[i] = abs(h_vel[i] - h_vel[i - 1])
	return (h_vel, h_jerk)


#============================================
def _percentile(values: list, pct: float) -> float:
	"""Compute a percentile from a list of numeric values.

	Uses nearest-rank method.

	Args:
		values: Non-empty list of numbers.
		pct: Percentile as fraction (0.0 to 1.0).

	Returns:
		The percentile value.
	"""
	sorted_vals = sorted(values)
	idx = int(pct * (len(sorted_vals) - 1))
	idx = max(0, min(idx, len(sorted_vals) - 1))
	return sorted_vals[idx]


#============================================
def _detect_quantization_chatter(
	crop_rects: list,
	vx_list: list,
	vy_list: list,
) -> float:
	"""Detect quantization chatter in integer crop rects.

	Chatter occurs when the floating-point crop center oscillates near
	x.5, causing the rounded integer value to alternate between floor
	and ceil every frame. Detection is pattern-based: look for
	alternating +1/-1 patterns in integer center deltas over a sliding
	window, only when underlying velocity is low.

	Args:
		crop_rects: List of (x, y, w, h) integer crop tuples.
		vx_list: Per-frame float x velocity.
		vy_list: Per-frame float y velocity.

	Returns:
		Fraction of frames participating in chatter patterns (0.0 to 1.0).
	"""
	n = len(crop_rects)
	if n < CHATTER_WINDOW:
		return 0.0
	# compute integer center deltas
	cx_int = [r[0] + r[2] // 2 for r in crop_rects]
	cy_int = [r[1] + r[3] // 2 for r in crop_rects]
	dx = [0] * n
	dy = [0] * n
	for i in range(1, n):
		dx[i] = cx_int[i] - cx_int[i - 1]
		dy[i] = cy_int[i] - cy_int[i - 1]
	# mark frames as chatter candidates
	chatter_frames = [False] * n
	# velocity threshold: only flag chatter at low underlying velocity
	vel_threshold = 2.0
	for i in range(CHATTER_WINDOW, n):
		# check if underlying velocity is low in this window
		window_vel = max(
			max(abs(vx_list[j]) for j in range(i - CHATTER_WINDOW + 1, i + 1)),
			max(abs(vy_list[j]) for j in range(i - CHATTER_WINDOW + 1, i + 1)),
		)
		if window_vel > vel_threshold:
			continue
		# check for alternating pattern in x or y deltas
		dx_window = [dx[j] for j in range(i - CHATTER_WINDOW + 1, i + 1)]
		dy_window = [dy[j] for j in range(i - CHATTER_WINDOW + 1, i + 1)]
		if _is_alternating_pattern(dx_window) or _is_alternating_pattern(dy_window):
			for j in range(i - CHATTER_WINDOW + 1, i + 1):
				chatter_frames[j] = True
	chatter_count = sum(chatter_frames)
	chatter_fraction = chatter_count / n
	return chatter_fraction


#============================================
def _is_alternating_pattern(deltas: list) -> bool:
	"""Check if a sequence of integer deltas shows alternating +1/-1 or 0/+1/0 pattern.

	Args:
		deltas: List of integer deltas.

	Returns:
		True if the pattern is alternating (chatter-like).
	"""
	if len(deltas) < 3:
		return False
	# count sign changes among nonzero deltas
	sign_changes = 0
	nonzero_count = 0
	prev_sign = 0
	for d in deltas:
		if d == 0:
			continue
		nonzero_count += 1
		curr_sign = 1 if d > 0 else -1
		if prev_sign != 0 and curr_sign != prev_sign:
			sign_changes += 1
		prev_sign = curr_sign
	# need at least 2 nonzero values and mostly alternating
	if nonzero_count < 2:
		return False
	# all deltas must be small magnitude (1 or 0)
	if any(abs(d) > 1 for d in deltas):
		return False
	# alternating means sign changes on most transitions
	alternation_ratio = sign_changes / max(1, nonzero_count - 1)
	is_alternating = alternation_ratio >= 0.6
	return is_alternating


#============================================
def _compute_instability_scores(
	center_jerk: list,
	confidences: list,
) -> list:
	"""Compute per-frame confidence-weighted instability score.

	Low confidence amplifies the instability score.

	Args:
		center_jerk: Per-frame jerk magnitudes.
		confidences: Per-frame confidence values (0.0 to 1.0).

	Returns:
		List of instability scores per frame.
	"""
	n = len(center_jerk)
	scores = [0.0] * n
	for i in range(n):
		conf = confidences[i]
		# amplify instability when confidence is low
		scores[i] = center_jerk[i] * (1.0 + (1.0 - conf))
	return scores


#============================================
def _classify_region_cause(
	center_jerk: list,
	height_jerk: list,
	confidences: list,
	vx_list: list,
	vy_list: list,
	start: int,
	end: int,
) -> str:
	"""Classify the dominant cause of instability in a frame region.

	Uses heuristic signal correlations to suggest a cause category.
	These are inference, not ground truth.

	Args:
		center_jerk: Per-frame center jerk values.
		height_jerk: Per-frame height jerk values.
		confidences: Per-frame confidence values.
		vx_list: Per-frame x velocity.
		vy_list: Per-frame y velocity.
		start: Start frame index (inclusive).
		end: End frame index (exclusive).

	Returns:
		Cause category string.
	"""
	region_len = end - start
	if region_len == 0:
		return CAUSE_BBOX_NOISE
	# compute region statistics
	region_conf = [confidences[i] for i in range(start, end)]
	region_cjerk = [center_jerk[i] for i in range(start, end)]
	region_hjerk = [height_jerk[i] for i in range(start, end)]
	region_speed = [math.hypot(vx_list[i], vy_list[i]) for i in range(start, end)]
	mean_conf = statistics.mean(region_conf)
	mean_cjerk = statistics.mean(region_cjerk)
	mean_hjerk = statistics.mean(region_hjerk)
	mean_speed = statistics.mean(region_speed)
	# heuristic classification
	# size_instability: high height jerk, low center jerk
	if mean_hjerk > mean_cjerk and mean_hjerk > 0.5:
		return CAUSE_SIZE_INSTABILITY
	# confidence_gap: low confidence
	if mean_conf < LOW_CONF_THRESHOLD:
		return CAUSE_CONFIDENCE_GAP
	# smoothing_lag: high velocity with jerk spikes (direction changes)
	if mean_speed > 3.0 and mean_cjerk > 1.0:
		return CAUSE_SMOOTHING_LAG
	# bbox_noise: high jerk with decent confidence
	return CAUSE_BBOX_NOISE


#============================================
def _find_instability_regions(
	instability_scores: list,
	center_jerk: list,
	height_jerk: list,
	confidences: list,
	vx_list: list,
	vy_list: list,
	threshold_pct: float = 0.85,
) -> list:
	"""Find contiguous regions of high instability and classify causes.

	Args:
		instability_scores: Per-frame instability scores.
		center_jerk: Per-frame center jerk values.
		height_jerk: Per-frame height jerk values.
		confidences: Per-frame confidence values.
		vx_list: Per-frame x velocity.
		vy_list: Per-frame y velocity.
		threshold_pct: Percentile above which frames are considered unstable.

	Returns:
		List of region dicts sorted by descending mean instability score.
		Each dict has: start_frame, end_frame, cause, mean_confidence,
		jerk_p95, height_jerk_p95.
	"""
	n = len(instability_scores)
	if n < MIN_REGION_LENGTH:
		return []
	# compute threshold from percentile
	threshold = _percentile(instability_scores, threshold_pct)
	# threshold must be positive to be meaningful
	if threshold <= 0.0:
		return []
	# find runs of frames above threshold
	regions = []
	in_region = False
	region_start = 0
	for i in range(n):
		if instability_scores[i] >= threshold:
			if not in_region:
				region_start = i
				in_region = True
		else:
			if in_region:
				if i - region_start >= MIN_REGION_LENGTH:
					regions.append((region_start, i))
				in_region = False
	# close final region
	if in_region and n - region_start >= MIN_REGION_LENGTH:
		regions.append((region_start, n))
	# classify and score each region
	result = []
	for start, end in regions:
		cause = _classify_region_cause(
			center_jerk, height_jerk, confidences,
			vx_list, vy_list, start, end,
		)
		region_jerk = [center_jerk[i] for i in range(start, end)]
		region_hjerk = [height_jerk[i] for i in range(start, end)]
		region_conf = [confidences[i] for i in range(start, end)]
		region_instab = [instability_scores[i] for i in range(start, end)]
		region_dict = {
			"start_frame": start,
			"end_frame": end,
			"cause": cause,
			"mean_confidence": round(statistics.mean(region_conf), 3),
			"jerk_p95": round(_percentile(region_jerk, 0.95), 2),
			"height_jerk_p95": round(_percentile(region_hjerk, 0.95), 2),
			"mean_instability": round(statistics.mean(region_instab), 3),
		}
		result.append(region_dict)
	# sort by mean instability descending
	result.sort(key=lambda r: -r["mean_instability"])
	return result


#============================================
def _compute_dominant_symptom(
	instability_scores: list,
	instability_regions: list,
	center_jerk: list,
	height_jerk: list,
) -> str:
	"""Determine the dominant symptom from instability regions.

	Aggregates instability-weighted frame counts across regions by cause.
	bbox_noise and smoothing_lag map to lateral_jitter, confidence_gap
	maps to low_confidence_drift, size_instability maps to zoom_pumping.

	Args:
		instability_scores: Per-frame instability scores.
		instability_regions: List of region dicts with cause labels.
		center_jerk: Per-frame center jerk values.
		height_jerk: Per-frame height jerk values.

	Returns:
		Dominant symptom string.
	"""
	if not instability_regions:
		return "stable"
	# accumulate instability-weighted frame counts by symptom
	symptom_weight = {
		"lateral_jitter": 0.0,
		"zoom_pumping": 0.0,
		"low_confidence_drift": 0.0,
	}
	# mapping from region cause to symptom
	cause_to_symptom = {
		CAUSE_BBOX_NOISE: "lateral_jitter",
		CAUSE_SMOOTHING_LAG: "lateral_jitter",
		CAUSE_CONFIDENCE_GAP: "low_confidence_drift",
		CAUSE_SIZE_INSTABILITY: "zoom_pumping",
	}
	total_weight = 0.0
	for region in instability_regions:
		cause = region["cause"]
		symptom = cause_to_symptom[cause]
		# weight by total instability score in the region
		start = region["start_frame"]
		end = region["end_frame"]
		region_weight = sum(instability_scores[i] for i in range(start, end))
		symptom_weight[symptom] += region_weight
		total_weight += region_weight
	if total_weight <= 0.0:
		return "stable"
	# find dominant symptom
	best_symptom = max(symptom_weight, key=lambda s: symptom_weight[s])
	best_fraction = symptom_weight[best_symptom] / total_weight
	# if no single category exceeds 50%, label as mixed
	if best_fraction < 0.5:
		return "mixed"
	dominant = f"{best_symptom}_dominated"
	return dominant


#============================================
def _suggest_seed_frames(
	instability_regions: list,
	instability_scores: list,
) -> list:
	"""Suggest seed frame positions based on instability regions.

	Picks the frame with maximum instability score within each region.

	Args:
		instability_regions: List of region dicts.
		instability_scores: Per-frame instability scores.

	Returns:
		List of suggested frame indices, sorted ascending.
	"""
	suggestions = []
	for region in instability_regions:
		start = region["start_frame"]
		end = region["end_frame"]
		# find frame with max instability in region
		best_frame = start
		best_score = instability_scores[start]
		for i in range(start + 1, end):
			if instability_scores[i] > best_score:
				best_score = instability_scores[i]
				best_frame = i
		suggestions.append(best_frame)
	suggestions.sort()
	return suggestions


#============================================
def _compute_bad_frame_runs(bad_flags: list) -> tuple:
	"""Identify consecutive runs of bad frames >= 3 frames long.

	Args:
		bad_flags: List of booleans indicating bad frames.

	Returns:
		Tuple of (max_run_length, run_count) where run_count is the number
		of consecutive True runs of length >= 3.
	"""
	n = len(bad_flags)
	max_run_length = 0
	run_count = 0
	in_run = False
	current_run_length = 0
	for i in range(n):
		if bad_flags[i]:
			if not in_run:
				in_run = True
				current_run_length = 1
			else:
				current_run_length += 1
		else:
			if in_run:
				if current_run_length >= 3:
					run_count += 1
					max_run_length = max(max_run_length, current_run_length)
				in_run = False
				current_run_length = 0
	# close final run
	if in_run and current_run_length >= 3:
		run_count += 1
		max_run_length = max(max_run_length, current_run_length)
	return (max_run_length, run_count)


#============================================
def _compute_composition_metrics(crop_rects: list, trajectory: list) -> dict:
	"""Compute composition-quality metrics from crop rects and trajectory.

	Per-frame signals include center offset, edge margins, and zoom stability.
	Bad frames are flagged for center offset, edge margin, or zoom jitter.
	Summary metrics include percentiles, edge touch counts, and bad-frame run
	statistics.

	Args:
		crop_rects: List of (x, y, w, h) integer crop tuples per frame.
		trajectory: List of per-frame dicts with keys cx, cy, w, h, conf,
			source. None entries indicate missing tracking data.

	Returns:
		Dict with composition metrics including center offset, edge margins,
		and bad-frame statistics.
	"""
	n = len(crop_rects)
	if n == 0:
		return {}
	# initialize per-frame arrays
	center_offset_norm = []
	edge_margin_px = []
	edge_margin_norm = []
	bad_center_frame = []
	bad_edge_frame = []
	bad_zoom_frame = []
	bad_frame = []
	# process each frame
	for i in range(n):
		crop_x, crop_y, crop_w, crop_h = crop_rects[i]
		crop_cx = crop_x + crop_w / 2.0
		crop_cy = crop_y + crop_h / 2.0
		traj = trajectory[i] if i < len(trajectory) else None
		# compute center offset
		if traj is not None:
			traj_cx = traj["cx"]
			traj_cy = traj["cy"]
			dx_norm = (traj_cx - crop_cx) / crop_w if crop_w > 0 else 0.0
			dy_norm = (traj_cy - crop_cy) / crop_h if crop_h > 0 else 0.0
			offset = math.hypot(dx_norm, dy_norm)
		else:
			offset = 0.0
		center_offset_norm.append(offset)
		# compute edge margins
		if traj is not None:
			traj_w = traj["w"]
			traj_h = traj["h"]
			subj_left = traj_cx - traj_w / 2.0
			subj_right = traj_cx + traj_w / 2.0
			subj_top = traj_cy - traj_h / 2.0
			subj_bottom = traj_cy + traj_h / 2.0
			crop_left = float(crop_x)
			crop_right = float(crop_x + crop_w)
			crop_top = float(crop_y)
			crop_bottom = float(crop_y + crop_h)
			# compute four margins in pixels
			left_margin_px = subj_left - crop_left
			right_margin_px = crop_right - subj_right
			top_margin_px = subj_top - crop_top
			bottom_margin_px = crop_bottom - subj_bottom
			min_margin_px = min(
				left_margin_px, right_margin_px,
				top_margin_px, bottom_margin_px,
			)
			# compute normalized margins
			left_norm = left_margin_px / crop_w if crop_w > 0 else float('inf')
			right_norm = right_margin_px / crop_w if crop_w > 0 else float('inf')
			top_norm = top_margin_px / crop_h if crop_h > 0 else float('inf')
			bottom_norm = bottom_margin_px / crop_h if crop_h > 0 else float('inf')
			min_norm = min(left_norm, right_norm, top_norm, bottom_norm)
		else:
			# missing trajectory: use default values
			min_margin_px = float('inf')
			min_norm = float('inf')
		edge_margin_px.append(min_margin_px)
		edge_margin_norm.append(min_norm)
		# compute bad frame flags
		bad_center = center_offset_norm[i] > 0.25
		bad_center_frame.append(bad_center)
		bad_edge = edge_margin_norm[i] < 0.05
		bad_edge_frame.append(bad_edge)
		bad_zoom = False
		if i > 0:
			prev_h = crop_rects[i - 1][3]
			curr_h = crop_h
			if prev_h > 0:
				h_change_frac = abs(float(curr_h) - float(prev_h)) / float(prev_h)
				bad_zoom = h_change_frac > 0.02
		bad_zoom_frame.append(bad_zoom)
		bad_frame.append(bad_center or bad_edge or bad_zoom)
	# compute summary metrics
	# filter out infinite values for edge margins
	edge_margin_px_finite = [m for m in edge_margin_px if math.isfinite(m)]
	# edge_margin_norm filtered below where used for touch count
	# center offset percentiles
	center_offset_p50 = round(_percentile(center_offset_norm, 0.50), 4)
	center_offset_p95 = round(_percentile(center_offset_norm, 0.95), 4)
	center_offset_max = round(max(center_offset_norm), 4)
	# edge margin statistics
	if edge_margin_px_finite:
		edge_margin_min_px = round(min(edge_margin_px_finite), 4)
		edge_margin_p05 = round(_percentile(edge_margin_px_finite, 0.05), 4)
	else:
		edge_margin_min_px = 0.0
		edge_margin_p05 = 0.0
	# edge touch count (margin < 5 pixels)
	edge_touch_count = sum(1 for m in edge_margin_px if math.isfinite(m) and m < 5.0)
	# bad frame fractions
	bad_frame_fraction = round(sum(bad_frame) / n, 4) if n > 0 else 0.0
	bad_center_fraction = round(sum(bad_center_frame) / n, 4) if n > 0 else 0.0
	bad_edge_fraction = round(sum(bad_edge_frame) / n, 4) if n > 0 else 0.0
	bad_zoom_fraction = round(sum(bad_zoom_frame) / n, 4) if n > 0 else 0.0
	# bad frame runs
	bad_run_max_length, bad_run_count = _compute_bad_frame_runs(bad_frame)
	result = {
		"center_offset_p50": center_offset_p50,
		"center_offset_p95": center_offset_p95,
		"center_offset_max": center_offset_max,
		"edge_margin_min_px": edge_margin_min_px,
		"edge_margin_p05": edge_margin_p05,
		"edge_touch_count": edge_touch_count,
		"bad_frame_fraction": bad_frame_fraction,
		"bad_center_fraction": bad_center_fraction,
		"bad_edge_fraction": bad_edge_fraction,
		"bad_zoom_fraction": bad_zoom_fraction,
		"bad_run_max_length": bad_run_max_length,
		"bad_run_count": bad_run_count,
	}
	return result


#============================================
def analyze_crop_stability(
	crop_rects: list,
	trajectory: list,
	output_w: int,
	output_h: int,
	fps: float,
) -> dict:
	"""Crop-path metrics from rendered crop rects and trajectory.

	Computes motion-stability metrics including center jerk (2D vector),
	height jerk, crop size CV, quantization chatter fraction, confidence
	statistics, instability regions with heuristic cause labels, and
	dominant symptom classification.

	Args:
		crop_rects: List of (x, y, w, h) integer crop tuples per frame.
		trajectory: List of per-frame dicts with keys cx, cy, w, h, conf,
			source. None entries indicate missing tracking data.
		output_w: Output frame width in pixels.
		output_h: Output frame height in pixels.
		fps: Video frame rate.

	Returns:
		Dict with analysis results.
	"""
	n = len(crop_rects)
	duration_s = n / fps if fps > 0 else 0.0
	# extract crop centers and heights from integer crop rects
	cx_list = [r[0] + r[2] / 2.0 for r in crop_rects]
	cy_list = [r[1] + r[3] / 2.0 for r in crop_rects]
	heights = [float(r[3]) for r in crop_rects]
	# extract confidence per frame from trajectory
	confidences = []
	for i in range(n):
		traj = trajectory[i] if i < len(trajectory) else None
		if traj is not None:
			confidences.append(float(traj["conf"]))
		else:
			confidences.append(0.0)
	# compute velocity and jerk
	vx_list, vy_list = _compute_center_velocities(cx_list, cy_list)
	center_jerk = _compute_center_jerk(vx_list, vy_list)
	h_vel, h_jerk = _compute_height_jerk(heights)
	# compute percentiles (skip first 2 frames which are always 0)
	valid_cjerk = center_jerk[2:] if n > 2 else center_jerk
	valid_hjerk = h_jerk[2:] if n > 2 else h_jerk
	if not valid_cjerk:
		valid_cjerk = [0.0]
	if not valid_hjerk:
		valid_hjerk = [0.0]
	cjerk_p50 = round(_percentile(valid_cjerk, 0.50), 3)
	cjerk_p95 = round(_percentile(valid_cjerk, 0.95), 3)
	cjerk_max = round(max(valid_cjerk), 3)
	hjerk_p50 = round(_percentile(valid_hjerk, 0.50), 3)
	hjerk_p95 = round(_percentile(valid_hjerk, 0.95), 3)
	hjerk_max = round(max(valid_hjerk), 3)
	# crop size coefficient of variation
	if n > 1:
		h_mean = statistics.mean(heights)
		h_stdev = statistics.stdev(heights)
		crop_size_cv = round(h_stdev / h_mean, 4) if h_mean > 0 else 0.0
	else:
		crop_size_cv = 0.0
	# quantization chatter
	chatter_frac = round(
		_detect_quantization_chatter(crop_rects, vx_list, vy_list), 4,
	)
	# confidence stats
	mean_conf = round(statistics.mean(confidences), 3) if confidences else 0.0
	low_conf_count = sum(1 for c in confidences if c < LOW_CONF_THRESHOLD)
	low_conf_frac = round(low_conf_count / n, 4) if n > 0 else 0.0
	# instability regions
	instability_scores = _compute_instability_scores(center_jerk, confidences)
	regions = _find_instability_regions(
		instability_scores, center_jerk, h_jerk,
		confidences, vx_list, vy_list,
	)
	# dominant symptom
	dominant = _compute_dominant_symptom(
		instability_scores, regions, center_jerk, h_jerk,
	)
	# seed suggestions
	seed_suggestions = _suggest_seed_frames(regions, instability_scores)
	# composition quality metrics (extreme-value focused)
	composition = _compute_composition_metrics(crop_rects, trajectory)
	# build result dict
	result = {
		"summary": {
			"frames": n,
			"duration_s": round(duration_s, 2),
			"fps": round(fps, 4),
			"output_size": [output_w, output_h],
		},
		"motion_stability": {
			"center_jerk_p50": cjerk_p50,
			"center_jerk_p95": cjerk_p95,
			"center_jerk_max": cjerk_max,
			"height_jerk_p50": hjerk_p50,
			"height_jerk_p95": hjerk_p95,
			"height_jerk_max": hjerk_max,
			"crop_size_cv": crop_size_cv,
			"quantization_chatter_fraction": chatter_frac,
		},
		"confidence": {
			"mean": mean_conf,
			"low_conf_fraction": low_conf_frac,
		},
		"composition": composition,
		"instability_regions": regions,
		"dominant_symptom": dominant,
		"seed_suggestions": seed_suggestions,
	}
	return result


#============================================
def analyze_solver_context(
	interval_results: list,
	seeds: list,
	fps: float,
) -> dict:
	"""Solver-quality metrics from intervals, diagnostics, and seeds.

	Extracts FWD/BWD convergence error, seed density, desert count,
	identity score, and competitor margin statistics.

	Args:
		interval_results: List of solved interval result dicts, sorted
			by start_frame.
		seeds: List of seed dicts with at least "frame" key.
		fps: Video frame rate.

	Returns:
		Dict with solver context metrics.
	"""
	# seed density (seeds per minute)
	if not interval_results:
		return {
			"seed_density": 0.0,
			"desert_count": 0,
			"fwd_bwd_convergence_median": 0.0,
			"fwd_bwd_convergence_p90": 0.0,
			"identity_score_median": 0.0,
			"competitor_margin_median": 0.0,
		}
	# compute total duration from intervals
	first_start = int(interval_results[0]["start_frame"])
	last_end = max(
		int(r["start_frame"]) + int(r.get("frame_count", 0))
		for r in interval_results
	)
	total_frames = last_end - first_start
	duration_min = (total_frames / fps / 60.0) if fps > 0 else 1.0
	seed_count = len(seeds)
	seed_density = round(seed_count / max(0.001, duration_min), 1)
	# desert count: seedless gaps > 5 seconds
	seed_frames = sorted(s["frame"] for s in seeds)
	desert_threshold = 5.0 * fps
	desert_count = 0
	for i in range(1, len(seed_frames)):
		gap = seed_frames[i] - seed_frames[i - 1]
		if gap > desert_threshold:
			desert_count += 1
	# also check gap from start to first seed and last seed to end
	if seed_frames and (seed_frames[0] - first_start) > desert_threshold:
		desert_count += 1
	if seed_frames and (last_end - seed_frames[-1]) > desert_threshold:
		desert_count += 1
	# extract per-interval scores from interval_score dict
	# the actual structure is: result["interval_score"]["identity_score"]
	# and result["interval_score"]["meeting_point_error"] is a list of
	# per-frame dicts with "center_err_px" and "scale_err_pct"
	convergence_errors = []
	identity_scores = []
	competitor_margins = []
	for result in interval_results:
		iscore = result.get("interval_score", {})
		# convergence error from meeting_point_error list
		mpe_list = iscore.get("meeting_point_error", [])
		for mpe in mpe_list:
			center_err = mpe.get("center_err_px")
			if center_err is not None:
				convergence_errors.append(float(center_err))
		# identity score
		id_score = iscore.get("identity_score")
		if id_score is not None:
			identity_scores.append(float(id_score))
		# competitor margin
		margin = iscore.get("competitor_margin")
		if margin is not None:
			competitor_margins.append(float(margin))
	# compute stats
	conv_median = 0.0
	conv_p90 = 0.0
	if convergence_errors:
		conv_median = round(statistics.median(convergence_errors), 2)
		conv_p90 = round(_percentile(convergence_errors, 0.90), 2)
	id_median = 0.0
	if identity_scores:
		id_median = round(statistics.median(identity_scores), 3)
	margin_median = 0.0
	if competitor_margins:
		margin_median = round(statistics.median(competitor_margins), 3)
	result = {
		"seed_density": seed_density,
		"desert_count": desert_count,
		"fwd_bwd_convergence_median": conv_median,
		"fwd_bwd_convergence_p90": conv_p90,
		"identity_score_median": id_median,
		"competitor_margin_median": margin_median,
	}
	return result


#============================================
def format_analysis_report(
	analysis: dict,
	solver_context: dict,
	output_yaml_path: str,
	regime_summary_line: str = "",
) -> str:
	"""Format the analysis results as a human-readable console report.

	Args:
		analysis: Dict from analyze_crop_stability().
		solver_context: Dict from analyze_solver_context().
		output_yaml_path: Path where the YAML report was written.
		regime_summary_line: Optional one-line regime summary string.

	Returns:
		Formatted multi-line string for console output.
	"""
	summary = analysis["summary"]
	motion = analysis["motion_stability"]
	conf = analysis["confidence"]
	regions = analysis["instability_regions"]
	dominant = analysis["dominant_symptom"]
	seeds_suggested = analysis["seed_suggestions"]
	lines = []
	lines.append("=== crop path analysis ===")
	lines.append(f"  frames:             {summary['frames']}"
		+ f" ({summary['duration_s']:.1f}s at {summary['fps']:.0f}fps)")
	lines.append(f"  output size:        {summary['output_size'][0]}x{summary['output_size'][1]}")
	lines.append("")
	lines.append("  motion stability:")
	lines.append(f"    center jerk:      median {motion['center_jerk_p50']} px/f"
		+ f", p95 {motion['center_jerk_p95']} px/f")
	lines.append(f"    height jerk:      median {motion['height_jerk_p50']} px/f"
		+ f", p95 {motion['height_jerk_p95']} px/f")
	lines.append(f"    crop size CV:     {motion['crop_size_cv']}")
	lines.append(f"    quant chatter:    {motion['quantization_chatter_fraction'] * 100:.1f}% of frames")
	lines.append("")
	lines.append("  confidence:")
	lines.append(f"    mean:             {conf['mean']}")
	lines.append(f"    low-conf frames:  {conf['low_conf_fraction'] * 100:.1f}%")
	lines.append("")
	# solver context
	lines.append("  solver context:")
	lines.append(f"    seed density:     {solver_context['seed_density']} seeds/min")
	lines.append(f"    desert count:     {solver_context['desert_count']}")
	lines.append(f"    FWD/BWD conv:     median {solver_context['fwd_bwd_convergence_median']} px"
		+ f", p90 {solver_context['fwd_bwd_convergence_p90']} px")
	lines.append(f"    identity score:   {solver_context['identity_score_median']}")
	lines.append(f"    competitor margin: {solver_context['competitor_margin_median']}")
	lines.append("")
	# instability regions (top 5)
	if regions:
		top_regions = regions[:5]
		lines.append(f"  instability regions (top {len(top_regions)}):")
		for region in top_regions:
			lines.append(
				f"    frames {region['start_frame']}-{region['end_frame']}:"
				+ f" {region['cause']}"
				+ f" (conf {region['mean_confidence']}"
				+ f", jerk p95 {region['jerk_p95']})"
			)
	else:
		lines.append("  instability regions: none detected")
	lines.append("")
	# diagnosis
	lines.append("  diagnosis:")
	lines.append(f"    dominant symptom: {dominant}")
	if regions:
		primary = regions[0]
		lines.append(f"    primary issue: {primary['cause']} (heuristic)")
		affected = primary["end_frame"] - primary["start_frame"]
		lines.append(f"    affected frames: {affected}")
	if seeds_suggested:
		frame_list = ", ".join(str(f) for f in seeds_suggested[:5])
		lines.append(f"    suggested seed frames: {frame_list}")
	# chatter note
	chatter = motion["quantization_chatter_fraction"]
	if chatter > 0.03:
		lines.append("    secondary: quantization chatter in stationary sections")
		lines.append("    suggestion: crop controller subpixel smoothing")
	# regime classification summary (smart mode)
	if regime_summary_line:
		lines.append("")
		lines.append(f"  {regime_summary_line}")
	lines.append("")
	lines.append(f"  wrote: {output_yaml_path}")
	report = "\n".join(lines)
	return report


#============================================
def write_analysis_yaml(
	analysis: dict,
	solver_context: dict,
	output_path: str,
	regime_spans: list = None,
) -> None:
	"""Write the analysis results as a diagnostic YAML file.

	Args:
		analysis: Dict from analyze_crop_stability().
		solver_context: Dict from analyze_solver_context().
		output_path: File path for the YAML output.
		regime_spans: Optional list of regime span dicts to include.
	"""
	# build output dict
	doc = {
		"track_runner_encode_analysis": 1,
		"summary": analysis["summary"],
		"motion_stability": analysis["motion_stability"],
		"confidence": analysis["confidence"],
		"instability_regions": analysis["instability_regions"],
		"dominant_symptom": analysis["dominant_symptom"],
		"solver_context": solver_context,
		"seed_suggestions": analysis["seed_suggestions"],
	}
	# build diagnosis section
	regions = analysis["instability_regions"]
	diagnosis = {}
	if regions:
		primary = regions[0]
		diagnosis["primary_issue"] = f"{primary['cause']} (heuristic)"
		diagnosis["affected_frames"] = primary["end_frame"] - primary["start_frame"]
		diagnosis["suggestion_method"] = "instability_region_max_frame"
	chatter = analysis["motion_stability"]["quantization_chatter_fraction"]
	if chatter > 0.03:
		diagnosis["secondary_issue"] = "quantization_chatter (heuristic)"
		diagnosis["suggestion_secondary"] = "crop controller subpixel smoothing"
	if diagnosis:
		doc["diagnosis"] = diagnosis
	# add regime classification if available
	if regime_spans:
		total_frames = analysis["summary"]["frames"]
		# compute per-regime frame counts
		regime_counts = {}
		for span in regime_spans:
			regime = span["regime"]
			span_len = span["end_frame"] - span["start_frame"]
			regime_counts[regime] = regime_counts.get(regime, 0) + span_len
		regime_pcts = {}
		for regime, count in regime_counts.items():
			regime_pcts[regime] = round(100.0 * count / total_frames, 1)
		doc["regime_summary"] = {
			"frame_percentages": regime_pcts,
			"num_transitions": max(0, len(regime_spans) - 1),
			"spans": regime_spans,
		}
	# write with comment header
	parent_dir = os.path.dirname(os.path.abspath(output_path))
	os.makedirs(parent_dir, exist_ok=True)
	with open(output_path, "w") as f:
		f.write("# auto-generated by track_runner analyze\n")
		f.write("# this is a diagnostic report, not an encode settings file\n")
		yaml.dump(doc, f, default_flow_style=False, sort_keys=False)
