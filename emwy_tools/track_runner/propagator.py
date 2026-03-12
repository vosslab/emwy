"""Frame-to-frame local torso tracking using optical flow and patch correlation.

Given a known torso bounding box at frame N, estimates the torso position at
frame N+1 (forward) or N-1 (backward) using Lucas-Kanade optical flow
combined with patch correlation for confirmation.
"""

# Standard Library
import math
import time

# PIP3 modules
import cv2
import numpy

# Confidence decay applied per propagated frame
CONF_DECAY_PER_FRAME = 0.97
# Minimum confidence floor
CONF_FLOOR = 0.1
# Number of consecutive near-zero-displacement frames to trigger stationary lock
STATIONARY_STREAK_THRESHOLD = 5
# Displacement threshold (fraction of torso height) for "near zero"
STATIONARY_DISP_FRACTION = 0.03
# Patch search margin in pixels for correlation
PATCH_SEARCH_MARGIN = 20
# Minimum feature points to trust flow result
MIN_FLOW_FEATURES = 4
# LK optical flow parameters
_LK_PARAMS = {
	"winSize": (15, 15),
	"maxLevel": 3,
	"criteria": (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
}
# goodFeaturesToTrack parameters
_GFT_PARAMS = {
	"maxCorners": 50,
	"qualityLevel": 0.01,
	"minDistance": 5,
	"blockSize": 5,
}


#============================================
def build_appearance_model(frame: numpy.ndarray, bbox: dict) -> dict:
	"""Build an appearance model from a frame and torso bounding box.

	Captures a template patch and HSV color summary for later use
	in patch correlation and appearance confirmation.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		bbox: Tracking state dict with cx, cy, w, h keys.

	Returns:
		Dict with keys: template (BGR patch), hsv_mean (H, S, V tuple),
		scale (torso height in pixels), cx, cy, w, h.
	"""
	cx = float(bbox["cx"])
	cy = float(bbox["cy"])
	w = float(bbox["w"])
	h = float(bbox["h"])
	frame_h, frame_w = frame.shape[:2]

	# compute pixel bounds clamped to frame
	x1 = int(max(0, cx - w / 2.0))
	y1 = int(max(0, cy - h / 2.0))
	x2 = int(min(frame_w, cx + w / 2.0))
	y2 = int(min(frame_h, cy + h / 2.0))

	# extract template patch; fall back to 1x1 if region is degenerate
	if x2 > x1 and y2 > y1:
		patch = frame[y1:y2, x1:x2].copy()
	else:
		fallback_y = max(0, int(cy))
		fallback_x = max(0, int(cx))
		patch = frame[fallback_y:max(fallback_y + 1, 1),
			fallback_x:max(fallback_x + 1, 1)].copy()

	# compute HSV mean over the patch
	if patch.size > 0:
		hsv_patch = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
		hsv_mean = (
			float(numpy.mean(hsv_patch[:, :, 0])),
			float(numpy.mean(hsv_patch[:, :, 1])),
			float(numpy.mean(hsv_patch[:, :, 2])),
		)
	else:
		hsv_mean = (0.0, 0.0, 0.0)

	appearance = {
		"template": patch,
		"hsv_mean": hsv_mean,
		"scale": h,
		"cx": cx,
		"cy": cy,
		"w": w,
		"h": h,
	}
	return appearance


#============================================
def _extract_features(frame: numpy.ndarray, bbox: dict) -> numpy.ndarray | None:
	"""Extract good feature points inside a torso bounding box.

	Uses Shi-Tomasi corner detection restricted to the torso region.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		bbox: Tracking state dict with cx, cy, w, h keys.

	Returns:
		Array of feature points shaped (N, 1, 2) as float32, or None
		if no features found.
	"""
	cx = float(bbox["cx"])
	cy = float(bbox["cy"])
	w = float(bbox["w"])
	h = float(bbox["h"])
	frame_h, frame_w = frame.shape[:2]

	# compute pixel bounds clamped to frame
	x1 = int(max(0, cx - w / 2.0))
	y1 = int(max(0, cy - h / 2.0))
	x2 = int(min(frame_w, cx + w / 2.0))
	y2 = int(min(frame_h, cy + h / 2.0))

	if x2 <= x1 or y2 <= y1:
		return None

	# convert region to grayscale for corner detection
	roi = frame[y1:y2, x1:x2]
	gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

	# detect corners inside the roi
	pts = cv2.goodFeaturesToTrack(gray_roi, **_GFT_PARAMS)
	if pts is None or len(pts) == 0:
		return None

	# shift points back to full-frame coordinates
	pts[:, :, 0] += x1
	pts[:, :, 1] += y1
	return pts.astype(numpy.float32)


#============================================
def _compute_median_flow(
	prev_pts: numpy.ndarray,
	curr_pts: numpy.ndarray,
	status: numpy.ndarray,
) -> tuple:
	"""Compute the median displacement from valid optical flow point pairs.

	Args:
		prev_pts: Feature points in the previous frame, shape (N, 1, 2).
		curr_pts: Tracked points in the current frame, shape (N, 1, 2).
		status: LK status array, shape (N, 1), 1 for tracked, 0 for lost.

	Returns:
		Tuple (dx, dy) median displacement in pixels, or (0.0, 0.0) if
		no valid points.
	"""
	# select points where tracking succeeded
	mask = status.ravel().astype(bool)
	if not numpy.any(mask):
		return (0.0, 0.0)

	good_prev = prev_pts[mask].reshape(-1, 2)
	good_curr = curr_pts[mask].reshape(-1, 2)

	# displacement vectors
	flow = good_curr - good_prev
	# median is robust to outlier flow vectors
	dx = float(numpy.median(flow[:, 0]))
	dy = float(numpy.median(flow[:, 1]))
	return (dx, dy)


#============================================
def _estimate_scale_change(
	prev_pts: numpy.ndarray,
	curr_pts: numpy.ndarray,
	status: numpy.ndarray,
	prev_bbox: dict,
) -> float:
	"""Estimate scale change from flow divergence between tracked points.

	Uses the ratio of inter-point distances in curr vs prev to estimate
	whether the subject is getting larger or smaller.

	Args:
		prev_pts: Feature points in the previous frame, shape (N, 1, 2).
		curr_pts: Tracked points in the current frame, shape (N, 1, 2).
		status: LK status array, shape (N, 1).
		prev_bbox: Tracking state dict for context (not used in ratio).

	Returns:
		Scale factor as a float. 1.0 means no scale change.
	"""
	mask = status.ravel().astype(bool)
	if numpy.sum(mask) < 2:
		# not enough points to estimate scale
		return 1.0

	good_prev = prev_pts[mask].reshape(-1, 2)
	good_curr = curr_pts[mask].reshape(-1, 2)

	n = len(good_prev)
	# compute pairwise distances for a random sample of pairs
	# to avoid O(n^2) over 50 points, sample up to 20 pairs
	max_pairs = 20
	ratios = []
	# use consecutive pairs for speed and reproducibility
	num_pairs = min(max_pairs, n - 1)
	for i in range(num_pairs):
		dist_prev = float(numpy.linalg.norm(good_prev[i + 1] - good_prev[i]))
		dist_curr = float(numpy.linalg.norm(good_curr[i + 1] - good_curr[i]))
		if dist_prev > 1e-3:
			ratios.append(dist_curr / dist_prev)

	if not ratios:
		return 1.0

	# median ratio is robust to a few outlier pairs
	scale = float(numpy.median(ratios))
	# clamp to a reasonable range per frame
	scale = max(0.85, min(1.15, scale))
	return scale


#============================================
def _patch_correlation(
	prev_frame: numpy.ndarray,
	curr_frame: numpy.ndarray,
	prev_bbox: dict,
	search_margin: int = PATCH_SEARCH_MARGIN,
) -> tuple:
	"""Find the best matching location for a template patch in the next frame.

	Performs normalized cross-correlation inside a search window around
	the predicted center.

	Args:
		prev_frame: BGR image of the previous frame.
		curr_frame: BGR image of the current frame.
		prev_bbox: Tracking state dict with cx, cy, w, h.
		search_margin: Pixel margin around predicted center to search.

	Returns:
		Tuple (dx, dy, correlation_score) where dx/dy are integer pixel
		offsets from center and correlation_score is in [0, 1].
	"""
	cx = float(prev_bbox["cx"])
	cy = float(prev_bbox["cy"])
	w = float(prev_bbox["w"])
	h = float(prev_bbox["h"])
	frame_h, frame_w = prev_frame.shape[:2]

	# compute template patch bounds in prev_frame
	tx1 = int(max(0, cx - w / 2.0))
	ty1 = int(max(0, cy - h / 2.0))
	tx2 = int(min(frame_w, cx + w / 2.0))
	ty2 = int(min(frame_h, cy + h / 2.0))

	if tx2 <= tx1 + 2 or ty2 <= ty1 + 2:
		# degenerate template - return zero offset, low score
		return (0, 0, 0.0)

	# extract grayscale template from previous frame
	template = cv2.cvtColor(prev_frame[ty1:ty2, tx1:tx2], cv2.COLOR_BGR2GRAY)

	# define search region in curr_frame centered on same location + margin
	sx1 = int(max(0, tx1 - search_margin))
	sy1 = int(max(0, ty1 - search_margin))
	sx2 = int(min(frame_w, tx2 + search_margin))
	sy2 = int(min(frame_h, ty2 + search_margin))

	if sx2 <= sx1 + template.shape[1] or sy2 <= sy1 + template.shape[0]:
		# search region too small
		return (0, 0, 0.0)

	search_region = cv2.cvtColor(curr_frame[sy1:sy2, sx1:sx2], cv2.COLOR_BGR2GRAY)

	# run normalized cross-correlation
	result = cv2.matchTemplate(search_region, template, cv2.TM_CCOEFF_NORMED)
	_, max_val, _, max_loc = cv2.minMaxLoc(result)

	# max_loc is (col, row) in the result image
	# convert to offset in full-frame pixels
	match_x = sx1 + max_loc[0] + template.shape[1] // 2
	match_y = sy1 + max_loc[1] + template.shape[0] // 2
	dx = int(match_x - cx)
	dy = int(match_y - cy)

	# clamp to search margin to avoid runaway offsets
	dx = max(-search_margin, min(search_margin, dx))
	dy = max(-search_margin, min(search_margin, dy))

	# normalize correlation score to [0, 1]
	score = float(max(0.0, min(1.0, (max_val + 1.0) / 2.0)))
	return (dx, dy, score)


#============================================
def _track_one_frame(
	prev_frame: numpy.ndarray,
	curr_frame: numpy.ndarray,
	prev_state: dict,
	appearance_model: dict,
) -> dict:
	"""Estimate the tracking state for curr_frame given the state in prev_frame.

	Runs Lucas-Kanade optical flow on features inside the torso region.
	Falls back to patch correlation if flow fails. Blends estimates based
	on torso size (scale-gated behavior). Updates confidence based on
	flow quality.

	Args:
		prev_frame: BGR image of the previous frame.
		curr_frame: BGR image of the current frame.
		prev_state: Tracking state dict (cx, cy, w, h, conf, source).
		appearance_model: Appearance model from build_appearance_model().

	Returns:
		New tracking state dict for curr_frame.
	"""
	prev_h = float(prev_state["h"])
	prev_cx = float(prev_state["cx"])
	prev_cy = float(prev_state["cy"])
	prev_w = float(prev_state["w"])
	prev_conf = float(prev_state["conf"])
	is_stationary = bool(prev_state.get("stationary_lock", False))

	# if stationary lock is active, hold position, decay confidence gently
	if is_stationary:
		new_conf = max(CONF_FLOOR, prev_conf * CONF_DECAY_PER_FRAME)
		new_state = {
			"cx": prev_cx,
			"cy": prev_cy,
			"w": prev_w,
			"h": prev_h,
			"conf": new_conf,
			"source": "propagated",
			"stationary_lock": True,
			"disp_history": list(prev_state.get("disp_history", [])),
		}
		return new_state

	# extract flow features from the torso region
	prev_pts = _extract_features(prev_frame, prev_state)
	use_flow = False
	dx_flow = 0.0
	dy_flow = 0.0
	scale_change = 1.0
	flow_conf = 0.0

	if prev_pts is not None and len(prev_pts) >= MIN_FLOW_FEATURES:
		# run pyramidal Lucas-Kanade optical flow
		curr_pts, status, _ = cv2.calcOpticalFlowPyrLK(
			cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY),
			cv2.cvtColor(curr_frame, cv2.COLOR_BGR2GRAY),
			prev_pts,
			None,
			**_LK_PARAMS,
		)
		if curr_pts is not None and status is not None:
			good_count = int(numpy.sum(status))
			if good_count >= MIN_FLOW_FEATURES:
				dx_flow, dy_flow = _compute_median_flow(prev_pts, curr_pts, status)
				# scale change estimation for large and medium runners
				if prev_h >= 30.0:
					scale_change = _estimate_scale_change(
						prev_pts, curr_pts, status, prev_state,
					)
				# confidence based on fraction of features tracked
				flow_conf = min(1.0, good_count / max(1, len(prev_pts)))
				use_flow = True

	# patch correlation for confirmation / fallback
	dx_corr = 0
	dy_corr = 0
	corr_score = 0.0
	if prev_h >= 30.0:
		# only run correlation when the runner is large enough for a good template
		dx_corr, dy_corr, corr_score = _patch_correlation(
			prev_frame, curr_frame, prev_state,
		)

	# scale-gated blending of flow vs correlation
	if prev_h > 60.0:
		# large runner: mostly appearance / patch correlation
		if use_flow:
			dx = dx_flow * 0.4 + dx_corr * 0.6
			dy = dy_flow * 0.4 + dy_corr * 0.6
		else:
			dx = float(dx_corr)
			dy = float(dy_corr)
		quality = max(flow_conf, corr_score)
	elif prev_h >= 30.0:
		# medium runner: balance flow and correlation
		if use_flow:
			dx = dx_flow * 0.6 + dx_corr * 0.4
			dy = dy_flow * 0.6 + dy_corr * 0.4
		else:
			dx = float(dx_corr)
			dy = float(dy_corr)
		quality = max(flow_conf, corr_score * 0.7)
	else:
		# small runner: motion continuity only (flow), suppress appearance
		if use_flow:
			dx = dx_flow
			dy = dy_flow
		else:
			dx = 0.0
			dy = 0.0
		quality = flow_conf

	# compute new center and size
	new_cx = prev_cx + dx
	new_cy = prev_cy + dy
	new_w = prev_w * scale_change
	new_h = prev_h * scale_change

	# decay confidence per frame; boost slightly if quality is high
	conf_decay = CONF_DECAY_PER_FRAME if quality > 0.5 else CONF_DECAY_PER_FRAME * 0.95
	new_conf = max(CONF_FLOOR, prev_conf * conf_decay)

	# update displacement history for stationary lock detection
	disp_history = list(prev_state.get("disp_history", []))
	total_disp = math.sqrt(dx * dx + dy * dy)
	disp_threshold = prev_h * STATIONARY_DISP_FRACTION
	disp_history.append(total_disp < disp_threshold)
	# keep only the last STATIONARY_STREAK_THRESHOLD entries
	if len(disp_history) > STATIONARY_STREAK_THRESHOLD:
		disp_history = disp_history[-STATIONARY_STREAK_THRESHOLD:]

	# detect stationary lock: all recent displacements were near zero
	stationary_lock = (
		len(disp_history) >= STATIONARY_STREAK_THRESHOLD
		and all(disp_history)
	)

	new_state = {
		"cx": new_cx,
		"cy": new_cy,
		"w": new_w,
		"h": new_h,
		"conf": new_conf,
		"source": "propagated",
		"stationary_lock": stationary_lock,
		"disp_history": disp_history,
	}
	return new_state


