"""
config.py

Configuration loading, validation, and default schema for the track_runner tool.
"""

# Standard Library
import copy
import os

# PIP3 modules
import yaml

#============================================

TOOL_CONFIG_HEADER_KEY = "track_runner"
TOOL_CONFIG_HEADER_VALUE = 1

SEEDS_HEADER_KEY = "track_runner_seeds"
SEEDS_HEADER_VALUE = 1

DIAGNOSTICS_HEADER_KEY = "track_runner_diagnostics"
DIAGNOSTICS_HEADER_VALUE = 1

#============================================

def default_config() -> dict:
	"""
	Return the full default config schema for track_runner.

	Returns:
		dict: Default configuration dictionary.
	"""
	config = {
		TOOL_CONFIG_HEADER_KEY: TOOL_CONFIG_HEADER_VALUE,
		"settings": {
			"detection": {
				"kind": "yolo",
				"model": "yolov8n",
				"detect_interval": 1,
				"confidence_threshold": 0.25,
				"nms_threshold": 0.45,
				"fallback": "hog",
			},
			"camera_compensation": {
				"enabled": False,
				"method": "affine_ransac",
				"exclude_tracked_region": True,
			},
			"tracking": {
				"min_search_radius": 100,
				"search_radius_scale": 1.5,
				"reacquire_window": 15,
				"confidence_threshold": 0.3,
				"reacquire_threshold": 0.5,
				"max_missed_before_lost": 60,
				"max_vy_fraction": 0.03,
				"max_v_log_h": 0.05,
				"velocity_freeze_streak": 3,
				"jerk_threshold": 0.3,
			},
			"scoring": {
				"w_detect": 0.30,
				"w_predict": 0.25,
				"w_color": 0.15,
				"w_size": 0.15,
				"w_path": 0.10,
				"w_motion": 0.05,
				"hard_gate_aspect_min": 1.5,
				"hard_gate_aspect_max": 4.0,
				"hard_gate_scale_band": 2.0,
				"max_bbox_area_fraction": 0.15,
				"vertical_limit_scale": 0.5,
				"max_displacement_per_frame": 80,
			},
			"crop": {
				"aspect": "1:1",
				"target_fill_ratio": 0.30,
				"far_fill_ratio": 0.50,
				"far_threshold_px": 120,
				"very_far_fill_ratio": 0.65,
				"very_far_threshold_px": 60,
				"smoothing_attack": 0.15,
				"smoothing_release": 0.05,
				"max_crop_velocity": 30,
				"min_crop_size": 200,
			},
			"jersey_color": {
				"hsv_low": None,
				"hsv_high": None,
			},
			"seeding": {
				"interval_seconds": 10,
				"min_seeds": 1,
				"torso_aspect_min": 0.3,
				"torso_aspect_max": 0.8,
			},
			"output": {
				"video_codec": "libx264",
				"crf": 18,
			},
			"experiment": {
				"enabled": False,
				"variant": "full",
				"write_debug_video": True,
				"save_metrics_json": True,
			},
			"io": {
				"cache_dir": None,
				"report_format": "yaml",
			},
		},
	}
	return config

#============================================

def validate_config(config: dict) -> None:
	"""
	Validate that required keys are present in the config.

	Args:
		config: Configuration dictionary to validate.

	Raises:
		RuntimeError: If required keys are missing.
	"""
	# check header key
	if TOOL_CONFIG_HEADER_KEY not in config:
		raise RuntimeError(
			f"config missing required header key: {TOOL_CONFIG_HEADER_KEY}"
		)
	header_value = config[TOOL_CONFIG_HEADER_KEY]
	if header_value != TOOL_CONFIG_HEADER_VALUE:
		raise RuntimeError(
			f"config header value mismatch: expected "
			f"{TOOL_CONFIG_HEADER_VALUE}, got {header_value}"
		)
	# check settings key
	if "settings" not in config:
		raise RuntimeError("config missing required key: settings")
	settings = config["settings"]
	if not isinstance(settings, dict):
		raise RuntimeError("config 'settings' must be a mapping")
	# check required sub-sections
	required_sections = ["detection", "tracking", "scoring", "crop"]
	for section in required_sections:
		if section not in settings:
			raise RuntimeError(
				f"config missing required key: settings.{section}"
			)
	return

#============================================

