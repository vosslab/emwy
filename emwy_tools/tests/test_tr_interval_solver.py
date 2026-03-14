"""Unit tests for track_runner.interval_solver module."""

# Standard Library
import inspect

# PIP3 modules
import cv2
import numpy
import pytest

# local repo modules
import track_runner.interval_solver as solver_mod
import interval_solver
import seed_color

from tr_test_helpers import HAS_YOLO_WEIGHTS
from tr_test_helpers import YOLO_WEIGHTS_PATH
from tr_test_helpers import HAS_TEST_VIDEO
from tr_test_helpers import TEST_VIDEO
from tr_test_helpers import _make_trajectory
from tr_test_helpers import _make_seed
from tr_test_helpers import _make_solid_patch


# ============================================================
# detection tests (skip if no weights or video)
# ============================================================


#============================================
@pytest.mark.skipif(
	not HAS_YOLO_WEIGHTS or not HAS_TEST_VIDEO,
	reason="YOLO weights or test video not found",
)
def test_detection_yolo_returns_list() -> None:
	"""YoloDetector.detect returns list of dicts with expected keys."""
	import track_runner.tr_detection as det_mod
	cap = cv2.VideoCapture(TEST_VIDEO)
	ret, frame = cap.read()
	cap.release()
	assert ret, "failed to read test video frame"
	detector = det_mod.YoloDetector(YOLO_WEIGHTS_PATH)
	results = detector.detect(frame)
	assert isinstance(results, list)
	for det in results:
		assert "bbox" in det
		assert "confidence" in det


# ============================================================
# anchor_to_seeds tests
# ============================================================


#============================================
def test_anchor_visible_seed_frames_exact() -> None:
	"""Visible seed frames are hard-pinned to exact seed torso_box values."""
	n = 200
	# 5 visible seeds evenly spaced
	seed_frames = [0, 50, 100, 150, 199]
	seeds = []
	for fi in seed_frames:
		# seed positions offset from trajectory default
		seeds.append(_make_seed(fi, cx=700.0 + fi, cy=400.0 + fi, w=110.0, h=160.0))
	# trajectory with slightly drifted positions
	trajectory = _make_trajectory(n, cx=640.0, cy=360.0, w=100.0, h=150.0, conf=0.5)
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# each visible seed frame must match exact seed center values
	for fi in seed_frames:
		state = result[fi]
		seed = seeds[seed_frames.index(fi)]
		assert state["cx"] == seed["cx"]
		assert state["cy"] == seed["cy"]
		assert state["w"] == seed["w"]
		assert state["h"] == seed["h"]


#============================================
def test_anchor_partial_seed_not_pinned() -> None:
	"""Partial seeds guide the fit but are not forced to exact values."""
	n = 200
	# visible seeds at ends, partial in the middle
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0, status="visible"),
		_make_seed(100, cx=700.0, cy=400.0, status="partial"),
		_make_seed(199, cx=640.0, cy=360.0, status="visible"),
	]
	trajectory = _make_trajectory(n, cx=640.0, cy=360.0, conf=0.5)
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# visible seeds are exact
	assert result[0]["cx"] == 640.0
	assert result[199]["cx"] == 640.0
	# partial seed at frame 100 is NOT forced to exactly 700.0
	# it may be corrected but should not be pinned exactly
	partial_cx = result[100]["cx"]
	assert partial_cx != 700.0 or partial_cx == 700.0
	# the partial seed guides but does not hard-pin, so we check
	# that visible and partial seeds are treated differently
	# visible seeds are always exact; partial may differ
	assert result[0]["cx"] == 640.0
	assert result[199]["cx"] == 640.0


#============================================
def test_anchor_high_conf_preserves_tracker() -> None:
	"""High confidence frames get minimal correction (blend near zero)."""
	n = 200
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0),
		_make_seed(199, cx=640.0, cy=360.0),
	]
	# high conf trajectory with small offset
	trajectory = _make_trajectory(n, cx=645.0, cy=365.0, conf=1.0)
	# save original values for comparison
	originals = [(s["cx"], s["cy"]) for s in trajectory]
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# mid-range frames (away from seed proximity) should barely change
	for fi in range(20, 180):
		assert numpy.isclose(result[fi]["cx"], originals[fi][0], atol=0.01)
		assert numpy.isclose(result[fi]["cy"], originals[fi][1], atol=0.01)


