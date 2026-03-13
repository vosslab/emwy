"""Overlay style configuration loader for track_runner.

Reads overlay_styles.yaml once, caches the result, and provides
typed lookups for colors, line styles, thickness tiers, and opacity.
All color accessors return hex strings for UI or BGR tuples for cv2.
"""

# Standard Library
import os
import re

# PIP3 modules
import yaml

#============================================
# module-level cache (loaded once per process)
_PALETTE_CACHE = None
_HEX_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
_VALID_LINE_STYLES = {"solid", "dashed", "dotted"}


#============================================
def hex_to_bgr(hex_color: str) -> tuple:
	"""Convert a hex color string to a BGR tuple for OpenCV.

	Args:
		hex_color: Color as "#RRGGBB".

	Returns:
		Tuple of (B, G, R) integer values.
	"""
	hex_color = hex_color.lstrip("#")
	r = int(hex_color[0:2], 16)
	g = int(hex_color[2:4], 16)
	b = int(hex_color[4:6], 16)
	bgr = (b, g, r)
	return bgr


#============================================
def _validate_palette(palette: dict) -> None:
	"""Validate palette values after loading.

	Checks hex colors, line_style values, thickness_tier references,
	and opacity ranges. Raises ValueError on any invalid entry.

	Args:
		palette: Parsed YAML dict.
	"""
	thickness_tiers = palette.get("thickness_tiers", {})

	# validate hex colors in seed_status
	for key, entry in palette.get("seed_status", {}).items():
		color = entry.get("color", "")
		if not _HEX_PATTERN.match(color):
			raise ValueError(f"seed_status.{key}.color invalid: {color}")
		tier = entry.get("thickness_tier")
		if tier is not None and tier not in thickness_tiers:
			raise ValueError(f"seed_status.{key}.thickness_tier unknown: {tier}")

	# validate predictions
	for key, entry in palette.get("predictions", {}).items():
		color = entry.get("color", "")
		if not _HEX_PATTERN.match(color):
			raise ValueError(f"predictions.{key}.color invalid: {color}")
		ls = entry.get("line_style")
		if ls is not None and ls not in _VALID_LINE_STYLES:
			raise ValueError(f"predictions.{key}.line_style invalid: {ls}")

	# validate tracking_source (flat hex values)
	for key, color in palette.get("tracking_source", {}).items():
		if not _HEX_PATTERN.match(str(color)):
			raise ValueError(f"tracking_source.{key} invalid: {color}")

	# validate workspace_mode (flat hex values)
	for key, color in palette.get("workspace_mode", {}).items():
		if not _HEX_PATTERN.match(str(color)):
			raise ValueError(f"workspace_mode.{key} invalid: {color}")

	# validate draw_mode_badge (flat hex values)
	for key, color in palette.get("draw_mode_badge", {}).items():
		if not _HEX_PATTERN.match(str(color)):
			raise ValueError(f"draw_mode_badge.{key} invalid: {color}")

	# validate preview_box
	pb = palette.get("preview_box", {})
	if pb:
		color = pb.get("color", "")
		if not _HEX_PATTERN.match(color):
			raise ValueError(f"preview_box.color invalid: {color}")
		opacity = pb.get("fill_opacity", 0.0)
		if not (0.0 <= float(opacity) <= 1.0):
			raise ValueError(f"preview_box.fill_opacity out of range: {opacity}")

	# validate encoder_overlay opacity values
	eo = palette.get("encoder_overlay", {})
	for key in ("box_opacity", "text_opacity"):
		val = eo.get(key, 0.0)
		if not (0.0 <= float(val) <= 1.0):
			raise ValueError(f"encoder_overlay.{key} out of range: {val}")

	# validate defaults
	defaults = palette.get("defaults", {})
	ls = defaults.get("line_style")
	if ls is not None and ls not in _VALID_LINE_STYLES:
		raise ValueError(f"defaults.line_style invalid: {ls}")
	opacity = defaults.get("fill_opacity", 0.0)
	if not (0.0 <= float(opacity) <= 1.0):
		raise ValueError(f"defaults.fill_opacity out of range: {opacity}")


#============================================
def _merge_defaults(palette: dict) -> None:
	"""Merge defaults into each style entry so consumers get complete dicts.

	Modifies palette in-place. Each seed_status and predictions entry
	inherits fill_opacity, line_style, and thickness_tier from defaults
	unless it provides its own value.

	Args:
		palette: Parsed and validated YAML dict.
	"""
	defaults = palette.get("defaults", {})
	default_fill = defaults.get("fill_opacity", 0.06)
	default_ls = defaults.get("line_style", "solid")
	default_tier = defaults.get("thickness_tier", "normal")

	# merge into seed_status entries
	for entry in palette.get("seed_status", {}).values():
		entry.setdefault("fill_opacity", default_fill)
		entry.setdefault("line_style", default_ls)
		entry.setdefault("thickness_tier", default_tier)

	# merge into predictions entries
	for entry in palette.get("predictions", {}).values():
		entry.setdefault("fill_opacity", default_fill)
		entry.setdefault("line_style", default_ls)
		entry.setdefault("thickness_tier", default_tier)


