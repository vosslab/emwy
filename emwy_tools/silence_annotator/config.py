"""
config.py

Config loading, defaults, and validation for silence annotator.
"""

# Standard Library
import os

# PIP3 modules
import yaml

# local repo modules
import detection
import emwy_yaml_writer

#============================================

def parse_overlay_geometry(value: str) -> list:
	"""
	Parse overlay geometry string into list of floats.

	Args:
		value: Geometry string "x,y,w,h".

	Returns:
		list: Parsed geometry values.
	"""
	if value is None:
		raise RuntimeError("overlay geometry must be provided")
	parts = [item.strip() for item in value.split(',') if item.strip() != ""]
	if len(parts) != 4:
		raise RuntimeError("overlay geometry must be four comma-separated values")
	values = [float(item) for item in parts]
	for number in values:
		if number < 0 or number > 1:
			raise RuntimeError("overlay geometry values must be between 0 and 1")
	return values

#============================================

def coerce_bool(value, config_path: str, key_path: str) -> bool:
	"""
	Coerce a value to bool.

	Args:
		value: Raw value.
		config_path: Config file path.
		key_path: Key path string.

	Returns:
		bool: Coerced boolean.
	"""
	if isinstance(value, bool):
		return value
	if isinstance(value, int):
		return bool(value)
	if isinstance(value, str):
		normalized = value.strip().lower()
		if normalized in ("true", "yes", "1", "on"):
			return True
		if normalized in ("false", "no", "0", "off"):
			return False
	raise RuntimeError(f"config {config_path}: {key_path} must be a boolean")

#============================================

def coerce_float(value, config_path: str, key_path: str) -> float:
	"""
	Coerce a value to float.

	Args:
		value: Raw value.
		config_path: Config file path.
		key_path: Key path string.

	Returns:
		float: Coerced float.
	"""
	if isinstance(value, (int, float)):
		return float(value)
	if isinstance(value, str):
		return float(value)
	raise RuntimeError(f"config {config_path}: {key_path} must be a number")

#============================================

def coerce_int(value, config_path: str, key_path: str) -> int:
	"""
	Coerce a value to int.

	Args:
		value: Raw value.
		config_path: Config file path.
		key_path: Key path string.

	Returns:
		int: Coerced int.
	"""
	if isinstance(value, int):
		return value
	if isinstance(value, float):
		return int(value)
	if isinstance(value, str):
		return int(float(value))
	raise RuntimeError(f"config {config_path}: {key_path} must be an integer")

#============================================

def normalize_geometry(value, config_path: str, key_path: str) -> list:
	"""
	Normalize overlay geometry into a list of floats.

	Args:
		value: Raw geometry value.
		config_path: Config file path.
		key_path: Key path string.

	Returns:
		list: Geometry list [x, y, w, h].
	"""
	if isinstance(value, str):
		values = parse_overlay_geometry(value)
	elif isinstance(value, (list, tuple)):
		if len(value) != 4:
			raise RuntimeError(f"config {config_path}: {key_path} must have 4 values")
		values = [coerce_float(item, config_path, key_path) for item in value]
	else:
		raise RuntimeError(f"config {config_path}: {key_path} must be list or string")
	for number in values:
		if number < 0 or number > 1:
			raise RuntimeError(f"config {config_path}: {key_path} values must be 0..1")
	return values

#============================================

def default_config() -> dict:
	"""
	Build the default config dictionary.

	Returns:
		dict: Default configuration values.
	"""
	return {
		'silence_annotator': 1,
		'settings': {
			'detection': {
				'threshold_db': -40.0,
				'min_silence': 3.0,
				'min_content': 1.5,
			'frame_seconds': 0.25,
			'hop_seconds': 0.05,
			'smooth_frames': 5,
		},
		'trim_leading_silence': True,
		'trim_trailing_silence': True,
		'speeds': {
			'silence': 10.0,
			'content': 1.0,
			},
			'overlay': {
				'enabled': True,
				'text_template': "Fast Forward {speed}X {animate}",
				'geometry': [0.1, 0.4, 0.8, 0.2],
				'opacity': 0.9,
				'font_size': 96,
				'text_color': "#ffffff",
				'animate': {
					'kind': 'cycle',
					'values': ['>', '>>', '>>>'],
					'cadence': 0.5,
				},
			},
			'title_card': {
				'enabled': True,
				'duration': 2.0,
				'text_template': "{name}",
				'font_size': 96,
				'text_color': "#ffffff",
			},
			'auto_threshold': {
				'enabled': False,
				'step_db': detection.AUTO_THRESHOLD_STEP_DB,
				'max_db': detection.AUTO_THRESHOLD_MAX_DB,
				'max_tries': detection.AUTO_THRESHOLD_MAX_TRIES,
			},
		},
	}

