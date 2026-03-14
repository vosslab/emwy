"""Unit tests for track_runner.hypothesis and box_utils modules."""

# PIP3 modules
import numpy

# local repo modules
import box_utils
import track_runner.hypothesis as hyp_mod
import hypothesis

from tr_test_helpers import _make_appearance_model


# ============================================================
# basic hypothesis tests
# ============================================================


#============================================
def test_hypothesis_compute_iou_identical_boxes() -> None:
	"""IoU of identical boxes is 1.0."""
	box = {"cx": 100.0, "cy": 100.0, "w": 40.0, "h": 80.0}
	iou = box_utils.compute_iou(box, box)
	assert abs(iou - 1.0) < 1e-6


#============================================
def test_hypothesis_compute_iou_non_overlapping() -> None:
	"""Non-overlapping boxes yield IoU of 0.0."""
	box_a = {"cx": 100.0, "cy": 100.0, "w": 40.0, "h": 80.0}
	box_b = {"cx": 500.0, "cy": 500.0, "w": 40.0, "h": 80.0}
	iou = box_utils.compute_iou(box_a, box_b)
	assert iou == 0.0


#============================================
def test_hypothesis_detection_to_state_converts_to_center_format() -> None:
	"""_detection_to_state converts top-left bbox to center format."""
	# top-left origin: x=80, y=160, w=40, h=80 -> center cx=100, cy=200
	detection = {"bbox": [80, 160, 40, 80], "score": 0.7}
	state = hyp_mod._detection_to_state(detection)
	assert abs(state["cx"] - 100.0) < 1e-6
	assert abs(state["cy"] - 200.0) < 1e-6
	assert abs(state["w"] - 40.0) < 1e-6
	assert abs(state["h"] - 80.0) < 1e-6


#============================================
def test_hypothesis_generate_competitors_excludes_target() -> None:
	"""generate_competitors does not return competitor overlapping the target."""
	frame = numpy.zeros((480, 640, 3), dtype=numpy.uint8)
	target = {"cx": 320.0, "cy": 240.0, "w": 40.0, "h": 80.0, "conf": 0.9, "source": "propagated"}
	appearance_model = {"template": None, "hsv_mean": (0.0, 0.0, 0.0), "scale": 80.0}
	# detection that overlaps heavily with target -> should be excluded
	detections = [
		{"bbox": [295.0, 195.0, 50.0, 90.0], "score": 0.8},
	]
	competitors = hyp_mod.generate_competitors(frame, target, detections, appearance_model)
	# none of the competitors should have near-identical position to target
	for comp in competitors:
		iou = hyp_mod._compute_iou(comp, target)
		assert iou < hyp_mod.TARGET_OVERLAP_IOU + 0.01


#============================================
def test_hypothesis_compute_identity_score_small_box_neutral() -> None:
	"""compute_identity_score returns 0.5 for very small bbox (h < 30)."""
	frame = numpy.zeros((200, 200, 3), dtype=numpy.uint8)
	state = {"cx": 100.0, "cy": 100.0, "w": 10.0, "h": 15.0}
	appearance_model = {
		"template": None,
		"hsv_mean": (90.0, 200.0, 180.0),
		"scale": 80.0,
	}
	score = hyp_mod.compute_identity_score(frame, state, appearance_model)
	assert abs(score - 0.5) < 1e-6


# ============================================================
# HSV histogram identity scoring
# ============================================================


#============================================
def test_identity_score_same_color_large():
	"""Large runner with same color scores high (>0.7)."""
	# blue jersey: BGR (180, 50, 50)
	blue_bgr = (180, 50, 50)
	model = _make_appearance_model(blue_bgr, size=80)
	# build a frame with the same blue patch at center
	frame = numpy.zeros((200, 200, 3), dtype=numpy.uint8)
	frame[60:140, 60:140] = blue_bgr
	state = {"cx": 100.0, "cy": 100.0, "w": 80.0, "h": 80.0}
	score = hypothesis.compute_identity_score(frame, state, model)
	assert score > 0.7, f"same color large runner scored {score}, expected >0.7"


