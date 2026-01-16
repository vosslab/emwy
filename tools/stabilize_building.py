#!/usr/bin/env python3

"""
stabilize_building.py

Global "bird on a building" stabilization as a standalone media-prep tool.

This tool is intentionally strict:
- It performs global alignment so the reference frame (building) is static.
- It enforces a single static crop for the entire output (no per-frame crop/zoom).
- It can optionally fall back to a budgeted border fill on rare jerk frames.
- It fails if crop constraints cannot be met and fill budgets are exceeded.
"""

# Standard Library
import argparse
import hashlib
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

# PIP3 modules
import yaml

#============================================

TOOL_CONFIG_HEADER_KEY = "stabilize_building"
TOOL_CONFIG_HEADER_VALUE = 1

#============================================

def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed CLI args.
	"""
	parser = argparse.ArgumentParser(
		description="Stabilize 'bird on a building' footage (global align + static crop)."
	)
	parser.add_argument(
		"-i", "--input", dest="input_file", required=True,
		help="Input media file path."
	)
	parser.add_argument(
		"-o", "--output", dest="output_file", default=None,
		help="Output stabilized media file path."
	)
	parser.add_argument(
		"-c", "--config", dest="config_file", default=None,
		help="Optional config YAML path (if missing, defaults are written and then read)."
	)
	parser.add_argument(
		"--write-default-config", dest="write_default_config", action="store_true",
		help="Write the default config file for this input and exit 0."
	)
	parser.add_argument(
		"--use-default-config", dest="use_default_config", action="store_true",
		help="Read the per-input default config file (error if missing)."
	)
	parser.add_argument(
		"--start", dest="start", default=None,
		help="Optional start time (seconds or HH:MM:SS[.ms])."
	)
	parser.add_argument(
		"--duration", dest="duration", default=None,
		help="Optional duration (seconds)."
	)
	parser.add_argument(
		"--end", dest="end", default=None,
		help="Optional end time (seconds or HH:MM:SS[.ms])."
	)
	parser.add_argument(
		"--copy-subs", dest="copy_subs", action="store_true",
		help="Copy subtitle streams if present (no timing or placement edits)."
	)
	parser.add_argument(
		"--no-copy-audio", dest="copy_audio", action="store_false",
		help="Do not copy audio streams (video-only output)."
	)
	parser.add_argument(
		"--keep-temp", dest="keep_temp", action="store_true",
		help="Keep temporary files under the cache directory."
	)
	parser.set_defaults(copy_audio=True)
	parser.set_defaults(copy_subs=False)
	parser.set_defaults(keep_temp=False)
	parser.set_defaults(write_default_config=False)
	parser.set_defaults(use_default_config=False)
	return parser.parse_args()

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

def run_process(cmd: list, cwd: str | None = None,
	capture_output: bool = True) -> subprocess.CompletedProcess:
	"""
	Run a subprocess command.

	Args:
		cmd: Command list to execute.
		cwd: Working directory.
		capture_output: Capture stdout and stderr when True.

	Returns:
		subprocess.CompletedProcess: Completed process.
	"""
	showcmd = shlex.join(cmd)
	print(f"CMD: '{showcmd}'")
	proc = subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=True)
	if proc.returncode != 0:
		stderr_text = proc.stderr.strip()
		raise RuntimeError(f"command failed: {showcmd}\n{stderr_text}")
	return proc

#============================================

def parse_time_seconds(value: str | None) -> float | None:
	"""
	Parse a time value into seconds.

	Args:
		value: None, seconds string, or HH:MM:SS[.ms].

	Returns:
		float | None: Parsed seconds.
	"""
	if value is None:
		return None
	text = str(value).strip()
	if text == "":
		return None
	if ":" not in text:
		return float(text)
	parts = text.split(":")
	if len(parts) != 3:
		raise RuntimeError("time must be seconds or HH:MM:SS[.ms]")
	hours = float(parts[0])
	minutes = float(parts[1])
	seconds = float(parts[2])
	if hours < 0 or minutes < 0 or seconds < 0:
		raise RuntimeError("time components must be non-negative")
	return hours * 3600.0 + minutes * 60.0 + seconds

#============================================

def fps_fraction_to_float(value: str) -> float:
	"""
	Convert an ffprobe frame-rate fraction string to float.

	Args:
		value: Fraction string like "30000/1001" or "30/1".

	Returns:
		float: FPS value.
	"""
	text = str(value).strip()
	if "/" in text:
		num_text, den_text = text.split("/", 1)
		num = float(num_text)
		den = float(den_text)
		if den == 0:
			raise RuntimeError("invalid fps denominator")
		return num / den
	return float(text)

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
	streams = data.get("streams", [])
	if len(streams) == 0:
		raise RuntimeError("no video stream found for metadata")
	stream = streams[0]
	width = int(stream.get("width", 0))
	height = int(stream.get("height", 0))
	if width <= 0 or height <= 0:
		raise RuntimeError("invalid video resolution from ffprobe")
	fps_value = stream.get("r_frame_rate")
	if fps_value is None or fps_value == "0/0":
		fps_value = stream.get("avg_frame_rate")
	if fps_value is None or fps_value == "0/0":
		raise RuntimeError("invalid frame rate from ffprobe")
	return {
		"width": width,
		"height": height,
		"fps_fraction": fps_value,
		"fps": fps_fraction_to_float(fps_value),
		"pix_fmt": stream.get("pix_fmt", "yuv420p"),
	}

#============================================

def probe_all_streams(input_file: str) -> list:
	"""
	Probe all streams metadata using ffprobe.

	Args:
		input_file: Media file path.

	Returns:
		list: List of stream mappings.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-show_entries", "stream=index,codec_type,codec_name,codec_tag_string,channels,sample_rate,disposition",
		"-of", "json",
		input_file,
	]
	proc = run_process(cmd, capture_output=True)
	data = json.loads(proc.stdout)
	streams = data.get("streams", [])
	if not isinstance(streams, list):
		raise RuntimeError("invalid ffprobe stream list")
	return streams

#============================================

def select_audio_stream_for_copy(streams: list) -> dict | None:
	"""
	Select an audio stream to map/copy.

	Args:
		streams: Stream mappings from ffprobe.

	Returns:
		dict | None: Selected audio stream mapping, or None.
	"""
	audio_streams = []
	for stream in streams:
		if not isinstance(stream, dict):
			continue
		if stream.get("codec_type") != "audio":
			continue
		codec_name = stream.get("codec_name")
		if codec_name is None:
			continue
		if str(codec_name).strip().lower() == "none":
			continue
		audio_streams.append(stream)
	if len(audio_streams) == 0:
		return None
	defaults = []
	for stream in audio_streams:
		disposition = stream.get("disposition", {})
		if isinstance(disposition, dict) and int(disposition.get("default", 0)) == 1:
			defaults.append(stream)
	if len(defaults) > 0:
		return defaults[0]
	return audio_streams[0]

#============================================

