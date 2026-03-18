"""Unit tests for track_runner.regime_classifier module."""

# Standard Library
import math

# PIP3 modules
import numpy
import pytest

# local repo modules
import track_runner.regime_classifier as classifier


# ============================================================
# helpers
# ============================================================


#============================================
def _make_video_info(
	width: int = 1920,
	height: int = 1080,
	fps: float = 30.0,
	frame_count: int = 300,
) -> dict:
	"""Build a minimal video_info dict."""
	return {
		"width": width,
		"height": height,
		"fps": fps,
		"frame_count": frame_count,
	}


#============================================
def _make_trajectory(
	n_frames: int,
	cx: float = 960.0,
	cy: float = 540.0,
	w: float = 60.0,
	h: float = 120.0,
	conf: float = 0.9,
	source: str = "propagated",
) -> list:
	"""Build a uniform trajectory for classifier tests."""
	trajectory = []
	for i in range(n_frames):
		state = {
			"cx": cx, "cy": cy, "w": w, "h": h,
			"conf": conf, "source": source,
		}
		trajectory.append(state)
	return trajectory


# ============================================================
# feature extraction tests
# ============================================================


#============================================
def test_feature_extraction_basic() -> None:
	"""Feature extraction returns correct number of frames."""
	n = 60
	trajectory = _make_trajectory(n)
	video_info = _make_video_info(frame_count=n)
	features = classifier._per_frame_features(trajectory, video_info)
	assert len(features) == n


#============================================
def test_feature_conf_matches_input() -> None:
	"""Per-frame conf should match trajectory confidence."""
	trajectory = _make_trajectory(30, conf=0.75)
	video_info = _make_video_info(frame_count=30)
	features = classifier._per_frame_features(trajectory, video_info)
	for feat in features:
		assert abs(feat["conf"] - 0.75) < 0.01


#============================================
def test_feature_bbox_height_ratio() -> None:
	"""bbox_height_ratio should be h / frame_height."""
	# h=120 in frame of height 1080 -> ratio = 120/1080 ~ 0.111
	trajectory = _make_trajectory(30, h=120.0)
	video_info = _make_video_info(frame_count=30)
	features = classifier._per_frame_features(trajectory, video_info)
	expected = 120.0 / 1080.0
	for feat in features:
		assert abs(feat["bbox_height_ratio"] - expected) < 0.01


#============================================
def test_feature_edge_pressure_centered() -> None:
	"""Centered bbox should have high edge pressure (far from edges)."""
	trajectory = _make_trajectory(30, cx=960.0, cy=540.0, w=100.0, h=120.0)
	video_info = _make_video_info(frame_count=30)
	features = classifier._per_frame_features(trajectory, video_info)
	# centered bbox is far from edges, so edge_pressure should be > 0
	for feat in features:
		assert feat["edge_pressure"] > 0.1


#============================================
def test_feature_edge_pressure_near_edge() -> None:
	"""Bbox near frame edge should have low edge pressure."""
	# place bbox at left edge: cx=30, w=60 -> left edge = 0
	trajectory = _make_trajectory(30, cx=30.0, cy=540.0, w=60.0, h=120.0)
	video_info = _make_video_info(frame_count=30)
	features = classifier._per_frame_features(trajectory, video_info)
	for feat in features:
		assert feat["edge_pressure"] < 0.01


#============================================
def test_feature_source_type_preserved() -> None:
	"""Source type should match trajectory source field."""
	trajectory = _make_trajectory(30, source="hold_last")
	video_info = _make_video_info(frame_count=30)
	features = classifier._per_frame_features(trajectory, video_info)
	for feat in features:
		assert feat["source_type"] == "hold_last"


# ============================================================
# single frame classification tests
# ============================================================


#============================================
def test_classify_single_clear() -> None:
	"""High confidence, normal size -> clear regime."""
	feat = {
		"conf": 0.9, "conf_trend": 0.85,
		"bbox_height_ratio": 0.12,
		"height_change_rate": 0.01,
		"edge_pressure": 0.15,
		"source_type": "propagated",
	}
	label, dist_flag = classifier._classify_single_frame(feat)
	assert label == "clear"
	assert dist_flag is None


