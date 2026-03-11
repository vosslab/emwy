"""Interval confidence metrics for track_runner.

Takes interval evidence from forward and backward tracking passes and
returns agreement score, identity score, competitor margin, and a
final confidence label.
"""

# PIP3 modules
import numpy


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

	Per-frame center error is normalized by runner size (fraction of height),
	so a 5px error for a 100px-tall runner is treated differently than 5px for
	a 20px-tall runner. Center error is weighted 0.7 and scale error 0.3.

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
		# Use mean height as the normalization reference
		fwd_h = fwd["h"]
		bwd_h = bwd["h"]
		mean_h = (fwd_h + bwd_h) / 2.0
		if mean_h <= 0:
			frame_scores.append(0.0)
			continue
		# Normalized center error: fraction of runner height
		dx = fwd["cx"] - bwd["cx"]
		dy = fwd["cy"] - bwd["cy"]
		center_err_px = float(numpy.sqrt(dx * dx + dy * dy))
		# Clamp at 2x height so errors don't drive score below 0
		normalized_center_err = min(center_err_px / mean_h, 2.0)
		center_score = 1.0 - normalized_center_err / 2.0

		# Scale error: symmetric fractional height difference
		scale_err = abs(fwd_h - bwd_h) / mean_h
		scale_err_clamped = min(scale_err, 1.0)
		scale_score = 1.0 - scale_err_clamped

		# Weighted combination: center matters more than scale
		frame_score = 0.7 * center_score + 0.3 * scale_score
		frame_scores.append(frame_score)

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
