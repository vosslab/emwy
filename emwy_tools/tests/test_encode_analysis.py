"""Unit tests for track_runner.encode_analysis module.

Layer 1 synthetic tests: verify that computed metrics measure what
they claim using deterministic synthetic inputs.
"""

# Standard Library
import math
import os

# local repo modules
import track_runner.encode_analysis as ea


FPS = 30.0
OUTPUT_W = 960
OUTPUT_H = 540


#============================================
def _make_trajectory(n: int, conf: float = 0.9) -> list:
	"""Build a minimal trajectory list with constant confidence.

	Args:
		n: Number of frames.
		conf: Confidence value for all frames.

	Returns:
		List of trajectory dicts.
	"""
	traj = []
	for i in range(n):
		traj.append({
			"cx": 500.0, "cy": 300.0,
			"w": 60.0, "h": 120.0,
			"conf": conf, "source": "propagated",
		})
	return traj


#============================================
def _make_crop_rects_constant(n: int, x: int = 200, y: int = 100,
	w: int = 960, h: int = 540) -> list:
	"""Build constant crop rects (no motion).

	Args:
		n: Number of frames.
		x: Crop x position.
		y: Crop y position.
		w: Crop width.
		h: Crop height.

	Returns:
		List of (x, y, w, h) tuples.
	"""
	rects = [(x, y, w, h)] * n
	return rects


#============================================
class TestConstantVelocity:
	"""Constant-velocity crop path should have near-zero jerk."""

	def test_zero_jerk_stationary(self) -> None:
		"""Stationary input: all metrics near zero."""
		n = 100
		rects = _make_crop_rects_constant(n)
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		motion = result["motion_stability"]
		assert motion["center_jerk_p50"] == 0.0
		assert motion["center_jerk_p95"] == 0.0
		assert motion["height_jerk_p50"] == 0.0
		assert motion["height_jerk_p95"] == 0.0
		assert motion["crop_size_cv"] == 0.0

	def test_low_jerk_constant_velocity(self) -> None:
		"""Constant linear motion: jerk should be near zero."""
		n = 100
		# crop moves 1px/frame rightward at constant speed
		rects = [(200 + i, 100, 960, 540) for i in range(n)]
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		motion = result["motion_stability"]
		# velocity is constant, so jerk should be 0 or near-zero
		assert motion["center_jerk_p50"] == 0.0
		assert motion["center_jerk_p95"] == 0.0
		assert motion["height_jerk_p50"] == 0.0


