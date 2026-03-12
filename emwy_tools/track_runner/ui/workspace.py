"""Annotation workspace for track runner.

Provides the AnnotationWindow with mode toolbar and annotation controls.
"""

# Standard Library
# (none needed)

# PIP3 modules
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QActionGroup

# local repo modules
import ui.frame_view as frame_view_module
import ui.app_shell as app_shell_module

FrameView = frame_view_module.FrameView
AppShell = app_shell_module.AppShell

#============================================

class AnnotationWindow(AppShell):
	"""Main annotation workspace with mode selection and frame display.

	Provides a window with mode toolbar (Seed, Target, Edit), frame view,
	and annotation controls. Manages controller activation/deactivation
	and persists window geometry via QSettings.
	"""

	def __init__(self, title: str = "Track Runner") -> None:
		"""Initialize the AnnotationWindow.

		Args:
			title: Window title to display.
		"""
		super().__init__()

		self.setWindowTitle(title)

		# Create frame view as central widget
		self._frame_view = FrameView()
		self.setCentralWidget(self._frame_view)

		# Mode colors mapping
		self._mode_colors = {
			"seed": "#0D9488",
			"target": "#3B82F6",
			"edit": "#8B5CF6",
		}

		# Create mode toolbar
		self._mode_toolbar = self.addToolBar("Modes")
		self._mode_toolbar.setMovable(False)

		# Create mode action group (mutually exclusive)
		self._mode_group = QActionGroup(self)
		self._mode_group.setExclusive(True)

		self._mode_actions = {}
		for mode in ["seed", "target", "edit"]:
			action = QAction(mode.capitalize(), self)
			action.setCheckable(True)
			action.setData(mode)
			action.toggled.connect(self._on_mode_changed)
			self._mode_group.addAction(action)
			self._mode_toolbar.addAction(action)
			self._mode_actions[mode] = action

		# Set Seed mode as default
		self._mode_actions["seed"].setChecked(True)

		# Create annotation toolbar
		self._annotation_toolbar = self.addToolBar("Annotation")
		self._annotation_toolbar.setMovable(False)

		# Add mode label to annotation toolbar
		self._mode_label = QLabel("MODE: SEED")
		self._annotation_toolbar.addWidget(self._mode_label)

		# Initialize state
		self._active_controller = None
		self._current_mode = "seed"

		# Apply initial mode color
		self._apply_mode_color("seed")

		# Restore window geometry from QSettings
		settings = QSettings("emwy", "AnnotationWindow")
		geometry = settings.value("geometry")
		if geometry is not None:
			self.restoreGeometry(geometry)

	#============================================

	def _on_mode_changed(self, checked: bool) -> None:
		"""Handle mode button toggled signal.

		Determines which mode is now active, updates UI, and deactivates
		current controller.

		Args:
			checked: True if action is now checked.
		"""
		# Find which mode action is now checked
		current_mode = None
		for mode, action in self._mode_actions.items():
			if action.isChecked():
				current_mode = mode
				break

		if current_mode is None:
			return

		# Update mode label
		mode_text = current_mode.upper()
		self._mode_label.setText(f"MODE: {mode_text}")

		# Apply mode color to frame view
		self._apply_mode_color(current_mode)

		# Deactivate current controller
		self.set_controller(None)

		# Update internal state
		self._current_mode = current_mode

	#============================================

	def _apply_mode_color(self, mode: str) -> None:
		"""Apply mode-specific accent color to frame view.

		Args:
			mode: Mode name ("seed", "target", or "edit").
		"""
		color = self._mode_colors.get(mode, "#0D9488")
		# Apply color as border to the frame view
		stylesheet = f"border: 3px solid {color};"
		self._frame_view.setStyleSheet(stylesheet)

	#============================================

	def set_controller(self, controller) -> None:
		"""Set or clear the active controller.

		Deactivates the previous controller, activates the new one,
		and swaps annotation toolbar widgets.

		Args:
			controller: Controller instance with optional activate/deactivate
				methods and toolbar_widget attribute, or None.
		"""
		# Deactivate previous controller
		if self._active_controller is not None:
			if hasattr(self._active_controller, "deactivate"):
				self._active_controller.deactivate()

		# Store new controller
		self._active_controller = controller

		# Clear annotation toolbar and add new controller widgets
		for action in self._annotation_toolbar.actions():
			self._annotation_toolbar.removeAction(action)
		# Re-add mode label
		self._mode_label = QLabel(f"MODE: {self._current_mode.upper()}")
		self._annotation_toolbar.addWidget(self._mode_label)

		# Activate new controller if provided
		if self._active_controller is not None:
			if hasattr(self._active_controller, "activate"):
				self._active_controller.activate(self)
			# Add controller toolbar widget if available
			if hasattr(self._active_controller, "toolbar_widget"):
				widget = self._active_controller.toolbar_widget
				if widget is not None:
					self._annotation_toolbar.addWidget(widget)

	#============================================

	def set_frame(self, bgr_array) -> None:
		"""Set the displayed frame.

		Args:
			bgr_array: BGR numpy array for display.
		"""
		self._frame_view.set_frame(bgr_array)

	#============================================

	def get_frame_view(self) -> FrameView:
		"""Get the frame view widget.

		Returns:
			The FrameView instance.
		"""
		return self._frame_view

	#============================================

	def closeEvent(self, event) -> None:
		"""Save window state on close.

		Args:
			event: Close event.
		"""
		settings = QSettings("emwy", "AnnotationWindow")
		settings.setValue("geometry", self.saveGeometry())
		super().closeEvent(event)

	#============================================

	def run(self) -> None:
		"""Show window and start event loop.

		Convenience method for starting the application.
		"""
		self.show()
		app = QApplication.instance()
		if app is not None:
			app.exec()