#============================================
def test_classify_single_distance_far() -> None:
	"""Small bbox_height_ratio -> distance with far flag."""
	feat = {
		"conf": 0.9, "conf_trend": 0.85,
		"bbox_height_ratio": 0.04,
		"height_change_rate": 0.01,
		"edge_pressure": 0.15,
		"source_type": "propagated",
	}
	label, dist_flag = classifier._classify_single_frame(feat)
	assert label == "distance"
	assert dist_flag == "far"


#============================================
def test_classify_single_distance_near() -> None:
	"""Large bbox_height_ratio -> distance with near flag."""
	feat = {
		"conf": 0.9, "conf_trend": 0.85,
		"bbox_height_ratio": 0.30,
		"height_change_rate": 0.01,
		"edge_pressure": 0.15,
		"source_type": "propagated",
	}
	label, dist_flag = classifier._classify_single_frame(feat)
	assert label == "distance"
	assert dist_flag == "near"


#============================================
def test_classify_single_uncertain_with_corroboration() -> None:
	"""Low confidence + degraded source -> uncertain."""
	feat = {
		"conf": 0.3, "conf_trend": 0.4,
		"bbox_height_ratio": 0.12,
		"height_change_rate": 0.01,
		"edge_pressure": 0.15,
		"source_type": "hold_last",
	}
	label, dist_flag = classifier._classify_single_frame(feat)
	assert label == "uncertain"
	assert dist_flag is None


#============================================
def test_classify_confidence_alone_stays_clear() -> None:
	"""INVARIANT: Confidence drop alone (no corroboration) -> remains clear.

	This enforces the key classifier invariant: confidence alone must
	never trigger uncertain. Without geometric or source-type corroboration,
	the frame stays clear.
	"""
	feat = {
		"conf": 0.3, "conf_trend": 0.4,
		"bbox_height_ratio": 0.12,
		"height_change_rate": 0.01,
		# good edge pressure, normal source -- no corroboration
		"edge_pressure": 0.15,
		"source_type": "propagated",
	}
	label, dist_flag = classifier._classify_single_frame(feat)
	assert label == "clear", (
		"Confidence alone triggered uncertain -- violates classifier invariant"
	)


#============================================
def test_classify_uncertain_edge_pressure_corroboration() -> None:
	"""Low confidence + high edge pressure -> uncertain."""
	feat = {
		"conf": 0.3, "conf_trend": 0.4,
		"bbox_height_ratio": 0.12,
		"height_change_rate": 0.01,
		# low edge pressure = near frame edge = corroboration
		"edge_pressure": 0.005,
		"source_type": "propagated",
	}
	label, dist_flag = classifier._classify_single_frame(feat)
	assert label == "uncertain"


#============================================
def test_classify_uncertain_height_instability_corroboration() -> None:
	"""Low confidence + height instability -> uncertain."""
	feat = {
		"conf": 0.3, "conf_trend": 0.4,
		"bbox_height_ratio": 0.12,
		"height_change_rate": 0.20,
		"edge_pressure": 0.15,
		"source_type": "propagated",
	}
	label, dist_flag = classifier._classify_single_frame(feat)
	assert label == "uncertain"


# ============================================================
# full classify_regimes tests
# ============================================================


#============================================
def test_all_high_confidence_is_all_clear() -> None:
	"""Uniform high-confidence trajectory should produce all-clear."""
	n = 90
	trajectory = _make_trajectory(n, conf=0.9)
	video_info = _make_video_info(frame_count=n, fps=30.0)
	spans = classifier.classify_regimes(trajectory, video_info)
	# should have exactly one span, all clear
	assert len(spans) == 1
	assert spans[0]["regime"] == "clear"
	assert spans[0]["start_frame"] == 0
	assert spans[0]["end_frame"] == n


