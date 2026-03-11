"""Unit tests for track_runner package."""

# Standard Library
import math
import os
import tempfile

# PIP3 modules
import numpy
import pytest

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

# paths for optional integration tests
YOLO_WEIGHTS_PATH = os.path.join(
	os.path.expanduser("~"), ".cache", "track_runner", "yolov8n.onnx"
)
HAS_YOLO_WEIGHTS = os.path.isfile(YOLO_WEIGHTS_PATH)
TEST_VIDEO = os.path.join(REPO_ROOT, "TRACK_VIDEOS", "Track_Test-1.mov")
HAS_TEST_VIDEO = os.path.isfile(TEST_VIDEO)


# ============================================================
# config tests
# ============================================================


#============================================
def test_config_default_config_has_all_sections() -> None:
	"""settings has detection, tracking, scoring, crop, seeding, output."""
	import track_runner.config as config_mod
	cfg = config_mod.default_config()
	settings = cfg["settings"]
	for section in ("detection", "tracking", "scoring", "crop", "seeding", "output"):
		assert section in settings, f"missing section: {section}"


#============================================
def test_config_validate_passes_on_valid() -> None:
	"""validate_config(default_config()) does not raise."""
	import track_runner.config as config_mod
	cfg = config_mod.default_config()
	# should not raise
	config_mod.validate_config(cfg)


#============================================
def test_config_validate_fails_on_missing_header() -> None:
	"""validate_config({}) raises RuntimeError."""
	import track_runner.config as config_mod
	with pytest.raises(RuntimeError):
		config_mod.validate_config({})


#============================================
def test_config_validate_fails_on_missing_settings() -> None:
	"""validate_config({"track_runner": 1}) raises RuntimeError."""
	import track_runner.config as config_mod
	with pytest.raises(RuntimeError):
		config_mod.validate_config({"track_runner": 1})


#============================================
def test_config_merge_preserves_base() -> None:
	"""merge_config with partial override keeps base values."""
	import track_runner.config as config_mod
	base = config_mod.default_config()
	override = {"settings": {"crop": {"aspect": "16:9"}}}
	merged = config_mod.merge_config(base, override)
	# overridden value is present
	assert merged["settings"]["crop"]["aspect"] == "16:9"
	# base value preserved in a different section
	assert merged["settings"]["detection"]["kind"] == "yolo"


#============================================
def test_config_merge_overrides_scalar() -> None:
	"""merge_config replaces scalar values from override."""
	import track_runner.config as config_mod
	base = {"a": 1, "b": 2}
	override = {"a": 99}
	merged = config_mod.merge_config(base, override)
	assert merged["a"] == 99
	assert merged["b"] == 2


# ============================================================
# kalman tests
# ============================================================


#============================================
def test_kalman_create_state_shape() -> None:
	"""create_kalman returns state with x of shape (7,)."""
	import track_runner.kalman as kalman_mod
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	assert state["x"].shape == (7,)


#============================================
def test_kalman_create_initial_position() -> None:
	"""initial state cx, cy match input."""
	import track_runner.kalman as kalman_mod
	state = kalman_mod.create_kalman((150, 250, 40, 80))
	assert abs(state["x"][0] - 150.0) < 1e-9
	assert abs(state["x"][1] - 250.0) < 1e-9


#============================================
def test_kalman_create_log_height() -> None:
	"""initial log_h = log(input_h)."""
	import track_runner.kalman as kalman_mod
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	expected = math.log(80)
	assert abs(state["x"][2] - expected) < 1e-9


#============================================
def test_kalman_predict_advances_position() -> None:
	"""predict with nonzero velocity changes cx, cy."""
	import track_runner.kalman as kalman_mod
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	# manually inject velocity
	state["x"][4] = 10.0  # vx
	state["x"][5] = 5.0   # vy
	old_cx = float(state["x"][0])
	old_cy = float(state["x"][1])
	predicted = kalman_mod.predict(state)
	# position should have moved by the velocity
	assert abs(predicted["x"][0] - (old_cx + 10.0)) < 1e-9
	assert abs(predicted["x"][1] - (old_cy + 5.0)) < 1e-9


