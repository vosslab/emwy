"""Theme management for track runner UI.

Provides dark and light theme support with system detection.
"""

# Standard Library
# (none needed)

# PIP3 modules
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

#============================================

def apply_theme(app: QApplication, mode: str) -> None:
	"""Apply a theme to the application.

	Args:
		app: The QApplication instance.
		mode: Theme mode ('dark', 'light', or 'system').
	"""
	if mode == 'system':
		# Detect system theme from style hints
		try:
			color_scheme = app.styleHints().colorScheme()
			is_dark = (color_scheme == Qt.ColorScheme.Dark)
		except (AttributeError, RuntimeError):
			# Fallback: check palette brightness
			window_color = app.palette().color(QPalette.ColorRole.Window)
			is_dark = (window_color.value() < 128)
		mode = 'dark' if is_dark else 'light'

	if mode == 'dark':
		_apply_dark_theme(app)
	else:
		_apply_light_theme(app)

#============================================

def _apply_dark_theme(app: QApplication) -> None:
	"""Apply the dark theme palette and stylesheet.

	Args:
		app: The QApplication instance.
	"""
	palette = QPalette()

	# Define colors
	dark_bg = QColor('#0F0F23')
	light_text = QColor('#F8FAFC')
	dark_btn = QColor('#1E1E3A')
	highlight_color = QColor('#E11D48')
	white = QColor('#FFFFFF')

	# Set palette roles
	palette.setColor(QPalette.ColorRole.Window, dark_bg)
	palette.setColor(QPalette.ColorRole.Base, dark_bg)
	palette.setColor(QPalette.ColorRole.WindowText, light_text)
	palette.setColor(QPalette.ColorRole.Text, light_text)
	palette.setColor(QPalette.ColorRole.ButtonText, light_text)
	palette.setColor(QPalette.ColorRole.Button, dark_btn)
	palette.setColor(QPalette.ColorRole.Highlight, highlight_color)
	palette.setColor(QPalette.ColorRole.HighlightedText, white)

	app.setPalette(palette)

	# Apply stylesheet for scrollbars and tooltips
	qss = """
QScrollBar:vertical {
	background-color: #0F0F23;
	width: 12px;
}
QScrollBar::handle:vertical {
	background-color: #1E1E3A;
	border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
	background-color: #2E2E4A;
}
QTooltip {
	background-color: #1E1E3A;
	color: #F8FAFC;
	border: 1px solid #E11D48;
	padding: 2px;
}
"""
	app.setStyleSheet(qss)

#============================================

def _apply_light_theme(app: QApplication) -> None:
	"""Apply the light theme using Fusion style.

	Args:
		app: The QApplication instance.
	"""
	app.setStyle('Fusion')
	# Use Fusion's default light palette
	palette = app.palette()
	app.setPalette(palette)

#============================================

def get_current_mode() -> str:
	"""Get the current theme mode.

	Determines whether the current application theme is dark or light
	based on the brightness of the Window palette color.

	Returns:
		'dark' if the window color is dark, 'light' otherwise.
	"""
	app = QApplication.instance()
	if app is None:
		return 'light'

	window_color = app.palette().color(QPalette.ColorRole.Window)
	is_dark = (window_color.value() < 128)
	return 'dark' if is_dark else 'light'
