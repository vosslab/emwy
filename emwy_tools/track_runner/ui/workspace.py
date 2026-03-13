"""Annotation workspace for track runner.

Provides the AnnotationWindow with mode toolbar and annotation controls.
"""

# Standard Library
# (none needed)

# PIP3 modules
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QProgressBar
from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPixmap, QColor

# local repo modules
import overlay_config
import common_tools.frame_filters as frame_filters_module
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

	def __init__(self, title: str = "Track Runner", initial_mode: str = "seed") -> None:
		"""Initialize the AnnotationWindow.

		Args:
			title: Window title to display.
			initial_mode: Starting mode ("seed", "target", or "edit").
		"""
		super().__init__()

		self.setWindowTitle(title)

		# Create frame view as central widget
		self._frame_view = FrameView()
		self.setCentralWidget(self._frame_view)

		# Mode colors loaded from overlay_styles.yaml
		self._mode_colors = {
			"seed": overlay_config.get_workspace_mode_color("seed"),
			"target": overlay_config.get_workspace_mode_color("target"),
			"edit": overlay_config.get_workspace_mode_color("edit"),
		}

		# Create annotation toolbar
		self._annotation_toolbar = self.addToolBar("Annotation")
		self._annotation_toolbar.setMovable(False)

		# Guard: set_controller() is called during init via setChecked signal;
		# skip teardown logic until all widgets exist
		self._init_complete = False

		# Initialize state before mode toolbar (setChecked fires _on_mode_changed)
		self._active_controller = None
		self._controller_widget_action = None
		self._current_mode = "seed"
		self._current_filter = "bilateral+clahe"
		self._raw_bgr = None

		# Create mode label before mode toolbar so _on_mode_changed can update it
		self._mode_label = QLabel("MODE: SEED")
		self._annotation_toolbar.addWidget(self._mode_label)

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

		# Set initial mode (defaults to seed)
		self._mode_actions[initial_mode].setChecked(True)

		# Apply initial mode color
		self._apply_mode_color(initial_mode)

		# Add display filter button to annotation toolbar
		self._filter_button = QPushButton("Filter: bilateral+clahe")
		self._filter_button.clicked.connect(self._cycle_filter)
		self._annotation_toolbar.addWidget(self._filter_button)

		# Create overlay visibility toolbar with checkable toggle actions
		self._overlay_toolbar = self.addToolBar("Overlays")
		self._overlay_toolbar.setMovable(False)
		# map of overlay key -> (label, color hex from predictions section)
		pred_colors = {
			"fwd": ("FWD", overlay_config.get_prediction_color("forward")),
			"bwd": ("BWD", overlay_config.get_prediction_color("backward")),
			"fused": ("REFINED", overlay_config.get_prediction_color("fused")),
			"consensus": ("AVG", overlay_config.get_prediction_color("consensus")),
			"legend": ("Legend", "#FFFFFF"),
		}
		self._overlay_actions: dict = {}
		for key, (label, color) in pred_colors.items():
			action = QAction(label, self)
			action.setCheckable(True)
			action.setChecked(True)
			# color-code the action icon with a small swatch
			action.setIcon(self._make_swatch_icon(color))
			action.setData(key)
			action.toggled.connect(self._on_overlay_toggled)
			self._overlay_toolbar.addAction(action)
			self._overlay_actions[key] = action

		# Add progress bar to the status bar
		self._progress_bar = QProgressBar()
		self._progress_bar.setMaximumWidth(200)
		self._progress_bar.setTextVisible(True)
		self._progress_bar.setFormat("%v / %m")
		self._progress_bar.setValue(0)
		self._progress_bar.setMaximum(0)
		# style progress bar for the dark theme
		mode_color = self._mode_colors.get(initial_mode, "#0D9488")
		self._progress_bar.setStyleSheet(
			"QProgressBar { max-height: 14px; border: none; "
			"background: #1A1A2E; border-radius: 2px; text-align: center; "
			"font-size: 10px; color: #F8FAFC; }"
			f"QProgressBar::chunk {{ border-radius: 2px; background: {mode_color}; }}"
		)
		self.statusBar().addPermanentWidget(self._progress_bar)

		# Restore window geometry from QSettings
		settings = QSettings("emwy", "AnnotationWindow")
		geometry = settings.value("geometry")
		if geometry is not None:
			self.restoreGeometry(geometry)

		# all widgets created; set_controller() can now do full teardown
		self._init_complete = True

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
		# Apply subtle color accent as top border to the frame view
		stylesheet = f"border-top: 2px solid {color};"
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

		# skip widget teardown during __init__ (setChecked fires before widgets exist)
		if not self._init_complete:
			return

		# Reset progress bar between controller swaps
		self._progress_bar.setValue(0)
		self._progress_bar.setMaximum(0)

		# Reset overlay toggles to all-visible on mode switch
		for action in self._overlay_actions.values():
			action.setChecked(True)

		# Remove previous controller widget from toolbar (keep mode_label and filter_button)
		if self._controller_widget_action is not None:
			self._annotation_toolbar.removeAction(self._controller_widget_action)
			self._controller_widget_action = None

		# Update persistent widget labels
		self._mode_label.setText(f"MODE: {self._current_mode.upper()}")
		self._filter_button.setText(f"Filter: {self._current_filter}")

		# Activate new controller if provided
		if self._active_controller is not None:
			if hasattr(self._active_controller, "activate"):
				self._active_controller.activate(self)
			# Add controller toolbar widget if available
			if hasattr(self._active_controller, "toolbar_widget"):
				widget = self._active_controller.toolbar_widget
				if widget is not None:
					self._controller_widget_action = self._annotation_toolbar.addWidget(widget)

	#============================================

	def _make_swatch_icon(self, hex_color: str) -> QIcon:
		"""Create a small colored swatch icon for toolbar actions.

		Args:
			hex_color: Hex color string like "#EF4444".

		Returns:
			QIcon with a filled colored square.
		"""
		size = 12
		pixmap = QPixmap(size, size)
		pixmap.fill(QColor(hex_color))
		icon = QIcon(pixmap)
		return icon

	#============================================

	def _on_overlay_toggled(self, checked: bool) -> None:
		"""Handle overlay toggle action.

		Args:
			checked: Whether the overlay is now enabled.
		"""
		action = self.sender()
		if action is None:
			return
		key = action.data()
		if self._active_controller is not None:
			if hasattr(self._active_controller, "set_overlay_enabled"):
				self._active_controller.set_overlay_enabled(key, checked)

	#============================================

	def set_progress(self, current: int, total: int) -> None:
		"""Update the progress bar with current/total values.

		Args:
			current: Current item number (1-based).
			total: Total number of items.
		"""
		self._progress_bar.setMaximum(total)
		self._progress_bar.setValue(current)
		# update chunk color to match current mode
		mode_color = self._mode_colors.get(self._current_mode, "#0D9488")
		self._progress_bar.setStyleSheet(
			"QProgressBar { max-height: 14px; border: none; "
			"background: #1A1A2E; border-radius: 2px; text-align: center; "
			"font-size: 10px; color: #F8FAFC; }"
			f"QProgressBar::chunk {{ border-radius: 2px; background: {mode_color}; }}"
		)

	#============================================

	def _cycle_filter(self) -> None:
		"""Advance to the next display filter preset and refresh the frame."""
		self._current_filter = frame_filters_module.get_next_preset(
			self._current_filter
		)
		self._filter_button.setText(f"Filter: {self._current_filter}")
		# re-apply filter to the current raw frame
		if self._raw_bgr is not None:
			filtered = frame_filters_module.apply_filter(
				self._raw_bgr, self._current_filter
			)
			self._frame_view.set_frame(filtered)

	#============================================

	def set_frame(self, bgr_array) -> None:
		"""Set the displayed frame.

		Stores the raw BGR array and applies the active display filter
		before forwarding to the frame view.

		Args:
			bgr_array: BGR numpy array for display.
		"""
		# keep raw reference for filter cycling
		self._raw_bgr = bgr_array
		filtered = frame_filters_module.apply_filter(
			bgr_array, self._current_filter
		)
		self._frame_view.set_frame(filtered)

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
