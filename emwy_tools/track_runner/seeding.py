"""Interactive seeding UI for track_runner.

Collects seed points from the user by showing video frames at intervals
and letting the user draw rectangles around the runner's upper torso.
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
		config: Configuration dict with settings.seeding section.

	Returns:
		Normalized [x, y, w, h] as integers.
	"""
	x, y, w, h = box
	# enforce minimum dimensions of 10 pixels
	w = max(w, 10)
	h = max(h, 10)
	# read aspect ratio limits from config
	seeding = config.get("settings", {}).get("seeding", {})
	aspect_min = float(seeding.get("torso_aspect_min", 0.3))
	aspect_max = float(seeding.get("torso_aspect_max", 0.8))
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
def _compute_iou(box_a: list, box_b: list) -> float:
	"""Compute intersection-over-union between two [x, y, w, h] boxes.

	Args:
		box_a: First box as [x, y, w, h].
		box_b: Second box as [x, y, w, h].

	Returns:
		IoU value between 0.0 and 1.0.
	"""
	# convert to corner format
	ax1, ay1 = box_a[0], box_a[1]
	ax2, ay2 = ax1 + box_a[2], ay1 + box_a[3]
	bx1, by1 = box_b[0], box_b[1]
	bx2, by2 = bx1 + box_b[2], by1 + box_b[3]
	# compute intersection
	ix1 = max(ax1, bx1)
	iy1 = max(ay1, by1)
	ix2 = min(ax2, bx2)
	iy2 = min(ay2, by2)
	inter_w = max(0, ix2 - ix1)
	inter_h = max(0, iy2 - iy1)
	inter_area = inter_w * inter_h
	# compute union
	area_a = box_a[2] * box_a[3]
	area_b = box_b[2] * box_b[3]
	union_area = area_a + area_b - inter_area
	if union_area <= 0:
		return 0.0
	iou = inter_area / union_area
	return iou


#============================================
def find_overlapping_person(
	detections: list, torso_box: list,
) -> dict | None:
	"""Find the person detection that best overlaps a torso rectangle.

	Args:
		detections: List of detection dicts from detection.py.
			Each has keys: bbox ([x,y,w,h]), confidence (float).
		torso_box: User-drawn torso rectangle as [x, y, w, h].

	Returns:
		Best overlapping detection dict, or None if no overlap > 0.1.
	"""
	best_det = None
	best_iou = 0.1  # minimum threshold
	for det in detections:
		iou = _compute_iou(det["bbox"], torso_box)
		if iou > best_iou:
			best_iou = iou
			best_det = det
	return best_det


#============================================
def estimate_full_person_from_torso(torso_box: list) -> list:
	"""Estimate a full-person bounding box from a torso rectangle.

	When no person detection overlaps the torso box, this function
	estimates the full body position based on typical proportions.

	Args:
		torso_box: Torso rectangle as [x, y, w, h] in pixel coordinates.

	Returns:
		Full person box as [cx, cy, w, h] in center format.
	"""
	tx, ty, tw, th = torso_box
	# torso center
	torso_cx = tx + tw / 2.0
	torso_cy = ty + th / 2.0
	# full person height is 2.5 times the torso height
	full_h = th * 2.5
	# center shifted down by half a torso height
	full_cy = torso_cy + th * 0.5
	# full person width is 0.4 times the full height
	full_w = full_h * 0.4
	# use torso center x for the full person center x
	full_cx = torso_cx
	return [int(full_cx), int(full_cy), int(full_w), int(full_h)]


#============================================
def _bbox_to_center(bbox: list) -> list:
	"""Convert a [x, y, w, h] top-left box to [cx, cy, w, h] center format.

	Args:
		bbox: Bounding box as [x, y, w, h] with top-left origin.

	Returns:
		Box as [cx, cy, w, h] in center format.
	"""
	x, y, w, h = bbox
	cx = x + w // 2
	cy = y + h // 2
	return [cx, cy, w, h]


