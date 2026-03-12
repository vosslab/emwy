"""Interactive seed editor for track_runner v2.

Review, fix, delete, and redraw existing seed points. Shows each seed
on its original frame with optional forward/backward prediction overlays
and lets the user navigate, delete, change status, or redraw the box.
"""

# PIP3 modules
import cv2
import numpy

# local repo modules
import detection
import frame_reader
import seeding

# window title for the interactive seed editor UI
EDIT_WINDOW_TITLE = "Track Runner - Seed Editor"


#============================================
def _draw_seed_overlay(
	frame: numpy.ndarray,
	seed: dict,
	color: tuple = (255, 255, 0),
	alpha: float = 0.4,
) -> None:
	"""Draw an existing seed box on the frame with transparency.

	For absence seeds (not_in_frame/obstructed), draws a status label
	instead of a box.

	Args:
		frame: BGR image to draw on (modified in place).
		seed: Seed dict with cx, cy, w, h and status keys.
		color: BGR color tuple for the rectangle (default cyan).
		alpha: Opacity for the overlay (0.0 = invisible, 1.0 = opaque).
	"""
	status = seed.get("status", "visible")
	if status in ("not_in_frame", "obstructed"):
		# draw status label in the center of the frame
		h, w = frame.shape[:2]
		label = f"[{status}]"
		cv2.putText(
			frame, label,
			(w // 2 - 100, h // 2),
			cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2,
		)
		return
	# draw the seed box as a filled rectangle with transparency
	cx = float(seed.get("cx", 0))
	cy = float(seed.get("cy", 0))
	sw = float(seed.get("w", 0))
	sh = float(seed.get("h", 0))
	x1 = int(cx - sw / 2.0)
	y1 = int(cy - sh / 2.0)
	x2 = int(cx + sw / 2.0)
	y2 = int(cy + sh / 2.0)
	# draw semi-transparent filled rectangle
	overlay = frame.copy()
	cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
	cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
	# draw solid border on top
	cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)


#============================================
def _draw_predictions_overlay(
	frame: numpy.ndarray,
	predictions: dict | None,
	frame_idx: int,
	alpha: float = 0.15,
) -> None:
	"""Draw forward/backward prediction boxes with transparency.

	Args:
		frame: BGR image to draw on (modified in place).
		predictions: Optional dict mapping frame_index to prediction dicts.
		frame_idx: Current frame index to look up.
		alpha: Opacity for the overlay rectangles.
	"""
	if predictions is None:
		return
	frame_preds = predictions.get(frame_idx)
	if frame_preds is None:
		return
	# forward prediction in blue
	fwd = frame_preds.get("forward")
	if fwd is not None:
		cx = float(fwd.get("cx", 0))
		cy = float(fwd.get("cy", 0))
		w = float(fwd.get("w", 0))
		h = float(fwd.get("h", 0))
		x1 = int(cx - w / 2.0)
		y1 = int(cy - h / 2.0)
		x2 = int(cx + w / 2.0)
		y2 = int(cy + h / 2.0)
		overlay = frame.copy()
		cv2.rectangle(overlay, (x1, y1), (x2, y2), (255, 100, 0), -1)
		cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
		cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 100, 0), 1)
		cv2.putText(
			frame, "FWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 100, 0), 1,
		)
	# backward prediction in magenta
	bwd = frame_preds.get("backward")
	if bwd is not None:
		cx = float(bwd.get("cx", 0))
		cy = float(bwd.get("cy", 0))
		w = float(bwd.get("w", 0))
		h = float(bwd.get("h", 0))
		x1 = int(cx - w / 2.0)
		y1 = int(cy - h / 2.0)
		x2 = int(cx + w / 2.0)
		y2 = int(cy + h / 2.0)
		overlay = frame.copy()
		cv2.rectangle(overlay, (x1, y1), (x2, y2), (255, 0, 255), -1)
		cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
		cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 1)
		cv2.putText(
			frame, "BWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 255), 1,
		)


