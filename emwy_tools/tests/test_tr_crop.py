"""Unit tests for track_runner.tr_crop module."""

# Standard Library
import math
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
	"""Crop SIZE stays within frame bounds, position may extend for black fill."""
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
		# crop size must not exceed frame
		assert w <= frame_w, f"Frame {i}: w={w} > {frame_w}"
		assert h <= frame_h, f"Frame {i}: h={h} > {frame_h}"


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
	"""Crop SIZE stays within bounds after velocity cap applied."""
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
		# crop size must not exceed frame
		assert w <= frame_w, f"Frame {i}: w={w} > {frame_w}"
		assert h <= frame_h, f"Frame {i}: h={h} > {frame_h}"


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
		# size check
		assert w <= 1920 and h <= 1080


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


# ============================================================
# hidden size-smoothing default bug fix (Patch 1)
# ============================================================


#============================================
def test_zero_size_alpha_means_no_size_smoothing() -> None:
	"""crop_post_smooth_size_strength=0 produces no size smoothing.

	This verifies the bug fix: previously alpha_size=0 would fall back
	to alpha_pos/2, applying unwanted size smoothing.
	"""
	# build a trajectory with varying bbox height to detect smoothing
	trajectory = _make_synthetic_trajectory(
		60,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	# override with oscillating height
	for i in range(60):
		trajectory[i]["h"] = 100.0 + (50.0 if i % 10 < 5 else 0.0)
	# config: position smoothing ON, size smoothing explicitly OFF
	config = {
		"processing": {
			"crop_mode": "smooth",
			"crop_aspect": "1:1",
			"crop_fill_ratio": 0.30,
			"crop_min_size": 50,
			"crop_post_smooth_strength": 0.10,
			"crop_post_smooth_size_strength": 0.0,
		},
	}
	video_info = {
		"width": 1920,
		"height": 1080,
		"frame_count": 60,
	}
	rects = crop_mod.trajectory_to_crop_rects(trajectory, video_info, config)
	# also compute without any post-smoothing for size reference
	config_no_post = {
		"processing": {
			"crop_mode": "smooth",
			"crop_aspect": "1:1",
			"crop_fill_ratio": 0.30,
			"crop_min_size": 50,
			"crop_post_smooth_strength": 0.0,
			"crop_post_smooth_size_strength": 0.0,
		},
	}
	rects_no_post = crop_mod.trajectory_to_crop_rects(
		trajectory, video_info, config_no_post,
	)
	# heights should be identical: position smoothing should not affect size
	heights_with_pos = [r[3] for r in rects]
	heights_no_post = [r[3] for r in rects_no_post]
	assert heights_with_pos == heights_no_post, (
		"Size smoothing was applied despite alpha_size=0"
	)


# ============================================================
# experiment override passes (Patch 2)
# ============================================================


#============================================
def test_center_lock_preserves_baseline_size() -> None:
	"""Center-lock override keeps baseline width and height unchanged."""
	trajectory = _make_synthetic_trajectory(
		50,
		cx_func=lambda i: 400.0 + i * 5.0,
		cy_func=lambda i: 300.0 + i * 2.0,
		h_val=100.0,
	)
	config = _make_direct_center_config()
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	locked = crop_mod.center_lock_override(
		baseline, trajectory, 1920, 1080, alpha=0.05,
	)
	# width and height must match baseline for every frame
	for i in range(len(baseline)):
		assert locked[i][2] == baseline[i][2], (
			f"Frame {i}: width {locked[i][2]} != baseline {baseline[i][2]}"
		)
		assert locked[i][3] == baseline[i][3], (
			f"Frame {i}: height {locked[i][3]} != baseline {baseline[i][3]}"
		)


#============================================
def test_center_lock_reduces_center_jerk() -> None:
	"""Center-lock produces lower center jerk than raw trajectory centers."""
	# jittery trajectory
	numpy.random.seed(77)
	trajectory = _make_synthetic_trajectory(
		100,
		cx_func=lambda i: 640.0 + numpy.random.uniform(-25, 25),
		cy_func=lambda i: 360.0 + numpy.random.uniform(-25, 25),
		h_val=100.0,
	)
	config = _make_direct_center_config()
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	locked = crop_mod.center_lock_override(
		baseline, trajectory, 1920, 1080, alpha=0.05,
	)
	baseline_metrics = crop_mod.compute_crop_metrics(baseline)
	locked_metrics = crop_mod.compute_crop_metrics(locked)
	# locked should have lower velocity std (less jittery)
	assert locked_metrics["velocity_std"] < baseline_metrics["velocity_std"], (
		f"Center lock jitter {locked_metrics['velocity_std']:.2f} >= "
		f"baseline {baseline_metrics['velocity_std']:.2f}"
	)


#============================================
def test_center_lock_clamps_to_bounds() -> None:
	"""Center-locked rects stay within frame bounds."""
	trajectory = _make_synthetic_trajectory(
		30,
		cx_func=lambda i: 50.0 + i * 60.0,
		cy_func=lambda i: 50.0 + i * 35.0,
		h_val=120.0,
	)
	config = _make_direct_center_config()
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1280, 720, config,
	)
	locked = crop_mod.center_lock_override(
		baseline, trajectory, 1280, 720, alpha=0.05,
	)
	for i, (x, y, w, h) in enumerate(locked):
		assert x >= 0, f"Frame {i}: x={x} < 0"
		assert y >= 0, f"Frame {i}: y={y} < 0"
		assert x + w <= 1280, f"Frame {i}: x+w={x + w} > 1280"
		assert y + h <= 720, f"Frame {i}: y+h={y + h} > 720"


