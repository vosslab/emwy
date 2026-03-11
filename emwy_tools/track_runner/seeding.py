"""Interactive seeding UI for track_runner v2.

Collects seed points from the user by showing video frames at intervals
and letting the user draw rectangles around the runner's upper torso.
Seeds are returned in the v2 JSON format (no full-person estimation).
"""

# PIP3 modules
import cv2
import numpy

# window title for the interactive seed selection UI
SEED_WINDOW_TITLE = "Track Runner - Seed Selection"


#============================================
def extract_jersey_color(frame: numpy.ndarray, box: list) -> tuple:
	"""Extract median HSV color from a rectangular region.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		box: Rectangle as [x, y, w, h] in pixel coordinates.

	Returns:
		Tuple of (h_median, s_median, v_median) as ints.
	"""
	x, y, w, h = box
	# crop the region of interest from the frame
	roi = frame[y:y + h, x:x + w]
	# convert from BGR to HSV color space
	hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
	# compute median for each HSV channel
	h_median = int(numpy.median(hsv_roi[:, :, 0]))
	s_median = int(numpy.median(hsv_roi[:, :, 1]))
	v_median = int(numpy.median(hsv_roi[:, :, 2]))
	return (h_median, s_median, v_median)


#============================================
def extract_color_histogram(frame: numpy.ndarray, box: list) -> numpy.ndarray:
	"""Extract a normalized 2D color histogram from a rectangular region.

	Computes a joint histogram over the H and S channels of the HSV
	color space for the specified region.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		box: Rectangle as [x, y, w, h] in pixel coordinates.

	Returns:
		Normalized 2D histogram array with shape (30, 32).
	"""
	x, y, w, h = box
	# crop the region of interest
	roi = frame[y:y + h, x:x + w]
	# convert from BGR to HSV
	hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
	# compute 2D histogram on H and S channels
	# H range is 0-180 in OpenCV, S range is 0-256
	hist = cv2.calcHist(
		[hsv_roi], [0, 1], None,
		[30, 32], [0, 180, 0, 256],
	)
	# normalize the histogram so values sum to 1
	cv2.normalize(hist, hist, alpha=1.0, norm_type=cv2.NORM_L1)
	return hist


#============================================
def normalize_seed_box(box: list, config: dict) -> list:
	"""Normalize an inconsistently-drawn seed box.

	Enforces minimum dimensions and clamps the aspect ratio
	to the configured torso range.

	Args:
		box: Rectangle as [x, y, w, h] in pixel coordinates.
		config: Configuration dict optionally containing seeding section.

	Returns:
		Normalized [x, y, w, h] as integers.
	"""
	x, y, w, h = box
	# enforce minimum dimensions of 10 pixels
	w = max(w, 10)
	h = max(h, 10)
	# read aspect ratio limits from config; v2 config uses flat processing section
	processing = config.get("processing", config.get("settings", {}).get("seeding", {}))
	aspect_min = float(processing.get("torso_aspect_min", 0.3))
	aspect_max = float(processing.get("torso_aspect_max", 0.8))
	# compute current aspect ratio (width / height)
	aspect = w / h
	if aspect > aspect_max:
		# too wide, shrink width to match max aspect
		w = int(h * aspect_max)
	elif aspect < aspect_min:
		# too narrow, shrink height to match min aspect
		h = int(w / aspect_min)
	return [int(x), int(y), int(w), int(h)]


#============================================
def _build_seed_dict(
	frame_idx: int,
	time_sec: float,
	torso_box: list,
	jersey_hsv: tuple,
	pass_number: int,
	mode: str,
) -> dict:
	"""Build a v2 seed dict from collected fields.

	Args:
		frame_idx: Frame index (0-based).
		time_sec: Time in seconds.
		torso_box: Normalized torso box as [x, y, w, h].
		jersey_hsv: Tuple of (h, s, v) median HSV values.
		pass_number: Which collection pass this seed came from (1 = initial).
		mode: Seed collection mode string.

	Returns:
		Seed dict in v2 format with frame, time_s, torso_box, jersey_hsv,
		cx, cy, w, h, pass, source, and mode keys.
	"""
	tx, ty, tw, th = torso_box
	# compute center format for propagator compatibility
	cx = float(tx + tw / 2.0)
	cy = float(ty + th / 2.0)
	seed = {
		"frame_index": frame_idx,
		"frame": frame_idx,
		"time_s": round(time_sec, 3),
		"torso_box": torso_box,
		"jersey_hsv": list(jersey_hsv),
		"cx": cx,
		"cy": cy,
		"w": float(tw),
		"h": float(th),
		"pass": pass_number,
		"source": "human",
		"mode": mode,
		"status": "visible",
	}
	return seed


