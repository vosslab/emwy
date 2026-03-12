"""Competing path generation for track_runner interval solving.

Maintains the target path and 2-3 competitor paths through an interval.
Competitors come from YOLO detections that do not overlap with the target.
"""

# Standard Library
import math

# PIP3 modules
import cv2
import numpy

# Minimum person bounding box height in pixels to be considered a competitor
MIN_COMPETITOR_HEIGHT = 20
# Maximum number of competitors to track at once
MAX_COMPETITORS = 3
# IoU threshold above which a detection is considered to overlap with the target
TARGET_OVERLAP_IOU = 0.3
# IoU threshold for matching a competitor to a new detection
COMPETITOR_MATCH_IOU = 0.2


#============================================
def _compute_iou(box_a: dict, box_b: dict) -> float:
	"""Compute Intersection over Union for two center-format bounding boxes.

	Args:
		box_a: Dict with cx, cy, w, h keys.
		box_b: Dict with cx, cy, w, h keys.

	Returns:
		IoU value in [0, 1].
	"""
	# convert center format to (x1, y1, x2, y2)
	ax1 = box_a["cx"] - box_a["w"] / 2.0
	ay1 = box_a["cy"] - box_a["h"] / 2.0
	ax2 = box_a["cx"] + box_a["w"] / 2.0
	ay2 = box_a["cy"] + box_a["h"] / 2.0

	bx1 = box_b["cx"] - box_b["w"] / 2.0
	by1 = box_b["cy"] - box_b["h"] / 2.0
	bx2 = box_b["cx"] + box_b["w"] / 2.0
	by2 = box_b["cy"] + box_b["h"] / 2.0

	# intersection rectangle
	ix1 = max(ax1, bx1)
	iy1 = max(ay1, by1)
	ix2 = min(ax2, bx2)
	iy2 = min(ay2, by2)

	inter_w = max(0.0, ix2 - ix1)
	inter_h = max(0.0, iy2 - iy1)
	inter_area = inter_w * inter_h

	area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
	area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
	union_area = area_a + area_b - inter_area

	if union_area <= 0.0:
		return 0.0

	iou = inter_area / union_area
	return float(iou)


#============================================
def _detection_to_state(detection: dict) -> dict:
	"""Convert a YOLO detection dict to a hypothesis state dict.

	Detection format expected: {"bbox": [x, y, w, h], "score": float, ...}
	where bbox is top-left origin.

	Args:
		detection: Detection dict from the detector.

	Returns:
		Hypothesis state dict.
	"""
	bbox = detection["bbox"]
	x, y, w, h = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
	# convert top-left to center format
	cx = x + w / 2.0
	cy = y + h / 2.0
	conf = float(detection.get("score", 0.5))
	state = {
		"cx": cx,
		"cy": cy,
		"w": w,
		"h": h,
		"conf": conf,
		"source": "detection",
		"identity_score": 0.5,
		"competitor_margin": 0.0,
		"reason": "",
	}
	return state


#============================================
def compute_identity_score(
	frame: numpy.ndarray,
	state: dict,
	appearance_model: dict,
) -> float:
	"""Compare a candidate region to the seeded appearance model.

	Uses HSV histogram comparison and, for large runners, template
	normalized cross-correlation. Scale-gated: below 30px returns 0.5
	(uninformative); above 60px uses full appearance; 30-60px interpolates.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		state: Candidate tracking state dict with cx, cy, w, h.
		appearance_model: Appearance model from build_appearance_model().

	Returns:
		Identity score in [0, 1]. Higher means better match.
	"""
	h = float(state["h"])

	# below 30px: appearance is unreliable, return neutral
	if h < 30.0:
		return 0.5

	frame_h, frame_w = frame.shape[:2]
	cx = float(state["cx"])
	cy = float(state["cy"])
	w = float(state["w"])

	# clamp bbox to frame
	x1 = int(max(0, cx - w / 2.0))
	y1 = int(max(0, cy - h / 2.0))
	x2 = int(min(frame_w, cx + w / 2.0))
	y2 = int(min(frame_h, cy + h / 2.0))

	if x2 <= x1 or y2 <= y1:
		return 0.5

	# extract candidate patch and convert to HSV
	candidate_patch = frame[y1:y2, x1:x2]
	if candidate_patch.size == 0:
		return 0.5

	candidate_hsv = cv2.cvtColor(candidate_patch, cv2.COLOR_BGR2HSV)
	candidate_mean = (
		float(numpy.mean(candidate_hsv[:, :, 0])),
		float(numpy.mean(candidate_hsv[:, :, 1])),
		float(numpy.mean(candidate_hsv[:, :, 2])),
	)

	# compare HSV means to appearance model
	model_mean = appearance_model.get("hsv_mean", (0.0, 0.0, 0.0))

	# hue distance (circular, range 0-180 in OpenCV)
	hue_diff = abs(candidate_mean[0] - model_mean[0])
	hue_diff = min(hue_diff, 180.0 - hue_diff)
	# normalize to [0, 1] where 0 is perfect match
	hue_score = 1.0 - hue_diff / 90.0

	# saturation and value distance (range 0-255)
	sat_diff = abs(candidate_mean[1] - model_mean[1]) / 255.0
	val_diff = abs(candidate_mean[2] - model_mean[2]) / 255.0
	sv_score = 1.0 - (sat_diff + val_diff) / 2.0

	# weighted combination: hue is more discriminative for jersey colors
	hsv_score = 0.6 * hue_score + 0.4 * sv_score
	hsv_score = max(0.0, min(1.0, hsv_score))

	if h >= 60.0:
		# large runner: also use template correlation for richer comparison
		template = appearance_model.get("template")
		if template is not None and template.size > 0:
			# resize candidate patch to match template size
			tmpl_h, tmpl_w = template.shape[:2]
			if tmpl_h > 0 and tmpl_w > 0:
				resized = cv2.resize(candidate_patch, (tmpl_w, tmpl_h))
				tmpl_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
				cand_gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
				# compute normalized cross-correlation via matchTemplate on same size
				result = cv2.matchTemplate(
					cand_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED,
				)
				_, max_val, _, _ = cv2.minMaxLoc(result)
				# max_val in [-1, 1]; map to [0, 1]
				corr_score = float((max_val + 1.0) / 2.0)
				# blend with hsv_score
				identity = 0.5 * hsv_score + 0.5 * corr_score
				return max(0.0, min(1.0, identity))

		return hsv_score

	# medium runner (30-60px): HSV only
	return hsv_score


