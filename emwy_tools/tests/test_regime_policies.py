"""Unit tests for track_runner.regime_policies module."""

# PIP3 modules
import pytest

# local repo modules
import track_runner.regime_policies as policies


# ============================================================
# regime defaults tests
# ============================================================


#============================================
def test_defaults_have_exactly_two_keys_per_regime() -> None:
	"""Each regime default must have exactly fill_ratio and size_update_mode."""
	for regime in ("clear", "uncertain"):
		params = policies.REGIME_DEFAULTS[regime]
		assert set(params.keys()) == {"fill_ratio", "size_update_mode"}

	# distance has sub-flags
	for flag in ("far", "near"):
		params = policies.REGIME_DEFAULTS["distance"][flag]
		assert set(params.keys()) == {"fill_ratio", "size_update_mode"}


#============================================
def test_clear_defaults() -> None:
	"""Clear regime should have normal size_update_mode."""
	params = policies.REGIME_DEFAULTS["clear"]
	assert params["fill_ratio"] == 0.30
	assert params["size_update_mode"] == "normal"


#============================================
def test_uncertain_defaults() -> None:
	"""Uncertain regime should have frozen size_update_mode."""
	params = policies.REGIME_DEFAULTS["uncertain"]
	assert params["size_update_mode"] == "frozen"


#============================================
def test_distance_far_defaults() -> None:
	"""Distance far should have lower fill_ratio (wider crop)."""
	params = policies.REGIME_DEFAULTS["distance"]["far"]
	# far fill_ratio should be less than clear fill_ratio
	clear_fill = policies.REGIME_DEFAULTS["clear"]["fill_ratio"]
	assert params["fill_ratio"] < clear_fill
	assert params["size_update_mode"] == "slow"


#============================================
def test_distance_near_defaults() -> None:
	"""Distance near should have higher fill_ratio (tighter crop)."""
	params = policies.REGIME_DEFAULTS["distance"]["near"]
	clear_fill = policies.REGIME_DEFAULTS["clear"]["fill_ratio"]
	assert params["fill_ratio"] > clear_fill
	assert params["size_update_mode"] == "slow"


# ============================================================
# size mode multiplier tests
# ============================================================


#============================================
def test_normal_multiplier() -> None:
	"""Normal mode multiplier is 1.0."""
	assert policies.get_size_mode_multiplier("normal") == 1.0


#============================================
def test_slow_multiplier() -> None:
	"""Slow mode multiplier is 0.3."""
	assert policies.get_size_mode_multiplier("slow") == 0.3


#============================================
def test_frozen_multiplier() -> None:
	"""Frozen mode multiplier is 0.01."""
	assert policies.get_size_mode_multiplier("frozen") == 0.01


# ============================================================
# get_frame_params tests
# ============================================================


#============================================
def _make_spans() -> list:
	"""Build a two-span test case with blend zones."""
	spans = [
		{
			"start_frame": 0, "end_frame": 50, "regime": "clear",
			"distance_flag": None, "blend_in": 0, "blend_out": 9,
			"mean_conf": 0.9, "mean_bbox_ratio": 0.12,
		},
		{
			"start_frame": 50, "end_frame": 100, "regime": "uncertain",
			"distance_flag": None, "blend_in": 9, "blend_out": 0,
			"mean_conf": 0.4, "mean_bbox_ratio": 0.12,
		},
	]
	return spans


#============================================
def test_frame_params_clear_interior() -> None:
	"""Frame in clear interior should return clear defaults."""
	spans = _make_spans()
	params = policies.get_frame_params(10, spans)
	assert params["fill_ratio"] == 0.30
	assert params["size_update_mode"] == "normal"


#============================================
def test_frame_params_uncertain_interior() -> None:
	"""Frame in uncertain interior should return uncertain defaults."""
	spans = _make_spans()
	params = policies.get_frame_params(70, spans)
	assert params["fill_ratio"] == policies.REGIME_DEFAULTS["uncertain"]["fill_ratio"]
	assert params["size_update_mode"] == "frozen"


#============================================
def test_blend_zone_interpolates_fill_ratio() -> None:
	"""Frame in blend zone should have interpolated fill_ratio."""
	spans = _make_spans()
	clear_fill = policies.REGIME_DEFAULTS["clear"]["fill_ratio"]
	uncertain_fill = policies.REGIME_DEFAULTS["uncertain"]["fill_ratio"]

	# blend-in zone of uncertain span: frames 50-58
	# at frame 50 (t=0): fill should be near clear_fill
	# at frame 58 (t=8/9): fill should be near uncertain_fill
	params_start = policies.get_frame_params(50, spans)
	params_mid = policies.get_frame_params(54, spans)
	params_end = policies.get_frame_params(58, spans)

	# start of blend should be closer to clear fill
	assert abs(params_start["fill_ratio"] - clear_fill) < abs(params_start["fill_ratio"] - uncertain_fill)
	# end of blend should be closer to uncertain fill
	assert abs(params_end["fill_ratio"] - uncertain_fill) < abs(params_end["fill_ratio"] - clear_fill)
	# mid should be between the two
	min_fill = min(clear_fill, uncertain_fill)
	max_fill = max(clear_fill, uncertain_fill)
	assert min_fill <= params_mid["fill_ratio"] <= max_fill


#============================================
def test_empty_spans_returns_clear_defaults() -> None:
	"""Empty span list should return clear defaults as fallback."""
	params = policies.get_frame_params(0, [])
	assert params["fill_ratio"] == policies.REGIME_DEFAULTS["clear"]["fill_ratio"]
	assert params["size_update_mode"] == "normal"


#============================================
def test_distance_span_params() -> None:
	"""Distance span should return distance-specific fill_ratio."""
	spans = [
		{
			"start_frame": 0, "end_frame": 100, "regime": "distance",
			"distance_flag": "far", "blend_in": 0, "blend_out": 0,
			"mean_conf": 0.9, "mean_bbox_ratio": 0.05,
		},
	]
	params = policies.get_frame_params(50, spans)
	expected_fill = policies.REGIME_DEFAULTS["distance"]["far"]["fill_ratio"]
	assert params["fill_ratio"] == expected_fill
	assert params["size_update_mode"] == "slow"