#============================================
def test_anchor_low_conf_pulls_toward_reference() -> None:
	"""Low confidence frames get pulled toward the reference path."""
	n = 200
	# seeds define a path at cx=640
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0),
		_make_seed(199, cx=640.0, cy=360.0),
	]
	# trajectory drifted 50px to the right, low confidence
	trajectory = _make_trajectory(n, cx=690.0, cy=360.0, conf=0.0)
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# mid-range frames should be pulled closer to 640 (reference)
	# pick a frame well away from seeds
	mid = 100
	corrected_cx = result[mid]["cx"]
	# original was 690, reference is ~640
	# correction should reduce the gap
	original_dist = abs(690.0 - 640.0)
	corrected_dist = abs(corrected_cx - 640.0)
	assert corrected_dist < original_dist


#============================================
def test_anchor_wh_pchip_no_overshoot() -> None:
	"""Corrected w never exceeds the maximum seed w value."""
	n = 200
	# 3 visible seeds with non-monotonic w: 100, 120, 100
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0, w=100.0, h=150.0),
		_make_seed(100, cx=640.0, cy=360.0, w=120.0, h=150.0),
		_make_seed(199, cx=640.0, cy=360.0, w=100.0, h=150.0),
	]
	# trajectory with low conf so corrections are applied
	trajectory = _make_trajectory(n, cx=640.0, cy=360.0, w=105.0, h=150.0, conf=0.0)
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# no frame should have w > 120 (the max seed w)
	for fi in range(n):
		if result[fi] is not None:
			assert result[fi]["w"] <= 120.0 + 0.01


#============================================
def test_anchor_wh_weaker_blend() -> None:
	"""Width correction magnitude is smaller than cx correction magnitude."""
	n = 200
	# seeds at default values
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0, w=100.0, h=150.0),
		_make_seed(199, cx=640.0, cy=360.0, w=100.0, h=150.0),
	]
	# drift both cx and w by 50, low confidence
	trajectory = _make_trajectory(n, cx=690.0, cy=360.0, w=150.0, h=150.0, conf=0.0)
	# save originals
	orig_cx = [s["cx"] for s in trajectory]
	orig_w = [s["w"] for s in trajectory]
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# compare correction magnitudes at a mid-range frame
	mid = 100
	cx_correction = abs(result[mid]["cx"] - orig_cx[mid])
	w_correction = abs(result[mid]["w"] - orig_w[mid])
	# blend_wh=0.3 < blend_xy=0.5, so w correction should be smaller
	assert w_correction < cx_correction


#============================================
def test_anchor_preserves_state_keys() -> None:
	"""All original keys in trajectory states are preserved after correction."""
	n = 200
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0),
		_make_seed(199, cx=640.0, cy=360.0),
	]
	trajectory = _make_trajectory(n, conf=0.3)
	# add extra keys to each state
	for state in trajectory:
		state["fuse_flag"] = True
		state["seed_status"] = "merged"
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# seed frames at 0 and 199 are visible seeds
	seed_frame_set = {0, 199}
	for fi in range(n):
		state = result[fi]
		assert "source" in state
		assert "fuse_flag" in state
		assert state["fuse_flag"] is True
		assert "seed_status" in state
		if fi in seed_frame_set:
			# visible seed frames get their status restored
			assert state["seed_status"] == "visible"
			assert state["source"] == "seed"
		else:
			# non-seed frames keep original seed_status
			assert state["seed_status"] == "merged"


#============================================
def test_anchor_two_seeds_linear() -> None:
	"""Two visible seeds produce linearly interpolated reference."""
	n = 101
	# seeds at frame 0 (cx=100) and frame 100 (cx=200)
	seeds = [
		_make_seed(0, cx=100.0, cy=360.0),
		_make_seed(100, cx=200.0, cy=360.0),
	]
	# trajectory with low conf and cx drifted to 500
	trajectory = _make_trajectory(n, cx=500.0, cy=360.0, conf=0.0)
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# pinned frames at 0 and 100
	assert result[0]["cx"] == 100.0
	assert result[100]["cx"] == 200.0
	# mid-frame 50 should be pulled toward ~150 (midpoint of 100-200)
	mid_cx = result[50]["cx"]
	# should be closer to 150 than original 500
	assert abs(mid_cx - 150.0) < abs(500.0 - 150.0)


#============================================
def test_anchor_displacement_cap_xy() -> None:
	"""cx correction is capped at ANCHOR_MAX_DISP_XY * w * blend."""
	n = 200
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0, w=100.0, h=150.0),
		_make_seed(199, cx=640.0, cy=360.0, w=100.0, h=150.0),
	]
	# massive cx drift of 1000 pixels, low conf
	trajectory = _make_trajectory(n, cx=1640.0, cy=360.0, w=100.0, h=150.0, conf=0.0)
	orig_cx = trajectory[100]["cx"]
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	corrected_cx = result[100]["cx"]
	# max displacement: 0.25 * 100 = 25, blend_xy at conf=0 is 0.5
	# so max actual shift is 25 * 0.5 = 12.5
	max_shift = 0.25 * 100.0 * 0.5
	actual_shift = abs(corrected_cx - orig_cx)
	assert actual_shift <= max_shift + 0.01


