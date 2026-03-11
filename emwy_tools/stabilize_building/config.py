"""
config.py

Config loading, defaults, and validation for stabilize_building.
"""

# Standard Library
import os

# PIP3 modules
import yaml

#============================================

TOOL_CONFIG_HEADER_KEY = "stabilize_building"
TOOL_CONFIG_HEADER_VALUE = 1

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
