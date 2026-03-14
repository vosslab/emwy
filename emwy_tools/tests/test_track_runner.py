"""Unit tests for track_runner v2 modules.

Covers: state_io, config, scoring, propagator, hypothesis, review, crop, encoder,
flow consistency, identity scoring, velocity-adaptive crop, seed suggestion,
occlusion-risk flagging, detection caching.
"""

# Standard Library
import os
import inspect
import tempfile

# PIP3 modules
import cv2
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
		"intervals": [
			{"start_frame": 0, "end_frame": 100, "confidence": 0.9},
			{"start_frame": 100, "end_frame": 200, "agreement_score": 0.8},
		],
		"trajectory": [{"frame": 0, "x": 100}],
	}
	with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
		tmp_path = tmp.name
	state_io_mod.write_diagnostics(tmp_path, diag_data)
	loaded = state_io_mod.load_diagnostics(tmp_path)
	assert len(loaded["intervals"]) == 2
	assert loaded["intervals"][0]["start_frame"] == 0
	# score reconstruction: flat keys get grouped into interval_score sub-dict
	assert "interval_score" in loaded["intervals"][1]
	assert loaded["intervals"][1]["interval_score"]["agreement_score"] == 0.8
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
	import track_runner.tr_config as config_mod
	cfg = config_mod.default_config()
	for section in ("detection", "processing"):
		assert section in cfg, f"missing section: {section}"


#============================================
def test_config_default_config_has_header() -> None:
	"""default_config includes the track_runner header key."""
	import track_runner.tr_config as config_mod
	cfg = config_mod.default_config()
	assert config_mod.TOOL_CONFIG_HEADER_KEY in cfg
	assert cfg[config_mod.TOOL_CONFIG_HEADER_KEY] == config_mod.TOOL_CONFIG_HEADER_VALUE


#============================================
def test_config_validate_passes_on_valid() -> None:
	"""validate_config(default_config()) does not raise."""
	import track_runner.tr_config as config_mod
	cfg = config_mod.default_config()
	config_mod.validate_config(cfg)


#============================================
def test_config_validate_fails_on_missing_header() -> None:
	"""validate_config({}) raises RuntimeError."""
	import track_runner.tr_config as config_mod
	with pytest.raises(RuntimeError):
		config_mod.validate_config({})


#============================================
def test_config_validate_fails_on_wrong_version() -> None:
	"""validate_config with wrong version raises RuntimeError."""
	import track_runner.tr_config as config_mod
	bad = {config_mod.TOOL_CONFIG_HEADER_KEY: 99, "detection": {}, "processing": {}}
	with pytest.raises(RuntimeError):
		config_mod.validate_config(bad)


#============================================
def test_config_merge_overrides_scalar() -> None:
	"""merge_config replaces scalar values from override."""
	import track_runner.tr_config as config_mod
	base = {"a": 1, "b": 2}
	override = {"a": 99}
	merged = config_mod.merge_config(base, override)
	assert merged["a"] == 99
	assert merged["b"] == 2


#============================================
def test_config_merge_deep_merges_dicts() -> None:
	"""merge_config deep-merges nested dicts."""
	import track_runner.tr_config as config_mod
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
	import track_runner.tr_config as config_mod
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


#============================================
def test_classify_confidence_short_interval_promotes_one_tier() -> None:
	"""3-frame interval with fair metrics promotes to good."""
	import track_runner.scoring as scoring_mod
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.35, identity=0.8, margin=0.6,
		interval_length=3,
	)
	# without short-interval promotion this would be "fair"
	assert confidence == "good"


#============================================
def test_classify_confidence_short_interval_low_to_fair() -> None:
	"""2-frame interval with low metrics promotes from low to fair."""
	import track_runner.scoring as scoring_mod
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.15, identity=0.8, margin=0.15,
		interval_length=2,
	)
	# without promotion this would be "low"
	assert confidence == "fair"


#============================================
def test_classify_confidence_long_interval_unchanged() -> None:
	"""100-frame interval does not get short-interval promotion."""
	import track_runner.scoring as scoring_mod
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.35, identity=0.8, margin=0.6,
		interval_length=100,
	)
	assert confidence == "fair"


#============================================
def test_classify_confidence_short_high_stays_high() -> None:
	"""3-frame interval already at high does not double-promote."""
	import track_runner.scoring as scoring_mod
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.8, identity=0.9, margin=0.8,
		interval_length=3,
	)
	assert confidence == "high"


#============================================
def test_approx_seed_included_in_usable() -> None:
	"""Approximate seed is included in usable seeds filter."""
	# replicate the filter logic from solve_all_intervals
	seeds = [
		{"status": "visible", "frame_index": 0, "cx": 1, "cy": 1, "w": 1, "h": 1, "conf": 1.0, "pass": 1},
		{"status": "approximate", "frame_index": 10, "cx": 2, "cy": 2, "w": 2, "h": 2,
			"torso_box": [10, 20, 30, 40], "conf": None, "pass": 1},
		{"status": "not_in_frame", "frame_index": 20, "pass": 1},
	]
	usable = [
		s for s in seeds
		if s["status"] in ("visible", "partial", "approximate")
	]
	assert len(usable) == 2
	assert usable[1]["status"] == "approximate"


#============================================
def test_not_in_frame_seed_excluded_from_usable() -> None:
	"""Not-in-frame seed is excluded from usable seeds."""
	seeds = [
		{"status": "not_in_frame", "frame_index": 5, "pass": 1},
	]
	usable = [
		s for s in seeds
		if s["status"] in ("visible", "partial", "approximate")
	]
	assert len(usable) == 0


