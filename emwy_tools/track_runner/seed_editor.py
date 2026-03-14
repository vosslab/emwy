"""Interactive seed editor for track_runner v2.

Review, fix, delete, and redraw existing seed points. Shows each seed
on its original frame with optional forward/backward prediction overlays
and lets the user navigate, delete, change status, or redraw the box.
"""

# Standard Library
# (none)

# PIP3 modules
import cv2
import numpy
from PySide6.QtWidgets import QApplication

# local repo modules
import overlay_config

# local repo modules
import common_tools.frame_reader as frame_reader
import seeding
import ui.workspace as workspace_module
import ui.edit_controller as edit_controller_module

AnnotationWindow = workspace_module.AnnotationWindow
EditController = edit_controller_module.EditController


#============================================
def _draw_seed_overlay(
	frame: numpy.ndarray,
	seed: dict,
	color: tuple | None = None,
	alpha: float = 0.4,
) -> None:
	"""Draw an existing seed box on the frame with transparency.

	For non-precise seeds (approximate/not_in_frame), draws a status
	label instead of a box.

	Args:
		frame: BGR image to draw on (modified in place).
		seed: Seed dict with cx, cy, w, h and status keys.
		color: BGR color tuple for the rectangle. Defaults to seed status color.
		alpha: Opacity for the overlay (0.0 = invisible, 1.0 = opaque).
	"""
	# default color from seed status via overlay config
	if color is None:
		status = seed.get("status", "visible")
		color = overlay_config.get_seed_status_bgr(status)
	status = seed["status"]
	if status in ("not_in_frame", "approximate", "obstructed"):
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
	cx = float(seed["cx"])
	cy = float(seed["cy"])
	sw = float(seed["w"])
	sh = float(seed["h"])
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
	# forward prediction
	fwd = frame_preds.get("forward")
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
		overlay = frame.copy()
		cv2.rectangle(overlay, (x1, y1), (x2, y2), fwd_bgr, -1)
		cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
		cv2.rectangle(frame, (x1, y1), (x2, y2), fwd_bgr, 1)
		cv2.putText(
			frame, "FWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, fwd_bgr, 1,
		)
	# backward prediction
	bwd = frame_preds.get("backward")
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
		overlay = frame.copy()
		cv2.rectangle(overlay, (x1, y1), (x2, y2), bwd_bgr, -1)
		cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
		cv2.rectangle(frame, (x1, y1), (x2, y2), bwd_bgr, 1)
		cv2.putText(
			frame, "BWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, bwd_bgr, 1,
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
	cx = float(seed["cx"])
	cy = float(seed["cy"])
	sw = float(seed["w"])
	sh = float(seed["h"])
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
	cx = float(seed["cx"])
	cy = float(seed["cy"])
	sw = float(seed["w"])
	sh = float(seed["h"])
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
	color: tuple | None = None,
	alpha: float = 0.4,
) -> None:
	"""Draw a preview bounding box on a frame with transparency.

	Args:
		frame: BGR image to draw on (modified in place).
		box: Dict with cx, cy, w, h keys.
		color: BGR color tuple. Defaults to preview box color from config.
		alpha: Opacity for the overlay.
	"""
	# default color from overlay config (preview box)
	if color is None:
		color = overlay_config.hex_to_bgr(overlay_config.get_preview_box_color())
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
def edit_seeds(
	video_path: str,
	seeds: list,
	config: dict,
	predictions: dict | None = None,
	frame_filter: set | None = None,
	seed_confidences: dict | None = None,
	debug: bool = False,
	save_callback: object = None,
	start_frame: int | None = None,
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
		save_callback: Optional callable(work_seeds) for incremental saves.
		start_frame: Optional frame index to seek the UI to on launch.

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
			if int(s["frame_index"]) in frame_filter
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

	# lazy YOLO detector for bbox polish (created on first y-key press)
	yolo_detector = [None]

	print(f"  editing {len(filtered_indices)} seeds "
		f"(of {len(work_seeds)} total)")

	# Create QApplication if not already running
	app = QApplication.instance()
	if app is None:
		app = QApplication([])

	# Create controller and window
	controller = EditController(
		work_seeds=work_seeds,
		filtered_indices=filtered_indices,
		reader=reader,
		fps=fps,
		config=config,
		save_callback=save_callback or (lambda ws: None),
		predictions=predictions,
		seed_confidences=seed_confidences,
		yolo_detector_list=yolo_detector,
		frame_filter=frame_filter,
		start_frame=start_frame,
	)
	window = AnnotationWindow("Track Runner - Seed Editor", initial_mode="edit")
	window.set_controller(controller)
	window.show()
	app.exec()

	reader.close()

	# Get final results
	edited_seeds, summary = controller.get_summary()

	# print edit summary
	print(f"  edit summary: {summary['reviewed']} reviewed, "
		f"{summary['kept']} kept, "
		f"{summary['redrawn']} redrawn, {summary['deleted']} deleted, "
		f"{summary['status_changed']} status changed")
	return (edited_seeds, summary)