#============================================
def _refine_box_yolo(
	frame: numpy.ndarray,
	seed: dict,
	config: dict,
	detector: object,
) -> dict | None:
	"""Refine a seed box using YOLO detection in the local region.

	Runs YOLO on an ROI around the seed center and picks the best
	detection that passes guardrails (center shift, area change, Dice).

	Args:
		frame: BGR image of the seed's frame.
		seed: Seed dict with cx, cy, w, h keys.
		config: Configuration dict.
		detector: YoloDetector instance.

	Returns:
		Refined seed box dict with cx, cy, w, h keys, or None if no
		valid detection passes guardrails.
	"""
	cx = float(seed.get("cx", 0))
	cy = float(seed.get("cy", 0))
	sw = float(seed.get("w", 0))
	sh = float(seed.get("h", 0))
	seed_area = sw * sh
	if seed_area <= 0:
		return None
	# run YOLO on the ROI around the seed center
	detections = detector.detect_roi(
		frame, (cx, cy), (sw, sh),
	)
	if not detections:
		return None
	# evaluate each detection against guardrails
	best_score = -1.0
	best_det_box = None
	for det in detections:
		bbox = det["bbox"]
		# convert top-left [x,y,w,h] to center format
		det_cx = bbox[0] + bbox[2] / 2.0
		det_cy = bbox[1] + bbox[3] / 2.0
		det_w = float(bbox[2])
		det_h = float(bbox[3])
		det_area = det_w * det_h
		# guardrail: center shift must be < 20% of seed box height
		center_dist = numpy.sqrt((det_cx - cx) ** 2 + (det_cy - cy) ** 2)
		if center_dist > 0.2 * sh:
			continue
		# guardrail: area change must be < 30% of seed box area
		if abs(det_area - seed_area) > 0.3 * seed_area:
			continue
		# guardrail: Dice overlap must be >= 0.5
		# compute Dice coefficient inline
		a_x1 = cx - sw / 2.0
		a_y1 = cy - sh / 2.0
		a_x2 = cx + sw / 2.0
		a_y2 = cy + sh / 2.0
		b_x1 = det_cx - det_w / 2.0
		b_y1 = det_cy - det_h / 2.0
		b_x2 = det_cx + det_w / 2.0
		b_y2 = det_cy + det_h / 2.0
		inter_w = max(0.0, min(a_x2, b_x2) - max(a_x1, b_x1))
		inter_h = max(0.0, min(a_y2, b_y2) - max(a_y1, b_y1))
		intersection = inter_w * inter_h
		total = seed_area + det_area
		dice = 2.0 * intersection / total if total > 0 else 0.0
		if dice < 0.5:
			continue
		# score: confidence * dice
		conf = float(det.get("confidence", 0.5))
		combined = conf * dice
		if combined > best_score:
			best_score = combined
			best_det_box = {"cx": det_cx, "cy": det_cy, "w": det_w, "h": det_h}
	if best_det_box is None:
		return None
	# blend: 70% seed + 30% detection
	refined = {
		"cx": 0.7 * cx + 0.3 * best_det_box["cx"],
		"cy": 0.7 * cy + 0.3 * best_det_box["cy"],
		"w": 0.7 * sw + 0.3 * best_det_box["w"],
		"h": 0.7 * sh + 0.3 * best_det_box["h"],
	}
	# normalize via seeding utility
	box_list = [
		int(refined["cx"] - refined["w"] / 2.0),
		int(refined["cy"] - refined["h"] / 2.0),
		int(refined["w"]),
		int(refined["h"]),
	]
	norm = seeding.normalize_seed_box(box_list, config)
	result = {
		"cx": norm[0] + norm[2] / 2.0,
		"cy": norm[1] + norm[3] / 2.0,
		"w": float(norm[2]),
		"h": float(norm[3]),
	}
	return result