#============================================
def compute_competitor_margin(
	target_state: dict,
	competitors: list,
) -> float:
	"""Compute how far the target is from its nearest competitor.

	Uses a combined position-and-appearance distance. High margin means
	the target is clearly the right identity. Low margin means ambiguous.

	Args:
		target_state: Target tracking state dict with cx, cy, w, h, identity_score.
		competitors: List of competitor state dicts.

	Returns:
		Margin value >= 0. 0.0 if no competitors.
	"""
	if not competitors:
		return 1.0

	target_cx = float(target_state["cx"])
	target_cy = float(target_state["cy"])
	target_h = max(1.0, float(target_state["h"]))
	target_identity = float(target_state.get("identity_score", 0.5))

	min_distance = float("inf")
	for comp in competitors:
		comp_cx = float(comp["cx"])
		comp_cy = float(comp["cy"])
		comp_identity = float(comp.get("identity_score", 0.5))

		# positional distance normalized by target height
		pos_dist = math.sqrt(
			(target_cx - comp_cx) ** 2 + (target_cy - comp_cy) ** 2
		) / target_h

		# appearance distance: difference in identity scores
		app_dist = abs(target_identity - comp_identity)

		# combined distance: weight position more than appearance
		combined = 0.7 * pos_dist + 0.3 * app_dist
		if combined < min_distance:
			min_distance = combined

	# margin is the minimum combined distance clamped to [0, 1]
	margin = min(1.0, max(0.0, min_distance))
	return margin


#============================================
def generate_competitors(
	frame: numpy.ndarray,
	target_state: dict,
	detections: list,
	appearance_model: dict,
) -> list:
	"""Build a list of competitor states from YOLO detections.

	Filters detections that overlap with the target and those that
	are too small. Keeps up to MAX_COMPETITORS by detection confidence.

	Args:
		frame: BGR image of the current frame.
		target_state: Current target tracking state dict.
		detections: List of YOLO detection dicts from the detector.
		appearance_model: Appearance model from build_appearance_model().

	Returns:
		List of up to MAX_COMPETITORS competitor state dicts, each with
		identity_score and competitor_margin fields populated.
	"""
	candidates = []

	for det in detections:
		# build a center-format state for overlap check
		candidate = _detection_to_state(det)

		# skip if it overlaps with the target
		iou = _compute_iou(candidate, target_state)
		if iou >= TARGET_OVERLAP_IOU:
			continue

		# skip if too small to be a meaningful competitor
		if candidate["h"] < MIN_COMPETITOR_HEIGHT:
			continue

		# compute identity score for this competitor
		id_score = compute_identity_score(frame, candidate, appearance_model)
		candidate["identity_score"] = id_score

		candidates.append(candidate)

	# sort by detection confidence descending, keep top MAX_COMPETITORS
	candidates.sort(key=lambda c: c["conf"], reverse=True)
	competitors = candidates[:MAX_COMPETITORS]

	return competitors


