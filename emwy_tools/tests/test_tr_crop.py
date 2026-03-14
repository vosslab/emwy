"""Unit tests for track_runner.tr_crop module."""

# Standard Library
import statistics

# PIP3 modules
import numpy
import pytest

# local repo modules
import track_runner.tr_crop as crop_mod
import tr_crop as crop_module

from tr_test_helpers import _make_crop_state
from tr_test_helpers import _make_synthetic_trajectory
from tr_test_helpers import _make_direct_center_config


# ============================================================
# basic crop tests
# ============================================================


#============================================
def test_crop_parse_aspect_ratio_1_1() -> None:
	"""'1:1' -> 1.0."""
	assert crop_mod.parse_aspect_ratio("1:1") == 1.0


#============================================
def test_crop_parse_aspect_ratio_16_9() -> None:
	"""'16:9' -> close to 1.778."""
	result = crop_mod.parse_aspect_ratio("16:9")
	assert abs(result - 16.0 / 9.0) < 0.001


#============================================
def test_crop_parse_aspect_ratio_invalid() -> None:
	"""'abc' raises RuntimeError."""
	with pytest.raises(RuntimeError):
		crop_mod.parse_aspect_ratio("abc")


#============================================
def test_crop_controller_first_update_snaps_to_target() -> None:
	"""First update sets crop position near the target."""
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
	frame = numpy.zeros((300, 200, 3), dtype=numpy.uint8)
	result = crop_mod.apply_crop(frame, (10, 20, 50, 60))
	assert result.shape == (60, 50, 3)


#============================================
def test_crop_apply_crop_padding() -> None:
	"""Crop extending past frame edge gets black padding."""
	frame = numpy.ones((100, 100, 3), dtype=numpy.uint8) * 255
	result = crop_mod.apply_crop(frame, (80, 80, 40, 40))
	assert result.shape == (40, 40, 3)
	# top-left corner (inside frame) should be white
	assert result[0, 0, 0] == 255
	# bottom-right corner (outside frame) should be black padding
	assert result[39, 39, 0] == 0


# ============================================================
# crop post-smoothing tests
# ============================================================


#============================================
def test_post_smooth_passthrough() -> None:
	"""All params 0 returns input unchanged."""
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
	# Seed for reproducibility
	numpy.random.seed(42)
	# Create 100 frames of jittery trajectory
	rects = []
	for i in range(100):
		# Base position (500, 300) with noise +-20px on center
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
	middle_velocities = velocities_after[25:45]
	velocity_var = numpy.var(middle_velocities)
	# Smoothing should make velocities more consistent
	assert velocity_var < 1.0, (
		f"Velocity variance {velocity_var} too high after smoothing"
	)


#============================================
def test_post_smooth_direction_change() -> None:
	"""Trajectory with sharp turn does not produce giant overshoot."""
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
def test_direct_center_basic() -> None:
	"""Direct-center with smoothing off: crop center matches trajectory center."""
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
	config = _make_direct_center_config()
	rects = crop_mod.direct_center_crop_trajectory([], 1920, 1080, config)
	assert rects == []


#============================================
def test_direct_center_min_size_guard() -> None:
	"""Crop dimensions never go below crop_min_size from config."""
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
# velocity-adaptive crop
# ============================================================


#============================================
def test_crop_controller_velocity_adaptive():
	"""CropController adapts velocity cap based on subject speed."""
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