#============================================
def _draw_trajectory_preview(
	frame: numpy.ndarray,
	predictions: dict | None,
) -> None:
	"""Draw forward/backward trajectory prediction boxes on a frame in-place.

	Shows the interval_solver predictions as reference for the user when
	refining seeds in later passes.

	Args:
		frame: BGR image to draw on (modified in place).
		predictions: Optional dict with "forward" and/or "backward" state dicts,
			each containing cx, cy, w, h keys.
	"""
	if predictions is None:
		return
	# forward prediction in blue
	fwd = predictions.get("forward")
	if fwd is not None:
		cx = float(fwd.get("cx", 0))
		cy = float(fwd.get("cy", 0))
		w = float(fwd.get("w", 0))
		h = float(fwd.get("h", 0))
		x1 = int(cx - w / 2.0)
		y1 = int(cy - h / 2.0)
		x2 = int(cx + w / 2.0)
		y2 = int(cy + h / 2.0)
		cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 100, 0), 2)
		cv2.putText(
			frame, "FWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 100, 0), 1,
		)
	# backward prediction in magenta
	bwd = predictions.get("backward")
	if bwd is not None:
		cx = float(bwd.get("cx", 0))
		cy = float(bwd.get("cy", 0))
		w = float(bwd.get("w", 0))
		h = float(bwd.get("h", 0))
		x1 = int(cx - w / 2.0)
		y1 = int(cy - h / 2.0)
		x2 = int(cx + w / 2.0)
		y2 = int(cy + h / 2.0)
		cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 2)
		cv2.putText(
			frame, "BWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1,
		)