#============================================

def default_config_path(input_file: str) -> str:
	"""
	Build the default config path based on the input file.

	Args:
		input_file: Input file path.

	Returns:
		str: Config file path.
	"""
	return f"{input_file}.silence.config.yaml"

#============================================

def build_config_text(config: dict) -> str:
	"""
	Build YAML text for the config file.

	Args:
		config: Config dictionary.

	Returns:
		str: YAML content.
	"""
	settings = config.get('settings', {})
	detection_settings = settings.get('detection', {})
	speeds = settings.get('speeds', {})
	overlay = settings.get('overlay', {})
	trim_edges = settings.get('trim_edges')
	trim_leading = settings.get('trim_leading_silence')
	trim_trailing = settings.get('trim_trailing_silence')
	if trim_leading is None:
		trim_leading = trim_edges if trim_edges is not None else True
	if trim_trailing is None:
		trim_trailing = trim_edges if trim_edges is not None else True
	title_card = settings.get('title_card', {})
	auto_threshold = settings.get('auto_threshold', {})
	geometry = overlay.get('geometry', [0.1, 0.4, 0.8, 0.2])
	lines = []
	lines.append("silence_annotator: 1")
	lines.append("settings:")
	lines.append("  detection:")
	lines.append(f"    threshold_db: {detection_settings.get('threshold_db', -40.0)}")
	lines.append(f"    min_silence: {detection_settings.get('min_silence', 3.0)}")
	lines.append(f"    min_content: {detection_settings.get('min_content', 1.5)}")
	lines.append(f"    frame_seconds: {detection_settings.get('frame_seconds', 0.25)}")
	lines.append(f"    hop_seconds: {detection_settings.get('hop_seconds', 0.05)}")
	lines.append(f"    smooth_frames: {detection_settings.get('smooth_frames', 5)}")
	lines.append(f"  trim_leading_silence: {str(bool(trim_leading)).lower()}")
	lines.append(f"  trim_trailing_silence: {str(bool(trim_trailing)).lower()}")
	lines.append("  speeds:")
	lines.append(f"    silence: {speeds.get('silence', 10.0)}")
	lines.append(f"    content: {speeds.get('content', 1.0)}")
	lines.append("  overlay:")
	lines.append(f"    enabled: {str(bool(overlay.get('enabled', True))).lower()}")
	lines.append(
		f"    text_template: \"{overlay.get('text_template', 'Fast Forward {speed}X {animate}')}\""
	)
	lines.append(
		f"    geometry: [{geometry[0]}, {geometry[1]}, {geometry[2]}, {geometry[3]}]"
	)
	lines.append(f"    opacity: {overlay.get('opacity', 0.9)}")
	lines.append(f"    font_size: {overlay.get('font_size', 96)}")
	lines.append(f"    text_color: \"{overlay.get('text_color', '#ffffff')}\"")
	animate = overlay.get('animate', {
		'kind': 'cycle',
		'values': ['>', '>>', '>>>'],
		'cadence': 0.5,
	})
	lines.append("    animate:")
	lines.append(f"      kind: {animate.get('kind', 'cycle')}")
	animate_values = animate.get('values', ['>', '>>', '>>>'])
	lines.append(
		f"      values: [{emwy_yaml_writer.format_yaml_list(animate_values)}]"
	)
	animate_fps = animate.get('fps')
	if animate_fps is not None:
		lines.append(
			f"      fps: {emwy_yaml_writer.format_speed(float(animate_fps))}"
		)
	animate_cadence = animate.get('cadence')
	if animate_cadence is not None:
		lines.append(
			f"      cadence: {emwy_yaml_writer.format_speed(float(animate_cadence))}"
		)
	lines.append("  title_card:")
	lines.append(f"    enabled: {str(bool(title_card.get('enabled', True))).lower()}")
	lines.append(f"    duration: {title_card.get('duration', 2.0)}")
	lines.append(
		f"    text_template: \"{title_card.get('text_template', '{name}')}\""
	)
	lines.append(f"    font_size: {title_card.get('font_size', 96)}")
	lines.append(f"    text_color: \"{title_card.get('text_color', '#ffffff')}\"")
	lines.append("  auto_threshold:")
	lines.append(
		f"    enabled: {str(bool(auto_threshold.get('enabled', False))).lower()}"
	)
	lines.append(f"    step_db: {auto_threshold.get('step_db', detection.AUTO_THRESHOLD_STEP_DB)}")
	lines.append(f"    max_db: {auto_threshold.get('max_db', detection.AUTO_THRESHOLD_MAX_DB)}")
	lines.append(
		f"    max_tries: {auto_threshold.get('max_tries', detection.AUTO_THRESHOLD_MAX_TRIES)}"
	)
	lines.append("")
	return "\n".join(lines)

