"""
Graphics items for annotation overlays in the frame view.
"""

# Standard Library
# (none)

# PIP3 modules
from PySide6 import QtWidgets
from PySide6.QtWidgets import QApplication, QGraphicsRectItem, QGraphicsTextItem
from PySide6.QtGui import QColor, QPen, QBrush, QFont
from PySide6.QtCore import Qt, QRectF

# local repo modules
import overlay_config

#============================================

def _get_device_pixel_ratio() -> float:
	"""Get the device pixel ratio for DPI-aware line scaling.

	Returns:
		Device pixel ratio (2.0 on Retina, 1.0 on standard displays).
	"""
	app = QApplication.instance()
	if app is None:
		return 1.0
	# Use the primary screen device pixel ratio
	screens = app.screens()
	if not screens:
		return 1.0
	dpr = screens[0].devicePixelRatio()
	return dpr

#============================================


class RectItem(QGraphicsRectItem):
	"""
	A colored rectangle overlay item with optional label.

	Draws a semi-transparent filled rectangle with a thin border and
	optional text label above the top-left corner. Border thickness
	scales with the box area and compensates for display DPI so
	overlays stay unobtrusive on small torso boxes but remain visible
	on large ones.
	"""

	def __init__(
		self,
		x: float,
		y: float,
		w: float,
		h: float,
		color_str: str = "#00FF00",
		label: str = "",
		fill_alpha: int = 15,
		dashed: bool = False,
		thickness_scale: float = 1.0,
		parent: QtWidgets.QGraphicsItem | None = None
	) -> None:
		"""
		Initialize RectItem.

		Args:
			x: Top-left x coordinate.
			y: Top-left y coordinate.
			w: Width of rectangle.
			h: Height of rectangle.
			color_str: Color as hex string (e.g. "#00FF00").
			label: Optional text label.
			fill_alpha: Fill opacity 0-255 (default 15, ~6%).
			dashed: Use dashed line style instead of solid.
			thickness_scale: Multiplier for border thickness (1.0 = normal).
			parent: Parent graphics item.
		"""
		super().__init__(x, y, w, h, parent)

		color = QColor(color_str)

		# semi-transparent fill
		fill_color = QColor(color_str)
		fill_color.setAlpha(fill_alpha)
		self.setBrush(QBrush(fill_color))

		# border thickness scales with box area, adjusted for DPI
		# small boxes (~50x80) get thickness 1, large (~200x300) get 2
		dpr = _get_device_pixel_ratio()
		box_area = w * h
		base_thickness = 1.0 if box_area < 20000 else 2.0
		# divide by DPI ratio so lines look the same on retina vs standard
		thickness = (base_thickness * thickness_scale) / dpr
		pen = QPen(color)
		pen.setWidthF(thickness)
		if dashed:
			# custom dash pattern: [dash_length, gap_length] in pen-width units
			pen.setStyle(Qt.PenStyle.CustomDashLine)
			pen.setDashPattern([6, 10])
		self.setPen(pen)

		if label:
			# label font scales with box height
			font_size = max(7, min(12, int(h * 0.08)))
			label_item = QGraphicsTextItem(label, self)
			label_item.setDefaultTextColor(color)
			label_font = QFont()
			label_font.setPointSize(font_size)
			label_item.setFont(label_font)
			# position label just above the top-left corner
			label_item.setPos(x, y - font_size - 6)

	#============================================


class PreviewBoxItem(QGraphicsRectItem):
	"""
	A semi-transparent preview box for user confirmation.

	Represents a proposed box with a semi-transparent green fill and
	solid green border.
	"""

	def __init__(
		self,
		x: float,
		y: float,
		w: float,
		h: float,
		parent: QtWidgets.QGraphicsItem | None = None
	) -> None:
		"""
		Initialize PreviewBoxItem.

		Args:
			x: Top-left x coordinate.
			y: Top-left y coordinate.
			w: Width of box.
			h: Height of box.
			parent: Parent graphics item.
		"""
		super().__init__(x, y, w, h, parent)

		# Semi-transparent fill from overlay_styles.yaml
		preview_color = overlay_config.get_preview_box_color()
		preview_opacity = overlay_config.get_preview_box_fill_opacity()
		fill_color = QColor(preview_color)
		fill_color.setAlpha(int(preview_opacity * 255))
		self.setBrush(QBrush(fill_color))

		# Solid border, DPI-adjusted, with heavy thickness tier
		dpr = _get_device_pixel_ratio()
		border_color = QColor(preview_color)
		thickness = overlay_config.get_thickness_scale("heavy")
		pen = QPen(border_color)
		pen.setWidthF(thickness / dpr)
		self.setPen(pen)

	#============================================


class ScaleBarItem(QGraphicsTextItem):
	"""
	A zoom scale indicator displayed in the top-right corner.

	Shows the zoom factor (e.g. "1.5x") when zoomed in, with a
	semi-transparent dark background for readability.
	"""

	def __init__(self, parent: QtWidgets.QGraphicsItem | None = None) -> None:
		"""
		Initialize ScaleBarItem.

		Args:
			parent: Parent graphics item.
		"""
		super().__init__("", parent)

		# Setup text appearance
		font = QFont()
		font.setPointSize(16)
		font.setBold(True)
		self.setFont(font)
		self.setDefaultTextColor(QColor(255, 255, 255))

		self.zoom_factor = 1.0
		self.background_item = None

	#============================================

	def update_zoom(self, zoom_factor: float) -> None:
		"""
		Update the zoom display.

		Shows "Xz" format (e.g. "1.5x") when zoom_factor > 1.05,
		hides otherwise.

		Args:
			zoom_factor: Current zoom factor.
		"""
		self.zoom_factor = zoom_factor

		if zoom_factor > 1.05:
			# Format zoom factor with one decimal place
			text = f"{zoom_factor:.1f}x"
			self.setPlainText(text)
			self.show()

			# Create or update background rect for readability
			if self.background_item is None:
				self.background_item = QtWidgets.QGraphicsRectItem(self)
				bg_color = QColor(0, 0, 0)
				bg_color.setAlpha(180)
				self.background_item.setBrush(QBrush(bg_color))
				self.background_item.setPen(QPen(Qt.PenStyle.NoPen))
				self.background_item.setZValue(-1)

			# Position background behind text with padding
			text_rect = self.boundingRect()
			padding = 4
			bg_rect = QRectF(
				-padding,
				-padding,
				text_rect.width() + 2 * padding,
				text_rect.height() + 2 * padding
			)
			self.background_item.setRect(bg_rect)
		else:
			self.setPlainText("")
			self.hide()
