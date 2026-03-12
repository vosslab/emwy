"""Unit tests for track_runner v2 modules.

Covers: state_io, config, scoring, propagator, hypothesis, review, crop, encoder.
All v1 tests (kalman, tracker, old scoring API, old seeding API) have been removed.
"""

# Standard Library
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
# state_io tests
# ============================================================


#============================================
def test_state_io_seeds_round_trip() -> None:
	"""write_seeds then load_seeds returns same seeds list."""
	import track_runner.state_io as state_io_mod
	seeds_data = {
		"video_file": "test.mov",
		"seeds": [
			{
				"frame_index": 150,
				"time_s": 5.0,
				"torso_box": [640, 360, 40, 60],
				"jersey_hsv": [120, 180, 200],
				"pass": 1,
				"source": "human",
				"mode": "initial",
			}
		],
	}
	with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
		tmp_path = tmp.name
	state_io_mod.write_seeds(tmp_path, seeds_data)
	loaded = state_io_mod.load_seeds(tmp_path)
	assert loaded["seeds"][0]["frame_index"] == 150
	assert loaded[state_io_mod.SEEDS_HEADER_KEY] == state_io_mod.SEEDS_HEADER_VALUE
	os.unlink(tmp_path)


#============================================
def test_state_io_seeds_missing_file_returns_empty() -> None:
	"""load_seeds returns empty structure for non-existent file."""
	import track_runner.state_io as state_io_mod
	result = state_io_mod.load_seeds("/tmp/nonexistent_seeds_99999.json")
	assert "seeds" in result
	assert result["seeds"] == []


#============================================
def test_state_io_seeds_wrong_header_raises() -> None:
	"""load_seeds raises RuntimeError if header version is wrong."""
	import json
	import track_runner.state_io as state_io_mod
	bad_data = {"track_runner_seeds": 99, "seeds": []}
	with tempfile.NamedTemporaryFile(
		suffix=".json", mode="w", delete=False
	) as tmp:
		json.dump(bad_data, tmp)
		tmp_path = tmp.name
	with pytest.raises(RuntimeError):
		state_io_mod.load_seeds(tmp_path)
	os.unlink(tmp_path)


#============================================
def test_state_io_diagnostics_round_trip() -> None:
	"""write_diagnostics then load_diagnostics returns same data."""
	import track_runner.state_io as state_io_mod
	diag_data = {
		"intervals": [1, 2, 3],
		"trajectory": [{"frame": 0, "x": 100}],
	}
	with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
		tmp_path = tmp.name
	state_io_mod.write_diagnostics(tmp_path, diag_data)
	loaded = state_io_mod.load_diagnostics(tmp_path)
	assert loaded["intervals"] == [1, 2, 3]
	assert loaded[state_io_mod.DIAGNOSTICS_HEADER_KEY] == state_io_mod.DIAGNOSTICS_HEADER_VALUE
	os.unlink(tmp_path)


#============================================
def test_state_io_diagnostics_missing_file_returns_empty() -> None:
	"""load_diagnostics returns empty structure for non-existent file."""
	import track_runner.state_io as state_io_mod
	result = state_io_mod.load_diagnostics("/tmp/nonexistent_diag_99999.json")
	assert state_io_mod.DIAGNOSTICS_HEADER_KEY in result


#============================================
def test_state_io_merge_seeds_no_duplicate_frames() -> None:
	"""merge_seeds never overwrites an existing frame entry."""
	import track_runner.state_io as state_io_mod
	existing = [{"frame": 10, "mode": "initial"}, {"frame": 20, "mode": "initial"}]
	new = [{"frame": 10, "mode": "gap_refine"}, {"frame": 30, "mode": "interval_refine"}]
	merged = state_io_mod.merge_seeds(existing, new)
	assert len(merged) == 3
	# original frame 10 entry must not be overwritten
	frame_10 = next(s for s in merged if s["frame"] == 10)
	assert frame_10["mode"] == "initial"


# ============================================================
# config tests
# ============================================================


#============================================
def test_config_default_config_has_required_sections() -> None:
	"""default_config has detection and processing sections."""
	import track_runner.config as config_mod
	cfg = config_mod.default_config()
	for section in ("detection", "processing"):
		assert section in cfg, f"missing section: {section}"


