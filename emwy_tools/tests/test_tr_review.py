"""Unit tests for track_runner.review module."""

# local repo modules
import track_runner.review as review_mod
import review

from tr_test_helpers import _make_test_diagnostics
from tr_test_helpers import _make_fused_track


# ============================================================
# basic review tests
# ============================================================


#============================================
def test_review_needs_refinement_true_when_weak() -> None:
	"""needs_refinement returns True when any interval is not high."""
	diag = _make_test_diagnostics(confidence="low")
	assert review_mod.needs_refinement(diag) is True


#============================================
def test_review_needs_refinement_false_when_all_high() -> None:
	"""needs_refinement returns False when all intervals are high."""
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
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	suggestions = review_mod.identify_weak_spans(diag)
	# only the weak interval contributes suggestions
	for s in suggestions:
		# all frames should be in the weak interval (300-600)
		assert s["frame"] >= 300


#============================================
def test_review_identify_weak_spans_produces_reason() -> None:
	"""identify_weak_spans sets reason field from interval failure_reasons."""
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	suggestions = review_mod.identify_weak_spans(diag)
	assert len(suggestions) == 1
	assert suggestions[0]["reason"] == "low_agreement"


#============================================
def test_review_identify_weak_spans_all_fields_present() -> None:
	"""Each suggestion has frame, time_s, reason, competitor_summary."""
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
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	targets = review_mod.generate_refinement_targets(diag, mode="suggested")
	assert len(targets) >= 1
	# all frames must be in range [300, 600]
	for f in targets:
		assert 300 <= f <= 600


#============================================
def test_review_generate_refinement_targets_interval_mode() -> None:
	"""'interval' mode returns evenly spaced frames."""
	diag = _make_test_diagnostics()
	targets = review_mod.generate_refinement_targets(diag, mode="interval", seed_interval=150)
	# with span 0-600 and spacing 150, expect frames at 150, 300, 450
	assert len(targets) >= 2
	# targets should be sorted
	assert targets == sorted(targets)


#============================================
def test_review_generate_refinement_targets_gap_mode() -> None:
	"""'gap' mode returns midpoint of intervals exceeding threshold."""
	diag = _make_test_diagnostics()
	# gap_threshold=250 -> both intervals (300 frames each) exceed threshold
	targets = review_mod.generate_refinement_targets(diag, mode="gap", gap_threshold=250)
	assert len(targets) >= 1


#============================================
def test_review_generate_refinement_targets_time_range() -> None:
	"""time_range restricts targets to the given window."""
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
	diag = _make_test_diagnostics(confidence="low", reasons=["low_agreement"])
	summary = review_mod.format_review_summary(diag)
	assert isinstance(summary, str)
	assert len(summary) > 0
	assert "WEAK" in summary or "TRUST" in summary


# ============================================================
# review system occlusion integration
# ============================================================


#============================================
def test_review_find_occlusion_exits():
	"""_find_occlusion_exits detects True->False transitions."""
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