#============================================
def test_confidence_drop_with_hold_last_creates_uncertain() -> None:
	"""Confidence drop + hold_last source -> uncertain span."""
	n = 90
	trajectory = _make_trajectory(n, conf=0.9)
	# frames 30-59: low conf + hold_last source
	for i in range(30, 60):
		trajectory[i]["conf"] = 0.2
		trajectory[i]["source"] = "hold_last"
	video_info = _make_video_info(frame_count=n, fps=30.0)
	spans = classifier.classify_regimes(trajectory, video_info)
	# find uncertain span
	uncertain_spans = [s for s in spans if s["regime"] == "uncertain"]
	assert len(uncertain_spans) >= 1
	# uncertain span should cover roughly frames 30-60
	unc = uncertain_spans[0]
	assert unc["start_frame"] <= 35
	assert unc["end_frame"] >= 55


#============================================
def test_short_blip_does_not_create_new_regime() -> None:
	"""A 3-frame confidence drop should be smoothed away."""
	n = 90
	trajectory = _make_trajectory(n, conf=0.9)
	# only 3 frames with low conf + hold_last -- too short for a span
	for i in range(40, 43):
		trajectory[i]["conf"] = 0.2
		trajectory[i]["source"] = "hold_last"
	video_info = _make_video_info(frame_count=n, fps=30.0)
	spans = classifier.classify_regimes(trajectory, video_info)
	# smoothing should absorb the 3-frame blip into clear
	assert len(spans) == 1
	assert spans[0]["regime"] == "clear"


#============================================
def test_small_bbox_creates_distance_far() -> None:
	"""Small bbox (h/frame_h < 0.08) -> distance span with far flag."""
	n = 90
	# h=50 in 1080p -> ratio = 0.046, well below 0.08
	trajectory = _make_trajectory(n, h=50.0, w=25.0, conf=0.9)
	video_info = _make_video_info(frame_count=n, fps=30.0)
	spans = classifier.classify_regimes(trajectory, video_info)
	assert len(spans) == 1
	assert spans[0]["regime"] == "distance"
	assert spans[0]["distance_flag"] == "far"


#============================================
def test_large_bbox_creates_distance_near() -> None:
	"""Large bbox (h/frame_h > 0.25) -> distance span with near flag."""
	n = 90
	# h=300 in 1080p -> ratio = 0.278, above 0.25
	trajectory = _make_trajectory(n, h=300.0, w=150.0, conf=0.9)
	video_info = _make_video_info(frame_count=n, fps=30.0)
	spans = classifier.classify_regimes(trajectory, video_info)
	assert len(spans) == 1
	assert spans[0]["regime"] == "distance"
	assert spans[0]["distance_flag"] == "near"


#============================================
def test_blend_zones_exist_at_transitions() -> None:
	"""Adjacent regime spans should have blend zones."""
	n = 120
	trajectory = _make_trajectory(n, conf=0.9)
	# make frames 60-119 have small bbox -> distance
	for i in range(60, n):
		trajectory[i]["h"] = 50.0
		trajectory[i]["w"] = 25.0
	video_info = _make_video_info(frame_count=n, fps=30.0)
	spans = classifier.classify_regimes(trajectory, video_info)
	# should have at least 2 spans with blend zones
	assert len(spans) >= 2
	# check that at least one span has blend_in or blend_out > 0
	has_blend = False
	for span in spans:
		if span["blend_in"] > 0 or span["blend_out"] > 0:
			has_blend = True
	assert has_blend, "Expected blend zones at regime transitions"


#============================================
def test_regime_summary_format() -> None:
	"""format_regime_summary produces expected string format."""
	spans = [
		{
			"start_frame": 0, "end_frame": 85, "regime": "clear",
			"distance_flag": None, "blend_in": 0, "blend_out": 5,
			"mean_conf": 0.9, "mean_bbox_ratio": 0.12,
		},
		{
			"start_frame": 85, "end_frame": 100, "regime": "uncertain",
			"distance_flag": None, "blend_in": 5, "blend_out": 0,
			"mean_conf": 0.4, "mean_bbox_ratio": 0.12,
		},
	]
	summary = classifier.format_regime_summary(spans, 100)
	assert "clear" in summary
	assert "uncertain" in summary
	assert "1 transitions" in summary


#============================================
def test_empty_trajectory() -> None:
	"""Empty trajectory should return empty span list."""
	spans = classifier.classify_regimes([], _make_video_info(frame_count=0))
	assert spans == []