#============================================
def _interactive_draw_box(
	frame: numpy.ndarray,
	predictions: dict | None = None,
) -> list | str | None:
	"""Show a frame and let the user draw a rectangle interactively.

	Uses cv2.imshow with a mouse callback for click-drag drawing.

	Args:
		frame: BGR image to display.
		predictions: Optional dict with "forward"/"backward" prediction
			dicts (cx, cy, w, h) for overlay display during refinement.

	Returns:
		Drawn box as [x, y, w, h], or "skip" if spacebar pressed,
		or "prev"/"next" if left/right arrow pressed,
		or "not_in_frame"/"obstructed" if n/o pressed,
		or None if ESC/q pressed to finish.
	"""
	# mutable state for the mouse callback closure
	state = {
		"drawing": False,
		"x1": 0, "y1": 0,
		"x2": 0, "y2": 0,
		"done": False,
	}
	# draw prediction overlays on a copy before entering the loop
	display_frame = frame.copy()
	_draw_trajectory_preview(display_frame, predictions)

	#============================================
	def mouse_callback(event: int, x: int, y: int, flags: int, param: object) -> None:
		"""Handle mouse events for rectangle drawing."""
		if event == cv2.EVENT_LBUTTONDOWN:
			# start drawing
			state["drawing"] = True
			state["x1"] = x
			state["y1"] = y
			state["x2"] = x
			state["y2"] = y
		elif event == cv2.EVENT_MOUSEMOVE and state["drawing"]:
			# update preview rectangle
			state["x2"] = x
			state["y2"] = y
		elif event == cv2.EVENT_LBUTTONUP:
			# finish drawing
			state["drawing"] = False
			state["x2"] = x
			state["y2"] = y
			state["done"] = True

	# set up the window and mouse callback
	cv2.namedWindow(SEED_WINDOW_TITLE, cv2.WINDOW_NORMAL)
	cv2.setMouseCallback(SEED_WINDOW_TITLE, mouse_callback)
	while True:
		# draw instructions and current rectangle on a fresh copy
		show = display_frame.copy()
		# add instruction text overlays
		cv2.putText(
			show,
			"Draw a rectangle around the runner's upper torso",
			(10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
			(0, 255, 255), 2,
		)
		cv2.putText(
			show,
			"LEFT/RIGHT=scrub, SPACE=skip, ESC/q=done",
			(10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
			(0, 255, 255), 2,
		)
		cv2.putText(
			show,
			"n=not in frame, o=obstructed",
			(10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
			(0, 255, 255), 2,
		)
		# draw the rectangle preview while dragging
		if state["drawing"]:
			cv2.rectangle(
				show,
				(state["x1"], state["y1"]),
				(state["x2"], state["y2"]),
				(0, 255, 0), 2,
			)
		cv2.imshow(SEED_WINDOW_TITLE, show)
		key = cv2.waitKey(30) & 0xFF
		# ESC or q: finish collecting seeds
		if key == 27 or key == 113:
			cv2.destroyWindow(SEED_WINDOW_TITLE)
			cv2.waitKey(1)
			return None
		# spacebar: skip this frame
		if key == 32:
			return "skip"
		# left arrow: scrub backward
		if key == 81 or key == 2:
			return "prev"
		# right arrow: scrub forward
		if key == 83 or key == 3:
			return "next"
		# n key: mark runner as not in frame
		if key == 110:
			return "not_in_frame"
		# o key: mark runner as obstructed
		if key == 111:
			return "obstructed"
		# check if mouse drawing finished
		if state["done"]:
			# compute box from the two corner points
			x1 = min(state["x1"], state["x2"])
			y1 = min(state["y1"], state["y2"])
			x2 = max(state["x1"], state["x2"])
			y2 = max(state["y1"], state["y2"])
			w = x2 - x1
			h = y2 - y1
			# ignore tiny accidental clicks
			if w < 5 or h < 5:
				state["done"] = False
				continue
			return [x1, y1, w, h]


#============================================
def collect_seeds(
	video_path: str,
	interval_seconds: float,
	config: dict,
	pass_number: int = 1,
	existing_seeds: list | None = None,
	pre_provided_seeds: list | None = None,
) -> list:
	"""Collect initial seed points for runner tracking (pass 1).

	Opens an interactive UI at regularly spaced frames for the user to draw
	torso rectangles. New seeds append to existing_seeds; never overwrites.

	If pre_provided_seeds is not None, returns them directly for headless
	or automated testing.

	Args:
		video_path: Path to the input video file.
		interval_seconds: Time between seed frames in seconds.
		config: Configuration dict.
		pass_number: Which collection pass this is (default 1 = initial).
		existing_seeds: Optional list of already-collected seeds to append to.
		pre_provided_seeds: Optional list of pre-built seed dicts for testing.

	Returns:
		List of seed dicts in v2 format (existing + newly collected).
	"""
	# headless mode: return pre-provided seeds without opening video
	if pre_provided_seeds is not None:
		return list(pre_provided_seeds)

	# start with a copy of any existing seeds
	all_seeds = list(existing_seeds) if existing_seeds else []

	# open the video file
	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		raise RuntimeError(f"cannot open video: {video_path}")
	fps = cap.get(cv2.CAP_PROP_FPS)
	total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
	if fps <= 0:
		raise RuntimeError(f"invalid fps from video: {video_path}")

	# compute frame indices at the requested interval
	frame_interval = int(round(fps * interval_seconds))
	if frame_interval < 1:
		frame_interval = 1
	seed_frame_indices = list(range(0, total_frames, frame_interval))

	# scrub step is 0.2 seconds worth of frames
	scrub_step = max(1, int(round(fps * 0.2)))

	new_seeds = []
	list_idx = 0
	current_frame = seed_frame_indices[0] if seed_frame_indices else 0
	while list_idx < len(seed_frame_indices):
		frame_idx = current_frame
		cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
		ret, frame = cap.read()
		if not ret:
			list_idx += 1
			if list_idx < len(seed_frame_indices):
				current_frame = seed_frame_indices[list_idx]
			continue
		time_sec = frame_idx / fps
		drawn_box = _interactive_draw_box(frame)
		if drawn_box is None:
			# user pressed ESC/q to finish
			break
		if drawn_box == "skip":
			# advance to next seed interval
			list_idx += 1
			if list_idx < len(seed_frame_indices):
				current_frame = seed_frame_indices[list_idx]
			continue
		if drawn_box == "prev":
			# scrub backward by 0.2 seconds
			current_frame = max(0, current_frame - scrub_step)
			continue
		if drawn_box == "next":
			# scrub forward by 0.2 seconds
			current_frame = min(total_frames - 1, current_frame + scrub_step)
			continue
		# handle absence markers
		if drawn_box in ("not_in_frame", "obstructed"):
			seed = {
				"frame_index": frame_idx,
				"frame": frame_idx,
				"time_s": round(time_sec, 3),
				"status": drawn_box,
				"pass": pass_number,
				"source": "human",
				"mode": "initial",
			}
			new_seeds.append(seed)
			list_idx += 1
			if list_idx < len(seed_frame_indices):
				current_frame = seed_frame_indices[list_idx]
			continue
		# process the drawn rectangle into a seed
		norm_box = normalize_seed_box(drawn_box, config)
		jersey_hsv = extract_jersey_color(frame, norm_box)
		seed = _build_seed_dict(
			frame_idx, time_sec, norm_box, jersey_hsv, pass_number, "initial",
		)
		new_seeds.append(seed)
		list_idx += 1
		if list_idx < len(seed_frame_indices):
			current_frame = seed_frame_indices[list_idx]

	cap.release()
	cv2.destroyAllWindows()
	cv2.waitKey(1)

	# append new seeds without overwriting existing
	all_seeds.extend(new_seeds)
	return all_seeds


#============================================
def collect_seeds_at_frames(
	video_path: str,
	target_frames: list,
	config: dict,
	pass_number: int = 2,
	mode: str = "suggested_refine",
	existing_seeds: list | None = None,
	predictions: dict | None = None,
) -> list:
	"""Collect seed points at specific frame indices (refinement passes).

	Opens an interactive UI at each target frame, with arrow key
	scrubbing and optional trajectory prediction overlay. New seeds
	append to existing_seeds; never overwrites.

	Args:
		video_path: Path to the input video file.
		target_frames: List of frame indices to seed at.
		config: Configuration dict.
		pass_number: Which collection pass this is (default 2 = first refinement).
		mode: Seed mode string such as "suggested_refine", "interval_refine",
			or "gap_refine".
		existing_seeds: Optional list of already-collected seeds to append to.
		predictions: Optional dict mapping frame_index (int) to prediction
			dicts with "forward"/"backward" state dicts for overlay display.

	Returns:
		List of seed dicts in v2 format (existing + newly collected).
	"""
	if not target_frames:
		return list(existing_seeds) if existing_seeds else []

	# start with a copy of any existing seeds
	all_seeds = list(existing_seeds) if existing_seeds else []

	# open the video file
	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		raise RuntimeError(f"cannot open video: {video_path}")
	fps = cap.get(cv2.CAP_PROP_FPS)
	total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
	if fps <= 0:
		raise RuntimeError(f"invalid fps from video: {video_path}")

	# scrub step is 0.2 seconds worth of frames
	scrub_step = max(1, int(round(fps * 0.2)))

	sorted_targets = sorted(target_frames)
	new_seeds = []
	list_idx = 0
	current_frame = sorted_targets[0]

	while list_idx < len(sorted_targets):
		frame_idx = current_frame
		cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
		ret, frame = cap.read()
		if not ret:
			list_idx += 1
			if list_idx < len(sorted_targets):
				current_frame = sorted_targets[list_idx]
			continue
		time_sec = frame_idx / fps

		# look up predictions for this frame if available
		frame_preds = None
		if predictions is not None:
			frame_preds = predictions.get(frame_idx)

		drawn_box = _interactive_draw_box(frame, predictions=frame_preds)
		if drawn_box is None:
			break
		if drawn_box == "skip":
			list_idx += 1
			if list_idx < len(sorted_targets):
				current_frame = sorted_targets[list_idx]
			continue
		if drawn_box == "prev":
			current_frame = max(0, current_frame - scrub_step)
			continue
		if drawn_box == "next":
			current_frame = min(total_frames - 1, current_frame + scrub_step)
			continue
		# handle absence markers
		if drawn_box in ("not_in_frame", "obstructed"):
			seed = {
				"frame_index": frame_idx,
				"frame": frame_idx,
				"time_s": round(time_sec, 3),
				"status": drawn_box,
				"pass": pass_number,
				"source": "human",
				"mode": mode,
			}
			new_seeds.append(seed)
			list_idx += 1
			if list_idx < len(sorted_targets):
				current_frame = sorted_targets[list_idx]
			continue
		# process the drawn rectangle into a seed
		norm_box = normalize_seed_box(drawn_box, config)
		jersey_hsv = extract_jersey_color(frame, norm_box)
		seed = _build_seed_dict(
			frame_idx, time_sec, norm_box, jersey_hsv, pass_number, mode,
		)
		new_seeds.append(seed)
		list_idx += 1
		if list_idx < len(sorted_targets):
			current_frame = sorted_targets[list_idx]

	cap.release()
	cv2.destroyAllWindows()
	cv2.waitKey(1)

	# append new seeds without overwriting existing
	all_seeds.extend(new_seeds)
	return all_seeds
