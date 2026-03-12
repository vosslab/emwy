"""Interval confidence metrics for track_runner.

Takes interval evidence from forward and backward tracking passes and
returns agreement score, identity score, competitor margin, and a
final confidence label.
"""

# PIP3 modules
import numpy


#============================================
def _compute_dice_coefficient(
	box_a: dict,
	box_b: dict,
) -> float:
	"""Compute Dice coefficient between two bounding boxes.

	Dice = 2 * intersection_area / (area_a + area_b).
	Result is in [0.0, 1.0] where 1.0 means identical boxes.

	Args:
		box_a: Dict with keys "cx", "cy", "w", "h" (center-format box).
		box_b: Dict with keys "cx", "cy", "w", "h" (center-format box).

	Returns:
		Float Dice coefficient in [0.0, 1.0].
	"""
	# convert center-format to corner-format rectangles
	a_x1 = box_a["cx"] - box_a["w"] / 2.0
	a_y1 = box_a["cy"] - box_a["h"] / 2.0
	a_x2 = box_a["cx"] + box_a["w"] / 2.0
	a_y2 = box_a["cy"] + box_a["h"] / 2.0

	b_x1 = box_b["cx"] - box_b["w"] / 2.0
	b_y1 = box_b["cy"] - box_b["h"] / 2.0
	b_x2 = box_b["cx"] + box_b["w"] / 2.0
	b_y2 = box_b["cy"] + box_b["h"] / 2.0

	# compute intersection rectangle
	inter_x1 = max(a_x1, b_x1)
	inter_y1 = max(a_y1, b_y1)
	inter_x2 = min(a_x2, b_x2)
	inter_y2 = min(a_y2, b_y2)

	# intersection area (zero if no overlap)
	inter_w = max(0.0, inter_x2 - inter_x1)
	inter_h = max(0.0, inter_y2 - inter_y1)
	intersection = inter_w * inter_h

	# individual areas
	area_a = box_a["w"] * box_a["h"]
	area_b = box_b["w"] * box_b["h"]

	# Dice coefficient: 2 * intersection / (area_a + area_b)
	total_area = area_a + area_b
	if total_area <= 0:
		return 0.0
	dice = 2.0 * intersection / total_area
	return dice


#============================================
def compute_meeting_point_errors(
	forward_track: list,
	backward_track: list,
) -> list:
	"""Compute per-frame center and scale errors between forward and backward tracks.

	Args:
		forward_track: List of tracking state dicts from forward propagation.
			Each dict has keys "cx", "cy", "w", "h", "conf", "source".
		backward_track: List of tracking state dicts from backward propagation,
			already reversed to align frame-by-frame with forward_track.

	Returns:
		List of dicts with keys:
			- "frame": int, frame index
			- "center_err_px": float, Euclidean center distance in pixels
			- "scale_err_pct": float, fractional height difference (0.0 to 1.0+)
	"""
	errors = []
	# Iterate over the shorter of the two tracks to avoid index errors
	num_frames = min(len(forward_track), len(backward_track))
	for i in range(num_frames):
		fwd = forward_track[i]
		bwd = backward_track[i]
		# Compute Euclidean center distance
		dx = fwd["cx"] - bwd["cx"]
		dy = fwd["cy"] - bwd["cy"]
		center_err = float(numpy.sqrt(dx * dx + dy * dy))
		# Compute scale error as fractional height difference
		fwd_h = fwd["h"]
		bwd_h = bwd["h"]
		if fwd_h > 0 and bwd_h > 0:
			# Use mean height as reference so the ratio is symmetric
			mean_h = (fwd_h + bwd_h) / 2.0
			scale_err = abs(fwd_h - bwd_h) / mean_h
		else:
			scale_err = 1.0
		frame_error = {
			"frame": i,
			"center_err_px": center_err,
			"scale_err_pct": scale_err,
		}
		errors.append(frame_error)
	return errors


