"""
Graphics items for annotation overlays in the frame view.
"""

# Standard Library
# (none)

# PIP3 modules
from PySide6 import QtWidgets
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem
from PySide6.QtGui import QColor, QPen, QBrush, QFont
from PySide6.QtCore import Qt, QRectF

#============================================


class RectItem(QGraphicsRectItem):
	"""
	A colored rectangle overlay item with optional label.

	Draws a colored outline rectangle (no fill) with an optional text label
	positioned above the top-left corner.
	"""

	def __init__(
		self,
		x: float,
		y: float,
		w: float,
		h: float,
		color_str: str = "#00FF00",
		label: str = "",
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
			parent: Parent graphics item.
		"""
		super().__init__(x, y, w, h, parent)

		color = QColor(color_str)
		pen = QPen(color)
		pen.setWidth(2)
		self.setPen(pen)
		self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

		if label:
			self.label_text = QGraphicsTextItem(label, self)
			self.label_text.setDefaultTextColor(color)
			self.label_text.setPos(x, y - 20)

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

		# Semi-transparent green fill
		fill_color = QColor("#22C55E")
		fill_color.setAlpha(60)
		self.setBrush(QBrush(fill_color))

		# Solid green border
		border_color = QColor("#22C55E")
		pen = QPen(border_color)
		pen.setWidth(2)
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
