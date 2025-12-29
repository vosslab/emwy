#!/usr/bin/env python3

"""
silence_annotator.py

Analyze a video or audio file and identify time ranges of silence versus content.
Outputs machine-readable timestamps, including optional EMWY v2 YAML.
"""

# Standard Library
import argparse
import decimal
import json
import math
import os
import shlex
import shutil
import subprocess
import tempfile
import wave

# PIP3 modules
import numpy
import yaml

# local repo modules
import emwy_yaml_writer

#============================================

AUTO_THRESHOLD_STEP_DB = 2.0
AUTO_THRESHOLD_MAX_DB = -5.0
AUTO_THRESHOLD_MAX_TRIES = 20

#============================================

def parse_args():
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed command-line arguments.
	"""
	parser = argparse.ArgumentParser(
		description="Detect silence ranges in a video or audio file using Python audio."
	)
	parser.add_argument(
		'-i', '--input', dest='input_file', required=True,
		help="Input video file path."
	)
	parser.add_argument(
		'-a', '--audio', dest='audio_file', default=None,
		help="Optional wav file path to skip extraction."
	)
	parser.add_argument(
		'-k', '--keep-wav', dest='keep_wav', action='store_true',
		help="Keep extracted wav file."
	)
	parser.add_argument(
		'-K', '--no-keep-wav', dest='keep_wav', action='store_false',
		help="Remove extracted wav file after analysis."
	)
	parser.add_argument(
		'-d', '--debug', dest='debug', action='store_true',
		help="Enable verbose debug output and write a debug file."
	)
	parser.add_argument(
		'-c', '--config', dest='config_file', default=None,
		help="Path to a silence annotator config YAML."
	)
	parser.add_argument(
		'-l', '--trim-leading-silence', dest='trim_leading_silence',
		help="Trim leading silence from output.",
		action='store_true'
	)
	parser.add_argument(
		'-L', '--keep-leading-silence', dest='trim_leading_silence',
		help="Keep leading silence in output.",
		action='store_false'
	)
	parser.add_argument(
		'-t', '--trim-trailing-silence', dest='trim_trailing_silence',
		help="Trim trailing silence from output.",
		action='store_true'
	)
	parser.add_argument(
		'-T', '--keep-trailing-silence', dest='trim_trailing_silence',
		help="Keep trailing silence in output.",
		action='store_false'
	)
	parser.add_argument(
		'-e', '--trim-edge-silence', dest='trim_edge_silence',
		help=argparse.SUPPRESS,
		action='store_true'
	)
	parser.add_argument(
		'-E', '--keep-edge-silence', dest='trim_edge_silence',
		help=argparse.SUPPRESS,
		action='store_false'
	)
	parser.add_argument(
		'-s', '--min-silence', dest='min_silence', type=float, default=None,
		help="Override minimum silence seconds."
	)
	parser.add_argument(
		'-m', '--min-content', dest='min_content', type=float, default=None,
		help="Override minimum content seconds."
	)
	parser.add_argument(
		'-S', '--silence-speed', dest='silence_speed', type=float, default=None,
		help="Override silence speed multiplier."
	)
	parser.add_argument(
		'-C', '--content-speed', dest='content_speed', type=float, default=None,
		help="Override content speed multiplier."
	)
	parser.add_argument(
		'-N', '--no-fast-forward-overlay', dest='fast_forward_overlay',
		help="Disable fast-forward overlay text.",
		action='store_false'
	)
	parser.set_defaults(keep_wav=False)
	parser.set_defaults(fast_forward_overlay=None)
	parser.set_defaults(debug=False)
	parser.set_defaults(trim_edge_silence=None)
	parser.set_defaults(trim_leading_silence=None)
	parser.set_defaults(trim_trailing_silence=None)
	args = parser.parse_args()
	return args

#============================================

def ensure_file_exists(filepath: str) -> None:
	"""
	Ensure a file exists.

	Args:
		filepath: File path to verify.
	"""
	if not os.path.isfile(filepath):
		raise RuntimeError(f"file not found: {filepath}")
	return

#============================================

def check_dependency(cmd_name: str) -> None:
	"""
	Ensure a required external command exists.

	Args:
		cmd_name: Command to locate.
	"""
	if shutil.which(cmd_name) is None:
		raise RuntimeError(f"missing dependency: {cmd_name}")
	return

#============================================

def run_process(cmd: list, capture_output: bool = True) -> subprocess.CompletedProcess:
	"""
	Run a subprocess command.

	Args:
		cmd: Command list to execute.
		capture_output: Capture stdout and stderr when True.

	Returns:
		subprocess.CompletedProcess: The completed process.
	"""
	showcmd = shlex.join(cmd)
	print(f"CMD: '{showcmd}'")
	proc = subprocess.run(cmd, capture_output=capture_output, text=True)
	if proc.returncode != 0:
		stderr_text = proc.stderr.strip()
		raise RuntimeError(f"command failed: {showcmd}\n{stderr_text}")
	return proc

#============================================

def make_temp_wav() -> str:
	"""
	Create a temporary wav filename.

	Returns:
		str: Temporary wav path.
	"""
	temp_handle, temp_path = tempfile.mkstemp(prefix="silence-", suffix=".wav")
	os.close(temp_handle)
	return temp_path

#============================================

def extract_audio(input_file: str, wav_path: str) -> str:
	"""
	Extract audio from a video file using ffmpeg.

	Args:
		input_file: Video file path.
		wav_path: Output wav path.

	Returns:
		str: Output wav path.
	"""
	cmd = [
		"ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
		"-i", input_file,
		"-vn", "-sn",
		"-acodec", "pcm_s16le",
		"-ar", "48000",
	]
	cmd += ["-ac", "1"]
	cmd.append(wav_path)
	run_process(cmd, capture_output=True)
	if not os.path.isfile(wav_path):
		raise RuntimeError("audio extraction failed")
	return wav_path

#============================================

def probe_video_stream(input_file: str) -> dict:
	"""
	Probe video stream metadata using ffprobe.

	Args:
		input_file: Media file path.

	Returns:
		dict: Video metadata fields.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-select_streams", "v:0",
		"-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,pix_fmt",
		"-of", "json",
		input_file,
	]
	proc = run_process(cmd, capture_output=True)
	data = json.loads(proc.stdout)
	streams = data.get('streams', [])
	if len(streams) == 0:
		raise RuntimeError("no video stream found for metadata")
	stream = streams[0]
	width = int(stream.get('width', 0))
	height = int(stream.get('height', 0))
	if width <= 0 or height <= 0:
		raise RuntimeError("invalid video resolution from ffprobe")
	fps_value = stream.get('r_frame_rate')
	if fps_value is None or fps_value == "0/0":
		fps_value = stream.get('avg_frame_rate')
	if fps_value is None or fps_value == "0/0":
		raise RuntimeError("invalid frame rate from ffprobe")
	pix_fmt = stream.get('pix_fmt', 'yuv420p')
	return {
		'width': width,
		'height': height,
		'fps': fps_value,
		'pix_fmt': pix_fmt,
	}