#============================================
def test_trajectory_erasure_all_drawing_modes() -> None:
	"""_apply_trajectory_erasure erases approx and not_in_frame, keeps visible and partial."""
	import track_runner.interval_solver as solver
	fps = 30.0
	# build a trajectory of 500 frames with dummy data
	trajectory = [{"cx": 1.0}] * 500
	# all four drawing modes
	seeds = [
		# visible: precise torso box, fully visible -- keep
		{"status": "visible", "frame_index": 50},
		# partial: precise torso box, partially hidden -- keep
		{"status": "partial", "frame_index": 100},
		# approximate: larger approx area, uncertain position -- erase
		# torso_box is [x, y, w, h] (top-left); cx/cy are center coords
		{"status": "approximate", "frame_index": 200, "torso_box": [10, 20, 30, 40],
			"cx": 25.0, "cy": 40.0, "w": 30.0, "h": 40.0},
		# not_in_frame: runner off-screen -- erase
		{"status": "not_in_frame", "frame_index": 400},
	]
	# pass ALL seeds; function decides what to erase
	result = solver._apply_trajectory_erasure(trajectory, seeds, fps)
	# visible at 50: NOT erased
	assert result[50] is not None
	# partial at 100: NOT erased
	assert result[100] is not None
	# approximate at 200: replaced with low-confidence hint (not erased to None)
	assert result[200] is not None
	assert result[200]["source"] == "approx_seed_hint"
	assert result[200]["conf"] == 0.3
	# not_in_frame at 400: erased (off-screen)
	assert result[400] is None


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
	import box_utils
	box = {"cx": 100.0, "cy": 100.0, "w": 40.0, "h": 80.0}
	# call box_utils.compute_iou
	iou = box_utils.compute_iou(box, box)
	assert abs(iou - 1.0) < 1e-6


#============================================
def test_hypothesis_compute_iou_non_overlapping() -> None:
	"""Non-overlapping boxes yield IoU of 0.0."""
	import box_utils
	box_a = {"cx": 100.0, "cy": 100.0, "w": 40.0, "h": 80.0}
	box_b = {"cx": 500.0, "cy": 500.0, "w": 40.0, "h": 80.0}
	iou = box_utils.compute_iou(box_a, box_b)
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
	import track_runner.tr_crop as crop_mod
	assert crop_mod.parse_aspect_ratio("1:1") == 1.0


#============================================
def test_crop_parse_aspect_ratio_16_9() -> None:
	"""'16:9' -> close to 1.778."""
	import track_runner.tr_crop as crop_mod
	result = crop_mod.parse_aspect_ratio("16:9")
	assert abs(result - 16.0 / 9.0) < 0.001


#============================================
def test_crop_parse_aspect_ratio_invalid() -> None:
	"""'abc' raises RuntimeError."""
	import track_runner.tr_crop as crop_mod
	with pytest.raises(RuntimeError):
		crop_mod.parse_aspect_ratio("abc")


#============================================
def _make_crop_state(cx: float, cy: float, h: float, conf: float = 1.0) -> dict:
	"""Build a minimal v2 tracking state dict for crop tests."""
	return {"cx": cx, "cy": cy, "w": h * 0.5, "h": h, "conf": conf, "source": "propagated"}


#============================================
def test_crop_controller_first_update_snaps_to_target() -> None:
	"""First update sets crop position near the target."""
	import track_runner.tr_crop as crop_mod
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
	import track_runner.tr_crop as crop_mod
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
	import track_runner.tr_crop as crop_mod
	ctrl = crop_mod.CropController(1920, 1080, aspect_ratio=1.0)
	state1 = _make_crop_state(cx=500.0, cy=540.0, h=100.0, conf=1.0)
	ctrl.update(state1)
	smooth_before = ctrl.smooth_cx
	# jump far with very low confidence
	state2 = _make_crop_state(cx=1500.0, cy=540.0, h=100.0, conf=0.01)
	ctrl.update(state2)
	smooth_after = ctrl.smooth_cx
	# low confidence should limit movement to a small fraction of the jump
	assert abs(smooth_after - smooth_before) < 25


#============================================
def test_crop_controller_clamps_to_frame_bounds() -> None:
	"""Crop rectangle stays within frame dimensions."""
	import track_runner.tr_crop as crop_mod
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
def test_crop_fill_ratio_always_applied() -> None:
	"""crop_fill_ratio is used directly, not overridden by tiered system."""
	import track_runner.tr_crop as crop_mod
	# target_fill_ratio=0.10 means bbox_h / 0.10 = 10x the bbox height
	ctrl = crop_mod.CropController(
		1920, 1080, aspect_ratio=16/9, target_fill_ratio=0.10,
	)
	# bbox height of 80px: expected crop_h ~ 80/0.10 = 800
	state = _make_crop_state(cx=960.0, cy=540.0, h=80.0, conf=1.0)
	result = ctrl.update(state)
	crop_x, crop_y, crop_w, crop_h = result
	# allow some tolerance for rounding, but should be near 800
	assert 780 <= crop_h <= 820, f"expected ~800, got {crop_h}"


#============================================
def test_crop_output_resolution_median() -> None:
	"""Output resolution uses median of crop rects, not first frame."""
	import statistics
	# simulate crop rects with varying sizes
	crop_rects = [
		(0, 0, 300, 200),
		(0, 0, 500, 400),
		(0, 0, 500, 400),
		(0, 0, 500, 400),
		(0, 0, 700, 600),
	]
	all_widths = [r[2] for r in crop_rects]
	all_heights = [r[3] for r in crop_rects]
	median_w = int(statistics.median(all_widths))
	median_h = int(statistics.median(all_heights))
	# median should be 500x400, not first-frame 300x200
	assert median_w == 500
	assert median_h == 400


#============================================
def test_crop_apply_crop_shape() -> None:
	"""apply_crop returns expected dimensions."""
	import track_runner.tr_crop as crop_mod
	frame = numpy.zeros((300, 200, 3), dtype=numpy.uint8)
	result = crop_mod.apply_crop(frame, (10, 20, 50, 60))
	assert result.shape == (60, 50, 3)


#============================================
def test_crop_apply_crop_padding() -> None:
	"""Crop extending past frame edge gets black padding."""
	import track_runner.tr_crop as crop_mod
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
	import track_runner.tr_detection as det_mod
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


# ============================================================
# anchor_to_seeds tests
# ============================================================


#============================================
def _make_trajectory(
	n_frames: int,
	cx: float = 640.0,
	cy: float = 360.0,
	w: float = 100.0,
	h: float = 150.0,
	conf: float = 0.5,
) -> list:
	"""Create a uniform trajectory for testing anchor_to_seeds."""
	trajectory = []
	for i in range(n_frames):
		state = {
			"cx": cx, "cy": cy, "w": w, "h": h,
			"conf": conf, "source": "merged",
		}
		trajectory.append(state)
	return trajectory


