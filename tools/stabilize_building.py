#!/usr/bin/env python3

"""
stabilize_building.py

Global "bird on a building" stabilization as a standalone media-prep tool.

This tool is intentionally strict:
- It performs global alignment so the reference frame (building) is static.
- It enforces crop-only framing (single static crop for the entire output).
- It fails if a stable crop is infeasible or constraints are violated.
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
		description="Stabilize 'bird on a building' footage (global align + crop-only)."
	)
	parser.add_argument(
		"-i", "--input", dest="input_file", required=True,
		help="Input media file path."
	)
	parser.add_argument(
		"-o", "--output", dest="output_file", required=True,
		help="Output stabilized media file path."
	)
	parser.add_argument(
		"-c", "--config", dest="config_file", default=None,
		help="Config YAML path (default: <input>.stabilize_building.config.yaml)."
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
				"min_height_px": 480,
				"center_safe_margin": 0.10,
			},
			"rejection": {
				"max_missing_fraction": 0.05,
				"max_mad_fraction": 0.50,
				"max_scale_jump": 0.15,
				"max_abs_angle_rad": 0.02,
				"max_abs_zoom_percent": 2.0,
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
	lines.append(f"    min_height_px: {crop.get('min_height_px', 480)}")
	lines.append(f"    center_safe_margin: {crop.get('center_safe_margin', 0.10)}")
	lines.append("  rejection:")
	lines.append(f"    max_missing_fraction: {rejection.get('max_missing_fraction', 0.05)}")
	lines.append(f"    max_mad_fraction: {rejection.get('max_mad_fraction', 0.50)}")
	lines.append(f"    max_scale_jump: {rejection.get('max_scale_jump', 0.15)}")
	lines.append(f"    max_abs_angle_rad: {rejection.get('max_abs_angle_rad', 0.02)}")
	lines.append(f"    max_abs_zoom_percent: {rejection.get('max_abs_zoom_percent', 2.0)}")
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
	center_safe_margin = coerce_float(crop.get("center_safe_margin", settings["crop"]["center_safe_margin"]),
		config_path, "settings.crop.center_safe_margin")
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
	if min_height_px <= 0:
		raise RuntimeError("min_height_px must be positive")
	if center_safe_margin < 0 or center_safe_margin >= 0.5:
		raise RuntimeError("center_safe_margin must be >= 0 and < 0.5")
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
			"center_safe_margin": center_safe_margin,
		},
		"rejection": {
			"max_missing_fraction": max_missing_fraction,
			"max_mad_fraction": max_mad_fraction,
			"max_scale_jump": max_scale_jump,
			"max_abs_angle_rad": max_abs_angle_rad,
			"max_abs_zoom_percent": max_abs_zoom_percent,
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
		"relative=0:"
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
	total = len(transforms)
	non_reference = [item for item in transforms if not item.get("is_reference")]
	missing = sum(1 for item in non_reference if item.get("missing"))
	missing_fraction = float(missing) / float(len(non_reference)) if len(non_reference) > 0 else 1.0
	dx_values = [float(item["dx"]) for item in transforms if not item.get("missing")]
	dy_values = [float(item["dy"]) for item in transforms if not item.get("missing")]
	angle_values = [float(item["angle"]) for item in transforms if not item.get("missing")]
	zoom_values = [float(item["zoom_percent"]) for item in transforms if not item.get("missing")]
	if len(dx_values) == 0 or len(dy_values) == 0:
		reasons.append("no usable transforms")
		return False, reasons, {"missing_fraction": missing_fraction}
	max_abs_angle = max(abs(v) for v in angle_values) if len(angle_values) > 0 else 0.0
	max_abs_zoom_percent = max(abs(v) for v in zoom_values) if len(zoom_values) > 0 else 0.0
	mad_dx = mad(dx_values)
	mad_dy = mad(dy_values)
	mad_dx_fraction = mad_dx / float(width)
	mad_dy_fraction = mad_dy / float(height)
	if missing_fraction > float(rejection["max_missing_fraction"]):
		reasons.append("missing transforms fraction too high")
	if mad_dx_fraction > float(rejection["max_mad_fraction"]) or mad_dy_fraction > float(rejection["max_mad_fraction"]):
		reasons.append("motion path is inconsistent (MAD too large)")
	if max_abs_angle > float(rejection["max_abs_angle_rad"]):
		reasons.append("rotation unsupported (max_abs_angle_rad exceeded)")
	if max_abs_zoom_percent > float(rejection["max_abs_zoom_percent"]):
		reasons.append("zoom unsupported (max_abs_zoom_percent exceeded)")
	max_scale_jump = 0.0
	for i in range(len(zoom_values) - 1):
		s0 = scale_ratio_from_zoom_percent(zoom_values[i])
		s1 = scale_ratio_from_zoom_percent(zoom_values[i + 1])
		if s0 <= 0:
			continue
		jump = abs((s1 / s0) - 1.0)
		if jump > max_scale_jump:
			max_scale_jump = jump
	if max_scale_jump > float(rejection["max_scale_jump"]):
		reasons.append("scale continuity suggests zoom (max_scale_jump exceeded)")
	stats = {
		"missing_fraction": missing_fraction,
		"mad_dx": mad_dx,
		"mad_dy": mad_dy,
		"mad_dx_fraction": mad_dx_fraction,
		"mad_dy_fraction": mad_dy_fraction,
		"max_abs_angle": max_abs_angle,
		"max_abs_zoom_percent": max_abs_zoom_percent,
		"max_scale_jump": max_scale_jump,
	}
	return len(reasons) == 0, reasons, stats

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
	copy_audio: bool, copy_subs: bool, start_seconds: float | None,
	duration_seconds: float | None) -> None:
	"""
	Render stabilized output using vidstabtransform + crop + scale.

	Args:
		input_file: Input media file.
		output_file: Output media file.
		trf_path: Transforms file path.
		transform: Transform settings mapping.
		crop_rect: Crop rectangle dict.
		copy_audio: Copy audio streams.
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
	if copy_audio:
		cmd += ["-map", "0:a?"]
	if copy_subs:
		cmd += ["-map", "0:s?"]
	cmd += ["-map_metadata", "0"]
	input_path = escape_ffmpeg_filter_value(trf_path)
	filter_text = (
		"vidstabtransform="
		f"input={input_path}:"
		"relative=0:"
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
	if copy_audio:
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
	config_path = args.config_file
	if config_path is None:
		config_path = default_config_path(args.input_file)
	if not os.path.exists(config_path):
		write_config_file(config_path, default_config())
		print(f"Wrote default config: {config_path}")
	config = load_config(config_path)
	settings = build_settings(config, config_path, args.input_file)
	video = probe_video_stream(args.input_file)
	width = int(video["width"])
	height = int(video["height"])
	fps = float(video["fps"])
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
		"rejection": settings["rejection"],
		"toolchain": toolchain,
	})
	trf_path = os.path.join(cache_dir, f"{analysis_key}.transforms.trf")
	report_path = f"{args.output_file}.stabilize_building.report.{settings['io']['report_format']}"
	report = {
		"stabilize_building": 1,
		"input": identity,
		"output": os.path.abspath(args.output_file),
		"range": {"start": start_seconds, "duration": duration_seconds},
		"settings": settings,
		"toolchain": toolchain,
		"cache_dir_abs": cache_dir,
		"analysis_key": analysis_key,
		"run_key": run_key,
		"result": {"pass": False, "message": None},
		"motion": {},
		"crop": {},
		"warnings": [],
	}
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
	transforms = parse_global_motions_text(global_text)
	report["motion"]["frame_count"] = len(transforms)
	report["motion"]["debug_meta"] = debug_meta
	ok_motion, motion_reasons, motion_stats = motion_reliability_ok(
		width, height, transforms, settings["rejection"]
	)
	report["motion"]["stats"] = motion_stats
	if not ok_motion:
		report["result"]["pass"] = False
		report["result"]["message"] = "unreliable motion estimation"
		report["motion"]["reasons"] = motion_reasons
		write_report(report_path, report, settings["io"]["report_format"])
		raise RuntimeError("global stabilization unsuitable for this material (unreliable motion)")
	crop_rect = compute_static_crop(width, height, transforms)
	report["crop"]["rect"] = crop_rect
	if crop_rect["w"] > 0 and crop_rect["h"] > 0:
		report["crop"]["area_ratio"] = (float(crop_rect["w"]) * float(crop_rect["h"])) / (float(width) * float(height))
		report["crop"]["zoom_factor"] = float(width) / float(crop_rect["w"])
	ok_crop, crop_reasons = crop_constraints_ok(
		width, height, crop_rect,
		settings["crop"]["min_area_ratio"],
		settings["crop"]["min_height_px"],
		settings["crop"]["center_safe_margin"],
	)
	if not ok_crop:
		report["result"]["pass"] = False
		report["result"]["message"] = "crop infeasible"
		report["crop"]["reasons"] = crop_reasons
		write_report(report_path, report, settings["io"]["report_format"])
		raise RuntimeError("global stabilization unsuitable for this material (crop infeasible)")
	if args.copy_subs:
		report["warnings"].append("subtitles copied unchanged; crop may remove visible subtitle regions")
	print("Running vidstabtransform (pass 2/2): stabilize + crop + encode")
	render_stabilized_output(
		args.input_file,
		args.output_file,
		trf_path,
		settings["engine"]["transform"],
		crop_rect,
		width,
		height,
		args.copy_audio,
		args.copy_subs,
		start_seconds,
		duration_seconds,
	)
	report["result"]["pass"] = True
	report["result"]["message"] = "ok"
	write_report(report_path, report, settings["io"]["report_format"])
	return

#============================================

if __name__ == "__main__":
	main()
