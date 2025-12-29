#!/usr/bin/env python3

"""
emwy_yaml_writer.py

Helpers to build EMWY v2 YAML text.
"""

# Standard Library
import decimal
from fractions import Fraction

#============================================

def yaml_quote(value: str) -> str:
	"""
	Quote a string for YAML output.

	Args:
		value: Raw string.

	Returns:
		str: YAML-quoted string.
	"""
	escaped = value.replace("\\", "\\\\").replace('"', '\\"')
	return f"\"{escaped}\""

#============================================

def format_speed(speed: float) -> str:
	"""
	Format speed for YAML output.

	Args:
		speed: Speed value.

	Returns:
		str: Formatted speed string.
	"""
	value = f"{speed:.3f}"
	value = value.rstrip('0').rstrip('.')
	if value == "":
		value = "1.0"
	return value

#============================================

def format_yaml_list(values: list) -> str:
	"""
	Format a list for YAML inline list output.

	Args:
		values: List of values to format.

	Returns:
		str: YAML inline list string.
	"""
	parts = []
	for value in values:
		parts.append(yaml_quote(str(value)))
	return ", ".join(parts)

#============================================

def parse_timecode(raw_time: str) -> decimal.Decimal:
	"""
	Parse a timecode string into seconds.

	Args:
		raw_time: Timecode string.

	Returns:
		decimal.Decimal: Time in seconds.
	"""
	if raw_time is None:
		raise RuntimeError("time value is required")
	value = str(raw_time).strip()
	if value == "":
		raise RuntimeError("time value is empty")
	if ':' not in value:
		return decimal.Decimal(value)
	parts = value.split(':')
	seconds = decimal.Decimal(parts.pop())
	minutes = decimal.Decimal(parts.pop())
	hours = decimal.Decimal(0)
	if len(parts) > 0:
		hours = decimal.Decimal(parts.pop())
	return hours * decimal.Decimal(3600) + minutes * decimal.Decimal(60) + seconds

#============================================

def parse_fps(raw_fps) -> Fraction:
	"""
	Parse fps string into a Fraction.

	Args:
		raw_fps: Fps value (string or number).

	Returns:
		Fraction: Fps as a fraction.
	"""
	if raw_fps is None:
		raise RuntimeError("fps is required")
	value = str(raw_fps)
	if '/' in value:
		parts = value.split('/')
		return Fraction(int(parts[0]), int(parts[1]))
	return Fraction(value)

#============================================

def round_half_up_fraction(value: Fraction) -> int:
	"""
	Round a fraction to the nearest int, half up.

	Args:
		value: Fraction to round.

	Returns:
		int: Rounded integer.
	"""
	numerator = value.numerator
	denominator = value.denominator
	whole = numerator // denominator
	remainder = numerator - (whole * denominator)
	if remainder * 2 > denominator:
		return whole + 1
	if remainder * 2 == denominator:
		return whole + 1
	return whole

#============================================

def frames_from_seconds(seconds: decimal.Decimal, fps: Fraction) -> int:
	"""
	Convert seconds to frames using half-up rounding.

	Args:
		seconds: Time in seconds.
		fps: Frames per second.

	Returns:
		int: Frame count.
	"""
	seconds_fraction = Fraction(str(seconds))
	frame_fraction = seconds_fraction * fps
	return round_half_up_fraction(frame_fraction)

#============================================

def format_duration_from_frames(frames: int, fps: Fraction) -> str:
	"""
	Format a frame count as seconds.

	Args:
		frames: Frame count.
		fps: Frames per second.

	Returns:
		str: Duration string.
	"""
	seconds_fraction = Fraction(frames, 1) / fps
	numerator = decimal.Decimal(seconds_fraction.numerator)
	denominator = decimal.Decimal(seconds_fraction.denominator)
	value = numerator / denominator
	result = f"{value:.6f}".rstrip('0').rstrip('.')
	if result == "":
		result = "0"
	return result

#============================================