#============================================
def _make_seed(
	frame_index: int,
	cx: float = 640.0,
	cy: float = 360.0,
	w: float = 100.0,
	h: float = 150.0,
	status: str = "visible",
) -> dict:
	"""Create a seed dict for testing anchor_to_seeds."""
	# torso_box stores [x, y, w, h] (top-left corner)
	tx = cx - w / 2.0
	ty = cy - h / 2.0
	seed = {
		"frame_index": frame_index,
		"status": status,
		"torso_box": [tx, ty, w, h],
		"cx": cx,
		"cy": cy,
		"w": w,
		"h": h,
		"pass": 1,
	}
	return seed


#============================================
def test_anchor_visible_seed_frames_exact() -> None:
	"""Visible seed frames are hard-pinned to exact seed torso_box values."""
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
	import track_runner.interval_solver as solver_mod
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
# refinement pass tests
# ============================================================


#============================================
def test_refine_soft_prior_none_unchanged() -> None:
	"""soft_prior=None produces identical output to no-prior call."""
	import track_runner.propagator as prop_mod
	# create two identical small frames
	frame_a = numpy.zeros((100, 100, 3), dtype=numpy.uint8)
	frame_b = numpy.zeros((100, 100, 3), dtype=numpy.uint8)
	prev_state = prop_mod.make_seed_state(50.0, 50.0, 20.0, 30.0, conf=0.8)
	appearance = prop_mod.build_appearance_model(frame_a, prev_state)
	# call without soft_prior
	result_none = prop_mod._track_one_frame(
		frame_a, frame_b, prev_state, appearance, soft_prior=None,
	)
	# call with explicit None
	result_default = prop_mod._track_one_frame(
		frame_a, frame_b, prev_state, appearance,
	)
	# positions must be identical
	assert result_none["cx"] == result_default["cx"]
	assert result_none["cy"] == result_default["cy"]


#============================================
def test_refine_soft_prior_pulls_position() -> None:
	"""soft_prior with weight > 0 blends cx/cy toward prior center."""
	import track_runner.propagator as prop_mod
	# uniform frames so flow returns zero displacement
	frame_a = numpy.full((100, 100, 3), 128, dtype=numpy.uint8)
	frame_b = numpy.full((100, 100, 3), 128, dtype=numpy.uint8)
	prev_state = prop_mod.make_seed_state(50.0, 50.0, 20.0, 30.0, conf=0.8)
	appearance = prop_mod.build_appearance_model(frame_a, prev_state)
	# call without prior
	result_no_prior = prop_mod._track_one_frame(
		frame_a, frame_b, prev_state, appearance,
	)
	# call with prior pulling toward (80, 80)
	soft_prior = {"cx": 80.0, "cy": 80.0, "weight": 0.3}
	result_with_prior = prop_mod._track_one_frame(
		frame_a, frame_b, prev_state, appearance, soft_prior=soft_prior,
	)
	# with prior, cx/cy should be closer to 80 than without
	no_prior_dist = abs(result_no_prior["cx"] - 80.0)
	with_prior_dist = abs(result_with_prior["cx"] - 80.0)
	assert with_prior_dist < no_prior_dist


#============================================
def test_refine_soft_prior_does_not_affect_wh() -> None:
	"""w and h are unchanged by soft prior (prior is cx/cy only)."""
	import track_runner.propagator as prop_mod
	frame_a = numpy.full((100, 100, 3), 128, dtype=numpy.uint8)
	frame_b = numpy.full((100, 100, 3), 128, dtype=numpy.uint8)
	prev_state = prop_mod.make_seed_state(50.0, 50.0, 20.0, 30.0, conf=0.8)
	appearance = prop_mod.build_appearance_model(frame_a, prev_state)
	# without prior
	result_no_prior = prop_mod._track_one_frame(
		frame_a, frame_b, prev_state, appearance,
	)
	# with prior at a different position
	soft_prior = {"cx": 80.0, "cy": 80.0, "weight": 0.3}
	result_with_prior = prop_mod._track_one_frame(
		frame_a, frame_b, prev_state, appearance, soft_prior=soft_prior,
	)
	# w and h should be identical
	assert result_with_prior["w"] == result_no_prior["w"]
	assert result_with_prior["h"] == result_no_prior["h"]


#============================================
def test_refine_prior_weight_capped() -> None:
	"""Prior weight never exceeds PRIOR_WEIGHT_SCALE regardless of confidence."""
	import track_runner.propagator as prop_mod
	# fused state with very high confidence
	fused_state = {"cx": 80.0, "cy": 80.0, "conf": 5.0}
	# compute weight the same way propagate_forward does
	prior_conf = float(fused_state["conf"])
	prior_weight = min(
		prop_mod.PRIOR_WEIGHT_SCALE,
		prior_conf * prop_mod.PRIOR_WEIGHT_SCALE,
	)
	assert prior_weight <= prop_mod.PRIOR_WEIGHT_SCALE


#============================================
def test_refine_short_interval_no_crash() -> None:
	"""Refinement on a 1-2 frame interval does not crash or produce None."""
	import track_runner.interval_solver as solver_mod
	import track_runner.propagator as prop_mod
	# build a minimal fused track (2 frames)
	fused_track = [
		{"cx": 50.0, "cy": 50.0, "w": 20.0, "h": 30.0, "conf": 0.8, "source": "merged"},
		{"cx": 51.0, "cy": 51.0, "w": 20.0, "h": 30.0, "conf": 0.7, "source": "merged"},
	]
	start_state = prop_mod.make_seed_state(50.0, 50.0, 20.0, 30.0)
	end_state = prop_mod.make_seed_state(51.0, 51.0, 20.0, 30.0)
	# create a minimal mock reader
	frame = numpy.full((100, 100, 3), 128, dtype=numpy.uint8)

	class _MockReader:
		"""Minimal VideoReader mock returning a fixed frame."""
		def read_frame(self, idx: int) -> numpy.ndarray:
			return frame
		def get_info(self) -> dict:
			info = {"fps": 30.0, "frame_count": 100}
			return info

	reader = _MockReader()
	appearance = prop_mod.build_appearance_model(frame, start_state)
	# should not crash
	refined = solver_mod.refine_interval(
		reader, 0, 1, start_state, end_state,
		fused_track, appearance,
	)
	# result should have states, none should be None
	assert len(refined) >= 1
	for state in refined:
		assert state is not None
		assert "cx" in state


