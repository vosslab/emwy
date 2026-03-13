"""Zoom control widget for the track runner status bar."""

# Standard Library
# (none)

# PIP3 modules
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QSlider

# Slider range maps to zoom percent (10 = 0.1x, 3000 = 30.0x)
SLIDER_MIN = 10
SLIDER_MAX = 3000
SLIDER_DEFAULT = 100
SLIDER_STEP = 5

#============================================


class ZoomControls(QWidget):
	"""Horizontal zoom control bar with buttons, label, and slider.

	Provides zoom in/out buttons, a percentage label, a fit-to-view button,
	and a slider for direct zoom control. Designed for the status bar.
	"""

	# emitted when the user clicks zoom-in button
	zoom_in_clicked = Signal()
	# emitted when the user clicks zoom-out button
	zoom_out_clicked = Signal()
	# emitted when the user clicks fit-to-view button
	zoom_to_fit_clicked = Signal()
	# emitted when the slider value changes (carries zoom percent as int)
	zoom_slider_changed = Signal(int)

	def __init__(self, parent: QWidget | None = None) -> None:
		"""Initialize ZoomControls.

		Args:
			parent: Parent widget.
		"""
		super().__init__(parent)

		layout = QHBoxLayout(self)
		layout.setContentsMargins(4, 2, 4, 2)
		layout.setSpacing(4)

		# Zoom out button
		self._btn_out = QPushButton("-")
		self._btn_out.setFixedWidth(28)
		self._btn_out.setToolTip("Zoom out")
		self._btn_out.clicked.connect(self.zoom_out_clicked.emit)
		layout.addWidget(self._btn_out)

		# Percentage label showing current zoom
		self._label = QLabel("100%")
		self._label.setMinimumWidth(48)
		self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
		layout.addWidget(self._label)

		# Zoom in button
		self._btn_in = QPushButton("+")
		self._btn_in.setFixedWidth(28)
		self._btn_in.setToolTip("Zoom in")
		self._btn_in.clicked.connect(self.zoom_in_clicked.emit)
		layout.addWidget(self._btn_in)

		# Fit-to-view button
		self._btn_fit = QPushButton("Fit")
		self._btn_fit.setToolTip("Fit image to window")
		self._btn_fit.clicked.connect(self.zoom_to_fit_clicked.emit)
		layout.addWidget(self._btn_fit)

		# Horizontal zoom slider
		self._slider = QSlider(Qt.Orientation.Horizontal)
		self._slider.setRange(SLIDER_MIN, SLIDER_MAX)
		self._slider.setSingleStep(SLIDER_STEP)
		self._slider.setValue(SLIDER_DEFAULT)
		self._slider.setFixedWidth(120)
		self._slider.setToolTip("Drag to zoom")
		self._slider.valueChanged.connect(self._on_slider_changed)
		layout.addWidget(self._slider)

	#============================================

	def _on_slider_changed(self, value: int) -> None:
		"""Forward slider value changes as zoom_slider_changed signal.

		Args:
			value: Slider value (zoom percent as integer).
		"""
		self.zoom_slider_changed.emit(value)

	#============================================

	def update_zoom_display(self, percent: float) -> None:
		"""Update label and slider to reflect the current zoom percentage.

		Blocks slider signals to avoid feedback loops when the zoom
		was triggered externally (wheel, keyboard, or programmatic).

		Args:
			percent: Current zoom as a percentage (e.g. 150.0 for 1.5x).
		"""
		# Update the text label
		label_text = f"{percent:.0f}%"
		self._label.setText(label_text)

		# Update slider position without emitting signals
		clamped = max(SLIDER_MIN, min(SLIDER_MAX, int(percent)))
		self._slider.blockSignals(True)
		self._slider.setValue(clamped)
		self._slider.blockSignals(False)