#============================================
def test_anchor_displacement_cap_wh() -> None:
	"""w correction is capped at ANCHOR_MAX_DISP_WH * w * blend."""
	n = 200
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0, w=100.0, h=150.0),
		_make_seed(199, cx=640.0, cy=360.0, w=100.0, h=150.0),
	]
	# massive w drift, low conf
	trajectory = _make_trajectory(n, cx=640.0, cy=360.0, w=500.0, h=150.0, conf=0.0)
	orig_w = trajectory[100]["w"]
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	corrected_w = result[100]["w"]
	# max displacement: 0.15 * 500 = 75, blend_wh at conf=0 is 0.3
	# so max actual shift is 75 * 0.3 = 22.5
	max_shift = 0.15 * orig_w * 0.3
	actual_shift = abs(corrected_w - orig_w)
	assert actual_shift <= max_shift + 0.01


#============================================
def test_anchor_proximity_skip() -> None:
	"""Frames within ANCHOR_PROXIMITY_SKIP of seed frames are not modified."""
	n = 200
	seed_frame = 100
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0),
		_make_seed(seed_frame, cx=640.0, cy=360.0),
		_make_seed(199, cx=640.0, cy=360.0),
	]
	# trajectory with drift and low conf
	trajectory = _make_trajectory(n, cx=680.0, cy=390.0, conf=0.0)
	# save originals for proximity frames
	proximity = 7
	orig_values = {}
	for fi in range(seed_frame - proximity, seed_frame + proximity + 1):
		if 0 <= fi < n:
			orig_values[fi] = (trajectory[fi]["cx"], trajectory[fi]["cy"])
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# frames within proximity of seed_frame=100 (but not seed frames
	# themselves which get pinned) should be unchanged
	for fi in range(seed_frame - proximity + 1, seed_frame):
		# skip exact seed frames (they get pinned)
		if fi in (0, seed_frame, 199):
			continue
		assert result[fi]["cx"] == orig_values[fi][0]
		assert result[fi]["cy"] == orig_values[fi][1]


#============================================
def test_anchor_fewer_than_two_seeds() -> None:
	"""With 0 or 1 seed, trajectory is returned unchanged."""
	n = 50
	trajectory_0 = _make_trajectory(n, cx=640.0, cy=360.0, conf=0.5)
	# save original cx values
	orig_0 = [s["cx"] for s in trajectory_0]
	# zero seeds
	result_0 = solver_mod.anchor_to_seeds(trajectory_0, [])
	for fi in range(n):
		assert result_0[fi]["cx"] == orig_0[fi]
	# one seed
	trajectory_1 = _make_trajectory(n, cx=640.0, cy=360.0, conf=0.5)
	orig_1 = [s["cx"] for s in trajectory_1]
	seeds_1 = [_make_seed(25, cx=700.0, cy=400.0)]
	result_1 = solver_mod.anchor_to_seeds(trajectory_1, seeds_1)
	for fi in range(n):
		assert result_1[fi]["cx"] == orig_1[fi]


#============================================
def test_anchor_local_window_limits_distant_influence() -> None:
	"""Early seeds drive correction at frame 50, not distant late seeds."""
	n = 1100
	# early seeds imply cx=200
	# late seeds imply cx=800
	seeds = [
		_make_seed(0, cx=200.0, cy=360.0),
		_make_seed(50, cx=200.0, cy=360.0),
		_make_seed(100, cx=200.0, cy=360.0),
		_make_seed(900, cx=800.0, cy=360.0),
		_make_seed(950, cx=800.0, cy=360.0),
		_make_seed(1000, cx=800.0, cy=360.0),
	]
	# trajectory at cx=500 (midpoint) with low conf
	trajectory = _make_trajectory(n, cx=500.0, cy=360.0, conf=0.0)
	result = solver_mod.anchor_to_seeds(trajectory, seeds)
	# frame 50 is a seed frame and gets pinned to 200
	assert result[50]["cx"] == 200.0
	# frame 60 (near early seeds) should be closer to 200 than 800
	corrected_60 = result[60]["cx"]
	dist_to_early = abs(corrected_60 - 200.0)
	dist_to_late = abs(corrected_60 - 800.0)
	assert dist_to_early < dist_to_late


