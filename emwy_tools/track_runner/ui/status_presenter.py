"""Status presenter for seed editor annotation display.

Shows seed status information including frame index, time, confidence,
and status color in the annotation toolbar.
"""

# Standard Library
# (none)

# PIP3 modules
from PySide6.QtWidgets import QLabel

# local repo modules
import overlay_config

#============================================

class StatusPresenter:
	"""Displays seed status information in the annotation toolbar.

	Updates status label with seed index, frame information, and confidence
	scores. Color-codes status for quick visual feedback.
	"""

	def __init__(self) -> None:
		"""Initialize the StatusPresenter.

		Creates a monospace QLabel with styling for status display.
		"""
		self._label = QLabel("")
		self._label.setStyleSheet(
			"font-family: monospace; "
			"font-size: 11px; "
			"padding: 4px; "
		)

	#============================================

	def get_widget(self) -> QLabel:
		"""Get the status label widget.

		Returns:
			The QLabel widget for display in the toolbar.
		"""
		return self._label

	#============================================

	def update(
		self,
		seed: dict,
		seed_index: int,
		total_seeds: int,
		confidence: dict | None = None,
	) -> None:
		"""Update the status label with seed information.

		Args:
			seed: Seed dict with frame_index, status, and time_s keys.
			seed_index: 0-based index in the filtered list.
			total_seeds: Total number of seeds being reviewed.
			confidence: Optional dict with 'score' and 'label' keys.
		"""
		frame_idx = int(seed.get("frame_index", 0))
		status = seed.get("status", "unknown")
		time_s = float(seed.get("time_s", 0.0))

		text = (
			f"Seed {seed_index + 1}/{total_seeds}  "
			f"frame {frame_idx}  "
			f"{time_s:.1f}s  "
			f"{status}"
		)

		if confidence is not None:
			score = float(confidence.get("score", 0.0))
			label = confidence.get("label", "unknown")
			text += f"  conf {score:.2f} ({label})"

		self._label.setText(text)

		# Apply color based on status
		color = self._get_status_color(status)
		stylesheet = f"color: {color}; font-weight: bold; padding: 4px;"
		self._label.setStyleSheet(stylesheet)

	#============================================

	def _get_status_color(self, status: str) -> str:
		"""Map status to a display color from overlay_styles.yaml.

		Args:
			status: Status string from the seed.

		Returns:
			Hex color string for the status.
		"""
		color = overlay_config.get_seed_status_color(status)
		return color

	#============================================

	def clear(self) -> None:
		"""Clear the status label and reset styling."""
		self._label.setText("")
		self._label.setStyleSheet("padding: 4px;")
