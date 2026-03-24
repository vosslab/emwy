"""Unit tests for track_runner.tr_crop module.

Tests the rate-limiter gate, EMA smoothing, zoom phase detection,
and aspect ratio parsing in the crop trajectory pipeline.
"""

# PIP3 modules
import numpy

# local repo modules
import tr_crop


FRAME_W = 1920
FRAME_H = 1080
FPS = 60.0


#============================================
def _make_trajectory(n: int, cx: float = 960.0, cy: float = 540.0,
	h: float = 200.0) -> list:
	"""Build a synthetic trajectory with constant or callable values.

	Args:
		n: Number of frames.
		cx: Center x (constant float or callable(i)->float).
		cy: Center y (constant float or callable(i)->float).
		h: Bbox height (constant float or callable(i)->float).

	Returns:
		List of trajectory dicts.
	"""
	traj = []
	for i in range(n):
		state = {
			"cx": cx(i) if callable(cx) else cx,
			"cy": cy(i) if callable(cy) else cy,
			"h": h(i) if callable(h) else h,
			"conf": 0.9,
			"source": "propagated",
		}
		traj.append(state)
	return traj


#============================================
def _make_config(**overrides) -> dict:
	"""Build a minimal config dict for direct_center_crop_trajectory.

	Args:
		**overrides: Keys to set in the processing section.

	Returns:
		Config dict with processing section.
	"""
	processing = {
		"crop_aspect": "16:9",
		"crop_fill_ratio": 0.30,
		"crop_post_smooth_strength": 0.0,
		"crop_post_smooth_size_strength": 0.0,
		"crop_post_smooth_max_velocity": 0.0,
		"crop_max_height_change": 0.005,
		"crop_zoom_stabilization": False,
		"crop_torso_anchor": 0.50,
		"crop_containment_radius": 0.0,
		"crop_min_size": 200,
	}
	processing.update(overrides)
	return {"processing": processing}


#============================================
def _extract_heights(rects: list) -> numpy.ndarray:
	"""Extract crop heights from a list of (x, y, w, h) tuples.

	Args:
		rects: List of (x, y, w, h) integer tuples.

	Returns:
		Numpy array of crop heights as floats.
	"""
	return numpy.array([r[3] for r in rects], dtype=float)


# ---- Test 1: Direct gate comparison ----

#============================================
def test_gate_ema_bypasses_rate_limiter():
	"""With alpha_size > 0, rate limiter is bypassed entirely.

	A step change in bbox height produces smooth EMA output without
	staircase clamping artifacts.
	"""
	n = 200
	# step change at frame 50: height jumps from 200 to 280
	def step_h(i: int) -> float:
		if i < 50:
			return 200.0
		return 280.0

	traj = _make_trajectory(n, h=step_h)

	# with EMA on, rate limiter should be bypassed
	config_ema = _make_config(
		crop_post_smooth_size_strength=0.05,
		crop_max_height_change=0.005,
	)
	rects_ema = tr_crop.direct_center_crop_trajectory(
		traj, FRAME_W, FRAME_H, config_ema, fps=FPS,
	)
	heights_ema = _extract_heights(rects_ema)

	# without EMA, rate limiter should produce staircase
	config_no_ema = _make_config(
		crop_post_smooth_size_strength=0.0,
		crop_max_height_change=0.005,
	)
	rects_no_ema = tr_crop.direct_center_crop_trajectory(
		traj, FRAME_W, FRAME_H, config_no_ema, fps=FPS,
	)
	heights_no_ema = _extract_heights(rects_no_ema)

	# the EMA path should have no frame with delta exactly at the clamp limit
	# (staircase artifact = many frames with delta == max_height_change * h)
	deltas_ema = numpy.diff(heights_ema)
	# count frames where delta is at the clamp ceiling (within rounding)
	# for the no-EMA path, the limiter clamps to 0.5% of height
	clamp_count_ema = 0
	for i in range(len(deltas_ema)):
		expected_clamp = 0.005 * heights_ema[i]
		if abs(abs(deltas_ema[i]) - expected_clamp) < 1.5:
			clamp_count_ema += 1

	# the no-EMA path should have many clamped frames (the staircase)
	deltas_no_ema = numpy.diff(heights_no_ema)
	clamp_count_no_ema = 0
	for i in range(len(deltas_no_ema)):
		expected_clamp = 0.005 * heights_no_ema[i]
		if abs(abs(deltas_no_ema[i]) - expected_clamp) < 1.5:
			clamp_count_no_ema += 1

	# EMA path should have far fewer clamped frames than non-EMA path
	assert clamp_count_ema < clamp_count_no_ema, (
		f"EMA path has {clamp_count_ema} clamped frames, "
		f"non-EMA has {clamp_count_no_ema}; expected EMA < non-EMA"
	)
	# non-EMA path should have substantial clamping (staircase is the
	# primary convergence mechanism for a step input)
	assert clamp_count_no_ema > 20, (
		f"Expected >20 clamped frames in non-EMA path, got {clamp_count_no_ema}"
	)