#============================================
def collect_seeds(
	video_path: str,
	interval_seconds: float,
	config: dict,
	detector: object | None = None,
	pre_provided_seeds: list | None = None,
) -> list:
	"""Collect seed points for runner tracking.

	If pre_provided_seeds is not None, returns them directly for
	headless or automated testing. Otherwise opens an interactive
	UI for the user to draw torso rectangles on video frames.

	Args:
		video_path: Path to the input video file.
		interval_seconds: Time between seed frames in seconds.
		config: Configuration dict with settings.seeding section.
		detector: Optional person detector with a detect(frame) method.
		pre_provided_seeds: Optional list of pre-built seed dicts.

	Returns:
		List of seed dicts, each containing:
			frame_index (int), time_seconds (float),
			torso_box ([x,y,w,h]), full_person_box ([cx,cy,w,h]),
			jersey_hsv ([h,s,v]), color_histogram (ndarray).
	"""
	# headless mode: return pre-provided seeds without opening video
	if pre_provided_seeds is not None:
		return list(pre_provided_seeds)
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
	# collect seeds interactively using a mutable index pointer
	seeds = []
	list_idx = 0
	current_frame = seed_frame_indices[0] if seed_frame_indices else 0
	while list_idx < len(seed_frame_indices):
		# seek to the current frame position
		frame_idx = current_frame
		cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
		ret, frame = cap.read()
		if not ret:
			list_idx += 1
			if list_idx < len(seed_frame_indices):
				current_frame = seed_frame_indices[list_idx]
			continue
		time_sec = frame_idx / fps
		# show frame and let user draw a rectangle
		drawn_box = _interactive_draw_box(frame)
		if drawn_box is None:
			# user pressed ESC or q to finish
			break
		if drawn_box == "skip":
			# user pressed spacebar to skip to next seed interval
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
		# handle absence markers (not_in_frame / obstructed)
		if drawn_box in ("not_in_frame", "obstructed"):
			seed = {
				"frame_index": frame_idx,
				"time_seconds": round(time_sec, 3),
				"status": drawn_box,
			}
			seeds.append(seed)
			list_idx += 1
			if list_idx < len(seed_frame_indices):
				current_frame = seed_frame_indices[list_idx]
			continue
		# process the drawn rectangle into a seed
		norm_box = normalize_seed_box(drawn_box, config)
		jersey_hsv = extract_jersey_color(frame, norm_box)
		color_hist = extract_color_histogram(frame, norm_box)
		# determine full person box from detection or estimation
		full_box = _resolve_full_person_box(
			frame, norm_box, detector,
		)
		seed = {
			"frame_index": frame_idx,
			"time_seconds": round(time_sec, 3),
			"torso_box": norm_box,
			"full_person_box": full_box,
			"jersey_hsv": list(jersey_hsv),
			"color_histogram": color_hist,
		}
		seeds.append(seed)
		# advance to next seed interval after successful seed
		list_idx += 1
		if list_idx < len(seed_frame_indices):
			current_frame = seed_frame_indices[list_idx]
	cap.release()
	cv2.destroyAllWindows()
	cv2.waitKey(1)
	return seeds