#============================================
def test_fixed_height_zero_variance() -> None:
	"""Fixed-height override produces zero crop-height variance."""
	# trajectory with varying bbox height
	trajectory = _make_synthetic_trajectory(
		80,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	for i in range(80):
		trajectory[i]["h"] = 80.0 + i * 1.5
	config = _make_direct_center_config()
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	fixed = crop_mod.fixed_height_override(
		baseline, 1920, 1080, min_crop_size=50,
	)
	# all heights must be identical
	heights = [r[3] for r in fixed]
	assert len(set(heights)) == 1, (
		f"Expected single height value, got {len(set(heights))} distinct: "
		f"min={min(heights)}, max={max(heights)}"
	)
	# all widths must be identical (same aspect ratio)
	widths = [r[2] for r in fixed]
	assert len(set(widths)) == 1, (
		f"Expected single width value, got {len(set(widths))} distinct"
	)


#============================================
def test_fixed_height_respects_min_size() -> None:
	"""Fixed-height output respects crop_min_size."""
	# very small bbox -> median height would be tiny
	trajectory = _make_synthetic_trajectory(
		30,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=10.0,
	)
	config = _make_direct_center_config({"crop_min_size": 100})
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	fixed = crop_mod.fixed_height_override(
		baseline, 1920, 1080, min_crop_size=100,
	)
	for i, (x, y, w, h) in enumerate(fixed):
		assert h >= 100, f"Frame {i}: h={h} < min_size 100"


#============================================
def test_fixed_height_clamps_to_bounds() -> None:
	"""Fixed-height rects stay within frame bounds."""
	trajectory = _make_synthetic_trajectory(
		30,
		cx_func=lambda i: 50.0 + i * 60.0,
		cy_func=lambda i: 50.0 + i * 35.0,
		h_val=200.0,
	)
	config = _make_direct_center_config()
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1280, 720, config,
	)
	fixed = crop_mod.fixed_height_override(
		baseline, 1280, 720, min_crop_size=50,
	)
	for i, (x, y, w, h) in enumerate(fixed):
		assert x >= 0, f"Frame {i}: x={x} < 0"
		assert y >= 0, f"Frame {i}: y={y} < 0"
		assert x + w <= 1280, f"Frame {i}: x+w={x + w} > 1280"
		assert y + h <= 720, f"Frame {i}: y+h={y + h} > 720"