#============================================

def probe_audio_stream(input_file: str) -> dict:
	"""
	Probe audio stream metadata using ffprobe.

	Args:
		input_file: Media file path.

	Returns:
		dict: Audio metadata fields.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-select_streams", "a:0",
		"-show_entries", "stream=sample_rate,channels",
		"-of", "json",
		input_file,
	]
	proc = run_process(cmd, capture_output=True)
	data = json.loads(proc.stdout)
	streams = data.get('streams', [])
	if len(streams) == 0:
		raise RuntimeError("no audio stream found for metadata")
	stream = streams[0]
	sample_rate = int(stream.get('sample_rate', 0))
	channels = int(stream.get('channels', 0))
	if sample_rate <= 0:
		raise RuntimeError("invalid audio sample rate from ffprobe")
	if channels <= 0:
		raise RuntimeError("invalid audio channel count from ffprobe")
	return {
		'sample_rate': sample_rate,
		'channels': channels,
	}

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
				'step_db': AUTO_THRESHOLD_STEP_DB,
				'max_db': AUTO_THRESHOLD_MAX_DB,
				'max_tries': AUTO_THRESHOLD_MAX_TRIES,
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
	detection = settings.get('detection', {})
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
	lines.append(f"    threshold_db: {detection.get('threshold_db', -40.0)}")
	lines.append(f"    min_silence: {detection.get('min_silence', 3.0)}")
	lines.append(f"    min_content: {detection.get('min_content', 1.5)}")
	lines.append(f"    frame_seconds: {detection.get('frame_seconds', 0.25)}")
	lines.append(f"    hop_seconds: {detection.get('hop_seconds', 0.05)}")
	lines.append(f"    smooth_frames: {detection.get('smooth_frames', 5)}")
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
	lines.append(f"    step_db: {auto_threshold.get('step_db', AUTO_THRESHOLD_STEP_DB)}")
	lines.append(f"    max_db: {auto_threshold.get('max_db', AUTO_THRESHOLD_MAX_DB)}")
	lines.append(
		f"    max_tries: {auto_threshold.get('max_tries', AUTO_THRESHOLD_MAX_TRIES)}"
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
	detection = overrides.get('detection', {})
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
	threshold_db = coerce_float(detection.get('threshold_db',
		settings['detection']['threshold_db']), config_path,
		"settings.detection.threshold_db")
	min_silence = coerce_float(detection.get('min_silence',
		settings['detection']['min_silence']), config_path,
		"settings.detection.min_silence")
	min_content = coerce_float(detection.get('min_content',
		settings['detection']['min_content']), config_path,
		"settings.detection.min_content")
	frame_seconds = coerce_float(detection.get('frame_seconds',
		settings['detection']['frame_seconds']), config_path,
		"settings.detection.frame_seconds")
	hop_seconds = coerce_float(detection.get('hop_seconds',
		settings['detection']['hop_seconds']), config_path,
		"settings.detection.hop_seconds")
	smooth_frames = coerce_int(detection.get('smooth_frames',
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

#============================================

def get_wav_duration_seconds(audio_path: str) -> float:
	"""
	Get wav duration in seconds.

	Args:
		audio_path: Audio file path.

	Returns:
		float: Duration in seconds.
	"""
	with wave.open(audio_path, 'rb') as wav_handle:
		sample_rate = wav_handle.getframerate()
		total_frames = wav_handle.getnframes()
	if sample_rate <= 0:
		raise RuntimeError("audio sample rate must be positive")
	if total_frames <= 0:
		raise RuntimeError("audio duration must be positive")
	duration = total_frames / float(sample_rate)
	return duration

#============================================

def get_wav_info(audio_path: str) -> dict:
	"""
	Get wav metadata.

	Args:
		audio_path: Audio file path.

	Returns:
		dict: Wav info.
	"""
	with wave.open(audio_path, 'rb') as wav_handle:
		channels = wav_handle.getnchannels()
		sample_rate = wav_handle.getframerate()
		sample_width = wav_handle.getsampwidth()
		total_frames = wav_handle.getnframes()
	if sample_rate <= 0:
		raise RuntimeError("audio sample rate must be positive")
	if total_frames <= 0:
		raise RuntimeError("audio duration must be positive")
	if channels <= 0:
		raise RuntimeError("audio channel count must be positive")
	return {
		'channels': channels,
		'sample_rate': sample_rate,
		'sample_width': sample_width,
		'total_frames': total_frames,
		'duration': total_frames / float(sample_rate),
	}

#============================================

def scan_wav_for_silence(audio_path: str, threshold_db: float,
	min_silence: float, frame_seconds: float, hop_seconds: float,
	smooth_frames: int, include_series: bool = False) -> tuple:
	"""
	Scan wav samples for silence segments.

	Args:
		audio_path: Audio file path.
		threshold_db: Silence threshold in dBFS.
		min_silence: Minimum silence duration in seconds.
		frame_seconds: Frame window size in seconds.
		hop_seconds: Hop size in seconds.
		smooth_frames: Smoothing window in frames.

	Returns:
		tuple: (raw_silences, stats)
	"""
	info = get_wav_info(audio_path)
	channels = info['channels']
	sample_rate = info['sample_rate']
	sample_width = info['sample_width']
	total_frames = info['total_frames']
	if sample_width not in (1, 2, 4):
		raise RuntimeError("unsupported wav sample width")
	max_amplitude = float(2 ** (8 * sample_width - 1))
	threshold_amp = 10 ** (threshold_db / 20.0)
	threshold_int = int(max_amplitude * threshold_amp)
	if threshold_int < 1:
		threshold_int = 1
	frame_size = max(1, int(sample_rate * frame_seconds))
	hop_size = max(1, int(sample_rate * hop_seconds))
	dtype_map = {
		1: numpy.dtype('u1'),
		2: numpy.dtype('<i2'),
		4: numpy.dtype('<i4'),
	}
	raw_silences = []
	with wave.open(audio_path, 'rb') as wav_handle:
		data = wav_handle.readframes(total_frames)
	samples = numpy.frombuffer(data, dtype=dtype_map[sample_width])
	if sample_width == 1:
		samples = samples.astype(numpy.int16) - 128
	if samples.size == 0:
		stats = {
			'channels': channels,
			'sample_rate': sample_rate,
			'sample_width': sample_width,
			'total_frames': total_frames,
			'duration': total_frames / float(sample_rate),
			'threshold_int': threshold_int,
			'threshold_db': threshold_db,
			'frame_size': frame_size,
			'frame_seconds': frame_seconds,
			'hop_seconds': hop_seconds,
			'smooth_frames': smooth_frames,
			'frame_count': 0,
			'below_frames': 0,
			'below_pct': 0.0,
			'longest_run_sec': 0.0,
			'runs_over_min': 0,
			'max_amp': None,
			'rms_amp': None,
		}
		if include_series:
			stats['frame_db'] = numpy.array([], dtype=numpy.float64)
		return [], stats
	frame_count = samples.size // channels
	if samples.size != frame_count * channels:
		samples = samples[:frame_count * channels]
	if frame_count == 0:
		stats = {
			'channels': channels,
			'sample_rate': sample_rate,
			'sample_width': sample_width,
			'total_frames': total_frames,
			'duration': total_frames / float(sample_rate),
			'threshold_int': threshold_int,
			'threshold_db': threshold_db,
			'frame_size': frame_size,
			'frame_seconds': frame_seconds,
			'hop_seconds': hop_seconds,
			'smooth_frames': smooth_frames,
			'frame_count': 0,
			'below_frames': 0,
			'below_pct': 0.0,
			'longest_run_sec': 0.0,
			'runs_over_min': 0,
			'max_amp': None,
			'rms_amp': None,
		}
		if include_series:
			stats['frame_db'] = numpy.array([], dtype=numpy.float64)
		return [], stats
	if channels > 1:
		samples = samples.reshape(frame_count, channels)
		samples = numpy.mean(samples, axis=1, dtype=numpy.float64)
		samples = samples.astype(numpy.int64, copy=False).reshape(frame_count, 1)
		channels = 1
	else:
		samples = samples.reshape(frame_count, 1)
	usable_frames = (frame_count - frame_size) // hop_size + 1
	if usable_frames <= 0:
		stats = {
			'channels': channels,
			'sample_rate': sample_rate,
			'sample_width': sample_width,
			'total_frames': total_frames,
			'duration': total_frames / float(sample_rate),
			'threshold_int': threshold_int,
			'threshold_db': threshold_db,
			'frame_size': frame_size,
			'frame_seconds': frame_seconds,
			'hop_seconds': hop_seconds,
			'smooth_frames': smooth_frames,
			'frame_count': 0,
			'below_frames': 0,
			'below_pct': 0.0,
			'longest_run_sec': 0.0,
			'runs_over_min': 0,
			'max_amp': None,
			'rms_amp': None,
		}
		if include_series:
			stats['frame_db'] = numpy.array([], dtype=numpy.float64)
		return [], stats
	starts = numpy.arange(usable_frames) * hop_size
	ends = starts + frame_size
	frame_db = numpy.empty(usable_frames, dtype=numpy.float64)
	sum_sq = 0.0
	max_abs = 0
	for index, (start_idx, end_idx) in enumerate(zip(starts, ends)):
		window = samples[start_idx:end_idx]
		window_int = window.astype(numpy.int64, copy=False)
		abs_max = int(numpy.max(numpy.abs(window_int)))
		if abs_max > max_abs:
			max_abs = abs_max
		mean_sq = float(numpy.mean(window_int.astype(numpy.float64) ** 2))
		sum_sq += mean_sq * window_int.size
		rms = math.sqrt(mean_sq)
		rms_norm = rms / max_amplitude
		db = amplitude_to_db(rms_norm)
		if db is None:
			db = -120.0
		frame_db[index] = db
	smooth_db = None
	if smooth_frames > 1:
		window = numpy.ones(smooth_frames, dtype=numpy.float64) / smooth_frames
		smooth_db = numpy.convolve(frame_db, window, mode='same')
		mask = smooth_db < threshold_db
	else:
		mask = frame_db < threshold_db
	mask_int = mask.astype(numpy.int8)
	diff = numpy.diff(mask_int)
	start_idxs = numpy.where(diff == 1)[0] + 1
	end_idxs = numpy.where(diff == -1)[0] + 1
	if mask[0]:
		start_idxs = numpy.concatenate(
			(numpy.array([0], dtype=numpy.int64), start_idxs)
		)
	if mask[-1]:
		end_idxs = numpy.concatenate(
			(end_idxs, numpy.array([len(mask)], dtype=numpy.int64))
		)
	longest_run = 0
	runs_over_min = 0
	for start_idx, end_idx in zip(start_idxs, end_idxs):
		start_idx = int(start_idx)
		end_idx = int(end_idx)
		run_len = end_idx - start_idx
		run_seconds = run_len * hop_seconds + (frame_seconds - hop_seconds)
		if run_seconds >= min_silence:
			raw_silences.append({
				'start': start_idx * hop_seconds,
				'end': (end_idx - 1) * hop_seconds + frame_seconds,
				'duration': run_seconds,
			})
			runs_over_min += 1
		if run_len > longest_run:
			longest_run = run_len
	below_frames = int(numpy.sum(mask))
	below_pct = 0.0
	if mask.size > 0:
		below_pct = (below_frames / float(mask.size)) * 100.0
	rms_amp = None
	max_amp = None
	if sum_sq > 0 and frame_count > 0:
		rms_amp = math.sqrt(sum_sq / float(frame_count * channels)) / max_amplitude
		max_amp = max_abs / max_amplitude
	stats = {
		'channels': channels,
		'sample_rate': sample_rate,
		'sample_width': sample_width,
		'total_frames': total_frames,
		'duration': total_frames / float(sample_rate),
		'threshold_int': threshold_int,
		'threshold_db': threshold_db,
		'frame_size': frame_size,
		'frame_seconds': frame_seconds,
		'hop_seconds': hop_seconds,
		'smooth_frames': smooth_frames,
		'frame_count': int(mask.size),
		'below_frames': below_frames,
		'below_pct': below_pct,
		'longest_run_sec': longest_run * hop_seconds + (frame_seconds - hop_seconds),
		'runs_over_min': runs_over_min,
		'max_amp': max_amp,
		'rms_amp': rms_amp,
	}
	if include_series:
		stats['frame_db'] = frame_db
		if smooth_db is not None:
			stats['smooth_db'] = smooth_db
	return raw_silences, stats

#============================================

def build_debug_report(audio_path: str, threshold_db: float, min_silence: float,
	stats: dict, auto_attempts: list = None, threshold_used: float = None) -> str:
	"""
	Build a debug report for Python silence detection.

	Args:
		audio_path: Audio file path.
		threshold_db: Silence threshold in dBFS.
		min_silence: Minimum silence duration in seconds.
		stats: Scan statistics.
		auto_attempts: Auto-threshold attempts.
		threshold_used: Effective threshold.

	Returns:
		str: Debug report text.
	"""
	lines = []
	lines.append(f"audio_path: {audio_path}")
	lines.append(f"threshold_db: {threshold_db:.2f}")
	lines.append(f"min_silence: {min_silence:.3f}")
	lines.append("")
	lines.append("wav_info:")
	lines.append(f"channels: {stats['channels']}")
	lines.append(f"sample_rate: {stats['sample_rate']}")
	lines.append(f"sample_width: {stats['sample_width']}")
	lines.append(f"total_frames: {stats['total_frames']}")
	lines.append(f"duration: {stats['duration']:.3f}")
	lines.append(f"frame_seconds: {stats['frame_seconds']:.3f}")
	lines.append(f"hop_seconds: {stats['hop_seconds']:.3f}")
	lines.append(f"frame_count: {stats['frame_count']}")
	lines.append(f"smooth_frames: {stats['smooth_frames']}")
	lines.append("")
	lines.append("silence_scan:")
	lines.append(f"threshold_int: {stats['threshold_int']}")
	lines.append(f"below_frames: {stats['below_frames']}")
	lines.append(f"below_pct: {stats['below_pct']:.2f}")
	lines.append(f"longest_run_sec: {stats['longest_run_sec']:.3f}")
	lines.append(f"runs_over_min: {stats['runs_over_min']}")
	if stats['rms_amp'] is not None:
		lines.append(f"rms_amp: {stats['rms_amp']:.6f}")
	if stats['max_amp'] is not None:
		lines.append(f"max_amp: {stats['max_amp']:.6f}")
	lines.append("")
	if auto_attempts is not None and len(auto_attempts) > 0:
		lines.append("auto_threshold_attempts:")
		for attempt in auto_attempts:
			lines.append(
				f"- threshold_db: {attempt['threshold_db']:.2f} "
				f"raw: {attempt['raw_count']} "
				f"normalized: {attempt['normalized_count']}"
			)
		lines.append("")
	if threshold_used is not None:
		lines.append("threshold_used:")
		lines.append(f"{threshold_used:.2f}")
		lines.append("")
	return "\n".join(lines)

#============================================

def merge_segments(segments: list, gap_threshold: float = 0.0) -> list:
	"""
	Merge overlapping or adjacent segments.

	Args:
		segments: List of segments with start/end.
		gap_threshold: Merge segments when gap is less than or equal to this.

	Returns:
		list: Merged segments.
	"""
	if len(segments) == 0:
		return []
	sorted_segments = sorted(segments, key=lambda item: item['start'])
	merged = []
	current = {
		'start': sorted_segments[0]['start'],
		'end': sorted_segments[0]['end'],
	}
	for segment in sorted_segments[1:]:
		gap = segment['start'] - current['end']
		if gap <= gap_threshold:
			if segment['end'] > current['end']:
				current['end'] = segment['end']
		else:
			current['duration'] = current['end'] - current['start']
			merged.append(current)
			current = {'start': segment['start'], 'end': segment['end']}
	current['duration'] = current['end'] - current['start']
	merged.append(current)
	return merged

#============================================

def clamp_segments(segments: list, duration: float) -> list:
	"""
	Clamp segment start and end times to the audio duration.

	Args:
		segments: List of segments with start/end.
		duration: Total audio duration.

	Returns:
		list: Clamped segments.
	"""
	clamped = []
	for segment in segments:
		start = max(0.0, segment['start'])
		end = min(duration, segment['end'])
		if end <= start:
			continue
		clamped.append({
			'start': start,
			'end': end,
			'duration': end - start,
		})
	return clamped

#============================================

def normalize_silences(silences: list, duration: float,
	min_silence: float, min_content: float) -> list:
	"""
	Normalize silence segments with minimum duration and gap rules.

	Args:
		silences: List of silence segments.
		duration: Total audio duration.
		min_silence: Minimum silence duration.
		min_content: Minimum content duration between silences.

	Returns:
		list: Normalized silence segments.
	"""
	silences = clamp_segments(silences, duration)
	silences = merge_segments(silences, gap_threshold=0.0)
	if min_silence > 0:
		silences = [seg for seg in silences if seg['duration'] >= min_silence]
	if len(silences) == 0:
		return []
	if min_content > 0:
		if silences[0]['start'] < min_content:
			silences[0]['start'] = 0.0
		if (duration - silences[-1]['end']) < min_content:
			silences[-1]['end'] = duration
		silences = merge_segments(silences, gap_threshold=min_content)
		silences = clamp_segments(silences, duration)
	return silences

#============================================

def trim_leading_trailing_silences(silences: list, duration: float,
	trim_leading: bool = True, trim_trailing: bool = True) -> list:
	"""
	Remove leading/trailing silence segments that touch the bounds.

	Args:
		silences: List of silence segments.
		duration: Total audio duration.

	Returns:
		list: Trimmed silence segments.
	"""
	if len(silences) == 0:
		return silences
	epsilon = 0.0001
	trimmed = list(silences)
	if trim_leading and trimmed and trimmed[0]['start'] <= epsilon:
		trimmed = trimmed[1:]
	if trim_trailing and trimmed and trimmed[-1]['end'] >= (duration - epsilon):
		trimmed = trimmed[:-1]
	return trimmed

#============================================

def compute_contents(silences: list, duration: float) -> list:
	"""
	Compute content segments as the complement of silence.

	Args:
		silences: List of silence segments.
		duration: Total audio duration.

	Returns:
		list: Content segments with start/end/duration.
	"""
	if len(silences) == 0:
		return [{'start': 0.0, 'end': duration, 'duration': duration}]
	contents = []
	current = 0.0
	for silence in silences:
		if silence['start'] > current:
			contents.append({
				'start': current,
				'end': silence['start'],
				'duration': silence['start'] - current,
			})
		current = silence['end']
	if current < duration:
		contents.append({
			'start': current,
			'end': duration,
			'duration': duration - current,
		})
	return contents

#============================================

def seconds_to_millis(seconds: float) -> int:
	"""
	Convert seconds to integer milliseconds using half-up rounding.

	Args:
		seconds: Time in seconds.

	Returns:
		int: Time in milliseconds.
	"""
	value = decimal.Decimal(str(seconds))
	millis = value * decimal.Decimal(1000)
	millis = millis.quantize(decimal.Decimal("1"), rounding=decimal.ROUND_HALF_UP)
	result = int(millis)
	if result < 0:
		result = 0
	return result

#============================================

def format_timestamp(seconds: float) -> str:
	"""
	Format seconds as HH:MM:SS.mmm.

	Args:
		seconds: Time in seconds.

	Returns:
		str: Formatted timestamp.
	"""
	total_millis = seconds_to_millis(seconds)
	hours = total_millis // 3600000
	remainder = total_millis % 3600000
	minutes = remainder // 60000
	remainder = remainder % 60000
	seconds_part = remainder // 1000
	millis_part = remainder % 1000
	return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}.{millis_part:03d}"

#============================================

def add_timecodes(segments: list) -> list:
	"""
	Add timecode strings to segments.

	Args:
		segments: List of segments.

	Returns:
		list: Segments with timecode fields.
	"""
	decorated = []
	for segment in segments:
		segment_copy = dict(segment)
		segment_copy['start_tc'] = format_timestamp(segment['start'])
		segment_copy['end_tc'] = format_timestamp(segment['end'])
		segment_copy['duration_tc'] = format_timestamp(segment['duration'])
		decorated.append(segment_copy)
	return decorated

#============================================

def build_segment_list(silences: list, contents: list) -> list:
	"""
	Build an ordered segment list with kind labels.

	Args:
		silences: Silence segments with timecodes.
		contents: Content segments with timecodes.

	Returns:
		list: Ordered segments with kind.
	"""
	segments = []
	for segment in silences:
		item = dict(segment)
		item['kind'] = 'silence'
		segments.append(item)
	for segment in contents:
		item = dict(segment)
		item['kind'] = 'content'
		segments.append(item)
	segments.sort(key=lambda entry: entry['start'])
	return segments

#============================================

def default_output_path(input_file: str) -> str:
	"""
	Build a default output report path.

	Args:
		input_file: Input file path.

	Returns:
		str: Output file path.
	"""
	return f"{input_file}.emwy.yaml"

#============================================

def default_debug_path(input_file: str) -> str:
	"""
	Build a default debug output path.

	Args:
		input_file: Input file path.

	Returns:
		str: Debug output file path.
	"""
	return f"{input_file}.silence.debug.txt"

#============================================

def default_plot_path(input_file: str) -> str:
	"""
	Build a default debug plot path.

	Args:
		input_file: Input file path.

	Returns:
		str: Debug plot path.
	"""
	return f"{input_file}.silence.debug.png"

#============================================

def default_output_media_path(input_file: str) -> str:
	"""
	Build a default output media path for EMWY YAML.

	Args:
		input_file: Input file path.

	Returns:
		str: Output media file path.
	"""
	base, _ = os.path.splitext(input_file)
	return f"{base}.silencefast.mkv"

#============================================

def write_yaml_report(output_file: str, yaml_text: str) -> None:
	"""
	Write report to YAML.

	Args:
		output_file: YAML output path.
		yaml_text: YAML content.
	"""
	with open(output_file, 'w', encoding='utf-8') as handle:
		handle.write(yaml_text)
	return

#============================================

def write_text_report(output_file: str, text: str) -> None:
	"""
	Write text to a file.

	Args:
		output_file: Output file path.
		text: Text to write.
	"""
	with open(output_file, 'w', encoding='utf-8') as handle:
		handle.write(text)
	return

#============================================

def write_debug_plot(output_file: str, frame_db: numpy.ndarray,
	smooth_db: numpy.ndarray, threshold_db: float, frame_seconds: float,
	hop_seconds: float) -> None:
	"""
	Write a debug loudness plot.

	Args:
		output_file: Output plot path.
		frame_db: Frame dBFS values.
		threshold_db: Silence threshold in dBFS.
		frame_seconds: Frame window size in seconds.
		hop_seconds: Hop size in seconds.
	"""
	if frame_db.size == 0:
		return
	try:
		import matplotlib.pyplot as pyplot
	except ImportError as exc:
		raise RuntimeError("matplotlib is required for --debug plots") from exc
	times = numpy.arange(frame_db.size) * hop_seconds + (frame_seconds * 0.5)
	plotter = pyplot
	plotter.figure(figsize=(12, 4))
	plotter.plot(times, frame_db, linewidth=0.6, alpha=0.4, label="raw")
	if smooth_db is not None and smooth_db.size == frame_db.size:
		plotter.plot(times, smooth_db, linewidth=1.0, label="smooth")
	plotter.axhline(threshold_db, color='red', linestyle='--', linewidth=1.0)
	plotter.xlabel("Seconds")
	plotter.ylabel("dBFS")
	plotter.title("Frame RMS Loudness")
	plotter.legend(loc="upper right")
	plotter.tight_layout()
	plotter.savefig(output_file)
	plotter.close()
	return

#============================================

def amplitude_to_db(value: float) -> float:
	"""
	Convert linear amplitude to dBFS.

	Args:
		value: Linear amplitude.

	Returns:
		float: dBFS value.
	"""
	if value is None or value <= 0:
		return None
	return 20.0 * math.log10(value)

#============================================

def auto_find_silence(audio_path: str, duration: float, threshold_db: float,
	min_silence: float, min_content: float, frame_seconds: float,
	hop_seconds: float, smooth_frames: int, step_db: float,
	max_db: float, max_tries: int) -> dict:
	"""
	Auto-raise threshold until silence is detected.

	Args:
		audio_path: Audio file path.
		duration: Total duration in seconds.
		threshold_db: Starting threshold in dBFS.
		min_silence: Minimum silence duration in seconds.
		min_content: Minimum content duration in seconds.
		frame_seconds: Frame window size in seconds.
		hop_seconds: Hop size in seconds.
		smooth_frames: Smoothing window in frames.
		step_db: Threshold increment in dB.
		max_db: Maximum threshold in dBFS.
		max_tries: Maximum adjustment attempts.

	Returns:
		dict: Auto adjustment results.
	"""
	attempts = []
	current = threshold_db
	tries = 0
	while True:
		current += step_db
		if current > max_db:
			break
		tries += 1
		if tries > max_tries:
			break
		raw_silences, scan_stats = scan_wav_for_silence(
			audio_path, current, min_silence, frame_seconds,
			hop_seconds, smooth_frames
		)
		silences = normalize_silences(raw_silences, duration,
			min_silence, min_content)
		attempts.append({
			'threshold_db': current,
			'raw_count': len(raw_silences),
			'normalized_count': len(silences),
		})
		if len(silences) > 0:
			return {
				'found': True,
				'threshold_db': current,
				'raw_silences': raw_silences,
				'silences': silences,
				'scan_stats': scan_stats,
				'attempts': attempts,
			}
	return {
		'found': False,
		'attempts': attempts,
	}

#============================================

def print_debug_summary(args: argparse.Namespace, audio_path: str,
	temp_wav: str, output_file: str, output_media_file: str,
	raw_silences: list, silences: list, contents: list,
	scan_stats: dict = None, auto_attempts: list = None,
	threshold_used: float = None, debug_plot: str = None,
	threshold_db: float = None, min_silence: float = None,
	min_content: float = None) -> None:
	"""
	Print verbose debug summary.

	Args:
		args: Parsed arguments.
		audio_path: Audio file path.
		temp_wav: Temporary wav path if created.
		output_file: YAML report path.
		output_media_file: Output media file in YAML.
		raw_silences: Silence ranges before normalization.
		silences: Normalized silence ranges.
		contents: Content ranges.
		scan_stats: Wav scan stats.
		auto_attempts: Auto threshold attempts.
		threshold_used: Effective threshold.
	"""
	print("")
	print("Debug")
	print(f"Audio path: {audio_path}")
	print(f"Temp wav: {temp_wav if temp_wav is not None else '[none]'}")
	print(f"Keep wav: {args.keep_wav}")
	print("Channels: mono (forced)")
	if threshold_db is not None:
		print(f"Threshold dB: {threshold_db:.2f}")
	if threshold_used is not None and threshold_db is not None:
		if threshold_used != threshold_db:
			print(f"Threshold used: {threshold_used:.2f} (auto)")
	if min_silence is not None:
		print(f"Min silence: {min_silence:.3f}")
	if min_content is not None:
		print(f"Min content: {min_content:.3f}")
	print(f"Raw silence ranges: {len(raw_silences)}")
	print(f"Normalized silence ranges: {len(silences)}")
	print(f"Content ranges: {len(contents)}")
	if scan_stats is not None:
		rms_db = amplitude_to_db(scan_stats.get('rms_amp'))
		max_db = amplitude_to_db(scan_stats.get('max_amp'))
		if rms_db is not None:
			print(f"RMS amplitude dB: {rms_db:.2f}")
		if max_db is not None:
			print(f"Max amplitude dB: {max_db:.2f}")
		print("Silence scan:")
		print(f"  Threshold int: {scan_stats['threshold_int']}")
		print(f"  Frame seconds: {scan_stats['frame_seconds']:.3f}")
		print(f"  Hop seconds: {scan_stats['hop_seconds']:.3f}")
		print(f"  Frame count: {scan_stats['frame_count']}")
		print(f"  Smooth frames: {scan_stats['smooth_frames']}")
		print(f"  Below frames: {scan_stats['below_frames']} "
			f"({scan_stats['below_pct']:.2f}%)")
		print(f"  Longest run: {scan_stats['longest_run_sec']:.3f}s")
		print(f"  Runs >= min: {scan_stats['runs_over_min']}")
	if auto_attempts is not None and len(auto_attempts) > 0:
		print("Auto threshold attempts:")
		for attempt in auto_attempts:
			print(f"  {attempt['threshold_db']:.2f} "
				f"raw:{attempt['raw_count']} "
				f"norm:{attempt['normalized_count']}")
	print(f"Report file: {output_file}")
	print(f"Output media: {output_media_file}")
	if debug_plot is not None:
		print(f"Debug plot: {debug_plot}")
	print("")
	return

#============================================

def print_summary(input_file: str, duration: float, silences: list,
	contents: list, output_file: str,
	silence_speed: float, content_speed: float,
	debug_file: str = None, debug_plot: str = None,
	threshold_used: float = None, threshold_initial: float = None) -> None:
	"""
	Print a human-readable summary.

	Args:
		input_file: Input file path.
		duration: Total audio duration.
		silences: Silence segments.
		contents: Content segments.
		output_file: Output report path.
	"""
	silence_total = sum(seg['duration'] for seg in silences)
	content_total = sum(seg['duration'] for seg in contents)
	if duration > 0:
		silence_pct = (silence_total / duration) * 100.0
		content_pct = (content_total / duration) * 100.0
	else:
		silence_pct = 0.0
		content_pct = 0.0
	print("")
	print("Silence Annotator Summary")
	print(f"Input: {input_file}")
	print(f"Duration: {format_timestamp(duration)} ({duration:.3f}s)")
	print(f"Silence: {format_timestamp(silence_total)} ({silence_pct:.2f}%)")
	print(f"Content: {format_timestamp(content_total)} ({content_pct:.2f}%)")
	print(f"Silence ranges: {len(silences)}")
	print(f"Content ranges: {len(contents)}")
	print(f"Report: {output_file}")
	if debug_file is not None:
		print(f"Debug file: {debug_file}")
	if debug_plot is not None:
		print(f"Debug plot: {debug_plot}")
	if threshold_used is not None and threshold_initial is not None:
		if threshold_used != threshold_initial:
			print(f"Threshold used: {threshold_used:.2f} (auto)")
	print(f"Silence speed: {format_speed(silence_speed)}")
	print(f"Content speed: {format_speed(content_speed)}")
	print("")
	return

#============================================

def main() -> None:
	"""
	Main entry point.
	"""
	args = parse_args()
	ensure_file_exists(args.input_file)
	if args.audio_file is not None:
		ensure_file_exists(args.audio_file)
	config_path = args.config_file
	if config_path is None:
		config_path = default_config_path(args.input_file)
	if not os.path.exists(config_path):
		write_config_file(config_path, default_config())
		print(f"Wrote default config: {config_path}")
	config = load_config(config_path)
	settings = build_settings(config, config_path)
	if args.trim_edge_silence is not None:
		if args.trim_leading_silence is None:
			settings['trim_leading_silence'] = args.trim_edge_silence
		if args.trim_trailing_silence is None:
			settings['trim_trailing_silence'] = args.trim_edge_silence
	if args.trim_leading_silence is not None:
		settings['trim_leading_silence'] = args.trim_leading_silence
	if args.trim_trailing_silence is not None:
		settings['trim_trailing_silence'] = args.trim_trailing_silence
	if args.min_silence is not None:
		settings['min_silence'] = args.min_silence
	if args.min_content is not None:
		settings['min_content'] = args.min_content
	if args.silence_speed is not None:
		settings['silence_speed'] = args.silence_speed
	if args.content_speed is not None:
		settings['content_speed'] = args.content_speed
	if args.fast_forward_overlay is False:
		settings['overlay_enabled'] = False
	if settings['threshold_db'] > 0:
		raise RuntimeError("threshold must be 0 or negative dBFS")
	if settings['min_silence'] <= 0:
		raise RuntimeError("min_silence must be positive")
	if settings['min_content'] <= 0:
		raise RuntimeError("min_content must be positive")
	if settings['silence_speed'] <= 0:
		raise RuntimeError("silence_speed must be positive")
	if settings['content_speed'] <= 0:
		raise RuntimeError("content_speed must be positive")
	if settings['title_card_enabled']:
		if settings['title_card_duration'] <= 0:
			raise RuntimeError("title_card duration must be positive")
		if settings['title_card_font_size'] <= 0:
			raise RuntimeError("title_card font_size must be positive")
	overlay_geometry = None
	if settings['overlay_enabled']:
		overlay_geometry = settings['overlay_geometry']
		if settings['overlay_opacity'] < 0 or settings['overlay_opacity'] > 1:
			raise RuntimeError("fast_forward_opacity must be between 0 and 1")
		if settings['overlay_font_size'] <= 0:
			raise RuntimeError("fast_forward_font_size must be positive")
	if settings['frame_seconds'] <= 0:
		raise RuntimeError("frame_seconds must be positive")
	if settings['hop_seconds'] <= 0:
		raise RuntimeError("hop_seconds must be positive")
	if settings['smooth_frames'] <= 0:
		raise RuntimeError("smooth_frames must be positive")
	if settings['hop_seconds'] > settings['frame_seconds']:
		raise RuntimeError("hop_seconds must be <= frame_seconds")
	needs_ffmpeg = args.audio_file is None
	if needs_ffmpeg:
		check_dependency("ffmpeg")
	check_dependency("ffprobe")
	temp_wav = None
	audio_path = args.audio_file
	if audio_path is None:
		temp_wav = make_temp_wav()
		audio_path = extract_audio(args.input_file, temp_wav)
	else:
		audio_ext = os.path.splitext(audio_path)[1].lower()
		if audio_ext not in ('.wav', '.wave'):
			raise RuntimeError("audio_file must be wav when using --audio")
	audio_duration = get_wav_duration_seconds(audio_path)
	raw_silences, scan_stats = scan_wav_for_silence(
		audio_path, settings['threshold_db'], settings['min_silence'],
		settings['frame_seconds'], settings['hop_seconds'],
		settings['smooth_frames'], include_series=args.debug
	)
	silences = normalize_silences(raw_silences, audio_duration,
		settings['min_silence'], settings['min_content'])
	if settings['trim_leading_silence'] or settings['trim_trailing_silence']:
		silences = trim_leading_trailing_silences(silences, audio_duration,
			settings['trim_leading_silence'], settings['trim_trailing_silence'])
	threshold_used = settings['threshold_db']
	auto_attempts = []
	if settings['auto_threshold'] and len(silences) == 0:
		auto_result = auto_find_silence(audio_path, audio_duration,
			settings['threshold_db'], settings['min_silence'],
			settings['min_content'], settings['frame_seconds'],
			settings['hop_seconds'], settings['smooth_frames'],
			settings['auto_step_db'], settings['auto_max_db'],
			settings['auto_max_tries'])
		auto_attempts = auto_result['attempts']
		if auto_result['found']:
			raw_silences = auto_result['raw_silences']
			silences = auto_result['silences']
			scan_stats = auto_result['scan_stats']
			threshold_used = auto_result['threshold_db']
			if args.debug and 'frame_db' not in scan_stats:
				raw_silences, scan_stats = scan_wav_for_silence(
					audio_path, threshold_used, settings['min_silence'],
					settings['frame_seconds'], settings['hop_seconds'],
					settings['smooth_frames'],
					include_series=True
				)
				silences = normalize_silences(raw_silences, audio_duration,
					settings['min_silence'], settings['min_content'])
	debug_file = None
	plot_file = None
	if args.debug:
		debug_file = default_debug_path(args.input_file)
		plot_file = default_plot_path(args.input_file)
		debug_text = build_debug_report(audio_path, settings['threshold_db'],
			settings['min_silence'], scan_stats, auto_attempts, threshold_used)
		write_text_report(debug_file, debug_text)
		write_debug_plot(plot_file, scan_stats.get('frame_db', numpy.array([])),
			scan_stats.get('smooth_db'), threshold_used,
			scan_stats['frame_seconds'], scan_stats['hop_seconds'])
	contents = compute_contents(silences, audio_duration)
	silences = add_timecodes(silences)
	contents = add_timecodes(contents)
	segments = build_segment_list(silences, contents)
	output_file = default_output_path(args.input_file)
	output_media_file = default_output_media_path(args.input_file)
	intro_title = None
	if settings['title_card_enabled']:
		base_name = os.path.splitext(os.path.basename(args.input_file))[0]
		intro_title = settings['title_card_text'].replace("{name}", base_name)
	video_meta = probe_video_stream(args.input_file)
	audio_meta = probe_audio_stream(args.input_file)
	profile = {
		'fps': video_meta['fps'],
		'width': video_meta['width'],
		'height': video_meta['height'],
		'sample_rate': audio_meta['sample_rate'],
		'channels': 'mono',
	}
	yaml_text = emwy_yaml_writer.build_silence_timeline_yaml(
		args.input_file, output_media_file, profile, "source",
		segments,
		settings['silence_speed'], settings['content_speed'],
		overlay_text_template=settings['overlay_text'] if settings['overlay_enabled'] else None,
		overlay_animate=settings['overlay_animate'] if settings['overlay_enabled'] else None,
		overlay_geometry=overlay_geometry,
		overlay_opacity=settings['overlay_opacity'],
		overlay_font_size=settings['overlay_font_size'],
		overlay_text_color=settings['overlay_text_color'],
		intro_title=intro_title,
		intro_duration=settings['title_card_duration'],
		intro_font_size=settings['title_card_font_size'],
		intro_text_color=settings['title_card_text_color'],
		playback_styles={
			'content': settings['content_speed'],
			'fast_forward': settings['silence_speed'],
		},
		segment_style_map={
			'content': 'content',
			'silence': 'fast_forward',
		},
		overlay_apply_style="fast_forward",
	)
	write_yaml_report(output_file, yaml_text)
	if args.debug:
		print_debug_summary(args, audio_path, temp_wav, output_file,
			output_media_file, raw_silences, silences, contents, scan_stats,
			auto_attempts, threshold_used, plot_file,
			threshold_db=settings['threshold_db'],
			min_silence=settings['min_silence'],
			min_content=settings['min_content'])
	print_summary(args.input_file, audio_duration, silences, contents, output_file,
		settings['silence_speed'], settings['content_speed'], debug_file,
		plot_file, threshold_used, settings['threshold_db'])
	if temp_wav is not None and args.keep_wav is False:
		os.remove(temp_wav)
	return

#============================================

if __name__ == '__main__':
	main()