#============================================
def test_kalman_predict_does_not_mutate() -> None:
	"""predict returns new dict, original unchanged."""
	import track_runner.kalman as kalman_mod
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	state["x"][4] = 10.0
	original_cx = float(state["x"][0])
	_ = kalman_mod.predict(state)
	# original state should be unchanged
	assert abs(state["x"][0] - original_cx) < 1e-9


#============================================
def test_kalman_update_moves_toward_measurement() -> None:
	"""update shifts state toward observation."""
	import track_runner.kalman as kalman_mod
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	# measurement is offset from initial state
	meas = (120.0, 220.0, math.log(80), 0.5)
	updated = kalman_mod.update(state, meas)
	# updated cx should be between 100 and 120
	assert updated["x"][0] > 100.0
	assert updated["x"][0] <= 120.0


#============================================
def test_kalman_get_bbox_roundtrip() -> None:
	"""create from (cx,cy,w,h), get_bbox returns close values."""
	import track_runner.kalman as kalman_mod
	bbox_in = (300, 400, 50, 100)
	state = kalman_mod.create_kalman(bbox_in)
	cx, cy, w, h = kalman_mod.get_bbox(state)
	assert abs(cx - 300) < 1e-6
	assert abs(cy - 400) < 1e-6
	assert abs(w - 50) < 1e-6
	assert abs(h - 100) < 1e-6


#============================================
def test_kalman_measurement_from_bbox() -> None:
	"""measurement_from_bbox converts correctly."""
	import track_runner.kalman as kalman_mod
	result = kalman_mod.measurement_from_bbox((100, 200, 40, 80))
	assert abs(result[0] - 100) < 1e-9
	assert abs(result[1] - 200) < 1e-9
	assert abs(result[2] - math.log(80)) < 1e-9
	assert abs(result[3] - 0.5) < 1e-9


#============================================
def test_kalman_predict_update_cycle() -> None:
	"""10 predict-update cycles converges toward observations."""
	import track_runner.kalman as kalman_mod
	# start at (100, 200), target moves linearly to (200, 250)
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	for i in range(10):
		state = kalman_mod.predict(state)
		# target position moves linearly
		target_cx = 100 + (i + 1) * 10
		target_cy = 200 + (i + 1) * 5
		meas = kalman_mod.measurement_from_bbox(
			(target_cx, target_cy, 40, 80)
		)
		state = kalman_mod.update(state, meas)
	# final state should be near the last target position
	cx, cy, w, h = kalman_mod.get_bbox(state)
	assert abs(cx - 200) < 20
	assert abs(cy - 250) < 20


#============================================
def test_kalman_innovation_distance_zero_for_match() -> None:
	"""distance is near 0 for exact match."""
	import track_runner.kalman as kalman_mod
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	# measurement that matches the initial state exactly
	meas = kalman_mod.measurement_from_bbox((100, 200, 40, 80))
	dist = kalman_mod.get_innovation_distance(state, meas)
	assert dist < 1e-6


# ============================================================
# scoring tests
# ============================================================


def _make_scoring_config() -> dict:
	"""Build a minimal config for scoring tests."""
	import track_runner.config as config_mod
	return config_mod.default_config()


#============================================
def test_scoring_hard_gates_rejects_far_candidate() -> None:
	"""candidate far from prediction is filtered."""
	import track_runner.kalman as kalman_mod
	import track_runner.scoring as scoring_mod
	config = _make_scoring_config()
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	pred = kalman_mod.predict(state)
	# candidate 5000 pixels away
	candidates = [{"bbox": [5000, 5000, 40, 120], "confidence": 0.9, "class_id": 0}]
	result = scoring_mod.apply_hard_gates(candidates, pred, config)
	assert len(result) == 0