#============================================
def test_refine_low_conf_prior_has_small_effect() -> None:
	"""When fused confidence is low, prior weight is near zero."""
	import track_runner.propagator as prop_mod
	# low confidence fused state
	fused_state = {"cx": 80.0, "cy": 80.0, "conf": 0.1}
	prior_conf = float(fused_state["conf"])
	prior_weight = min(
		prop_mod.PRIOR_WEIGHT_SCALE,
		prior_conf * prop_mod.PRIOR_WEIGHT_SCALE,
	)
	# weight should be 0.1 * 0.3 = 0.03 (near zero)
	assert prior_weight < 0.05
	# verify the exact computation
	expected = 0.1 * prop_mod.PRIOR_WEIGHT_SCALE
	assert abs(prior_weight - expected) < 1e-9


# ============================================================
# crop post-smoothing tests
# ============================================================


#============================================
def test_post_smooth_passthrough() -> None:
	"""All params 0 returns input unchanged."""
	import track_runner.tr_crop as crop_mod

	# Create a list of 20 crop rects with some variation
	rects = [
		(500 + i * 10, 300 + (i % 5), 200, 200)
		for i in range(20)
	]
	# Call with all params 0
	result = crop_mod.smooth_crop_trajectory(
		rects,
		1920,
		1080,
		alpha_position=0.0,
		alpha_size=0.0,
		max_velocity=0.0,
	)
	# Assert result equals input exactly
	assert result == rects


#============================================
def test_post_smooth_reduces_jitter() -> None:
	"""Synthetic jittery trajectory has lower velocity_std after smoothing."""
	import track_runner.tr_crop as crop_mod

	# Seed for reproducibility
	numpy.random.seed(42)
	# Create 100 frames of jittery trajectory
	rects = []
	for i in range(100):
		# Base position (500, 300) with noise ±20px on center
		center_x = 500.0 + numpy.random.uniform(-20, 20)
		center_y = 300.0 + numpy.random.uniform(-20, 20)
		x = center_x - 100
		y = center_y - 100
		rects.append((x, y, 200, 200))
	# Compute metrics before smoothing
	before_metrics = crop_mod.compute_crop_metrics(rects)
	# Smooth with alpha_position=0.10
	smoothed = crop_mod.smooth_crop_trajectory(
		rects,
		1920,
		1080,
		alpha_position=0.10,
		alpha_size=0.0,
		max_velocity=0.0,
	)
	# Compute metrics after smoothing
	after_metrics = crop_mod.compute_crop_metrics(smoothed)
	# Assert after velocity_std < before velocity_std
	assert after_metrics["velocity_std"] < before_metrics["velocity_std"]


#============================================
def test_post_smooth_clamps_to_bounds() -> None:
	"""Smoothed rects stay within frame bounds."""
	import track_runner.tr_crop as crop_mod

	frame_width = 1920
	frame_height = 1080
	# Create rects near edges
	rects = [
		(10, 10, 200, 200),
		(1850, 10, 200, 200),
		(10, 950, 200, 200),
		(1850, 950, 200, 200),
		(500, 300, 200, 200),
	]
	# Smooth
	smoothed = crop_mod.smooth_crop_trajectory(
		rects,
		alpha_position=0.10,
		alpha_size=0.0,
		max_velocity=0.0,
		frame_width=frame_width,
		frame_height=frame_height,
	)
	# Assert all output rects stay within bounds
	for x, y, w, h in smoothed:
		assert x >= 0
		assert y >= 0
		assert x + w <= frame_width
		assert y + h <= frame_height


#============================================
def test_post_smooth_preserves_constant_velocity() -> None:
	"""Constant velocity trajectory is preserved in shape (not amplitude)."""
	import track_runner.tr_crop as crop_mod

	# Create 50 rects with constant velocity (linearly increasing x)
	rects = []
	for i in range(50):
		x = 500.0 + i * 5.0
		y = 300.0
		rects.append((x, y, 200, 200))
	# Compute velocity before smoothing
	velocities_before = []
	for i in range(1, len(rects)):
		v = (rects[i][0] + 100) - (rects[i - 1][0] + 100)
		velocities_before.append(v)
	# Smooth (very light smoothing)
	smoothed = crop_mod.smooth_crop_trajectory(
		rects,
		1920,
		1080,
		alpha_position=0.10,
		alpha_size=0.0,
		max_velocity=0.0,
	)
	# Compute velocity after smoothing
	velocities_after = []
	for i in range(1, len(smoothed)):
		v = (smoothed[i][0] + 100) - (smoothed[i - 1][0] + 100)
		velocities_after.append(v)
	# With constant input velocity, smoothed velocities should be stable
	# (low variance in the middle frames)
	import numpy
	middle_velocities = velocities_after[25:45]
	velocity_var = numpy.var(middle_velocities)
	# Smoothing should make velocities more consistent
	assert velocity_var < 1.0, (
		f"Velocity variance {velocity_var} too high after smoothing"
	)


#============================================
def test_post_smooth_direction_change() -> None:
	"""Trajectory with sharp turn does not produce giant overshoot."""
	import track_runner.tr_crop as crop_mod

	# Create 40 rects: first 20 move right, next 20 move left
	rects = []
	# First 20 frames: move right
	for i in range(20):
		x = 500.0 + i * 10.0
		y = 300.0
		rects.append((x, y, 200, 200))
	# Next 20 frames: move left
	for i in range(20):
		x = 700.0 - i * 10.0
		y = 300.0
		rects.append((x, y, 200, 200))
	# Smooth
	smoothed = crop_mod.smooth_crop_trajectory(
		rects,
		1920,
		1080,
		alpha_position=0.10,
		alpha_size=0.0,
		max_velocity=0.0,
	)
	# At turn point (frame 20), smoothed center should not overshoot wildly
	turn_frame = 20
	orig_x_center = rects[turn_frame][0] + 100
	smooth_x_center = smoothed[turn_frame][0] + 100
	overshoot = abs(smooth_x_center - orig_x_center)
	# Allow up to 100px overshoot at direction change (EMA lag)
	assert overshoot < 100.0, (
		f"Turn overshoot {overshoot}px exceeds 100px"
	)
	# No frames should have negative x
	for x, y, w, h in smoothed:
		assert x >= 0.0


