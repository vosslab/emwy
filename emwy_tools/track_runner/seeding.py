"""Interactive seeding UI for track_runner v2.

Collects seed points from the user by showing video frames at intervals
and letting the user draw rectangles around the runner's upper torso.
Seeds are returned in the v2 JSON format (no full-person estimation).
"""

# PIP3 modules
import cv2
import numpy
from PySide6.QtWidgets import QApplication

# local repo modules
import overlay_config
import common_tools.frame_reader as frame_reader
import ui.workspace as workspace_module
import ui.seed_controller as seed_controller_module
import ui.target_controller as target_controller_module

AnnotationWindow = workspace_module.AnnotationWindow
SeedController = seed_controller_module.SeedController
TargetController = target_controller_module.TargetController

# window title for the legacy interactive seed selection UI
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
def detection_to_torso_box(bbox: list) -> list:
	"""Extract upper 60% of detection bbox as torso region.

	Args:
		bbox: Bounding box as [x, y, w, h] in pixel coordinates.

	Returns:
		Torso box as [x, y, w, h] representing the upper 60% of bbox.
	"""
	x, y, w, h = bbox
	torso_h = int(h * 0.6)
	return [x, y, w, torso_h]


#============================================
def suggest_seed_candidates(
	frame: numpy.ndarray,
	detections: list,
	confirmed_seeds: list,
	frame_index: int,
) -> dict:
	"""Suggest seed candidates from YOLO detections.

	Analyzes detections and confirmed seeds to suggest the best
	candidate for seeding, or returns candidates for manual selection.

	Args:
		frame: BGR image as a numpy array (H, W, 3).
		detections: List of detection dicts from YoloDetector with
			keys: bbox, confidence, class_id.
		confirmed_seeds: List of already-seeded dicts with jersey_hsv
			and optionally histogram.
		frame_index: Current frame index for reference.

	Returns:
		Dict with keys:
			candidates: List of candidate dicts with keys bbox,
				torso_box, histogram, detection_confidence.
			suggestion_index: Index in candidates for auto-highlight
				(None if manual mode).
			mode: "none" (no detections), "manual" (no single best),
				or "single" (exactly one detection).
			scores: List of Bhattacharyya distances (lower = better match)
				or None if no confirmed seeds.
	"""
	# no detections: return empty candidates
	if not detections:
		return {
			"candidates": [],
			"suggestion_index": None,
			"mode": "none",
			"scores": None,
		}

	# build candidate list with torso regions and histograms
	candidates = []
	for det in detections:
		bbox = det["bbox"]
		torso_box = detection_to_torso_box(bbox)
		# extract histogram from torso region
		hist = extract_color_histogram(frame, torso_box)
		candidate = {
			"bbox": bbox,
			"torso_box": torso_box,
			"histogram": hist,
			"detection_confidence": det["confidence"],
		}
		candidates.append(candidate)

	# if no confirmed seeds: return manual mode (let user pick)
	if not confirmed_seeds:
		return {
			"candidates": candidates,
			"suggestion_index": None,
			"mode": "manual" if len(candidates) > 1 else "single",
			"scores": None,
		}

	# exactly one detection: auto-suggest it
	if len(candidates) == 1:
		return {
			"candidates": candidates,
			"suggestion_index": 0,
			"mode": "single",
			"scores": [0.0],
		}

	# multiple detections with confirmed seeds: rank by histogram match
	# build reference histogram from confirmed seeds
	ref_hists = []
	for seed in confirmed_seeds:
		if "histogram" in seed:
			# convert back to float32 ndarray if stored as Python list
			hist_val = seed["histogram"]
			if not isinstance(hist_val, numpy.ndarray):
				hist_val = numpy.array(hist_val, dtype=numpy.float32)
			elif hist_val.dtype != numpy.float32:
				hist_val = hist_val.astype(numpy.float32)
			ref_hists.append(hist_val)
	# if no stored histograms in confirmed seeds, fall back to manual mode
	if not ref_hists:
		return {
			"candidates": candidates,
			"suggestion_index": None,
			"mode": "manual",
			"scores": None,
		}

	# average reference histograms
	ref_hist = ref_hists[0]
	if len(ref_hists) > 1:
		avg_hist = numpy.zeros_like(ref_hists[0])
		for h in ref_hists:
			avg_hist += h
		avg_hist = avg_hist / len(ref_hists)
		ref_hist = avg_hist

	# ensure ref_hist is float32 for compareHist
	ref_hist = ref_hist.astype(numpy.float32)

	# compute Bhattacharyya distances from each candidate to reference
	scores = []
	for candidate in candidates:
		cand_hist = candidate["histogram"]
		# ensure candidate histogram is float32 ndarray
		if not isinstance(cand_hist, numpy.ndarray):
			cand_hist = numpy.array(cand_hist, dtype=numpy.float32)
		elif cand_hist.dtype != numpy.float32:
			cand_hist = cand_hist.astype(numpy.float32)
		distance = cv2.compareHist(
			cand_hist, ref_hist, cv2.HISTCMP_BHATTACHARYYA
		)
		scores.append(distance)

	# find best match (lowest distance)
	best_idx = int(numpy.argmin(scores))
	best_score = scores[best_idx]

	# auto-suggest if best score is good AND gap to second-best is large
	# thresholds: distance < 0.5 (strong match) and gap > 0.15
	suggestion_idx = None
	if len(candidates) > 1:
		second_best = sorted(scores)[1]
		gap = second_best - best_score
		if best_score < 0.5 and gap > 0.15:
			suggestion_idx = best_idx
	elif best_score < 0.5:
		# single candidate with good score
		suggestion_idx = best_idx

	mode_str = "auto" if suggestion_idx is not None else "manual"

	return {
		"candidates": candidates,
		"suggestion_index": suggestion_idx,
		"mode": mode_str,
		"scores": scores,
	}


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
	histogram: numpy.ndarray | None = None,
) -> dict:
	"""Build a v2 seed dict from collected fields.

	Args:
		frame_idx: Frame index (0-based).
		time_sec: Time in seconds.
		torso_box: Normalized torso box as [x, y, w, h].
		jersey_hsv: Tuple of (h, s, v) median HSV values.
		pass_number: Which collection pass this seed came from (1 = initial).
		mode: Seed collection mode string.
		histogram: Optional 2D HS histogram for color matching.

	Returns:
		Seed dict in v2 format with frame, time_s, torso_box, jersey_hsv,
		cx, cy, w, h, pass, source, mode, and optionally histogram keys.
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
		"conf": None,
		"source": "human",
		"mode": mode,
		"status": "visible",
	}
	# add histogram if provided (convert ndarray to list for JSON serialization)
	if histogram is not None:
		seed["histogram"] = histogram.tolist()
	return seed


#============================================
def _draw_trajectory_preview(
	frame: numpy.ndarray,
	predictions: dict | None,
	alpha: float = 0.15,
) -> None:
	"""Draw forward/backward trajectory prediction boxes on a frame in-place.

	Shows the interval_solver predictions as reference for the user when
	refining seeds in later passes. Boxes are drawn with transparency so
	the underlying frame content remains visible.

	Args:
		frame: BGR image to draw on (modified in place).
		predictions: Optional dict with "forward" and/or "backward" state dicts,
			each containing cx, cy, w, h keys.
		alpha: Opacity for the overlay rectangles (0.0=invisible, 1.0=opaque).
	"""
	if predictions is None:
		return
	# forward prediction
	fwd = predictions.get("forward")
	if fwd is not None:
		fwd_bgr = overlay_config.get_prediction_bgr("forward")
		cx = float(fwd["cx"])
		cy = float(fwd["cy"])
		w = float(fwd["w"])
		h = float(fwd["h"])
		x1 = int(cx - w / 2.0)
		y1 = int(cy - h / 2.0)
		x2 = int(cx + w / 2.0)
		y2 = int(cy + h / 2.0)
		# draw semi-transparent filled rectangle
		overlay = frame.copy()
		cv2.rectangle(overlay, (x1, y1), (x2, y2), fwd_bgr, -1)
		cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
		# draw thin border on top
		cv2.rectangle(frame, (x1, y1), (x2, y2), fwd_bgr, 1)
		cv2.putText(
			frame, "FWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, fwd_bgr, 1,
		)
	# backward prediction
	bwd = predictions.get("backward")
	if bwd is not None:
		bwd_bgr = overlay_config.get_prediction_bgr("backward")
		cx = float(bwd["cx"])
		cy = float(bwd["cy"])
		w = float(bwd["w"])
		h = float(bwd["h"])
		x1 = int(cx - w / 2.0)
		y1 = int(cy - h / 2.0)
		x2 = int(cx + w / 2.0)
		y2 = int(cy + h / 2.0)
		# draw semi-transparent filled rectangle
		overlay = frame.copy()
		cv2.rectangle(overlay, (x1, y1), (x2, y2), bwd_bgr, -1)
		cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
		# draw thin border on top
		cv2.rectangle(frame, (x1, y1), (x2, y2), bwd_bgr, 1)
		cv2.putText(
			frame, "BWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, bwd_bgr, 1,
		)


#============================================
def _interactive_draw_box(
	frame: numpy.ndarray,
	predictions: dict | None = None,
	box_color: tuple | None = None,
	initial_zoom: dict | None = None,
) -> list | str | None:
	"""Show a frame and let the user draw a rectangle interactively.

	Uses cv2.imshow with a mouse callback for click-drag drawing.

	Args:
		frame: BGR image to display.
		initial_zoom: Optional zoom state dict with "zoom_level", "zoom_cx",
			"zoom_cy" to restore a previous zoom level (e.g. from partial mode).
		predictions: Optional dict with "forward"/"backward" prediction
			dicts (cx, cy, w, h) for overlay display during refinement.
		box_color: BGR color tuple for the drawn rectangle (default green).

	Returns:
		Drawn box as [x, y, w, h], or "skip" if spacebar pressed,
		or "prev"/"next" if left/right arrow pressed,
		or "not_in_frame" if n pressed,
		or "partial" if p pressed,
		or averaged FWD/BWD box as [x,y,w,h] if f pressed with sufficient overlap,
		or None if ESC/q pressed to finish.
	"""
	# default box color from overlay config (preview box = user-drawn)
	if box_color is None:
		box_color = overlay_config.hex_to_bgr(overlay_config.get_preview_box_color())
	# mutable state for the mouse callback closure
	state = {
		"drawing": False,
		"x1": 0, "y1": 0,
		"x2": 0, "y2": 0,
		"done": False,
		# zoom state: z key cycles through zoom levels (0=off, 1-3=zoomed)
		"zoom_level": 0,
		"zoom_cx": 0, "zoom_cy": 0,
	}
	# restore zoom state from caller (e.g. partial mode in seed editor)
	if initial_zoom is not None:
		state["zoom_level"] = initial_zoom.get("zoom_level", 0)
		state["zoom_cx"] = initial_zoom.get("zoom_cx", 0)
		state["zoom_cy"] = initial_zoom.get("zoom_cy", 0)
	# frame dimensions for zoom crop calculation
	frame_h, frame_w = frame.shape[:2]
	# three zoom levels: 1.5x, 2.25x, 3.375x (each 1.5x the previous)
	_zoom_factors = [1.0, 1.5, 2.25, 3.375]
	# draw prediction overlays on a copy before entering the loop
	display_frame = frame.copy()
	_draw_trajectory_preview(display_frame, predictions)

	#============================================
	def _mouse_to_frame(mx: int, my: int) -> tuple:
		"""Map mouse coordinates back to original frame coordinates."""
		if state["zoom_level"] == 0:
			return (mx, my)
		# compute the crop region used for the zoomed view
		zf = _zoom_factors[state["zoom_level"]]
		crop_w = int(frame_w / zf)
		crop_h = int(frame_h / zf)
		crop_x1 = max(0, min(state["zoom_cx"] - crop_w // 2, frame_w - crop_w))
		crop_y1 = max(0, min(state["zoom_cy"] - crop_h // 2, frame_h - crop_h))
		# map display pixel to original frame pixel
		orig_x = int(crop_x1 + mx * crop_w / frame_w)
		orig_y = int(crop_y1 + my * crop_h / frame_h)
		return (orig_x, orig_y)

	# minimum and maximum area guardrails for drawn boxes
	min_box_area = 10
	max_box_area = frame_w * frame_h * 0.5

	#============================================
	def mouse_callback(event: int, x: int, y: int, flags: int, param: object) -> None:
		"""Handle mouse events for rectangle drawing."""
		if event == cv2.EVENT_LBUTTONDOWN:
			# start drawing (in frame coordinates)
			fx, fy = _mouse_to_frame(x, y)
			state["drawing"] = True
			state["x1"] = fx
			state["y1"] = fy
			state["x2"] = fx
			state["y2"] = fy
		elif event == cv2.EVENT_MOUSEMOVE and state["drawing"]:
			# update preview rectangle (in frame coordinates)
			fx, fy = _mouse_to_frame(x, y)
			state["x2"] = fx
			state["y2"] = fy
		elif event == cv2.EVENT_LBUTTONUP:
			# finish drawing (in frame coordinates)
			fx, fy = _mouse_to_frame(x, y)
			state["drawing"] = False
			state["x2"] = fx
			state["y2"] = fy
			state["done"] = True

	#============================================
	def _apply_zoom(img: numpy.ndarray) -> numpy.ndarray:
		"""Apply zoom crop and resize if zoom is active."""
		if state["zoom_level"] == 0:
			return img
		zf = _zoom_factors[state["zoom_level"]]
		crop_w = int(frame_w / zf)
		crop_h = int(frame_h / zf)
		crop_x1 = max(0, min(state["zoom_cx"] - crop_w // 2, frame_w - crop_w))
		crop_y1 = max(0, min(state["zoom_cy"] - crop_h // 2, frame_h - crop_h))
		cropped = img[crop_y1:crop_y1 + crop_h, crop_x1:crop_x1 + crop_w]
		# resize back to full display size
		zoomed_img = cv2.resize(cropped, (frame_w, frame_h))
		return zoomed_img

	#============================================
	def _frame_to_display(fx: int, fy: int) -> tuple:
		"""Map frame coordinates to display coordinates for drawing."""
		if state["zoom_level"] == 0:
			return (fx, fy)
		zf = _zoom_factors[state["zoom_level"]]
		crop_w = int(frame_w / zf)
		crop_h = int(frame_h / zf)
		crop_x1 = max(0, min(state["zoom_cx"] - crop_w // 2, frame_w - crop_w))
		crop_y1 = max(0, min(state["zoom_cy"] - crop_h // 2, frame_h - crop_h))
		dx = int((fx - crop_x1) * frame_w / crop_w)
		dy = int((fy - crop_y1) * frame_h / crop_h)
		return (dx, dy)

	# set up the window and mouse callback
	cv2.namedWindow(SEED_WINDOW_TITLE, cv2.WINDOW_NORMAL)
	cv2.setMouseCallback(SEED_WINDOW_TITLE, mouse_callback)
	while True:
		# draw instructions and current rectangle on a fresh copy
		show = display_frame.copy()
		# draw the rectangle preview while dragging (on full-frame coords)
		if state["drawing"]:
			cv2.rectangle(
				show,
				(state["x1"], state["y1"]),
				(state["x2"], state["y2"]),
				box_color, 2,
			)
		# apply zoom crop after drawing overlays
		show = _apply_zoom(show)
		# add instruction text overlays (always on display coords)
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
			"n=not in frame, p=partial, a=approx, f=FWD/BWD avg",
			(10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
			(0, 255, 255), 2,
		)
		cv2.putText(
			show,
			"z=toggle zoom",
			(10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
			(0, 255, 255), 2,
		)
		# show zoom indicator when zoomed
		if state["zoom_level"] > 0:
			zoom_label = f"ZOOM {_zoom_factors[state['zoom_level']]:.1f}x"
			cv2.putText(
				show, zoom_label,
				(frame_w - 200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
				(0, 255, 0), 2,
			)
		cv2.imshow(SEED_WINDOW_TITLE, show)
		key = cv2.waitKey(30) & 0xFF
		# ESC or q: finish collecting seeds
		if key == 27 or key == 113:
			cv2.destroyWindow(SEED_WINDOW_TITLE)
			# flush macOS event loop to dismiss the window
			for _ in range(5):
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
		# z key: cycle zoom levels (off -> 1.5x -> 2.25x -> 3.4x -> off)
		if key == 122:
			next_level = state["zoom_level"] + 1
			if next_level >= len(_zoom_factors):
				# reset to no zoom
				state["zoom_level"] = 0
			else:
				state["zoom_level"] = next_level
				# set center on first zoom level only
				if next_level == 1:
					# center on average of FWD/BWD predictions when available
					zoom_cx = frame_w // 2
					zoom_cy = frame_h // 2
					if predictions is not None:
						fwd = predictions.get("forward")
						bwd = predictions.get("backward")
						if fwd is not None and bwd is not None:
							zoom_cx = int((fwd["cx"] + bwd["cx"]) / 2.0)
							zoom_cy = int((fwd["cy"] + bwd["cy"]) / 2.0)
						elif fwd is not None:
							zoom_cx = int(fwd["cx"])
							zoom_cy = int(fwd["cy"])
						elif bwd is not None:
							zoom_cx = int(bwd["cx"])
							zoom_cy = int(bwd["cy"])
					state["zoom_cx"] = zoom_cx
					state["zoom_cy"] = zoom_cy
			continue
		# f key: auto-accept average of FWD/BWD predictions if overlap is sufficient
		if key == 102:
			if predictions is None:
				continue
			fwd = predictions.get("forward")
			bwd = predictions.get("backward")
			if fwd is None or bwd is None:
				continue
			# compute FWD and BWD boxes in pixel coordinates
			fwd_cx = float(fwd["cx"])
			fwd_cy = float(fwd["cy"])
			fwd_w = float(fwd["w"])
			fwd_h = float(fwd["h"])
			bwd_cx = float(bwd["cx"])
			bwd_cy = float(bwd["cy"])
			bwd_w = float(bwd["w"])
			bwd_h = float(bwd["h"])
			# compute intersection area
			f_x1 = fwd_cx - fwd_w / 2.0
			f_y1 = fwd_cy - fwd_h / 2.0
			f_x2 = fwd_cx + fwd_w / 2.0
			f_y2 = fwd_cy + fwd_h / 2.0
			b_x1 = bwd_cx - bwd_w / 2.0
			b_y1 = bwd_cy - bwd_h / 2.0
			b_x2 = bwd_cx + bwd_w / 2.0
			b_y2 = bwd_cy + bwd_h / 2.0
			inter_w = max(0.0, min(f_x2, b_x2) - max(f_x1, b_x1))
			inter_h = max(0.0, min(f_y2, b_y2) - max(f_y1, b_y1))
			intersection = inter_w * inter_h
			fwd_area = fwd_w * fwd_h
			bwd_area = bwd_w * bwd_h
			total = fwd_area + bwd_area
			# check overlap ratio: intersection / (FWD + BWD)
			if total <= 0 or intersection / total < 0.1:
				continue
			# compute average box and return as [x, y, w, h]
			avg_cx = (fwd_cx + bwd_cx) / 2.0
			avg_cy = (fwd_cy + bwd_cy) / 2.0
			avg_w = (fwd_w + bwd_w) / 2.0
			avg_h = (fwd_h + bwd_h) / 2.0
			avg_x = int(avg_cx - avg_w / 2.0)
			avg_y = int(avg_cy - avg_h / 2.0)
			return [avg_x, avg_y, int(avg_w), int(avg_h)]
		# n key: mark runner as not in frame
		if key == 110:
			return "not_in_frame"
		# p key: mark runner as partial (partially hidden, but position known)
		if key == 112:
			return "partial"
		# check if mouse drawing finished
		if state["done"]:
			# compute box from the two corner points (already in frame coords)
			x1 = min(state["x1"], state["x2"])
			y1 = min(state["y1"], state["y2"])
			x2 = max(state["x1"], state["x2"])
			y2 = max(state["y1"], state["y2"])
			w = x2 - x1
			h = y2 - y1
			box_area = w * h
			# reject boxes that are too small or too large
			if box_area < min_box_area or box_area > max_box_area:
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
	frame_count_override: int | None = None,
	debug: bool = False,
	save_callback: object = None,
	time_range: tuple | None = None,
	predictions: dict | None = None,
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
		frame_count_override: Optional frame count from ffprobe to use instead
			of OpenCV's CAP_PROP_FRAME_COUNT (which can be inaccurate).
		debug: Enable verbose frame-reading output.
		save_callback: Optional callable(seeds_list) invoked after each new
			seed is collected, for crash-safe incremental saving.
		time_range: Optional (start_s, end_s) tuple to limit candidate frames.
			Either value may be None for open-ended ranges.
		predictions: Optional dict mapping frame_index to prediction dicts
			with "forward"/"backward" state dicts for overlay display.

	Returns:
		List of seed dicts in v2 format (existing + newly collected).
	"""
	# headless mode: return pre-provided seeds without opening video
	if pre_provided_seeds is not None:
		return list(pre_provided_seeds)

	# start with a copy of any existing seeds
	all_seeds = list(existing_seeds) if existing_seeds else []

	# open the video file to get metadata
	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		raise RuntimeError(f"cannot open video: {video_path}")
	fps = cap.get(cv2.CAP_PROP_FPS)
	# prefer ffprobe frame count over OpenCV (which can be inaccurate)
	if frame_count_override is not None:
		total_frames = frame_count_override
	else:
		total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
	cap.release()
	if fps <= 0:
		raise RuntimeError(f"invalid fps from video: {video_path}")
	# create reliable frame reader with sequential fallback
	reader = frame_reader.FrameReader(video_path, fps, total_frames, debug=debug)

	# compute frame interval for the requested seed spacing
	frame_interval = int(round(fps * interval_seconds))
	if frame_interval < 1:
		frame_interval = 1

	# generate candidates at the requested interval
	seed_frame_indices = list(range(0, total_frames, frame_interval))
	# filter candidates by time_range if provided
	if time_range is not None:
		start_s, end_s = time_range
		start_frame = int(start_s * fps) if start_s is not None else 0
		end_frame = int(end_s * fps) if end_s is not None else total_frames
		original_count = len(seed_frame_indices)
		seed_frame_indices = [
			f for f in seed_frame_indices
			if start_frame <= f <= end_frame
		]
		filtered = original_count - len(seed_frame_indices)
		if filtered > 0:
			print(f"  time_range filter: kept {len(seed_frame_indices)} "
				f"of {original_count} candidates")
	# filter out frames that already have seeds to prevent duplicates
	if all_seeds:
		existing_frame_set = set(int(s["frame_index"]) for s in all_seeds)
		original_count = len(seed_frame_indices)
		filtered = []
		for fi in seed_frame_indices:
			if fi not in existing_frame_set:
				filtered.append(fi)
			else:
				# bump to next unused frame so user still gets a distinct frame
				bumped = fi + 1
				while bumped in existing_frame_set and bumped < total_frames:
					bumped += 1
				if bumped < total_frames and bumped not in existing_frame_set:
					filtered.append(bumped)
					# mark bumped frame as used to avoid future collisions
					existing_frame_set.add(bumped)
		seed_frame_indices = filtered
		skipped = original_count - len(seed_frame_indices)
		if skipped > 0:
			print(f"  filtered {skipped} candidates that already have seeds")
	print(f"  total_frames={total_frames}, frame_interval={frame_interval}, "
		f"candidates={len(seed_frame_indices)}")
	if all_seeds:
		print(f"  {len(all_seeds)} existing seeds, "
			f"{len(seed_frame_indices)} candidates at {interval_seconds}s interval")

	# Create QApplication if not already running
	app = QApplication.instance()
	if app is None:
		app = QApplication([])

	# Create window and controller
	window = AnnotationWindow("Track Runner - Seed Collection")
	controller = SeedController(
		seed_frame_indices=seed_frame_indices,
		reader=reader,
		fps=fps,
		config=config,
		all_seeds=all_seeds,
		save_callback=save_callback,
		pass_number=pass_number,
		mode_str="initial",
		predictions=predictions,
	)
	window.set_controller(controller)
	window.show()
	app.exec()

	reader.close()
	all_seeds = controller.get_final_seeds()
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
	debug: bool = False,
	save_callback: object = None,
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
		debug: Enable verbose frame-reading output.
		save_callback: Optional callable(seeds_list) invoked after each new
			seed is collected, for crash-safe incremental saving.

	Returns:
		List of seed dicts in v2 format (existing + newly collected).
	"""
	if not target_frames:
		return list(existing_seeds) if existing_seeds else []

	# start with a copy of any existing seeds
	all_seeds = list(existing_seeds) if existing_seeds else []

	# open the video file to get metadata
	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		raise RuntimeError(f"cannot open video: {video_path}")
	fps = cap.get(cv2.CAP_PROP_FPS)
	total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
	cap.release()
	if fps <= 0:
		raise RuntimeError(f"invalid fps from video: {video_path}")
	# create reliable frame reader with sequential fallback
	reader = frame_reader.FrameReader(video_path, fps, total_frames, debug=debug)

	sorted_targets = sorted(target_frames)
	# filter out frames that already have seeds to prevent duplicates
	if all_seeds:
		existing_frame_set = set(int(s["frame_index"]) for s in all_seeds)
		original_count = len(sorted_targets)
		sorted_targets = [fi for fi in sorted_targets if fi not in existing_frame_set]
		skipped = original_count - len(sorted_targets)
		if skipped > 0:
			print(f"  filtered {skipped} target frames that already have seeds")
	if not sorted_targets:
		# all targets already seeded, nothing to do
		reader.close()
		return all_seeds

	# Create QApplication if not already running
	app = QApplication.instance()
	if app is None:
		app = QApplication([])

	# Create window and controller
	window = AnnotationWindow("Track Runner - Target Collection", initial_mode="target")
	controller = TargetController(
		sorted_targets=sorted_targets,
		reader=reader,
		fps=fps,
		config=config,
		all_seeds=all_seeds,
		save_callback=save_callback,
		pass_number=pass_number,
		mode_str=mode,
		predictions=predictions,
	)
	window.set_controller(controller)
	window.show()
	app.exec()

	reader.close()
	all_seeds = controller.get_final_seeds()
	return all_seeds