#============================================
def compute_agreement(forward_track: list, backward_track: list) -> float:
	"""Compute overall agreement score between forward and backward tracks.

	Uses Dice coefficient (2*intersection / (area_a + area_b)) per frame,
	which naturally handles scale: two large boxes with high overlap score
	well regardless of absolute pixel size.

	Args:
		forward_track: List of tracking state dicts from forward propagation.
		backward_track: List of tracking state dicts from backward propagation,
			aligned frame-by-frame with forward_track.

	Returns:
		Float in [0.0, 1.0] where 1.0 means perfect agreement.
	"""
	num_frames = min(len(forward_track), len(backward_track))
	if num_frames == 0:
		return 0.0

	frame_scores = []
	for i in range(num_frames):
		fwd = forward_track[i]
		bwd = backward_track[i]
		# Dice coefficient captures both position and scale agreement
		# as a single area-overlap metric
		dice = _compute_dice_coefficient(fwd, bwd)
		frame_scores.append(dice)

	agreement = float(numpy.mean(frame_scores))
	return agreement


#============================================
def classify_confidence(
	agreement: float,
	identity: float,
	margin: float,
) -> tuple:
	"""Classify overall confidence from agreement, identity, and competitor margin.

	Decision grid:
		- High agreement (>0.8) + High separation (>0.5) -> "high"
		- High agreement (>0.8) + Low separation         -> "low", ["low_separation"]
		- Low agreement                                   -> "low", ["low_agreement"]
		- Strong competitor (margin < 0.2)                -> adds "likely_identity_swap"
		- Weak appearance (identity < 0.4)                -> adds "weak_appearance"

	Args:
		agreement: Float [0, 1], forward/backward agreement score.
		identity: Float [0, 1], average identity match score.
		margin: Float [0, 1], average separation from competitors.

	Returns:
		Tuple of (confidence_label: str, failure_reasons: list of str).
	"""
	failure_reasons = []

	# Determine base confidence from agreement and separation
	high_agreement = agreement > 0.8
	high_separation = margin > 0.5
	strong_competitor = margin < 0.2

	if high_agreement and high_separation:
		confidence = "high"
	elif high_agreement and not high_separation:
		confidence = "low"
		failure_reasons.append("low_separation")
	else:
		# Low agreement regardless of separation
		confidence = "low"
		failure_reasons.append("low_agreement")
		if strong_competitor:
			failure_reasons.append("likely_identity_swap")

	# Additional reason for weak appearance regardless of confidence level
	if identity < 0.4:
		failure_reasons.append("weak_appearance")

	return (confidence, failure_reasons)


#============================================
def score_interval(
	forward_track: list,
	backward_track: list,
	identity_scores: list,
	competitor_margins: list,
) -> dict:
	"""Score an interval using forward/backward track evidence.

	Args:
		forward_track: List of tracking state dicts from forward propagation.
			Each dict has keys "cx", "cy", "w", "h", "conf", "source".
		backward_track: List of tracking state dicts from backward propagation,
			already reversed to align frame-by-frame with forward_track.
		identity_scores: List of per-frame identity match scores (float 0-1).
		competitor_margins: List of per-frame competitor margin scores (float 0-1).

	Returns:
		Dict with keys:
			- "agreement_score": float, forward/backward agreement [0, 1]
			- "identity_score": float, average identity match [0, 1]
			- "competitor_margin": float, average competitor separation [0, 1]
			- "confidence": str, "high", "medium", or "low"
			- "failure_reasons": list of str
			- "meeting_point_error": list of per-frame error dicts
	"""
	# Compute agreement between forward and backward passes
	agreement_score = compute_agreement(forward_track, backward_track)

	# Average identity score across frames; default 0.0 if no data
	if identity_scores:
		identity_score = float(numpy.mean(identity_scores))
	else:
		identity_score = 0.0

	# Average competitor margin across frames; default 0.0 if no data
	if competitor_margins:
		competitor_margin = float(numpy.mean(competitor_margins))
	else:
		competitor_margin = 0.0

	# Classify confidence from the three aggregate signals
	confidence, failure_reasons = classify_confidence(
		agreement_score, identity_score, competitor_margin,
	)

	# Compute per-frame meeting point errors for diagnostic output
	meeting_point_error = compute_meeting_point_errors(forward_track, backward_track)

	result = {
		"agreement_score": agreement_score,
		"identity_score": identity_score,
		"competitor_margin": competitor_margin,
		"confidence": confidence,
		"failure_reasons": failure_reasons,
		"meeting_point_error": meeting_point_error,
	}
	return result