#============================================
def propagate_forward(
	frames_reader: object,
	start_frame: int,
	start_state: dict,
	end_frame: int,
	appearance_model: dict,
	debug: bool = False,
) -> list:
	"""Propagate a tracking state forward from start_frame to end_frame.

	Reads frames from frames_reader and tracks the torso bounding box
	forward one frame at a time using optical flow and patch correlation.

	Args:
		frames_reader: VideoReader with read_frame(index) and get_info().
		start_frame: Frame index where start_state is known.
		start_state: Tracking state dict at start_frame.
		end_frame: Last frame index to track to (inclusive).
		appearance_model: Appearance model from build_appearance_model().
		debug: If True, print a heartbeat every 30 seconds with progress.

	Returns:
		List of tracking state dicts, one per frame from start_frame to
		end_frame inclusive. Index 0 is the state at start_frame (the seed).
	"""
	states = [start_state]
	prev_state = start_state
	prev_frame = frames_reader.read_frame(start_frame)
	if prev_frame is None:
		# cannot read the starting frame; return seed only
		return states

	t_prop_start = time.time()
	last_heartbeat = t_prop_start
	for frame_idx in range(start_frame + 1, end_frame + 1):
		curr_frame = frames_reader.read_frame(frame_idx)
		if curr_frame is None:
			# end of video reached early
			break
		new_state = _track_one_frame(prev_frame, curr_frame, prev_state, appearance_model)
		states.append(new_state)
		prev_state = new_state
		prev_frame = curr_frame
		# heartbeat every 30 seconds during long propagation runs
		if debug:
			now = time.time()
			if now - last_heartbeat >= 30.0:
				done = frame_idx - start_frame
				total = end_frame - start_frame
				elapsed = now - t_prop_start
				rate = done / max(0.1, elapsed)
				print(f"      propagation fwd: {done}/{total} frames "
					f"({elapsed:.0f}s, {rate:.1f} frames/s)", flush=True)
				last_heartbeat = now

	return states