#============================================
def test_config_default_config_has_header() -> None:
	"""default_config includes the track_runner header key."""
	import track_runner.config as config_mod
	cfg = config_mod.default_config()
	assert config_mod.TOOL_CONFIG_HEADER_KEY in cfg
	assert cfg[config_mod.TOOL_CONFIG_HEADER_KEY] == config_mod.TOOL_CONFIG_HEADER_VALUE


#============================================
def test_config_validate_passes_on_valid() -> None:
	"""validate_config(default_config()) does not raise."""
	import track_runner.config as config_mod
	cfg = config_mod.default_config()
	config_mod.validate_config(cfg)


#============================================
def test_config_validate_fails_on_missing_header() -> None:
	"""validate_config({}) raises RuntimeError."""
	import track_runner.config as config_mod
	with pytest.raises(RuntimeError):
		config_mod.validate_config({})


#============================================
def test_config_validate_fails_on_wrong_version() -> None:
	"""validate_config with wrong version raises RuntimeError."""
	import track_runner.config as config_mod
	bad = {config_mod.TOOL_CONFIG_HEADER_KEY: 99, "detection": {}, "processing": {}}
	with pytest.raises(RuntimeError):
		config_mod.validate_config(bad)


#============================================
def test_config_merge_overrides_scalar() -> None:
	"""merge_config replaces scalar values from override."""
	import track_runner.config as config_mod
	base = {"a": 1, "b": 2}
	override = {"a": 99}
	merged = config_mod.merge_config(base, override)
	assert merged["a"] == 99
	assert merged["b"] == 2


#============================================
def test_config_merge_deep_merges_dicts() -> None:
	"""merge_config deep-merges nested dicts."""
	import track_runner.config as config_mod
	base = config_mod.default_config()
	override = {"processing": {"crf": 28}}
	merged = config_mod.merge_config(base, override)
	# overridden crf
	assert merged["processing"]["crf"] == 28
	# other processing keys still from base
	assert "crop_aspect" in merged["processing"]


#============================================
def test_config_write_and_load_round_trip() -> None:
	"""write_config then load_config returns equivalent config."""
	import track_runner.config as config_mod
	cfg = config_mod.default_config()
	with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
		tmp_path = tmp.name
	config_mod.write_config(tmp_path, cfg)
	loaded = config_mod.load_config(tmp_path)
	assert config_mod.TOOL_CONFIG_HEADER_KEY in loaded
	os.unlink(tmp_path)


# ============================================================
# scoring tests
# ============================================================


def _make_track_state(cx: float, cy: float, w: float, h: float) -> dict:
	"""Build a minimal v2 tracking state dict."""
	return {"cx": cx, "cy": cy, "w": w, "h": h, "conf": 0.9, "source": "propagated"}


#============================================
def test_scoring_compute_agreement_identical_tracks() -> None:
	"""Identical forward/backward tracks yield agreement near 1.0."""
	import track_runner.scoring as scoring_mod
	track = [_make_track_state(100.0, 200.0, 40.0, 80.0)] * 10
	score = scoring_mod.compute_agreement(track, track)
	assert score > 0.95


#============================================
def test_scoring_compute_agreement_diverged_tracks() -> None:
	"""Tracks offset by 2x height yield low agreement."""
	import track_runner.scoring as scoring_mod
	fwd = [_make_track_state(100.0, 200.0, 40.0, 80.0)] * 10
	# backward track is 200px offset (2.5x height of 80)
	bwd = [_make_track_state(300.0, 200.0, 40.0, 80.0)] * 10
	score = scoring_mod.compute_agreement(fwd, bwd)
	assert score < 0.5


#============================================
def test_scoring_classify_confidence_high() -> None:
	"""High agreement and margin produces high confidence."""
	import track_runner.scoring as scoring_mod
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.95, identity=0.8, margin=0.7,
	)
	assert confidence == "high"
	assert reasons == []


#============================================
def test_scoring_classify_confidence_low_agreement() -> None:
	"""Low agreement produces low confidence with low_agreement reason."""
	import track_runner.scoring as scoring_mod
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.5, identity=0.8, margin=0.6,
	)
	assert confidence == "fair"
	assert "low_agreement" in reasons


#============================================
def test_scoring_classify_confidence_low_separation() -> None:
	"""High agreement but low margin gives low_separation reason."""
	import track_runner.scoring as scoring_mod
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.9, identity=0.8, margin=0.3,
	)
	assert confidence == "good"
	assert "low_separation" in reasons