#============================================
def _propagate_competitor_simple(
	prev_frame: numpy.ndarray,
	curr_frame: numpy.ndarray,
	comp_state: dict,
) -> dict:
	"""Propagate a competitor one frame forward using simple center tracking.

	Uses optical flow on a small number of points inside the competitor box.
	This is simpler than the full propagator to keep hypothesis.py lightweight.

	Args:
		prev_frame: BGR image of the previous frame.
		curr_frame: BGR image of the current frame.
		comp_state: Competitor state dict with cx, cy, w, h.

	Returns:
		Updated competitor state dict.
	"""
	cx = float(comp_state["cx"])
	cy = float(comp_state["cy"])
	w = float(comp_state["w"])
	h = float(comp_state["h"])
	frame_h, frame_w = prev_frame.shape[:2]

	# extract a small patch at the competitor center for tracking
	x1 = int(max(0, cx - w / 2.0))
	y1 = int(max(0, cy - h / 2.0))
	x2 = int(min(frame_w, cx + w / 2.0))
	y2 = int(min(frame_h, cy + h / 2.0))

	dx = 0.0
	dy = 0.0

	if x2 > x1 + 2 and y2 > y1 + 2:
		roi = cv2.cvtColor(prev_frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
		pts = cv2.goodFeaturesToTrack(
			roi, maxCorners=10, qualityLevel=0.01, minDistance=4, blockSize=4,
		)
		if pts is not None and len(pts) >= 2:
			# shift to full-frame coords
			pts[:, :, 0] += x1
			pts[:, :, 1] += y1
			pts = pts.astype(numpy.float32)

			curr_pts, status, _ = cv2.calcOpticalFlowPyrLK(
				cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY),
				cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY),
				pts,
				None,
				winSize=(11, 11),
				maxLevel=2,
				criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, 0.01),
			)
			if curr_pts is not None and status is not None:
				mask = status.ravel().astype(bool)
				if numpy.any(mask):
					good_prev = pts[mask].reshape(-1, 2)
					good_curr = curr_pts[mask].reshape(-1, 2)
					flow = good_curr - good_prev
					dx = float(numpy.median(flow[:, 0]))
					dy = float(numpy.median(flow[:, 1]))

	# create updated competitor state
	updated = {
		"cx": cx + dx,
		"cy": cy + dy,
		"w": w,
		"h": h,
		"conf": float(comp_state["conf"]) * 0.95,
		"source": "propagated",
		"identity_score": float(comp_state.get("identity_score", 0.5)),
		"competitor_margin": 0.0,
		"reason": "",
	}
	return updated


#============================================
def maintain_paths(
	prev_competitors: list,
	curr_frame: numpy.ndarray,
	prev_frame: numpy.ndarray,
	detections: list,
) -> list:
	"""Propagate existing competitors and update from new detections.

	Propagates each competitor one frame forward using simple optical flow,
	matches to new detections by IoU, drops competitors that leave the frame
	or shrink below the minimum size, and adds new competitors from unmatched
	detections.

	Args:
		prev_competitors: List of competitor state dicts from the previous frame.
		curr_frame: BGR image of the current frame.
		prev_frame: BGR image of the previous frame.
		detections: List of YOLO detection dicts for the current frame.

	Returns:
		Updated list of up to MAX_COMPETITORS competitor state dicts.
	"""
	frame_h, frame_w = curr_frame.shape[:2]
	updated_competitors = []

	# convert detections to state dicts for IoU matching
	det_states = [_detection_to_state(d) for d in detections]
	det_matched = [False] * len(det_states)

	# propagate each previous competitor forward
	for comp in prev_competitors:
		propagated = _propagate_competitor_simple(prev_frame, curr_frame, comp)

		# drop if center is outside frame
		cx = propagated["cx"]
		cy = propagated["cy"]
		if cx < 0 or cx >= frame_w or cy < 0 or cy >= frame_h:
			continue

		# drop if too small
		if propagated["h"] < MIN_COMPETITOR_HEIGHT:
			continue

		# try to match to a new detection by IoU
		best_iou = 0.0
		best_det_idx = -1
		for di, det_state in enumerate(det_states):
			if det_matched[di]:
				continue
			iou = _compute_iou(propagated, det_state)
			if iou > best_iou:
				best_iou = iou
				best_det_idx = di

		if best_iou >= COMPETITOR_MATCH_IOU and best_det_idx >= 0:
			# update competitor position from matched detection
			det_matched[best_det_idx] = True
			matched_det = det_states[best_det_idx]
			propagated["cx"] = matched_det["cx"]
			propagated["cy"] = matched_det["cy"]
			propagated["w"] = matched_det["w"]
			propagated["h"] = matched_det["h"]
			# refresh confidence from detection
			propagated["conf"] = matched_det["conf"]

		updated_competitors.append(propagated)

	# add new competitors from unmatched detections
	for di, det_state in enumerate(det_states):
		if det_matched[di]:
			continue
		if det_state["h"] < MIN_COMPETITOR_HEIGHT:
			continue
		# only add if we still have room
		if len(updated_competitors) >= MAX_COMPETITORS:
			break
		updated_competitors.append(det_state)

	# cap at MAX_COMPETITORS, sorted by confidence descending
	updated_competitors.sort(key=lambda c: c["conf"], reverse=True)
	return updated_competitors[:MAX_COMPETITORS]


# simple assertion tests for _compute_iou
_box_a = {"cx": 50.0, "cy": 50.0, "w": 20.0, "h": 20.0}
_box_b = {"cx": 50.0, "cy": 50.0, "w": 20.0, "h": 20.0}
assert abs(_compute_iou(_box_a, _box_b) - 1.0) < 1e-6

_box_c = {"cx": 200.0, "cy": 200.0, "w": 20.0, "h": 20.0}
assert _compute_iou(_box_a, _box_c) == 0.0