#============================================
def propagate_backward(
	frames_reader: object,
	start_frame: int,
	start_state: dict,
	end_frame: int,
	appearance_model: dict,
	debug: bool = False,
) -> list:
	"""Propagate a tracking state backward from start_frame to end_frame.

	Reads frames from frames_reader and tracks the torso bounding box
	backward one frame at a time. Returns states in reverse order so that
	index 0 corresponds to end_frame and the last element to start_frame.

	Args:
		frames_reader: VideoReader with read_frame(index) and get_info().
		start_frame: Frame index where start_state is known (later frame).
		start_state: Tracking state dict at start_frame.
		end_frame: Earliest frame index to track back to (inclusive).
		appearance_model: Appearance model from build_appearance_model().
		debug: If True, print a heartbeat every 30 seconds with progress.

	Returns:
		List of tracking state dicts from end_frame to start_frame inclusive.
		Index 0 is the state at end_frame, last index is at start_frame.
	"""
	# collect states in reverse order, then flip
	reverse_states = [start_state]
	prev_state = start_state
	prev_frame = frames_reader.read_frame(start_frame)
	if prev_frame is None:
		return reverse_states

	t_prop_start = time.time()
	last_heartbeat = t_prop_start
	total = start_frame - end_frame
	for frame_idx in range(start_frame - 1, end_frame - 1, -1):
		curr_frame = frames_reader.read_frame(frame_idx)
		if curr_frame is None:
			break
		# track "forward" in backward time (curr_frame is older)
		new_state = _track_one_frame(prev_frame, curr_frame, prev_state, appearance_model)
		reverse_states.append(new_state)
		prev_state = new_state
		prev_frame = curr_frame
		# heartbeat every 30 seconds during long propagation runs
		if debug:
			now = time.time()
			if now - last_heartbeat >= 30.0:
				done = start_frame - frame_idx
				elapsed = now - t_prop_start
				rate = done / max(0.1, elapsed)
				print(f"      propagation bwd: {done}/{total} frames "
					f"({elapsed:.0f}s, {rate:.1f} frames/s)", flush=True)
				last_heartbeat = now

	# reverse so index 0 = end_frame, last = start_frame
	reverse_states.reverse()
	return reverse_states


#============================================
def make_seed_state(
	cx: float,
	cy: float,
	w: float,
	h: float,
	conf: float = 1.0,
) -> dict:
	"""Create a seed tracking state dict at a known location.

	Args:
		cx: Center x in full-frame pixel coordinates.
		cy: Center y in full-frame pixel coordinates.
		w: Bounding box width in pixels.
		h: Bounding box height in pixels.
		conf: Initial confidence (default 1.0 for human seeds).

	Returns:
		Tracking state dict with source='seed'.
	"""
	state = {
		"cx": float(cx),
		"cy": float(cy),
		"w": float(w),
		"h": float(h),
		"conf": float(conf),
		"source": "seed",
		"stationary_lock": False,
		"disp_history": [],
	}
	return state


# simple assertion tests for make_seed_state
result = make_seed_state(100.0, 200.0, 50.0, 80.0)
assert result["cx"] == 100.0
assert result["source"] == "seed"
assert result["conf"] == 1.0
