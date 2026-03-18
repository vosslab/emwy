"""Regime classifier for smart crop mode.

Classifies trajectory spans into regimes (clear, uncertain, distance)
based on geometric and confidence signals. Confidence alone cannot
trigger a regime change -- at least one geometric or source-type
corroborating signal is required alongside confidence.

The annotated torso box is the primary camera target, but not a
temporally stable signal. It reflects human-verified subject position
and should anchor the crop. However, frame-to-frame variation from
interpolation, posture changes, and small annotation noise introduces
jitter. The crop therefore follows a smoothed and composition-adjusted
version of the box rather than the raw box directly.

Over short time windows, the underlying subject motion is assumed to
be locally smooth and low-order relative to the scene, even though
image-plane motion is affected by handheld camera motion and framing
adjustments. Large frame-to-frame deviations are more likely noise
than true subject motion and should be damped unless supported by
consistent multi-frame evidence. This is why the uncertain regime
reduces responsiveness and why the classifier requires geometric
corroboration alongside confidence drops.

All thresholds are provisional and will be tuned after 7-video experiment.
"""

# Standard Library
import math

# PIP3 modules
import numpy


# ============================================================
# per-frame feature extraction
# ============================================================


#============================================
def _per_frame_features(
	trajectory: list,
	video_info: dict,
) -> list:
	"""Extract per-frame classification features from trajectory data.

	Args:
		trajectory: Dense list of tracking state dicts (gap-filled).
			Required keys: cx, cy, w, h, conf, source.
		video_info: Dict with frame_count, width, height, fps.

	Returns:
		List of feature dicts, one per frame. Keys:
			conf, conf_trend, bbox_height_ratio, height_change_rate,
			edge_pressure, source_type.
	"""
	n = len(trajectory)
	frame_h = float(video_info["height"])
	frame_w = float(video_info["width"])
	fps = float(video_info["fps"])

	# extract raw arrays, treating None entries as fallback
	confs = numpy.empty(n, dtype=float)
	heights = numpy.empty(n, dtype=float)
	cxs = numpy.empty(n, dtype=float)
	cys = numpy.empty(n, dtype=float)
	widths = numpy.empty(n, dtype=float)
	sources = []
	for i in range(n):
		state = trajectory[i]
		if state is None:
			# treat None as a low-confidence fallback at frame center
			confs[i] = 0.1
			heights[i] = frame_h * 0.5
			cxs[i] = frame_w / 2.0
			cys[i] = frame_h / 2.0
			widths[i] = frame_w * 0.3
			sources.append("fallback")
		else:
			confs[i] = state["conf"]
			heights[i] = state["h"]
			cxs[i] = state["cx"]
			cys[i] = state["cy"]
			widths[i] = state["w"]
			sources.append(state.get("source", "propagated"))

	# confidence trend: rolling mean over ~1 second window
	window = max(1, round(fps))
	conf_trend = _rolling_mean(confs, window)

	# bbox height ratio: h / frame_height
	bbox_height_ratio = heights / frame_h

	# height change rate: rolling normalized std over ~1 second window
	height_change_rate = _rolling_normalized_std(heights, window)

	# edge pressure: min distance from bbox edges to frame edges, normalized
	# lower = closer to edge = more pressure
	edge_pressure = numpy.empty(n, dtype=float)
	for i in range(n):
		half_w = widths[i] / 2.0
		half_h = heights[i] / 2.0
		# distances from bbox edges to frame edges
		left = cxs[i] - half_w
		right = frame_w - (cxs[i] + half_w)
		top = cys[i] - half_h
		bottom = frame_h - (cys[i] + half_h)
		min_dist = max(0.0, min(left, right, top, bottom))
		# normalize by frame diagonal
		diag = math.hypot(frame_w, frame_h)
		edge_pressure[i] = min_dist / diag if diag > 0 else 0.0

	# build per-frame feature dicts
	features = []
	for i in range(n):
		feat = {
			"conf": confs[i],
			"conf_trend": conf_trend[i],
			"bbox_height_ratio": bbox_height_ratio[i],
			"height_change_rate": height_change_rate[i],
			"edge_pressure": edge_pressure[i],
			"source_type": sources[i],
		}
		features.append(feat)

	return features