#============================================
def test_identity_score_different_color_large():
	"""Large runner with different color scores lower than same color."""
	# blue jersey model
	blue_bgr = (180, 50, 50)
	model = _make_appearance_model(blue_bgr, size=80)
	# red jersey in the frame: BGR (50, 50, 200)
	red_bgr = (50, 50, 200)
	frame = numpy.zeros((200, 200, 3), dtype=numpy.uint8)
	frame[60:140, 60:140] = red_bgr
	state = {"cx": 100.0, "cy": 100.0, "w": 80.0, "h": 80.0}
	score_diff = hypothesis.compute_identity_score(frame, state, model)
	# same color for comparison
	frame_same = numpy.zeros((200, 200, 3), dtype=numpy.uint8)
	frame_same[60:140, 60:140] = blue_bgr
	score_same = hypothesis.compute_identity_score(frame_same, state, model)
	assert score_same > score_diff, (
		f"same-color score {score_same} should exceed diff-color {score_diff}"
	)


#============================================
def test_identity_score_small_runner_neutral():
	"""Runner below 30px returns neutral 0.5."""
	blue_bgr = (180, 50, 50)
	model = _make_appearance_model(blue_bgr, size=80)
	frame = numpy.zeros((200, 200, 3), dtype=numpy.uint8)
	frame[90:110, 90:110] = blue_bgr
	# 20px tall runner
	state = {"cx": 100.0, "cy": 100.0, "w": 20.0, "h": 20.0}
	score = hypothesis.compute_identity_score(frame, state, model)
	assert score == 0.5, f"small runner scored {score}, expected 0.5"


#============================================
def test_identity_score_medium_runner_uses_mean_hsv():
	"""Runner 30-60px uses mean-HSV (not histogram)."""
	blue_bgr = (180, 50, 50)
	model = _make_appearance_model(blue_bgr, size=80)
	frame = numpy.zeros((200, 200, 3), dtype=numpy.uint8)
	frame[75:125, 75:125] = blue_bgr
	# 50px tall runner: medium range
	state = {"cx": 100.0, "cy": 100.0, "w": 50.0, "h": 50.0}
	score = hypothesis.compute_identity_score(frame, state, model)
	# same color should score reasonably well even with mean-HSV
	assert score > 0.5, f"medium same-color runner scored {score}, expected >0.5"


#============================================
def test_histogram_bins_constant():
	"""MIN_HISTOGRAM_BINS is set to 50."""
	assert hypothesis.MIN_HISTOGRAM_BINS == 50


# ============================================================
# occlusion-risk flagging
# ============================================================


#============================================
def test_occlusion_risk_no_overlap():
	"""No occlusion risk when detections are far from target."""
	target = {"cx": 100.0, "cy": 100.0, "w": 50.0, "h": 100.0}
	# detection far away
	detections = [
		{"bbox": [500, 100, 50, 100], "confidence": 0.9, "class_id": 0},
	]
	risk = hypothesis.compute_occlusion_risk(target, detections)
	assert risk is False


#============================================
def test_occlusion_risk_with_overlap():
	"""Occlusion risk detected when nearby detection overlaps target."""
	target = {"cx": 100.0, "cy": 100.0, "w": 50.0, "h": 100.0}
	# detection overlapping partially (not the target itself)
	# target covers x=[75,125], y=[50,150]
	# detection covers x=[100,160], y=[50,150]: overlap but not high IoU
	detections = [
		{"bbox": [100, 50, 60, 100], "confidence": 0.8, "class_id": 0},
	]
	risk = hypothesis.compute_occlusion_risk(target, detections)
	assert risk is True


#============================================
def test_occlusion_risk_skips_target_itself():
	"""Detection with very high IoU (the target) is skipped."""
	target = {"cx": 100.0, "cy": 100.0, "w": 50.0, "h": 100.0}
	# detection nearly identical to target (IoU ~1.0)
	detections = [
		{"bbox": [75, 50, 50, 100], "confidence": 0.95, "class_id": 0},
	]
	risk = hypothesis.compute_occlusion_risk(target, detections)
	# high-IoU detection is the target itself, should be skipped
	assert risk is False


#============================================
def test_occlusion_iou_threshold():
	"""OCCLUSION_RISK_IOU is set to 0.15."""
	assert hypothesis.OCCLUSION_RISK_IOU == 0.15