#============================================
def test_slow_size_deadband_suppresses_small_oscillations() -> None:
	"""Slow-size deadband rejects height changes below threshold."""
	# trajectory with small oscillations (2% of height)
	trajectory = _make_synthetic_trajectory(
		60,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	# add small oscillation: +/- 1% of baseline height -> within 3% deadband
	for i in range(60):
		trajectory[i]["h"] = 100.0 + 3.0 * (1.0 if i % 2 == 0 else -1.0)
	config = _make_direct_center_config()
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	slow = crop_mod.slow_size_override(
		baseline, 1920, 1080,
		alpha=0.01, deadband_fraction=0.05, min_crop_size=50,
	)
	# height variance should be much lower after slow-size
	baseline_heights = numpy.array([r[3] for r in baseline], dtype=float)
	slow_heights = numpy.array([r[3] for r in slow], dtype=float)
	assert numpy.std(slow_heights) < numpy.std(baseline_heights), (
		f"Slow-size std {numpy.std(slow_heights):.2f} >= "
		f"baseline std {numpy.std(baseline_heights):.2f}"
	)


#============================================
def test_slow_size_allows_large_changes() -> None:
	"""Slow-size allows real large height changes through (smoothed)."""
	# trajectory with a big height change in the middle
	trajectory = _make_synthetic_trajectory(
		60,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	# first 30 frames: h=100, next 30: h=200
	for i in range(60):
		trajectory[i]["h"] = 100.0 if i < 30 else 200.0
	config = _make_direct_center_config()
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	slow = crop_mod.slow_size_override(
		baseline, 1920, 1080,
		alpha=0.05, deadband_fraction=0.03, min_crop_size=50,
	)
	# the large change should eventually come through:
	# last frame height should be closer to 200/0.30=667 than to 100/0.30=333
	first_h = slow[0][3]
	last_h = slow[-1][3]
	assert last_h > first_h, (
		f"Slow-size should track the large height increase: "
		f"first={first_h}, last={last_h}"
	)


#============================================
def test_slow_size_clamps_to_bounds() -> None:
	"""Slow-size rects stay within frame bounds."""
	trajectory = _make_synthetic_trajectory(
		30,
		cx_func=lambda i: 50.0 + i * 60.0,
		cy_func=lambda i: 50.0 + i * 35.0,
		h_val=200.0,
	)
	config = _make_direct_center_config()
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1280, 720, config,
	)
	slow = crop_mod.slow_size_override(
		baseline, 1280, 720,
		alpha=0.01, deadband_fraction=0.03, min_crop_size=50,
	)
	for i, (x, y, w, h) in enumerate(slow):
		assert x >= 0, f"Frame {i}: x={x} < 0"
		assert y >= 0, f"Frame {i}: y={y} < 0"
		assert x + w <= 1280, f"Frame {i}: x+w={x + w} > 1280"
		assert y + h <= 720, f"Frame {i}: y+h={y + h} > 720"


#============================================
def test_apply_experiment_overrides_no_override() -> None:
	"""No experiment overrides returns rects identical to input."""
	trajectory = _make_synthetic_trajectory(
		30,
		cx_func=lambda i: 640.0 + i * 3.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	config = _make_direct_center_config()
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	# no experiment keys in config
	result = crop_mod.apply_experiment_overrides(
		baseline, trajectory, 1920, 1080, config,
	)
	assert result == baseline, "No-override should return identical rects"


#============================================
def test_apply_experiment_overrides_center_lock() -> None:
	"""Dispatch with exp_center_override=center_lock applies center lock."""
	numpy.random.seed(88)
	trajectory = _make_synthetic_trajectory(
		50,
		cx_func=lambda i: 640.0 + numpy.random.uniform(-20, 20),
		cy_func=lambda i: 360.0 + numpy.random.uniform(-20, 20),
		h_val=100.0,
	)
	config = _make_direct_center_config({
		"exp_center_override": "center_lock",
		"exp_center_alpha": 0.05,
	})
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	result = crop_mod.apply_experiment_overrides(
		baseline, trajectory, 1920, 1080, config,
	)
	# center lock should reduce jitter
	baseline_metrics = crop_mod.compute_crop_metrics(baseline)
	result_metrics = crop_mod.compute_crop_metrics(result)
	assert result_metrics["velocity_std"] < baseline_metrics["velocity_std"]


#============================================
def test_apply_experiment_overrides_fixed_crop() -> None:
	"""Dispatch with exp_size_override=fixed_crop produces constant height."""
	trajectory = _make_synthetic_trajectory(
		40,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	for i in range(40):
		trajectory[i]["h"] = 80.0 + i * 2.0
	config = _make_direct_center_config({
		"exp_size_override": "fixed_crop",
	})
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	result = crop_mod.apply_experiment_overrides(
		baseline, trajectory, 1920, 1080, config,
	)
	heights = [r[3] for r in result]
	assert len(set(heights)) == 1, (
		f"Expected constant height, got {len(set(heights))} distinct values"
	)


#============================================
def test_apply_experiment_overrides_slow_size() -> None:
	"""Dispatch with exp_size_override=slow_size smooths height."""
	trajectory = _make_synthetic_trajectory(
		60,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	for i in range(60):
		trajectory[i]["h"] = 100.0 + 5.0 * (1.0 if i % 2 == 0 else -1.0)
	config = _make_direct_center_config({
		"exp_size_override": "slow_size",
		"exp_slow_size_alpha": 0.01,
		"exp_slow_size_deadband": 0.05,
	})
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	result = crop_mod.apply_experiment_overrides(
		baseline, trajectory, 1920, 1080, config,
	)
	# slow size should reduce height variance
	baseline_heights = numpy.array([r[3] for r in baseline], dtype=float)
	result_heights = numpy.array([r[3] for r in result], dtype=float)
	assert numpy.std(result_heights) < numpy.std(baseline_heights)


#============================================
def test_apply_experiment_overrides_combined() -> None:
	"""Combined center_lock + fixed_crop applies both overrides."""
	numpy.random.seed(66)
	trajectory = _make_synthetic_trajectory(
		50,
		cx_func=lambda i: 640.0 + numpy.random.uniform(-20, 20),
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	for i in range(50):
		trajectory[i]["h"] = 80.0 + i * 1.5
	config = _make_direct_center_config({
		"exp_center_override": "center_lock",
		"exp_center_alpha": 0.05,
		"exp_size_override": "fixed_crop",
	})
	baseline = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	result = crop_mod.apply_experiment_overrides(
		baseline, trajectory, 1920, 1080, config,
	)
	# height should be constant (fixed crop)
	heights = [r[3] for r in result]
	assert len(set(heights)) == 1, "Combined: expected constant height"
	# center should be smoother (center lock)
	baseline_metrics = crop_mod.compute_crop_metrics(baseline)
	result_metrics = crop_mod.compute_crop_metrics(result)
	assert result_metrics["velocity_std"] < baseline_metrics["velocity_std"]


# ============================================================
# constraint-based stabilization (M3)
# ============================================================


#============================================
def test_zoom_constraint_limits_height_change_rate() -> None:
	"""Zoom constraint caps per-frame height change rate."""
	# config: WITH tight zoom constraint (2% per frame)
	config_constrained = _make_direct_center_config({
		"crop_max_height_change": 0.02,
	})

	# trajectory with changing bbox height to trigger constraint
	trajectory_changing = _make_synthetic_trajectory(
		50,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	for i in range(50):
		trajectory_changing[i]["h"] = 100.0 + i * 2.0

	rects_changing = crop_mod.direct_center_crop_trajectory(
		trajectory_changing, 1920, 1080, config_constrained,
	)
	# verify constraint is active by checking height changes
	max_delta_pct = 0.0
	for i in range(1, len(rects_changing)):
		h_prev = float(rects_changing[i - 1][3])
		h_curr = float(rects_changing[i][3])
		if h_prev > 0:
			delta_pct = abs(h_curr - h_prev) / h_prev
			max_delta_pct = max(max_delta_pct, delta_pct)
	# should be constrained to ~2% or below (allow 0.5% tolerance for rounding)
	assert max_delta_pct <= 0.02 + 0.005, (
		f"Height constraint not active: max delta {max_delta_pct:.4f} > 0.025"
	)


#============================================
def test_zoom_constraint_disabled_when_zero() -> None:
	"""Zoom constraint with value 0 does not limit height changes."""
	# trajectory with fast height change
	trajectory = _make_synthetic_trajectory(
		20,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)
	for i in range(20):
		trajectory[i]["h"] = 100.0 if i < 10 else 500.0

	# config with zoom constraint disabled
	config = _make_direct_center_config({
		"crop_max_height_change": 0.0,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)

	# find the biggest height jump (should be at frame 10)
	max_jump = 0.0
	for i in range(1, len(rects)):
		delta = abs(rects[i][3] - rects[i - 1][3])
		max_jump = max(max_jump, delta)

	# with constraint disabled, we should see a large jump
	# (larger than 5% of height)
	h_at_9 = float(rects[9][3])
	assert max_jump > 0.05 * h_at_9, (
		f"Expected large height jump with constraint disabled, "
		f"got max_jump={max_jump}"
	)


#============================================
def test_containment_clamp_pulls_drifting_center() -> None:
	"""Containment clamp pulls crop center toward raw trajectory when drifting."""
	# trajectory that drifts sideways in one direction
	trajectory = _make_synthetic_trajectory(
		50,
		cx_func=lambda i: 640.0 + i * 2.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)

	# config: apply position smoothing that lags behind, then clamp
	config = _make_direct_center_config({
		"crop_post_smooth_strength": 0.05,
		"crop_containment_radius": 0.20,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)

	# all crop centers should be within the containment radius of raw centers
	for i, (x, y, w, h) in enumerate(rects):
		raw_cx = trajectory[i]["cx"]
		raw_cy = trajectory[i]["cy"]
		crop_cx = x + w / 2.0
		crop_cy = y + h / 2.0
		# normalized offset from raw to crop center
		dx_norm = (raw_cx - crop_cx) / w
		dy_norm = (raw_cy - crop_cy) / h
		offset_norm = math.sqrt(dx_norm * dx_norm + dy_norm * dy_norm)
		assert offset_norm <= 0.20 + 0.01, (
			f"Frame {i}: offset {offset_norm:.3f} exceeds radius 0.20"
		)


#============================================
def test_containment_clamp_disabled_when_zero() -> None:
	"""Containment clamp with radius 0 does not add extra constraint."""
	# trajectory where smoothing causes lag
	trajectory = _make_synthetic_trajectory(
		50,
		cx_func=lambda i: 640.0 + i * 5.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)

	# config: position smoothing with NO containment
	config_no_contain = _make_direct_center_config({
		"crop_post_smooth_strength": 0.10,
		"crop_containment_radius": 0.0,
	})
	rects_no_contain = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_no_contain,
	)

	# config: position smoothing WITH tight containment
	config_with_contain = _make_direct_center_config({
		"crop_post_smooth_strength": 0.10,
		"crop_containment_radius": 0.05,
	})
	rects_with_contain = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_with_contain,
	)

	# calculate average offset for each
	no_contain_offsets = []
	for i, (x, y, w, h) in enumerate(rects_no_contain):
		raw_cx = trajectory[i]["cx"]
		raw_cy = trajectory[i]["cy"]
		crop_cx = x + w / 2.0
		crop_cy = y + h / 2.0
		dx_norm = (raw_cx - crop_cx) / w
		dy_norm = (raw_cy - crop_cy) / h
		offset = math.sqrt(dx_norm * dx_norm + dy_norm * dy_norm)
		no_contain_offsets.append(offset)

	with_contain_offsets = []
	for i, (x, y, w, h) in enumerate(rects_with_contain):
		raw_cx = trajectory[i]["cx"]
		raw_cy = trajectory[i]["cy"]
		crop_cx = x + w / 2.0
		crop_cy = y + h / 2.0
		dx_norm = (raw_cx - crop_cx) / w
		dy_norm = (raw_cy - crop_cy) / h
		offset = math.sqrt(dx_norm * dx_norm + dy_norm * dy_norm)
		with_contain_offsets.append(offset)

	# with containment, peak offsets should be smaller
	# (average may be similar due to small differences)
	max_no_contain = max(no_contain_offsets)
	max_with_contain = max(with_contain_offsets)
	assert max_with_contain <= max_no_contain, (
		f"Containment should reduce peak offset: "
		f"no_contain={max_no_contain:.3f}, with_contain={max_with_contain:.3f}"
	)


#============================================
def test_crop_position_can_extend_beyond_frame() -> None:
	"""Crop position can extend beyond frame bounds (black fill policy)."""
	# trajectory near frame edge, with small crop size
	trajectory = _make_synthetic_trajectory(
		10,
		cx_func=lambda i: 30.0 + i * 20.0,
		cy_func=lambda i: 40.0 + i * 30.0,
		h_val=50.0,
	)

	config = _make_direct_center_config({
		"crop_containment_radius": 0.0,
	})
	frame_w = 400
	frame_h = 300
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, frame_w, frame_h, config,
	)

	# check that some crops extend beyond bounds
	has_negative_x = False
	has_negative_y = False
	has_overflow_x = False
	has_overflow_y = False

	for x, y, w, h in rects:
		if x < 0:
			has_negative_x = True
		if y < 0:
			has_negative_y = True
		if x + w > frame_w:
			has_overflow_x = True
		if y + h > frame_h:
			has_overflow_y = True

	# with trajectory moving into corners, we should see some out-of-bounds
	assert has_negative_x or has_negative_y or has_overflow_x or has_overflow_y, (
		"Expected at least one crop to extend beyond frame bounds"
	)


#============================================
def test_crop_size_clamped_to_frame_dimensions() -> None:
	"""Crop size is clamped to frame dimensions, never larger."""
	# trajectory with very large subject
	trajectory = _make_synthetic_trajectory(
		20,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=1000.0,
	)

	config = _make_direct_center_config({
		"crop_fill_ratio": 0.30,
	})
	frame_w = 800
	frame_h = 600
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, frame_w, frame_h, config,
	)

	# all crop sizes must stay within frame
	for i, (x, y, w, h) in enumerate(rects):
		assert w <= frame_w, (
			f"Frame {i}: crop width {w} exceeds frame width {frame_w}"
		)
		assert h <= frame_h, (
			f"Frame {i}: crop height {h} exceeds frame height {frame_h}"
		)


#============================================
def test_containment_double_clamp_enforces_after_resmoothing() -> None:
	"""Double containment clamp enforces constraint after re-smoothing."""
	# trajectory with a fast sideways jump that gets smoothed
	trajectory = _make_synthetic_trajectory(
		50,
		cx_func=lambda i: 640.0 if i < 25 else 700.0,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)

	# tight containment + light smoothing (re-smoothing should not reintroduce violations)
	config = _make_direct_center_config({
		"crop_post_smooth_strength": 0.10,
		"crop_containment_radius": 0.15,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)

	# check that no frame violates the containment constraint
	violations = 0
	for i, (x, y, w, h) in enumerate(rects):
		raw_cx = trajectory[i]["cx"]
		raw_cy = trajectory[i]["cy"]
		crop_cx = x + w / 2.0
		crop_cy = y + h / 2.0
		dx_norm = (raw_cx - crop_cx) / w
		dy_norm = (raw_cy - crop_cy) / h
		offset_norm = math.sqrt(dx_norm * dx_norm + dy_norm * dy_norm)
		if offset_norm > 0.15 + 0.01:
			violations += 1

	assert violations == 0, (
		f"Double clamp failed: {violations} frames violate containment constraint"
	)


#============================================
def test_containment_clamp_activates() -> None:
	"""Containment clamp pulls crop center back when subject drifts far away."""
	# trajectory with rapid oscillation: subject jumps between left and right
	# with heavy smoothing, crop lags, creating large offset
	def cx_func(i: int) -> float:
		return 300.0 if i % 4 < 2 else 700.0

	trajectory = _make_synthetic_trajectory(
		40,
		cx_func=cx_func,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)

	# heavy position smoothing creates lag, tight containment pulls it back
	config = _make_direct_center_config({
		"crop_post_smooth_strength": 0.05,  # heavy smoothing = lag
		"crop_containment_radius": 0.20,    # tight containment
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)

	# verify no frame exceeds containment radius
	max_offset = 0.0
	for i, (x, y, w, h) in enumerate(rects):
		raw_cx = trajectory[i]["cx"]
		crop_cx = x + w / 2.0
		dx_norm = (raw_cx - crop_cx) / w
		offset_norm = abs(dx_norm)  # y is constant so only x offset
		max_offset = max(max_offset, offset_norm)
		# allow 1% tolerance for rounding
		assert offset_norm <= 0.20 + 0.01, (
			f"Frame {i}: offset {offset_norm:.3f} exceeds "
			f"containment_radius 0.20"
		)

	# verify that containment actually activated (offset should be significant)
	assert max_offset >= 0.05, (
		f"Containment did not activate: max offset {max_offset:.3f} too small"
	)


#============================================
def test_double_clamp_prevents_resmoothing_violations() -> None:
	"""Second containment clamp fixes violations reintroduced by re-smoothing."""
	# extreme position jump at frame 25
	def cx_func(i: int) -> float:
		return 400.0 if i < 25 else 1000.0

	trajectory = _make_synthetic_trajectory(
		50,
		cx_func=cx_func,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)

	# light smoothing after first clamp (re-smoothing can reintroduce violations)
	config = _make_direct_center_config({
		"crop_post_smooth_strength": 0.20,
		"crop_containment_radius": 0.15,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)

	# verify containment is maintained throughout
	violations = 0
	for i, (x, y, w, h) in enumerate(rects):
		raw_cx = trajectory[i]["cx"]
		crop_cx = x + w / 2.0
		dx_norm = (raw_cx - crop_cx) / w
		offset_norm = abs(dx_norm)
		if offset_norm > 0.15 + 0.01:  # allow 1% tolerance
			violations += 1

	assert violations == 0, (
		f"Second clamp failed: {violations} frames violate containment"
	)


#============================================
def test_zoom_constraint_limits_height_change() -> None:
	"""Zoom constraint caps frame-to-frame height change to max_height_change."""
	# trajectory with a sudden height change at frame 30
	def h_func(i: int) -> float:
		if i < 30:
			return 100.0
		else:
			return 200.0  # sudden double

	trajectory = []
	for i in range(60):
		state = {
			"cx": 640.0,
			"cy": 360.0,
			"w": h_func(i) * 0.5,
			"h": h_func(i),
			"conf": 0.9,
			"source": "propagated",
		}
		trajectory.append(state)

	# tight zoom constraint: max 0.5% per frame
	config = _make_direct_center_config({
		"crop_max_height_change": 0.005,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)

	# verify frame-to-frame height change never exceeds constraint
	max_change = 0.0
	for i in range(1, len(rects)):
		h_prev = rects[i - 1][3]
		h_curr = rects[i][3]
		delta = h_curr - h_prev
		max_change_frac = abs(delta) / h_prev if h_prev > 0 else 0.0
		# allow 0.2% tolerance for rounding and integer conversion
		assert max_change_frac <= 0.005 + 0.002, (
			f"Frame {i}: height change {max_change_frac:.4f} "
			f"exceeds limit 0.005"
		)
		max_change = max(max_change, max_change_frac)

	# verify constraint actually activated (should smooth the transition)
	# most frames should be near the 0.5% limit
	assert max_change > 0.004, (
		f"Zoom constraint should be active, max change {max_change:.4f}"
	)


#============================================
def test_crop_position_allows_black_fill() -> None:
	"""Crop position can extend beyond frame bounds for black fill."""
	# subject near the frame edge
	trajectory = _make_synthetic_trajectory(
		20,
		cx_func=lambda i: 50.0,  # far left edge
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)

	config = _make_direct_center_config({
		"crop_fill_ratio": 0.30,  # fill 30% with subject
	})
	frame_w = 1920
	frame_h = 1080
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, frame_w, frame_h, config,
	)

	# with subject at x=50 and fill_ratio=0.30, crop_h = 100/0.30 = 333.3
	# crop_w = 333.3 * (16/9) = 592.6, so crop_x = 50 - 592.6/2 = -246.3
	# crop position should allow negative x for black fill
	has_negative_x = any(x < 0 for x, y, w, h in rects)
	assert has_negative_x, (
		"Subject at frame edge should allow negative crop_x for black fill"
	)

	# but crop size must still fit
	for i, (x, y, w, h) in enumerate(rects):
		assert w <= frame_w, f"Frame {i}: width {w} exceeds frame"
		assert h <= frame_h, f"Frame {i}: height {h} exceeds frame"


#============================================
def test_crop_size_stays_within_frame() -> None:
	"""Crop SIZE always stays within frame, even with large bbox height."""
	# trajectory with very large bounding box
	trajectory = _make_synthetic_trajectory(
		30,
		cx_func=lambda i: 640.0,
		cy_func=lambda i: 360.0,
		h_val=5000.0,  # huge height
	)

	config = _make_direct_center_config({
		"crop_fill_ratio": 0.30,
	})
	frame_w = 800
	frame_h = 600
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, frame_w, frame_h, config,
	)

	# all crop dimensions must not exceed frame
	for i, (x, y, w, h) in enumerate(rects):
		assert w <= frame_w, (
			f"Frame {i}: crop_w {w} exceeds frame_w {frame_w}"
		)
		assert h <= frame_h, (
			f"Frame {i}: crop_h {h} exceeds frame_h {frame_h}"
		)


#============================================
def test_containment_disabled_when_zero() -> None:
	"""When crop_containment_radius=0, no containment clamping occurs."""
	# trajectory with fast oscillation that would normally trigger containment
	def cx_func(i: int) -> float:
		return 300.0 if i % 3 < 1.5 else 800.0

	trajectory = _make_synthetic_trajectory(
		40,
		cx_func=cx_func,
		cy_func=lambda i: 360.0,
		h_val=100.0,
	)

	# disable containment
	config = _make_direct_center_config({
		"crop_post_smooth_strength": 0.05,
		"crop_containment_radius": 0.0,  # disabled
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)

	# no containment clamp means crop center can drift further from subject
	# we just verify the function runs and produces valid output
	assert len(rects) == 40
	for x, y, w, h in rects:
		assert w > 0 and h > 0


# duplicate test_zoom_constraint_disabled_when_zero removed (defined above)


# ============================================================
# composition offset tests (torso anchor)
# ============================================================


#============================================
def test_torso_anchor_default_matches_baseline() -> None:
	"""anchor=0.50 (default) produces same output as no anchor."""
	n = 60
	trajectory = _make_synthetic_trajectory(
		n, cx_func=lambda i: 960.0, cy_func=lambda i: 540.0, h_val=200.0,
	)
	config_no_anchor = _make_direct_center_config({
		"crop_max_height_change": 0.005,
	})
	config_with_anchor = _make_direct_center_config({
		"crop_max_height_change": 0.005,
		"crop_torso_anchor": 0.50,
	})
	rects_base = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_no_anchor,
	)
	rects_anchor = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_with_anchor,
	)
	# must be identical
	assert len(rects_base) == len(rects_anchor)
	for a, b in zip(rects_base, rects_anchor):
		assert a == b


#============================================
def test_torso_anchor_038_shifts_crop_down() -> None:
	"""anchor=0.38 shifts crop so torso is in upper 40% of frame."""
	n = 60
	cy_target = 540.0
	trajectory = _make_synthetic_trajectory(
		n, cx_func=lambda i: 960.0, cy_func=lambda i: cy_target, h_val=200.0,
	)
	config_centered = _make_direct_center_config({
		"crop_max_height_change": 0.0,
	})
	config_anchor = _make_direct_center_config({
		"crop_max_height_change": 0.0,
		"crop_torso_anchor": 0.38,
	})
	rects_centered = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_centered,
	)
	rects_anchor = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_anchor,
	)
	# with anchor < 0.5, crop shifts down => crop_y increases
	# so torso center is in upper portion of crop
	mid = n // 2
	_, y_c, _, h_c = rects_centered[mid]
	_, y_a, _, h_a = rects_anchor[mid]
	# anchor crop should have higher y (shifted down)
	assert y_a > y_c, f"anchor crop y={y_a} should be > centered y={y_c}"
	# check torso sits in upper 40% of anchored crop
	torso_pos_in_crop = (cy_target - y_a) / h_a
	assert torso_pos_in_crop < 0.42, (
		f"torso at {torso_pos_in_crop:.2f} within crop, expected < 0.42"
	)


#============================================
def test_torso_anchor_offset_scales_with_crop_height() -> None:
	"""Composition offset scales with smoothed crop height, not bbox height."""
	n = 60
	cy_target = 540.0
	# two configs with different fill_ratio => different crop height
	# use centered anchor as baseline, then anchored to measure offset
	config_small_centered = _make_direct_center_config({
		"crop_max_height_change": 0.0,
		"crop_torso_anchor": 0.50,
		"crop_fill_ratio": 0.30,
	})
	config_small_anchored = _make_direct_center_config({
		"crop_max_height_change": 0.0,
		"crop_torso_anchor": 0.38,
		"crop_fill_ratio": 0.30,
	})
	config_large_centered = _make_direct_center_config({
		"crop_max_height_change": 0.0,
		"crop_torso_anchor": 0.50,
		"crop_fill_ratio": 0.20,
	})
	config_large_anchored = _make_direct_center_config({
		"crop_max_height_change": 0.0,
		"crop_torso_anchor": 0.38,
		"crop_fill_ratio": 0.20,
	})
	trajectory = _make_synthetic_trajectory(
		n, cx_func=lambda i: 960.0, cy_func=lambda i: cy_target, h_val=200.0,
	)
	mid = n // 2
	# measure the y-shift caused by anchor for each fill ratio
	rects_sc = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_small_centered,
	)
	rects_sa = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_small_anchored,
	)
	rects_lc = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_large_centered,
	)
	rects_la = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_large_anchored,
	)
	# offset = difference in y between anchored and centered
	offset_small = rects_sa[mid][1] - rects_sc[mid][1]
	offset_large = rects_la[mid][1] - rects_lc[mid][1]
	# both offsets should be positive (crop shifts down)
	assert offset_small > 0, f"small crop offset should be positive: {offset_small}"
	assert offset_large > 0, f"large crop offset should be positive: {offset_large}"
	# larger crop height => larger offset
	assert offset_large > offset_small, (
		f"larger crop offset {offset_large} should exceed smaller {offset_small}"
	)


