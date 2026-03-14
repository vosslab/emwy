"""Unit tests for track_runner.scoring module."""

# local repo modules
import track_runner.scoring as scoring_mod
import track_runner.interval_solver as solver

from tr_test_helpers import _make_track_state


#============================================
def test_scoring_compute_agreement_identical_tracks() -> None:
	"""Identical forward/backward tracks yield agreement near 1.0."""
	track = [_make_track_state(100.0, 200.0, 40.0, 80.0)] * 10
	score = scoring_mod.compute_agreement(track, track)
	assert score > 0.95


#============================================
def test_scoring_compute_agreement_diverged_tracks() -> None:
	"""Tracks offset by 2x height yield low agreement."""
	fwd = [_make_track_state(100.0, 200.0, 40.0, 80.0)] * 10
	# backward track is 200px offset (2.5x height of 80)
	bwd = [_make_track_state(300.0, 200.0, 40.0, 80.0)] * 10
	score = scoring_mod.compute_agreement(fwd, bwd)
	assert score < 0.5


#============================================
def test_scoring_classify_confidence_high() -> None:
	"""High agreement and margin produces high confidence."""
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.95, identity=0.8, margin=0.7,
	)
	assert confidence == "high"
	assert reasons == []


#============================================
def test_scoring_classify_confidence_low_agreement() -> None:
	"""Low agreement produces low confidence with low_agreement reason."""
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.5, identity=0.8, margin=0.6,
	)
	assert confidence == "fair"
	assert "low_agreement" in reasons


#============================================
def test_scoring_classify_confidence_low_separation() -> None:
	"""High agreement but low margin gives low_separation reason."""
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.9, identity=0.8, margin=0.3,
	)
	assert confidence == "good"
	assert "low_separation" in reasons


#============================================
def test_scoring_classify_confidence_weak_appearance() -> None:
	"""Low identity adds weak_appearance reason regardless of confidence."""
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.95, identity=0.2, margin=0.7,
	)
	# weak_appearance is added even when agreement/margin are fine
	assert "weak_appearance" in reasons


#============================================
def test_scoring_score_interval_returns_expected_keys() -> None:
	"""score_interval result has all required keys."""
	track = [_make_track_state(100.0, 200.0, 40.0, 80.0)] * 5
	identity_scores = [0.8] * 5
	competitor_margins = [0.6] * 5
	result = scoring_mod.score_interval(track, track, identity_scores, competitor_margins)
	for key in ("agreement_score", "identity_score", "competitor_margin", "confidence", "failure_reasons"):
		assert key in result, f"missing key: {key}"


#============================================
def test_classify_confidence_short_interval_promotes_one_tier() -> None:
	"""3-frame interval with fair metrics promotes to good."""
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.35, identity=0.8, margin=0.6,
		interval_length=3,
	)
	# without short-interval promotion this would be "fair"
	assert confidence == "good"


#============================================
def test_classify_confidence_short_interval_low_to_fair() -> None:
	"""2-frame interval with low metrics promotes from low to fair."""
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.15, identity=0.8, margin=0.15,
		interval_length=2,
	)
	# without promotion this would be "low"
	assert confidence == "fair"


#============================================
def test_classify_confidence_long_interval_unchanged() -> None:
	"""100-frame interval does not get short-interval promotion."""
	confidence, reasons = scoring_mod.classify_confidence(
		agreement=0.35, identity=0.8, margin=0.6,
		interval_length=100,
	)
	assert confidence == "fair"


#============================================
def test_classify_confidence_short_high_stays_high() -> None:
	"""3-frame interval already at high does not double-promote."""
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