#============================================
def load_palette(yaml_path: str = "") -> dict:
	"""Load and cache the overlay styles palette from YAML.

	Args:
		yaml_path: Path to overlay_styles.yaml. Defaults to the file
			in the same directory as this module.

	Returns:
		Parsed and validated palette dict.
	"""
	global _PALETTE_CACHE
	if _PALETTE_CACHE is not None:
		return _PALETTE_CACHE

	if not yaml_path:
		# default: overlay_styles.yaml next to this module
		module_dir = os.path.dirname(os.path.abspath(__file__))
		yaml_path = os.path.join(module_dir, "overlay_styles.yaml")

	with open(yaml_path, "r") as fh:
		palette = yaml.safe_load(fh)

	_validate_palette(palette)
	_merge_defaults(palette)
	_PALETTE_CACHE = palette
	return palette


#============================================
def get_seed_status_color(status: str) -> str:
	"""Get hex color for a seed status.

	Args:
		status: Status string (visible, partial, approximate, not_in_frame).

	Returns:
		Hex color string like "#22C55E".
	"""
	palette = load_palette()
	entry = palette.get("seed_status", {}).get(status)
	if entry is None:
		return "#FFFFFF"
	color = entry.get("color", "#FFFFFF")
	return color


#============================================
def get_seed_status_bgr(status: str) -> tuple:
	"""Get BGR color tuple for a seed status (for cv2).

	Args:
		status: Status string.

	Returns:
		Tuple of (B, G, R) values.
	"""
	hex_color = get_seed_status_color(status)
	bgr = hex_to_bgr(hex_color)
	return bgr


#============================================
def get_seed_status_style(status: str) -> dict:
	"""Get full style dict for a seed status.

	Returns a dict with keys: color, line_style, thickness_tier, fill_opacity.
	Returns defaults for unknown statuses.

	Args:
		status: Status string.

	Returns:
		Style dict with color, line_style, thickness_tier, fill_opacity keys.
	"""
	palette = load_palette()
	entry = palette.get("seed_status", {}).get(status)
	if entry is None:
		defaults = palette.get("defaults", {})
		style = {
			"color": "#FFFFFF",
			"line_style": defaults.get("line_style", "solid"),
			"thickness_tier": defaults.get("thickness_tier", "normal"),
			"fill_opacity": defaults.get("fill_opacity", 0.06),
		}
		return style
	# entry already has defaults merged in
	style = {
		"color": entry.get("color", "#FFFFFF"),
		"line_style": entry.get("line_style", "solid"),
		"thickness_tier": entry.get("thickness_tier", "normal"),
		"fill_opacity": entry.get("fill_opacity", 0.06),
	}
	return style


#============================================
def get_prediction_color(direction: str) -> str:
	"""Get hex color for a prediction direction.

	Args:
		direction: "forward" or "backward".

	Returns:
		Hex color string.
	"""
	palette = load_palette()
	entry = palette.get("predictions", {}).get(direction, {})
	color = entry.get("color", "#FFFFFF")
	return color


#============================================
def get_prediction_bgr(direction: str) -> tuple:
	"""Get BGR color tuple for a prediction direction (for cv2).

	Args:
		direction: "forward" or "backward".

	Returns:
		Tuple of (B, G, R) values.
	"""
	hex_color = get_prediction_color(direction)
	bgr = hex_to_bgr(hex_color)
	return bgr


#============================================
def get_prediction_style(direction: str) -> dict:
	"""Get full style dict for a prediction direction.

	Args:
		direction: "forward" or "backward".

	Returns:
		Style dict with color, line_style, thickness_tier, fill_opacity keys.
	"""
	palette = load_palette()
	entry = palette.get("predictions", {}).get(direction, {})
	defaults = palette.get("defaults", {})
	style = {
		"color": entry.get("color", "#FFFFFF"),
		"line_style": entry.get("line_style", defaults.get("line_style", "solid")),
		"thickness_tier": entry.get("thickness_tier", defaults.get("thickness_tier", "normal")),
		"fill_opacity": entry.get("fill_opacity", defaults.get("fill_opacity", 0.06)),
	}
	return style


#============================================
def get_source_bgr(source: str, seed_status: str = "") -> tuple:
	"""Get BGR color for a tracking source label.

	Seed-type sources (human, seed) are colored by annotation status
	rather than by tracking source, because on seed frames the annotation
	status is more informative than the generic source label.

	Args:
		source: Frame source string from tracker pipeline.
		seed_status: Seed annotation status (visible, partial, approximate).

	Returns:
		Tuple of (B, G, R) color values.
	"""
	# seed sources: color by annotation status
	if source in ("human", "seed"):
		bgr = get_seed_status_bgr(seed_status)
		return bgr

	palette = load_palette()
	hex_color = palette.get("tracking_source", {}).get(source)
	if hex_color is None:
		# fall back to lost color
		hex_color = palette.get("tracking_source", {}).get("lost", "#C80000")
	bgr = hex_to_bgr(hex_color)
	return bgr


