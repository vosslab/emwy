"""Edit mode controller for seed editor annotation.

Manages the workflow for reviewing, deleting, redrawn, and changing status
of existing seeds. Handles keyboard shortcuts and mouse drawing.
"""

# Standard Library
# (none)

# PIP3 modules
from PySide6.QtCore import QObject, Qt, QTimer, QThread
import numpy

# local repo modules
import ui.overlay_items as overlay_items_module
import ui.status_presenter as status_presenter_module

PreviewBoxItem = overlay_items_module.PreviewBoxItem
RectItem = overlay_items_module.RectItem
ScaleBarItem = overlay_items_module.ScaleBarItem
StatusPresenter = status_presenter_module.StatusPresenter

#============================================


class _YoloLoaderThread(QThread):
	"""Background thread for loading YOLO detector.

	Loads YOLO weights in a non-blocking thread to avoid freezing the
	event loop during initialization.
	"""

	def __init__(self, detector_list: list, config: dict) -> None:
		"""Initialize the YOLO loader thread.

		Args:
			detector_list: Mutable list [None] to store loaded detector.
			config: Configuration dict for detector creation.
		"""
		super().__init__()
		self._detector_list = detector_list
		self._config = config

	#============================================

	def run(self) -> None:
		"""Load YOLO detector in background thread."""
		import detection as detection_module
		det = detection_module.create_detector(self._config)
		self._detector_list[0] = det

#============================================