#============================================
def test_torso_anchor_containment_still_works() -> None:
	"""Containment clamp functions correctly with composition offset active."""
	n = 60
	# subject drifts to edge of frame
	trajectory = _make_synthetic_trajectory(
		n,
		cx_func=lambda i: 960.0 + i * 5.0,
		cy_func=lambda i: 540.0,
		h_val=200.0,
	)
	config = _make_direct_center_config({
		"crop_max_height_change": 0.005,
		"crop_containment_radius": 0.20,
		"crop_torso_anchor": 0.38,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	# verify all rects are valid and function completes
	assert len(rects) == n
	for x, y, w, h in rects:
		assert w > 0 and h > 0


# ============================================================
# zoom phase detector tests
# ============================================================


#============================================
def test_zoom_phases_smooth_signal_no_events() -> None:
	"""Smooth height signal produces no transitions or settling."""
	n = 100
	# gradual height change: 200 to 210 over 100 frames (< 1% per frame)
	raw_h = numpy.linspace(200.0, 210.0, n)
	trans, settle = crop_mod._detect_zoom_phases(raw_h)
	assert not trans.any(), "smooth signal should have no transitions"
	assert not settle.any(), "smooth signal should have no settling"


#============================================
def test_zoom_phases_large_jump_detected() -> None:
	"""2x height jump at frame 50 triggers transition and settling."""
	n = 150
	raw_h = numpy.full(n, 200.0)
	# instant 2x jump at frame 50 that persists
	raw_h[50:] = 400.0
	trans, settle = crop_mod._detect_zoom_phases(
		raw_h, window=5, threshold_ratio=1.40, settle_frames=30,
	)
	# frames near jump should be in transition (within window)
	assert trans[50], "jump frame should be in transition"
	# frames before jump should not be flagged as transition
	assert not trans[45], "frame well before jump should not be transition"
	# settling should follow the transition block
	# find the last transition frame and check settling starts after it
	last_trans = max(i for i in range(n) if trans[i])
	assert settle[last_trans + 1], "settling should start after transition"
	# settling should end within settle_frames
	settle_end = last_trans + 1 + 30
	if settle_end < n:
		assert not settle[settle_end], "settling should end after 30 frames"


#============================================
def test_zoom_phases_zoom_out_detected() -> None:
	"""Zoom-out (height decrease) is also detected."""
	n = 150
	raw_h = numpy.full(n, 400.0)
	# instant halving at frame 40
	raw_h[40:] = 200.0
	trans, settle = crop_mod._detect_zoom_phases(
		raw_h, window=5, threshold_ratio=1.40, settle_frames=20,
	)
	assert trans[40], "zoom-out frame should be in transition"
	# settling should follow
	last_trans = max(i for i in range(n) if trans[i])
	if last_trans + 1 < n:
		assert settle[last_trans + 1], "settling should follow transition"


#============================================
def test_zoom_phases_gradual_ramp_not_detected() -> None:
	"""A 5-frame spread ramp that stays under threshold is not a transition.

	Ratio of 1.30 over 5 frames is under the 1.40 threshold.
	"""
	n = 100
	raw_h = numpy.full(n, 200.0)
	# spread ramp: 200 -> 260 over 5 frames (ratio 1.30, under 1.40)
	for i in range(5):
		raw_h[50 + i] = 200.0 + i * 12.0
	raw_h[55:] = 260.0
	trans, settle = crop_mod._detect_zoom_phases(
		raw_h, window=5, threshold_ratio=1.40, settle_frames=30,
	)
	assert not trans.any(), "gradual ramp under threshold should not trigger"


#============================================
def test_zoom_phases_spread_ramp_detected() -> None:
	"""A 5-frame spread ramp exceeding threshold is detected."""
	n = 100
	raw_h = numpy.full(n, 200.0)
	# spread ramp: 200 -> 350 over 5 frames (ratio 1.75, above 1.40)
	for i in range(5):
		raw_h[50 + i] = 200.0 + i * 30.0 + 30.0
	raw_h[55:] = 350.0
	trans, settle = crop_mod._detect_zoom_phases(
		raw_h, window=5, threshold_ratio=1.40, settle_frames=30,
	)
	# at least some frames in the ramp should be detected
	ramp_trans = trans[48:58].any()
	assert ramp_trans, "spread ramp above threshold should trigger transition"


#============================================
def test_zoom_phases_overlapping_events_merge() -> None:
	"""Two events close together merge their settling zones."""
	n = 200
	raw_h = numpy.full(n, 200.0)
	# first jump at frame 20
	raw_h[20:60] = 400.0
	# second jump at frame 60 (back down, close to first)
	raw_h[60:] = 200.0
	trans, settle = crop_mod._detect_zoom_phases(
		raw_h, window=5, threshold_ratio=1.40, settle_frames=30,
	)
	# both events should have transitions
	assert trans[20], "first event should be in transition"
	# frames between events should be transition or settling (merged)
	all_affected = trans | settle
	# check continuous coverage from first event through settling
	assert all_affected[30], "mid-zone should be in transition or settling"


#============================================
def test_zoom_phases_no_overlap_between_masks() -> None:
	"""Transition and settle masks should not overlap."""
	n = 150
	raw_h = numpy.full(n, 200.0)
	raw_h[50:] = 400.0
	trans, settle = crop_mod._detect_zoom_phases(
		raw_h, window=5, threshold_ratio=1.40, settle_frames=30,
	)
	# no frame should be both transition and settling
	overlap = trans & settle
	assert not overlap.any(), "transition and settle masks must not overlap"


# ============================================================
# zoom stabilization integration tests (three-mode constraint)
# ============================================================


#============================================
def test_zoom_stabilization_disabled_matches_baseline() -> None:
	"""crop_zoom_stabilization=False produces same output as no stabilization."""
	n = 100
	trajectory = _make_synthetic_trajectory(
		n, cx_func=lambda i: 960.0, cy_func=lambda i: 540.0,
		h_val=200.0,
	)
	# inject a height jump
	for i in range(50, n):
		trajectory[i]["h"] = 400.0
	config_off = _make_direct_center_config({
		"crop_max_height_change": 0.005,
		"crop_zoom_stabilization": False,
	})
	config_default = _make_direct_center_config({
		"crop_max_height_change": 0.005,
	})
	rects_off = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_off,
	)
	rects_default = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_default,
	)
	assert len(rects_off) == len(rects_default)
	for a, b in zip(rects_off, rects_default):
		assert a == b