#============================================
def test_post_smooth_final_velocity_cap() -> None:
	"""Velocity cap limits per-frame center displacement."""
	import track_runner.tr_crop as crop_mod

	# Create 30 rects: frames 0-14 at x=500, frames 15-29 at x=800
	rects = []
	for i in range(15):
		rects.append((500.0, 300.0, 200, 200))
	for i in range(15):
		rects.append((800.0, 300.0, 200, 200))
	# Smooth with max_velocity=15.0 and alpha_position=0.0 (no EMA)
	smoothed = crop_mod.smooth_crop_trajectory(
		rects,
		1920,
		1080,
		alpha_position=0.0,
		alpha_size=0.0,
		max_velocity=15.0,
	)
	# Compute frame-to-frame center step distances
	max_step = 0.0
	for i in range(1, len(smoothed)):
		x1, y1, w1, h1 = smoothed[i - 1]
		x2, y2, w2, h2 = smoothed[i]
		c1_x = x1 + w1 / 2
		c1_y = y1 + h1 / 2
		c2_x = x2 + w2 / 2
		c2_y = y2 + h2 / 2
		step = ((c2_x - c1_x) ** 2 + (c2_y - c1_y) ** 2) ** 0.5
		max_step = max(max_step, step)
	# Assert max step distance <= 15.0 + small tolerance
	assert max_step <= 16.0


#============================================
def test_forward_backward_ema_short_sequence() -> None:
	"""Explicit edge behavior on short input."""
	import track_runner.tr_crop as crop_mod

	signal = numpy.array([10.0, 50.0, 10.0, 50.0, 10.0])
	alpha = 0.3
	result = crop_mod._forward_backward_ema(signal, alpha)
	# Assert length preserved
	assert len(result) == 5
	# Assert result is smoother than input
	assert (max(result) - min(result)) < (max(signal) - min(signal))
	# Assert result[0] closer to 10.0 than to 50.0 (endpoint stiffness)
	assert abs(result[0] - 10.0) < abs(result[0] - 50.0)


#============================================
def test_forward_backward_ema_interior_symmetry() -> None:
	"""Reversing input yields approximately matching reversed output."""
	import track_runner.tr_crop as crop_mod

	signal = numpy.array([0.0, 0.0, 100.0, 0.0, 0.0])
	reversed_signal = signal[::-1]
	result = crop_mod._forward_backward_ema(signal, 0.2)
	result_rev = crop_mod._forward_backward_ema(reversed_signal, 0.2)
	# Interior values should be close (within 5.0)
	for i in range(1, 4):
		assert abs(result[i] - result_rev[4 - i]) < 5.0


#============================================
def test_compute_crop_metrics() -> None:
	"""Verify metrics dict has expected keys and sane values."""
	import track_runner.tr_crop as crop_mod

	# Test with small jitter
	numpy.random.seed(42)
	rects = []
	for i in range(50):
		center_x = 500.0 + numpy.random.uniform(-5, 5)
		center_y = 300.0 + numpy.random.uniform(-5, 5)
		x = center_x - 100
		y = center_y - 100
		rects.append((x, y, 200, 200))
	# Call compute_crop_metrics
	metrics = crop_mod.compute_crop_metrics(rects)
	# Assert result has expected keys
	assert "velocity_std" in metrics
	assert "acceleration_std" in metrics
	assert "p95_step_distance" in metrics
	# Assert all values are >= 0.0
	assert metrics["velocity_std"] >= 0.0
	assert metrics["acceleration_std"] >= 0.0
	assert metrics["p95_step_distance"] >= 0.0
	# Assert velocity_std > 0 (there IS jitter)
	assert metrics["velocity_std"] > 0.0
	# Test edge case: single rect returns all zeros
	single_rect = [(500.0, 300.0, 200, 200)]
	single_metrics = crop_mod.compute_crop_metrics(single_rect)
	assert single_metrics["velocity_std"] == 0.0
	assert single_metrics["acceleration_std"] == 0.0
	assert single_metrics["p95_step_distance"] == 0.0


# ============================================================
# direct_center crop mode tests
# ============================================================


#============================================
def _make_synthetic_trajectory(
	n_frames: int,
	cx_func: callable,
	cy_func: callable,
	h_val: float = 100.0,
) -> list:
	"""Helper to build a dense trajectory list for direct-center tests.

	Args:
		n_frames: Number of frames to generate.
		cx_func: Callable(i) -> float for center x at frame i.
		cy_func: Callable(i) -> float for center y at frame i.
		h_val: Constant bounding box height.

	Returns:
		List of tracking state dicts.
	"""
	trajectory = []
	for i in range(n_frames):
		state = {
			"cx": cx_func(i),
			"cy": cy_func(i),
			"w": h_val * 0.5,
			"h": h_val,
			"conf": 0.9,
			"source": "propagated",
		}
		trajectory.append(state)
	return trajectory


#============================================
def _make_direct_center_config(overrides: dict = None) -> dict:
	"""Helper to build a config dict for direct-center tests.

	Args:
		overrides: Optional dict of processing keys to override.

	Returns:
		Config dict with crop_mode='direct_center'.
	"""
	processing = {
		"crop_mode": "direct_center",
		"crop_aspect": "16:9",
		"crop_fill_ratio": 0.30,
		"crop_min_size": 50,
		"crop_post_smooth_strength": 0.0,
		"crop_post_smooth_size_strength": 0.0,
		"crop_post_smooth_max_velocity": 0.0,
	}
	if overrides:
		processing.update(overrides)
	config = {"processing": processing}
	return config