#============================================
def collect_seeds_at_frames(
	video_path: str,
	target_frames: list,
	config: dict,
	detector: object | None = None,
	predictions: dict | None = None,
) -> list:
	"""Collect seed points at specific frame indices.

	Opens an interactive UI at each target frame, with arrow key
	scrubbing so the user can find the runner nearby.

	Args:
		video_path: Path to the input video file.
		target_frames: List of frame indices to seed at.
		config: Configuration dict with settings.seeding section.
		detector: Optional person detector with a detect(frame) method.
		predictions: Optional dict mapping frame_index to prediction
			dicts with forward/backward bbox data for overlay display.

	Returns:
		List of seed dicts (same format as collect_seeds).
	"""
	if not target_frames:
		return []
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
	# sort target frames
	sorted_targets = sorted(target_frames)
	seeds = []
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
		# handle absence markers (not_in_frame / obstructed)
		if drawn_box in ("not_in_frame", "obstructed"):
			seed = {
				"frame_index": frame_idx,
				"time_seconds": round(time_sec, 3),
				"status": drawn_box,
			}
			seeds.append(seed)
			list_idx += 1
			if list_idx < len(sorted_targets):
				current_frame = sorted_targets[list_idx]
			continue
		# process the drawn rectangle into a seed
		norm_box = normalize_seed_box(drawn_box, config)
		jersey_hsv = extract_jersey_color(frame, norm_box)
		color_hist = extract_color_histogram(frame, norm_box)
		full_box = _resolve_full_person_box(frame, norm_box, detector)
		seed = {
			"frame_index": frame_idx,
			"time_seconds": round(time_sec, 3),
			"torso_box": norm_box,
			"full_person_box": full_box,
			"jersey_hsv": list(jersey_hsv),
			"color_histogram": color_hist,
		}
		seeds.append(seed)
		list_idx += 1
		if list_idx < len(sorted_targets):
			current_frame = sorted_targets[list_idx]
	cap.release()
	cv2.destroyAllWindows()
	cv2.waitKey(1)
	return seeds


#============================================
def _resolve_full_person_box(
	frame: numpy.ndarray,
	torso_box: list,
	detector: object | None,
) -> list:
	"""Determine the full-person box using detection or estimation.

	If a detector is provided, runs detection and looks for an
	overlapping person. Falls back to geometric estimation.

	Args:
		frame: BGR image as a numpy array.
		torso_box: Normalized torso rectangle as [x, y, w, h].
		detector: Optional person detector with detect(frame) method.

	Returns:
		Full person box as [cx, cy, w, h] in center format.
	"""
	if detector is not None:
		detections = detector.detect(frame)
		best = find_overlapping_person(detections, torso_box)
		if best is not None:
			# convert detection bbox to center format
			return _bbox_to_center(best["bbox"])
	# no detection overlap, estimate from torso geometry
	return estimate_full_person_from_torso(torso_box)


#============================================
def _draw_prediction_box(
	frame: numpy.ndarray, prediction: dict,
	color: tuple, label: str,
) -> None:
	"""Draw a prediction bounding box on a frame.

	Converts center-format bbox (cx, cy, w, h) to corners and draws
	a labeled rectangle with confidence value.

	Args:
		frame: BGR image to draw on (modified in place).
		prediction: Dict with bbox [cx, cy, w, h], source, and confidence.
		color: BGR color tuple for the rectangle.
		label: Label string like "FWD" or "BWD".
	"""
	bbox = prediction.get("bbox")
	if bbox is None or len(bbox) != 4:
		return
	cx, cy, w, h = bbox
	# convert center format to corner format
	x1 = int(cx - w / 2.0)
	y1 = int(cy - h / 2.0)
	x2 = int(cx + w / 2.0)
	y2 = int(cy + h / 2.0)
	# draw rectangle
	cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
	# draw label with confidence
	conf = prediction.get("confidence", 0.0)
	label_text = f"{label} {conf:.2f}"
	cv2.putText(
		frame, label_text,
		(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
		color, 1,
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
		predictions: Optional dict with forward/backward prediction
			data to draw as colored overlays on the frame.

	Returns:
		Drawn box as [x, y, w, h], or "skip" if spacebar pressed,
		or "prev"/"next" if left/right arrow pressed,
		or None if ESC/q pressed to finish.
	"""
	# mutable state for the mouse callback closure
	state = {
		"drawing": False,
		"x1": 0, "y1": 0,
		"x2": 0, "y2": 0,
		"done": False,
	}
	display_frame = frame.copy()
	# draw prediction overlays if available
	if predictions is not None:
		# forward prediction: blue
		fwd = predictions.get("forward")
		if fwd is not None:
			_draw_prediction_box(display_frame, fwd, (255, 100, 0), "FWD")
		# backward prediction: magenta
		bwd = predictions.get("backward")
		if bwd is not None:
			_draw_prediction_box(display_frame, bwd, (255, 0, 255), "BWD")

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
