"""
Graphics items for annotation overlays in the frame view.
"""

# Standard Library
# (none)

# PIP3 modules
from PySide6 import QtWidgets
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem
from PySide6.QtGui import QColor, QPen, QBrush, QFont, QPainter
from PySide6.QtCore import Qt, QRectF

# local repo modules
import overlay_config

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

		# border thickness: 2px baseline, cosmetic so it stays constant on screen
		base_thickness = 2.0 * thickness_scale
		pen = QPen(color)
		pen.setWidthF(base_thickness)
		# cosmetic pen stays constant width regardless of view zoom
		pen.setCosmetic(True)
		if dashed:
			# custom dash pattern: [dash_length, gap_length] in pen-width units
			pen.setStyle(Qt.PenStyle.CustomDashLine)
			pen.setDashPattern([6, 10])
		self.setPen(pen)

		# dark contrast outline drawn behind the colored border
		outline_pen = QPen(QColor(0, 0, 0, 180))
		outline_pen.setWidthF(base_thickness + 2.0)
		outline_pen.setCosmetic(True)
		if dashed:
			outline_pen.setStyle(Qt.PenStyle.CustomDashLine)
			outline_pen.setDashPattern([6, 10])
		self._outline_pen = outline_pen

		if label:
			# label font scales with box height, uses mono family
			font_size = max(7, min(12, int(h * 0.08)))
			label_item = QGraphicsTextItem(label, self)
			label_item.setDefaultTextColor(color)
			label_font = QFont(overlay_config.get_mono_font_family())
			label_font.setPointSize(font_size)
			label_item.setFont(label_font)
			# position label just above the top-left corner
			label_item.setPos(x, y - font_size - 6)

	#============================================

	def paint(
		self, painter: QPainter, option: object, widget: object = None
	) -> None:
		"""Paint with dark outline behind the colored border for contrast.

		Args:
			painter: QPainter instance.
			option: Style option (unused).
			widget: Target widget (unused).
		"""
		# draw dark outline first (wider, behind)
		painter.setPen(self._outline_pen)
		painter.setBrush(Qt.BrushStyle.NoBrush)
		painter.drawRect(self.rect())
		# draw normal fill + colored border on top
		super().paint(painter, option, widget)

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

		# Solid border with cosmetic 3px width
		border_color = QColor(preview_color)
		pen = QPen(border_color)
		pen.setWidthF(3.0)
		# cosmetic pen stays constant width regardless of view zoom
		pen.setCosmetic(True)
		self.setPen(pen)

		# dark contrast outline drawn behind the colored border
		outline_pen = QPen(QColor(0, 0, 0, 180))
		outline_pen.setWidthF(5.0)
		outline_pen.setCosmetic(True)
		self._outline_pen = outline_pen

	#============================================

	def paint(
		self, painter: QPainter, option: object, widget: object = None
	) -> None:
		"""Paint with dark outline behind the colored border for contrast.

		Args:
			painter: QPainter instance.
			option: Style option (unused).
			widget: Target widget (unused).
		"""
		# draw dark outline first (wider, behind)
		painter.setPen(self._outline_pen)
		painter.setBrush(Qt.BrushStyle.NoBrush)
		painter.drawRect(self.rect())
		# draw normal fill + colored border on top
		super().paint(painter, option, widget)

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

		# Setup text appearance with mono font
		font = QFont(overlay_config.get_mono_font_family())
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


#============================================


# prediction legend entry layout: (style_key, label_text)
_LEGEND_ENTRIES = [
	("forward", "FWD"),
	("backward", "BWD"),
	("fused", "REFINED"),
	("consensus", "AVG"),
]


#============================================