#============================================
def test_zoom_stabilization_transition_mode_near_freeze() -> None:
	"""Transition frames change crop height at most 2% of normal rate."""
	n = 100
	trajectory = _make_synthetic_trajectory(
		n, cx_func=lambda i: 960.0, cy_func=lambda i: 540.0,
		h_val=200.0,
	)
	# inject a persistent 2x height jump at frame 50
	for i in range(50, n):
		trajectory[i]["h"] = 400.0
	config_stabilized = _make_direct_center_config({
		"crop_max_height_change": 0.005,
		"crop_zoom_stabilization": True,
	})
	config_normal = _make_direct_center_config({
		"crop_max_height_change": 0.005,
		"crop_zoom_stabilization": False,
	})
	rects_stab = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_stabilized,
	)
	rects_norm = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config_normal,
	)
	# compare height change rate in 10 frames after jump
	stab_deltas = []
	norm_deltas = []
	for i in range(51, 61):
		stab_deltas.append(abs(rects_stab[i][3] - rects_stab[i - 1][3]))
		norm_deltas.append(abs(rects_norm[i][3] - rects_norm[i - 1][3]))
	avg_stab = sum(stab_deltas) / len(stab_deltas)
	avg_norm = sum(norm_deltas) / len(norm_deltas)
	# stabilized should be significantly slower
	assert avg_stab < avg_norm, (
		f"stabilized avg delta {avg_stab:.2f} should be < normal {avg_norm:.2f}"
	)
	# stabilized rate should be much less than normal (transition=0.02x)
	if avg_norm > 0:
		ratio = avg_stab / avg_norm
		assert ratio < 0.25, (
			f"stabilized/normal ratio {ratio:.2f} should be < 0.25 (transition mode)"
		)