#============================================
def _refine_box_consensus(
	seed: dict,
	predictions: dict | None,
	frame_idx: int,
) -> dict | None:
	"""Refine a seed box using forward/backward prediction consensus.

	Blends the seed with available FWD and BWD predictions at the
	same frame index.

	Args:
		seed: Seed dict with cx, cy, w, h keys.
		predictions: Dict mapping frame_index to prediction dicts with
			'forward' and 'backward' keys.
		frame_idx: Frame index to look up predictions for.

	Returns:
		Refined box dict with cx, cy, w, h keys, or None if no
		predictions are available.
	"""
	if predictions is None:
		return None
	frame_preds = predictions.get(frame_idx)
	if frame_preds is None:
		return None
	cx = float(seed.get("cx", 0))
	cy = float(seed.get("cy", 0))
	sw = float(seed.get("w", 0))
	sh = float(seed.get("h", 0))
	fwd = frame_preds.get("forward")
	bwd = frame_preds.get("backward")
	if fwd is not None and bwd is not None:
		# both available: 60% seed + 20% fwd + 20% bwd
		refined = {
			"cx": 0.6 * cx + 0.2 * float(fwd["cx"]) + 0.2 * float(bwd["cx"]),
			"cy": 0.6 * cy + 0.2 * float(fwd["cy"]) + 0.2 * float(bwd["cy"]),
			"w": 0.6 * sw + 0.2 * float(fwd["w"]) + 0.2 * float(bwd["w"]),
			"h": 0.6 * sh + 0.2 * float(fwd["h"]) + 0.2 * float(bwd["h"]),
		}
	elif fwd is not None:
		# only forward: 70% seed + 30% fwd
		refined = {
			"cx": 0.7 * cx + 0.3 * float(fwd["cx"]),
			"cy": 0.7 * cy + 0.3 * float(fwd["cy"]),
			"w": 0.7 * sw + 0.3 * float(fwd["w"]),
			"h": 0.7 * sh + 0.3 * float(fwd["h"]),
		}
	elif bwd is not None:
		# only backward: 70% seed + 30% bwd
		refined = {
			"cx": 0.7 * cx + 0.3 * float(bwd["cx"]),
			"cy": 0.7 * cy + 0.3 * float(bwd["cy"]),
			"w": 0.7 * sw + 0.3 * float(bwd["w"]),
			"h": 0.7 * sh + 0.3 * float(bwd["h"]),
		}
	else:
		return None
	return refined


#============================================
def _draw_preview_box(
	frame: numpy.ndarray,
	box: dict,
	color: tuple = (0, 255, 0),
	alpha: float = 0.4,
) -> None:
	"""Draw a preview bounding box on a frame with transparency.

	Args:
		frame: BGR image to draw on (modified in place).
		box: Dict with cx, cy, w, h keys.
		color: BGR color tuple (default green).
		alpha: Opacity for the overlay.
	"""
	cx = float(box["cx"])
	cy = float(box["cy"])
	bw = float(box["w"])
	bh = float(box["h"])
	x1 = int(cx - bw / 2.0)
	y1 = int(cy - bh / 2.0)
	x2 = int(cx + bw / 2.0)
	y2 = int(cy + bh / 2.0)
	overlay = frame.copy()
	cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
	cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
	cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)