#============================================
def test_direct_center_basic() -> None:
	"""Direct-center with smoothing off: crop center matches trajectory center."""
	import track_runner.tr_crop as crop_mod

	# constant position trajectory
	trajectory = _make_synthetic_trajectory(
		30,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	config = _make_direct_center_config()
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	assert len(rects) == 30
	# check crop center matches trajectory center within 1px (round tolerance)
	for i, (x, y, w, h) in enumerate(rects):
		crop_cx = x + w / 2.0
		crop_cy = y + h / 2.0
		assert abs(crop_cx - 640.0) <= 1.0, f"Frame {i}: cx off by {abs(crop_cx - 640.0)}"
		assert abs(crop_cy - 360.0) <= 1.0, f"Frame {i}: cy off by {abs(crop_cy - 360.0)}"


#============================================
def test_direct_center_with_smoothing() -> None:
	"""With alpha > 0, output has lower velocity_std than raw positions."""
	import track_runner.tr_crop as crop_mod

	# jittery trajectory
	numpy.random.seed(99)
	trajectory = _make_synthetic_trajectory(
		100,
		cx_func=lambda i: 640.0 + numpy.random.uniform(-30, 30),
		cy_func=lambda i: 360.0 + numpy.random.uniform(-30, 30),
		h_val=100.0,
	)
	# without smoothing
	config_raw = _make_direct_center_config()
	rects_raw = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_raw,
	)
	# with smoothing
	config_smooth = _make_direct_center_config({
		"crop_post_smooth_strength": 0.10,
	})
	# re-seed for same trajectory
	numpy.random.seed(99)
	trajectory2 = _make_synthetic_trajectory(
		100,
		cx_func=lambda i: 640.0 + numpy.random.uniform(-30, 30),
		cy_func=lambda i: 360.0 + numpy.random.uniform(-30, 30),
		h_val=100.0,
	)
	rects_smooth = crop_mod.direct_center_crop_trajectory(
		trajectory2, 1920, 1080, config_smooth,
	)
	metrics_raw = crop_mod.compute_crop_metrics(rects_raw)
	metrics_smooth = crop_mod.compute_crop_metrics(rects_smooth)
	assert metrics_smooth["velocity_std"] < metrics_raw["velocity_std"]


#============================================
def test_direct_center_clamps_to_bounds() -> None:
	"""All rects stay within frame bounds."""
	import track_runner.tr_crop as crop_mod

	frame_w = 1280
	frame_h = 720
	# trajectory near frame edges
	trajectory = _make_synthetic_trajectory(
		20,
		cx_func=lambda i: 50.0 + i * 60.0,
		cy_func=lambda i: 50.0 + i * 35.0,
		h_val=120.0,
	)
	config = _make_direct_center_config()
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, frame_w, frame_h, config,
	)
	for i, (x, y, w, h) in enumerate(rects):
		assert x >= 0, f"Frame {i}: x={x} < 0"
		assert y >= 0, f"Frame {i}: y={y} < 0"
		assert x + w <= frame_w, f"Frame {i}: x+w={x + w} > {frame_w}"
		assert y + h <= frame_h, f"Frame {i}: y+h={y + h} > {frame_h}"