def load_config(path: str) -> dict:
	"""
	Read a YAML config file and validate the header.

	Args:
		path: Path to the YAML config file.

	Returns:
		dict: Parsed and validated configuration.

	Raises:
		RuntimeError: If the file cannot be read or header is missing.
	"""
	if not os.path.isfile(path):
		raise RuntimeError(f"config file not found: {path}")
	with open(path, "r") as fh:
		config = yaml.safe_load(fh)
	if not isinstance(config, dict):
		raise RuntimeError(f"config file did not parse as a mapping: {path}")
	# check header
	if TOOL_CONFIG_HEADER_KEY not in config:
		raise RuntimeError(
			f"config missing required header key: "
			f"{TOOL_CONFIG_HEADER_KEY} in {path}"
		)
	# backward compat: warn if seeds found in config file
	if "seeds" in config:
		print(f"warning: seeds found in config file {path}; use separate seeds file instead")
	return config

#============================================

def write_config(path: str, config: dict) -> None:
	"""
	Write a config dictionary to a YAML file.

	Args:
		path: Output file path.
		config: Configuration dictionary to write.
	"""
	# ensure header is present
	if TOOL_CONFIG_HEADER_KEY not in config:
		config[TOOL_CONFIG_HEADER_KEY] = TOOL_CONFIG_HEADER_VALUE
	with open(path, "w") as fh:
		yaml.dump(config, fh, default_flow_style=False, sort_keys=False)
	return

#============================================

def default_config_path(input_file: str) -> str:
	"""
	Build the default config path based on the input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Config file path.
	"""
	return f"{input_file}.track_runner.config.yaml"

#============================================

def default_seeds_path(input_file: str) -> str:
	"""Build the default seeds file path based on the input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Seeds file path.
	"""
	return f"{input_file}.track_runner.seeds.yaml"

#============================================

def default_diagnostics_path(input_file: str) -> str:
	"""Build the default diagnostics file path based on the input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Diagnostics file path.
	"""
	return f"{input_file}.track_runner.diagnostics.yaml"

#============================================

def load_seeds(path: str) -> list:
	"""Load seeds from a seeds YAML file.

	Returns an empty list if the file does not exist.

	Args:
		path: Path to the seeds YAML file.

	Returns:
		list: List of seed dicts.
	"""
	if not os.path.isfile(path):
		return []
	with open(path, "r") as fh:
		data = yaml.safe_load(fh)
	if not isinstance(data, dict):
		return []
	# validate header
	if data.get(SEEDS_HEADER_KEY) != SEEDS_HEADER_VALUE:
		print(f"warning: seeds file missing valid header: {path}")
		return []
	seeds = data.get("seeds", [])
	return seeds

#============================================

def write_seeds(path: str, seeds: list) -> None:
	"""Write seeds list to a YAML file.

	Args:
		path: Output file path.
		seeds: List of seed dicts.
	"""
	data = {
		SEEDS_HEADER_KEY: SEEDS_HEADER_VALUE,
		"seeds": seeds,
	}
	with open(path, "w") as fh:
		yaml.dump(data, fh, default_flow_style=False, sort_keys=False)
	return

#============================================

def load_diagnostics(path: str) -> dict:
	"""Load diagnostics from a diagnostics YAML file.

	Returns an empty dict if the file does not exist.

	Args:
		path: Path to the diagnostics YAML file.

	Returns:
		dict: Diagnostics dictionary.
	"""
	if not os.path.isfile(path):
		return {}
	with open(path, "r") as fh:
		data = yaml.safe_load(fh)
	if not isinstance(data, dict):
		return {}
	# validate header
	if data.get(DIAGNOSTICS_HEADER_KEY) != DIAGNOSTICS_HEADER_VALUE:
		print(f"warning: diagnostics file missing valid header: {path}")
		return {}
	diag = dict(data)
	# remove header key from returned dict
	diag.pop(DIAGNOSTICS_HEADER_KEY, None)
	return diag

#============================================

def write_diagnostics(path: str, diag: dict) -> None:
	"""Write diagnostics dict to a YAML file.

	Args:
		path: Output file path.
		diag: Diagnostics dictionary.
	"""
	data = {DIAGNOSTICS_HEADER_KEY: DIAGNOSTICS_HEADER_VALUE}
	data.update(diag)
	with open(path, "w") as fh:
		yaml.dump(data, fh, default_flow_style=False, sort_keys=False)
	return

def merge_config(base: dict, override: dict) -> dict:
	"""
	Deep merge override into base config.

	Only dict values are merged recursively; scalars and lists
	from override replace the base value.

	Args:
		base: Base configuration dictionary.
		override: Override dictionary with partial values.

	Returns:
		dict: Merged configuration dictionary.
	"""
	result = copy.deepcopy(base)
	for key, value in override.items():
		# recursive merge only for dict-to-dict
		if key in result and isinstance(result[key], dict) and isinstance(value, dict):
			result[key] = merge_config(result[key], value)
		else:
			result[key] = copy.deepcopy(value)
	return result
