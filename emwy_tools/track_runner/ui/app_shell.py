"""Application shell for track runner UI.

Provides the main window with theme management.
"""

# Standard Library
# (none needed)

# PIP3 modules
from PySide6.QtWidgets import QMainWindow, QApplication

# local repo modules
import ui.theme as theme_module

#============================================

class AppShell(QMainWindow):
	"""Main application window with theme support.

	Inherits from QMainWindow and provides theme toggle and management
	functionality.
	"""

	def __init__(self) -> None:
		"""Initialize the application shell.

		Calls apply_theme with 'system' mode to detect and apply
		the appropriate theme for the current system.
		"""
		super().__init__()
		self._theme_mode: str = 'light'

		# Apply system theme on startup
		app = QApplication.instance()
		if app is not None:
			theme_module.apply_theme(app, 'system')
			self._theme_mode = theme_module.get_current_mode()

	#============================================

	def toggle_theme(self) -> None:
		"""Toggle between dark and light themes.

		Flips the current theme by determining the opposite mode
		and calling set_theme().
		"""
		new_mode = 'light' if self._theme_mode == 'dark' else 'dark'
		self.set_theme(new_mode)

	#============================================

	def set_theme(self, mode: str) -> None:
		"""Set the application theme.

		Args:
			mode: Theme mode ('dark' or 'light').
		"""
		app = QApplication.instance()
		if app is not None:
			theme_module.apply_theme(app, mode)
			self._theme_mode = theme_module.get_current_mode()
