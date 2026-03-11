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
				"detect_interval": 4,
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
				"hard_gate_scale_band": 3.0,
			},
			"crop": {
				"aspect": "1:1",
				"target_fill_ratio": 0.30,
				"smoothing_attack": 0.15,
				"smoothing_release": 0.05,
				"max_crop_velocity": 30,
				"min_crop_size": 360,
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
		"seeds": [],
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