#============================================
def compute_seed_confidences(
	seeds: list,
	intervals: list,
) -> dict:
	"""Compute confidence scores for each seed based on adjacent interval metrics.

	For each seed's frame_index, finds adjacent intervals where start_frame or
	end_frame matches, then combines their metrics into a composite score.

	Args:
		seeds: List of seed dicts with 'frame_index' keys.
		intervals: List of interval dicts from diagnostics, each with
			'start_frame', 'end_frame', 'agreement_score', 'identity_score',
			'competitor_margin' keys.

	Returns:
		Dict mapping frame_index (int) to {"score": float, "label": str,
		"adjacent_intervals": int}.
	"""
	confidences = {}
	for seed in seeds:
		fi = int(seed.get("frame_index", seed.get("frame", 0)))
		# find intervals adjacent to this seed frame
		adjacent = []
		for iv in intervals:
			start_f = int(iv.get("start_frame", 0))
			end_f = int(iv.get("end_frame", 0))
			if start_f == fi or end_f == fi:
				adjacent.append(iv)
		if not adjacent:
			confidences[fi] = {
				"score": 0.0,
				"label": "unknown",
				"adjacent_intervals": 0,
			}
			continue
		# combine metrics from adjacent intervals
		agreements = []
		margins = []
		identities = []
		for iv in adjacent:
			agreements.append(float(iv.get("agreement_score", 0.0)))
			margins.append(float(iv.get("competitor_margin", 0.0)))
			identities.append(float(iv.get("identity_score", 0.0)))
		avg_agreement = float(numpy.mean(agreements))
		min_margin = float(min(margins))
		avg_identity = float(numpy.mean(identities))
		# weighted composite score
		score = 0.5 * avg_agreement + 0.3 * min_margin + 0.2 * avg_identity
		# classify label from composite score
		if score > 0.7:
			label = "high"
		elif score > 0.4:
			label = "medium"
		else:
			label = "low"
		confidences[fi] = {
			"score": round(score, 4),
			"label": label,
			"adjacent_intervals": len(adjacent),
		}
	return confidences


#============================================
# self-test for compute_seed_confidences
if __name__ == "__main__":
	# test with matching intervals
	test_seeds = [
		{"frame_index": 100},
		{"frame_index": 500},
		{"frame_index": 999},
	]
	test_intervals = [
		{
			"start_frame": 100, "end_frame": 500,
			"agreement_score": 0.9, "identity_score": 0.8,
			"competitor_margin": 0.6,
		},
		{
			"start_frame": 500, "end_frame": 999,
			"agreement_score": 0.3, "identity_score": 0.2,
			"competitor_margin": 0.1,
		},
	]
	result = compute_seed_confidences(test_seeds, test_intervals)
	# frame 100: one adjacent interval (start_frame=100)
	assert result[100]["adjacent_intervals"] == 1
	assert result[100]["label"] == "high"
	# frame 500: two adjacent intervals (end of first, start of second)
	assert result[500]["adjacent_intervals"] == 2
	# frame 999: one adjacent interval (end_frame=999)
	assert result[999]["adjacent_intervals"] == 1
	assert result[999]["label"] == "low"

	# test with no matching intervals
	orphan_seeds = [{"frame_index": 42}]
	orphan_result = compute_seed_confidences(orphan_seeds, test_intervals)
	assert orphan_result[42]["label"] == "unknown"
	assert orphan_result[42]["adjacent_intervals"] == 0

	print("all scoring self-tests passed")