def compute_output_duration_tc(start_tc: str, end_tc: str, fps: Fraction,
	speed: float) -> str:
	"""
	Compute output duration timecode for a segment.

	Args:
		start_tc: Start timecode.
		end_tc: End timecode.
		fps: Frames per second.
		speed: Playback speed.

	Returns:
		str: Duration timecode string.
	"""
	start_seconds = parse_timecode(start_tc)
	end_seconds = parse_timecode(end_tc)
	if end_seconds <= start_seconds:
		raise RuntimeError("segment end time must be after start time")
	duration_seconds = end_seconds - start_seconds
	input_frames = frames_from_seconds(duration_seconds, fps)
	speed_fraction = Fraction(str(decimal.Decimal(str(speed))))
	if speed_fraction <= 0:
		raise RuntimeError("speed must be positive")
	output_frames = round_half_up_fraction(
		Fraction(input_frames, 1) / speed_fraction
	)
	if output_frames <= 0:
		raise RuntimeError("segment duration is zero after speed change")
	return format_duration_from_frames(output_frames, fps)

#============================================

def format_seconds_duration(seconds: float, fps: Fraction) -> str:
	"""
	Format a seconds duration using frame rounding.

	Args:
		seconds: Duration in seconds.
		fps: Frames per second.

	Returns:
		str: Duration string.
	"""
	seconds_value = decimal.Decimal(str(seconds))
	frames = frames_from_seconds(seconds_value, fps)
	return format_duration_from_frames(frames, fps)

#============================================

