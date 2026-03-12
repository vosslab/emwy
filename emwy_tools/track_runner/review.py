"""Weak span identification and seed suggestion for track_runner.

After interval solving, analyzes results to tell the user where to add
more seeds. Provides human-readable summaries and refinement target lists.
"""

# Standard Library
# (none needed beyond builtins)


#============================================
# Reasons recognized in the failure_reasons list from scoring.py
# Listed here for documentation and validation
_KNOWN_REASONS = (
	"low_agreement",
	"low_separation",
	"weak_appearance",
	"detector_conflict",
	"stationary_ambiguity",
	"likely_occlusion",
	"likely_identity_swap",
)

# Human-readable explanation for each failure reason
_REASON_EXPLANATIONS = {
	"low_agreement": "forward/backward trajectories diverge",
	"low_separation": "competitor margin too small",
	"weak_appearance": "appearance evidence collapsed",
	"detector_conflict": "YOLO detections contradict tracked path",
	"stationary_ambiguity": "unclear whether runner is stationary or moving",
	"likely_occlusion": "tracked region partially or fully obscured",
	"likely_identity_swap": "strong competitor overtakes target mid-interval",
}


#============================================
def _midpoint_frame(start_frame: int, end_frame: int) -> int:
	"""Return the midpoint frame index between two frames.

	Args:
		start_frame: Start frame index.
		end_frame: End frame index.

	Returns:
		Integer frame index at the midpoint.
	"""
	return (start_frame + end_frame) // 2


