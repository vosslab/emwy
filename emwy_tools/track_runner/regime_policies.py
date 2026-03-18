"""Regime policy mapping for smart crop mode.

Maps regime labels to exactly 2 crop parameter targets:
fill_ratio and size_update_mode. No config overrides for v1a.

fill_ratio: subject height / crop height (lower = wider crop)
size_update_mode: 'normal', 'slow', or 'frozen'
  - normal: config max_height_change * 1.0
  - slow: config max_height_change * 0.3
  - frozen: config max_height_change * 0.01
"""

# ============================================================
# regime defaults (exactly 2 levers per regime)
# ============================================================

# fill_ratio values: lower = wider crop (subject is smaller fraction)
# size_update_mode: controls zoom rate
REGIME_DEFAULTS = {
	"clear": {
		"fill_ratio": 0.30,
		"size_update_mode": "normal",
	},
	"uncertain": {
		"fill_ratio": 0.25,
		"size_update_mode": "frozen",
	},
	"distance": {
		# distance uses sub-flags for fill_ratio selection
		"far": {
			"fill_ratio": 0.15,
			"size_update_mode": "slow",
		},
		"near": {
			"fill_ratio": 0.35,
			"size_update_mode": "slow",
		},
	},
}

# size_update_mode multipliers applied to config crop_max_height_change
SIZE_MODE_MULTIPLIERS = {
	"normal": 1.0,
	"slow": 0.3,
	"frozen": 0.01,
}


#============================================
def _get_regime_params(regime: str, distance_flag: str = None) -> dict:
	"""Get the default parameters for a regime.

	Args:
		regime: Regime label ('clear', 'uncertain', 'distance').
		distance_flag: 'far' or 'near' for distance regime.

	Returns:
		Dict with fill_ratio and size_update_mode.
	"""
	if regime == "distance":
		flag = distance_flag if distance_flag in ("far", "near") else "far"
		params = REGIME_DEFAULTS["distance"][flag]
	else:
		params = REGIME_DEFAULTS[regime]
	return params


#============================================
def get_frame_params(
	frame_idx: int,
	regime_spans: list,
) -> dict:
	"""Get fill_ratio and size_update_mode for a specific frame.

	fill_ratio is linearly interpolated in blend zones between
	adjacent regimes. size_update_mode is categorical and uses
	the incoming span's mode (no interpolation).

	Args:
		frame_idx: Frame index to query.
		regime_spans: List of span dicts from classify_regimes().

	Returns:
		Dict with keys:
			fill_ratio (float): interpolated fill ratio for this frame.
			size_update_mode (str): 'normal', 'slow', or 'frozen'.
	"""
	if not regime_spans:
		# fallback to clear defaults
		return {
			"fill_ratio": REGIME_DEFAULTS["clear"]["fill_ratio"],
			"size_update_mode": REGIME_DEFAULTS["clear"]["size_update_mode"],
		}

	# find which span this frame belongs to
	span_idx = _find_span_index(frame_idx, regime_spans)
	span = regime_spans[span_idx]
	params = _get_regime_params(span["regime"], span["distance_flag"])

	# check if we are in a blend zone
	fill_ratio = params["fill_ratio"]
	size_mode = params["size_update_mode"]

	# blend-in zone: interpolate from previous span's fill_ratio
	blend_in = span["blend_in"]
	local_offset = frame_idx - span["start_frame"]
	if blend_in > 0 and local_offset < blend_in and span_idx > 0:
		prev_span = regime_spans[span_idx - 1]
		prev_params = _get_regime_params(
			prev_span["regime"], prev_span["distance_flag"],
		)
		# linear interpolation: t=0 at span start, t=1 at end of blend
		t = local_offset / float(blend_in)
		fill_ratio = prev_params["fill_ratio"] + t * (fill_ratio - prev_params["fill_ratio"])
		# size_update_mode: use incoming span's mode (categorical)

	# blend-out zone: interpolate toward next span's fill_ratio
	blend_out = span["blend_out"]
	frames_from_end = span["end_frame"] - 1 - frame_idx
	if blend_out > 0 and frames_from_end < blend_out and span_idx < len(regime_spans) - 1:
		next_span = regime_spans[span_idx + 1]
		next_params = _get_regime_params(
			next_span["regime"], next_span["distance_flag"],
		)
		# linear interpolation: t=0 at start of blend-out, t=1 at span end
		t = 1.0 - frames_from_end / float(blend_out)
		fill_ratio = params["fill_ratio"] + t * (next_params["fill_ratio"] - params["fill_ratio"])
		# size_update_mode: use next span's mode in blend-out zone
		size_mode = next_params["size_update_mode"]

	result = {
		"fill_ratio": fill_ratio,
		"size_update_mode": size_mode,
	}
	return result


#============================================
def _find_span_index(frame_idx: int, regime_spans: list) -> int:
	"""Find the span index that contains a given frame.

	Args:
		frame_idx: Frame index to search for.
		regime_spans: List of span dicts with start_frame and end_frame.

	Returns:
		Index into regime_spans. Returns last span index if frame is
		beyond all spans.
	"""
	for i, span in enumerate(regime_spans):
		if frame_idx < span["end_frame"]:
			return i
	# frame beyond all spans, return last
	return len(regime_spans) - 1


#============================================
def get_size_mode_multiplier(size_update_mode: str) -> float:
	"""Get the max_height_change multiplier for a size_update_mode.

	Args:
		size_update_mode: 'normal', 'slow', or 'frozen'.

	Returns:
		Multiplier float (1.0 for normal, 0.3 for slow, 0.01 for frozen).
	"""
	multiplier = SIZE_MODE_MULTIPLIERS[size_update_mode]
	return multiplier
