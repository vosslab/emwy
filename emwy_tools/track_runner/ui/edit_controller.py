"""Edit mode controller for seed editor annotation.

Manages the workflow for reviewing, deleting, redrawn, and changing status
of existing seeds. Handles keyboard shortcuts and mouse drawing.
"""

# Standard Library
# (none)

# PIP3 modules
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QPushButton

# local repo modules
import overlay_config
import ui.overlay_items as overlay_items_module
import ui.status_presenter as status_presenter_module
import ui.base_controller as base_controller_module

PreviewBoxItem = overlay_items_module.PreviewBoxItem
RectItem = overlay_items_module.RectItem
StatusPresenter = status_presenter_module.StatusPresenter
BaseAnnotationController = base_controller_module.BaseAnnotationController

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
		import tr_detection as detection_module
		det = detection_module.create_detector(self._config)
		self._detector_list[0] = det

#============================================


class EditController(BaseAnnotationController):
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
		frame_filter: set | None = None,
		start_frame: int | None = None,
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
			yolo_detector_list: Optional [None] list for lazy YOLO loading.
			frame_filter: Optional set of frame indices for filtering seeds.
			start_frame: Optional frame index to seek to on first activate.
		"""
		super().__init__(
			reader=reader,
			fps=fps,
			config=config,
			save_callback=save_callback,
			predictions=predictions,
		)

		self._work_seeds = work_seeds
		self._filtered_indices = filtered_indices
		self._seed_confidences = seed_confidences
		self._yolo_detector_list = yolo_detector_list or [None]
		self._frame_filter = frame_filter

		# Navigation state
		self._nav_idx = 0

		# Tracking counters
		self._reviewed = 0
		self._kept = 0
		self._redrawn = 0
		self._deleted = 0
		self._added = 0
		self._status_changed = 0
		self._changed_frames: set = set()
		self._delete_indices: set = set()

		# Status presenter
		self._status_presenter = StatusPresenter()

		# Seed box display
		self._seed_rect_item: object = None

		# Polish mode state
		self._polish_preview_item: object = None
		self._polish_mode: str | None = None
		self._pending_refined: dict | None = None
		self._yolo_loading: bool = False
		self._yolo_tried: bool = False
		self._yolo_thread: object = None

		# Current seed being reviewed
		self._current_seed: dict | None = None

		# Start frame for initial seek
		self._start_frame = start_frame

		# Keybindings label
		self._keybindings_label: QLabel | None = None

	#============================================

	def _build_toolbar(self) -> QWidget:
		"""Build the toolbar widget with nav and draw mode buttons.

		Returns:
			QWidget containing prev/next and draw mode buttons.
		"""
		widget = QWidget()
		layout = QHBoxLayout(widget)
		layout.setContentsMargins(4, 0, 4, 0)
		layout.setSpacing(4)

		# Navigation buttons
		btn_prev = QPushButton("<  Prev")
		btn_prev.setToolTip("Previous seed (LEFT or Shift+LEFT when zoomed)")
		btn_prev.clicked.connect(self._on_prev)
		layout.addWidget(btn_prev)

		btn_keep = QPushButton("Keep  >")
		btn_keep.setToolTip("Keep seed and advance (SPACE or RIGHT)")
		btn_keep.clicked.connect(self._on_keep)
		layout.addWidget(btn_keep)

		# Separator space
		layout.addSpacing(12)

		# Draw mode toggle buttons (checkable for visual state)
		self._btn_partial = QPushButton("Partial")
		self._btn_partial.setCheckable(True)
		self._btn_partial.setToolTip("Toggle partial draw mode (P)")
		self._btn_partial.clicked.connect(self._on_partial_toggle)
		layout.addWidget(self._btn_partial)

		self._btn_approx = QPushButton("Approx")
		self._btn_approx.setCheckable(True)
		self._btn_approx.setToolTip("Toggle approx/obstruction draw mode (A)")
		self._btn_approx.clicked.connect(self._on_approx_toggle)
		layout.addWidget(self._btn_approx)

		return widget

	#============================================

	def _on_activated(self) -> None:
		"""Set up status presenter and load the first seed."""
		# Add status presenter to toolbar
		toolbar_widget = self._status_presenter.get_widget()
		self._window.statusBar().addWidget(toolbar_widget)

		# Add keybinding hints as a permanent label in the status bar
		self._keybindings_label = QLabel(self._get_default_status_text())
		self._keybindings_label.setStyleSheet(
			"font-family: monospace; font-size: 10px; "
			"color: #888888; padding: 2px 8px;"
		)
		self._window.statusBar().addPermanentWidget(self._keybindings_label)

		# Seek to nearest seed at or after start_frame if provided
		if self._start_frame is not None and self._filtered_indices:
			for i, idx in enumerate(self._filtered_indices):
				frame_idx = int(self._work_seeds[idx]["frame_index"])
				if frame_idx >= self._start_frame:
					self._nav_idx = i
					break
			else:
				# all seeds before start_frame, go to last
				self._nav_idx = len(self._filtered_indices) - 1

		# Load and display the current seed
		self._load_current_seed()

	#============================================

	def _on_deactivated(self) -> None:
		"""Clean up edit-specific state."""
		# Remove edit-specific overlays (seed rect, polish preview)
		if self._window is not None:
			scene = self._window.get_frame_view().scene()
			if self._seed_rect_item is not None:
				scene.removeItem(self._seed_rect_item)
				self._seed_rect_item = None
			if self._polish_preview_item is not None:
				scene.removeItem(self._polish_preview_item)
				self._polish_preview_item = None

		# Remove status bar widgets to prevent accumulation
		if self._window is not None:
			self._window.statusBar().removeWidget(
				self._status_presenter.get_widget()
			)
			if self._keybindings_label is not None:
				self._window.statusBar().removeWidget(self._keybindings_label)

		# Clear status bar
		self._status_presenter.clear()

	#============================================

	def _get_default_status_text(self) -> str:
		"""Short mode summary for the status bar.

		Returns:
			String with mode summary.
		"""
		return "Edit mode - review seeds"

	#============================================

	def _get_keybinding_hints(self) -> str:
		"""Keybinding hints for the key hint overlay.

		Returns:
			String with keybinding hints.
		"""
		hints = (
			"SPACE/R=keep  LEFT=prev  D=del  Y=yolo  F=avg  "
			"[/]=jump  L=low  U=add  P=part  A=approx  "
			"V=hide preds  Z=zoom  ESC=done"
		)
		return hints

	#============================================

	def _get_mode_name(self) -> str:
		"""Mode name for display.

		Returns:
			String "edit".
		"""
		return "edit"

	#============================================

	def _get_zoom_center(self) -> tuple | None:
		"""Get zoom center from current seed or predictions.

		Returns:
			Tuple of (cx, cy) or None.
		"""
		# try to center on current seed position
		if self._current_seed is not None:
			cx = self._current_seed.get("cx")
			cy = self._current_seed.get("cy")
			if cx is not None and cy is not None:
				return (float(cx), float(cy))
		# fallback to prediction center
		return self._get_prediction_center()

	#============================================

	def _set_status_text(self, text: str) -> None:
		"""Set status via the StatusPresenter widget.

		Args:
			text: Message to display.
		"""
		self._status_presenter.get_widget().setText(text)

	#============================================

	def _restore_default_status(self) -> None:
		"""Restore the status presenter with current seed info."""
		self._update_status_presenter()

	#============================================

	def _load_current_seed(self) -> None:
		"""Load and display the current seed frame."""
		if self._nav_idx >= len(self._filtered_indices):
			self._on_quit()
			return

		seed_list_idx = self._filtered_indices[self._nav_idx]
		seed = self._work_seeds[seed_list_idx]
		self._current_seed = seed
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

		# Show seed box underneath (thick, solid)
		self._update_seed_rect_overlay()

		# Show FWD/BWD overlays on top (thin, dashed)
		self._update_fwd_bwd_overlays()

		# Update progress bar
		self._window.set_progress(
			self._nav_idx + 1, len(self._filtered_indices)
		)

		# Update status presenter
		seed_confidence = None
		if self._seed_confidences is not None:
			seed_confidence = self._seed_confidences.get(frame_idx)
		# look up interval_info for severity display
		interval_info = None
		if self._predictions is not None:
			preds = self._predictions.get(frame_idx)
			if preds is not None:
				interval_info = preds.get("interval_info")
		self._status_presenter.update(
			seed, self._nav_idx, len(self._filtered_indices),
			seed_confidence, interval_info,
		)

		# Update scale bar
		self._update_scale_bar()

		# Recenter view on bbox when zoomed in
		self._recenter_on_bbox()

	#============================================

	def _recenter_on_bbox(self) -> None:
		"""Recenter the view on the current seed bbox when zoomed in."""
		frame_view = self._window.get_frame_view()
		zoom = frame_view.get_zoom_factor()
		# Skip if not zoomed in
		if zoom <= 1.05:
			return

		seed = self._current_seed
		status = seed.get("status", "unknown")

		# Use seed cx/cy if the seed has a real position
		if status not in ("approximate", "not_in_frame") and seed.get("cx") is not None:
			center_x = float(seed["cx"])
			center_y = float(seed["cy"])
		else:
			# Fall back to FWD/BWD prediction average center
			center = self._get_prediction_center()
			if center is None:
				return
			center_x, center_y = center

		frame_view.set_zoom(zoom, center_x, center_y)

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

		# Show box for any seed that has coordinates
		cx = seed.get("cx")
		cy = seed.get("cy")
		if cx is None or cy is None:
			return

		# Extract seed box
		cx = float(cx)
		cy = float(cy)
		w = float(seed.get("w", 0))
		h = float(seed.get("h", 0))

		x = int(cx - w / 2.0)
		y = int(cy - h / 2.0)

		# Color seed box by status type from overlay_styles.yaml
		status = seed.get("status", "visible")
		style = overlay_config.get_seed_status_style(status)
		color = style["color"]
		fill_alpha = int(style["fill_opacity"] * 255)
		thickness = overlay_config.get_thickness_scale(style["thickness_tier"])

		# Create seed box overlay: solid line, heavy thickness, drawn underneath
		self._seed_rect_item = RectItem(
			x, y, int(w), int(h),
			color_str=color,
			label=f"SEED ({status})",
			fill_alpha=fill_alpha,
			thickness_scale=thickness,
		)
		# low z-value so seed box renders below FWD/BWD
		self._seed_rect_item.setZValue(1)
		scene.addItem(self._seed_rect_item)

	#============================================

	def handle_key_press(self, key: int, modifiers: object = None) -> bool:
		"""Handle keyboard events.

		Args:
			key: Qt key code.
			modifiers: Qt keyboard modifiers (for detecting Shift, etc.).

		Returns:
			True if event was handled.
		"""
		# Check for Shift modifier on arrow keys for frame advance
		shift_held = False
		if modifiers is not None:
			shift_held = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)

		# Reject polish preview on any non-SPACE key
		if self._polish_mode == "pending" and key != Qt.Key.Key_Space:
			self._clear_polish_preview()
			self._update_status_presenter()

		# Common keys (ESC/Q, P, A, Z)
		result = self._handle_common_key(key, modifiers)
		if result is not None:
			return result

		if key == Qt.Key.Key_Space:
			if self._polish_mode == "pending":
				self._on_accept_polish()
				return True
			self._on_keep()
			return True
		elif key == Qt.Key.Key_Right:
			is_zoomed = self._window.get_frame_view().get_zoom_factor() > 1.05
			if shift_held or not is_zoomed:
				if self._polish_mode == "pending":
					self._on_accept_polish()
					return True
				self._on_keep()
				return True
			return False
		elif key == Qt.Key.Key_Left:
			is_zoomed = self._window.get_frame_view().get_zoom_factor() > 1.05
			if shift_held or not is_zoomed:
				self._on_prev()
				return True
			return False
		elif key == Qt.Key.Key_D:
			self._on_delete()
			return True
		elif key == Qt.Key.Key_N:
			self._on_status_change("not_in_frame")
			return True
		elif key == Qt.Key.Key_Y:
			self._on_yolo_polish()
			return True
		elif key == Qt.Key.Key_F:
			self._on_consensus_polish()
			return True
		elif key == Qt.Key.Key_BracketRight:
			self._on_jump_forward()
			return True
		elif key == Qt.Key.Key_BracketLeft:
			self._on_jump_backward()
			return True
		elif key == Qt.Key.Key_L:
			self._on_jump_low_conf()
			return True
		elif key == Qt.Key.Key_U:
			self._on_enter_add_mode()
			return True

		return False

	#============================================

	def _on_box_drawn(self, box: list) -> None:
		"""Process a drawn box.

		Args:
			box: Box as [x, y, w, h].
		"""
		import seeding as seeding_module

		seed_list_idx = self._filtered_indices[self._nav_idx]
		seed = self._work_seeds[seed_list_idx]
		frame_idx = int(seed["frame_index"])

		if self._approx_mode:
			self._approx_mode = False
			self._update_mode_badge()
			# Build approximate seed with approx area box
			norm_box = seeding_module.normalize_seed_box(box, self._config)
			tx, ty, tw, th = norm_box
			cx = float(tx + tw / 2.0)
			cy = float(ty + th / 2.0)
			new_seed = {
				"frame_index": frame_idx,
				"frame": frame_idx,
				"time_s": seed.get("time_s", round(frame_idx / self._fps, 3)),
				"status": "approximate",
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
			self._update_mode_badge()
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
		# look up interval_info for severity display
		interval_info = None
		if self._predictions is not None:
			preds = self._predictions.get(frame_idx)
			if preds is not None:
				interval_info = preds.get("interval_info")
		self._status_presenter.update(
			self._current_seed, self._nav_idx, len(self._filtered_indices),
			conf, interval_info,
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

	def _on_jump_forward(self) -> None:
		"""Jump forward 10% of the filtered seed list."""
		total = len(self._filtered_indices)
		jump = max(1, total // 10)
		self._nav_idx = min(self._nav_idx + jump, total - 1)
		self._load_current_seed()

	#============================================

	def _on_jump_backward(self) -> None:
		"""Jump backward 10% of the filtered seed list."""
		total = len(self._filtered_indices)
		jump = max(1, total // 10)
		self._nav_idx = max(self._nav_idx - jump, 0)
		self._load_current_seed()

	#============================================

	def _on_jump_low_conf(self) -> None:
		"""Jump to the next low-confidence seed after the current position.

		Searches forward through filtered seeds for one with confidence
		score below 0.5. Wraps around to the beginning if needed.
		"""
		if self._seed_confidences is None:
			print("  no confidence data available")
			return

		total = len(self._filtered_indices)
		# search forward from current position, wrapping around
		for offset in range(1, total):
			idx = (self._nav_idx + offset) % total
			seed_list_idx = self._filtered_indices[idx]
			seed = self._work_seeds[seed_list_idx]
			frame_idx = int(seed["frame_index"])
			conf = self._seed_confidences.get(frame_idx)
			if conf is not None and float(conf.get("score", 1.0)) < 0.5:
				self._nav_idx = idx
				self._load_current_seed()
				return

		print("  no low-confidence seeds found")

	#============================================

	def _on_quit(self) -> None:
		"""Quit the editor."""
		self._done = True
		if self._window is not None:
			self._window.close()

	#============================================

	def _on_enter_add_mode(self) -> None:
		"""Enter seed-add mode via SeedController.

		Saves the current frame position, creates a SeedController with
		a return callback, and swaps controllers.
		"""
		import ui.seed_controller as seed_controller_module

		# Save current frame for position restoration on return
		self._saved_frame_index = self._current_frame

		# Collect frame indices of existing seeds for duplicate filtering
		existing_frames = set()
		for seed in self._work_seeds:
			existing_frames.add(int(seed["frame_index"]))

		# Build a list of all frame indices the user could scrub to
		# (use the reader's total frame count as the range)
		total_frames = self._reader._total_frames
		# Start the seed controller at the current frame
		seed_frame_indices = list(range(total_frames))

		controller = seed_controller_module.SeedController(
			seed_frame_indices=seed_frame_indices,
			reader=self._reader,
			fps=self._fps,
			config=self._config,
			all_seeds=self._work_seeds,
			save_callback=self._save_callback,
			pass_number=1,
			mode_str="edit_add",
			predictions=self._predictions,
			return_callback=self._resume_from_add_mode,
			start_frame=self._current_frame,
		)

		# Swap controllers via the window
		self._window.set_controller(controller)
		# Update mode indicator
		if hasattr(self._window, "_mode_actions"):
			self._window._mode_actions["seed"].setChecked(True)

	#============================================

	def _resume_from_add_mode(self, new_seeds: list) -> None:
		"""Resume edit mode after returning from add-seed mode.

		Args:
			new_seeds: List of newly collected seeds from seed mode.
		"""
		# 1. Purge deleted seeds
		if self._delete_indices:
			self._work_seeds[:] = [
				s for i, s in enumerate(self._work_seeds)
				if i not in self._delete_indices
			]
			self._delete_indices.clear()

		# 2. Append new seeds
		self._added += len(new_seeds)
		self._work_seeds.extend(new_seeds)

		# 3. Rebuild filtered indices
		self._rebuild_filtered_indices()

		# 4. Restore position: first seed with frame_index >= saved
		self._restore_nav_position()

		# 5. Swap back to edit mode
		self._window.set_controller(self)
		if hasattr(self._window, "_mode_actions"):
			self._window._mode_actions["edit"].setChecked(True)

	#============================================

	def _rebuild_filtered_indices(self) -> None:
		"""Rebuild filtered indices after seed list changes.

		Sorts work_seeds in place by frame_index and rebuilds
		_filtered_indices based on _frame_filter.
		"""
		# Sort work_seeds in place by frame_index
		self._work_seeds.sort(key=lambda s: int(s["frame_index"]))

		# Rebuild filtered indices
		if self._frame_filter is not None:
			self._filtered_indices = [
				i for i, s in enumerate(self._work_seeds)
				if int(s["frame_index"]) in self._frame_filter
			]
		else:
			self._filtered_indices = list(range(len(self._work_seeds)))

	#============================================

	def _restore_nav_position(self) -> None:
		"""Restore nav position to first seed at or after saved frame."""
		if not self._filtered_indices:
			# No seeds left, quit gracefully
			self._nav_idx = 0
			return

		saved = getattr(self, "_saved_frame_index", 0)
		for i, idx in enumerate(self._filtered_indices):
			frame_idx = int(self._work_seeds[idx]["frame_index"])
			if frame_idx >= saved:
				self._nav_idx = i
				return
		# All seeds before saved frame, go to last
		self._nav_idx = len(self._filtered_indices) - 1

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
			"added": self._added,
			"status_changed": self._status_changed,
			"changed_frames": self._changed_frames,
		}

		return (final_seeds, summary)
