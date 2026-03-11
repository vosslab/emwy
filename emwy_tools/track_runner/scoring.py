"""Candidate scoring module for track_runner.

Scores detection candidates against the current tracked state using
hard gates (reject before scoring) and weighted scoring (normalized 0-1 terms).
"""

# Standard Library
import math

# local repo modules
import kalman


#============================================
def _bbox_center(bbox: list) -> tuple:
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
def apply_hard_gates(candidates: list, prediction_state: dict, config: dict) -> list:
	"""Filter candidates by hard gates, rejecting those that fail any gate.

	Gates applied:
		1. Search radius: candidate center within scaled predicted height.
		2. Aspect ratio: candidate h/w within configured bounds.
		3. Scale band: candidate area within factor of predicted area.

	Args:
		candidates: List of detection dicts with "bbox", "confidence", "class_id".
		prediction_state: Kalman state dict from predict step.
		config: Project config dict with settings.tracking and settings.scoring.

	Returns:
		List of candidates that pass all gates.
	"""
	# Extract predicted bounding box in center format
	pred_cx, pred_cy, pred_w, pred_h = kalman.get_bbox(prediction_state)
	pred_area = pred_w * pred_h

	# Read gate parameters from config
	tracking_cfg = config.get("settings", {}).get("tracking", {})
	scoring_cfg = config.get("settings", {}).get("scoring", {})
	search_radius_scale = tracking_cfg.get("search_radius_scale", 1.5)
	min_search_radius = tracking_cfg.get("min_search_radius", 100)
	aspect_min = scoring_cfg.get("hard_gate_aspect_min", 1.5)
	aspect_max = scoring_cfg.get("hard_gate_aspect_max", 4.0)
	scale_band = scoring_cfg.get("hard_gate_scale_band", 3.0)

	# Compute the effective search radius
	max_search_radius = max(min_search_radius, search_radius_scale * pred_h)

	passed = []
	for cand in candidates:
		cand_cx, cand_cy, cand_w, cand_h = _bbox_center(cand["bbox"])

		# Gate 1: search radius
		dx = cand_cx - pred_cx
		dy = cand_cy - pred_cy
		dist = math.sqrt(dx * dx + dy * dy)
		if dist > max_search_radius:
			continue

		# Gate 2: aspect ratio (height / width)
		if cand_w <= 0 or cand_h <= 0:
			continue
		aspect = cand_h / cand_w
		if aspect < aspect_min or aspect > aspect_max:
			continue

		# Gate 3: scale band (area comparison)
		cand_area = cand_w * cand_h
		if pred_area > 0:
			if cand_area < pred_area / scale_band:
				continue
			if cand_area > pred_area * scale_band:
				continue

		passed.append(cand)

	return passed


#============================================
def score_candidates(
	candidates: list,
	prediction_state: dict,
	appearance: dict | None,
	config: dict,
) -> list:
	"""Score surviving candidates with weighted terms normalized 0-1.

	Args:
		candidates: List of detection dicts that passed hard gates.
		prediction_state: Kalman state dict from predict step.
		appearance: Optional appearance dict with "jersey_hsv" and/or
			"color_histogram". If None, color score defaults to 0.5.
		config: Project config dict with settings.scoring weights.

	Returns:
		List of candidate dicts, each with an added "score" float key.
	"""
	# Extract predicted bounding box and state
	pred_cx, pred_cy, pred_w, pred_h = kalman.get_bbox(prediction_state)
	pred_log_h = float(prediction_state["x"][2])

	# Read scoring weights from config
	scoring_cfg = config.get("settings", {}).get("scoring", {})
	w_detect = scoring_cfg.get("w_detect", 0.30)
	w_predict = scoring_cfg.get("w_predict", 0.25)
	w_color = scoring_cfg.get("w_color", 0.15)
	w_size = scoring_cfg.get("w_size", 0.15)
	w_path = scoring_cfg.get("w_path", 0.10)
	w_motion = scoring_cfg.get("w_motion", 0.05)

	# Compute max search radius for prediction score normalization
	tracking_cfg = config.get("settings", {}).get("tracking", {})
	search_radius_scale = tracking_cfg.get("search_radius_scale", 1.5)
	min_search_radius = tracking_cfg.get("min_search_radius", 100)
	max_search_radius = max(min_search_radius, search_radius_scale * pred_h)

	# Size score tolerance in log space (~2.7x size difference)
	size_tolerance = 1.0

	# Placeholder scores for unimplemented modules
	path_score = 0.5
	motion_score = 0.5

	scored = []
	for cand in candidates:
		cand_cx, cand_cy, cand_w, cand_h = _bbox_center(cand["bbox"])

		# Detector confidence, clamped 0-1
		detect_score = max(0.0, min(1.0, cand["confidence"]))

		# Prediction proximity score
		dx = cand_cx - pred_cx
		dy = cand_cy - pred_cy
		dist = math.sqrt(dx * dx + dy * dy)
		predict_score = 1.0 - dist / max_search_radius
		predict_score = max(0.0, min(1.0, predict_score))

		# Color score
		color_score = _compute_color_score(appearance)

		# Size score: log-height difference
		if cand_h > 0:
			cand_log_h = math.log(cand_h)
		else:
			cand_log_h = pred_log_h
		log_h_diff = abs(cand_log_h - pred_log_h)
		size_score = 1.0 - log_h_diff / size_tolerance
		size_score = max(0.0, min(1.0, size_score))

		# Weighted sum
		total = (
			w_detect * detect_score
			+ w_predict * predict_score
			+ w_color * color_score
			+ w_size * size_score
			+ w_path * path_score
			+ w_motion * motion_score
		)

		# Build scored candidate (copy original and add score)
		scored_cand = dict(cand)
		scored_cand["score"] = total
		scored.append(scored_cand)

	return scored


#============================================
def _compute_color_score(appearance: dict | None) -> float:
	"""Compute color similarity score from appearance data.

	Without a frame available, this returns a default value.
	Full histogram comparison can be added later.

	Args:
		appearance: Optional appearance dict with "jersey_hsv" key.

	Returns:
		Float color score between 0 and 1.
	"""
	# Without appearance data or frame, default to neutral score
	if appearance is None:
		return 0.5
	# Placeholder: frame-based color comparison not yet available
	return 0.5


#============================================
def select_best(scored_candidates: list) -> dict | None:
	"""Return the candidate with the highest score.

	Args:
		scored_candidates: List of candidate dicts each containing a "score" key.

	Returns:
		The highest-scoring candidate dict, or None if the list is empty.
	"""
	if not scored_candidates:
		return None
	best = max(scored_candidates, key=lambda c: c["score"])
	return best