class PredictionLegendItem(QGraphicsRectItem):
	"""Compact legend showing prediction overlay colors and line styles.

	Positioned in the bottom-left corner of the scene. Each row has a
	short colored line sample followed by a label.
	"""

	def __init__(
		self,
		scene_width: float,
		scene_height: float,
		parent: QtWidgets.QGraphicsItem | None = None,
	) -> None:
		"""Initialize legend item positioned at top-left.

		Placed in the top-left corner to stay away from tracking boxes
		which tend to be in the center/lower portion of the frame.
		Uses setPos() for scene placement; rect stays at local (0,0).

		Args:
			scene_width: Width of the video frame in pixels.
			scene_height: Height of the video frame in pixels.
			parent: Parent graphics item.
		"""
		# layout constants
		row_height = 16
		margin = 8
		swatch_width = 24
		label_offset = swatch_width + 6
		font_size = 9
		entry_count = len(_LEGEND_ENTRIES)
		box_width = 100
		box_height = entry_count * row_height + margin * 2

		# rect in local coords at (0,0); setPos for scene placement
		super().__init__(0, 0, box_width, box_height, parent)
		self.setPos(margin, margin)

		# semi-transparent dark background
		bg_color = QColor(0, 0, 0)
		bg_color.setAlpha(160)
		self.setBrush(QBrush(bg_color))
		self.setPen(QPen(Qt.PenStyle.NoPen))

		self._swatch_items = []
		self._label_items = []
		# use configured mono font for legend labels
		font = QFont(overlay_config.get_mono_font_family())
		font.setPointSize(font_size)

		for i, (style_key, label_text) in enumerate(_LEGEND_ENTRIES):
			style = overlay_config.get_prediction_style(style_key)
			# children positioned relative to local (0,0)
			row_y = margin + i * row_height

			# colored line swatch
			swatch = _SwatchLineItem(
				margin, row_y + row_height // 2,
				swatch_width, style, self,
			)
			self._swatch_items.append(swatch)

			# label text
			label_item = QGraphicsTextItem(label_text, self)
			label_item.setDefaultTextColor(QColor(style["color"]))
			label_item.setFont(font)
			label_item.setPos(margin + label_offset, row_y - 2)
			self._label_items.append(label_item)

		self.setZValue(100)

	#============================================

	def reposition(
		self,
		scene_width: float,
		scene_height: float,
		bbox_cx: float = -1,
		bbox_cy: float = -1,
	) -> None:
		"""Move the legend to the corner farthest from the tracked box.

		Uses setPos() for scene placement. Children stay at their local
		positions relative to (0,0) so no child repositioning is needed.

		Args:
			scene_width: Scene width in pixels.
			scene_height: Scene height in pixels.
			bbox_cx: Center x of the tracked bbox (or -1 if unknown).
			bbox_cy: Center y of the tracked bbox (or -1 if unknown).
		"""
		margin = 8
		box_w = self.rect().width()
		box_h = self.rect().height()

		# four candidate corners
		corners = [
			(margin, margin),
			(scene_width - box_w - margin, margin),
			(margin, scene_height - box_h - margin),
			(scene_width - box_w - margin, scene_height - box_h - margin),
		]

		if bbox_cx < 0 or bbox_cy < 0:
			# no bbox info: default to top-left
			best_x, best_y = corners[0]
		else:
			# pick corner with maximum distance from bbox center
			best_x, best_y = corners[0]
			best_dist = 0.0
			for cx, cy in corners:
				# distance from legend center to bbox center
				lx = cx + box_w / 2.0
				ly = cy + box_h / 2.0
				dist = (lx - bbox_cx) ** 2 + (ly - bbox_cy) ** 2
				if dist > best_dist:
					best_dist = dist
					best_x = cx
					best_y = cy

		# move to the chosen corner via setPos (children follow automatically)
		self.setPos(best_x, best_y)


#============================================