def build_silence_timeline_yaml(input_file: str, output_media_file: str,
	profile: dict, asset_id: str, segments: list,
	silence_speed: float, content_speed: float, overlay_text_template: str = None,
	overlay_animate: dict = None, overlay_geometry: list = None,
	overlay_opacity: float = 0.9,
	overlay_id: str = "fast_forward", overlay_style_id: str = "fast_forward_style",
	overlay_font_size: int = 96, overlay_text_color: str = "#ffffff",
	intro_title: str = None, intro_duration: float = 2.0,
	intro_style_id: str = "intro_card_style", intro_font_size: int = 96,
	intro_text_color: str = "#ffffff", use_playback_styles: bool = True,
	playback_styles: dict = None, segment_style_map: dict = None,
	overlay_apply_style: str = None) -> str:
	"""
	Build an EMWY v2 YAML project using timeline segments.

	Args:
		input_file: Source media file.
		output_media_file: Output media file in YAML.
		profile: Profile metadata dict.
		asset_id: Asset id for the source media.
		segments: Ordered segments with kind, start_tc, end_tc.
		silence_speed: Speed for silence segments.
		content_speed: Speed for content segments.
		intro_title: Optional intro title card text.
		intro_duration: Intro title card duration in seconds.
		use_playback_styles: Whether to emit playback styles in assets.
		playback_styles: Mapping of playback style ids to speeds.
		segment_style_map: Mapping of segment kinds to playback style ids.
		overlay_apply_style: Playback style id for overlay apply, if needed.
		overlay_animate: Optional overlay animation mapping.

	Returns:
		str: YAML content.
	"""
	lines = []
	lines.append("emwy: 2")
	lines.append("")
	lines.append("profile:")
	lines.append(f"  fps: {yaml_quote(profile['fps'])}")
	lines.append(f"  resolution: [{profile['width']}, {profile['height']}]")
	audio_line = f"  audio: {{sample_rate: {profile['sample_rate']}, "
	audio_line += f"channels: {profile['channels']}}}"
	lines.append(audio_line)
	lines.append("")
	lines.append("assets:")
	lines.append("  video:")
	lines.append(f"    {asset_id}: {{file: {yaml_quote(input_file)}}}")
	if use_playback_styles:
		if not isinstance(playback_styles, dict) or len(playback_styles) == 0:
			raise RuntimeError("playback_styles is required for playback styles output")
		lines.append("  playback_styles:")
		for style_id, style_speed in playback_styles.items():
			lines.append(f"    {style_id}: {{speed: {format_speed(style_speed)}}}")
	if intro_title is not None:
		lines.append("  cards:")
		lines.append(f"    {intro_style_id}:")
		lines.append("      kind: title_card_style")
		lines.append(f"      font_size: {int(intro_font_size)}")
		lines.append(f"      text_color: {yaml_quote(intro_text_color)}")
	if overlay_text_template is not None:
		lines.append("  overlay_text_styles:")
		lines.append(f"    {overlay_style_id}:")
		lines.append("      kind: overlay_text_style")
		lines.append(f"      font_size: {int(overlay_font_size)}")
		lines.append(f"      text_color: {yaml_quote(overlay_text_color)}")
		lines.append("      background: {kind: transparent}")
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	if intro_title is not None:
		fps = parse_fps(profile['fps'])
		if intro_duration <= 0:
			raise RuntimeError("intro duration must be positive")
		intro_duration_tc = format_seconds_duration(intro_duration, fps)
		lines.append("    - generator:")
		lines.append("        kind: title_card")
		lines.append(f"        title: {yaml_quote(intro_title)}")
		lines.append(f"        duration: {yaml_quote(intro_duration_tc)}")
		lines.append(f"        style: {intro_style_id}")
		lines.append("        fill_missing: {audio: silence}")
	for segment in segments:
		speed = silence_speed if segment['kind'] == 'silence' else content_speed
		lines.append("    - source:")
		lines.append(f"        asset: {asset_id}")
		lines.append(f"        in: {yaml_quote(segment['start_tc'])}")
		lines.append(f"        out: {yaml_quote(segment['end_tc'])}")
		if use_playback_styles:
			style_id = segment.get('style')
			if style_id is None and isinstance(segment_style_map, dict):
				style_id = segment_style_map.get(segment['kind'])
			if style_id is None:
				raise RuntimeError("segment style is required when using playback styles")
			lines.append(f"        style: {style_id}")
		else:
			if speed != 1.0:
				lines.append(f"        video: {{speed: {format_speed(speed)}}}")
				lines.append(f"        audio: {{speed: {format_speed(speed)}}}")
	if overlay_text_template is not None:
		fps = parse_fps(profile['fps'])
		geometry = overlay_geometry or [0.1, 0.4, 0.8, 0.2]
		if len(geometry) != 4:
			raise RuntimeError("overlay geometry must include 4 values")
		lines.append("  overlays:")
		lines.append(f"    - id: {overlay_id}")
		geometry_line = "      geometry: ["
		geometry_line += f"{geometry[0]}, {geometry[1]}, {geometry[2]}, {geometry[3]}"
		geometry_line += "]"
		lines.append(geometry_line)
		lines.append(f"      opacity: {overlay_opacity}")
		lines.append("      apply:")
		if use_playback_styles:
			if overlay_apply_style is None:
				raise RuntimeError("overlay_apply_style is required for playback styles")
			lines.append("        kind: playback_style")
			lines.append(f"        style: {overlay_apply_style}")
		else:
			lines.append("        kind: speed")
			lines.append("        stream: video")
			lines.append(f"        min_speed: {format_speed(silence_speed)}")
		lines.append("      template:")
		lines.append("        generator:")
		lines.append("          kind: overlay_text")
		lines.append(f"          text: {yaml_quote(overlay_text_template)}")
		lines.append(f"          style: {overlay_style_id}")
		if overlay_animate is not None:
			if not isinstance(overlay_animate, dict):
				raise RuntimeError("overlay_animate must be a mapping")
			values = overlay_animate.get('values')
			if not isinstance(values, list) or len(values) == 0:
				raise RuntimeError("overlay_animate values must be a non-empty list")
			lines.append("          animate:")
			kind = overlay_animate.get('kind', 'cycle')
			lines.append(f"            kind: {kind}")
			lines.append(f"            values: [{format_yaml_list(values)}]")
			fps_value = overlay_animate.get('fps')
			if fps_value is not None:
				lines.append(f"            fps: {format_speed(float(fps_value))}")
			cadence_value = overlay_animate.get('cadence')
			if cadence_value is not None:
				lines.append(f"            cadence: {format_speed(float(cadence_value))}")
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: {yaml_quote(output_media_file)}")
	lines.append("")
	return "\n".join(lines)

#============================================
