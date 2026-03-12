"""Action helpers for track runner UI.

Provides factory functions for creating standardized QAction instances.
"""

# Standard Library
# (none needed)

# PIP3 modules
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QStyle
from PySide6.QtCore import QObject

#============================================

def make_action(
	parent: QObject,
	name: str,
	key: str,
	tooltip: str,
	sp: QStyle.StandardPixmap | None = None,
) -> QAction:
	"""Create a standardized QAction.

	Creates a QAction with optional icon support and keyboard shortcuts.
	If a standard pixmap is provided, uses it as the icon; otherwise,
	uses the name as text.

	Args:
		parent: The parent QObject.
		name: Display name for the action (used as text if no icon).
		key: Keyboard shortcut string (e.g. 'Ctrl+S').
		tooltip: Tooltip text displayed to the user.
		sp: Optional QStyle.StandardPixmap for the icon. If None, uses
			text mode instead.

	Returns:
		A configured QAction instance.
	"""
	action = QAction(parent)

	if sp is not None:
		# Icon mode: set icon from standard pixmap
		action.setIcon(parent.style().standardIcon(sp))
	else:
		# Text mode: set text from name
		action.setText(name)

	# Always set shortcut and tooltip
	action.setShortcut(key)
	action.setToolTip(f'{tooltip} [{key}]')

	return action
