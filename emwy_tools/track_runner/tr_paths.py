"""tr_paths.py

Centralized path construction for track_runner config and state files.

By default, config and state files live in a ./tr_config/ subdirectory
under the current working directory. Encoded output stays next to the
source video file. The tr_config/ directory is auto-created as a real
directory on first run; users can replace it with a symlink to any
location (network drive, NAS mount, etc.).
"""

# Standard Library
import os

#============================================

# subdirectory for config and state files relative to cwd
DATA_DIR = "tr_config"

#============================================

def ensure_data_dir() -> str:
	"""Create the tr_config data directory if it does not exist.

	Returns:
		str: Absolute path to the data directory.
	"""
	data_path = os.path.abspath(DATA_DIR)
	os.makedirs(data_path, exist_ok=True)
	return data_path

#============================================

def ensure_parent_dir(path: str) -> None:
	"""Create the parent directory of path if it does not exist.

	Args:
		path: File path whose parent directory should exist.
	"""
	parent = os.path.dirname(os.path.abspath(path))
	os.makedirs(parent, exist_ok=True)

#============================================

def _data_file_path(input_file: str, suffix: str) -> str:
	"""Build a data file path inside DATA_DIR from the input basename.

	Args:
		input_file: Full path to the input video file.
		suffix: File suffix to append (e.g. '.track_runner.seeds.json').

	Returns:
		str: Path like tr_config/{basename}{suffix}.
	"""
	basename = os.path.basename(input_file)
	filename = f"{basename}{suffix}"
	data_path = os.path.join(DATA_DIR, filename)
	return data_path

#============================================

def default_config_path(input_file: str) -> str:
	"""Return the default config YAML path for a given input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Config file path inside tr_config/.
	"""
	config_path = _data_file_path(input_file, ".track_runner.config.yaml")
	return config_path

#============================================

def default_seeds_path(input_file: str) -> str:
	"""Return the default seeds JSON file path for a given input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Seeds JSON file path inside tr_config/.
	"""
	seeds_path = _data_file_path(input_file, ".track_runner.seeds.json")
	return seeds_path

#============================================

def default_diagnostics_path(input_file: str) -> str:
	"""Return the default diagnostics JSON file path for a given input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Diagnostics JSON file path inside tr_config/.
	"""
	diag_path = _data_file_path(input_file, ".track_runner.diagnostics.json")
	return diag_path

#============================================

def default_intervals_path(input_file: str) -> str:
	"""Return the default solved-intervals JSON file path for a given input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Solved-intervals JSON file path inside tr_config/.
	"""
	intervals_path = _data_file_path(input_file, ".track_runner.intervals.json")
	return intervals_path

#============================================

def default_encode_analysis_path(input_file: str) -> str:
	"""Return the default encode analysis YAML path for a given input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Analysis YAML file path inside tr_config/.
	"""
	analysis_path = _data_file_path(input_file, ".encode_analysis.yaml")
	return analysis_path

#============================================

def default_output_path(input_file: str) -> str:
	"""Return the default encoded output path next to the source video.

	Output stays in the same directory as the input file to keep
	large encoded files on fast local storage.

	Args:
		input_file: Input media file path.

	Returns:
		str: Output file path like {input_dir}/{stem}_tracked{ext}.
	"""
	stem, ext = os.path.splitext(input_file)
	output_path = f"{stem}_tracked{ext}"
	return output_path