#============================================
def test_scoring_classify_confidence_weak_appearance() -> None:
	"""Low identity adds weak_appearance reason regardless of confidence."""
	import track_runner.scoring as scoring_mod
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.95, identity=0.2, margin=0.7,
	)
	# weak_appearance is added even when agreement/margin are fine
	assert "weak_appearance" in reasons


#============================================
def test_scoring_score_interval_returns_expected_keys() -> None:
	"""score_interval result has all required keys."""
	import track_runner.scoring as scoring_mod
	track = [_make_track_state(100.0, 200.0, 40.0, 80.0)] * 5
	identity_scores = [0.8] * 5
	competitor_margins = [0.6] * 5
	result = scoring_mod.score_interval(track, track, identity_scores, competitor_margins)
	for key in ("agreement_score", "identity_score", "competitor_margin", "confidence", "failure_reasons"):
		assert key in result, f"missing key: {key}"


# ============================================================
# propagator tests
# ============================================================


#============================================
def test_propagator_make_seed_state_keys() -> None:
	"""make_seed_state returns dict with required v2 state keys."""
	import track_runner.propagator as prop_mod
	state = prop_mod.make_seed_state(cx=100.0, cy=200.0, w=40.0, h=80.0, conf=1.0)
	for key in ("cx", "cy", "w", "h", "conf", "source"):
		assert key in state, f"missing key: {key}"


#============================================
def test_propagator_make_seed_state_values() -> None:
	"""make_seed_state stores exact input values."""
	import track_runner.propagator as prop_mod
	state = prop_mod.make_seed_state(cx=150.0, cy=250.0, w=50.0, h=100.0, conf=0.9)
	assert abs(state["cx"] - 150.0) < 1e-9
	assert abs(state["cy"] - 250.0) < 1e-9
	assert abs(state["h"] - 100.0) < 1e-9
	assert abs(state["conf"] - 0.9) < 1e-9


#============================================
def test_propagator_build_appearance_model_keys() -> None:
	"""build_appearance_model returns dict with template and hsv_mean."""
	import track_runner.propagator as prop_mod
	# create a minimal synthetic frame
	frame = numpy.zeros((200, 300, 3), dtype=numpy.uint8)
	frame[50:150, 100:200] = (0, 128, 255)
	bbox = {"cx": 150.0, "cy": 100.0, "w": 100.0, "h": 100.0}
	model = prop_mod.build_appearance_model(frame, bbox)
	assert "template" in model
	assert "hsv_mean" in model
	assert len(model["hsv_mean"]) == 3


# ============================================================
# hypothesis tests
# ============================================================


#============================================
def test_hypothesis_compute_iou_identical_boxes() -> None:
	"""IoU of identical boxes is 1.0."""
	import track_runner.hypothesis as hyp_mod
	box = {"cx": 100.0, "cy": 100.0, "w": 40.0, "h": 80.0}
	# call private function through module
	iou = hyp_mod._compute_iou(box, box)
	assert abs(iou - 1.0) < 1e-6


#============================================
def test_hypothesis_compute_iou_non_overlapping() -> None:
	"""Non-overlapping boxes yield IoU of 0.0."""
	import track_runner.hypothesis as hyp_mod
	box_a = {"cx": 100.0, "cy": 100.0, "w": 40.0, "h": 80.0}
	box_b = {"cx": 500.0, "cy": 500.0, "w": 40.0, "h": 80.0}
	iou = hyp_mod._compute_iou(box_a, box_b)
	assert iou == 0.0


#============================================
def test_hypothesis_detection_to_state_converts_to_center_format() -> None:
	"""_detection_to_state converts top-left bbox to center format."""
	import track_runner.hypothesis as hyp_mod
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
	import track_runner.hypothesis as hyp_mod
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
	import track_runner.hypothesis as hyp_mod
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
# review tests
# ============================================================


def _make_test_diagnostics(confidence: str = "low", reasons: list | None = None) -> dict:
	"""Build a minimal diagnostics dict for review tests."""
	if reasons is None:
		reasons = ["low_agreement"]
	return {
		"fps": 30.0,
		"intervals": [
			{
				"start_frame": 0,
				"end_frame": 300,
				"interval_score": {
					"confidence": "high",
					"failure_reasons": [],
					"agreement_score": 0.9,
					"identity_score": 0.85,
					"competitor_margin": 0.75,
				},
			},
			{
				"start_frame": 300,
				"end_frame": 600,
				"interval_score": {
					"confidence": confidence,
					"failure_reasons": reasons,
					"agreement_score": 0.3,
					"identity_score": 0.8,
					"competitor_margin": 0.7,
				},
			},
		],
	}