class EditController(QObject):
	"""Manages the Edit mode annotation workflow.

	Allows reviewing, filtering, deleting, and redrawing existing seeds.
	Handles keyboard shortcuts and mouse drawing for box refinement.
	"""

	def __init__(
		self,
		work_seeds: list,
		filtered_indices: list,
		reader: object,
		fps: float,
		config: dict,
		save_callback: object,
		predictions: dict | None = None,
		seed_confidences: dict | None = None,
		yolo_detector_list: list | None = None,
	) -> None:
		"""Initialize the EditController.

		Args:
			work_seeds: Mutable list of all seeds (modified in-place for edits).
			filtered_indices: List of indices into work_seeds to iterate over.
			reader: FrameReader instance with read_frame(idx) method.
			fps: Frames per second of the video.
			config: Configuration dict.
			save_callback: Callable(work_seeds) to save incremental changes.
			predictions: Optional dict mapping frame_index to prediction dicts.
			seed_confidences: Optional dict mapping frame_index to confidence dicts.
			yolo_detector_list: Optional [None] list for lazy YOLO loading (Patch 6).
		"""
		super().__init__()

		self._work_seeds = work_seeds
		self._filtered_indices = filtered_indices
		self._reader = reader
		self._fps = fps
		self._config = config
		self._save_callback = save_callback
		self._predictions = predictions
		self._seed_confidences = seed_confidences
		self._yolo_detector_list = yolo_detector_list or [None]

		# Navigation state
		self._nav_idx = 0
		self._current_frame = 0
		self._current_bgr: numpy.ndarray | None = None

		# Tracking counters
		self._reviewed = 0
		self._kept = 0
		self._redrawn = 0
		self._deleted = 0
		self._status_changed = 0
		self._changed_frames: set = set()
		self._delete_indices: set = set()

		# Window and UI state
		self._window: object = None
		self._status_presenter = StatusPresenter()
		self._scale_bar_item: object = None

		# Drawing state
		self._drawing = False
		self._drag_start: tuple | None = None
		self._drag_current: tuple | None = None
		self._preview_item: object = None
		self._partial_mode = False

		# Seed box display
		self._seed_rect_item: object = None
		self._fwd_item: object = None
		self._bwd_item: object = None

		# Polish mode state (Patch 6)
		self._polish_preview_item: object = None
		self._polish_mode: str | None = None
		self._pending_refined: dict | None = None
		self._yolo_loading: bool = False
		self._yolo_tried: bool = False
		self._yolo_thread: object = None
		self._approx_mode: bool = False

		# Session state
		self._done = False

	#============================================

	def activate(self, window: object) -> None:
		"""Activate the controller and connect to window events.

		Args:
			window: AnnotationWindow instance.
		"""
		self._window = window

		# Install event filter for keyboard and mouse events
		self._window.installEventFilter(self)
		viewport = self._window.get_frame_view().viewport()
		viewport.installEventFilter(self)

		# Add scale bar item to scene
		scene = self._window.get_frame_view().scene()
		self._scale_bar_item = ScaleBarItem()
		scene.addItem(self._scale_bar_item)

		# Add status presenter to toolbar
		toolbar_widget = self._status_presenter.get_widget()
		window.statusBar().addWidget(toolbar_widget)

		# Load and display the first frame
		self._load_current_seed()

	#============================================

	def deactivate(self) -> None:
		"""Deactivate the controller and disconnect from window events."""
		if self._window is not None:
			self._window.removeEventFilter(self)
			viewport = self._window.get_frame_view().viewport()
			viewport.removeEventFilter(self)

		# Clear overlay items
		if self._window is not None:
			scene = self._window.get_frame_view().scene()
			if self._seed_rect_item is not None:
				scene.removeItem(self._seed_rect_item)
				self._seed_rect_item = None
			if self._fwd_item is not None:
				scene.removeItem(self._fwd_item)
				self._fwd_item = None
			if self._bwd_item is not None:
				scene.removeItem(self._bwd_item)
				self._bwd_item = None
			if self._preview_item is not None:
				scene.removeItem(self._preview_item)
				self._preview_item = None
			if self._polish_preview_item is not None:
				scene.removeItem(self._polish_preview_item)
				self._polish_preview_item = None
			if self._scale_bar_item is not None:
				scene.removeItem(self._scale_bar_item)
				self._scale_bar_item = None

		# Clear status bar
		self._status_presenter.clear()

	#============================================

	def eventFilter(self, obj: object, event: object) -> bool:
		"""Handle window and viewport events.

		Args:
			obj: Object that received the event.
			event: Event instance.

		Returns:
			True if event was handled, False otherwise.
		"""
		from PySide6.QtCore import QEvent as QEventType
		from PySide6.QtGui import QMouseEvent

		if event.type() == QEventType.Type.KeyPress:
			key = event.key()
			if self.handle_key_press(key):
				return True
		elif event.type() == QEventType.Type.MouseButtonPress:
			if isinstance(event, QMouseEvent):
				pos = event.position()
				sx, sy = self._window.get_frame_view().map_to_scene(
					int(pos.x()), int(pos.y())
				)
				self.handle_mouse_press(sx, sy)
				return True
		elif event.type() == QEventType.Type.MouseMove:
			if isinstance(event, QMouseEvent):
				pos = event.position()
				sx, sy = self._window.get_frame_view().map_to_scene(
					int(pos.x()), int(pos.y())
				)
				self.handle_mouse_move(sx, sy)
				return True
		elif event.type() == QEventType.Type.MouseButtonRelease:
			if isinstance(event, QMouseEvent):
				pos = event.position()
				sx, sy = self._window.get_frame_view().map_to_scene(
					int(pos.x()), int(pos.y())
				)
				self.handle_mouse_release(sx, sy)
				return True
		elif event.type() == QEventType.Type.Wheel:
			# Update scale bar after zoom changes
			QTimer.singleShot(0, self._update_scale_bar)
			return False

		return super().eventFilter(obj, event)

	#============================================

	def _load_current_seed(self) -> None:
		"""Load and display the current seed frame."""
		if self._nav_idx >= len(self._filtered_indices):
			self._on_quit()
			return

		seed_list_idx = self._filtered_indices[self._nav_idx]
		seed = self._work_seeds[seed_list_idx]
		frame_idx = int(seed["frame_index"])

		# Read the frame
		frame = self._reader.read_frame(frame_idx)
		if frame is None:
			self._nav_idx += 1
			self._load_current_seed()
			return

		self._current_frame = frame_idx
		self._current_bgr = frame
		self._window.set_frame(frame)

		# Show existing seed box if visible or partial
		self._update_seed_rect_overlay()

		# Show FWD/BWD overlays
		self._update_fwd_bwd_overlays()

		# Update status presenter
		seed_confidence = None
		if self._seed_confidences is not None:
			seed_confidence = self._seed_confidences.get(frame_idx)
		self._status_presenter.update(
			seed, self._nav_idx, len(self._filtered_indices), seed_confidence
		)

		# Update scale bar
		self._update_scale_bar()

	#============================================

	def _update_seed_rect_overlay(self) -> None:
		"""Show the existing seed box on the frame."""
		scene = self._window.get_frame_view().scene()

		# Remove old seed rect item
		if self._seed_rect_item is not None:
			scene.removeItem(self._seed_rect_item)
			self._seed_rect_item = None

		# Get current seed
		seed_list_idx = self._filtered_indices[self._nav_idx]
		seed = self._work_seeds[seed_list_idx]
		status = seed.get("status", "unknown")

		# Only show box for visible and partial status
		if status not in ("visible", "partial"):
			return

		# Extract seed box
		cx = float(seed.get("cx", 0))
		cy = float(seed.get("cy", 0))
		w = float(seed.get("w", 0))
		h = float(seed.get("h", 0))

		x = int(cx - w / 2.0)
		y = int(cy - h / 2.0)

		# Create and add seed box overlay
		self._seed_rect_item = RectItem(
			x, y, int(w), int(h),
			color_str="#00FFFF",
			label="SEED"
		)
		scene.addItem(self._seed_rect_item)

	#============================================

	def _update_fwd_bwd_overlays(self) -> None:
		"""Update FWD/BWD prediction overlays."""
		scene = self._window.get_frame_view().scene()

		# Remove old overlays
		if self._fwd_item is not None:
			scene.removeItem(self._fwd_item)
			self._fwd_item = None
		if self._bwd_item is not None:
			scene.removeItem(self._bwd_item)
			self._bwd_item = None

		# Return early if no predictions
		if self._predictions is None:
			return

		preds = self._predictions.get(self._current_frame)
		if preds is None:
			return

		# FWD prediction
		fwd = preds.get("forward")
		if fwd is not None:
			cx = float(fwd["cx"])
			cy = float(fwd["cy"])
			w = float(fwd["w"])
			h = float(fwd["h"])
			x = int(cx - w / 2.0)
			y = int(cy - h / 2.0)
			self._fwd_item = RectItem(
				x, y, int(w), int(h),
				color_str="#FF6400",
				label="FWD"
			)
			scene.addItem(self._fwd_item)

		# BWD prediction
		bwd = preds.get("backward")
		if bwd is not None:
			cx = float(bwd["cx"])
			cy = float(bwd["cy"])
			w = float(bwd["w"])
			h = float(bwd["h"])
			x = int(cx - w / 2.0)
			y = int(cy - h / 2.0)
			self._bwd_item = RectItem(
				x, y, int(w), int(h),
				color_str="#FF00FF",
				label="BWD"
			)
			scene.addItem(self._bwd_item)

	#============================================

	def _update_scale_bar(self) -> None:
		"""Update the zoom scale bar display."""
		if self._scale_bar_item is None:
			return
		zoom = self._window.get_frame_view().get_zoom_factor()
		self._scale_bar_item.update_zoom(zoom)

	#============================================

	def handle_key_press(self, key: int) -> bool:
		"""Handle keyboard events.

		Args:
			key: Qt key code.

		Returns:
			True if event was handled.
		"""
		# Reject polish preview on any non-SPACE key
		if self._polish_mode == "pending" and key != Qt.Key.Key_Space:
			self._clear_polish_preview()
			self._update_status_presenter()

		if key == Qt.Key.Key_Escape or key == Qt.Key.Key_Q:
			self._on_quit()
			return True
		elif key == Qt.Key.Key_Space or key == Qt.Key.Key_Right:
			if self._polish_mode == "pending":
				self._on_accept_polish()
				return True
			self._on_keep()
			return True
		elif key == Qt.Key.Key_Left:
			self._on_prev()
			return True
		elif key == Qt.Key.Key_D:
			self._on_delete()
			return True
		elif key == Qt.Key.Key_N:
			self._on_status_change("not_in_frame")
			return True
		elif key == Qt.Key.Key_P:
			self._on_partial_mode()
			return True
		elif key == Qt.Key.Key_Z:
			self._on_zoom_toggle()
			return True
		elif key == Qt.Key.Key_Y:
			self._on_yolo_polish()
			return True
		elif key == Qt.Key.Key_F:
			self._on_consensus_polish()
			return True
		elif key == Qt.Key.Key_A:
			self._on_approx_toggle()
			return True

		return False

	#============================================

	def handle_mouse_press(self, scene_x: float, scene_y: float) -> None:
		"""Handle mouse button press.

		Args:
			scene_x: Scene x coordinate.
			scene_y: Scene y coordinate.
		"""
		if self._current_bgr is None:
			return

		self._drawing = True
		self._drag_start = (scene_x, scene_y)
		self._drag_current = (scene_x, scene_y)

		# Remove any old preview item
		if self._preview_item is not None:
			scene = self._window.get_frame_view().scene()
			scene.removeItem(self._preview_item)
			self._preview_item = None

	#============================================

	def handle_mouse_move(self, scene_x: float, scene_y: float) -> None:
		"""Handle mouse move.

		Args:
			scene_x: Scene x coordinate.
			scene_y: Scene y coordinate.
		"""
		if not self._drawing or self._drag_start is None:
			return

		self._drag_current = (scene_x, scene_y)

		# Update preview box
		scene = self._window.get_frame_view().scene()
		if self._preview_item is not None:
			scene.removeItem(self._preview_item)

		x1, y1 = self._drag_start
		x2, y2 = self._drag_current
		x = min(x1, x2)
		y = min(y1, y2)
		w = abs(x2 - x1)
		h = abs(y2 - y1)

		self._preview_item = PreviewBoxItem(x, y, w, h)
		scene.addItem(self._preview_item)

	#============================================

	def handle_mouse_release(self, scene_x: float, scene_y: float) -> None:
		"""Handle mouse button release.

		Args:
			scene_x: Scene x coordinate.
			scene_y: Scene y coordinate.
		"""
		if not self._drawing:
			return

		self._drawing = False

		if self._drag_start is None:
			return

		x1, y1 = self._drag_start
		x2, y2 = scene_x, scene_y

		# Normalize the box
		x = min(x1, x2)
		y = min(y1, y2)
		w = abs(x2 - x1)
		h = abs(y2 - y1)

		# Remove preview item
		scene = self._window.get_frame_view().scene()
		if self._preview_item is not None:
			scene.removeItem(self._preview_item)
			self._preview_item = None

		# Validate box size
		box_area = w * h
		frame_h, frame_w = self._current_bgr.shape[:2]
		min_area = 10
		max_area = frame_w * frame_h * 0.5

		if box_area < min_area or box_area > max_area:
			return

		box = [int(x), int(y), int(w), int(h)]
		self._on_box_drawn(box)

	#============================================

	def _on_box_drawn(self, box: list) -> None:
		"""Process a drawn box.

		Args:
			box: Box as [x, y, w, h].
		"""
		from emwy_tools.track_runner import seeding as seeding_module

		seed_list_idx = self._filtered_indices[self._nav_idx]
		seed = self._work_seeds[seed_list_idx]
		frame_idx = int(seed["frame_index"])

		if self._approx_mode:
			self._approx_mode = False
			# Build obstructed seed with position box
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			tx, ty, tw, th = norm_box
			cx = float(tx + tw / 2.0)
			cy = float(ty + th / 2.0)
			new_seed = {
				"frame_index": frame_idx,
				"frame": frame_idx,
				"time_s": seed.get("time_s", round(frame_idx / self._fps, 3)),
				"status": "obstructed",
				"torso_box": norm_box,
				"cx": cx,
				"cy": cy,
				"w": float(tw),
				"h": float(th),
				"conf": None,
				"pass": seed["pass"],
				"source": "human",
				"mode": "edit_redraw",
			}
			self._work_seeds[seed_list_idx] = new_seed
			self._redrawn += 1
			self._reviewed += 1
			self._status_changed += 1
			self._changed_frames.add(frame_idx)
			self._save_callback(self._work_seeds)
			self._advance()
			return

		if self._partial_mode:
			self._partial_mode = False
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			jersey_hsv = seeding_module.extract_jersey_color(
				self._current_bgr, norm_box
			)
			new_seed = seeding_module._build_seed_dict(
				frame_idx,
				frame_idx / self._fps,
				norm_box,
				jersey_hsv,
				seed["pass"],
				"edit_redraw",
			)
			new_seed["status"] = "partial"
			self._reviewed += 1
			self._redrawn += 1
			self._status_changed += 1
			self._changed_frames.add(frame_idx)
			self._work_seeds[seed_list_idx] = new_seed
			self._save_callback(self._work_seeds)
			self._advance()
		else:
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			jersey_hsv = seeding_module.extract_jersey_color(
				self._current_bgr, norm_box
			)
			new_seed = seeding_module._build_seed_dict(
				frame_idx,
				frame_idx / self._fps,
				norm_box,
				jersey_hsv,
				seed["pass"],
				"edit_redraw",
			)
			self._reviewed += 1
			self._redrawn += 1
			self._changed_frames.add(frame_idx)
			self._work_seeds[seed_list_idx] = new_seed
			self._save_callback(self._work_seeds)
			self._advance()

	#============================================

	def _on_keep(self) -> None:
		"""Keep seed as-is and advance."""
		self._reviewed += 1
		self._kept += 1
		self._advance()

	#============================================

	def _on_prev(self) -> None:
		"""Go back to previous seed."""
		self._nav_idx = max(0, self._nav_idx - 1)
		self._load_current_seed()

	#============================================

	def _on_delete(self) -> None:
		"""Delete the current seed."""
		seed_list_idx = self._filtered_indices[self._nav_idx]
		frame_idx = int(self._work_seeds[seed_list_idx]["frame_index"])

		self._reviewed += 1
		self._deleted += 1
		self._delete_indices.add(seed_list_idx)
		self._changed_frames.add(frame_idx)
		self._save_callback(self._work_seeds)
		self._advance()

	#============================================

	def _on_status_change(self, new_status: str) -> None:
		"""Change seed status (only not_in_frame supported).

		Args:
			new_status: New status string.
		"""
		seed_list_idx = self._filtered_indices[self._nav_idx]
		seed = self._work_seeds[seed_list_idx]
		frame_idx = int(seed["frame_index"])

		self._reviewed += 1
		self._status_changed += 1
		self._changed_frames.add(frame_idx)

		# Build new seed without torso_box
		new_seed = {
			"frame_index": seed.get("frame_index"),
			"frame": seed.get("frame"),
			"time_s": seed.get("time_s"),
			"status": new_status,
			"conf": None,
			"pass": seed["pass"],
			"source": "human",
			"mode": "edit_redraw",
		}
		self._work_seeds[seed_list_idx] = new_seed
		self._save_callback(self._work_seeds)
		self._advance()

	#============================================

	def _on_partial_mode(self) -> None:
		"""Enter partial mode for redrawing torso box."""
		self._partial_mode = True
		print("  partial mode: draw the runner's torso box")

	#============================================

	def _on_zoom_toggle(self) -> None:
		"""Toggle zoom level."""
		# Delegate to frame_view zoom; update scale bar after
		QTimer.singleShot(0, self._update_scale_bar)

	#============================================

	def _on_yolo_polish(self) -> None:
		"""Run YOLO polish on current seed and show preview."""
		if self._current_seed is None:
			return
		status = self._current_seed.get("status", "visible")
		if status in ("not_in_frame",):
			return
		# Lazily load YOLO on first press
		if self._yolo_loading:
			return
		det = self._yolo_detector_list[0] if self._yolo_detector_list else None
		if det is None and not self._yolo_tried:
			self._start_yolo_load()
			return
		if det is None:
			# Load failed
			self._status_presenter.get_widget().setText(
				"YOLO: load failed"
			)
			return
		# Run refinement
		import seed_editor as seed_editor_module
		refined = seed_editor_module._refine_box_yolo(
			self._current_bgr, self._current_seed, self._config, det,
		)
		if refined is None:
			self._status_presenter.get_widget().setText(
				"YOLO: no refinement available"
			)
			return
		# Show preview as PreviewBoxItem
		self._show_polish_preview(refined, "YOLO polish: SPACE=accept, other=reject")

	#============================================

	def _start_yolo_load(self) -> None:
		"""Start background YOLO loading in QThread."""
		self._yolo_loading = True
		self._yolo_tried = True
		status_widget = self._status_presenter.get_widget()
		status_widget.setText("Loading YOLO...")
		self._yolo_thread = _YoloLoaderThread(self._yolo_detector_list, self._config)
		self._yolo_thread.finished.connect(self._on_yolo_loaded)
		self._yolo_thread.start()

	#============================================

	def _on_yolo_loaded(self) -> None:
		"""Handle YOLO loading completion."""
		self._yolo_loading = False
		det = self._yolo_detector_list[0] if self._yolo_detector_list else None
		if det is None:
			self._status_presenter.get_widget().setText("YOLO: load failed")
		else:
			self._status_presenter.get_widget().setText("YOLO: ready - press y again")

	#============================================

	def _on_consensus_polish(self) -> None:
		"""Run FWD/BWD consensus polish and show preview."""
		if self._current_seed is None:
			return
		status = self._current_seed.get("status", "visible")
		if status in ("not_in_frame",):
			return
		import seed_editor as seed_editor_module
		frame_idx = int(self._current_seed["frame_index"])
		refined = seed_editor_module._refine_box_consensus(
			self._current_seed, self._predictions, frame_idx,
		)
		if refined is None:
			self._status_presenter.get_widget().setText(
				"FWD/BWD: no predictions available"
			)
			return
		self._show_polish_preview(refined, "FWD/BWD polish: SPACE=accept, other=reject")

	#============================================

	def _show_polish_preview(self, refined: dict, message: str) -> None:
		"""Show a polish preview box as a QGraphicsItem.

		Args:
			refined: Refined box dict with cx, cy, w, h keys.
			message: Status message to display.
		"""
		# Clear existing preview
		self._clear_polish_preview()
		# Compute box coordinates from cx, cy, w, h
		cx = float(refined["cx"])
		cy = float(refined["cy"])
		w = float(refined["w"])
		h = float(refined["h"])
		x = int(cx - w / 2.0)
		y = int(cy - h / 2.0)
		scene = self._window.get_frame_view().scene()
		self._polish_preview_item = PreviewBoxItem(x, y, int(w), int(h))
		scene.addItem(self._polish_preview_item)
		# Store refined box for accept
		self._pending_refined = refined
		self._polish_mode = "pending"
		# Update status label
		self._status_presenter.get_widget().setText(message)

	#============================================

	def _clear_polish_preview(self) -> None:
		"""Clear the polish preview item from the scene."""
		if self._polish_preview_item is not None:
			scene = self._window.get_frame_view().scene()
			scene.removeItem(self._polish_preview_item)
			self._polish_preview_item = None
		self._pending_refined = None
		self._polish_mode = None

	#============================================

	def _on_accept_polish(self) -> None:
		"""Accept the polish preview and update seed."""
		if self._pending_refined is None:
			return
		refined = self._pending_refined
		seed = self._current_seed
		frame_idx = int(seed["frame_index"])
		time_sec = seed.get("time_s", frame_idx / self._fps)
		rx = int(refined["cx"] - refined["w"] / 2.0)
		ry = int(refined["cy"] - refined["h"] / 2.0)
		polish_box = [rx, ry, int(refined["w"]), int(refined["h"])]
		import seeding as seeding_module
		norm_box = seeding_module.normalize_seed_box(polish_box, self._config)
		jersey_hsv = seeding_module.extract_jersey_color(
			self._current_bgr, norm_box
		)
		new_seed = seeding_module._build_seed_dict(
			frame_idx, time_sec, norm_box, jersey_hsv, seed["pass"],
			"bbox_polish",
		)
		seed_list_idx = self._filtered_indices[self._nav_idx]
		self._work_seeds[seed_list_idx] = new_seed
		self._redrawn += 1
		self._reviewed += 1
		self._changed_frames.add(frame_idx)
		self._save_callback(self._work_seeds)
		self._clear_polish_preview()
		self._advance()

	#============================================

	def _update_status_presenter(self) -> None:
		"""Update status presenter with current seed info."""
		if self._current_seed is None:
			return
		seed_list_idx = (
			self._filtered_indices[self._nav_idx]
			if self._nav_idx < len(self._filtered_indices) else -1
		)
		if seed_list_idx < 0:
			return
		frame_idx = int(self._current_seed["frame_index"])
		conf = None
		if self._seed_confidences is not None:
			conf = self._seed_confidences.get(frame_idx)
		self._status_presenter.update(
			self._current_seed, self._nav_idx, len(self._filtered_indices), conf,
		)

	#============================================

	def _on_approx_toggle(self) -> None:
		"""Toggle approximated obstruction mode."""
		if self._approx_mode:
			self._approx_mode = False
			self._status_presenter.get_widget().setText("Approx cancelled")
		else:
			self._approx_mode = True
			self._status_presenter.get_widget().setText(
				"Approx mode: draw the obstruction region"
			)

	#============================================

	def _advance(self) -> None:
		"""Advance to next seed."""
		self._nav_idx += 1
		if self._nav_idx >= len(self._filtered_indices):
			self._on_quit()
			return
		self._load_current_seed()

	#============================================

	def _on_quit(self) -> None:
		"""Quit the editor."""
		self._done = True
		if self._window is not None:
			self._window.close()

	#============================================

	def get_summary(self) -> tuple:
		"""Get the editing summary and final seeds list.

		Returns:
			Tuple of (final_seeds, summary_dict) where final_seeds is the
			work_seeds list with deleted indices removed, and summary_dict
			contains counts and metadata.
		"""
		# Remove deleted seeds
		final_seeds = [
			s for i, s in enumerate(self._work_seeds)
			if i not in self._delete_indices
		]

		summary = {
			"reviewed": self._reviewed,
			"kept": self._kept,
			"redrawn": self._redrawn,
			"deleted": self._deleted,
			"status_changed": self._status_changed,
			"changed_frames": self._changed_frames,
		}

		return (final_seeds, summary)