#============================================
def _rolling_mean(
	signal: numpy.ndarray,
	window: int,
) -> numpy.ndarray:
	"""Compute rolling mean with centered window, edge-padded.

	Args:
		signal: 1-D numpy array.
		window: Window size in frames.

	Returns:
		Rolling mean array of same length.
	"""
	n = len(signal)
	if n == 0:
		return signal.copy()
	# pad symmetrically so output length matches input
	pad_before = window // 2
	pad_after = window - 1 - pad_before
	padded = numpy.pad(signal, (pad_before, pad_after), mode="edge")
	# cumsum trick for O(n) rolling mean
	# prepend a zero so cumsum[i+window] - cumsum[i] gives the window sum
	cumsum = numpy.concatenate(([0.0], numpy.cumsum(padded)))
	rolling = (cumsum[window:] - cumsum[:-window]) / float(window)
	# rolling should have exactly n elements
	result = rolling[:n]
	return result


#============================================
def _rolling_normalized_std(
	signal: numpy.ndarray,
	window: int,
) -> numpy.ndarray:
	"""Compute rolling std normalized by rolling mean.

	Args:
		signal: 1-D numpy array.
		window: Window size in frames.

	Returns:
		Rolling normalized std array (std/mean where mean > 0).
	"""
	n = len(signal)
	if n == 0:
		return signal.copy()
	rolling_mean = _rolling_mean(signal, window)
	# compute rolling std using E[x^2] - E[x]^2
	pad_before = window // 2
	pad_after = window - 1 - pad_before
	padded = numpy.pad(signal, (pad_before, pad_after), mode="edge")
	sq_padded = padded * padded
	cumsum_sq = numpy.concatenate(([0.0], numpy.cumsum(sq_padded)))
	cumsum = numpy.concatenate(([0.0], numpy.cumsum(padded)))
	rolling_sq = (cumsum_sq[window:] - cumsum_sq[:-window]) / float(window)
	rolling_mu = (cumsum[window:] - cumsum[:-window]) / float(window)
	# variance = E[x^2] - E[x]^2, clamp to avoid negative from float error
	variance = numpy.maximum(rolling_sq[:n] - rolling_mu[:n] ** 2, 0.0)
	rolling_std = numpy.sqrt(variance)
	# normalize by mean, avoid division by zero
	result = numpy.where(
		rolling_mean > 1e-6,
		rolling_std / rolling_mean,
		0.0,
	)
	return result


# ============================================================
# regime classification
# ============================================================

# provisional thresholds -- will be tuned after 7-video experiment
_CONF_LOW_THRESHOLD = 0.5
_CONF_TREND_LOW_THRESHOLD = 0.55
_EDGE_PRESSURE_HIGH = 0.02
_HEIGHT_CHANGE_RATE_HIGH = 0.15
_BBOX_RATIO_FAR = 0.08
_BBOX_RATIO_NEAR = 0.25
_FALLBACK_SOURCES = {"hold_last", "fallback"}
_MIN_SPAN_FRAMES_FRAC = 0.5  # seconds, converted to frames using fps


#============================================
def classify_regimes(
	trajectory: list,
	video_info: dict,
	config: dict = None,
) -> list:
	"""Classify trajectory frames into regime spans.

	Produces a list of regime span dicts with start_frame, end_frame,
	regime label, and summary statistics. Regime transitions include
	blend zones for smooth parameter interpolation.

	The classifier enforces the invariant that confidence alone cannot
	trigger the uncertain regime -- at least one geometric or source-type
	corroborating signal is required.

	Args:
		trajectory: Dense list of tracking state dicts (gap-filled).
		video_info: Dict with frame_count, width, height, fps.
		config: Optional config dict (reserved for future threshold overrides).

	Returns:
		List of span dicts sorted by start_frame. Each dict has:
			start_frame (int), end_frame (int), regime (str),
			distance_flag (str or None), blend_in (int), blend_out (int),
			mean_conf (float), mean_bbox_ratio (float).
	"""
	n = len(trajectory)
	if n == 0:
		return []

	fps = float(video_info["fps"])

	# step 1: extract per-frame features
	features = _per_frame_features(trajectory, video_info)

	# step 2: per-frame raw regime labels
	raw_labels = []
	raw_distance_flags = []
	for i in range(n):
		feat = features[i]
		label, dist_flag = _classify_single_frame(feat)
		raw_labels.append(label)
		raw_distance_flags.append(dist_flag)

	# step 3: smooth labels (minimum span duration, absorb short blips)
	min_span_frames = max(1, round(_MIN_SPAN_FRAMES_FRAC * fps))
	smoothed_labels = _smooth_labels(raw_labels, min_span_frames)
	# smooth distance flags too (majority vote within smoothed spans)
	smoothed_dist_flags = _smooth_distance_flags(
		raw_distance_flags, smoothed_labels,
	)

	# step 4: convert to span list with blend zones
	blend_frames = max(1, round(0.3 * fps))
	spans = _labels_to_spans(
		smoothed_labels, smoothed_dist_flags, features, blend_frames,
	)

	return spans