#============================================
class TestSinusoidalOscillation:
	"""Sinusoidal center oscillation should produce elevated jerk."""

	def test_elevated_center_jerk(self) -> None:
		"""Sinusoidal x oscillation: center jerk proportional to amplitude."""
		n = 200
		# sinusoidal x oscillation: 10px amplitude, period 20 frames
		rects = []
		for i in range(n):
			x_offset = int(10 * math.sin(2 * math.pi * i / 20))
			rects.append((200 + x_offset, 100, 960, 540))
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		motion = result["motion_stability"]
		# jerk should be clearly nonzero
		assert motion["center_jerk_p95"] > 0.5
		# height jerk should stay low (no height change)
		assert motion["height_jerk_p95"] == 0.0

	def test_higher_amplitude_more_jerk(self) -> None:
		"""Higher amplitude oscillation should produce more jerk."""
		n = 200
		# small amplitude (2px)
		rects_small = [
			(200 + int(2 * math.sin(2 * math.pi * i / 20)), 100, 960, 540)
			for i in range(n)
		]
		# large amplitude (40px) -- big enough gap to avoid integer quantization ties
		rects_large = [
			(200 + int(40 * math.sin(2 * math.pi * i / 20)), 100, 960, 540)
			for i in range(n)
		]
		traj = _make_trajectory(n)
		small = ea.analyze_crop_stability(rects_small, traj, OUTPUT_W, OUTPUT_H, FPS)
		large = ea.analyze_crop_stability(rects_large, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert large["motion_stability"]["center_jerk_max"] > small["motion_stability"]["center_jerk_max"]


#============================================
class TestStepChangeHeight:
	"""Step change in crop height should produce a spike in height jerk."""

	def test_height_jerk_spike(self) -> None:
		"""Abrupt height change: height jerk max should be large."""
		n = 100
		# constant height for first 50 frames, then sudden jump
		rects = []
		for i in range(n):
			h = 540 if i < 50 else 600
			rects.append((200, 100, 960, h))
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		motion = result["motion_stability"]
		# height jerk max should capture the step
		assert motion["height_jerk_max"] > 0.0
		# crop_size_cv should be nonzero
		assert motion["crop_size_cv"] > 0.0


#============================================
class TestQuantizationChatter:
	"""Test quantization chatter detection."""

	def test_chatter_detected(self) -> None:
		"""Alternating +1/-1 center deltas at low velocity = chatter."""
		n = 100
		# alternate between x=200 and x=201 every frame (classic chatter)
		rects = []
		for i in range(n):
			x = 200 + (i % 2)
			rects.append((x, 100, 960, 540))
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		# chatter fraction should be significant
		assert result["motion_stability"]["quantization_chatter_fraction"] > 0.1

	def test_no_chatter_real_motion(self) -> None:
		"""Consistent 1px/frame motion should NOT be flagged as chatter."""
		n = 100
		# steady 3px/frame rightward (real motion, not oscillation)
		rects = [(200 + 3 * i, 100, 960, 540) for i in range(n)]
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		# real motion at 3px/frame exceeds the velocity threshold
		assert result["motion_stability"]["quantization_chatter_fraction"] == 0.0


#============================================
class TestDirectionReversal:
	"""Direction reversal at constant speed: high vector jerk."""

	def test_reversal_high_jerk(self) -> None:
		"""Zigzag path: high center jerk from direction changes."""
		n = 100
		# zigzag: move right 5px, then left 5px, repeat
		rects = []
		x = 200
		direction = 1
		for i in range(n):
			rects.append((x, 100, 960, 540))
			x += 5 * direction
			# reverse every 5 frames
			if i % 5 == 4:
				direction *= -1
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		motion = result["motion_stability"]
		# direction reversals should produce high jerk
		assert motion["center_jerk_p95"] > 5.0


#============================================
class TestConfidenceMetrics:
	"""Test confidence statistics computation."""

	def test_high_confidence(self) -> None:
		"""All high-confidence frames: low_conf_fraction should be 0."""
		n = 100
		rects = _make_crop_rects_constant(n)
		traj = _make_trajectory(n, conf=0.95)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert result["confidence"]["mean"] == 0.95
		assert result["confidence"]["low_conf_fraction"] == 0.0

	def test_low_confidence(self) -> None:
		"""All low-confidence frames: low_conf_fraction should be 1."""
		n = 100
		rects = _make_crop_rects_constant(n)
		traj = _make_trajectory(n, conf=0.2)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert result["confidence"]["mean"] == 0.2
		assert result["confidence"]["low_conf_fraction"] == 1.0

	def test_mixed_confidence(self) -> None:
		"""Half high, half low confidence: fraction should be ~0.5."""
		n = 100
		rects = _make_crop_rects_constant(n)
		traj = []
		for i in range(n):
			conf = 0.9 if i < 50 else 0.3
			traj.append({
				"cx": 500.0, "cy": 300.0,
				"w": 60.0, "h": 120.0,
				"conf": conf, "source": "propagated",
			})
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert result["confidence"]["low_conf_fraction"] == 0.5


#============================================
class TestInstabilityRegions:
	"""Test instability region detection and classification."""

	def test_stable_no_regions(self) -> None:
		"""Stationary input with high confidence: no instability regions."""
		n = 100
		rects = _make_crop_rects_constant(n)
		traj = _make_trajectory(n, conf=0.95)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert result["instability_regions"] == []
		assert result["dominant_symptom"] == "stable"


#============================================
class TestDominantSymptom:
	"""Test dominant symptom classification."""

	def test_stable_when_no_issues(self) -> None:
		"""No instability regions: dominant symptom is stable."""
		n = 100
		rects = _make_crop_rects_constant(n)
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert result["dominant_symptom"] == "stable"


#============================================
class TestSolverContext:
	"""Test analyze_solver_context() with synthetic interval data."""

	def test_basic_solver_context(self) -> None:
		"""Basic solver context: computes seed density and desert count."""
		seeds = [{"frame": 0}, {"frame": 300}, {"frame": 600}]
		# interval_score structure matches real track runner intervals format:
		# identity_score and competitor_margin are top-level in interval_score,
		# meeting_point_error is a list of per-frame dicts with center_err_px
		interval_results = [
			{
				"start_frame": 0,
				"frame_count": 300,
				"interval_score": {
					"identity_score": 0.85,
					"competitor_margin": 0.4,
					"meeting_point_error": [
						{"center_err_px": 5.0, "scale_err_pct": 0.01},
					],
				},
			},
			{
				"start_frame": 300,
				"frame_count": 300,
				"interval_score": {
					"identity_score": 0.75,
					"competitor_margin": 0.3,
					"meeting_point_error": [
						{"center_err_px": 8.0, "scale_err_pct": 0.02},
					],
				},
			},
		]
		result = ea.analyze_solver_context(interval_results, seeds, FPS)
		# 3 seeds over 600 frames at 30fps = 20 seconds = 0.333 min
		# density = 3 / 0.333 = ~9.0
		assert result["seed_density"] > 5.0
		assert result["fwd_bwd_convergence_median"] == 6.5
		assert result["identity_score_median"] == 0.8
		assert result["competitor_margin_median"] == 0.35

	def test_empty_intervals(self) -> None:
		"""Empty intervals: all zeros."""
		result = ea.analyze_solver_context([], [], FPS)
		assert result["seed_density"] == 0.0
		assert result["desert_count"] == 0

	def test_desert_detection(self) -> None:
		"""Large gap between seeds: should count as desert."""
		# seeds at frames 0 and 1000 (33.3s gap at 30fps)
		seeds = [{"frame": 0}, {"frame": 1000}]
		interval_results = [{
			"start_frame": 0,
			"frame_count": 1000,
			"diagnostics": {},
		}]
		result = ea.analyze_solver_context(interval_results, seeds, FPS)
		# 1000 frame gap = 33.3s >> 5s threshold
		assert result["desert_count"] >= 1


#============================================
class TestReproducibility:
	"""Same input must produce identical output."""

	def test_deterministic_output(self) -> None:
		"""Two runs on same data produce identical results."""
		n = 200
		rects = [
			(200 + int(10 * math.sin(2 * math.pi * i / 30)), 100, 960, 540)
			for i in range(n)
		]
		traj = _make_trajectory(n, conf=0.8)
		result1 = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		result2 = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert result1 == result2


#============================================
class TestYamlOutput:
	"""Test YAML write and format functions."""

	def test_write_analysis_yaml(self, tmp_path: object) -> None:
		"""write_analysis_yaml creates a valid YAML file."""
		n = 50
		rects = _make_crop_rects_constant(n)
		traj = _make_trajectory(n)
		analysis = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		solver = ea.analyze_solver_context([], [], FPS)
		yaml_path = os.path.join(str(tmp_path), "test_analysis.yaml")
		ea.write_analysis_yaml(analysis, solver, yaml_path)
		assert os.path.isfile(yaml_path)
		# verify file is readable
		with open(yaml_path) as f:
			content = f.read()
		assert "track_runner_encode_analysis" in content

	def test_format_report_returns_string(self) -> None:
		"""format_analysis_report returns a non-empty string."""
		n = 50
		rects = _make_crop_rects_constant(n)
		traj = _make_trajectory(n)
		analysis = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		solver = ea.analyze_solver_context([], [], FPS)
		report = ea.format_analysis_report(analysis, solver, "test.yaml")
		assert isinstance(report, str)
		assert "crop path analysis" in report
		assert len(report) > 100


#============================================
class TestSmoothMonotonicZoom:
	"""Smooth monotonic zoom: low height jerk, nonzero height velocity."""

	def test_smooth_zoom(self) -> None:
		"""Gradual zoom should have low height jerk."""
		n = 200
		# height grows linearly from 500 to 600 over 200 frames
		rects = [
			(200, 100, 960, 500 + i // 2) for i in range(n)
		]
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		motion = result["motion_stability"]
		# smooth zoom = low jerk
		assert motion["height_jerk_p95"] <= 1.0
		# but nonzero CV (size is changing)
		assert motion["crop_size_cv"] > 0.0


#============================================
class TestEdgeCases:
	"""Edge cases and boundary conditions."""

	def test_single_frame(self) -> None:
		"""Single frame: should not crash."""
		rects = [(200, 100, 960, 540)]
		traj = [{"cx": 500.0, "cy": 300.0, "w": 60.0, "h": 120.0,
			"conf": 0.9, "source": "propagated"}]
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert result["summary"]["frames"] == 1

	def test_two_frames(self) -> None:
		"""Two frames: should compute velocity but no jerk."""
		rects = [(200, 100, 960, 540), (205, 100, 960, 540)]
		traj = _make_trajectory(2)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert result["summary"]["frames"] == 2

	def test_none_trajectory_entries(self) -> None:
		"""None entries in trajectory: should use 0 confidence."""
		n = 50
		rects = _make_crop_rects_constant(n)
		traj = [None] * n
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		assert result["confidence"]["mean"] == 0.0
		assert result["confidence"]["low_conf_fraction"] == 1.0


#============================================
class TestCompositionMetrics:
	"""Test composition-quality metrics (center offset, edge margins)."""

	def test_centered_subject_low_offset(self) -> None:
		"""Subject centered in crop: center offset should be near zero."""
		n = 100
		# crop 960x540 centered at (480, 270), subject 60x120 centered at (480, 270)
		rects = [(0, 0, 960, 540)] * n
		traj = []
		for i in range(n):
			traj.append({
				"cx": 480.0, "cy": 270.0,
				"w": 60.0, "h": 120.0,
				"conf": 0.9, "source": "propagated",
			})
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		comp = result["composition"]
		assert comp["center_offset_p50"] < 0.01
		assert comp["center_offset_max"] < 0.01
		assert comp["bad_center_fraction"] == 0.0

	def test_edge_drifted_subject_high_offset(self) -> None:
		"""Subject drifted to corner: high center offset and edge touch."""
		n = 100
		# crop 960x540 at (0, 0), subject at far corner (950, 530)
		rects = [(0, 0, 960, 540)] * n
		traj = []
		for i in range(n):
			traj.append({
				"cx": 950.0, "cy": 530.0,
				"w": 60.0, "h": 120.0,
				"conf": 0.9, "source": "propagated",
			})
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		comp = result["composition"]
		# center is at (480, 270), subject at (950, 530)
		# dx_norm = (950 - 480) / 960 = 0.489, dy_norm = (530 - 270) / 540 = 0.481
		# offset = hypot(0.489, 0.481) ≈ 0.68 > 0.25 -> bad_center
		assert comp["center_offset_p50"] > 0.25
		assert comp["bad_center_fraction"] > 0.0
		# edge touch: subject at (950 +/- 30, 530 +/- 60)
		# right margin = 960 - 980 = -20 (off edge) -> margin < 5
		assert comp["edge_touch_count"] > 0

	def test_bad_frame_run_detection(self) -> None:
		"""Consecutive bad frames: run detection should count runs."""
		n = 50
		# first 10 frames: centered (good)
		# next 15 frames: drifted (bad)
		# next 10 frames: centered (good)
		# next 15 frames: drifted again (bad)
		rects = [(0, 0, 960, 540)] * n
		traj = []
		for i in range(n):
			if i < 10 or (20 <= i < 30) or (45 <= i):
				# centered
				cx, cy = 480.0, 270.0
			else:
				# drifted to edge
				cx, cy = 950.0, 530.0
			traj.append({
				"cx": cx, "cy": cy,
				"w": 60.0, "h": 120.0,
				"conf": 0.9, "source": "propagated",
			})
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		comp = result["composition"]
		# should have runs of bad frames: 15 frames (10-24), 15 frames (30-44)
		assert comp["bad_run_count"] >= 2
		assert comp["bad_run_max_length"] >= 10

	def test_bad_center_isolation(self) -> None:
		"""High offset alone (edges safe): bad_center but not bad_edge."""
		n = 100
		# crop 1000x600, subject moves horizontally across
		rects = [(0, 0, 1000, 600)] * n
		traj = []
		for i in range(n):
			# subject moves from center to far right (high offset)
			cx = 500.0 + 300.0 * (i / n)  # 500 to 800
			cy = 300.0  # vertically centered
			traj.append({
				"cx": cx, "cy": cy,
				"w": 50.0, "h": 100.0,  # small subject, safe edges
				"conf": 0.9, "source": "propagated",
			})
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		comp = result["composition"]
		# late frames have high offset (cx > 700 from center 500)
		# but subject is small (50x100) so edges are safe
		assert comp["bad_center_fraction"] > 0.0
		# edge margins should be safe because subject is small
		assert comp["edge_margin_p05"] > 10.0

	def test_bad_edge_isolation(self) -> None:
		"""Subject too close to edge: bad_edge but offset low."""
		n = 100
		# crop 960x540, subject positioned near bottom-right edge
		rects = [(0, 0, 960, 540)] * n
		traj = []
		for i in range(n):
			# subject: 200x200, positioned at (880, 460) = 10px from right/bottom
			traj.append({
				"cx": 880.0, "cy": 460.0,
				"w": 200.0, "h": 200.0,
				"conf": 0.9, "source": "propagated",
			})
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		comp = result["composition"]
		# crop center is (480, 270), subject at (880, 460)
		# offset should still be moderate
		# but edge margins are tight: right = 960 - 980 = -20 (bad)
		assert comp["edge_margin_min_px"] < 5.0
		assert comp["edge_touch_count"] > 0
		assert comp["bad_edge_fraction"] > 0.0

	def test_bad_zoom_isolation(self) -> None:
		"""Crop height changes > 2%: bad_zoom flag."""
		n = 50
		rects = []
		for i in range(n):
			# height: 540 for first 25, then 570 (5.6% jump)
			h = 540 if i < 25 else 570
			rects.append((0, 0, 960, h))
		traj = _make_trajectory(n)
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		comp = result["composition"]
		# after frame 25, zoom change is (570 - 540) / 540 = 5.6% > 2%
		assert comp["bad_zoom_fraction"] > 0.0

	def test_anisotropic_normalization_correctness(self) -> None:
		"""Verify normalization is per-axis: wider crop = smaller normalized offset."""
		n = 100
		# two crops, same center offset in pixels, different dimensions
		# crop1: 400x300, subject offset by (40, 30) pixels from center
		# -> offset_norm = hypot(40/400, 30/300) = hypot(0.1, 0.1) ≈ 0.141
		rects1 = [(0, 0, 400, 300)] * n
		traj1 = []
		for i in range(n):
			traj1.append({
				"cx": 200.0 + 40.0, "cy": 150.0 + 30.0,
				"w": 60.0, "h": 120.0,
				"conf": 0.9, "source": "propagated",
			})
		# crop2: 800x600 (2x larger), same pixel offset
		# -> offset_norm = hypot(40/800, 30/600) = hypot(0.05, 0.05) ≈ 0.0707
		rects2 = [(0, 0, 800, 600)] * n
		traj2 = []
		for i in range(n):
			traj2.append({
				"cx": 400.0 + 40.0, "cy": 300.0 + 30.0,
				"w": 60.0, "h": 120.0,
				"conf": 0.9, "source": "propagated",
			})
		result1 = ea.analyze_crop_stability(rects1, traj1, 400, 300, FPS)
		result2 = ea.analyze_crop_stability(rects2, traj2, 800, 600, FPS)
		comp1 = result1["composition"]
		comp2 = result2["composition"]
		# larger crop -> smaller normalized offset
		assert comp1["center_offset_p50"] > comp2["center_offset_p50"]

	def test_composition_none_trajectory_fallback(self) -> None:
		"""None trajectory entries: should use defaults (offset=0, margin=inf)."""
		n = 100
		rects = [(0, 0, 960, 540)] * n
		traj = [None] * n
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		comp = result["composition"]
		# no trajectory = no bad frames
		assert comp["bad_frame_fraction"] == 0.0
		assert comp["center_offset_p50"] == 0.0

	def test_bad_run_count_minimum_length(self) -> None:
		"""Bad-frame runs < 3 frames: should not count."""
		n = 100
		rects = [(0, 0, 960, 540)] * n
		traj = []
		for i in range(n):
			# single bad frame at i=20, pair at i=50-51, run of 5 at i=70-74
			if i == 20 or (50 <= i < 52) or (70 <= i < 75):
				cx, cy = 950.0, 530.0
			else:
				cx, cy = 480.0, 270.0
			traj.append({
				"cx": cx, "cy": cy,
				"w": 60.0, "h": 120.0,
				"conf": 0.9, "source": "propagated",
			})
		result = ea.analyze_crop_stability(rects, traj, OUTPUT_W, OUTPUT_H, FPS)
		comp = result["composition"]
		# only runs >= 3 count: run at 70-74 (length 5)
		assert comp["bad_run_count"] == 1
		assert comp["bad_run_max_length"] == 5