#============================================
def test_scoring_hard_gates_rejects_wrong_aspect() -> None:
	"""too-wide candidate filtered."""
	import track_runner.kalman as kalman_mod
	import track_runner.scoring as scoring_mod
	config = _make_scoring_config()
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	pred = kalman_mod.predict(state)
	# candidate that is very wide and short (aspect h/w < 1.5)
	candidates = [{"bbox": [80, 180, 200, 20], "confidence": 0.9, "class_id": 0}]
	result = scoring_mod.apply_hard_gates(candidates, pred, config)
	assert len(result) == 0


#============================================
def test_scoring_hard_gates_rejects_wrong_scale() -> None:
	"""very small candidate filtered."""
	import track_runner.kalman as kalman_mod
	import track_runner.scoring as scoring_mod
	config = _make_scoring_config()
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	pred = kalman_mod.predict(state)
	# tiny candidate (area way below pred_area / scale_band)
	candidates = [{"bbox": [98, 198, 2, 4], "confidence": 0.9, "class_id": 0}]
	result = scoring_mod.apply_hard_gates(candidates, pred, config)
	assert len(result) == 0


#============================================
def test_scoring_hard_gates_accepts_good_candidate() -> None:
	"""nearby correct-sized candidate passes."""
	import track_runner.kalman as kalman_mod
	import track_runner.scoring as scoring_mod
	config = _make_scoring_config()
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	pred = kalman_mod.predict(state)
	# candidate near prediction, aspect h/w = 120/40 = 3.0 (within 1.5-4.0)
	candidates = [{"bbox": [85, 145, 40, 120], "confidence": 0.9, "class_id": 0}]
	result = scoring_mod.apply_hard_gates(candidates, pred, config)
	assert len(result) == 1


#============================================
def test_scoring_score_candidates_returns_scores() -> None:
	"""scored list has 'score' key."""
	import track_runner.kalman as kalman_mod
	import track_runner.scoring as scoring_mod
	config = _make_scoring_config()
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	pred = kalman_mod.predict(state)
	candidates = [{"bbox": [85, 145, 40, 120], "confidence": 0.9, "class_id": 0}]
	scored = scoring_mod.score_candidates(candidates, pred, None, config)
	assert len(scored) == 1
	assert "score" in scored[0]
	assert isinstance(scored[0]["score"], float)


#============================================
def test_scoring_better_candidate_scores_higher() -> None:
	"""closer + more confident > far + less confident."""
	import track_runner.kalman as kalman_mod
	import track_runner.scoring as scoring_mod
	config = _make_scoring_config()
	state = kalman_mod.create_kalman((100, 200, 40, 80))
	pred = kalman_mod.predict(state)
	# good candidate: close and high confidence
	good = {"bbox": [85, 145, 40, 120], "confidence": 0.95, "class_id": 0}
	# worse candidate: further away and lower confidence
	bad = {"bbox": [60, 120, 40, 120], "confidence": 0.3, "class_id": 0}
	scored = scoring_mod.score_candidates([good, bad], pred, None, config)
	# find the scored versions by matching confidence
	score_good = [c for c in scored if c["confidence"] == 0.95][0]["score"]
	score_bad = [c for c in scored if c["confidence"] == 0.3][0]["score"]
	assert score_good > score_bad


# ============================================================
# crop tests
# ============================================================


#============================================
def test_crop_parse_aspect_ratio_1_1() -> None:
	"""'1:1' -> 1.0."""
	import track_runner.crop as crop_mod
	assert crop_mod.parse_aspect_ratio("1:1") == 1.0


#============================================
def test_crop_parse_aspect_ratio_16_9() -> None:
	"""'16:9' -> close to 1.778."""
	import track_runner.crop as crop_mod
	result = crop_mod.parse_aspect_ratio("16:9")
	assert abs(result - 16.0 / 9.0) < 0.001