#============================================
def _classify_single_frame(feat: dict) -> tuple:
	"""Classify a single frame into a regime.

	Enforces the invariant: confidence alone cannot trigger uncertain.

	Args:
		feat: Feature dict from _per_frame_features.

	Returns:
		Tuple of (regime_label, distance_flag).
		regime_label: 'clear', 'uncertain', or 'distance'.
		distance_flag: 'far' or 'near' for distance regime, None otherwise.
	"""
	bbox_ratio = feat["bbox_height_ratio"]
	conf = feat["conf"]
	conf_trend = feat["conf_trend"]
	edge_pressure = feat["edge_pressure"]
	height_change = feat["height_change_rate"]
	source = feat["source_type"]

	# distance regime: triggered by bbox size regardless of confidence
	if bbox_ratio < _BBOX_RATIO_FAR:
		return ("distance", "far")
	if bbox_ratio > _BBOX_RATIO_NEAR:
		return ("distance", "near")

	# uncertain regime: requires BOTH low confidence AND geometric corroboration
	conf_low = (conf < _CONF_LOW_THRESHOLD or conf_trend < _CONF_TREND_LOW_THRESHOLD)
	# geometric/source corroborating signals
	has_edge_pressure = edge_pressure < _EDGE_PRESSURE_HIGH
	has_height_instability = height_change > _HEIGHT_CHANGE_RATE_HIGH
	has_degraded_source = source in _FALLBACK_SOURCES
	corroboration = has_edge_pressure or has_height_instability or has_degraded_source

	if conf_low and corroboration:
		return ("uncertain", None)

	# default: clear
	return ("clear", None)


#============================================
def _smooth_labels(
	raw_labels: list,
	min_span_frames: int,
) -> list:
	"""Smooth raw per-frame labels by absorbing short spans.

	Short spans (below min_span_frames) are absorbed into their
	neighbors using majority-vote of the surrounding context.

	Args:
		raw_labels: Per-frame regime label strings.
		min_span_frames: Minimum span duration in frames.

	Returns:
		Smoothed per-frame label list.
	"""
	n = len(raw_labels)
	if n == 0:
		return []

	# convert to spans first
	spans = []
	start = 0
	for i in range(1, n):
		if raw_labels[i] != raw_labels[start]:
			spans.append((start, i, raw_labels[start]))
			start = i
	spans.append((start, n, raw_labels[start]))

	# absorb short spans into neighbors
	# iterate until stable (usually 1-2 passes)
	changed = True
	max_iterations = 10
	iteration = 0
	while changed and iteration < max_iterations:
		changed = False
		new_spans = []
		for idx, (s, e, label) in enumerate(spans):
			duration = e - s
			if duration < min_span_frames and len(spans) > 1:
				# absorb into larger neighbor
				if idx > 0 and idx < len(spans) - 1:
					prev_label = spans[idx - 1][2]
					next_label = spans[idx + 1][2]
					# prefer surrounding label if they agree
					if prev_label == next_label:
						label = prev_label
						changed = True
					else:
						# use the longer neighbor's label
						prev_len = spans[idx - 1][1] - spans[idx - 1][0]
						next_len = spans[idx + 1][1] - spans[idx + 1][0]
						label = prev_label if prev_len >= next_len else next_label
						changed = True
				elif idx == 0 and len(spans) > 1:
					label = spans[1][2]
					changed = True
				elif idx == len(spans) - 1 and len(spans) > 1:
					label = spans[-2][2]
					changed = True
			new_spans.append((s, e, label))

		# merge adjacent spans with same label
		merged = [new_spans[0]]
		for s, e, label in new_spans[1:]:
			if label == merged[-1][2]:
				# extend previous span
				merged[-1] = (merged[-1][0], e, label)
			else:
				merged.append((s, e, label))
		spans = merged
		iteration += 1

	# expand back to per-frame labels
	result = ["clear"] * n
	for s, e, label in spans:
		for i in range(s, e):
			result[i] = label

	return result


