"""Status presenter for seed editor annotation display.

Shows seed status information including frame index, time, confidence,
and status color in the annotation toolbar.
"""

# Standard Library
# (none)

# PIP3 modules
from PySide6.QtCore import Qt
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
		mono_family = overlay_config.get_mono_font_family()
		self._label = QLabel("")
		self._label.setStyleSheet(
			f"font-family: '{mono_family}'; "
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
		interval_info: dict | None = None,
	) -> None:
		"""Update the status label with seed information.

		Args:
			seed: Seed dict with frame_index, status, and time_s keys.
			seed_index: 0-based index in the filtered list.
			total_seeds: Total number of seeds being reviewed.
			confidence: Optional dict with 'score' and 'label' keys.
			interval_info: Optional dict with severity, agreement, margin,
				and reasons keys from prediction diagnostics.
		"""
		frame_idx = int(seed.get("frame_index", 0))
		status = seed.get("status", "unknown")
		time_s = float(seed.get("time_s", 0.0))

		# primary info line
		text = (
			f"Seed {seed_index + 1}/{total_seeds}  "
			f"frame {frame_idx}  "
			f"{time_s:.1f}s  "
			f"{status}"
		)

		if confidence is not None:
			score = float(confidence.get("score", 0.0))
			text += f"  conf {score:.2f}"

		# severity badge with color from overlay_styles.yaml
		severity_html = ""
		if interval_info is not None:
			severity = interval_info.get("severity", "").lower()
			sev_style = overlay_config.get_severity_style(severity)
			sev_color = sev_style["color"]
			sev_label = sev_style["label"]
			severity_html = f"  <span style='color: {sev_color};'>[{sev_label}]</span>"
			# compact reason text
			reason_parts = self._format_reasons(interval_info)
			if reason_parts:
				reason_text = ", ".join(reason_parts)
				severity_html += (
					f" <span style='color: #94A3B8;'>({reason_text})</span>"
				)

		# use rich text if severity info is present
		if severity_html:
			# wrap the primary text as HTML and append severity
			status_color = self._get_status_color(status)
			html = (
				f"<span style='color: {status_color}; font-weight: bold;'>"
				f"{text}</span>{severity_html}"
			)
			self._label.setText(html)
			self._label.setTextFormat(Qt.TextFormat.RichText)
		else:
			self._label.setText(text)
			self._label.setTextFormat(Qt.TextFormat.PlainText)

		# Apply color based on status
		mono_family = overlay_config.get_mono_font_family()
		color = self._get_status_color(status)
		stylesheet = (
			f"font-family: '{mono_family}'; color: {color}; "
			"font-weight: bold; padding: 4px;"
		)
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

	def _format_reasons(self, interval_info: dict) -> list:
		"""Format interval_info reasons as compact human-readable labels.

		Args:
			interval_info: Dict with agreement, margin, and reasons keys.

		Returns:
			List of short reason strings.
		"""
		parts = []
		agreement = interval_info.get("agreement", 1.0)
		margin = interval_info.get("margin", 1.0)
		reasons = interval_info.get("reasons", [])
		# agreement level
		if agreement < 0.2:
			parts.append("low agree")
		elif agreement < 0.4:
			parts.append("mod agree")
		# margin level
		if margin < 0.2:
			parts.append("competitor")
		# specific failure reasons
		if "likely_identity_swap" in reasons:
			parts.append("id swap")
		return parts

	#============================================

	def clear(self) -> None:
		"""Clear the status label and reset styling."""
		self._label.setText("")
		self._label.setStyleSheet("padding: 4px;")