#============================================
def test_crop_parse_aspect_ratio_invalid() -> None:
	"""'abc' raises RuntimeError."""
	import track_runner.crop as crop_mod
	with pytest.raises(RuntimeError):
		crop_mod.parse_aspect_ratio("abc")


#============================================
def test_crop_controller_first_frame_snaps() -> None:
	"""first update sets position immediately."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	# target at center of frame
	result = ctrl.update((960, 540, 50, 100), 1.0, (1920, 1080))
	# crop center should be near (960, 540) on first frame
	crop_cx = result[0] + result[2] / 2.0
	crop_cy = result[1] + result[3] / 2.0
	assert abs(crop_cx - 960) < 50
	assert abs(crop_cy - 540) < 50


#============================================
def test_crop_controller_smooths_movement() -> None:
	"""second frame does not jump fully to new position."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	# first frame at (500, 500)
	ctrl.update((500, 500, 50, 100), 1.0, (1920, 1080))
	# second frame target jumps to (900, 500)
	result = ctrl.update((900, 500, 50, 100), 1.0, (1920, 1080))
	# crop center should NOT have fully jumped to 900
	crop_cx = result[0] + result[2] / 2.0
	assert crop_cx < 900
	assert crop_cx > 500


#============================================
def test_crop_controller_low_confidence_holds() -> None:
	"""low confidence = minimal movement."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	# first frame at (500, 500)
	ctrl.update((500, 500, 50, 100), 1.0, (1920, 1080))
	state_before = ctrl.get_state()
	# second frame target jumps far, but confidence is nearly zero
	ctrl.update((1500, 500, 50, 100), 0.01, (1920, 1080))
	state_after = ctrl.get_state()
	# position should barely move
	assert abs(state_after["cx"] - state_before["cx"]) < 10


#============================================
def test_crop_controller_reset_clears_state() -> None:
	"""after reset, get_state returns None."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	ctrl.update((500, 500, 50, 100), 1.0, (1920, 1080))
	assert ctrl.get_state() is not None
	ctrl.reset()
	assert ctrl.get_state() is None