#============================================
def test_review_needs_refinement_true_when_weak() -> None:
	"""needs_refinement returns True when any interval is not high."""
	import track_runner.review as review_mod
	diag = _make_test_diagnostics(confidence="low")
	assert review_mod.needs_refinement(diag) is True


#============================================
def test_review_needs_refinement_false_when_all_high() -> None:
	"""needs_refinement returns False when all intervals are high."""
	import track_runner.review as review_mod
	diag = {
		"fps": 30.0,
		"intervals": [
			{
				"start_frame": 0,
				"end_frame": 300,
				"interval_score": {
					"confidence": "high",
					"failure_reasons": [],
					"agreement_score": 0.9,
					"identity_score": 0.85,
					"competitor_margin": 0.75,
				},
			},
		],
	}
	assert review_mod.needs_refinement(diag) is False


#============================================
def test_review_identify_weak_spans_skips_high() -> None:
	"""identify_weak_spans produces no suggestions for high-confidence intervals."""
	import track_runner.review as review_mod
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	suggestions = review_mod.identify_weak_spans(diag)
	# only the weak interval contributes suggestions
	for s in suggestions:
		# all frames should be in the weak interval (300-600)
		assert s["frame"] >= 300


#============================================
def test_review_identify_weak_spans_produces_reason() -> None:
	"""identify_weak_spans sets reason field from interval failure_reasons."""
	import track_runner.review as review_mod
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	suggestions = review_mod.identify_weak_spans(diag)
	assert len(suggestions) == 1
	assert suggestions[0]["reason"] == "low_agreement"


#============================================
def test_review_identify_weak_spans_all_fields_present() -> None:
	"""Each suggestion has frame, time_s, reason, competitor_summary."""
	import track_runner.review as review_mod
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	suggestions = review_mod.identify_weak_spans(diag)
	for s in suggestions:
		assert "frame" in s
		assert "time_s" in s
		assert "reason" in s
		assert "competitor_summary" in s


#============================================
def test_review_generate_refinement_targets_suggested_mode() -> None:
	"""generate_refinement_targets with 'suggested' returns weak-span frames."""
	import track_runner.review as review_mod
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	targets = review_mod.generate_refinement_targets(diag, mode="suggested")
	assert len(targets) >= 1
	# all frames must be in range [300, 600]
	for f in targets:
		assert 300 <= f <= 600


#============================================
def test_review_generate_refinement_targets_interval_mode() -> None:
	"""'interval' mode returns evenly spaced frames."""
	import track_runner.review as review_mod
	diag = _make_test_diagnostics()
	targets = review_mod.generate_refinement_targets(diag, mode="interval", seed_interval=150)
	# with span 0-600 and spacing 150, expect frames at 150, 300, 450
	assert len(targets) >= 2
	# targets should be sorted
	assert targets == sorted(targets)


#============================================
def test_review_generate_refinement_targets_gap_mode() -> None:
	"""'gap' mode returns midpoint of intervals exceeding threshold."""
	import track_runner.review as review_mod
	diag = _make_test_diagnostics()
	# gap_threshold=250 -> both intervals (300 frames each) exceed threshold
	targets = review_mod.generate_refinement_targets(diag, mode="gap", gap_threshold=250)
	assert len(targets) >= 1


#============================================
def test_review_generate_refinement_targets_time_range() -> None:
	"""time_range restricts targets to the given window."""
	import track_runner.review as review_mod
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	# only look at frames 0-299 (where the high-confidence interval lives)
	targets = review_mod.generate_refinement_targets(
		diag, mode="suggested", time_range=(0.0, 9.9),
	)
	# should be empty since the weak interval is at frames 300-600
	assert len(targets) == 0


#============================================
def test_review_format_review_summary_is_string() -> None:
	"""format_review_summary returns a non-empty string."""
	import track_runner.review as review_mod
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	summary = review_mod.format_review_summary(diag)
	assert isinstance(summary, str)
	assert len(summary) > 0
	assert "WEAK" in summary or "TRUST" in summary


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
def _make_crop_state(cx: float, cy: float, h: float, conf: float = 1.0) -> dict:
	"""Build a minimal v2 tracking state dict for crop tests."""
	return {"cx": cx, "cy": cy, "w": h * 0.5, "h": h, "conf": conf, "source": "propagated"}