#============================================
def get_workspace_mode_color(mode: str) -> str:
	"""Get hex color for a workspace mode.

	Args:
		mode: Mode name ("seed", "target", or "edit").

	Returns:
		Hex color string.
	"""
	palette = load_palette()
	color = palette.get("workspace_mode", {}).get(mode, "#0D9488")
	return color


#============================================
def get_draw_mode_badge_color(mode: str) -> str:
	"""Get hex color for a draw mode badge.

	Args:
		mode: Draw mode ("approximate" or "partial").

	Returns:
		Hex color string.
	"""
	palette = load_palette()
	color = palette.get("draw_mode_badge", {}).get(mode, "#FFFFFF")
	return color


#============================================
def get_preview_box_color() -> str:
	"""Get hex color for the preview box.

	Returns:
		Hex color string.
	"""
	palette = load_palette()
	color = palette.get("preview_box", {}).get("color", "#22C55E")
	return color


#============================================
def get_preview_box_fill_opacity() -> float:
	"""Get fill opacity for the preview box.

	Returns:
		Opacity value between 0.0 and 1.0.
	"""
	palette = load_palette()
	opacity = float(palette.get("preview_box", {}).get("fill_opacity", 0.24))
	return opacity


#============================================
def get_encoder_overlay_opacity(kind: str) -> float:
	"""Get encoder overlay opacity for box or text blending.

	Args:
		kind: "box" or "text".

	Returns:
		Opacity value between 0.0 and 1.0.
	"""
	palette = load_palette()
	key = f"{kind}_opacity"
	opacity = float(palette.get("encoder_overlay", {}).get(key, 0.55))
	return opacity


#============================================
def get_thickness_scale(tier: str) -> float:
	"""Get the thickness multiplier for a named tier.

	Args:
		tier: Tier name ("normal" or "heavy").

	Returns:
		Scale multiplier (e.g. 1.0 for normal, 2.0 for heavy).
	"""
	palette = load_palette()
	scale = float(palette.get("thickness_tiers", {}).get(tier, 1.0))
	return scale


#============================================
def _resolve_font_family(comma_list: str) -> str:
	"""Try each font in a comma-separated list via QFontDatabase.

	Falls back to the last entry if none are found.

	Args:
		comma_list: Comma-separated font family names.

	Returns:
		First available font family name.
	"""
	from PySide6.QtGui import QFontDatabase
	candidates = [f.strip() for f in comma_list.split(",")]
	for name in candidates:
		if QFontDatabase.hasFamily(name):
			return name
	# last entry is the generic fallback
	last = candidates[-1] if candidates else "sans-serif"
	return last


#============================================
def get_ui_font_family() -> str:
	"""Get the best available UI font family.

	Returns:
		Font family name string.
	"""
	palette = load_palette()
	raw = palette.get("fonts", {}).get(
		"ui_family", "Helvetica Neue, Helvetica, Arial, sans-serif"
	)
	family = _resolve_font_family(raw)
	return family


#============================================
def get_mono_font_family() -> str:
	"""Get the best available monospace font family.

	Returns:
		Font family name string.
	"""
	palette = load_palette()
	raw = palette.get("fonts", {}).get(
		"mono_family", "Menlo, SF Mono, Consolas, monospace"
	)
	family = _resolve_font_family(raw)
	return family


#============================================
def get_overlay_font_size() -> int:
	"""Get the overlay font size in points.

	Returns:
		Font size integer.
	"""
	palette = load_palette()
	size = int(palette.get("fonts", {}).get("overlay_size", 10))
	return size


#============================================
def get_status_font_size() -> int:
	"""Get the status bar font size in points.

	Returns:
		Font size integer.
	"""
	palette = load_palette()
	size = int(palette.get("fonts", {}).get("status_size", 12))
	return size


#============================================
def get_theme_color(key: str) -> str:
	"""Get a theme color by key.

	Args:
		key: Theme color key (surface, surface_raised, border_subtle, etc).

	Returns:
		Hex color string.
	"""
	palette = load_palette()
	defaults = {
		"surface": "#1A1A2E",
		"surface_raised": "#25253E",
		"border_subtle": "#2A2A44",
		"text_secondary": "#94A3B8",
		"text_muted": "#64748B",
	}
	color = palette.get("theme", {}).get(key, defaults.get(key, "#FFFFFF"))
	return color


#============================================
def get_severity_style(level: str) -> dict:
	"""Get severity display style for a given level.

	Args:
		level: Severity level ("high", "medium", or "low").

	Returns:
		Dict with "color" and "label" keys.
	"""
	palette = load_palette()
	defaults = {
		"high": {"color": "#EF4444", "label": "HIGH"},
		"medium": {"color": "#F59E0B", "label": "MED"},
		"low": {"color": "#22C55E", "label": "LOW"},
	}
	entry = palette.get("severity", {}).get(level, defaults.get(level, {}))
	style = {
		"color": entry.get("color", "#FFFFFF"),
		"label": entry.get("label", level.upper()),
	}
	return style