#============================================
def test_crop_controller_clamps_to_frame() -> None:
	"""crop does not exceed frame bounds."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	# target near the very edge of the frame
	result = ctrl.update((1900, 1060, 50, 100), 1.0, (1920, 1080))
	crop_x, crop_y, crop_w, crop_h = result
	# crop must not extend beyond frame
	assert crop_x >= 0
	assert crop_y >= 0
	assert crop_x + crop_w <= 1920
	assert crop_y + crop_h <= 1080


#============================================
def test_crop_apply_crop_shape() -> None:
	"""apply_crop returns expected dimensions."""
	import track_runner.crop as crop_mod
	# create a 200x300 BGR frame
	frame = numpy.zeros((300, 200, 3), dtype=numpy.uint8)
	result = crop_mod.apply_crop(frame, (10, 20, 50, 60))
	# output shape should be (60, 50, 3)
	assert result.shape == (60, 50, 3)


#============================================
def test_crop_apply_crop_padding() -> None:
	"""crop extending past frame edge gets black padding."""
	import track_runner.crop as crop_mod
	# white 100x100 frame
	frame = numpy.ones((100, 100, 3), dtype=numpy.uint8) * 255
	# crop that extends 20px past the right and bottom edges
	result = crop_mod.apply_crop(frame, (80, 80, 40, 40))
	assert result.shape == (40, 40, 3)
	# top-left corner (inside original frame) should be white
	assert result[0, 0, 0] == 255
	# bottom-right corner (outside frame) should be black padding
	assert result[39, 39, 0] == 0


# ============================================================
# detection tests (skip if no weights or video)
# ============================================================


#============================================
@pytest.mark.skipif(not HAS_TEST_VIDEO, reason="test video not found")
def test_detection_hog_returns_list() -> None:
	"""HogDetector.detect returns list of dicts."""
	import cv2
	import track_runner.detection as det_mod
	detector = det_mod.HogDetector(confidence_threshold=0.1)
	cap = cv2.VideoCapture(TEST_VIDEO)
	ret, frame = cap.read()
	cap.release()
	assert ret, "failed to read test video frame"
	results = detector.detect(frame)
	assert isinstance(results, list)
	# each detection should have the expected keys
	for det in results:
		assert "bbox" in det
		assert "confidence" in det
		assert "class_id" in det


#============================================
@pytest.mark.skipif(
	not HAS_YOLO_WEIGHTS or not HAS_TEST_VIDEO,
	reason="YOLO weights or test video not found",
)
def test_detection_yolo_returns_list() -> None:
	"""YoloDetector.detect returns list of dicts."""
	import cv2
	import track_runner.detection as det_mod
	detector = det_mod.YoloDetector(YOLO_WEIGHTS_PATH)
	cap = cv2.VideoCapture(TEST_VIDEO)
	ret, frame = cap.read()
	cap.release()
	assert ret, "failed to read test video frame"
	results = detector.detect(frame)
	assert isinstance(results, list)
	for det in results:
		assert "bbox" in det
		assert "confidence" in det
		assert "class_id" in det


#============================================
@pytest.mark.skipif(
	not HAS_YOLO_WEIGHTS or not HAS_TEST_VIDEO,
	reason="YOLO weights or test video not found",
)
def test_detection_yolo_finds_persons() -> None:
	"""YOLO finds at least 1 person in test frame."""
	import cv2
	import track_runner.detection as det_mod
	detector = det_mod.YoloDetector(YOLO_WEIGHTS_PATH)
	cap = cv2.VideoCapture(TEST_VIDEO)
	ret, frame = cap.read()
	cap.release()
	assert ret, "failed to read test video frame"
	results = detector.detect(frame)
	assert len(results) >= 1


#============================================
def test_detection_create_detector_fallback() -> None:
	"""create_detector with kind='hog' returns HogDetector."""
	import track_runner.detection as det_mod
	config = {
		"settings": {
			"detection": {
				"kind": "hog",
				"confidence_threshold": 0.25,
				"nms_threshold": 0.45,
			}
		}
	}
	detector = det_mod.create_detector(config)
	assert isinstance(detector, det_mod.HogDetector)


# ============================================================
# seeding tests
# ============================================================


#============================================
def test_seeding_extract_jersey_color() -> None:
	"""returns 3-tuple of ints from synthetic image."""
	import track_runner.seeding as seed_mod
	# create a solid blue BGR image
	frame = numpy.zeros((100, 100, 3), dtype=numpy.uint8)
	frame[:, :] = (255, 0, 0)  # BGR blue
	result = seed_mod.extract_jersey_color(frame, [10, 10, 30, 30])
	assert isinstance(result, tuple)
	assert len(result) == 3
	# each element should be an int
	for val in result:
		assert isinstance(val, int)


#============================================
def test_seeding_extract_color_histogram_shape() -> None:
	"""histogram shape is (30, 32)."""
	import track_runner.seeding as seed_mod
	frame = numpy.zeros((100, 100, 3), dtype=numpy.uint8)
	frame[:, :] = (0, 128, 255)  # some color
	hist = seed_mod.extract_color_histogram(frame, [10, 10, 30, 30])
	assert hist.shape == (30, 32)


#============================================
def test_seeding_normalize_seed_box_clamps_aspect() -> None:
	"""too-wide box gets narrowed."""
	import track_runner.seeding as seed_mod
	config = _make_scoring_config()
	# box that is very wide: w=200, h=50, aspect = 4.0 > max 0.8
	result = seed_mod.normalize_seed_box([10, 10, 200, 50], config)
	# width should be reduced so w/h <= 0.8
	assert result[2] / result[3] <= 0.81


#============================================
def test_seeding_estimate_full_person() -> None:
	"""full person height ~2.5x torso height."""
	import track_runner.seeding as seed_mod
	torso_box = [100, 100, 40, 60]
	result = seed_mod.estimate_full_person_from_torso(torso_box)
	# result is [cx, cy, w, h] in center format
	full_h = result[3]
	# full height should be 2.5 * torso height
	assert abs(full_h - 60 * 2.5) < 2


#============================================
def test_seeding_collect_headless() -> None:
	"""pre_provided_seeds returned unchanged."""
	import track_runner.seeding as seed_mod
	pre_seeds = [
		{"frame_index": 0, "torso_box": [10, 10, 20, 30]},
		{"frame_index": 100, "torso_box": [50, 50, 20, 30]},
	]
	result = seed_mod.collect_seeds(
		video_path="fake_video.mp4",
		interval_seconds=10,
		config=_make_scoring_config(),
		detector=None,
		pre_provided_seeds=pre_seeds,
	)
	assert result == pre_seeds


# ============================================================
# encoder tests (skip if no test video)
# ============================================================


#============================================
@pytest.mark.skipif(not HAS_TEST_VIDEO, reason="test video not found")
def test_encoder_video_reader_info() -> None:
	"""VideoReader.get_info returns dict with expected keys."""
	import track_runner.encoder as enc_mod
	reader = enc_mod.VideoReader(TEST_VIDEO)
	info = reader.get_info()
	reader.close()
	for key in ("frame_count", "fps", "width", "height"):
		assert key in info, f"missing key: {key}"
	assert info["frame_count"] > 0
	assert info["fps"] > 0


#============================================
@pytest.mark.skipif(not HAS_TEST_VIDEO, reason="test video not found")
def test_encoder_video_reader_frame_shape() -> None:
	"""read_frame returns correct shape."""
	import track_runner.encoder as enc_mod
	reader = enc_mod.VideoReader(TEST_VIDEO)
	info = reader.get_info()
	frame = reader.read_frame(0)
	reader.close()
	assert frame is not None
	assert frame.shape[0] == info["height"]
	assert frame.shape[1] == info["width"]
	assert frame.shape[2] == 3


#============================================
@pytest.mark.skipif(not HAS_TEST_VIDEO, reason="test video not found")
def test_encoder_video_reader_iteration() -> None:
	"""iterate yields (index, frame) tuples."""
	import track_runner.encoder as enc_mod
	reader = enc_mod.VideoReader(TEST_VIDEO)
	frames_read = []
	for idx, frame in reader:
		frames_read.append((idx, frame.shape))
		if idx >= 4:
			break
	reader.close()
	assert len(frames_read) == 5
	# check that indices are sequential
	for i, (idx, _) in enumerate(frames_read):
		assert idx == i


# ============================================================
# cli quality grade tests
# ============================================================


#============================================
def test_quality_grade_a() -> None:
	"""High detection rate and low streak earns A."""
	import track_runner.cli as cli_mod
	grade = cli_mod._tracking_quality_grade(90.0, 15, 30.0)
	assert grade == "A"


#============================================
def test_quality_grade_f() -> None:
	"""Very low detection rate earns F."""
	import track_runner.cli as cli_mod
	grade = cli_mod._tracking_quality_grade(10.0, 900, 30.0)
	assert grade == "F"


#============================================
def test_quality_grade_old_thresholds_would_be_wrong() -> None:
	"""15% detection should NOT be grade A (it was before the fix)."""
	import track_runner.cli as cli_mod
	grade = cli_mod._tracking_quality_grade(15.0, 30, 30.0)
	assert grade != "A"


# ============================================================
# cli streak detection tests
# ============================================================


#============================================
def test_find_worst_streaks_includes_interpolated() -> None:
	"""Streaks of predicted+interpolated frames are found."""
	import track_runner.cli as cli_mod
	# build frame_states: 10 detected, then 40 interpolated, then 10 detected
	states = []
	for i in range(10):
		states.append({"frame_index": i, "source": "detected"})
	for i in range(10, 50):
		states.append({"frame_index": i, "source": "interpolated"})
	for i in range(50, 60):
		states.append({"frame_index": i, "source": "detected"})
	streaks = cli_mod._find_worst_streaks(states, min_streak=30)
	assert len(streaks) == 1
	assert streaks[0][0] == 10
	assert streaks[0][1] == 40


# ============================================================
# debug overlay tests
# ============================================================


#============================================
def test_debug_overlay_cropped_draws_on_frame() -> None:
	"""draw_debug_overlay_cropped draws on the frame in-place."""
	import track_runner.encoder as enc_mod
	# create a 140x200 BGR frame (cropped/resized output)
	frame = numpy.zeros((140, 200, 3), dtype=numpy.uint8)
	state = {
		"frame_index": 42,
		"source": "detected",
		"confidence": 0.85,
		"bbox": (150.0, 100.0, 40.0, 80.0),
	}
	crop_rect = (50, 30, 200, 140)
	enc_mod.draw_debug_overlay_cropped(frame, state, crop_rect, 200, 140)
	# frame should have some non-zero pixels from drawing
	assert not numpy.all(frame == 0)


#============================================
def test_debug_overlay_cropped_none_state() -> None:
	"""draw_debug_overlay_cropped handles None state without crashing."""
	import track_runner.encoder as enc_mod
	frame = numpy.zeros((140, 200, 3), dtype=numpy.uint8)
	crop_rect = (50, 30, 200, 140)
	enc_mod.draw_debug_overlay_cropped(frame, None, crop_rect, 200, 140)
	# should have drawn "NO DATA" text
	assert not numpy.all(frame == 0)


# ============================================================
# absence marker tests
# ============================================================


#============================================
def test_find_worst_streaks_includes_absent() -> None:
	"""Streaks containing absent frames are found."""
	import track_runner.cli as cli_mod
	states = []
	for i in range(10):
		states.append({"frame_index": i, "source": "detected"})
	for i in range(10, 30):
		states.append({"frame_index": i, "source": "predicted"})
	for i in range(30, 50):
		states.append({"frame_index": i, "source": "absent"})
	for i in range(50, 60):
		states.append({"frame_index": i, "source": "detected"})
	streaks = cli_mod._find_worst_streaks(states, min_streak=30)
	assert len(streaks) == 1
	# the streak covers both predicted and absent frames
	assert streaks[0][0] == 10
	assert streaks[0][1] == 40


# ============================================================
# jerk detection tests
# ============================================================


#============================================
def test_find_jerk_regions_detects_jump() -> None:
	"""Sudden 500px jump with 100px person height is flagged."""
	import track_runner.tracker as tracker_mod
	# smooth path then sudden jump
	states = []
	for i in range(20):
		states.append({
			"frame_index": i,
			"source": "detected",
			"confidence": 0.9,
			"bbox": (100.0 + i * 2, 200.0, 40.0, 100.0),
		})
	# sudden 500px jump at frame 20
	states.append({
		"frame_index": 20,
		"source": "detected",
		"confidence": 0.9,
		"bbox": (600.0, 200.0, 40.0, 100.0),
	})
	regions = tracker_mod.find_jerk_regions(states, min_streak=1)
	assert len(regions) >= 1
	# the jerk frame should be at frame 20
	all_frames = set()
	for start, length in regions:
		for f in range(start, start + length):
			all_frames.add(f)
	assert 20 in all_frames


#============================================
def test_find_jerk_regions_ignores_smooth_motion() -> None:
	"""2px per frame movement produces no jerk regions."""
	import track_runner.tracker as tracker_mod
	states = []
	for i in range(50):
		states.append({
			"frame_index": i,
			"source": "detected",
			"confidence": 0.9,
			"bbox": (100.0 + i * 2, 200.0, 40.0, 100.0),
		})
	regions = tracker_mod.find_jerk_regions(states)
	assert len(regions) == 0


#============================================
def test_merge_streak_lists_overlap() -> None:
	"""Overlapping streaks from two lists combine."""
	import track_runner.cli as cli_mod
	a = [(10, 20)]   # frames 10-29
	b = [(25, 15)]   # frames 25-39
	merged = cli_mod._merge_streak_lists(a, b)
	assert len(merged) == 1
	# merged should cover frames 10-39
	assert merged[0][0] == 10
	assert merged[0][1] == 30


# ============================================================
# config file separation tests
# ============================================================


#============================================
def test_config_seeds_round_trip() -> None:
	"""write_seeds then load_seeds returns same list."""
	import track_runner.config as config_mod
	seeds = [
		{"frame_index": 0, "torso_box": [10, 10, 20, 30]},
		{"frame_index": 100, "torso_box": [50, 50, 20, 30]},
	]
	with tempfile.NamedTemporaryFile(
		suffix=".yaml", mode="w", delete=False
	) as tmp:
		tmp_path = tmp.name
	config_mod.write_seeds(tmp_path, seeds)
	loaded = config_mod.load_seeds(tmp_path)
	assert loaded == seeds
	os.unlink(tmp_path)


#============================================
def test_config_load_seeds_missing_file() -> None:
	"""load_seeds returns empty list for missing file."""
	import track_runner.config as config_mod
	result = config_mod.load_seeds("/tmp/nonexistent_seeds_12345.yaml")
	assert result == []


#============================================
def test_config_diagnostics_round_trip() -> None:
	"""write_diagnostics then load_diagnostics returns same dict."""
	import track_runner.config as config_mod
	diag = {
		"bad_streaks": [[10, 40]],
		"max_streak": 40,
		"detect_pct": 75.0,
	}
	with tempfile.NamedTemporaryFile(
		suffix=".yaml", mode="w", delete=False
	) as tmp:
		tmp_path = tmp.name
	config_mod.write_diagnostics(tmp_path, diag)
	loaded = config_mod.load_diagnostics(tmp_path)
	assert loaded == diag
	os.unlink(tmp_path)


#============================================
def test_config_load_diagnostics_missing_file() -> None:
	"""load_diagnostics returns empty dict for missing file."""
	import track_runner.config as config_mod
	result = config_mod.load_diagnostics("/tmp/nonexistent_diag_12345.yaml")
	assert result == {}


# ============================================================
# adaptive fill ratio tests
# ============================================================


#============================================
def test_crop_adaptive_fill_far_runner() -> None:
	"""Small bbox (far runner) gets tighter crop than baseline."""
	import track_runner.crop as crop_mod
	# with far_fill_ratio=0.50, a 80px tall runner should get ~160px crop
	ctrl = crop_mod.CropController(
		1920, 1080, aspect_ratio=1.0,
		target_fill_ratio=0.30, far_fill_ratio=0.50,
		far_threshold_px=120, min_crop_size=100,
	)
	result = ctrl.update((960, 540, 30, 80), 1.0, (1920, 1080))
	crop_h = result[3]
	# crop height should be around 160 (80/0.50), not 267 (80/0.30)
	assert crop_h < 200


#============================================
def test_crop_adaptive_fill_close_runner() -> None:
	"""Large bbox (close runner) uses baseline fill ratio."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(
		1920, 1080, aspect_ratio=1.0,
		target_fill_ratio=0.30, far_fill_ratio=0.50,
		far_threshold_px=120, min_crop_size=100,
	)
	result = ctrl.update((960, 540, 120, 400), 1.0, (1920, 1080))
	crop_h = result[3]
	# crop height should be around 1080 (clamped) or 400/0.30=1333 clamped to 1080
	assert crop_h >= 1000