#============================================
def _interactive_edit_seed(
	frame: numpy.ndarray,
	seed: dict,
	seed_index: int,
	total_seeds: int,
	predictions: dict | None = None,
	seed_confidence: dict | None = None,
	config: dict | None = None,
	detector: object | None = None,
) -> str | list | None:
	"""Core UI loop for editing one seed.

	Shows the frame with the existing seed box in cyan, optional FWD/BWD
	prediction boxes, status bar, and instruction text.

	Args:
		frame: BGR image of the seed's frame.
		seed: Current seed dict.
		seed_index: 0-based index of this seed in the list.
		total_seeds: Total number of seeds being reviewed.
		predictions: Optional prediction dict for overlay display.

	Returns:
		"keep": keep seed as-is, advance to next
		"prev": go back to previous seed
		"delete": remove this seed
		"not_in_frame": change status to not_in_frame
		"obstructed": change status to obstructed
		"partial": change status to partial (then redraw)
		list [x,y,w,h]: redraw with new box
		None: quit/save and exit
	"""
	# prepare display frame with overlays
	display = frame.copy()
	frame_idx = int(seed.get("frame_index", 0))
	status = seed.get("status", "visible")
	time_s = seed.get("time_s", frame_idx / 30.0)

	# draw prediction overlays first (behind seed box)
	_draw_predictions_overlay(display, predictions, frame_idx)
	# choose color based on seed status: gold for partial, cyan for visible
	if status == "partial":
		seed_color = (0, 200, 220)
	else:
		seed_color = (255, 255, 0)
	_draw_seed_overlay(display, seed, color=seed_color)

	# mutable state for mouse drawing (redraw mode)
	draw_state = {
		"drawing": False,
		"x1": 0, "y1": 0,
		"x2": 0, "y2": 0,
		"done": False,
		# zoom state: z key toggles 1.5x zoom centered on frame
		"zoomed": False,
		"zoom_cx": 0, "zoom_cy": 0,
	}
	# frame dimensions for zoom crop calculation
	ed_frame_h, ed_frame_w = frame.shape[:2]
	zoom_factor = 1.5
	# minimum and maximum area guardrails for drawn boxes
	min_box_area = 10
	max_box_area = ed_frame_w * ed_frame_h * 0.5

	#============================================
	def _mouse_to_frame(mx: int, my: int) -> tuple:
		"""Map mouse coordinates back to original frame coordinates."""
		if not draw_state["zoomed"]:
			return (mx, my)
		crop_w = int(ed_frame_w / zoom_factor)
		crop_h = int(ed_frame_h / zoom_factor)
		crop_x1 = max(0, min(draw_state["zoom_cx"] - crop_w // 2, ed_frame_w - crop_w))
		crop_y1 = max(0, min(draw_state["zoom_cy"] - crop_h // 2, ed_frame_h - crop_h))
		orig_x = int(crop_x1 + mx * crop_w / ed_frame_w)
		orig_y = int(crop_y1 + my * crop_h / ed_frame_h)
		return (orig_x, orig_y)

	#============================================
	def _apply_zoom(img: numpy.ndarray) -> numpy.ndarray:
		"""Apply zoom crop and resize if zoom is active."""
		if not draw_state["zoomed"]:
			return img
		crop_w = int(ed_frame_w / zoom_factor)
		crop_h = int(ed_frame_h / zoom_factor)
		crop_x1 = max(0, min(draw_state["zoom_cx"] - crop_w // 2, ed_frame_w - crop_w))
		crop_y1 = max(0, min(draw_state["zoom_cy"] - crop_h // 2, ed_frame_h - crop_h))
		cropped = img[crop_y1:crop_y1 + crop_h, crop_x1:crop_x1 + crop_w]
		zoomed_img = cv2.resize(cropped, (ed_frame_w, ed_frame_h))
		return zoomed_img

	#============================================
	def mouse_callback(event: int, x: int, y: int, flags: int, param: object) -> None:
		"""Handle mouse events for rectangle drawing."""
		if event == cv2.EVENT_LBUTTONDOWN:
			fx, fy = _mouse_to_frame(x, y)
			draw_state["drawing"] = True
			draw_state["x1"] = fx
			draw_state["y1"] = fy
			draw_state["x2"] = fx
			draw_state["y2"] = fy
		elif event == cv2.EVENT_MOUSEMOVE and draw_state["drawing"]:
			fx, fy = _mouse_to_frame(x, y)
			draw_state["x2"] = fx
			draw_state["y2"] = fy
		elif event == cv2.EVENT_LBUTTONUP:
			fx, fy = _mouse_to_frame(x, y)
			draw_state["drawing"] = False
			draw_state["x2"] = fx
			draw_state["y2"] = fy
			draw_state["done"] = True

	cv2.namedWindow(EDIT_WINDOW_TITLE, cv2.WINDOW_NORMAL)
	cv2.setMouseCallback(EDIT_WINDOW_TITLE, mouse_callback)

	while True:
		show = display.copy()
		# draw the redraw rectangle preview while dragging (in frame coords)
		if draw_state["drawing"]:
			cv2.rectangle(
				show,
				(draw_state["x1"], draw_state["y1"]),
				(draw_state["x2"], draw_state["y2"]),
				(0, 255, 0), 2,
			)
		# apply zoom crop after drawing overlays on full-frame image
		show = _apply_zoom(show)
		# draw status bar at the top (on display coords)
		status_text = (
			f"Seed {seed_index + 1}/{total_seeds} | "
			f"frame {frame_idx} | {time_s:.1f}s | {status}"
		)
		# append confidence score if available
		if seed_confidence is not None:
			conf_score = seed_confidence.get("score", 0.0)
			conf_label = seed_confidence.get("label", "unknown")
			status_text += f" | conf: {conf_score:.2f} ({conf_label})"
		cv2.putText(
			show, status_text,
			(10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
			(0, 255, 255), 2,
		)
		# draw instruction text
		cv2.putText(
			show,
			"SPACE/RIGHT=keep, LEFT=prev, d=delete, draw=redraw",
			(10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
			(0, 255, 255), 2,
		)
		cv2.putText(
			show,
			"n=not_in_frame, o=obstructed, p=partial, y=YOLO, f=FWD/BWD",
			(10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
			(0, 255, 255), 2,
		)
		cv2.putText(
			show,
			"z=toggle zoom, ESC/q=save+exit",
			(10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
			(0, 255, 255), 2,
		)
		# show zoom indicator when zoomed
		if draw_state["zoomed"]:
			cv2.putText(
				show, "ZOOM 1.5x",
				(ed_frame_w - 200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
				(0, 255, 0), 2,
			)
		cv2.imshow(EDIT_WINDOW_TITLE, show)
		key = cv2.waitKey(30) & 0xFF
		# ESC or q: save and exit
		if key == 27 or key == 113:
			return None
		# SPACE or right arrow: keep, next seed
		if key == 32 or key == 83 or key == 3:
			return "keep"
		# left arrow: previous seed
		if key == 81 or key == 2:
			return "prev"
		# z key: toggle zoom on/off at center of frame
		if key == 122:
			if draw_state["zoomed"]:
				draw_state["zoomed"] = False
			else:
				draw_state["zoomed"] = True
				draw_state["zoom_cx"] = ed_frame_w // 2
				draw_state["zoom_cy"] = ed_frame_h // 2
			continue
		# d key: delete seed
		if key == 100:
			return "delete"
		# n key: change status to not_in_frame
		if key == 110:
			return "not_in_frame"
		# o key: change status to obstructed
		if key == 111:
			return "obstructed"
		# p key: change status to partial
		if key == 112:
			return "partial"
		# y key: YOLO-based bbox polish with preview
		if key == 121:
			if status in ("not_in_frame", "obstructed"):
				continue
			# lazily create YOLO detector on first y-key press
			if isinstance(detector, list) and detector[0] is None:
				print("  loading YOLO detector for bbox polish...")
				detector[0] = detection.create_detector(config or {})
			# resolve detector from lazy list or direct reference
			det = detector[0] if isinstance(detector, list) else detector
			if det is None:
				continue
			refined = _refine_box_yolo(frame, seed, config or {}, det)
			if refined is None:
				# flash "no refinement available" briefly
				tmp = display.copy()
				cv2.putText(
					tmp, "No YOLO refinement available",
					(10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
					(0, 0, 255), 2,
				)
				cv2.imshow(EDIT_WINDOW_TITLE, tmp)
				cv2.waitKey(800)
				continue
			# show preview: green refined box alongside original
			preview = display.copy()
			_draw_preview_box(preview, refined, color=(0, 255, 0))
			cv2.putText(
				preview, "YOLO polish: SPACE=accept, other=reject",
				(10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
				(0, 255, 0), 2,
			)
			cv2.imshow(EDIT_WINDOW_TITLE, preview)
			accept_key = cv2.waitKey(0) & 0xFF
			if accept_key == 32:
				# return as polish tuple for caller to set bbox_polish mode
				rx = int(refined["cx"] - refined["w"] / 2.0)
				ry = int(refined["cy"] - refined["h"] / 2.0)
				return ("bbox_polish", [rx, ry, int(refined["w"]), int(refined["h"])])
			continue
		# f key: FWD/BWD consensus bbox polish with preview
		if key == 102:
			if status in ("not_in_frame", "obstructed"):
				continue
			refined = _refine_box_consensus(seed, predictions, frame_idx)
			if refined is None:
				# flash "no refinement available" briefly
				tmp = display.copy()
				cv2.putText(
					tmp, "No FWD/BWD predictions available",
					(10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
					(0, 0, 255), 2,
				)
				cv2.imshow(EDIT_WINDOW_TITLE, tmp)
				cv2.waitKey(800)
				continue
			# show preview: green refined box alongside original
			preview = display.copy()
			_draw_preview_box(preview, refined, color=(0, 255, 0))
			cv2.putText(
				preview, "FWD/BWD polish: SPACE=accept, other=reject",
				(10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
				(0, 255, 0), 2,
			)
			cv2.imshow(EDIT_WINDOW_TITLE, preview)
			accept_key = cv2.waitKey(0) & 0xFF
			if accept_key == 32:
				rx = int(refined["cx"] - refined["w"] / 2.0)
				ry = int(refined["cy"] - refined["h"] / 2.0)
				return ("bbox_polish", [rx, ry, int(refined["w"]), int(refined["h"])])
			continue
		# check if mouse drawing finished (redraw)
		if draw_state["done"]:
			x1 = min(draw_state["x1"], draw_state["x2"])
			y1 = min(draw_state["y1"], draw_state["y2"])
			x2 = max(draw_state["x1"], draw_state["x2"])
			y2 = max(draw_state["y1"], draw_state["y2"])
			w = x2 - x1
			h = y2 - y1
			box_area = w * h
			# reject boxes that are too small or too large
			if box_area < min_box_area or box_area > max_box_area:
				draw_state["done"] = False
				continue
			return [x1, y1, w, h]


#============================================
def edit_seeds(
	video_path: str,
	seeds: list,
	config: dict,
	predictions: dict | None = None,
	frame_filter: set | None = None,
	seed_confidences: dict | None = None,
	debug: bool = False,
) -> tuple:
	"""Main loop for reviewing and editing seeds interactively.

	Navigates through seeds, showing each on its original frame.
	The user can keep, delete, change status, or redraw each seed.

	Args:
		video_path: Path to the input video file.
		seeds: List of seed dicts to review (will not be mutated).
		config: Configuration dict.
		predictions: Optional dict mapping frame_index to prediction dicts.
		frame_filter: Optional set of frame indices to show (filters to only
			seeds at these frames). If None, shows all seeds.
		seed_confidences: Optional dict mapping frame_index to confidence
			dicts with 'score' and 'label' keys.
		debug: Enable verbose output.

	Returns:
		Tuple of (edited_seeds, summary) where edited_seeds is the cleaned
		list and summary is a dict with counts of actions taken.
	"""
	# work on a copy of the seeds list
	work_seeds = list(seeds)

	# apply frame filter if provided
	if frame_filter is not None:
		filtered_indices = [
			i for i, s in enumerate(work_seeds)
			if int(s.get("frame_index", -1)) in frame_filter
		]
		if not filtered_indices:
			print("  no seeds match the frame filter")
			summary = {
				"reviewed": 0, "kept": 0, "redrawn": 0,
				"deleted": 0, "status_changed": 0,
				"changed_frames": set(),
			}
			return (list(seeds), summary)
	else:
		filtered_indices = list(range(len(work_seeds)))

	# open the video to get metadata
	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		raise RuntimeError(f"cannot open video: {video_path}")
	fps = cap.get(cv2.CAP_PROP_FPS)
	total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
	cap.release()
	if fps <= 0:
		raise RuntimeError(f"invalid fps from video: {video_path}")
	# create reliable frame reader
	reader = frame_reader.FrameReader(video_path, fps, total_frames, debug=debug)

	# tracking counters
	reviewed = 0
	kept = 0
	redrawn = 0
	deleted = 0
	status_changed = 0
	# set of indices in work_seeds to delete at the end
	delete_indices = set()
	# frame indices that were modified (for selective interval invalidation)
	changed_frames = set()

	# lazy YOLO detector for bbox polish (created on first y-key press)
	yolo_detector = [None]

	print(f"  editing {len(filtered_indices)} seeds "
		f"(of {len(work_seeds)} total)")

	nav_idx = 0
	while 0 <= nav_idx < len(filtered_indices):
		seed_list_idx = filtered_indices[nav_idx]
		seed = work_seeds[seed_list_idx]
		frame_idx = int(seed.get("frame_index", 0))

		# read the frame
		frame = reader.read_frame(frame_idx)
		if frame is None:
			print(f"  warning: cannot read frame {frame_idx}, skipping")
			nav_idx += 1
			continue

		# look up confidence for this seed's frame
		frame_confidence = None
		if seed_confidences is not None:
			frame_confidence = seed_confidences.get(frame_idx)

		reviewed += 1
		result = _interactive_edit_seed(
			frame, seed, nav_idx, len(filtered_indices),
			predictions=predictions,
			seed_confidence=frame_confidence,
			config=config,
			detector=yolo_detector,
		)

		if result is None:
			# user pressed ESC/q to save and exit
			print(f"  user quit at seed {nav_idx + 1}/{len(filtered_indices)}")
			break
		if result == "keep":
			kept += 1
			nav_idx += 1
			continue
		if result == "prev":
			nav_idx = max(0, nav_idx - 1)
			continue
		if result == "delete":
			deleted += 1
			delete_indices.add(seed_list_idx)
			changed_frames.add(frame_idx)
			nav_idx += 1
			continue
		if result in ("not_in_frame", "obstructed"):
			status_changed += 1
			changed_frames.add(frame_idx)
			# change status and remove position data for absence statuses
			work_seeds[seed_list_idx] = {
				"frame_index": seed.get("frame_index"),
				"frame": seed.get("frame"),
				"time_s": seed.get("time_s"),
				"status": result,
				"pass": seed.get("pass", 1),
				"source": "human",
				"mode": "edit_redraw",
			}
			nav_idx += 1
			continue
		if result == "partial":
			# partial mode: re-show frame for redraw with gold box color
			print("  partial mode: draw the runner's torso box (press p to cancel)")
			partial_box = seeding._interactive_draw_box(
				frame, box_color=(0, 200, 220),
			)
			if partial_box == "partial":
				print("  partial mode cancelled")
				continue
			if isinstance(partial_box, list):
				status_changed += 1
				redrawn += 1
				changed_frames.add(frame_idx)
				time_sec = seed.get("time_s", frame_idx / fps)
				norm_box = seeding.normalize_seed_box(partial_box, config)
				jersey_hsv = seeding.extract_jersey_color(frame, norm_box)
				new_seed = seeding._build_seed_dict(
					frame_idx, time_sec, norm_box, jersey_hsv,
					seed.get("pass", 1), "edit_redraw",
				)
				new_seed["status"] = "partial"
				work_seeds[seed_list_idx] = new_seed
			nav_idx += 1
			continue
		if isinstance(result, tuple) and len(result) == 2 and result[0] == "bbox_polish":
			# user accepted a YOLO or FWD/BWD polish
			redrawn += 1
			changed_frames.add(frame_idx)
			polish_box = result[1]
			time_sec = seed.get("time_s", frame_idx / fps)
			norm_box = seeding.normalize_seed_box(polish_box, config)
			jersey_hsv = seeding.extract_jersey_color(frame, norm_box)
			new_seed = seeding._build_seed_dict(
				frame_idx, time_sec, norm_box, jersey_hsv,
				seed.get("pass", 1), "bbox_polish",
			)
			work_seeds[seed_list_idx] = new_seed
			nav_idx += 1
			continue
		if isinstance(result, list):
			# user drew a new box (redraw)
			redrawn += 1
			changed_frames.add(frame_idx)
			time_sec = seed.get("time_s", frame_idx / fps)
			norm_box = seeding.normalize_seed_box(result, config)
			jersey_hsv = seeding.extract_jersey_color(frame, norm_box)
			new_seed = seeding._build_seed_dict(
				frame_idx, time_sec, norm_box, jersey_hsv,
				seed.get("pass", 1), "edit_redraw",
			)
			work_seeds[seed_list_idx] = new_seed
			nav_idx += 1
			continue

	reader.close()
	cv2.destroyAllWindows()
	# flush macOS event loop to dismiss window
	for _ in range(5):
		cv2.waitKey(1)

	# remove deleted seeds (iterate in reverse to preserve indices)
	if delete_indices:
		edited_seeds = [
			s for i, s in enumerate(work_seeds)
			if i not in delete_indices
		]
	else:
		edited_seeds = work_seeds

	summary = {
		"reviewed": reviewed,
		"kept": kept,
		"redrawn": redrawn,
		"deleted": deleted,
		"status_changed": status_changed,
		"changed_frames": changed_frames,
	}
	# print edit summary
	print(f"  edit summary: {reviewed} reviewed, {kept} kept, "
		f"{redrawn} redrawn, {deleted} deleted, "
		f"{status_changed} status changed")
	return (edited_seeds, summary)