#============================================
def test_gate_ema_ignores_max_height_change_value():
	"""With alpha_size > 0, output is identical regardless of max_height_change.

	This proves the limiter path is fully bypassed when EMA is active.
	"""
	n = 200
	def step_h(i: int) -> float:
		if i < 50:
			return 200.0
		return 280.0
	traj = _make_trajectory(n, h=step_h)

	# two configs with same EMA alpha but different max_height_change
	config_low = _make_config(
		crop_post_smooth_size_strength=0.05,
		crop_max_height_change=0.005,
	)
	config_high = _make_config(
		crop_post_smooth_size_strength=0.05,
		crop_max_height_change=0.02,
	)
	rects_low = tr_crop.direct_center_crop_trajectory(
		traj, FRAME_W, FRAME_H, config_low, fps=FPS,
	)
	rects_high = tr_crop.direct_center_crop_trajectory(
		traj, FRAME_W, FRAME_H, config_high, fps=FPS,
	)
	heights_low = _extract_heights(rects_low)
	heights_high = _extract_heights(rects_high)

	# outputs must be identical (integer rounding, so exact match)
	assert list(heights_low) == list(heights_high), (
		"EMA path output differs when max_height_change changes; "
		"limiter is not fully bypassed"
	)


#============================================
def test_gate_ema_ignores_zoom_stabilization_flag():
	"""With alpha_size > 0, output is identical whether zoom_stabilization
	is True or False, since both limiter branches are bypassed.
	"""
	n = 200
	def step_h(i: int) -> float:
		if i < 50:
			return 200.0
		return 280.0
	traj = _make_trajectory(n, h=step_h)

	config_off = _make_config(
		crop_post_smooth_size_strength=0.05,
		crop_zoom_stabilization=False,
		crop_max_height_change=0.005,
	)
	config_on = _make_config(
		crop_post_smooth_size_strength=0.05,
		crop_zoom_stabilization=True,
		crop_max_height_change=0.005,
	)
	rects_off = tr_crop.direct_center_crop_trajectory(
		traj, FRAME_W, FRAME_H, config_off, fps=FPS,
	)
	rects_on = tr_crop.direct_center_crop_trajectory(
		traj, FRAME_W, FRAME_H, config_on, fps=FPS,
	)
	heights_off = _extract_heights(rects_off)
	heights_on = _extract_heights(rects_on)

	assert list(heights_off) == list(heights_on), (
		"EMA path output differs when zoom_stabilization changes; "
		"three-mode branch is not fully bypassed"
	)


# ---- Test 2: Rate limiter activates at alpha_size=0 ----

#============================================
def test_scalar_rate_limiter_clamps_step():
	"""With alpha_size=0 and zoom_stabilization=False, the scalar rate
	limiter caps per-frame height change at max_height_change fraction.
	"""
	n = 200
	# large step at frame 50
	def step_h(i: int) -> float:
		if i < 50:
			return 200.0
		return 400.0
	traj = _make_trajectory(n, h=step_h)

	config = _make_config(
		crop_post_smooth_size_strength=0.0,
		crop_zoom_stabilization=False,
		crop_max_height_change=0.005,
	)
	rects = tr_crop.direct_center_crop_trajectory(
		traj, FRAME_W, FRAME_H, config, fps=FPS,
	)
	heights = _extract_heights(rects)

	# check that after the step, height increases gradually
	# (clamped at ~0.5% per frame, not jumping instantly)
	# frame 51 should NOT be at the full target height
	# desired height at frame 51 = 400/0.30 = 1333
	# but it was 200/0.30 = 667 at frame 49, so it should be clamped
	assert heights[51] < 1000, (
		f"Expected rate-limited height at frame 51, got {heights[51]}"
	)
	# many frames after the step should show clamped deltas
	deltas = numpy.diff(heights[50:100])
	positive_deltas = deltas[deltas > 0]
	assert len(positive_deltas) > 10, (
		"Expected many positive deltas after step (gradual climb)"
	)


# ---- Test 3: Three-mode branch at alpha_size=0 ----

