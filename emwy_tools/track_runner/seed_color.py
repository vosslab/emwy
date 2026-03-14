"""Color and seed candidate extraction utilities.

Provides functions for extracting color features (jersey color, histograms)
from video frames and generating seed candidates from YOLO detections.
"""

# PIP3 modules
import cv2
import numpy

#============================================

def _clamp_box(frame: numpy.ndarray, box: list) -> tuple:
	"""Clamp a box to frame bounds and return the ROI.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		box: Rectangle as [x, y, w, h] in pixel coordinates.

	Returns:
		Cropped ROI as a numpy array, or None if the clamped region is empty.
	"""
	frame_h, frame_w = frame.shape[:2]
	x, y, w, h = box
	# clamp top-left corner to frame bounds
	x1 = max(0, int(x))
	y1 = max(0, int(y))
	# clamp bottom-right corner to frame bounds
	x2 = min(frame_w, int(x + w))
	y2 = min(frame_h, int(y + h))
	# check for empty region after clamping
	if x2 <= x1 or y2 <= y1:
		return None
	roi = frame[y1:y2, x1:x2]
	return roi


#============================================

def extract_jersey_color(frame: numpy.ndarray, box: list) -> tuple:
	"""Extract median HSV color from a rectangular region.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		box: Rectangle as [x, y, w, h] in pixel coordinates.

	Returns:
		Tuple of (h_median, s_median, v_median) as ints,
		or (0, 0, 0) if the box is out of frame bounds.
	"""
	# clamp box to frame bounds and extract ROI
	roi = _clamp_box(frame, box)
	if roi is None:
		return (0, 0, 0)
	# convert from BGR to HSV color space
	hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
	# compute median for each HSV channel
	h_median = int(numpy.median(hsv_roi[:, :, 0]))
	s_median = int(numpy.median(hsv_roi[:, :, 1]))
	v_median = int(numpy.median(hsv_roi[:, :, 2]))
	return (h_median, s_median, v_median)


#============================================

def extract_color_histogram(frame: numpy.ndarray, box: list) -> numpy.ndarray:
	"""Extract a normalized 2D color histogram from a rectangular region.

	Computes a joint histogram over the H and S channels of the HSV
	color space for the specified region.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		box: Rectangle as [x, y, w, h] in pixel coordinates.

	Returns:
		Normalized 2D histogram array with shape (30, 32).
	"""
	# clamp box to frame bounds and extract ROI
	roi = _clamp_box(frame, box)
	if roi is None:
		# return a zero histogram for out-of-bounds regions
		return numpy.zeros((30, 32), dtype=numpy.float32)
	# convert from BGR to HSV
	hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
	# compute 2D histogram on H and S channels
	# H range is 0-180 in OpenCV, S range is 0-256
	hist = cv2.calcHist(
		[hsv_roi], [0, 1], None,
		[30, 32], [0, 180, 0, 256],
	)
	# normalize the histogram so values sum to 1
	cv2.normalize(hist, hist, alpha=1.0, norm_type=cv2.NORM_L1)
	return hist


#============================================

def detection_to_torso_box(bbox: list) -> list:
	"""Extract upper 60% of detection bbox as torso region.

	Args:
		bbox: Bounding box as [x, y, w, h] in pixel coordinates.

	Returns:
		Torso box as [x, y, w, h] representing the upper 60% of bbox.
	"""
	x, y, w, h = bbox
	torso_h = int(h * 0.6)
	return [x, y, w, torso_h]


#============================================