def probe_duration_seconds(input_file: str) -> float:
	"""
	Probe media duration in seconds using ffprobe.

	Args:
		input_file: Media file path.

	Returns:
		float: Duration in seconds.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-show_entries", "format=duration",
		"-of", "default=nw=1:nk=1",
		input_file,
	]
	proc = run_process(cmd, capture_output=True)
	text = proc.stdout.strip()
	if text == "":
		raise RuntimeError("ffprobe did not return duration")
	seconds = float(text)
	if seconds <= 0:
		raise RuntimeError("ffprobe returned non-positive duration")
	return seconds

#============================================

def default_config_path(input_file: str) -> str:
	"""
	Build the default config path based on the input file.

	Args:
		input_file: Input file path.

	Returns:
		str: Config path.
	"""
	return f"{input_file}.stabilize_building.config.yaml"

#============================================

def default_cache_dir(input_file: str) -> str:
	"""
	Build a default cache directory path based on the input file.

	Args:
		input_file: Input file path.

	Returns:
		str: Cache dir path.
	"""
	return f"{input_file}.stabilize_building_cache"

#============================================

def default_config() -> dict:
	"""
	Build the default config dictionary.

	Returns:
		dict: Default config.
	"""
	return {
		TOOL_CONFIG_HEADER_KEY: TOOL_CONFIG_HEADER_VALUE,
		"settings": {
			"engine": {
				"kind": "vidstab",
				"detect": {
					"shakiness": 5,
					"accuracy": 15,
					"stepsize": 6,
					"mincontrast": 0.25,
					"reference_frame": 1,
				},
				"transform": {
					"optalgo": "opt",
					"smoothing": 15,
				},
			},
			"crop": {
				"min_area_ratio": 0.25,
				"min_height_px": 0,
				"min_height_ratio": 0.65,
				"center_safe_margin": 0.10,
			},
			"border": {
				"mode": "crop_prefer_fill_fallback",
				"fill": {
					"kind": "center_patch_median",
					"patch_fraction": 0.10,
					"sample_frames": 25,
					"max_area_ratio": 0.02,
					"max_frames_ratio": 0.02,
					"max_consecutive_frames": 15,
				},
			},
			"rejection": {
				"mode": "budgeted",
				"max_missing_fraction": 0.05,
				"max_mad_fraction": 0.50,
				"max_scale_jump": 0.50,
				"max_abs_angle_rad": 0.60,
				"max_abs_zoom_percent": 35.0,
				"outlier_max_frames_ratio": 0.90,
				"outlier_max_consecutive_frames": 600,
			},
			"io": {
				"cache_dir": None,
				"report_format": "yaml",
			},
		},
	}

#============================================

def build_config_text(config: dict) -> str:
	"""
	Build YAML text for the config file.

	Args:
		config: Config dictionary.

	Returns:
		str: YAML content.
	"""
	settings = config.get("settings", {})
	engine = settings.get("engine", {})
	detect = engine.get("detect", {})
	transform = engine.get("transform", {})
	crop = settings.get("crop", {})
	border = settings.get("border", {})
	fill = border.get("fill", {})
	rejection = settings.get("rejection", {})
	io = settings.get("io", {})
	lines = []
	lines.append(f"{TOOL_CONFIG_HEADER_KEY}: {TOOL_CONFIG_HEADER_VALUE}")
	lines.append("settings:")
	lines.append("  engine:")
	lines.append("    kind: vidstab")
	lines.append("    detect:")
	lines.append(f"      shakiness: {detect.get('shakiness', 5)}")
	lines.append(f"      accuracy: {detect.get('accuracy', 15)}")
	lines.append(f"      stepsize: {detect.get('stepsize', 6)}")
	lines.append(f"      mincontrast: {detect.get('mincontrast', 0.25)}")
	lines.append(f"      reference_frame: {detect.get('reference_frame', 1)}")
	lines.append("    transform:")
	lines.append(f"      optalgo: {transform.get('optalgo', 'opt')}")
	lines.append(f"      smoothing: {transform.get('smoothing', 15)}")
	lines.append("  crop:")
	lines.append(f"    min_area_ratio: {crop.get('min_area_ratio', 0.25)}")
	lines.append(f"    min_height_px: {crop.get('min_height_px', 0)}")
	lines.append(f"    min_height_ratio: {crop.get('min_height_ratio', 0.65)}")
	lines.append(f"    center_safe_margin: {crop.get('center_safe_margin', 0.10)}")
	lines.append("  border:")
	lines.append(f"    mode: {border.get('mode', 'crop_only')}")
	lines.append("    fill:")
	lines.append(f"      kind: {fill.get('kind', 'center_patch_median')}")
	lines.append(f"      patch_fraction: {fill.get('patch_fraction', 0.10)}")
	lines.append(f"      sample_frames: {fill.get('sample_frames', 25)}")
	lines.append(f"      max_area_ratio: {fill.get('max_area_ratio', 0.02)}")
	lines.append(f"      max_frames_ratio: {fill.get('max_frames_ratio', 0.02)}")
	lines.append(f"      max_consecutive_frames: {fill.get('max_consecutive_frames', 15)}")
	lines.append("  rejection:")
	lines.append(f"    mode: {rejection.get('mode', 'budgeted')}")
	lines.append(f"    max_missing_fraction: {rejection.get('max_missing_fraction', 0.05)}")
	lines.append(f"    max_mad_fraction: {rejection.get('max_mad_fraction', 0.50)}")
	lines.append(f"    max_scale_jump: {rejection.get('max_scale_jump', 0.50)}")
	lines.append(f"    max_abs_angle_rad: {rejection.get('max_abs_angle_rad', 0.60)}")
	lines.append(f"    max_abs_zoom_percent: {rejection.get('max_abs_zoom_percent', 35.0)}")
	lines.append(f"    outlier_max_frames_ratio: {rejection.get('outlier_max_frames_ratio', 0.90)}")
	lines.append(f"    outlier_max_consecutive_frames: {rejection.get('outlier_max_consecutive_frames', 600)}")
	lines.append("  io:")
	cache_dir_value = io.get("cache_dir")
	if cache_dir_value is None:
		lines.append("    cache_dir: null")
	else:
		lines.append(f"    cache_dir: \"{str(cache_dir_value)}\"")
	lines.append(f"    report_format: {io.get('report_format', 'yaml')}")
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
	os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
	with open(config_path, "w", encoding="utf-8") as handle:
		handle.write(text)
	return

#============================================

def load_config(config_path: str) -> dict:
	"""
	Load a config file from disk.

	Args:
		config_path: Config file path.

	Returns:
		dict: Parsed config mapping.
	"""
	with open(config_path, "r", encoding="utf-8") as handle:
		data = yaml.safe_load(handle)
	if not isinstance(data, dict):
		raise RuntimeError("config file must be a mapping")
	if data.get(TOOL_CONFIG_HEADER_KEY) != TOOL_CONFIG_HEADER_VALUE:
		raise RuntimeError(f"config file must set {TOOL_CONFIG_HEADER_KEY}: {TOOL_CONFIG_HEADER_VALUE}")
	return data

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

def coerce_str(value, config_path: str, key_path: str) -> str:
	"""
	Coerce a value to str.

	Args:
		value: Raw value.
		config_path: Config file path.
		key_path: Key path string.

	Returns:
		str: String value.
	"""
	if isinstance(value, str):
		return value
	raise RuntimeError(f"config {config_path}: {key_path} must be a string")

#============================================

def build_settings(config: dict, config_path: str, input_file: str) -> dict:
	"""
	Normalize settings with defaults.

	Args:
		config: Raw config mapping.
		config_path: Config file path.
		input_file: Input file path.

	Returns:
		dict: Normalized settings.
	"""
	defaults = default_config()
	settings = defaults.get("settings", {})
	overrides = {}
	if isinstance(config, dict):
		overrides = config.get("settings", {})
	engine = overrides.get("engine", {})
	detect = engine.get("detect", {})
	transform = engine.get("transform", {})
	crop = overrides.get("crop", {})
	border = overrides.get("border", {})
	fill = border.get("fill", {})
	rejection = overrides.get("rejection", {})
	io = overrides.get("io", {})
	engine_kind = coerce_str(engine.get("kind", settings["engine"]["kind"]),
		config_path, "settings.engine.kind")
	if engine_kind != "vidstab":
		raise RuntimeError("only engine.kind: vidstab is supported")
	shakiness = coerce_int(detect.get("shakiness", settings["engine"]["detect"]["shakiness"]),
		config_path, "settings.engine.detect.shakiness")
	accuracy = coerce_int(detect.get("accuracy", settings["engine"]["detect"]["accuracy"]),
		config_path, "settings.engine.detect.accuracy")
	stepsize = coerce_int(detect.get("stepsize", settings["engine"]["detect"]["stepsize"]),
		config_path, "settings.engine.detect.stepsize")
	mincontrast = coerce_float(detect.get("mincontrast", settings["engine"]["detect"]["mincontrast"]),
		config_path, "settings.engine.detect.mincontrast")
	reference_frame = coerce_int(detect.get("reference_frame", settings["engine"]["detect"]["reference_frame"]),
		config_path, "settings.engine.detect.reference_frame")
	optalgo = coerce_str(transform.get("optalgo", settings["engine"]["transform"]["optalgo"]),
		config_path, "settings.engine.transform.optalgo")
	smoothing = coerce_int(transform.get("smoothing", settings["engine"]["transform"]["smoothing"]),
		config_path, "settings.engine.transform.smoothing")
	min_area_ratio = coerce_float(crop.get("min_area_ratio", settings["crop"]["min_area_ratio"]),
		config_path, "settings.crop.min_area_ratio")
	min_height_px = coerce_int(crop.get("min_height_px", settings["crop"]["min_height_px"]),
		config_path, "settings.crop.min_height_px")
	min_height_ratio = coerce_float(
		crop.get("min_height_ratio", settings["crop"].get("min_height_ratio", 0.0)),
		config_path,
		"settings.crop.min_height_ratio",
	)
	center_safe_margin = coerce_float(crop.get("center_safe_margin", settings["crop"]["center_safe_margin"]),
		config_path, "settings.crop.center_safe_margin")
	border_mode = coerce_str(border.get("mode", settings["border"]["mode"]),
		config_path, "settings.border.mode")
	fill_kind = coerce_str(fill.get("kind", settings["border"]["fill"]["kind"]),
		config_path, "settings.border.fill.kind")
	fill_patch_fraction = coerce_float(fill.get("patch_fraction", settings["border"]["fill"]["patch_fraction"]),
		config_path, "settings.border.fill.patch_fraction")
	fill_sample_frames = coerce_int(fill.get("sample_frames", settings["border"]["fill"]["sample_frames"]),
		config_path, "settings.border.fill.sample_frames")
	fill_max_area_ratio = coerce_float(fill.get("max_area_ratio", settings["border"]["fill"]["max_area_ratio"]),
		config_path, "settings.border.fill.max_area_ratio")
	fill_max_frames_ratio = coerce_float(fill.get("max_frames_ratio", settings["border"]["fill"]["max_frames_ratio"]),
		config_path, "settings.border.fill.max_frames_ratio")
	fill_max_consecutive_frames = coerce_int(
		fill.get("max_consecutive_frames", settings["border"]["fill"]["max_consecutive_frames"]),
		config_path, "settings.border.fill.max_consecutive_frames"
	)
	rejection_mode = coerce_str(rejection.get("mode", settings["rejection"].get("mode", "budgeted")),
		config_path, "settings.rejection.mode")
	max_missing_fraction = coerce_float(rejection.get("max_missing_fraction", settings["rejection"]["max_missing_fraction"]),
		config_path, "settings.rejection.max_missing_fraction")
	max_mad_fraction = coerce_float(rejection.get("max_mad_fraction", settings["rejection"]["max_mad_fraction"]),
		config_path, "settings.rejection.max_mad_fraction")
	max_scale_jump = coerce_float(rejection.get("max_scale_jump", settings["rejection"]["max_scale_jump"]),
		config_path, "settings.rejection.max_scale_jump")
	max_abs_angle_rad = coerce_float(rejection.get("max_abs_angle_rad", settings["rejection"]["max_abs_angle_rad"]),
		config_path, "settings.rejection.max_abs_angle_rad")
	max_abs_zoom_percent = coerce_float(
		rejection.get("max_abs_zoom_percent", settings["rejection"]["max_abs_zoom_percent"]),
		config_path, "settings.rejection.max_abs_zoom_percent"
	)
	outlier_max_frames_ratio = coerce_float(
		rejection.get("outlier_max_frames_ratio", settings["rejection"].get("outlier_max_frames_ratio", 0.0)),
		config_path, "settings.rejection.outlier_max_frames_ratio"
	)
	outlier_max_consecutive_frames = coerce_int(
		rejection.get("outlier_max_consecutive_frames",
			settings["rejection"].get("outlier_max_consecutive_frames", 0)),
		config_path, "settings.rejection.outlier_max_consecutive_frames"
	)
	cache_dir = io.get("cache_dir")
	if cache_dir is None:
		cache_dir = default_cache_dir(input_file)
	if not isinstance(cache_dir, str) or cache_dir.strip() == "":
		raise RuntimeError(f"config {config_path}: settings.io.cache_dir must be a string or null")
	report_format = io.get("report_format", settings["io"]["report_format"])
	report_format = coerce_str(report_format, config_path, "settings.io.report_format")
	if report_format not in ("yaml", "json"):
		raise RuntimeError("report_format must be yaml or json")
	if shakiness < 1 or shakiness > 10:
		raise RuntimeError("shakiness must be 1..10")
	if accuracy < 1 or accuracy > 15:
		raise RuntimeError("accuracy must be 1..15")
	if accuracy < shakiness:
		raise RuntimeError("accuracy must be >= shakiness")
	if stepsize < 1 or stepsize > 32:
		raise RuntimeError("stepsize must be 1..32")
	if mincontrast < 0 or mincontrast > 1:
		raise RuntimeError("mincontrast must be 0..1")
	if reference_frame < 1:
		raise RuntimeError("reference_frame must be >= 1")
	if smoothing < 0:
		raise RuntimeError("smoothing must be >= 0")
	if min_area_ratio <= 0 or min_area_ratio > 1:
		raise RuntimeError("min_area_ratio must be > 0 and <= 1")
	if min_height_px < 0:
		raise RuntimeError("min_height_px must be >= 0")
	if min_height_ratio < 0 or min_height_ratio > 1:
		raise RuntimeError("min_height_ratio must be 0..1")
	if min_height_px == 0 and min_height_ratio == 0:
		raise RuntimeError("either min_height_px or min_height_ratio must be set")
	if center_safe_margin < 0 or center_safe_margin >= 0.5:
		raise RuntimeError("center_safe_margin must be >= 0 and < 0.5")
	if border_mode not in ("crop_only", "crop_prefer_fill_fallback"):
		raise RuntimeError("border.mode must be crop_only or crop_prefer_fill_fallback")
	if fill_kind != "center_patch_median":
		raise RuntimeError("border.fill.kind must be center_patch_median")
	if fill_patch_fraction <= 0 or fill_patch_fraction > 0.5:
		raise RuntimeError("border.fill.patch_fraction must be > 0 and <= 0.5")
	if fill_sample_frames <= 0:
		raise RuntimeError("border.fill.sample_frames must be positive")
	if fill_max_area_ratio < 0 or fill_max_area_ratio > 1:
		raise RuntimeError("border.fill.max_area_ratio must be 0..1")
	if fill_max_frames_ratio < 0 or fill_max_frames_ratio > 1:
		raise RuntimeError("border.fill.max_frames_ratio must be 0..1")
	if fill_max_consecutive_frames < 0:
		raise RuntimeError("border.fill.max_consecutive_frames must be >= 0")
	if rejection_mode not in ("max", "budgeted"):
		raise RuntimeError("rejection.mode must be max or budgeted")
	if max_missing_fraction < 0 or max_missing_fraction > 1:
		raise RuntimeError("max_missing_fraction must be 0..1")
	if max_mad_fraction <= 0:
		raise RuntimeError("max_mad_fraction must be positive")
	if max_scale_jump <= 0:
		raise RuntimeError("max_scale_jump must be positive")
	if max_abs_angle_rad < 0:
		raise RuntimeError("max_abs_angle_rad must be >= 0")
	if max_abs_zoom_percent < 0:
		raise RuntimeError("max_abs_zoom_percent must be >= 0")
	if outlier_max_frames_ratio < 0 or outlier_max_frames_ratio > 1:
		raise RuntimeError("outlier_max_frames_ratio must be 0..1")
	if outlier_max_consecutive_frames < 0:
		raise RuntimeError("outlier_max_consecutive_frames must be >= 0")
	if optalgo not in ("opt", "gauss", "avg"):
		raise RuntimeError("optalgo must be opt, gauss, or avg")
	return {
		"engine": {
			"kind": "vidstab",
			"detect": {
				"shakiness": shakiness,
				"accuracy": accuracy,
				"stepsize": stepsize,
				"mincontrast": mincontrast,
				"reference_frame": reference_frame,
			},
			"transform": {
				"optalgo": optalgo,
				"smoothing": smoothing,
			},
		},
		"crop": {
			"min_area_ratio": min_area_ratio,
			"min_height_px": min_height_px,
			"min_height_ratio": min_height_ratio,
			"center_safe_margin": center_safe_margin,
		},
		"border": {
			"mode": border_mode,
			"fill": {
				"kind": fill_kind,
				"patch_fraction": fill_patch_fraction,
				"sample_frames": fill_sample_frames,
				"max_area_ratio": fill_max_area_ratio,
				"max_frames_ratio": fill_max_frames_ratio,
				"max_consecutive_frames": fill_max_consecutive_frames,
			},
		},
		"rejection": {
			"mode": rejection_mode,
			"max_missing_fraction": max_missing_fraction,
			"max_mad_fraction": max_mad_fraction,
			"max_scale_jump": max_scale_jump,
			"max_abs_angle_rad": max_abs_angle_rad,
			"max_abs_zoom_percent": max_abs_zoom_percent,
			"outlier_max_frames_ratio": outlier_max_frames_ratio,
			"outlier_max_consecutive_frames": outlier_max_consecutive_frames,
		},
		"io": {
			"cache_dir": cache_dir,
			"report_format": report_format,
		},
	}

#============================================

def check_vidstab_filters() -> None:
	"""
	Verify ffmpeg exposes vidstabdetect and vidstabtransform filters.
	"""
	cmd = ["ffmpeg", "-hide_banner", "-filters"]
	proc = run_process(cmd, capture_output=True)
	text = proc.stdout
	if "vidstabdetect" not in text or "vidstabtransform" not in text:
		raise RuntimeError("ffmpeg is missing vid.stab filters (vidstabdetect/vidstabtransform)")
	return

#============================================

def ffmpeg_version_fingerprint() -> dict:
	"""
	Get a minimal ffmpeg toolchain fingerprint.

	Returns:
		dict: Fingerprint fields.
	"""
	cmd = ["ffmpeg", "-hide_banner", "-version"]
	proc = run_process(cmd, capture_output=True)
	lines = [line.strip() for line in proc.stdout.splitlines() if line.strip() != ""]
	version_line = lines[0] if len(lines) > 0 else ""
	config_line = ""
	for line in lines[:15]:
		if line.lower().startswith("configuration:"):
			config_line = line
			break
	return {
		"ffmpeg_version": version_line,
		"ffmpeg_configuration": config_line,
	}

#============================================

def file_identity(input_file: str) -> dict:
	"""
	Build an input file identity snapshot for caching and reporting.

	Args:
		input_file: Input file path.

	Returns:
		dict: Identity mapping.
	"""
	abs_path = os.path.abspath(input_file)
	stat = os.stat(abs_path)
	return {
		"path": abs_path,
		"size": int(stat.st_size),
		"mtime_ns": int(stat.st_mtime_ns),
	}

#============================================

def stable_hash_mapping(data: dict) -> str:
	"""
	Hash a mapping deterministically to a short hex string.

	Args:
		data: Mapping to hash.

	Returns:
		str: Hex digest (sha256).
	"""
	text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
	return hashlib.sha256(text.encode("utf-8")).hexdigest()

#============================================

def escape_ffmpeg_filter_value(value: str) -> str:
	"""
	Escape a value for ffmpeg filter arguments.

	Args:
		value: Raw value.

	Returns:
		str: Escaped value.
	"""
	text = str(value)
	text = text.replace("\\", "\\\\")
	text = text.replace(":", "\\:")
	text = text.replace(",", "\\,")
	text = text.replace("'", "\\'")
	text = text.replace("[", "\\[")
	text = text.replace("]", "\\]")
	return text

#============================================

def rgb_hex(red: int, green: int, blue: int) -> str:
	"""
	Format an RGB triplet as a #rrggbb string.

	Args:
		red: 0..255.
		green: 0..255.
		blue: 0..255.

	Returns:
		str: Hex color string.
	"""
	r = max(0, min(255, int(red)))
	g = max(0, min(255, int(green)))
	b = max(0, min(255, int(blue)))
	return f"#{r:02x}{g:02x}{b:02x}"

#============================================

def count_frames_in_trf(trf_path: str) -> int:
	"""
	Count frames in a vid.stab transforms file by counting 'Frame ' lines.

	Args:
		trf_path: Path to .trf file.

	Returns:
		int: Frame count.
	"""
	count = 0
	with open(trf_path, "r", encoding="utf-8", errors="replace") as handle:
		for line in handle:
			if line.startswith("Frame "):
				count += 1
	if count <= 0:
		raise RuntimeError("vidstabdetect produced no frames in transforms file")
	return count

#============================================

def run_vidstabdetect(input_file: str, trf_path: str, detect: dict,
	start_seconds: float | None, duration_seconds: float | None) -> None:
	"""
	Run vidstabdetect to generate a transforms file.

	Args:
		input_file: Input media file.
		trf_path: Output transforms file path.
		detect: Detect settings mapping.
		start_seconds: Optional start seconds.
		duration_seconds: Optional duration seconds.
	"""
	cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
	if start_seconds is not None:
		cmd += ["-ss", f"{start_seconds}"]
	if duration_seconds is not None:
		cmd += ["-t", f"{duration_seconds}"]
	cmd += ["-i", input_file]
	cmd += ["-an", "-sn"]
	result_path = escape_ffmpeg_filter_value(trf_path)
	filter_text = (
		"vidstabdetect="
		f"fileformat=ascii:"
		f"tripod={detect['reference_frame']}:"
		f"shakiness={detect['shakiness']}:"
		f"accuracy={detect['accuracy']}:"
		f"stepsize={detect['stepsize']}:"
		f"mincontrast={detect['mincontrast']}:"
		f"result={result_path}"
	)
	cmd += ["-vf", filter_text, "-f", "null", "-"]
	run_process(cmd, capture_output=True)
	if not os.path.isfile(trf_path):
		raise RuntimeError("vidstabdetect did not produce a transforms file")
	return

#============================================

def run_global_motions_from_trf(trf_path: str, width: int, height: int, fps: float,
	frame_count: int, transform: dict, output_dir: str | None = None) -> tuple[str, dict, str]:
	"""
	Generate a global_motions.trf using vidstabtransform debug on synthetic frames.

	This avoids decoding the source media again for crop feasibility computation.

	Args:
		trf_path: Path to transforms file.
		width: Source width.
		height: Source height.
		fps: Source fps.
		frame_count: Number of frames in the range.
		transform: Transform settings mapping.

	Returns:
		tuple[str, dict, str]: (global_motions_text, debug_meta, output_path)
	"""
	temp_dir_handle = None
	temp_dir = output_dir
	if temp_dir is None:
		temp_dir_handle = tempfile.TemporaryDirectory(prefix="stabilize-build-", dir=None)
		temp_dir = temp_dir_handle.name
	os.makedirs(temp_dir, exist_ok=True)
	motions_path = os.path.join(temp_dir, "global_motions.trf")
	input_path = escape_ffmpeg_filter_value(trf_path)
	filter_text = (
		"vidstabtransform="
		f"input={input_path}:"
		"relative=1:"
		"optzoom=0:"
		"zoom=0:"
		"crop=black:"
		f"optalgo={transform['optalgo']}:"
		f"smoothing={transform['smoothing']}:"
		"debug=1"
	)
	source_spec = f"color=black:size={width}x{height}:rate={fps}"
	cmd = [
		"ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
		"-f", "lavfi", "-i", source_spec,
		"-frames:v", str(frame_count),
		"-an", "-sn",
		"-vf", filter_text,
		"-f", "null", "-",
	]
	start_time = time.time()
	run_process(cmd, cwd=temp_dir, capture_output=True)
	elapsed = time.time() - start_time
	if not os.path.isfile(motions_path):
		raise RuntimeError("vidstabtransform debug did not produce global_motions.trf")
	with open(motions_path, "r", encoding="utf-8", errors="replace") as handle:
		text = handle.read()
	if temp_dir_handle is not None:
		temp_dir_handle.cleanup()
	return text, {
		"generated_in_seconds": elapsed,
		"frame_count": frame_count,
	}, motions_path

#============================================

def parse_global_motions_text(text: str) -> list:
	"""
	Parse global_motions.trf text into per-frame transform dicts.

	Args:
		text: global_motions.trf content.

	Returns:
		list: List of per-frame transforms.
	"""
	lines = [line.rstrip("\n") for line in text.splitlines()]
	frames = []
	i = 0
	while i < len(lines):
		line = lines[i].strip()
		i += 1
		if line == "" or line.startswith("#"):
			continue
		parts = [p for p in line.split(" ") if p != ""]
		if len(parts) < 6:
			raise RuntimeError("global_motions.trf parse error: expected 6 fields")
		try:
			dx = float(parts[1])
			dy = float(parts[2])
			angle = float(parts[3])
			zoom_percent = float(parts[4])
			flag = int(float(parts[5]))
		except ValueError as exc:
			raise RuntimeError("global_motions.trf parse error: non-numeric field") from exc
		info = {
			"dx": dx,
			"dy": dy,
			"angle": angle,
			"zoom_percent": zoom_percent,
			"flag": flag,
			"missing": False,
			"is_reference": False,
			"fields_count": None,
			"error": None,
		}
		if i < len(lines):
			next_line = lines[i].strip()
			if next_line.startswith("#"):
				i += 1
				comment = next_line[1:].strip()
				if comment.lower().startswith("no fields"):
					if len(frames) == 0:
						info["is_reference"] = True
						info["missing"] = False
					else:
						info["missing"] = True
				else:
					comment_parts = [p for p in comment.split(" ") if p != ""]
					if len(comment_parts) >= 2:
						try:
							info["error"] = float(comment_parts[0])
							info["fields_count"] = int(float(comment_parts[1]))
						except ValueError:
							pass
		frames.append(info)
	if len(frames) == 0:
		raise RuntimeError("global_motions.trf had no frame transforms")
	return frames

#============================================

def median(values: list[float]) -> float:
	"""
	Compute median of a list of floats.

	Args:
		values: Values list.

	Returns:
		float: Median value.
	"""
	if len(values) == 0:
		raise RuntimeError("median() requires at least one value")
	items = sorted(values)
	mid = len(items) // 2
	if len(items) % 2 == 1:
		return float(items[mid])
	return (float(items[mid - 1]) + float(items[mid])) / 2.0

#============================================

def mad(values: list[float]) -> float:
	"""
	Compute median absolute deviation of a list of floats.

	Args:
		values: Values list.

	Returns:
		float: MAD value.
	"""
	center = median(values)
	dev = [abs(v - center) for v in values]
	return median(dev)

#============================================

def scale_ratio_from_zoom_percent(zoom_percent: float) -> float:
	"""
	Convert a zoom percentage into a scale ratio.

	Args:
		zoom_percent: Zoom in percent (0.5 means +0.5%).

	Returns:
		float: Scale ratio.
	"""
	return 1.0 + zoom_percent / 100.0

#============================================

def compute_constraint_crop_rect(width: int, height: int, min_area_ratio: float,
	min_height_px: int, center_safe_margin: float) -> dict:
	"""
	Compute a centered crop rectangle that satisfies crop constraints.

	This is used as the fixed crop for border-fill fallback evaluation.

	Args:
		width: Frame width.
		height: Frame height.
		min_area_ratio: Minimum crop area ratio.
		min_height_px: Minimum crop height.
		center_safe_margin: Normalized safe margin inset (0..0.5).

	Returns:
		dict: Crop rectangle {x,y,w,h} or empty {w:0,h:0}.
	"""
	aspect = float(width) / float(height)
	safe_h = float(height) * (1.0 - 2.0 * float(center_safe_margin))
	required_h = max(float(min_height_px), safe_h)
	required_area = float(min_area_ratio) * float(width) * float(height)
	if required_area > 0:
		h_area = math.sqrt(required_area / aspect)
		required_h = max(required_h, h_area)
	if required_h > float(height):
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	required_w = required_h * aspect
	if required_w > float(width):
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	crop_w = int(math.floor(required_w))
	crop_h = int(math.floor(required_h))
	if crop_w <= 0 or crop_h <= 0:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	if crop_w > width:
		crop_w = width
	if crop_h > height:
		crop_h = height
	crop_x = int((width - crop_w) // 2)
	crop_y = int((height - crop_h) // 2)
	return {"x": crop_x, "y": crop_y, "w": crop_w, "h": crop_h}

#============================================

def compute_minimum_centered_crop(width: int, height: int, min_area_ratio: float,
	min_height_px: int) -> dict:
	"""
	Compute the smallest centered crop rectangle that satisfies basic constraints.

	Args:
		width: Frame width.
		height: Frame height.
		min_area_ratio: Minimum crop area ratio.
		min_height_px: Minimum crop height.

	Returns:
		dict: Crop rectangle {x,y,w,h} or empty {w:0,h:0}.
	"""
	aspect = float(width) / float(height)
	required_h = float(min_height_px)
	required_area = float(min_area_ratio) * float(width) * float(height)
	if required_area > 0:
		h_area = math.sqrt(required_area / aspect)
		required_h = max(required_h, h_area)
	if required_h > float(height):
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	required_w = required_h * aspect
	if required_w > float(width):
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	crop_w = int(math.ceil(required_w))
	crop_h = int(math.ceil(required_h))
	if crop_w <= 0 or crop_h <= 0:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	if crop_w > width or crop_h > height:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	crop_x = int((width - crop_w) // 2)
	crop_y = int((height - crop_h) // 2)
	return {"x": crop_x, "y": crop_y, "w": crop_w, "h": crop_h}

#============================================

def compute_valid_bbox(width: int, height: int, dx: float, dy: float) -> tuple[float, float, float, float]:
	"""
	Compute the valid pixel bbox after applying stabilization translation.

	Args:
		width: Frame width.
		height: Frame height.
		dx: Per-frame dx from global motion path.
		dy: Per-frame dy from global motion path.

	Returns:
		tuple[float,float,float,float]: (left, top, right, bottom).
	"""
	shift_x = -float(dx)
	shift_y = -float(dy)
	left = max(0.0, shift_x)
	right = min(float(width), float(width) + shift_x)
	top = max(0.0, shift_y)
	bottom = min(float(height), float(height) + shift_y)
	return left, top, right, bottom

#============================================

def compute_fill_budget(transforms: list, width: int, height: int, crop_rect: dict,
	max_area_ratio: float, max_frames_ratio: float, max_consecutive_frames: int) -> dict:
	"""
	Compute fill budget usage for a fixed crop rectangle over a motion path.

	Args:
		transforms: Per-frame motion transforms.
		width: Frame width.
		height: Frame height.
		crop_rect: Fixed crop rectangle in source pixels.
		max_area_ratio: Maximum fill area ratio allowed per frame.
		max_frames_ratio: Maximum fraction of frames allowed to need fill.
		max_consecutive_frames: Maximum run of consecutive frames allowed to need fill.

	Returns:
		dict: Fill stats including pass/fail.
	"""
	cx = float(crop_rect["x"])
	cy = float(crop_rect["y"])
	cw = float(crop_rect["w"])
	ch = float(crop_rect["h"])
	if cw <= 0 or ch <= 0:
		return {"pass": False, "reason": "invalid crop rectangle"}
	area = cw * ch
	total_frames = 0
	frames_with_fill = 0
	max_fill_ratio = 0.0
	max_gap_px = 0.0
	current_run = 0
	max_run = 0
	for item in transforms:
		if item.get("missing") or item.get("is_reference"):
			continue
		total_frames += 1
		left, top, right, bottom = compute_valid_bbox(width, height, item["dx"], item["dy"])
		ix0 = max(cx, left)
		iy0 = max(cy, top)
		ix1 = min(cx + cw, right)
		iy1 = min(cy + ch, bottom)
		iw = max(0.0, ix1 - ix0)
		ih = max(0.0, iy1 - iy0)
		inter_area = iw * ih
		fill_area = max(0.0, area - inter_area)
		fill_ratio = fill_area / area if area > 0 else 1.0
		if fill_ratio > max_fill_ratio:
			max_fill_ratio = fill_ratio
		needs_fill = fill_area > 0.0
		if needs_fill:
			frames_with_fill += 1
			current_run += 1
			if current_run > max_run:
				max_run = current_run
		else:
			current_run = 0
		gap_left = max(0.0, cx - left)
		gap_right = max(0.0, (cx + cw) - right)
		gap_top = max(0.0, cy - top)
		gap_bottom = max(0.0, (cy + ch) - bottom)
		max_gap_px = max(max_gap_px, gap_left, gap_right, gap_top, gap_bottom)
	frames_ratio = float(frames_with_fill) / float(total_frames) if total_frames > 0 else 1.0
	pass_budget = True
	reasons = []
	if max_fill_ratio > float(max_area_ratio):
		pass_budget = False
		reasons.append("max_area_ratio exceeded")
	if frames_ratio > float(max_frames_ratio):
		pass_budget = False
		reasons.append("max_frames_ratio exceeded")
	if max_consecutive_frames >= 0 and max_run > int(max_consecutive_frames):
		pass_budget = False
		reasons.append("max_consecutive_frames exceeded")
	return {
		"pass": pass_budget,
		"reasons": reasons,
		"total_frames": total_frames,
		"frames_with_fill": frames_with_fill,
		"frames_ratio": frames_ratio,
		"max_consecutive_frames": max_run,
		"max_fill_area_ratio": max_fill_ratio,
		"max_gap_px": max_gap_px,
	}

#============================================

def compute_static_crop(width: int, height: int, transforms: list) -> dict:
	"""
	Compute a single static crop rectangle from per-frame translations.

	Args:
		width: Frame width.
		height: Frame height.
		transforms: Per-frame transforms.

	Returns:
		dict: Crop rectangle {x,y,w,h} in source pixels.
	"""
	left = 0.0
	top = 0.0
	right = float(width)
	bottom = float(height)
	for item in transforms:
		if item.get("missing"):
			continue
		shift_x = -float(item["dx"])
		shift_y = -float(item["dy"])
		frame_left = max(0.0, shift_x)
		frame_right = min(float(width), float(width) + shift_x)
		frame_top = max(0.0, shift_y)
		frame_bottom = min(float(height), float(height) + shift_y)
		left = max(left, frame_left)
		right = min(right, frame_right)
		top = max(top, frame_top)
		bottom = min(bottom, frame_bottom)
	x0 = int(math.ceil(left))
	y0 = int(math.ceil(top))
	x1 = int(math.floor(right))
	y1 = int(math.floor(bottom))
	raw_w = x1 - x0
	raw_h = y1 - y0
	if raw_w <= 0 or raw_h <= 0:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	desired_aspect = float(width) / float(height)
	if float(raw_w) / float(raw_h) > desired_aspect:
		crop_h = raw_h
		crop_w = int(math.floor(float(crop_h) * desired_aspect))
	else:
		crop_w = raw_w
		crop_h = int(math.floor(float(crop_w) / desired_aspect))
	if crop_w <= 0 or crop_h <= 0:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	crop_x = x0 + (raw_w - crop_w) // 2
	crop_y = y0 + (raw_h - crop_h) // 2
	return {"x": int(crop_x), "y": int(crop_y), "w": int(crop_w), "h": int(crop_h)}

#============================================

def crop_constraints_ok(width: int, height: int, crop_rect: dict,
	min_area_ratio: float, min_height_px: int, center_safe_margin: float) -> tuple[bool, list]:
	"""
	Check crop constraints.

	Args:
		width: Frame width.
		height: Frame height.
		crop_rect: Crop rectangle dict.
		min_area_ratio: Minimum area ratio.
		min_height_px: Minimum crop height in pixels.
		center_safe_margin: Normalized safe margin.

	Returns:
		tuple[bool, list]: (ok, reasons)
	"""
	reasons = []
	cw = int(crop_rect.get("w", 0))
	ch = int(crop_rect.get("h", 0))
	cx = int(crop_rect.get("x", 0))
	cy = int(crop_rect.get("y", 0))
	if cw <= 0 or ch <= 0:
		reasons.append("crop rectangle is empty")
		return False, reasons
	if cw > width or ch > height:
		reasons.append("crop rectangle exceeds frame bounds")
		return False, reasons
	if cx < 0 or cy < 0 or (cx + cw) > width or (cy + ch) > height:
		reasons.append("crop rectangle is out of bounds")
		return False, reasons
	area_ratio = (float(cw) * float(ch)) / (float(width) * float(height))
	if area_ratio < float(min_area_ratio):
		reasons.append("crop area below min_area_ratio")
	if ch < int(min_height_px):
		reasons.append("crop height below min_height_px")
	safe_left = float(width) * float(center_safe_margin)
	safe_top = float(height) * float(center_safe_margin)
	safe_right = float(width) - safe_left
	safe_bottom = float(height) - safe_top
	if float(cx) > safe_left or float(cy) > safe_top:
		reasons.append("crop does not include center safe region (left/top)")
	if float(cx + cw) < safe_right or float(cy + ch) < safe_bottom:
		reasons.append("crop does not include center safe region (right/bottom)")
	return len(reasons) == 0, reasons

#============================================

def crop_basic_constraints_ok(width: int, height: int, crop_rect: dict,
	min_area_ratio: float, min_height_px: int) -> tuple[bool, list]:
	"""
	Check crop constraints without enforcing a center safe region.

	Args:
		width: Frame width.
		height: Frame height.
		crop_rect: Crop rectangle dict.
		min_area_ratio: Minimum crop area ratio.
		min_height_px: Minimum crop height in pixels.

	Returns:
		tuple[bool, list]: (ok, reasons)
	"""
	reasons = []
	cw = int(crop_rect.get("w", 0))
	ch = int(crop_rect.get("h", 0))
	cx = int(crop_rect.get("x", 0))
	cy = int(crop_rect.get("y", 0))
	if cw <= 0 or ch <= 0:
		reasons.append("crop rectangle is empty")
		return False, reasons
	if cw > width or ch > height:
		reasons.append("crop rectangle exceeds frame bounds")
		return False, reasons
	if cx < 0 or cy < 0 or (cx + cw) > width or (cy + ch) > height:
		reasons.append("crop rectangle is out of bounds")
		return False, reasons
	area_ratio = (float(cw) * float(ch)) / (float(width) * float(height))
	if area_ratio < float(min_area_ratio):
		reasons.append("crop area below min_area_ratio")
	if ch < int(min_height_px):
		reasons.append("crop height below min_height_px")
	return len(reasons) == 0, reasons

#============================================

def compute_center_patch_median_color(input_file: str, width: int, height: int,
	start_seconds: float | None, duration_seconds: float | None,
	patch_fraction: float, sample_frames: int) -> dict:
	"""
	Compute a deterministic fill color from a center patch sampled over time.

	This uses ffmpeg to extract a 1x1 RGB sample of a center patch on N frames.
	The final fill color is the per-channel median over those samples.

	Args:
		input_file: Input media file.
		width: Frame width.
		height: Frame height.
		start_seconds: Optional start time for sampling.
		duration_seconds: Optional duration for sampling.
		patch_fraction: Patch fraction of width/height (0..0.5).
		sample_frames: Number of samples.

	Returns:
		dict: {"color": "#rrggbb", "samples": sample_frames}.
	"""
	start = 0.0 if start_seconds is None else float(start_seconds)
	if duration_seconds is None:
		total = probe_duration_seconds(input_file)
		duration = max(0.0, total - start)
	else:
		duration = float(duration_seconds)
	if duration <= 0:
		raise RuntimeError("invalid duration for fill color sampling")
	patch_w = max(1, int(round(float(width) * float(patch_fraction))))
	patch_h = max(1, int(round(float(height) * float(patch_fraction))))
	if patch_w > width:
		patch_w = width
	if patch_h > height:
		patch_h = height
	patch_x = int((width - patch_w) // 2)
	patch_y = int((height - patch_h) // 2)
	reds = []
	greens = []
	blues = []
	count = int(sample_frames)
	if count <= 0:
		raise RuntimeError("sample_frames must be positive")
	for i in range(count):
		t = start + ((float(i) + 0.5) * duration / float(count))
		cmd = [
			"ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
			"-ss", f"{t}",
			"-i", input_file,
			"-frames:v", "1",
			"-an", "-sn",
			"-vf", f"crop={patch_w}:{patch_h}:{patch_x}:{patch_y},scale=1:1:flags=area,format=rgb24",
			"-f", "rawvideo",
			"-",
		]
		proc = subprocess.run(cmd, capture_output=True)
		if proc.returncode != 0:
			raise RuntimeError("ffmpeg failed while sampling fill color")
		data = proc.stdout
		if len(data) < 3:
			raise RuntimeError("ffmpeg did not return RGB bytes for fill color")
		reds.append(float(data[0]))
		greens.append(float(data[1]))
		blues.append(float(data[2]))
	color = rgb_hex(int(round(median(reds))), int(round(median(greens))), int(round(median(blues))))
	return {"color": color, "samples": count, "patch_fraction": float(patch_fraction)}

#============================================

def motion_reliability_ok(width: int, height: int, transforms: list, rejection: dict) -> tuple[bool, list, dict]:
	"""
	Check minimal motion-path reliability heuristics.

	Args:
		width: Frame width.
		height: Frame height.
		transforms: Per-frame transforms list.
		rejection: Rejection settings.

	Returns:
		tuple[bool, list, dict]: (ok, reasons, stats)
	"""
	reasons = []
	non_reference = [item for item in transforms if not item.get("is_reference")]
	missing = sum(1 for item in non_reference if item.get("missing"))
	missing_fraction = float(missing) / float(len(non_reference)) if len(non_reference) > 0 else 1.0
	dx_values = [float(item["dx"]) for item in transforms if not item.get("missing")]
	dy_values = [float(item["dy"]) for item in transforms if not item.get("missing")]
	angle_values = [float(item["angle"]) for item in transforms if not item.get("missing")]
	zoom_values = [float(item["zoom_percent"]) for item in transforms if not item.get("missing")]
	if len(dx_values) == 0 or len(dy_values) == 0:
		reasons.append("unreliable_motion_missing")
		return False, reasons, {"missing_fraction": missing_fraction}
	max_abs_angle = max(abs(v) for v in angle_values) if len(angle_values) > 0 else 0.0
	max_abs_zoom_percent = max(abs(v) for v in zoom_values) if len(zoom_values) > 0 else 0.0
	mad_dx = mad(dx_values)
	mad_dy = mad(dy_values)
	mad_tx_fraction = mad_dx / float(width)
	mad_ty_fraction = mad_dy / float(height)
	if missing_fraction > float(rejection["max_missing_fraction"]):
		reasons.append("unreliable_motion_missing")
	if mad_tx_fraction > float(rejection["max_mad_fraction"]) or mad_ty_fraction > float(rejection["max_mad_fraction"]):
		reasons.append("unreliable_motion_mad")
	max_scale_jump = 0.0
	max_abs_angle_frame = None
	max_abs_zoom_frame = None
	max_scale_jump_frame = None
	max_scale_jump_pair = None
	worst_angles = []
	worst_zooms = []
	worst_scale_jumps = []
	usable_indices = [idx for idx, item in enumerate(transforms) if not item.get("missing") and not item.get("is_reference")]
	for idx, item in enumerate(transforms):
		if item.get("missing") or item.get("is_reference"):
			continue
		worst_angles.append((idx, abs(float(item["angle"]))))
		worst_zooms.append((idx, abs(float(item["zoom_percent"]))))
	if len(worst_angles) > 0:
		worst_angles_sorted = sorted(worst_angles, key=lambda t: t[1], reverse=True)
		max_abs_angle_frame = worst_angles_sorted[0][0]
	if len(worst_zooms) > 0:
		worst_zooms_sorted = sorted(worst_zooms, key=lambda t: t[1], reverse=True)
		max_abs_zoom_frame = worst_zooms_sorted[0][0]
	for i in range(len(usable_indices) - 1):
		idx0 = usable_indices[i]
		idx1 = usable_indices[i + 1]
		s0 = scale_ratio_from_zoom_percent(float(transforms[idx0]["zoom_percent"]))
		s1 = scale_ratio_from_zoom_percent(float(transforms[idx1]["zoom_percent"]))
		if s0 <= 0:
			continue
		jump = abs((s1 / s0) - 1.0)
		worst_scale_jumps.append((idx1, jump, idx0, idx1))
		if jump > max_scale_jump:
			max_scale_jump = jump
			max_scale_jump_frame = idx1
			max_scale_jump_pair = (idx0, idx1)

	def _budget_stats(bad_set: set[int]) -> dict:
		bad_count = 0
		max_run = 0
		run = 0
		for idx in usable_indices:
			is_bad = idx in bad_set
			if is_bad:
				bad_count += 1
				run += 1
				if run > max_run:
					max_run = run
			else:
				run = 0
		total_frames = len(usable_indices)
		ratio = float(bad_count) / float(total_frames) if total_frames > 0 else 1.0
		return {
			"bad_frames": bad_count,
			"total_frames": total_frames,
			"bad_frames_ratio": ratio,
			"max_consecutive_bad_frames": max_run,
		}

	threshold_angle = float(rejection["max_abs_angle_rad"])
	threshold_zoom = float(rejection["max_abs_zoom_percent"])
	threshold_scale_jump = float(rejection["max_scale_jump"])
	angle_bad = {idx for idx, value in worst_angles if value > threshold_angle}
	zoom_bad = {idx for idx, value in worst_zooms if value > threshold_zoom}
	scale_bad = {item[0] for item in worst_scale_jumps if item[1] > threshold_scale_jump}
	angle_budget = _budget_stats(angle_bad)
	zoom_budget = _budget_stats(zoom_bad)
	scale_budget = _budget_stats(scale_bad)
	combined_bad = angle_bad | zoom_bad | scale_bad
	combined_budget = _budget_stats(combined_bad)

	mode = rejection.get("mode", "budgeted")
	outlier_max_frames_ratio = float(rejection.get("outlier_max_frames_ratio", 0.0))
	outlier_max_consecutive = int(rejection.get("outlier_max_consecutive_frames", 0))
	if mode == "max":
		if max_abs_angle > threshold_angle:
			reasons.append("unreliable_motion_angle")
		if max_abs_zoom_percent > threshold_zoom:
			reasons.append("unreliable_motion_zoom")
		if max_scale_jump > threshold_scale_jump:
			reasons.append("unreliable_motion_scale")
	else:
		if angle_budget["bad_frames_ratio"] > outlier_max_frames_ratio or angle_budget["max_consecutive_bad_frames"] > outlier_max_consecutive:
			reasons.append("unreliable_motion_angle")
		if zoom_budget["bad_frames_ratio"] > outlier_max_frames_ratio or zoom_budget["max_consecutive_bad_frames"] > outlier_max_consecutive:
			reasons.append("unreliable_motion_zoom")
		if scale_budget["bad_frames_ratio"] > outlier_max_frames_ratio or scale_budget["max_consecutive_bad_frames"] > outlier_max_consecutive:
			reasons.append("unreliable_motion_scale")

	stats = {
		"missing_fraction": missing_fraction,
		"mad_tx_fraction": mad_tx_fraction,
		"mad_ty_fraction": mad_ty_fraction,
		"max_scale_jump": max_scale_jump,
		"max_abs_angle_rad": max_abs_angle,
		"max_abs_zoom_percent": max_abs_zoom_percent,
		"max_abs_angle_frame": max_abs_angle_frame,
		"max_abs_zoom_percent_frame": max_abs_zoom_frame,
		"max_scale_jump_frame": max_scale_jump_frame,
		"max_scale_jump_pair": max_scale_jump_pair,
		"top_5_abs_angle": [
			{"frame": idx, "abs_angle_rad": value}
			for idx, value in sorted(worst_angles, key=lambda t: t[1], reverse=True)[:5]
		],
		"top_5_abs_zoom_percent": [
			{"frame": idx, "abs_zoom_percent": value}
			for idx, value in sorted(worst_zooms, key=lambda t: t[1], reverse=True)[:5]
		],
		"top_5_scale_jumps": [
			{"frame": item[0], "scale_jump": item[1], "pair": [item[2], item[3]]}
			for item in sorted(worst_scale_jumps, key=lambda t: t[1], reverse=True)[:5]
		],
		"rejection_mode": mode,
		"angle_outliers": angle_budget,
		"zoom_outliers": zoom_budget,
		"scale_jump_outliers": scale_budget,
		"combined_outliers": combined_budget,
	}
	return len(reasons) == 0, reasons, stats

#============================================

def print_unreliable_motion_summary(stats: dict, thresholds: dict, reasons: list,
	fps: float, start_seconds: float | None) -> None:
	"""
	Print a one-screen summary of the motion rejection metrics.

	Args:
		stats: Computed stats mapping.
		thresholds: Thresholds mapping.
		reasons: Rejection reason codes.
	"""
	print("FAIL unreliable motion", file=sys.stderr)
	print(f"reasons={reasons}", file=sys.stderr)
	print(
		f"missing_fraction={stats.get('missing_fraction')} (max {thresholds.get('max_missing_fraction')})",
		file=sys.stderr,
	)
	print(
		f"mad_tx/width={stats.get('mad_tx_fraction')} mad_ty/height={stats.get('mad_ty_fraction')} "
		f"(max {thresholds.get('max_mad_fraction')})",
		file=sys.stderr,
	)
	print(
		f"max_scale_jump={stats.get('max_scale_jump')} (max {thresholds.get('max_scale_jump')})",
		file=sys.stderr,
	)
	print(
		f"max_abs_angle_rad={stats.get('max_abs_angle_rad')} (max {thresholds.get('max_abs_angle_rad')})",
		file=sys.stderr,
	)
	print(
		f"max_abs_zoom_percent={stats.get('max_abs_zoom_percent')} (max {thresholds.get('max_abs_zoom_percent')})",
		file=sys.stderr,
	)
	mode = thresholds.get("mode")
	if mode == "budgeted":
		max_ratio = thresholds.get("outlier_max_frames_ratio")
		max_run = thresholds.get("outlier_max_consecutive_frames")
		angle = stats.get("angle_outliers", {})
		zoom = stats.get("zoom_outliers", {})
		scale = stats.get("scale_jump_outliers", {})
		combined = stats.get("combined_outliers", {})
		print(
			f"outlier_budget: max_frames_ratio={max_ratio} max_consecutive_frames={max_run}",
			file=sys.stderr,
		)
		print(
			f"angle_outliers: ratio={angle.get('bad_frames_ratio')} run={angle.get('max_consecutive_bad_frames')}",
			file=sys.stderr,
		)
		print(
			f"zoom_outliers: ratio={zoom.get('bad_frames_ratio')} run={zoom.get('max_consecutive_bad_frames')}",
			file=sys.stderr,
		)
		print(
			f"scale_outliers: ratio={scale.get('bad_frames_ratio')} run={scale.get('max_consecutive_bad_frames')}",
			file=sys.stderr,
		)
		print(
			f"any_outliers: ratio={combined.get('bad_frames_ratio')} run={combined.get('max_consecutive_bad_frames')}",
			file=sys.stderr,
		)
	angle_frame = stats.get("max_abs_angle_frame")
	zoom_frame = stats.get("max_abs_zoom_percent_frame")
	scale_frame = stats.get("max_scale_jump_frame")
	if angle_frame is not None:
		seconds = float(angle_frame) / float(fps) + (float(start_seconds) if start_seconds is not None else 0.0)
		print(f"max_abs_angle_frame={angle_frame} (t={seconds:.3f}s)", file=sys.stderr)
	if zoom_frame is not None:
		seconds = float(zoom_frame) / float(fps) + (float(start_seconds) if start_seconds is not None else 0.0)
		print(f"max_abs_zoom_frame={zoom_frame} (t={seconds:.3f}s)", file=sys.stderr)
	if scale_frame is not None:
		seconds = float(scale_frame) / float(fps) + (float(start_seconds) if start_seconds is not None else 0.0)
		print(f"max_scale_jump_frame={scale_frame} (t={seconds:.3f}s)", file=sys.stderr)
	return

#============================================

def write_report(report_path: str, report: dict, report_format: str) -> None:
	"""
	Write a report sidecar file.

	Args:
		report_path: Report path.
		report: Report mapping.
		report_format: "yaml" or "json".
	"""
	os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
	if report_format == "json":
		text = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
	else:
		text = yaml.safe_dump(report, sort_keys=True)
	with open(report_path, "w", encoding="utf-8") as handle:
		handle.write(text)
	return

#============================================

def render_stabilized_output(input_file: str, output_file: str, trf_path: str,
	transform: dict, crop_rect: dict, output_width: int, output_height: int,
	audio_stream: dict | None, copy_subs: bool, start_seconds: float | None,
	duration_seconds: float | None) -> None:
	"""
	Render stabilized output using vidstabtransform + crop + scale.

	Args:
		input_file: Input media file.
		output_file: Output media file.
		trf_path: Transforms file path.
		transform: Transform settings mapping.
		crop_rect: Crop rectangle dict.
		audio_stream: Selected audio stream mapping to copy, or None.
		copy_subs: Copy subtitle streams.
		start_seconds: Optional start seconds.
		duration_seconds: Optional duration seconds.
	"""
	cx = int(crop_rect["x"])
	cy = int(crop_rect["y"])
	cw = int(crop_rect["w"])
	ch = int(crop_rect["h"])
	cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
	if start_seconds is not None:
		cmd += ["-ss", f"{start_seconds}"]
	if duration_seconds is not None:
		cmd += ["-t", f"{duration_seconds}"]
	cmd += ["-i", input_file]
	cmd += ["-map", "0:v:0"]
	if audio_stream is not None:
		audio_index = int(audio_stream.get("index", -1))
		if audio_index >= 0:
			cmd += ["-map", f"0:{audio_index}"]
	if copy_subs:
		cmd += ["-map", "0:s?"]
	cmd += ["-map_metadata", "0"]
	input_path = escape_ffmpeg_filter_value(trf_path)
	filter_text = (
		"vidstabtransform="
		f"input={input_path}:"
		"relative=1:"
		"optzoom=0:"
		"zoom=0:"
		"crop=black:"
		f"optalgo={transform['optalgo']}:"
		f"smoothing={transform['smoothing']}"
		f",crop=w={cw}:h={ch}:x={cx}:y={cy}"
		f",scale={int(output_width)}:{int(output_height)}"
	)
	cmd += ["-vf", filter_text]
	cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
	if audio_stream is not None:
		cmd += ["-c:a", "copy"]
	if copy_subs:
		cmd += ["-c:s", "copy"]
	cmd.append(output_file)
	run_process(cmd, capture_output=True)
	if not os.path.isfile(output_file):
		raise RuntimeError("output render failed")
	return

#============================================

def render_stabilized_output_with_fill(input_file: str, output_file: str, trf_path: str,
	transform: dict, crop_rect: dict, output_width: int, output_height: int, fps: float,
	fill_color: str, fill_band_px: int, audio_stream: dict | None, copy_subs: bool,
	start_seconds: float | None, duration_seconds: float | None) -> None:
	"""
	Render stabilized output with a constant border fill color.

	This is only used in the border-fill fallback mode when crop-only is infeasible.

	Args:
		input_file: Input media file.
		output_file: Output media file.
		trf_path: Transforms file path.
		transform: Transform settings mapping.
		crop_rect: Fixed crop rectangle in source pixels.
		output_width: Output width.
		output_height: Output height.
		fps: Output fps for the fill source.
		fill_color: Fill color "#rrggbb".
		fill_band_px: Border band width in output pixels.
		audio_stream: Selected audio stream mapping to copy, or None.
		copy_subs: Copy subtitle streams.
		start_seconds: Optional start seconds.
		duration_seconds: Optional duration seconds.
	"""
	band = int(fill_band_px)
	if band < 1:
		raise RuntimeError("fill_band_px must be >= 1")
	if band * 2 >= int(output_width) or band * 2 >= int(output_height):
		raise RuntimeError("fill_band_px too large for output resolution")
	cx = int(crop_rect["x"])
	cy = int(crop_rect["y"])
	cw = int(crop_rect["w"])
	ch = int(crop_rect["h"])
	if cw <= 0 or ch <= 0:
		raise RuntimeError("invalid crop rectangle for fill mode")
	input_path = escape_ffmpeg_filter_value(trf_path)
	cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
	if start_seconds is not None:
		cmd += ["-ss", f"{start_seconds}"]
	if duration_seconds is not None:
		cmd += ["-t", f"{duration_seconds}"]
	cmd += ["-i", input_file]
	cmd += ["-f", "lavfi", "-i", f"color=c={fill_color}:size={int(output_width)}x{int(output_height)}:rate={fps}"]
	if audio_stream is not None:
		audio_index = int(audio_stream.get("index", -1))
		if audio_index >= 0:
			cmd += ["-map", f"0:{audio_index}"]
	if copy_subs:
		cmd += ["-map", "0:s?"]
	cmd += ["-map_metadata", "0"]
	center_w = int(output_width) - 2 * band
	center_h = int(output_height) - 2 * band
	filter_text = (
		f"[0:v]vidstabtransform=input={input_path}:relative=1:optzoom=0:zoom=0:crop=black:"
		f"optalgo={transform['optalgo']}:smoothing={transform['smoothing']},"
		f"crop=w={cw}:h={ch}:x={cx}:y={cy},"
		f"scale={int(output_width)}:{int(output_height)},format=rgba,split=5[v0][v1][v2][v3][v4];"
		f"[v0]crop=w={center_w}:h={center_h}:x={band}:y={band}[center];"
		f"[v1]crop=w={int(output_width)}:h={band}:x=0:y=0,colorkey=black:0.00001:0[top];"
		f"[v2]crop=w={int(output_width)}:h={band}:x=0:y={int(output_height) - band},colorkey=black:0.00001:0[bottom];"
		f"[v3]crop=w={band}:h={int(output_height)}:x=0:y=0,colorkey=black:0.00001:0[left];"
		f"[v4]crop=w={band}:h={int(output_height)}:x={int(output_width) - band}:y=0,colorkey=black:0.00001:0[right];"
		f"[1:v]format=rgba[base];"
		f"[base][left]overlay=0:0:shortest=1[t1];"
		f"[t1][right]overlay={int(output_width) - band}:0:shortest=1[t2];"
		f"[t2][top]overlay=0:0:shortest=1[t3];"
		f"[t3][bottom]overlay=0:{int(output_height) - band}:shortest=1[t4];"
		f"[t4][center]overlay={band}:{band}:shortest=1[vout]"
	)
	cmd += ["-filter_complex", filter_text]
	cmd += ["-map", "[vout]"]
	cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p"]
	if audio_stream is not None:
		cmd += ["-c:a", "copy"]
	if copy_subs:
		cmd += ["-c:s", "copy"]
	cmd.append(output_file)
	run_process(cmd, capture_output=True)
	if not os.path.isfile(output_file):
		raise RuntimeError("output render failed")
	return

#============================================

def main() -> None:
	"""
	Main entry point.
	"""
	args = parse_args()
	ensure_file_exists(args.input_file)
	check_dependency("ffmpeg")
	check_dependency("ffprobe")
	check_vidstab_filters()
	if args.config_file is not None and args.use_default_config:
		raise RuntimeError("use -c/--config or --use-default-config, not both")
	if args.config_file is not None and args.write_default_config:
		raise RuntimeError("use -c/--config or --write-default-config, not both")
	if args.use_default_config and args.write_default_config:
		raise RuntimeError("use --use-default-config or --write-default-config, not both")
	if args.write_default_config:
		config_path = default_config_path(args.input_file)
		if os.path.exists(config_path):
			raise RuntimeError(f"default config already exists: {config_path}")
		write_config_file(config_path, default_config())
		print(f"Wrote default config: {config_path}")
		return
	if args.output_file is None or str(args.output_file).strip() == "":
		raise RuntimeError("missing required -o/--output")
	start_seconds = parse_time_seconds(args.start)
	duration_seconds = parse_time_seconds(args.duration)
	end_seconds = parse_time_seconds(args.end)
	if duration_seconds is not None and end_seconds is not None:
		raise RuntimeError("use --duration or --end, not both")
	if end_seconds is not None and start_seconds is None:
		raise RuntimeError("--end requires --start")
	if start_seconds is not None and start_seconds < 0:
		raise RuntimeError("--start must be >= 0")
	if duration_seconds is not None and duration_seconds <= 0:
		raise RuntimeError("--duration must be > 0")
	if end_seconds is not None and end_seconds <= 0:
		raise RuntimeError("--end must be > 0")
	if end_seconds is not None and start_seconds is not None:
		duration_seconds = float(end_seconds) - float(start_seconds)
		if duration_seconds <= 0:
			raise RuntimeError("--end must be > --start")
	config_path_file = None
	config_path_for_errors = "<code defaults>"
	config_source = "code_defaults"
	config = default_config()
	if args.use_default_config:
		config_path_file = default_config_path(args.input_file)
		if not os.path.exists(config_path_file):
			raise RuntimeError(f"default config not found: {config_path_file}")
		config = load_config(config_path_file)
		config_path_for_errors = config_path_file
		config_source = "default_config"
	elif args.config_file is not None:
		config_path_file = args.config_file
		config_path_for_errors = config_path_file
		if os.path.exists(config_path_file):
			config = load_config(config_path_file)
			config_source = "explicit_config"
		else:
			write_config_file(config_path_file, default_config())
			print(f"Wrote default config: {config_path_file}")
			config = load_config(config_path_file)
			config_source = "explicit_config_written"
	settings = build_settings(config, config_path_for_errors, args.input_file)
	video = probe_video_stream(args.input_file)
	width = int(video["width"])
	height = int(video["height"])
	fps = float(video["fps"])
	min_height_px_setting = int(settings["crop"]["min_height_px"])
	min_height_ratio_setting = float(settings["crop"]["min_height_ratio"])
	effective_min_height_px = min_height_px_setting
	if effective_min_height_px <= 0:
		effective_min_height_px = int(round(float(height) * min_height_ratio_setting))
	if effective_min_height_px <= 0:
		raise RuntimeError("effective min height must be positive")
	cache_dir_raw = settings["io"]["cache_dir"]
	cache_dir = os.path.abspath(cache_dir_raw)
	os.makedirs(cache_dir, exist_ok=True)
	toolchain = ffmpeg_version_fingerprint()
	identity = file_identity(args.input_file)
	analysis_key = stable_hash_mapping({
		"input": identity,
		"range": {"start": start_seconds, "duration": duration_seconds},
		"video": {"width": width, "height": height, "fps_fraction": video["fps_fraction"]},
		"detect": settings["engine"]["detect"],
		"toolchain": toolchain,
	})
	run_key = stable_hash_mapping({
		"analysis_key": analysis_key,
		"transform": settings["engine"]["transform"],
		"crop": settings["crop"],
		"border": settings["border"],
		"rejection": settings["rejection"],
		"toolchain": toolchain,
	})
	trf_path = os.path.join(cache_dir, f"{analysis_key}.transforms.trf")
	report_path = f"{args.output_file}.stabilize_building.report.{settings['io']['report_format']}"
	config_path_abs = None
	if config_path_file is not None:
		config_path_abs = os.path.abspath(config_path_file)
	report = {
		"stabilize_building": 1,
		"config_path": config_path_abs,
		"config_source": config_source,
		"input": identity,
		"output": os.path.abspath(args.output_file),
		"range": {"start": start_seconds, "duration": duration_seconds},
		"settings": settings,
		"toolchain": toolchain,
		"cache_dir_abs": cache_dir,
		"analysis_key": analysis_key,
		"run_key": run_key,
		"result": {"pass": False, "mode": None, "message": None},
		"motion": {},
		"crop": {},
		"border": {},
		"streams": {},
		"warnings": [],
	}
	audio_stream = None
	if args.copy_audio:
		streams = probe_all_streams(args.input_file)
		audio_stream = select_audio_stream_for_copy(streams)
		if audio_stream is None:
			report["warnings"].append("no usable audio stream found; output will be video-only")
		if audio_stream is not None:
			disposition = audio_stream.get("disposition", {})
			default_value = 0
			if isinstance(disposition, dict):
				default_value = int(disposition.get("default", 0))
			report["streams"]["audio_selected"] = {
				"index": int(audio_stream.get("index", -1)),
				"codec_name": audio_stream.get("codec_name"),
				"codec_tag_string": audio_stream.get("codec_tag_string"),
				"channels": audio_stream.get("channels"),
				"sample_rate": audio_stream.get("sample_rate"),
				"default": default_value,
			}
	report["crop"]["effective_min_height_px"] = effective_min_height_px
	if not os.path.isfile(trf_path):
		print("Running vidstabdetect (pass 1/2): motion analysis")
		temp_trf = os.path.join(cache_dir, f"{analysis_key}.tmp.trf")
		if os.path.isfile(temp_trf):
			os.remove(temp_trf)
		run_vidstabdetect(
			args.input_file,
			temp_trf,
			settings["engine"]["detect"],
			start_seconds,
			duration_seconds,
		)
		os.replace(temp_trf, trf_path)
	else:
		print("Cache hit: reusing motion analysis transforms")
	frame_count = count_frames_in_trf(trf_path)
	if frame_count <= 1:
		raise RuntimeError("insufficient frames for stabilization")
	print("Computing crop feasibility from motion path")
	global_dir = None
	if args.keep_temp:
		global_dir = os.path.join(cache_dir, f"{run_key}.global_motions")
	global_text, debug_meta, global_path = run_global_motions_from_trf(
		trf_path, width, height, fps, frame_count, settings["engine"]["transform"], output_dir=global_dir
	)
	if args.keep_temp:
		report["motion"]["global_motions_path"] = global_path
	report["motion"]["global_motions_driver"] = {
		"width": width,
		"height": height,
		"fps": fps,
		"frame_count": frame_count,
	}
	transforms = parse_global_motions_text(global_text)
	report["motion"]["frame_count"] = len(transforms)
	report["motion"]["debug_meta"] = debug_meta
	ok_motion, motion_reasons, motion_stats = motion_reliability_ok(
		width, height, transforms, settings["rejection"]
	)
	motion_thresholds = {
		"mode": settings["rejection"]["mode"],
		"max_missing_fraction": settings["rejection"]["max_missing_fraction"],
		"max_mad_fraction": settings["rejection"]["max_mad_fraction"],
		"max_scale_jump": settings["rejection"]["max_scale_jump"],
		"max_abs_angle_rad": settings["rejection"]["max_abs_angle_rad"],
		"max_abs_zoom_percent": settings["rejection"]["max_abs_zoom_percent"],
		"outlier_max_frames_ratio": settings["rejection"]["outlier_max_frames_ratio"],
		"outlier_max_consecutive_frames": settings["rejection"]["outlier_max_consecutive_frames"],
	}
	report["motion"]["stats"] = motion_stats
	report["motion"]["thresholds"] = motion_thresholds
	report["motion"]["rejection"] = {
		"pass": bool(ok_motion),
		"reasons": motion_reasons,
	}
	if not ok_motion:
		failure_code = "unreliable_motion_multiple"
		if len(motion_reasons) == 1:
			failure_code = motion_reasons[0]
		combined = motion_stats.get("combined_outliers", {})
		required = {
			"max_abs_angle_rad": motion_stats.get("max_abs_angle_rad"),
			"max_abs_zoom_percent": motion_stats.get("max_abs_zoom_percent"),
			"max_scale_jump": motion_stats.get("max_scale_jump"),
			"outlier_frames_ratio": combined.get("bad_frames_ratio"),
			"outlier_max_consecutive_frames": combined.get("max_consecutive_bad_frames"),
		}
		report["motion"]["required_thresholds_to_pass"] = required
		report["result"]["pass"] = False
		report["result"]["mode"] = "motion_rejection"
		report["result"]["message"] = failure_code
		write_report(report_path, report, settings["io"]["report_format"])
		print_unreliable_motion_summary(motion_stats, motion_thresholds, motion_reasons, fps, start_seconds)
		raise RuntimeError(failure_code)
	crop_rect = compute_static_crop(width, height, transforms)
	report["crop"]["crop_to_content_rect"] = crop_rect
	if crop_rect["w"] > 0 and crop_rect["h"] > 0:
		report["crop"]["crop_to_content_area_ratio"] = (
			(float(crop_rect["w"]) * float(crop_rect["h"])) / (float(width) * float(height))
		)
		report["crop"]["crop_to_content_zoom_factor"] = float(width) / float(crop_rect["w"])
	ok_crop, crop_reasons = crop_constraints_ok(
		width, height, crop_rect,
		settings["crop"]["min_area_ratio"],
		effective_min_height_px,
		settings["crop"]["center_safe_margin"],
	)
	if not ok_crop:
		border_mode = settings["border"]["mode"]
		report["crop"]["crop_to_content_reasons"] = crop_reasons
		report["border"]["mode"] = border_mode
		if border_mode != "crop_prefer_fill_fallback":
			report["result"]["pass"] = False
			report["result"]["mode"] = "crop_only"
			report["result"]["message"] = "crop infeasible"
			write_report(report_path, report, settings["io"]["report_format"])
			raise RuntimeError("global stabilization unsuitable for this material (crop infeasible)")
		fill = settings["border"]["fill"]
		fill_crop_rect = crop_rect
		ok_fill_crop, fill_crop_reasons = crop_basic_constraints_ok(
			width,
			height,
			fill_crop_rect,
			settings["crop"]["min_area_ratio"],
			effective_min_height_px,
		)
		if not ok_fill_crop:
			fill_crop_rect = compute_minimum_centered_crop(
				width,
				height,
				settings["crop"]["min_area_ratio"],
				effective_min_height_px,
			)
			ok_fill_crop, fill_crop_reasons = crop_basic_constraints_ok(
				width,
				height,
				fill_crop_rect,
				settings["crop"]["min_area_ratio"],
				effective_min_height_px,
			)
		report["crop"]["fill_crop_rect"] = fill_crop_rect
		if not ok_fill_crop:
			report["result"]["pass"] = False
			report["result"]["mode"] = "fill_fallback"
			report["result"]["message"] = "fill crop infeasible"
			report["crop"]["fill_crop_reasons"] = fill_crop_reasons
			write_report(report_path, report, settings["io"]["report_format"])
			raise RuntimeError("global stabilization unsuitable for this material (fill crop infeasible)")
		fill_stats = compute_fill_budget(
			transforms,
			width,
			height,
			fill_crop_rect,
			fill["max_area_ratio"],
			fill["max_frames_ratio"],
			fill["max_consecutive_frames"],
		)
		report["border"]["fill_budget"] = fill_stats
		zoom_factor = float(width) / float(fill_crop_rect["w"]) if fill_crop_rect["w"] > 0 else 1.0
		max_gap_out = float(fill_stats.get("max_gap_px", 0.0)) * zoom_factor
		fill_band_px = int(math.ceil(max_gap_out)) + 2
		report["border"]["fill_band_px"] = fill_band_px
		safe_margin_px = float(min(width, height)) * float(settings["crop"]["center_safe_margin"])
		report["border"]["safe_margin_px"] = safe_margin_px
		if float(fill_band_px) > safe_margin_px:
			report["warnings"].append("fill band exceeds center_safe_margin; fill may reach into the safe region")
		if not bool(fill_stats.get("pass")):
			report["result"]["pass"] = False
			report["result"]["mode"] = "fill_fallback"
			report["result"]["message"] = "fill budget exceeded"
			write_report(report_path, report, settings["io"]["report_format"])
			raise RuntimeError("global stabilization unsuitable for this material (fill budget exceeded)")
		fill_color_info = compute_center_patch_median_color(
			args.input_file,
			width,
			height,
			start_seconds,
			duration_seconds,
			fill["patch_fraction"],
			fill["sample_frames"],
		)
		report["border"]["fill_color"] = fill_color_info
		report["crop"]["rect"] = fill_crop_rect
		if args.copy_subs:
			report["warnings"].append("subtitles copied unchanged; crop may remove visible subtitle regions")
		print("Running vidstabtransform (pass 2/2): stabilize + crop + fill + encode")
		render_stabilized_output_with_fill(
			args.input_file,
			args.output_file,
			trf_path,
			settings["engine"]["transform"],
			fill_crop_rect,
			width,
			height,
			fps,
			fill_color_info["color"],
			fill_band_px,
			audio_stream,
			args.copy_subs,
			start_seconds,
			duration_seconds,
		)
		report["result"]["pass"] = True
		report["result"]["mode"] = "fill_fallback"
		report["result"]["message"] = "ok"
		write_report(report_path, report, settings["io"]["report_format"])
		return
	if args.copy_subs:
		report["warnings"].append("subtitles copied unchanged; crop may remove visible subtitle regions")
	print("Running vidstabtransform (pass 2/2): stabilize + crop + encode")
	report["border"]["mode"] = settings["border"]["mode"]
	report["crop"]["rect"] = crop_rect
	render_stabilized_output(
		args.input_file,
		args.output_file,
		trf_path,
		settings["engine"]["transform"],
		crop_rect,
		width,
		height,
		audio_stream,
		args.copy_subs,
		start_seconds,
		duration_seconds,
	)
	report["result"]["pass"] = True
	report["result"]["mode"] = "crop_only"
	report["result"]["message"] = "ok"
	write_report(report_path, report, settings["io"]["report_format"])
	return

#============================================

if __name__ == "__main__":
	main()