#============================================
def test_three_mode_constraint_activates():
	"""With alpha_size=0, zoom_stabilization=True, the three-mode
	constraint produces different rates for transition vs normal frames.
	"""
	n = 300
	# simulate an iPhone zoom transition: large jump at frame 50-54
	# followed by gradual drift
	def zoom_h(i: int) -> float:
		if i < 50:
			return 200.0
		if i < 55:
			# rapid zoom transition (5 frames, ratio > 1.40)
			return 200.0 + (i - 50) * 40.0
		# post-transition: stays at 400
		return 400.0
	traj = _make_trajectory(n, h=zoom_h)

	# three-mode constraint active
	config_3mode = _make_config(
		crop_post_smooth_size_strength=0.0,
		crop_zoom_stabilization=True,
		crop_max_height_change=0.005,
	)
	rects_3mode = tr_crop.direct_center_crop_trajectory(
		traj, FRAME_W, FRAME_H, config_3mode, fps=FPS,
	)
	heights_3mode = _extract_heights(rects_3mode)

	# scalar constraint for comparison
	config_scalar = _make_config(
		crop_post_smooth_size_strength=0.0,
		crop_zoom_stabilization=False,
		crop_max_height_change=0.005,
	)
	rects_scalar = tr_crop.direct_center_crop_trajectory(
		traj, FRAME_W, FRAME_H, config_scalar, fps=FPS,
	)
	heights_scalar = _extract_heights(rects_scalar)

	# during transition frames (50-54), three-mode should constrain MORE
	# tightly (0.02x rate) than scalar (1.0x rate)
	# so three-mode height at frame 55 should be closer to pre-transition
	assert heights_3mode[55] < heights_scalar[55], (
		f"Three-mode at frame 55: {heights_3mode[55]}, "
		f"scalar: {heights_scalar[55]}; "
		f"expected three-mode to constrain more tightly during transition"
	)

	# after settling period, heights should eventually converge
	# (both paths approach the same target)
	# check that both are within 20% of target by frame 250
	target_h = 400.0 / 0.30
	# clamp to frame height
	target_h = min(target_h, FRAME_H)
	assert abs(heights_3mode[250] - target_h) / target_h < 0.20, (
		f"Three-mode not converged by frame 250: {heights_3mode[250]} vs {target_h}"
	)


# ---- Test 4: EMA convergence time ----

#============================================
def test_ema_convergence_within_60_frames():
	"""A 40% step change through alpha=0.05 forward-backward EMA
	converges to within 5% of target within 60 frames.
	"""
	n = 200
	base = 200.0
	target = base * 1.4  # 40% increase
	# step at frame 50
	signal = numpy.full(n, base, dtype=float)
	signal[50:] = target

	smoothed = tr_crop._forward_backward_ema(signal, 0.05)

	# at frame 50+60=110, should be within 5% of target
	tolerance = 0.05 * target
	assert abs(smoothed[110] - target) < tolerance, (
		f"EMA not converged at frame 110: {smoothed[110]:.1f} vs {target:.1f} "
		f"(tolerance {tolerance:.1f})"
	)


#============================================
def test_ema_preserves_constant_signal():
	"""Forward-backward EMA does not distort a constant signal."""
	n = 100
	signal = numpy.full(n, 500.0, dtype=float)
	smoothed = tr_crop._forward_backward_ema(signal, 0.05)
	# should be identical (within float precision)
	assert numpy.allclose(smoothed, 500.0, atol=0.01), (
		"EMA distorted a constant signal"
	)


# ---- Test 5: parse_aspect_ratio ----

#============================================
def test_parse_aspect_ratio_16_9():
	"""Parse '16:9' aspect ratio."""
	result = tr_crop.parse_aspect_ratio("16:9")
	assert abs(result - 16.0 / 9.0) < 0.001


#============================================
def test_parse_aspect_ratio_4_3():
	"""Parse '4:3' aspect ratio."""
	result = tr_crop.parse_aspect_ratio("4:3")
	assert abs(result - 4.0 / 3.0) < 0.001


#============================================
def test_parse_aspect_ratio_1_1():
	"""Parse '1:1' aspect ratio."""
	result = tr_crop.parse_aspect_ratio("1:1")
	assert abs(result - 1.0) < 0.001


#============================================
def test_parse_aspect_ratio_invalid():
	"""Invalid aspect ratio string raises RuntimeError."""
	raised = False
	try:
		tr_crop.parse_aspect_ratio("bad")
	except RuntimeError:
		raised = True
	assert raised, "Expected RuntimeError for invalid aspect ratio"
