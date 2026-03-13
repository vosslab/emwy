"""Theme management for track runner UI.

Provides dark and light theme support with system detection.
"""

# Standard Library
# (none needed)

# PIP3 modules
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor, QFont
from PySide6.QtCore import Qt

# local repo modules
import overlay_config

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

	# Set app-wide default font with no-hinting for Retina clarity
	ui_font = QFont(overlay_config.get_ui_font_family())
	ui_font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
	app.setFont(ui_font)

	# Load theme colors from overlay_styles.yaml
	surface = overlay_config.get_theme_color("surface")
	surface_raised = overlay_config.get_theme_color("surface_raised")
	border_subtle = overlay_config.get_theme_color("border_subtle")

	# Apply stylesheet for depth, polish, scrollbars, and tooltips
	qss = f"""
QToolBar {{
	background: {surface};
	border-bottom: 1px solid {border_subtle};
	padding: 2px;
	spacing: 4px;
}}
QPushButton {{
	border: 1px solid {border_subtle};
	border-radius: 4px;
	padding: 4px 8px;
	background: {surface_raised};
}}
QPushButton:hover {{
	background: #2E2E4A;
}}
QPushButton:pressed {{
	background: #3E3E5A;
}}
QPushButton:checked {{
	background: #3E3E5A;
	border: 1px solid #8B5CF6;
}}
QStatusBar {{
	border-top: 1px solid {border_subtle};
	background: {surface};
}}
QScrollBar:vertical {{
	background-color: #0F0F23;
	width: 12px;
}}
QScrollBar::handle:vertical {{
	background-color: #1E1E3A;
	border-radius: 6px;
}}
QScrollBar::handle:vertical:hover {{
	background-color: #2E2E4A;
}}
QToolTip {{
	background-color: #1E1E3A;
	color: #F8FAFC;
	border: 1px solid #E11D48;
	padding: 2px;
}}
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