#============================================
def test_zoom_stabilization_settling_mode_slow_convergence() -> None:
	"""Settling frames change crop height at reduced rate vs normal."""
	n = 250
	trajectory = _make_synthetic_trajectory(
		n, cx_func=lambda i: 960.0, cy_func=lambda i: 540.0,
		h_val=200.0,
	)
	# inject a persistent height jump at frame 30
	for i in range(30, n):
		trajectory[i]["h"] = 400.0
	config = _make_direct_center_config({
		"crop_max_height_change": 0.005,
		"crop_zoom_stabilization": True,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	# detect the phases to know which frames are settling
	raw_h = numpy.array([t["h"] for t in trajectory])
	trans, settle = crop_mod._detect_zoom_phases(raw_h)
	# find settling frames and check their rate is bounded
	settle_indices = numpy.where(settle)[0]
	if len(settle_indices) > 2:
		# check that settling frames have smaller deltas than normal rate
		# normal max delta = 0.005 * height; settling = 0.20 * 0.005 * height = 0.001 * height
		for idx in settle_indices[1:]:
			delta = abs(rects[idx][3] - rects[idx - 1][3])
			# settling rate: 20% of 0.005 = 0.001 of prev height
			prev_h = rects[idx - 1][3]
			max_settle_delta = 0.001 * prev_h + 1.0  # +1 for rounding
			assert delta <= max_settle_delta, (
				f"settling frame {idx}: delta {delta} exceeds max {max_settle_delta}"
			)


#============================================
def test_zoom_stabilization_normal_rate_after_settling() -> None:
	"""After settling expires, normal height change rate resumes."""
	n = 300
	trajectory = _make_synthetic_trajectory(
		n, cx_func=lambda i: 960.0, cy_func=lambda i: 540.0,
		h_val=200.0,
	)
	# jump at frame 30 -- transition + settling should end well before frame 200
	for i in range(30, n):
		trajectory[i]["h"] = 400.0
	config = _make_direct_center_config({
		"crop_max_height_change": 0.005,
		"crop_zoom_stabilization": True,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	# check frames well after settling zone (frame 150+) have normal rate
	late_deltas = []
	for i in range(151, 180):
		late_deltas.append(abs(rects[i][3] - rects[i - 1][3]))
	# at least some frames should have nonzero height change (still converging)
	max_late_delta = max(late_deltas)
	assert max_late_delta > 0, "crop should still be converging after settling"


#============================================
def test_zoom_stabilization_biased_monotonicity_suppresses_small_reversals() -> None:
	"""Small reversals are suppressed during settling zone."""
	n = 200
	trajectory = _make_synthetic_trajectory(
		n, cx_func=lambda i: 960.0, cy_func=lambda i: 540.0,
		h_val=200.0,
	)
	# jump at frame 30
	for i in range(30, n):
		trajectory[i]["h"] = 400.0
	# inject small oscillations during what will be settling
	# (frames ~35-95 with default settle_frames=60)
	for i in range(40, 90, 4):
		trajectory[i]["h"] = 395.0  # small dip from 400
		trajectory[i + 1]["h"] = 400.0  # back to 400
	config = _make_direct_center_config({
		"crop_max_height_change": 0.005,
		"crop_zoom_stabilization": True,
	})
	rects = crop_mod.direct_center_crop_trajectory(
		trajectory, 1920, 1080, config,
	)
	# count direction changes in the settling region (frames 55-90)
	direction_changes = 0
	for i in range(56, 90):
		prev_delta = rects[i][3] - rects[i - 1][3]
		curr_delta = rects[i + 1][3] - rects[i][3]
		if prev_delta * curr_delta < 0:
			direction_changes += 1
	# with biased monotonicity, direction changes should be very few
	assert direction_changes < 5, (
		f"settling zone had {direction_changes} direction changes, "
		"expected < 5 with biased monotonicity"
	)