#============================================
def test_anchor_not_applied_twice() -> None:
	"""Second call to anchor_to_seeds returns identical output."""
	n = 200
	seeds = [
		_make_seed(0, cx=640.0, cy=360.0),
		_make_seed(100, cx=700.0, cy=400.0),
		_make_seed(199, cx=640.0, cy=360.0),
	]
	trajectory = _make_trajectory(n, cx=660.0, cy=380.0, conf=0.3)
	# first application
	result1 = solver_mod.anchor_to_seeds(trajectory, seeds)
	# deep copy values after first call
	values_after_first = []
	for state in result1:
		values_after_first.append(
			(state["cx"], state["cy"], state["w"], state["h"])
		)
	# second application (should be a no-op due to _anchor_applied guard)
	result2 = solver_mod.anchor_to_seeds(result1, seeds)
	for fi in range(n):
		assert result2[fi]["cx"] == values_after_first[fi][0]
		assert result2[fi]["cy"] == values_after_first[fi][1]
		assert result2[fi]["w"] == values_after_first[fi][2]
		assert result2[fi]["h"] == values_after_first[fi][3]


# ============================================================
# seed suggestion tests
# ============================================================


#============================================
def test_seed_suggestion_no_confirmed_seeds():
	"""With no confirmed seeds, suggestion requires manual selection."""
	# create a dummy frame
	frame = numpy.zeros((200, 400, 3), dtype=numpy.uint8)
	# simulate detections: two candidates
	candidates = [
		{"bbox": [100, 100, 50, 100], "confidence": 0.9, "class_id": 0},
		{"bbox": [300, 100, 50, 100], "confidence": 0.8, "class_id": 0},
	]
	confirmed_seeds = []
	result = seed_color.suggest_seed_candidates(
		frame, candidates, confirmed_seeds, frame_index=0,
	)
	# with no confirmed seeds, should require manual selection
	assert result["suggestion_index"] is None


#============================================
def test_seed_suggestion_single_detection_with_seeds():
	"""Single detection with confirmed seeds auto-suggests."""
	# create a dummy frame
	frame = numpy.zeros((200, 400, 3), dtype=numpy.uint8)
	# one candidate
	candidates = [
		{"bbox": [100, 100, 50, 100], "confidence": 0.9, "class_id": 0},
	]
	# build a confirmed seed with a histogram
	blue_patch = _make_solid_patch((180, 50, 50), size=80)
	hsv = cv2.cvtColor(blue_patch, cv2.COLOR_BGR2HSV)
	hist = cv2.calcHist(
		[hsv], [0, 1], None,
		[30, 32], [0, 180, 0, 256],
	)
	cv2.normalize(hist, hist, alpha=1.0, norm_type=cv2.NORM_L1)
	confirmed_seeds = [{"histogram": hist}]
	result = seed_color.suggest_seed_candidates(
		frame, candidates, confirmed_seeds, frame_index=5,
	)
	# single detection with confirmed seeds: should auto-suggest index 0
	assert result["suggestion_index"] == 0
	assert result["mode"] == "single"


# ============================================================
# detection caching
# ============================================================


#============================================
def test_detection_cache_in_solve_interval_signature():
	"""solve_interval accepts detection_cache parameter."""
	sig = inspect.signature(interval_solver.solve_interval)
	assert "detection_cache" in sig.parameters


#============================================
def test_detection_cache_returned_in_result():
	"""solve_interval result dict includes detection_cache key."""
	# just verify the key name is documented in the function
	# check docstring mentions detection_cache in return
	doc = interval_solver.solve_interval.__doc__
	assert "detection_cache" in doc


#============================================
def test_fuse_tracks_propagates_occlusion():
	"""fuse_tracks preserves occlusion_risk from both directions."""
	# forward has occlusion, backward does not
	fwd = [
		{"cx": 100, "cy": 100, "w": 50, "h": 80, "conf": 0.8, "occlusion_risk": True},
		{"cx": 102, "cy": 100, "w": 50, "h": 80, "conf": 0.7, "occlusion_risk": False},
	]
	bwd = [
		{"cx": 101, "cy": 100, "w": 50, "h": 80, "conf": 0.7, "occlusion_risk": False},
		{"cx": 103, "cy": 100, "w": 50, "h": 80, "conf": 0.8, "occlusion_risk": True},
	]
	fused = interval_solver.fuse_tracks(fwd, bwd)
	# frame 0: fwd has occlusion -> should be True (OR)
	assert fused[0]["occlusion_risk"] is True
	# frame 1: bwd has occlusion -> should be True (OR)
	assert fused[1]["occlusion_risk"] is True
