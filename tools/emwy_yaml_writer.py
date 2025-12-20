#!/usr/bin/env python3

"""
emwy_yaml_writer.py

Helpers to build EMWY v2 YAML text.
"""

# Standard Library

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

def build_silence_timeline_yaml(input_file: str, output_media_file: str,
	profile: dict, asset_id: str, segments: list,
	silence_speed: float, content_speed: float) -> str:
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
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	for segment in segments:
		speed = silence_speed if segment['kind'] == 'silence' else content_speed
		lines.append("    - source:")
		lines.append(f"        asset: {asset_id}")
		lines.append(f"        in: {yaml_quote(segment['start_tc'])}")
		lines.append(f"        out: {yaml_quote(segment['end_tc'])}")
		if speed != 1.0:
			lines.append(f"        video: {{speed: {format_speed(speed)}}}")
			lines.append(f"        audio: {{speed: {format_speed(speed)}}}")
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: {yaml_quote(output_media_file)}")
	lines.append("")
	return "\n".join(lines)

#============================================
