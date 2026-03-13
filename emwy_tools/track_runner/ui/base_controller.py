"""Base annotation controller for track runner UI.

Shared plumbing for all annotation controllers: event filter,
mouse drawing, overlay management, zoom, draw mode toggles,
scale bar, and activation lifecycle.
"""

# Standard Library
# (none)

# PIP3 modules
from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QWidget, QPushButton
import numpy

# local repo modules
import overlay_config
import ui.overlay_items as overlay_items_module

PreviewBoxItem = overlay_items_module.PreviewBoxItem
RectItem = overlay_items_module.RectItem
ScaleBarItem = overlay_items_module.ScaleBarItem
PredictionLegendItem = overlay_items_module.PredictionLegendItem
KeyHintOverlay = overlay_items_module.KeyHintOverlay

#============================================


class BaseAnnotationController(QObject):
	"""Shared base for annotation controllers.

	Provides window plumbing, event filter, mouse drawing, overlay
	management, zoom cycling, draw mode toggles, and scale bar.
	Subclasses implement abstract methods for mode-specific behavior.
	"""

	def __init__(
		self,
		reader: object,
		fps: float,
		config: dict,
		save_callback: object,
		predictions: dict | None = None,
	) -> None:
		"""Initialize common controller state.

		Args:
			reader: FrameReader instance with read_frame(idx) method.
			fps: Frames per second of the video.
			config: Configuration dict.
			save_callback: Callable for saving state.
			predictions: Optional dict mapping frame_index to prediction dicts.
		"""
		super().__init__()

		self._reader = reader
		self._fps = fps
		self._config = config
		self._save_callback = save_callback
		self._predictions = predictions

		# Window and UI state
		self._window: object = None
		self._current_frame: int = 0
		self._current_bgr: numpy.ndarray | None = None
		self._done: bool = False

		# Drawing state
		self._drawing: bool = False
		self._drag_start: tuple | None = None
		self._drag_current: tuple | None = None
		self._preview_item: object = None
		self._partial_mode: bool = False
		self._approx_mode: bool = False

		# Overlay items tracked for cleanup
		self._overlay_items: list = []
		self._fwd_item: object = None
		self._bwd_item: object = None
		self._fused_item: object = None
		self._consensus_item: object = None
		self._scale_bar_item: object = None
		self._legend_item: object = None
		self._key_hint_item: object = None

		# Peek suppression state
		self._preds_suppressed: bool = False

		# Per-overlay persistent visibility toggles
		self._overlay_visibility: dict = {
			"fwd": True, "bwd": True, "fused": True,
			"consensus": True, "legend": True,
		}

		# Toolbar widgets
		self._toolbar_widget: QWidget | None = None
		self._btn_partial: QPushButton | None = None
		self._btn_approx: QPushButton | None = None

	#============================================

	@property
	def toolbar_widget(self) -> QWidget | None:
		"""Toolbar widget for the annotation toolbar.

		Returns:
			QWidget with navigation and draw mode buttons, or None.
		"""
		return self._toolbar_widget

	#============================================

	def activate(self, window: object) -> None:
		"""Activate the controller and connect to window events.

		Args:
			window: AnnotationWindow instance.
		"""
		self._window = window

		# Build toolbar widget
		self._toolbar_widget = self._build_toolbar()

		# Install event filter for keyboard and mouse events
		self._window.installEventFilter(self)
		self._window.get_frame_view().installEventFilter(self)
		viewport = self._window.get_frame_view().viewport()
		viewport.installEventFilter(self)

		# Add scale bar item to scene
		scene = self._window.get_frame_view().scene()
		self._scale_bar_item = ScaleBarItem()
		scene.addItem(self._scale_bar_item)
		self._overlay_items.append(self._scale_bar_item)

		# Add prediction legend if predictions are available
		if self._predictions is not None:
			scene_rect = scene.sceneRect()
			self._legend_item = PredictionLegendItem(
				scene_rect.width(), scene_rect.height(),
			)
			scene.addItem(self._legend_item)
			self._overlay_items.append(self._legend_item)

		# Add keybinding hint overlay at bottom of frame
		scene_rect = scene.sceneRect()
		if scene_rect.width() > 0 and scene_rect.height() > 0:
			self._key_hint_item = KeyHintOverlay(
				scene_rect.width(), scene_rect.height(),
			)
			# populate with mode-specific hints
			mode_color = overlay_config.get_workspace_mode_color(
				self._get_mode_name()
			)
			self._key_hint_item.update_text(
				self._get_mode_name().upper(),
				self._get_keybinding_hints(),
				mode_color,
			)
			scene.addItem(self._key_hint_item)
			self._overlay_items.append(self._key_hint_item)

		# Subclass hook
		self._on_activated()

	#============================================

	def deactivate(self) -> None:
		"""Deactivate the controller and disconnect from window events."""
		if self._window is not None:
			self._window.removeEventFilter(self)
			self._window.get_frame_view().removeEventFilter(self)
			viewport = self._window.get_frame_view().viewport()
			viewport.removeEventFilter(self)

		# Remove all tracked overlay items from scene
		if self._window is not None:
			scene = self._window.get_frame_view().scene()
			for item in self._overlay_items:
				if item is not None:
					scene.removeItem(item)
		self._overlay_items.clear()
		self._fwd_item = None
		self._bwd_item = None
		self._fused_item = None
		self._consensus_item = None
		self._scale_bar_item = None
		self._legend_item = None
		self._key_hint_item = None
		# Remove preview item if present
		if self._preview_item is not None and self._window is not None:
			scene = self._window.get_frame_view().scene()
			scene.removeItem(self._preview_item)
			self._preview_item = None

		# Subclass hook
		self._on_deactivated()

	#============================================

	def _add_overlay(self, item: object) -> None:
		"""Add an overlay item to the scene and tracking list.

		Args:
			item: QGraphicsItem to add.
		"""
		scene = self._window.get_frame_view().scene()
		scene.addItem(item)
		self._overlay_items.append(item)

	#============================================

	def _remove_overlay(self, item: object) -> None:
		"""Remove an overlay item from the scene and tracking list.

		Args:
			item: QGraphicsItem to remove.
		"""
		if item is None:
			return
		scene = self._window.get_frame_view().scene()
		scene.removeItem(item)
		if item in self._overlay_items:
			self._overlay_items.remove(item)

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
			modifiers = event.modifiers()
			if self.handle_key_press(key, modifiers):
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
			# Delegate wheel to the FrameView so zoom works
			frame_view = self._window.get_frame_view()
			frame_view.wheelEvent(event)
			QTimer.singleShot(0, self._update_scale_bar)
			return True

		return super().eventFilter(obj, event)

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

	def _handle_common_key(self, key: int, modifiers: object) -> bool | None:
		"""Handle keys common to all controllers.

		Handles ESC/Q, P (partial), A (approx), Z (zoom).

		Args:
			key: Qt key code.
			modifiers: Qt keyboard modifiers.

		Returns:
			True if handled, None if not.
		"""
		if key == Qt.Key.Key_Escape or key == Qt.Key.Key_Q:
			self._on_quit()
			return True
		elif key == Qt.Key.Key_P:
			self._on_partial_toggle()
			return True
		elif key == Qt.Key.Key_A:
			self._on_approx_toggle()
			return True
		elif key == Qt.Key.Key_Z:
			self._on_zoom_toggle()
			return True
		elif key == Qt.Key.Key_V:
			self._suppress_predictions()
			return True
		return None

	#============================================

	def _get_prediction_center(self) -> tuple | None:
		"""Get average center of FWD/BWD predictions for the current frame.

		Returns:
			Tuple of (cx, cy) or None if no predictions available.
		"""
		if self._predictions is None:
			return None
		preds = self._predictions.get(self._current_frame)
		if preds is None:
			return None

		centers = []
		fwd = preds.get("forward")
		if fwd is not None:
			centers.append((float(fwd["cx"]), float(fwd["cy"])))
		bwd = preds.get("backward")
		if bwd is not None:
			centers.append((float(bwd["cx"]), float(bwd["cy"])))

		if not centers:
			return None

		# Average the available centers
		avg_cx = sum(c[0] for c in centers) / len(centers)
		avg_cy = sum(c[1] for c in centers) / len(centers)
		return (avg_cx, avg_cy)

	#============================================

	def _update_fwd_bwd_overlays(self) -> None:
		"""Update FWD/BWD/fused/consensus prediction overlays on the scene."""
		# Reset peek suppression on frame advance
		self._preds_suppressed = False

		# Remove old overlays
		if self._fwd_item is not None:
			self._remove_overlay(self._fwd_item)
			self._fwd_item = None
		if self._bwd_item is not None:
			self._remove_overlay(self._bwd_item)
			self._bwd_item = None
		if self._fused_item is not None:
			self._remove_overlay(self._fused_item)
			self._fused_item = None
		if self._consensus_item is not None:
			self._remove_overlay(self._consensus_item)
			self._consensus_item = None

		# Return early if no predictions
		if self._predictions is None:
			return
		preds = self._predictions.get(self._current_frame)
		if preds is None:
			return

		# Consensus overlay (AVG of FWD/BWD) -- Z=3, below others
		cons = preds.get("consensus")
		if cons is not None:
			cons_style = overlay_config.get_prediction_style("consensus")
			cx = float(cons["cx"])
			cy = float(cons["cy"])
			w = float(cons["w"])
			h = float(cons["h"])
			x = int(cx - w / 2.0)
			y = int(cy - h / 2.0)
			self._consensus_item = RectItem(
				x, y, int(w), int(h),
				color_str=cons_style["color"],
				label="AVG",
				fill_alpha=int(cons_style["fill_opacity"] * 255),
				dashed=(cons_style["line_style"] == "dotted"),
			)
			self._consensus_item.setZValue(3)
			self._add_overlay(self._consensus_item)

		# Fused (refined second-pass) overlay -- Z=4
		fused = preds.get("fused")
		if fused is not None:
			fused_style = overlay_config.get_prediction_style("fused")
			cx = float(fused["cx"])
			cy = float(fused["cy"])
			w = float(fused["w"])
			h = float(fused["h"])
			x = int(cx - w / 2.0)
			y = int(cy - h / 2.0)
			self._fused_item = RectItem(
				x, y, int(w), int(h),
				color_str=fused_style["color"],
				label="REFINED",
				fill_alpha=int(fused_style["fill_opacity"] * 255),
				dashed=(fused_style["line_style"] == "dashed"),
			)
			self._fused_item.setZValue(4)
			self._add_overlay(self._fused_item)

		# FWD prediction -- Z=5
		fwd = preds.get("forward")
		if fwd is not None:
			fwd_style = overlay_config.get_prediction_style("forward")
			cx = float(fwd["cx"])
			cy = float(fwd["cy"])
			w = float(fwd["w"])
			h = float(fwd["h"])
			x = int(cx - w / 2.0)
			y = int(cy - h / 2.0)
			self._fwd_item = RectItem(
				x, y, int(w), int(h),
				color_str=fwd_style["color"],
				label="FWD",
				fill_alpha=int(fwd_style["fill_opacity"] * 255),
				dashed=(fwd_style["line_style"] == "dashed"),
			)
			self._fwd_item.setZValue(5)
			self._add_overlay(self._fwd_item)

		# BWD prediction -- Z=5
		bwd = preds.get("backward")
		if bwd is not None:
			bwd_style = overlay_config.get_prediction_style("backward")
			cx = float(bwd["cx"])
			cy = float(bwd["cy"])
			w = float(bwd["w"])
			h = float(bwd["h"])
			x = int(cx - w / 2.0)
			y = int(cy - h / 2.0)
			self._bwd_item = RectItem(
				x, y, int(w), int(h),
				color_str=bwd_style["color"],
				label="BWD",
				fill_alpha=int(bwd_style["fill_opacity"] * 255),
				dashed=(bwd_style["line_style"] == "dashed"),
			)
			self._bwd_item.setZValue(5)
			self._add_overlay(self._bwd_item)

		# reposition legend to the corner farthest from the tracked box
		if self._legend_item is not None:
			# use consensus center as the bbox reference point
			cons = preds.get("consensus")
			if cons is not None:
				bbox_cx = float(cons["cx"])
				bbox_cy = float(cons["cy"])
			else:
				bbox_cx = -1
				bbox_cy = -1
			scene_rect = self._window.get_frame_view().scene().sceneRect()
			self._legend_item.reposition(
				scene_rect.width(), scene_rect.height(),
				bbox_cx, bbox_cy,
			)

		# apply per-overlay visibility (respects user toggles and peek suppression)
		self._apply_overlay_visibility()

	#============================================

	def _update_scale_bar(self) -> None:
		"""Update the zoom scale bar display."""
		if self._scale_bar_item is None:
			return
		zoom = self._window.get_frame_view().get_zoom_factor()
		self._scale_bar_item.update_zoom(zoom)

	#============================================

	def _on_zoom_toggle(self) -> None:
		"""Cycle through zoom levels (1x -> 1.5x -> 2.25x -> 3.375x -> 1x).

		Centers zoom on predictions or seed position when available,
		otherwise centers on the frame center.
		"""
		zoom_levels = [1.0, 1.5, 2.25, 3.375]
		frame_view = self._window.get_frame_view()
		current = frame_view.get_zoom_factor()
		# find the next zoom level in the cycle
		next_zoom = zoom_levels[0]
		for zf in zoom_levels:
			if zf > current + 0.01:
				next_zoom = zf
				break

		# determine zoom center
		center_x = -1.0
		center_y = -1.0
		if next_zoom > 1.0:
			center = self._get_zoom_center()
			if center is not None:
				center_x, center_y = center
			# fallback to frame center
			if center_x < 0 and self._current_bgr is not None:
				h, w = self._current_bgr.shape[:2]
				center_x = w / 2.0
				center_y = h / 2.0

		frame_view.set_zoom(next_zoom, center_x, center_y)
		self._update_scale_bar()

	#============================================

	def _get_zoom_center(self) -> tuple | None:
		"""Get zoom center point. Subclasses may override.

		Default uses prediction center.

		Returns:
			Tuple of (cx, cy) or None.
		"""
		return self._get_prediction_center()

	#============================================

	def _on_partial_toggle(self) -> None:
		"""Toggle partial draw mode."""
		if self._partial_mode:
			self._partial_mode = False
			self._update_mode_badge()
			print("  partial mode cancelled")
		else:
			self._partial_mode = True
			self._approx_mode = False
			self._update_mode_badge()
			print("  partial mode: draw the runner's torso box (press p again to cancel)")

	#============================================

	def _on_approx_toggle(self) -> None:
		"""Toggle approximate/obstruction draw mode."""
		if self._approx_mode:
			self._approx_mode = False
			self._update_mode_badge()
			print("  approx mode cancelled")
		else:
			self._approx_mode = True
			self._partial_mode = False
			self._update_mode_badge()
			print("  approx mode: draw approximate box for obstructed position")

	#============================================

	def _suppress_predictions(self) -> None:
		"""Toggle temporary prediction overlay suppression for current frame.

		Suppression resets on frame advance (in _update_fwd_bwd_overlays).
		"""
		self._preds_suppressed = not self._preds_suppressed
		self._apply_overlay_visibility()

	#============================================

	def _apply_overlay_visibility(self) -> None:
		"""Apply three-layer visibility model to prediction overlays.

		visible = available AND user_enabled AND NOT temporary_suppressed
		"""
		item_map = {
			"fwd": self._fwd_item,
			"bwd": self._bwd_item,
			"fused": self._fused_item,
			"consensus": self._consensus_item,
			"legend": self._legend_item,
		}
		for key, item in item_map.items():
			if item is not None:
				user_enabled = self._overlay_visibility.get(key, True)
				show = user_enabled and not self._preds_suppressed
				item.setVisible(show)

	#============================================

	def set_overlay_enabled(self, key: str, enabled: bool) -> None:
		"""Set persistent visibility for a specific overlay type.

		Args:
			key: Overlay key ("fwd", "bwd", "fused", "consensus", "legend").
			enabled: Whether the overlay should be visible.
		"""
		if key in self._overlay_visibility:
			self._overlay_visibility[key] = enabled
			self._apply_overlay_visibility()

	#============================================

	def _sync_toolbar_buttons(self) -> None:
		"""Sync toolbar button checked state with internal mode flags."""
		if self._btn_partial is not None:
			self._btn_partial.setChecked(self._partial_mode)
		if self._btn_approx is not None:
			self._btn_approx.setChecked(self._approx_mode)

	#============================================

	def _update_mode_badge(self) -> None:
		"""Update the status bar to show active draw mode (partial/approx).

		Calls _sync_toolbar_buttons, applies badge styling, and falls
		back to _get_default_status_text() for normal state.
		"""
		self._sync_toolbar_buttons()
		if self._window is None:
			return
		if self._approx_mode:
			approx_color = overlay_config.get_draw_mode_badge_color("approximate")
			self._window.statusBar().setStyleSheet(
				f"background-color: {approx_color}; color: #000000; font-weight: bold;"
			)
			self._set_status_text(
				"** APPROX MODE ** draw approximate box (press 'a' to cancel)"
			)
		elif self._partial_mode:
			partial_color = overlay_config.get_draw_mode_badge_color("partial")
			self._window.statusBar().setStyleSheet(
				f"background-color: {partial_color}; color: #000000; font-weight: bold;"
			)
			self._set_status_text(
				"** PARTIAL MODE ** draw visible torso (press 'p' to cancel)"
			)
		else:
			self._window.statusBar().setStyleSheet("")
			self._restore_default_status()

	#============================================

	def _set_status_text(self, text: str) -> None:
		"""Set the status bar message text.

		Subclasses may override if they use a custom status widget.

		Args:
			text: Message to display.
		"""
		self._window.statusBar().showMessage(text)

	#============================================

	def _restore_default_status(self) -> None:
		"""Restore the default status text.

		Subclasses may override to update their own status widget.
		"""
		text = self._get_default_status_text()
		self._window.statusBar().showMessage(text)

	#============================================
	# Abstract methods -- subclasses must implement

	def _on_box_drawn(self, box: list) -> None:
		"""Process a completed drawn box. Subclass must implement.

		Args:
			box: Box as [x, y, w, h].
		"""
		raise NotImplementedError

	#============================================

	def _on_quit(self) -> None:
		"""Handle quit/done request. Subclass must implement."""
		raise NotImplementedError

	#============================================

	def _build_toolbar(self) -> QWidget:
		"""Build the controller toolbar. Subclass must implement.

		Returns:
			QWidget for the annotation toolbar.
		"""
		raise NotImplementedError

	#============================================

	def _on_activated(self) -> None:
		"""Called after base activate finishes. Subclass must implement."""
		raise NotImplementedError

	#============================================

	def _on_deactivated(self) -> None:
		"""Called after base deactivate finishes. Subclass must implement."""
		raise NotImplementedError

	#============================================

	def _get_default_status_text(self) -> str:
		"""Short mode/state summary for the status bar. Subclass must implement.

		Returns:
			String with mode summary.
		"""
		raise NotImplementedError

	#============================================

	def _get_keybinding_hints(self) -> str:
		"""Keybinding hint string for the key hint overlay. Subclass must implement.

		Returns:
			String with keybinding hints (without mode label prefix).
		"""
		raise NotImplementedError

	#============================================

	def _get_mode_name(self) -> str:
		"""Short mode name for display. Subclass must implement.

		Returns:
			String like "seed", "edit", or "target".
		"""
		raise NotImplementedError

	#============================================

	def handle_key_press(self, key: int, modifiers: object = None) -> bool:
		"""Handle keyboard events. Subclass must implement.

		Args:
			key: Qt key code.
			modifiers: Qt keyboard modifiers.

		Returns:
			True if event was handled.
		"""
		raise NotImplementedError