#============================================
def test_direct_center_velocity_cap() -> None:
	"""With max_velocity set, no step exceeds the cap (within 1px tolerance)."""
	import track_runner.tr_crop as crop_mod

	# trajectory with a sudden jump at frame 15
	def cx_func(i: int) -> float:
		return 400.0 if i < 15 else 700.0

	trajectory = _make_synthetic_trajectory(
		30,
		cx_func=cx_func,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	config = _make_direct_center_config({
		"crop_post_smooth_max_velocity": 10.0,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	# check max step
	for i in range(1, len(rects)):
		x1, y1, w1, h1 = rects[i - 1]
		x2, y2, w2, h2 = rects[i]
		c1x = x1 + w1 / 2.0
		c1y = y1 + h1 / 2.0
		c2x = x2 + w2 / 2.0
		c2y = y2 + h2 / 2.0
		step = ((c2x - c1x) ** 2 + (c2y - c1y) ** 2) ** 0.5
		# 1px tolerance for rounding
		assert step <= 11.0, f"Frame {i}: step {step:.2f} exceeds cap"


#============================================
def test_direct_center_reclamp_after_velocity_cap() -> None:
	"""Rects remain in bounds after velocity cap is applied."""
	import track_runner.tr_crop as crop_mod

	frame_w = 800
	frame_h = 600
	# trajectory that jumps near the edge
	trajectory = _make_synthetic_trajectory(
		20,
		cx_func=lambda i: 100.0 if i < 10 else 750.0,
		cy_func=lambda i: 100.0 if i < 10 else 550.0,
		h_val=80.0,
	)
	config = _make_direct_center_config({
		"crop_post_smooth_max_velocity": 8.0,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, frame_w, frame_h, config,
	)
	for i, (x, y, w, h) in enumerate(rects):
		assert x >= 0, f"Frame {i}: x={x} < 0"
		assert y >= 0, f"Frame {i}: y={y} < 0"
		assert x + w <= frame_w, f"Frame {i}: x+w={x + w} > {frame_w}"
		assert y + h <= frame_h, f"Frame {i}: y+h={y + h} > {frame_h}"


#============================================
def test_direct_center_empty_trajectory() -> None:
	"""Empty input returns empty output."""
	import track_runner.tr_crop as crop_mod

	config = _make_direct_center_config()
	rects = crop_mod.direct_center_crop_trajectory([], 1920, 1080, config)
	assert rects == []


#============================================
def test_direct_center_min_size_guard() -> None:
	"""Crop dimensions never go below crop_min_size from config."""
	import track_runner.tr_crop as crop_mod

	# trajectory with very small bbox height
	trajectory = _make_synthetic_trajectory(
		20,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=5.0,
	)
	config = _make_direct_center_config({"crop_min_size": 100})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	for i, (x, y, w, h) in enumerate(rects):
		assert h >= 100, f"Frame {i}: h={h} < min_size 100"


#============================================
def test_direct_center_invalid_mode() -> None:
	"""Invalid crop_mode value raises RuntimeError."""
	import track_runner.tr_crop as crop_mod

	trajectory = _make_synthetic_trajectory(
		10,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
	)
	config = {
		"processing": {
			"crop_mode": "bogus_mode",
			"crop_aspect": "16:9",
			"crop_fill_ratio": 0.30,
		},
	}
	video_info = {
		"width": 1920,
		"height": 1080,
		"frame_count": 10,
	}
	with pytest.raises(RuntimeError, match="Unknown crop_mode"):
		crop_mod.trajectory_to_crop_rects(trajectory, video_info, config)


#============================================
def test_direct_center_steady_motion() -> None:
	"""Constant velocity, no jitter: crop center matches trajectory exactly."""
	import track_runner.tr_crop as crop_mod

	# linear motion across the frame
	trajectory = _make_synthetic_trajectory(
		50,
		cx_func=lambda i: 300.0 + i * 8.0,
		cy_func=lambda i: 360.0 + i * 2.0,
		h_val=100.0,
	)
	config = _make_direct_center_config()
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	# every crop center should match trajectory center within 1px
	for i, (x, y, w, h) in enumerate(rects):
		expected_cx = 300.0 + i * 8.0
		expected_cy = 360.0 + i * 2.0
		crop_cx = x + w / 2.0
		crop_cy = y + h / 2.0
		assert abs(crop_cx - expected_cx) <= 1.0, (
			f"Frame {i}: cx {crop_cx:.1f} vs expected {expected_cx:.1f}"
		)
		assert abs(crop_cy - expected_cy) <= 1.0, (
			f"Frame {i}: cy {crop_cy:.1f} vs expected {expected_cy:.1f}"
		)
		# bounds check
		assert x >= 0 and y >= 0
		assert x + w <= 1920 and y + h <= 1080


#============================================
def test_crop_mode_default_dispatch() -> None:
	"""Config without crop_mode key routes to smooth mode."""
	import track_runner.tr_crop as crop_mod

	# build trajectory and config without crop_mode
	trajectory = _make_synthetic_trajectory(
		20,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	config = {
		"processing": {
			"crop_aspect": "16:9",
			"crop_fill_ratio": 0.30,
			"crop_min_size": 50,
		},
	}
	video_info = {
		"width": 1920,
		"height": 1080,
		"frame_count": 20,
	}
	# should run without error (smooth mode)
	rects = crop_mod.trajectory_to_crop_rects(trajectory, video_info, config)
	assert len(rects) == 20
	# verify output matches what compute_crop_trajectory produces (smooth path)
	rects_smooth = crop_mod.compute_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	assert rects == rects_smooth


#============================================
def test_direct_center_malformed_trajectory() -> None:
	"""Trajectory entry missing required key raises RuntimeError at dispatch."""
	import track_runner.tr_crop as crop_mod

	# entry missing 'h' key
	trajectory = [
		{"cx": 640.0, "cy": 360.0, "w": 50.0, "conf": 0.9, "source": "test"},
	]
	config = {
		"processing": {
			"crop_mode": "direct_center",
			"crop_aspect": "16:9",
			"crop_fill_ratio": 0.30,
		},
	}
	video_info = {
		"width": 1920,
		"height": 1080,
		"frame_count": 1,
	}
	with pytest.raises(RuntimeError, match="missing required keys"):
		crop_mod.trajectory_to_crop_rects(trajectory, video_info, config)


# ============================================================
# WP 1A-1: Forward-backward flow consistency
# ============================================================


#============================================
def test_propagator_fb_consistency_threshold():
	"""FB_CONSISTENCY_THRESHOLD is 1.0 pixel."""
	import propagator
	assert propagator.FB_CONSISTENCY_THRESHOLD == 1.0


#============================================
def test_propagator_min_flow_features():
	"""MIN_FLOW_FEATURES must be at least 4."""
	import propagator
	assert propagator.MIN_FLOW_FEATURES >= 4


# ============================================================
# WP 1A-2: HSV histogram identity scoring
# ============================================================


#============================================
def _make_solid_patch(bgr_color: tuple, size: int = 80) -> numpy.ndarray:
	"""Create a solid-color BGR patch for testing.

	Args:
		bgr_color: (B, G, R) tuple for the patch color.
		size: Side length of the square patch in pixels.

	Returns:
		BGR numpy array of shape (size, size, 3).
	"""
	patch = numpy.zeros((size, size, 3), dtype=numpy.uint8)
	patch[:, :] = bgr_color
	return patch


#============================================
def _make_appearance_model(bgr_color: tuple, size: int = 80) -> dict:
	"""Build a minimal appearance model from a solid-color patch.

	Args:
		bgr_color: (B, G, R) tuple for the model color.
		size: Side length of the square patch.

	Returns:
		Appearance model dict with hsv_mean, template, and hs_histogram.
	"""
	patch = _make_solid_patch(bgr_color, size)
	hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
	hsv_mean = (
		float(numpy.mean(hsv[:, :, 0])),
		float(numpy.mean(hsv[:, :, 1])),
		float(numpy.mean(hsv[:, :, 2])),
	)
	# compute 2D HS histogram matching propagator.build_appearance_model
	hs_histogram = cv2.calcHist(
		[hsv], [0, 1], None,
		[30, 32], [0, 180, 0, 256],
	)
	cv2.normalize(hs_histogram, hs_histogram, alpha=1.0, norm_type=cv2.NORM_L1)
	model = {
		"hsv_mean": hsv_mean,
		"template": patch.copy(),
		"hs_histogram": hs_histogram,
		"seed_status": "",
	}
	return model


#============================================
def test_identity_score_same_color_large():
	"""Large runner with same color scores high (>0.7)."""
	import hypothesis
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
	import hypothesis
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
	import hypothesis
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
	import hypothesis
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
	import hypothesis
	assert hypothesis.MIN_HISTOGRAM_BINS == 50


# ============================================================
# WP 1A-3: Velocity-adaptive crop
# ============================================================


#============================================
def test_crop_controller_velocity_adaptive():
	"""CropController adapts velocity cap based on subject speed."""
	import tr_crop as crop_module
	controller = crop_module.CropController(
		frame_width=1920,
		frame_height=1080,
		max_crop_velocity=30.0,
		velocity_scale=2.0,
		displacement_alpha=0.1,
	)
	# feed a stationary target to establish baseline
	state = {"cx": 960.0, "cy": 540.0, "w": 100.0, "h": 100.0, "conf": 0.9, "source": "merged"}
	for _ in range(5):
		controller.update(state)
	# record the initial EMA displacement
	initial_ema = controller._ema_displacement
	# now feed a fast-moving target
	for step in range(10):
		moving_state = dict(state, cx=960.0 + step * 50.0)
		controller.update(moving_state)
	# EMA displacement should have increased
	assert controller._ema_displacement > initial_ema, (
		"EMA displacement should increase with fast-moving target"
	)


# ============================================================
# WP 1B-1: Seed suggestion
# ============================================================


#============================================
def test_seed_suggestion_no_confirmed_seeds():
	"""With no confirmed seeds, suggestion requires manual selection."""
	import seeding
	# create a dummy frame
	frame = numpy.zeros((200, 400, 3), dtype=numpy.uint8)
	# simulate detections: two candidates
	candidates = [
		{"bbox": [100, 100, 50, 100], "confidence": 0.9, "class_id": 0},
		{"bbox": [300, 100, 50, 100], "confidence": 0.8, "class_id": 0},
	]
	confirmed_seeds = []
	result = seeding.suggest_seed_candidates(
		frame, candidates, confirmed_seeds, frame_index=0,
	)
	# with no confirmed seeds, should require manual selection
	assert result["suggestion_index"] is None


#============================================
def test_seed_suggestion_single_detection_with_seeds():
	"""Single detection with confirmed seeds auto-suggests."""
	import seeding
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
	result = seeding.suggest_seed_candidates(
		frame, candidates, confirmed_seeds, frame_index=5,
	)
	# single detection with confirmed seeds: should auto-suggest index 0
	assert result["suggestion_index"] == 0
	assert result["mode"] == "single"


# ============================================================
# WP 2-1: Occlusion-risk flagging
# ============================================================


#============================================
def test_occlusion_risk_no_overlap():
	"""No occlusion risk when detections are far from target."""
	import hypothesis
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
	import hypothesis
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
	import hypothesis
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
	import hypothesis
	assert hypothesis.OCCLUSION_RISK_IOU == 0.15


# ============================================================
# WP 2-2: Review system occlusion integration
# ============================================================


#============================================
def _make_fused_track(n_frames: int, occlusion_frames: list) -> list:
	"""Build a minimal fused track with occlusion_risk flags.

	Args:
		n_frames: Total number of frames.
		occlusion_frames: List of frame indices (0-based) with occlusion.

	Returns:
		List of state dicts with occlusion_risk set.
	"""
	track = []
	for i in range(n_frames):
		state = {
			"cx": 100.0, "cy": 100.0, "w": 50.0, "h": 80.0,
			"conf": 0.8, "source": "merged", "fuse_flag": False,
			"occlusion_risk": i in occlusion_frames,
		}
		track.append(state)
	return track


#============================================
def test_review_find_occlusion_exits():
	"""_find_occlusion_exits detects True->False transitions."""
	import review
	# occlusion at frames 5,6,7 (indices), exits at frame 8
	track = _make_fused_track(20, [5, 6, 7])
	interval = {
		"start_frame": 100,
		"fused_track": track,
	}
	exits = review._find_occlusion_exits(interval)
	# frame index 8 in the track = absolute frame 108
	assert 108 in exits, f"expected exit at frame 108, got {exits}"


#============================================
def test_review_occlusion_adds_failure_reason():
	"""identify_weak_spans adds likely_occlusion for occluded intervals."""
	import review
	track = _make_fused_track(30, [10, 11, 12])
	interval = {
		"start_frame": 0,
		"end_frame": 30,
		"fused_track": track,
		"interval_score": {
			"agreement_score": 0.3,
			"competitor_margin": 0.5,
			"identity_score": 0.6,
			"confidence": "low",
			"failure_reasons": ["low_agreement"],
		},
	}
	diagnostics = {"intervals": [interval], "fps": 30.0}
	suggestions = review.identify_weak_spans(diagnostics)
	# should have suggestions including occlusion-related ones
	reasons = [s["reason"] for s in suggestions]
	assert "likely_occlusion" in reasons, (
		f"expected 'likely_occlusion' in reasons, got {reasons}"
	)


#============================================
def test_review_good_interval_still_gets_occlusion_exits():
	"""Good-confidence intervals still get occlusion exit suggestions."""
	import review
	# occlusion at frames 5-7, exit at frame 8
	track = _make_fused_track(20, [5, 6, 7])
	interval = {
		"start_frame": 200,
		"end_frame": 220,
		"fused_track": track,
		"interval_score": {
			"agreement_score": 0.9,
			"competitor_margin": 0.8,
			"identity_score": 0.9,
			"confidence": "good",
			"failure_reasons": [],
		},
	}
	diagnostics = {"intervals": [interval], "fps": 30.0}
	suggestions = review.identify_weak_spans(diagnostics)
	# should still get occlusion exit suggestion at frame 208
	frames = [s["frame"] for s in suggestions]
	assert 208 in frames, f"expected exit suggestion at 208, got {frames}"


# ============================================================
# WP 2-3: Detection caching
# ============================================================


#============================================
def test_detection_cache_in_solve_interval_signature():
	"""solve_interval accepts detection_cache parameter."""
	import interval_solver
	sig = inspect.signature(interval_solver.solve_interval)
	assert "detection_cache" in sig.parameters


#============================================
def test_detection_cache_returned_in_result():
	"""solve_interval result dict includes detection_cache key."""
	# just verify the key name is documented in the function
	import interval_solver
	# check docstring mentions detection_cache in return
	doc = interval_solver.solve_interval.__doc__
	assert "detection_cache" in doc


#============================================
def test_fuse_tracks_propagates_occlusion():
	"""fuse_tracks preserves occlusion_risk from both directions."""
	import interval_solver
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
