"""
QGraphicsView for displaying video frames with zoom and coordinate mapping.
"""

# Standard Library
# (none)

# PIP3 modules
import numpy
from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene
from PySide6.QtGui import QImage, QPixmap, QColor, QTransform, QPainter

#============================================


class FrameView(QGraphicsView):
	"""
	A QGraphicsView for displaying and interacting with video frames.

	Supports zoom with mouse wheel (anchored to cursor) and coordinate mapping.
	"""

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

		self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
		self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

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

	def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
		"""
		Handle mouse wheel zoom events.

		Zoom in on wheel up (scale * 1.25) or out on wheel down (scale / 1.25).
		Clamped between min_zoom and max_zoom.

		Args:
			event: Mouse wheel event.
		"""
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

		No-ops if no pixmap is loaded or if already inside a fit call
		(recursion guard for layout-triggered resizeEvent re-entry).
		"""
		if self._in_fit_to_view:
			return
		if self.pixmap_item is None:
			return
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
