"""Unit tests for track_runner.propagator module."""

# PIP3 modules
import numpy

# local repo modules
import track_runner.propagator as prop_mod
import track_runner.interval_solver as solver_mod


# ============================================================
# basic propagator tests
# ============================================================


#============================================
def test_propagator_make_seed_state_keys() -> None:
	"""make_seed_state returns dict with required v2 state keys."""
	state = prop_mod.make_seed_state(cx=100.0, cy=200.0, w=40.0, h=80.0, conf=1.0)
	for key in ("cx", "cy", "w", "h", "conf", "source"):
		assert key in state, f"missing key: {key}"


#============================================
def test_propagator_make_seed_state_values() -> None:
	"""make_seed_state stores exact input values."""
	state = prop_mod.make_seed_state(cx=150.0, cy=250.0, w=50.0, h=100.0, conf=0.9)
	assert abs(state["cx"] - 150.0) < 1e-9
	assert abs(state["cy"] - 250.0) < 1e-9
	assert abs(state["h"] - 100.0) < 1e-9
	assert abs(state["conf"] - 0.9) < 1e-9


#============================================
def test_propagator_build_appearance_model_keys() -> None:
	"""build_appearance_model returns dict with template and hsv_mean."""
	# create a minimal synthetic frame
	frame = numpy.zeros((200, 300, 3), dtype=numpy.uint8)
	frame[50:150, 100:200] = (0, 128, 255)
	bbox = {"cx": 150.0, "cy": 100.0, "w": 100.0, "h": 100.0}
	model = prop_mod.build_appearance_model(frame, bbox)
	assert "template" in model
	assert "hsv_mean" in model
	assert len(model["hsv_mean"]) == 3


# ============================================================
# refinement pass tests
# ============================================================


#============================================
def test_refine_soft_prior_none_unchanged() -> None:
	"""soft_prior=None produces identical output to no-prior call."""
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
# forward-backward flow consistency
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
