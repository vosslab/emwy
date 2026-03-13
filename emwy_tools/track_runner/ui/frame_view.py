"""
QGraphicsView for displaying video frames with zoom and coordinate mapping.
"""

# Standard Library
# (none)

# PIP3 modules
import numpy
from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene
from PySide6.QtGui import QImage, QPixmap, QColor, QTransform, QPainter

#============================================


class FrameView(QGraphicsView):
	"""
	A QGraphicsView for displaying and interacting with video frames.

	Supports zoom with mouse wheel (anchored to cursor), trackpad pan,
	and coordinate mapping.
	"""

	# emitted when zoom factor changes, carries zoom percentage (e.g. 150.0)
	zoom_changed = Signal(float)

	def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
		"""
		Initialize FrameView.

		Args:
			parent: Parent widget.
		"""
		super().__init__(parent)

		self.scene_obj = QGraphicsScene()
		self.scene_obj.setBackgroundBrush(QColor(0, 0, 0))
		self.setScene(self.scene_obj)

		self.pixmap_item = None

		self.zoom_factor = 1.0
		self.min_zoom = 0.1
		self.max_zoom = 30.0

		# Fit-to-view state
		self._is_fit_zoom = True
		self._needs_initial_fit = False
		self._in_fit_to_view = False

		# enable anti-aliasing for smooth overlay rendering
		self.setRenderHint(QPainter.RenderHint.Antialiasing)
		self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
		self.setRenderHint(QPainter.RenderHint.TextAntialiasing)

		# Zoom anchors under cursor; resize keeps center stable so
		# internal layout changes (status bar badge) don't shift the view
		self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
		self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

	#============================================

	def set_frame(self, bgr_array: numpy.ndarray) -> None:
		"""
		Update the displayed frame.

		Converts BGR numpy array to QImage then to QPixmap and displays it.

		Args:
			bgr_array: BGR image as numpy array (H x W x 3, uint8).
		"""
		if bgr_array.size == 0:
			return

		height, width = bgr_array.shape[:2]

		# Convert BGR to RGB by swapping channels
		rgb_array = bgr_array[:, :, ::-1].copy()

		# Create QImage from RGB data
		q_image = QImage(
			rgb_array.data,
			width,
			height,
			3 * width,
			QImage.Format.Format_RGB888
		)

		# Convert to QPixmap and display
		pixmap = QPixmap.fromImage(q_image)

		# Track whether this is the first frame (pixmap was None)
		is_first_frame = (self.pixmap_item is None)

		if self.pixmap_item is not None:
			self.scene_obj.removeItem(self.pixmap_item)

		self.pixmap_item = self.scene_obj.addPixmap(pixmap)
		self.scene_obj.setSceneRect(pixmap.rect())

		# Schedule initial fit when the first frame arrives
		if is_first_frame:
			self._needs_initial_fit = True

	#============================================

	def _is_trackpad_event(self, event: QtGui.QWheelEvent) -> bool:
		"""Detect whether a wheel event came from the trackpad.

		macOS trackpad events carry scroll phases (Begin/Update/End/Momentum)
		and provide pixel-level deltas.  Mouse wheel clicks have NoScrollPhase
		and no pixel delta.  Both signals are checked for reliability across
		different Qt builds.

		Args:
			event: Wheel event to classify.

		Returns:
			True if the event originated from a trackpad.
		"""
		# Primary: macOS trackpad has Begin/Update/End/Momentum phases
		if event.phase() != Qt.ScrollPhase.NoScrollPhase:
			return True
		# Secondary: trackpads supply pixel-level scroll deltas
		if event.hasPixelDelta():
			return True
		return False

	#============================================

	def _ensure_pan_margin(self) -> None:
		"""Expand scene rect so scroll bars have range for panning.

		Adds 2% of the image size as margin on each side, just enough
		for scroll bars to have range without letting the image leave
		the viewport.  The margin is reset to image bounds on the next
		set_frame() or fit_to_view() call.
		"""
		if self.pixmap_item is None:
			return
		image_rect = self.pixmap_item.boundingRect()
		# 2% margin: enough scroll range without going off edge
		margin_w = image_rect.width() * 0.02
		margin_h = image_rect.height() * 0.02
		expanded = image_rect.adjusted(
			-margin_w, -margin_h, margin_w, margin_h,
		)
		self.scene_obj.setSceneRect(expanded)

	#============================================

	def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
		"""Handle mouse wheel zoom and trackpad pan events.

		Trackpad two-finger swipe pans the view via scroll bars.
		Mouse scroll wheel zooms in/out by 1.25x per notch.

		Args:
			event: Mouse wheel event.
		"""
		if self._is_trackpad_event(event):
			# Pan the view via scroll bars
			pixel_delta = event.pixelDelta()
			angle_delta = event.angleDelta()
			# prefer pixelDelta when available; fall back to angleDelta
			dx = pixel_delta.x() if pixel_delta.x() != 0 else angle_delta.x()
			dy = pixel_delta.y() if pixel_delta.y() != 0 else angle_delta.y()
			if dx != 0 or dy != 0:
				# Exit fit mode since user is deliberately panning
				self._is_fit_zoom = False
				# Expand scene rect so scroll bars have range to move
				self._ensure_pan_margin()
				h_bar = self.horizontalScrollBar()
				v_bar = self.verticalScrollBar()
				h_bar.setValue(h_bar.value() - dx)
				v_bar.setValue(v_bar.value() - dy)
			event.accept()
			return

		# Mouse wheel: zoom in/out
		delta = event.angleDelta().y()
		if delta > 0:
			scale_factor = 1.25
		else:
			scale_factor = 1.0 / 1.25

		self.zoom_factor *= scale_factor
		self.zoom_factor = max(self.min_zoom, min(self.max_zoom, self.zoom_factor))

		# Manual wheel zoom exits fit mode
		self._is_fit_zoom = False
		self.setTransform(QTransform().scale(self.zoom_factor, self.zoom_factor))
		# notify listeners of new zoom percentage
		self.zoom_changed.emit(self.zoom_factor * 100.0)

	#============================================

	def map_to_scene(self, x: int, y: int) -> tuple:
		"""
		Convert display coordinates to scene (frame) coordinates.

		Args:
			x: Display x coordinate.
			y: Display y coordinate.

		Returns:
			Tuple of (scene_x, scene_y) as floats.
		"""
		point = self.mapToScene(x, y)
		return (point.x(), point.y())

	#============================================

	def set_zoom(self, factor: float, center_x: float = -1, center_y: float = -1) -> None:
		"""
		Set zoom to a specific factor, optionally centering on a scene point.

		Args:
			factor: Desired zoom factor (clamped to min/max).
			center_x: Scene x coordinate to center on (-1 for no recentering).
			center_y: Scene y coordinate to center on (-1 for no recentering).
		"""
		self.zoom_factor = max(self.min_zoom, min(self.max_zoom, factor))
		# Explicit set_zoom exits fit mode
		self._is_fit_zoom = False
		self.setTransform(QTransform().scale(self.zoom_factor, self.zoom_factor))
		# center the view on the requested scene point
		if center_x >= 0 and center_y >= 0:
			from PySide6.QtCore import QPointF
			self.centerOn(QPointF(center_x, center_y))
		self.zoom_changed.emit(self.zoom_factor * 100.0)

	#============================================

	def get_zoom_factor(self) -> float:
		"""
		Get the current zoom scale factor.

		Returns:
			Current zoom factor.
		"""
		return self.zoom_factor

	#============================================

	def fit_to_view(self) -> None:
		"""Scale the scene to fit entirely within the viewport.

		Resets scene rect to image bounds (undoing any pan margin) then
		fits.  No-ops if no pixmap is loaded or if already inside a fit
		call (recursion guard for layout-triggered resizeEvent re-entry).
		"""
		if self._in_fit_to_view:
			return
		if self.pixmap_item is None:
			return

		# Reset scene rect to image bounds (undo _ensure_pan_margin)
		image_rect = self.pixmap_item.boundingRect()
		self.scene_obj.setSceneRect(image_rect)

		scene_rect = self.scene_obj.sceneRect()
		if scene_rect.isEmpty():
			return

		self._in_fit_to_view = True
		self.fitInView(scene_rect, Qt.AspectRatioMode.KeepAspectRatio)

		# Read back the effective zoom from the resulting transform
		transform = self.transform()
		self.zoom_factor = transform.m11()
		self._is_fit_zoom = True
		self._in_fit_to_view = False
		self.zoom_changed.emit(self.zoom_factor * 100.0)

	#============================================

	def is_fit_zoom(self) -> bool:
		"""Check whether the view is currently in fit-to-window mode.

		Returns:
			True if the last zoom action was a fit-to-view.
		"""
		return self._is_fit_zoom

	#============================================

	def showEvent(self, event: QtGui.QShowEvent) -> None:
		"""Handle show event to apply deferred initial fit.

		Args:
			event: Show event.
		"""
		super().showEvent(event)
		# Apply initial fit once the viewport geometry is valid
		if self._needs_initial_fit and self.viewport().width() > 0:
			scene_rect = self.scene_obj.sceneRect()
			if not scene_rect.isEmpty():
				self.fit_to_view()
				self._needs_initial_fit = False

	#============================================

	def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
		"""Handle resize to refit or preserve manual zoom.

		Args:
			event: Resize event.
		"""
		super().resizeEvent(event)

		if self._needs_initial_fit and self.viewport().width() > 0:
			# Deferred initial fit not yet applied
			scene_rect = self.scene_obj.sceneRect()
			if not scene_rect.isEmpty():
				self.fit_to_view()
				self._needs_initial_fit = False
		elif self._is_fit_zoom and self.pixmap_item is not None:
			# Refit on resize while in fit mode
			self.fit_to_view()