class KeyHintOverlay(QGraphicsRectItem):
	"""Persistent keybinding hint strip at the bottom of the frame view.

	Shows mode label and keybinding hints as a single line of text
	on a semi-transparent dark background. Always visible.
	"""

	def __init__(
		self,
		scene_width: float,
		scene_height: float,
		parent: QtWidgets.QGraphicsItem | None = None,
	) -> None:
		"""Initialize hint overlay spanning full width at bottom.

		Args:
			scene_width: Scene width in pixels.
			scene_height: Scene height in pixels.
			parent: Parent graphics item.
		"""
		strip_height = 20
		# rect in local coords; setPos for scene placement
		super().__init__(0, 0, scene_width, strip_height, parent)
		self.setPos(0, scene_height - strip_height)

		# semi-transparent dark background
		bg_color = QColor(0, 0, 0)
		bg_color.setAlpha(160)
		self.setBrush(QBrush(bg_color))
		self.setPen(QPen(Qt.PenStyle.NoPen))

		# text label as child item
		self._text_item = QGraphicsTextItem("", self)
		self._text_item.setDefaultTextColor(QColor(200, 200, 200))
		font = QFont(overlay_config.get_mono_font_family())
		font.setPointSize(9)
		self._text_item.setFont(font)
		self._text_item.setPos(8, -1)

		# render below legend (100) but above overlays
		self.setZValue(90)

	#============================================

	def update_text(self, mode_label: str, hints: str, mode_color: str = "#FFFFFF") -> None:
		"""Update the hint text with mode label and keybinding hints.

		Args:
			mode_label: Short mode name (e.g. "EDIT", "SEED").
			hints: Space-separated keybinding hints string.
			mode_color: Hex color for the mode label.
		"""
		html = (
			f"<span style='color: {mode_color}; font-weight: bold;'>"
			f"{mode_label}</span>"
			f"  <span style='color: #C0C0C0;'>{hints}</span>"
		)
		self._text_item.setHtml(html)

	#============================================

	def reposition(self, scene_width: float, scene_height: float) -> None:
		"""Reposition to bottom of scene on resize.

		Args:
			scene_width: Scene width in pixels.
			scene_height: Scene height in pixels.
		"""
		strip_height = 20
		self.setRect(0, 0, scene_width, strip_height)
		self.setPos(0, scene_height - strip_height)


#============================================


class _SwatchLineItem(QGraphicsRectItem):
	"""Short colored line sample for the prediction legend.

	Draws a horizontal line with the correct color and dash style
	inside a zero-height rect.
	"""

	def __init__(
		self,
		x: float,
		y: float,
		width: float,
		style: dict,
		parent: QtWidgets.QGraphicsItem | None = None,
	) -> None:
		"""Initialize swatch line.

		Args:
			x: Left x coordinate.
			y: Center y coordinate.
			width: Length of the swatch line.
			style: Prediction style dict with color and line_style keys.
			parent: Parent graphics item.
		"""
		super().__init__(x, y - 1, width, 2, parent)
		# invisible rect, we only draw the pen line via paint()
		self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
		self.setPen(QPen(Qt.PenStyle.NoPen))

		self._line_x = x
		self._line_y = y
		self._line_w = width
		self._color = QColor(style["color"])
		self._line_style = style.get("line_style", "solid")

	#============================================

	def paint(
		self,
		painter: QPainter,
		option: object,
		widget: object = None,
	) -> None:
		"""Draw the swatch line with correct dash style.

		Args:
			painter: QPainter instance.
			option: Style option (unused).
			widget: Target widget (unused).
		"""
		# enable anti-aliasing for smooth swatch rendering
		painter.setRenderHint(QPainter.RenderHint.Antialiasing)
		pen = QPen(self._color)
		pen.setWidthF(2.0)
		if self._line_style == "dashed":
			pen.setStyle(Qt.PenStyle.CustomDashLine)
			pen.setDashPattern([6, 10])
		elif self._line_style == "dotted":
			pen.setStyle(Qt.PenStyle.CustomDashLine)
			pen.setDashPattern([2, 6])
		painter.setPen(pen)
		painter.drawLine(
			int(self._line_x), int(self._line_y),
			int(self._line_x + self._line_w), int(self._line_y),
		)