#============================================
def _reason_to_suggestion(
	reason: str,
	start_frame: int,
	end_frame: int,
	fps: float,
) -> dict:
	"""Build a single seed suggestion from a failure reason.

	Places the suggestion at the midpoint of the interval by default.
	For identity_swap reason, places it earlier (at 1/3 of interval).

	Args:
		reason: Failure reason string.
		start_frame: Interval start frame.
		end_frame: Interval end frame.
		fps: Frames per second.

	Returns:
		Seed suggestion dict with frame, time_s, reason, competitor_summary.
	"""
	interval_len = end_frame - start_frame

	if reason == "likely_identity_swap":
		# suggest earlier frame where swap may have started
		frame = start_frame + max(1, interval_len // 3)
	elif reason == "low_agreement":
		# disagreement often peaks in the middle
		frame = _midpoint_frame(start_frame, end_frame)
	else:
		# default: midpoint is a reasonable choice
		frame = _midpoint_frame(start_frame, end_frame)

	time_s = frame / max(1.0, fps)
	explanation = _REASON_EXPLANATIONS.get(reason, reason)
	suggestion = {
		"frame": frame,
		"time_s": time_s,
		"reason": reason,
		"competitor_summary": explanation,
	}
	return suggestion


# Severity tier ordering for comparisons
_SEVERITY_RANK = {"high": 2, "medium": 1, "low": 0}

# Duration threshold (seconds) for promoting severity one level
_DURATION_PROMOTE_THRESHOLD_S = 10.0


#============================================
def classify_interval_severity(interval: dict, fps: float) -> str:
	"""Classify an interval's weakness severity as high, medium, or low.

	Uses both tracking quality scores and interval duration. Longer weak
	intervals are more damaging to the output video, so duration promotes
	severity upward.

	Args:
		interval: Interval dict with interval_score sub-dict, start_frame, end_frame.
		fps: Video frame rate for duration calculation.

	Returns:
		"high", "medium", or "low" severity string.
	"""
	score = interval["interval_score"]
	agreement = float(score.get("agreement_score", 0.0))
	margin = float(score.get("competitor_margin", 0.0))
	failure_reasons = score.get("failure_reasons", [])

	# score-based classification
	# agreement < 0.2 means FWD/BWD strongly disagree -- high severity
	# agreement ~0.5 is already pretty good alignment
	if agreement < 0.2 or "likely_identity_swap" in failure_reasons:
		severity = "high"
	elif margin < 0.2 and agreement < 0.4:
		# low margin combined with poor agreement -- high severity
		severity = "high"
	elif agreement < 0.4:
		severity = "medium"
	elif margin < 0.2:
		# low margin but decent agreement (nearby competitor, tracking correct)
		severity = "medium"
	else:
		severity = "low"

	# duration-based promotion: intervals longer than threshold promote one level
	start_frame = int(interval["start_frame"])
	end_frame = int(interval["end_frame"])
	duration_s = (end_frame - start_frame) / max(1.0, fps)
	if duration_s > _DURATION_PROMOTE_THRESHOLD_S:
		if severity == "low":
			severity = "medium"
		elif severity == "medium":
			severity = "high"

	return severity


#============================================
def identify_weak_spans(diagnostics: dict) -> list:
	"""Walk interval results and return seed suggestions for weak intervals.

	For each interval whose confidence is "low" or "fair", generates one or more
	seed suggestions with a specific frame, time, reason, and competitor summary.

	Args:
		diagnostics: Dict returned by interval_solver.solve_all_intervals().
			Must have "intervals" key with list of interval result dicts.
			Each interval result must have start_frame, end_frame, interval_score.

	Returns:
		List of seed suggestion dicts sorted by frame, each with:
			frame (int), time_s (float), reason (str), competitor_summary (str or None).
	"""
	intervals = diagnostics.get("intervals", [])
	fps = float(diagnostics.get("fps", 30.0))
	suggestions = []

	for interval in intervals:
		start_frame = int(interval["start_frame"])
		end_frame = int(interval["end_frame"])
		score = interval["interval_score"]
		confidence = score.get("confidence", "low")
		failure_reasons = score.get("failure_reasons", [])

		# only suggest seeds for low/fair confidence intervals
		if confidence in ("high", "good"):
			continue

		if failure_reasons:
			# one suggestion per failure reason
			for reason in failure_reasons:
				suggestion = _reason_to_suggestion(
					reason, start_frame, end_frame, fps,
				)
				suggestions.append(suggestion)
		else:
			# no specific reason: suggest midpoint
			frame = _midpoint_frame(start_frame, end_frame)
			time_s = frame / max(1.0, fps)
			suggestion = {
				"frame": frame,
				"time_s": time_s,
				"reason": "low_confidence",
				"competitor_summary": "interval scored below threshold",
			}
			suggestions.append(suggestion)

	# deduplicate by frame, keeping first occurrence
	seen_frames = set()
	unique_suggestions = []
	for s in suggestions:
		if s["frame"] not in seen_frames:
			seen_frames.add(s["frame"])
			unique_suggestions.append(s)

	# sort by frame index
	unique_suggestions.sort(key=lambda s: s["frame"])
	return unique_suggestions


#============================================
def generate_refinement_targets(
	diagnostics: dict,
	mode: str = "suggested",
	seed_interval: int = 300,
	gap_threshold: int = 600,
	time_range: tuple | None = None,
	severity: str | None = None,
) -> list:
	"""Generate frame numbers where new seeds should be placed.

	Supports three modes that can be combined with comma-separation:
	- "suggested": frames from weak span analysis
	- "interval": evenly spaced frames at seed_interval spacing
	- "gap": frames where existing seed spacing exceeds gap_threshold

	When severity is set, only intervals at or above the given severity
	tier are included. Hierarchy: "high" shows only high-severity;
	"medium" shows high + medium; "low" (or None) shows all.

	Args:
		diagnostics: Dict from interval_solver.solve_all_intervals().
		mode: Mode string: "suggested", "interval", "gap", or comma-separated
			combination such as "suggested,gap".
		seed_interval: Frame spacing for "interval" mode.
		gap_threshold: Minimum seed gap (frames) to trigger a suggestion
			in "gap" mode.
		time_range: Optional (start_s, end_s) tuple to restrict scope.
			None means no restriction.
		severity: Optional minimum severity tier ("high", "medium", or "low").
			None means include all weak intervals.

	Returns:
		Sorted, deduplicated list of frame numbers (ints).
	"""
	fps = float(diagnostics.get("fps", 30.0))
	intervals = diagnostics.get("intervals", [])

	# build a set of interval frame ranges that pass severity filter
	# so we can exclude suggestions from intervals below threshold
	min_rank = _SEVERITY_RANK.get(severity, 0) if severity is not None else 0
	excluded_intervals = set()
	if severity is not None:
		for idx, iv in enumerate(intervals):
			score = iv["interval_score"]
			if score.get("confidence", "low") in ("high", "good"):
				continue
			iv_severity = classify_interval_severity(iv, fps)
			if _SEVERITY_RANK.get(iv_severity, 0) < min_rank:
				excluded_intervals.add(idx)

	# determine frame range limits from time_range
	range_start = None
	range_end = None
	if time_range is not None:
		range_start = int(time_range[0] * fps)
		range_end = int(time_range[1] * fps)

	def _in_range(frame: int) -> bool:
		"""Return True if frame is within the optional time_range."""
		if range_start is not None and frame < range_start:
			return False
		if range_end is not None and frame > range_end:
			return False
		return True

	def _frame_in_excluded_interval(frame: int) -> bool:
		"""Return True if frame falls within an excluded interval."""
		for idx in excluded_intervals:
			iv = intervals[idx]
			if int(iv["start_frame"]) <= frame <= int(iv["end_frame"]):
				return True
		return False

	active_modes = [m.strip() for m in mode.split(",")]
	target_set = set()

	if "suggested" in active_modes:
		# use weak span suggestions, filtered by severity
		suggestions = identify_weak_spans(diagnostics)
		for s in suggestions:
			if _in_range(s["frame"]) and not _frame_in_excluded_interval(s["frame"]):
				target_set.add(s["frame"])

	if "interval" in active_modes:
		# evenly spaced frames; find total frame span from intervals
		if intervals:
			overall_start = int(intervals[0]["start_frame"])
			overall_end = int(intervals[-1]["end_frame"])
			frame = overall_start + seed_interval
			while frame < overall_end:
				if _in_range(frame):
					target_set.add(frame)
				frame += seed_interval

	if "gap" in active_modes:
		# suggest frame at midpoint of any seed pair separated by more than threshold
		for idx, interval in enumerate(intervals):
			if idx in excluded_intervals:
				continue
			start_frame = int(interval["start_frame"])
			end_frame = int(interval["end_frame"])
			gap = end_frame - start_frame
			if gap > gap_threshold:
				mid = _midpoint_frame(start_frame, end_frame)
				if _in_range(mid):
					target_set.add(mid)

	targets = sorted(target_set)
	return targets


#============================================
def rank_target_frames_by_severity(
	diagnostics: dict,
	target_frames: list,
	max_count: int = 0,
) -> list:
	"""Rank target frames by parent interval severity and return top N.

	Each target frame is mapped to the interval that contains it. Frames
	are grouped by score tier (agreement, margin), worst tiers first.
	Within each tier, frames are spread evenly across the video for
	spatial coverage rather than clustering at the start.

	Args:
		diagnostics: Dict with "intervals" key.
		target_frames: List of frame numbers to rank.
		max_count: Maximum frames to return. 0 means no limit.

	Returns:
		List of frame numbers sorted by frame order, capped to max_count.
	"""
	intervals = diagnostics.get("intervals", [])

	# build lookup: for each target frame, find parent interval scores
	frame_scores = {}
	for frame in target_frames:
		# find the interval containing this frame
		best_score = None
		for iv in intervals:
			start = int(iv["start_frame"])
			end = int(iv["end_frame"])
			if start <= frame <= end:
				best_score = iv["interval_score"]
				break
		if best_score is None:
			# frame not in any interval, assign worst possible score
			agreement = 0.0
			margin = 0.0
		else:
			agreement = float(best_score.get("agreement_score", 0.0))
			margin = float(best_score.get("competitor_margin", 0.0))
		# round to bin nearby scores into the same tier
		frame_scores[frame] = (round(agreement, 2), round(margin, 2))

	# group frames by score tier
	tiers = {}
	for frame in target_frames:
		key = frame_scores[frame]
		if key not in tiers:
			tiers[key] = []
		tiers[key].append(frame)

	# sort tiers worst-first (lowest agreement, then lowest margin)
	sorted_tier_keys = sorted(tiers.keys())

	# collect frames tier by tier, subsampling within each tier
	# for even spatial coverage when a tier exceeds remaining budget
	selected = []
	remaining = max_count if max_count > 0 else len(target_frames)
	for key in sorted_tier_keys:
		tier_frames = sorted(tiers[key])
		if len(tier_frames) <= remaining:
			# take all frames from this tier
			selected.extend(tier_frames)
			remaining -= len(tier_frames)
		else:
			# subsample evenly across this tier for spatial coverage
			step = len(tier_frames) / remaining
			for i in range(remaining):
				idx = int(i * step)
				selected.append(tier_frames[idx])
			remaining = 0
		if remaining <= 0:
			break

	# return in frame order for sequential playback
	selected.sort()
	return selected


#============================================
def format_review_summary(diagnostics: dict) -> str:
	"""Produce a human-readable summary of all intervals with scores and suggestions.

	Args:
		diagnostics: Dict from interval_solver.solve_all_intervals().

	Returns:
		Multi-line string suitable for printing to the terminal.
	"""
	fps = float(diagnostics.get("fps", 30.0))
	intervals = diagnostics.get("intervals", [])
	suggestions = identify_weak_spans(diagnostics)

	# index suggestions by the interval they fall in for easy lookup
	lines = []
	lines.append("=== Track Runner Review Summary ===")
	lines.append(f"Intervals: {len(intervals)}")

	# count intervals by confidence tier
	from collections import Counter
	tier_counts = Counter(
		iv["interval_score"].get("confidence", "low")
		for iv in intervals
	)
	need_seed = tier_counts.get("low", 0) + tier_counts.get("fair", 0)
	lines.append(
		f"Confidence tiers: "
		f"{tier_counts.get('high', 0)} high, "
		f"{tier_counts.get('good', 0)} good, "
		f"{tier_counts.get('fair', 0)} fair, "
		f"{tier_counts.get('low', 0)} low"
	)
	lines.append(f"Need seeds: {need_seed} / {len(intervals)}")
	lines.append("")

	_confidence_labels = {
		"high": "TRUST", "good": "GOOD", "fair": "FAIR", "low": "WEAK",
	}
	for iv in intervals:
		start_frame = int(iv["start_frame"])
		end_frame = int(iv["end_frame"])
		duration_s = (end_frame - start_frame) / max(1.0, fps)
		score = iv["interval_score"]
		confidence = score.get("confidence", "low")
		agree = float(score.get("agreement_score", 0.0))
		identity = float(score.get("identity_score", 0.0))
		margin = float(score.get("competitor_margin", 0.0))
		reasons = score.get("failure_reasons", [])

		# format verdict label
		tag = _confidence_labels.get(confidence, "WEAK")
		if confidence in ("high", "good"):
			verdict = f"[{tag}]"
		else:
			reason_str = ", ".join(reasons) if reasons else "low_confidence"
			verdict = f"[{tag}: {reason_str}]"

		line = (
			f"  interval {start_frame:5d}-{end_frame:5d} "
			f"({duration_s:.1f}s)  "
			f"agree={agree:.2f}  margin={margin:.2f}  identity={identity:.2f}  "
			f"{verdict}"
		)
		lines.append(line)

	# list seed suggestions
	if suggestions:
		lines.append("")
		lines.append("Suggested seed frames:")
		for s in suggestions:
			time_s = float(s["time_s"])
			frame = int(s["frame"])
			reason = s["reason"]
			summary = s.get("competitor_summary") or ""
			lines.append(f"  frame {frame:5d}  ({time_s:.1f}s)  {reason}  -- {summary}")
	else:
		lines.append("")
		lines.append("No additional seeds suggested.")

	summary = "\n".join(lines)
	return summary


#============================================
def needs_refinement(diagnostics: dict) -> bool:
	"""Return True if any interval has low or fair confidence.

	Only low and fair tiers need additional seeds. High and good
	are considered acceptable.

	Args:
		diagnostics: Dict from interval_solver.solve_all_intervals().

	Returns:
		True if at least one interval needs refinement.
	"""
	intervals = diagnostics.get("intervals", [])
	for iv in intervals:
		score = iv["interval_score"]
		confidence = score.get("confidence", "low")
		if confidence in ("low", "fair"):
			return True
	return False


# simple assertion tests
_test_diag = {
	"fps": 30.0,
	"intervals": [
		{
			"start_frame": 0,
			"end_frame": 300,
			"interval_score": {
				"confidence": "high",
				"failure_reasons": [],
				"agreement_score": 0.9,
				"identity_score": 0.8,
				"competitor_margin": 0.7,
			},
		},
		{
			"start_frame": 300,
			"end_frame": 600,
			"interval_score": {
				"confidence": "fair",
				"failure_reasons": ["low_agreement"],
				"agreement_score": 0.3,
				"identity_score": 0.8,
				"competitor_margin": 0.7,
			},
		},
	],
}
assert needs_refinement(_test_diag) is True

_suggestions = identify_weak_spans(_test_diag)
assert len(_suggestions) == 1
assert _suggestions[0]["reason"] == "low_agreement"

_targets = generate_refinement_targets(_test_diag, mode="suggested")
assert len(_targets) == 1

# severity classification: agreement=0.3 is medium severity
_sev = classify_interval_severity(_test_diag["intervals"][1], 30.0)
assert _sev == "medium"

# severity filtering: medium+ should include the fair interval
_targets_med = generate_refinement_targets(_test_diag, mode="suggested", severity="medium")
assert len(_targets_med) == 1

# "good" confidence should NOT generate seed suggestions
_test_diag_good = {
	"fps": 30.0,
	"intervals": [
		{
			"start_frame": 0,
			"end_frame": 300,
			"interval_score": {
				"confidence": "good",
				"failure_reasons": ["low_separation"],
				"agreement_score": 0.7,
				"identity_score": 0.8,
				"competitor_margin": 0.3,
			},
		},
	],
}
assert needs_refinement(_test_diag_good) is False
assert identify_weak_spans(_test_diag_good) == []
