"""
config.py

Configuration loading, validation, and default schema for the track_runner tool (v2).
Seeds and diagnostics are handled separately in state_io.py.
"""

# Standard Library
import copy
import os

# PIP3 modules
import yaml

#============================================

TOOL_CONFIG_HEADER_KEY = "track_runner"
TOOL_CONFIG_HEADER_VALUE = 2

#============================================

def default_config() -> dict:
	"""
	Return the minimal default config schema for track_runner v2.

	Returns:
		dict: Default configuration dictionary.
	"""
	config = {
		TOOL_CONFIG_HEADER_KEY: TOOL_CONFIG_HEADER_VALUE,
		"detection": {
			"model": "yolov8n",
			"confidence_threshold": 0.25,
		},
		"processing": {
			"crop_aspect": "1:1",
			"crop_fill_ratio": 0.30,
			"video_codec": "libx264",
			"crf": 18,
			"encode_filters": [],
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
		RuntimeError: If required keys are missing or the header is wrong.
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
	# check required top-level sections
	required_sections = ["detection", "processing"]
	for section in required_sections:
		if section not in config:
			raise RuntimeError(f"config missing required key: {section}")
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
	# check header key exists
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
	# ensure header is present before writing
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