#============================================

def write_config_file(config_path: str, config: dict) -> None:
	"""
	Write a config file to disk.

	Args:
		config_path: Output file path.
		config: Config dictionary.
	"""
	text = build_config_text(config)
	os.makedirs(os.path.dirname(config_path) or '.', exist_ok=True)
	with open(config_path, 'w', encoding='utf-8') as handle:
		handle.write(text)
	return

#============================================

def load_config(config_path: str) -> dict:
	"""
	Load a config file from disk.

	Args:
		config_path: Config file path.

	Returns:
		dict: Parsed config dictionary.
	"""
	with open(config_path, 'r', encoding='utf-8') as handle:
		data = yaml.safe_load(handle)
	if not isinstance(data, dict):
		raise RuntimeError("config file must be a mapping")
	if data.get('silence_annotator') != 1:
		raise RuntimeError("config file must set silence_annotator: 1")
	return data

#============================================

def build_settings(config: dict, config_path: str) -> dict:
	"""
	Normalize settings with defaults.

	Args:
		config: Raw config dictionary.
		config_path: Config file path.

	Returns:
		dict: Normalized settings.
	"""
	defaults = default_config()
	settings = defaults.get('settings', {})
	overrides = {}
	if isinstance(config, dict):
		overrides = config.get('settings', {})
	detection_overrides = overrides.get('detection', {})
	speeds = overrides.get('speeds', {})
	overlay = overrides.get('overlay', {})
	trim_edges_override = overrides.get('trim_edges')
	trim_leading_override = overrides.get('trim_leading_silence')
	trim_trailing_override = overrides.get('trim_trailing_silence')
	default_trim_leading = settings.get('trim_leading_silence',
		settings.get('trim_edges', True))
	default_trim_trailing = settings.get('trim_trailing_silence',
		settings.get('trim_edges', True))
	if trim_leading_override is None and trim_edges_override is not None:
		trim_leading_override = trim_edges_override
	if trim_trailing_override is None and trim_edges_override is not None:
		trim_trailing_override = trim_edges_override
	trim_leading = coerce_bool(
		trim_leading_override if trim_leading_override is not None else default_trim_leading,
		config_path, "settings.trim_leading_silence"
	)
	trim_trailing = coerce_bool(
		trim_trailing_override if trim_trailing_override is not None else default_trim_trailing,
		config_path, "settings.trim_trailing_silence"
	)
	title_card = overrides.get('title_card', {})
	auto_threshold = overrides.get('auto_threshold', {})
	threshold_db = coerce_float(detection_overrides.get('threshold_db',
		settings['detection']['threshold_db']), config_path,
		"settings.detection.threshold_db")
	min_silence = coerce_float(detection_overrides.get('min_silence',
		settings['detection']['min_silence']), config_path,
		"settings.detection.min_silence")
	min_content = coerce_float(detection_overrides.get('min_content',
		settings['detection']['min_content']), config_path,
		"settings.detection.min_content")
	frame_seconds = coerce_float(detection_overrides.get('frame_seconds',
		settings['detection']['frame_seconds']), config_path,
		"settings.detection.frame_seconds")
	hop_seconds = coerce_float(detection_overrides.get('hop_seconds',
		settings['detection']['hop_seconds']), config_path,
		"settings.detection.hop_seconds")
	smooth_frames = coerce_int(detection_overrides.get('smooth_frames',
		settings['detection']['smooth_frames']), config_path,
		"settings.detection.smooth_frames")
	silence_speed = coerce_float(speeds.get('silence',
		settings['speeds']['silence']), config_path,
		"settings.speeds.silence")
	content_speed = coerce_float(speeds.get('content',
		settings['speeds']['content']), config_path,
		"settings.speeds.content")
	overlay_enabled = coerce_bool(overlay.get('enabled',
		settings['overlay']['enabled']), config_path,
		"settings.overlay.enabled")
	overlay_text = overlay.get('text_template',
		settings['overlay']['text_template'])
	if not isinstance(overlay_text, str):
		raise RuntimeError(f"config {config_path}: settings.overlay.text_template must be a string")
	overlay_geometry = normalize_geometry(overlay.get('geometry',
		settings['overlay']['geometry']), config_path,
		"settings.overlay.geometry")
	overlay_opacity = coerce_float(overlay.get('opacity',
		settings['overlay']['opacity']), config_path,
		"settings.overlay.opacity")
	overlay_font_size = coerce_int(overlay.get('font_size',
		settings['overlay']['font_size']), config_path,
		"settings.overlay.font_size")
	overlay_text_color = overlay.get('text_color',
		settings['overlay']['text_color'])
	if not isinstance(overlay_text_color, str):
		raise RuntimeError(f"config {config_path}: settings.overlay.text_color must be a string")
	overlay_animate = None
	if 'animate' in overlay:
		overlay_animate = overlay.get('animate')
	else:
		overlay_animate = settings['overlay'].get('animate')
	if overlay_animate is not None:
		if not isinstance(overlay_animate, dict):
			raise RuntimeError(f"config {config_path}: settings.overlay.animate must be a mapping")
		animate_values = overlay_animate.get('values')
		if not isinstance(animate_values, list) or len(animate_values) == 0:
			raise RuntimeError(
				f"config {config_path}: settings.overlay.animate.values must be a non-empty list"
			)
		animate_fps = overlay_animate.get('fps')
		if animate_fps is not None and float(animate_fps) <= 0:
			raise RuntimeError(
				f"config {config_path}: settings.overlay.animate.fps must be positive"
			)
		animate_cadence = overlay_animate.get('cadence')
		if animate_cadence is not None and float(animate_cadence) <= 0:
			raise RuntimeError(
				f"config {config_path}: settings.overlay.animate.cadence must be positive"
			)
	title_card_enabled = coerce_bool(title_card.get('enabled',
		settings['title_card']['enabled']), config_path,
		"settings.title_card.enabled")
	title_card_duration = coerce_float(title_card.get('duration',
		settings['title_card']['duration']), config_path,
		"settings.title_card.duration")
	title_card_text = title_card.get('text_template',
		settings['title_card']['text_template'])
	if not isinstance(title_card_text, str):
		raise RuntimeError(f"config {config_path}: settings.title_card.text_template must be a string")
	title_card_font_size = coerce_int(title_card.get('font_size',
		settings['title_card']['font_size']), config_path,
		"settings.title_card.font_size")
	title_card_text_color = title_card.get('text_color',
		settings['title_card']['text_color'])
	if not isinstance(title_card_text_color, str):
		raise RuntimeError(f"config {config_path}: settings.title_card.text_color must be a string")
	auto_enabled = coerce_bool(auto_threshold.get('enabled',
		settings['auto_threshold']['enabled']), config_path,
		"settings.auto_threshold.enabled")
	auto_step_db = coerce_float(auto_threshold.get('step_db',
		settings['auto_threshold']['step_db']), config_path,
		"settings.auto_threshold.step_db")
	auto_max_db = coerce_float(auto_threshold.get('max_db',
		settings['auto_threshold']['max_db']), config_path,
		"settings.auto_threshold.max_db")
	auto_max_tries = coerce_int(auto_threshold.get('max_tries',
		settings['auto_threshold']['max_tries']), config_path,
		"settings.auto_threshold.max_tries")
	return {
		'threshold_db': threshold_db,
		'min_silence': min_silence,
		'min_content': min_content,
		'frame_seconds': frame_seconds,
		'hop_seconds': hop_seconds,
		'smooth_frames': smooth_frames,
		'trim_leading_silence': trim_leading,
		'trim_trailing_silence': trim_trailing,
		'silence_speed': silence_speed,
		'content_speed': content_speed,
		'overlay_enabled': overlay_enabled,
		'overlay_text': overlay_text,
		'overlay_geometry': overlay_geometry,
		'overlay_opacity': overlay_opacity,
		'overlay_font_size': overlay_font_size,
		'overlay_text_color': overlay_text_color,
		'overlay_animate': overlay_animate,
		'title_card_enabled': title_card_enabled,
		'title_card_duration': title_card_duration,
		'title_card_text': title_card_text,
		'title_card_font_size': title_card_font_size,
		'title_card_text_color': title_card_text_color,
		'auto_threshold': auto_enabled,
		'auto_step_db': auto_step_db,
		'auto_max_db': auto_max_db,
		'auto_max_tries': auto_max_tries,
	}
