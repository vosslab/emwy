"""Interactive seed editor for track_runner v2.

Review, fix, delete, and redraw existing seed points. Shows each seed
on its original frame with optional forward/backward prediction overlays
and lets the user navigate, delete, change status, or redraw the box.
"""

# PIP3 modules
import cv2
import numpy

# local repo modules
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
	alpha: float = 0.4,
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
		cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 100, 0), 2)
		cv2.putText(
			frame, "FWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 100, 0), 1,
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
		cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 255), 2)
		cv2.putText(
			frame, "BWD",
			(x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1,
		)


#============================================
def _interactive_edit_seed(
	frame: numpy.ndarray,
	seed: dict,
	seed_index: int,
	total_seeds: int,
	predictions: dict | None = None,
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
	# draw the current seed box in cyan
	_draw_seed_overlay(display, seed, color=(255, 255, 0))

	# mutable state for mouse drawing (redraw mode)
	draw_state = {
		"drawing": False,
		"x1": 0, "y1": 0,
		"x2": 0, "y2": 0,
		"done": False,
	}

	#============================================
	def mouse_callback(event: int, x: int, y: int, flags: int, param: object) -> None:
		"""Handle mouse events for rectangle drawing."""
		if event == cv2.EVENT_LBUTTONDOWN:
			draw_state["drawing"] = True
			draw_state["x1"] = x
			draw_state["y1"] = y
			draw_state["x2"] = x
			draw_state["y2"] = y
		elif event == cv2.EVENT_MOUSEMOVE and draw_state["drawing"]:
			draw_state["x2"] = x
			draw_state["y2"] = y
		elif event == cv2.EVENT_LBUTTONUP:
			draw_state["drawing"] = False
			draw_state["x2"] = x
			draw_state["y2"] = y
			draw_state["done"] = True

	cv2.namedWindow(EDIT_WINDOW_TITLE, cv2.WINDOW_NORMAL)
	cv2.setMouseCallback(EDIT_WINDOW_TITLE, mouse_callback)

	while True:
		show = display.copy()
		# draw status bar at the top
		status_text = (
			f"Seed {seed_index + 1}/{total_seeds} | "
			f"frame {frame_idx} | {time_s:.1f}s | {status}"
		)
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
			"n=not_in_frame, o=obstructed, p=partial, ESC/q=save+exit",
			(10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
			(0, 255, 255), 2,
		)
		# draw the redraw rectangle preview while dragging
		if draw_state["drawing"]:
			cv2.rectangle(
				show,
				(draw_state["x1"], draw_state["y1"]),
				(draw_state["x2"], draw_state["y2"]),
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
		# check if mouse drawing finished (redraw)
		if draw_state["done"]:
			x1 = min(draw_state["x1"], draw_state["x2"])
			y1 = min(draw_state["y1"], draw_state["y2"])
			x2 = max(draw_state["x1"], draw_state["x2"])
			y2 = max(draw_state["y1"], draw_state["y2"])
			w = x2 - x1
			h = y2 - y1
			# ignore tiny accidental clicks
			if w < 5 or h < 5:
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

		reviewed += 1
		result = _interactive_edit_seed(
			frame, seed, nav_idx, len(filtered_indices),
			predictions=predictions,
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
			nav_idx += 1
			continue
		if result in ("not_in_frame", "obstructed"):
			status_changed += 1
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
		if isinstance(result, list):
			# user drew a new box (redraw)
			redrawn += 1
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
	}
	# print edit summary
	print(f"  edit summary: {reviewed} reviewed, {kept} kept, "
		f"{redrawn} redrawn, {deleted} deleted, "
		f"{status_changed} status changed")
	return (edited_seeds, summary)