#============================================
def _smooth_distance_flags(
	raw_flags: list,
	smoothed_labels: list,
) -> list:
	"""Smooth distance flags within distance spans using majority vote.

	Args:
		raw_flags: Per-frame distance flag strings (or None).
		smoothed_labels: Smoothed per-frame regime labels.

	Returns:
		Smoothed per-frame distance flag list.
	"""
	n = len(raw_flags)
	result = [None] * n

	# find distance spans and apply majority vote
	i = 0
	while i < n:
		if smoothed_labels[i] == "distance":
			# find end of distance span
			j = i
			while j < n and smoothed_labels[j] == "distance":
				j += 1
			# majority vote on flags within this span
			far_count = 0
			near_count = 0
			for k in range(i, j):
				if raw_flags[k] == "far":
					far_count += 1
				elif raw_flags[k] == "near":
					near_count += 1
			majority_flag = "far" if far_count >= near_count else "near"
			for k in range(i, j):
				result[k] = majority_flag
			i = j
		else:
			i += 1

	return result


#============================================
def _labels_to_spans(
	labels: list,
	distance_flags: list,
	features: list,
	blend_frames: int,
) -> list:
	"""Convert per-frame labels to span dicts with blend zones.

	Args:
		labels: Smoothed per-frame regime labels.
		distance_flags: Smoothed per-frame distance flags.
		features: Per-frame feature dicts (for summary stats).
		blend_frames: Number of frames for blend zones at transitions.

	Returns:
		List of span dicts.
	"""
	n = len(labels)
	if n == 0:
		return []

	# find spans
	spans = []
	start = 0
	for i in range(1, n):
		if labels[i] != labels[start] or distance_flags[i] != distance_flags[start]:
			spans.append((start, i))
			start = i
	spans.append((start, n))

	# build span dicts with blend zones
	result = []
	for idx, (s, e) in enumerate(spans):
		# blend_in: frames at the start of this span that blend from previous
		blend_in = 0
		if idx > 0:
			blend_in = min(blend_frames, (e - s) // 2)
		# blend_out: frames at the end that blend into next span
		blend_out = 0
		if idx < len(spans) - 1:
			blend_out = min(blend_frames, (e - s) // 2)

		# compute summary stats for the span
		span_confs = [features[i]["conf"] for i in range(s, e)]
		span_ratios = [features[i]["bbox_height_ratio"] for i in range(s, e)]
		mean_conf = sum(span_confs) / len(span_confs)
		mean_ratio = sum(span_ratios) / len(span_ratios)

		span_dict = {
			"start_frame": s,
			"end_frame": e,
			"regime": labels[s],
			"distance_flag": distance_flags[s],
			"blend_in": blend_in,
			"blend_out": blend_out,
			"mean_conf": round(mean_conf, 3),
			"mean_bbox_ratio": round(mean_ratio, 3),
		}
		result.append(span_dict)

	return result


# ============================================================
# regime summary for console output
# ============================================================


#============================================
def format_regime_summary(
	regime_spans: list,
	total_frames: int,
) -> str:
	"""Format regime classification as a one-line console summary.

	Args:
		regime_spans: List of span dicts from classify_regimes().
		total_frames: Total frames in the video.

	Returns:
		Summary string like "Regimes: clear 85%, distance 10%, uncertain 5%, 4 transitions".
	"""
	if not regime_spans or total_frames <= 0:
		return "Regimes: no data"

	# count frames per regime
	counts = {}
	for span in regime_spans:
		regime = span["regime"]
		span_len = span["end_frame"] - span["start_frame"]
		counts[regime] = counts.get(regime, 0) + span_len

	# format percentages in a stable order
	order = ["clear", "uncertain", "distance"]
	parts = []
	for regime in order:
		count = counts.get(regime, 0)
		pct = 100.0 * count / total_frames
		if count > 0:
			parts.append(f"{regime} {pct:.0f}%")

	# count transitions (number of spans minus 1)
	n_transitions = max(0, len(regime_spans) - 1)
	parts.append(f"{n_transitions} transitions")

	summary = "Regimes: " + ", ".join(parts)
	return summary