def suggest_seed_candidates(
	frame: numpy.ndarray,
	detections: list,
	confirmed_seeds: list,
	frame_index: int,
) -> dict:
	"""Suggest seed candidates from YOLO detections.

	Analyzes detections and confirmed seeds to suggest the best
	candidate for seeding, or returns candidates for manual selection.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		detections: List of detection dicts from YoloDetector with
			keys: bbox, confidence, class_id.
		confirmed_seeds: List of already-seeded dicts with jersey_hsv
			and optionally histogram.
		frame_index: Current frame index for reference.

	Returns:
		Dict with keys:
			candidates: List of candidate dicts with keys bbox,
				torso_box, histogram, detection_confidence.
			suggestion_index: Index in candidates for auto-highlight
				(None if manual mode).
			mode: "none" (no detections), "manual" (no single best),
				or "single" (exactly one detection).
			scores: List of Bhattacharyya distances (lower = better match)
				or None if no confirmed seeds.
	"""
	# no detections: return empty candidates
	if not detections:
		return {
			"candidates": [],
			"suggestion_index": None,
			"mode": "none",
			"scores": None,
		}

	# build candidate list with torso regions and histograms
	candidates = []
	for det in detections:
		bbox = det["bbox"]
		torso_box = detection_to_torso_box(bbox)
		# extract histogram from torso region
		hist = extract_color_histogram(frame, torso_box)
		candidate = {
			"bbox": bbox,
			"torso_box": torso_box,
			"histogram": hist,
			"detection_confidence": det["confidence"],
		}
		candidates.append(candidate)

	# if no confirmed seeds: return manual mode (let user pick)
	if not confirmed_seeds:
		return {
			"candidates": candidates,
			"suggestion_index": None,
			"mode": "manual" if len(candidates) > 1 else "single",
			"scores": None,
		}

	# exactly one detection: auto-suggest it
	if len(candidates) == 1:
		return {
			"candidates": candidates,
			"suggestion_index": 0,
			"mode": "single",
			"scores": [0.0],
		}

	# multiple detections with confirmed seeds: rank by histogram match
	# build reference histogram from confirmed seeds
	ref_hists = []
	for seed in confirmed_seeds:
		if "histogram" in seed:
			# convert back to float32 ndarray if stored as Python list
			hist_val = seed["histogram"]
			if not isinstance(hist_val, numpy.ndarray):
				hist_val = numpy.array(hist_val, dtype=numpy.float32)
			elif hist_val.dtype != numpy.float32:
				hist_val = hist_val.astype(numpy.float32)
			ref_hists.append(hist_val)
	# if no stored histograms in confirmed seeds, fall back to manual mode
	if not ref_hists:
		return {
			"candidates": candidates,
			"suggestion_index": None,
			"mode": "manual",
			"scores": None,
		}

	# average reference histograms
	ref_hist = ref_hists[0]
	if len(ref_hists) > 1:
		avg_hist = numpy.zeros_like(ref_hists[0])
		for h in ref_hists:
			avg_hist += h
		avg_hist = avg_hist / len(ref_hists)
		ref_hist = avg_hist

	# ensure ref_hist is float32 for compareHist
	ref_hist = ref_hist.astype(numpy.float32)

	# compute Bhattacharyya distances from each candidate to reference
	scores = []
	for candidate in candidates:
		cand_hist = candidate["histogram"]
		# ensure candidate histogram is float32 ndarray
		if not isinstance(cand_hist, numpy.ndarray):
			cand_hist = numpy.array(cand_hist, dtype=numpy.float32)
		elif cand_hist.dtype != numpy.float32:
			cand_hist = cand_hist.astype(numpy.float32)
		distance = cv2.compareHist(
			cand_hist, ref_hist, cv2.HISTCMP_BHATTACHARYYA
		)
		scores.append(distance)

	# find best match (lowest distance)
	best_idx = int(numpy.argmin(scores))
	best_score = scores[best_idx]

	# auto-suggest if best score is good AND gap to second-best is large
	# thresholds: distance < 0.5 (strong match) and gap > 0.15
	suggestion_idx = None
	if len(candidates) > 1:
		second_best = sorted(scores)[1]
		gap = second_best - best_score
		if best_score < 0.5 and gap > 0.15:
			suggestion_idx = best_idx
	elif best_score < 0.5:
		# single candidate with good score
		suggestion_idx = best_idx

	mode_str = "auto" if suggestion_idx is not None else "manual"

	return {
		"candidates": candidates,
		"suggestion_index": suggestion_idx,
		"mode": mode_str,
		"scores": scores,
	}


#============================================

def normalize_seed_box(box: list, config: dict) -> list:
	"""Normalize an inconsistently-drawn seed box.

	Enforces minimum dimensions and clamps the aspect ratio
	to the configured torso range.

	Args:
		box: Rectangle as [x, y, w, h] in pixel coordinates.
		config: Configuration dict optionally containing seeding section.

	Returns:
		Normalized [x, y, w, h] as integers.
	"""
	x, y, w, h = box
	# enforce minimum dimensions of 10 pixels
	w = max(w, 10)
	h = max(h, 10)
	# read aspect ratio limits from config; v2 config uses flat processing section
	processing = config.get("processing", config.get("settings", {}).get("seeding", {}))
	aspect_min = float(processing.get("torso_aspect_min", 0.3))
	aspect_max = float(processing.get("torso_aspect_max", 0.8))
	# compute current aspect ratio (width / height)
	aspect = w / h
	if aspect > aspect_max:
		# too wide, shrink width to match max aspect
		w = int(h * aspect_max)
	elif aspect < aspect_min:
		# too narrow, shrink height to match min aspect
		h = int(w / aspect_min)
	return [int(x), int(y), int(w), int(h)]


#============================================

def _build_seed_dict(
	frame_idx: int,
	time_sec: float,
	torso_box: list,
	jersey_hsv: tuple,
	pass_number: int,
	mode: str,
	histogram: numpy.ndarray | None = None,
) -> dict:
	"""Build a v2 seed dict from collected fields.

	Args:
		frame_idx: Frame index (0-based).
		time_sec: Time in seconds.
		torso_box: Normalized torso box as [x, y, w, h].
		jersey_hsv: Tuple of (h, s, v) median HSV values.
		pass_number: Which collection pass this seed came from (1 = initial).
		mode: Seed collection mode string.
		histogram: Optional 2D HS histogram for color matching.

	Returns:
		Seed dict in v2 format with frame, time_s, torso_box, jersey_hsv,
		cx, cy, w, h, pass, source, mode, and optionally histogram keys.
	"""
	tx, ty, tw, th = torso_box
	# compute center format for propagator compatibility
	cx = float(tx + tw / 2.0)
	cy = float(ty + th / 2.0)
	seed = {
		"frame_index": frame_idx,
		"frame": frame_idx,
		"time_s": round(time_sec, 3),
		"torso_box": torso_box,
		"jersey_hsv": list(jersey_hsv),
		"cx": cx,
		"cy": cy,
		"w": float(tw),
		"h": float(th),
		"pass": pass_number,
		"conf": None,
		"source": "human",
		"mode": mode,
		"status": "visible",
	}
	# add histogram if provided (convert ndarray to list for JSON serialization)
	if histogram is not None:
		seed["histogram"] = histogram.tolist()
	return seed