#============================================
def test_crop_controller_first_update_snaps_to_target() -> None:
	"""First update sets crop position near the target."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	state = _make_crop_state(cx=960.0, cy=540.0, h=100.0, conf=1.0)
	result = ctrl.update(state)
	crop_x, crop_y, crop_w, crop_h = result
	crop_cx = crop_x + crop_w / 2.0
	crop_cy = crop_y + crop_h / 2.0
	assert abs(crop_cx - 960) < 100
	assert abs(crop_cy - 540) < 100


#============================================
def test_crop_controller_second_update_smooths() -> None:
	"""Second update does not jump fully to new position."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	state1 = _make_crop_state(cx=500.0, cy=540.0, h=100.0, conf=1.0)
	ctrl.update(state1)
	state2 = _make_crop_state(cx=900.0, cy=540.0, h=100.0, conf=1.0)
	result = ctrl.update(state2)
	crop_x, crop_y, crop_w, crop_h = result
	crop_cx = crop_x + crop_w / 2.0
	# should be between 500 and 900 (smoothed)
	assert crop_cx < 900
	assert crop_cx > 500


#============================================
def test_crop_controller_low_confidence_holds_position() -> None:
	"""Low confidence causes minimal movement."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	state1 = _make_crop_state(cx=500.0, cy=540.0, h=100.0, conf=1.0)
	ctrl.update(state1)
	smooth_before = ctrl.smooth_cx
	# jump far with very low confidence
	state2 = _make_crop_state(cx=1500.0, cy=540.0, h=100.0, conf=0.01)
	ctrl.update(state2)
	smooth_after = ctrl.smooth_cx
	assert abs(smooth_after - smooth_before) < 20


#============================================
def test_crop_controller_clamps_to_frame_bounds() -> None:
	"""Crop rectangle stays within frame dimensions."""
	import track_runner.crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	# target near the very edge of the frame
	state = _make_crop_state(cx=1900.0, cy=1060.0, h=100.0, conf=1.0)
	result = ctrl.update(state)
	crop_x, crop_y, crop_w, crop_h = result
	assert crop_x >= 0
	assert crop_y >= 0
	assert crop_x + crop_w <= 1920
	assert crop_y + crop_h <= 1080


#============================================
def test_crop_apply_crop_shape() -> None:
	"""apply_crop returns expected dimensions."""
	import track_runner.crop as crop_mod
	frame = numpy.zeros((300, 200, 3), dtype=numpy.uint8)
	result = crop_mod.apply_crop(frame, (10, 20, 50, 60))
	assert result.shape == (60, 50, 3)


#============================================
def test_crop_apply_crop_padding() -> None:
	"""Crop extending past frame edge gets black padding."""
	import track_runner.crop as crop_mod
	frame = numpy.ones((100, 100, 3), dtype=numpy.uint8) * 255
	result = crop_mod.apply_crop(frame, (80, 80, 40, 40))
	assert result.shape == (40, 40, 3)
	# top-left corner (inside frame) should be white
	assert result[0, 0, 0] == 255
	# bottom-right corner (outside frame) should be black padding
	assert result[39, 39, 0] == 0


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
	for i, (idx, _) in enumerate(frames_read):
		assert idx == i


#============================================
def test_encoder_draw_debug_overlay_none_state() -> None:
	"""draw_debug_overlay_cropped handles None state without crashing."""
	import track_runner.encoder as enc_mod
	frame = numpy.zeros((140, 200, 3), dtype=numpy.uint8)
	crop_rect = (50, 30, 200, 140)
	enc_mod.draw_debug_overlay_cropped(frame, None, crop_rect, 200, 140)
	# should have drawn some text (non-zero pixels)
	assert not numpy.all(frame == 0)


#============================================
def test_encoder_draw_debug_overlay_with_state() -> None:
	"""draw_debug_overlay_cropped draws on frame when given a v2 state."""
	import track_runner.encoder as enc_mod
	frame = numpy.zeros((140, 200, 3), dtype=numpy.uint8)
	state = {
		"cx": 150.0, "cy": 100.0, "w": 40.0, "h": 80.0,
		"conf": 0.85, "source": "merged",
	}
	crop_rect = (50, 30, 200, 140)
	enc_mod.draw_debug_overlay_cropped(frame, state, crop_rect, 200, 140)
	assert not numpy.all(frame == 0)


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
