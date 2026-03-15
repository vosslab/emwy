#!/usr/bin/env python3
"""Tests for emwy_tools/track_runner/tr_paths.py."""

# Standard Library
import os

# local repo modules (conftest.py adds track_runner/ to sys.path)
import tr_paths

#============================================

def test_default_config_path_basename():
	"""Config path uses only the basename of the input file."""
	result = tr_paths.default_config_path("/fast-ssd/videos/lecture.mkv")
	assert result == "tr_config/lecture.mkv.track_runner.config.yaml"

#============================================

def test_default_seeds_path_basename():
	"""Seeds path uses only the basename of the input file."""
	result = tr_paths.default_seeds_path("/fast-ssd/videos/lecture.mkv")
	assert result == "tr_config/lecture.mkv.track_runner.seeds.json"

#============================================

def test_default_diagnostics_path_basename():
	"""Diagnostics path uses only the basename of the input file."""
	result = tr_paths.default_diagnostics_path("/fast-ssd/videos/lecture.mkv")
	assert result == "tr_config/lecture.mkv.track_runner.diagnostics.json"

#============================================

def test_default_intervals_path_basename():
	"""Intervals path uses only the basename of the input file."""
	result = tr_paths.default_intervals_path("/fast-ssd/videos/lecture.mkv")
	assert result == "tr_config/lecture.mkv.track_runner.intervals.json"

#============================================

def test_default_output_path_stays_next_to_input():
	"""Output path stays in the same directory as the input file."""
	result = tr_paths.default_output_path("/fast-ssd/videos/lecture.mkv")
	assert result == "/fast-ssd/videos/lecture_tracked.mkv"

#============================================

def test_default_output_path_preserves_extension():
	"""Output path preserves the original file extension."""
	result = tr_paths.default_output_path("/data/clip.mp4")
	assert result == "/data/clip_tracked.mp4"

#============================================

def test_data_dir_constant():
	"""DATA_DIR is the expected subdirectory name."""
	assert tr_paths.DATA_DIR == "tr_config"

#============================================

def test_ensure_data_dir_creates_directory(tmp_path):
	"""ensure_data_dir creates the tr_config directory."""
	# change to tmp_path so DATA_DIR resolves there
	original_cwd = os.getcwd()
	os.chdir(str(tmp_path))
	try:
		result = tr_paths.ensure_data_dir()
		assert os.path.isdir(result)
		assert result == os.path.abspath("tr_config")
	finally:
		os.chdir(original_cwd)

#============================================

def test_ensure_data_dir_idempotent(tmp_path):
	"""ensure_data_dir succeeds when directory already exists."""
	original_cwd = os.getcwd()
	os.chdir(str(tmp_path))
	try:
		# create it twice; second call should not raise
		tr_paths.ensure_data_dir()
		result = tr_paths.ensure_data_dir()
		assert os.path.isdir(result)
	finally:
		os.chdir(original_cwd)

#============================================

def test_ensure_parent_dir_creates_parent(tmp_path):
	"""ensure_parent_dir creates the parent directory of a file path."""
	target = os.path.join(str(tmp_path), "subdir", "file.json")
	tr_paths.ensure_parent_dir(target)
	parent = os.path.dirname(target)
	assert os.path.isdir(parent)

#============================================

def test_paths_strip_directory_from_input():
	"""All data paths use only the basename, ignoring directory components."""
	deep_input = "/a/b/c/d/video.avi"
	config = tr_paths.default_config_path(deep_input)
	seeds = tr_paths.default_seeds_path(deep_input)
	diag = tr_paths.default_diagnostics_path(deep_input)
	intervals = tr_paths.default_intervals_path(deep_input)
	# none should contain the original directory path
	assert "/a/b/c/d/" not in config
	assert "/a/b/c/d/" not in seeds
	assert "/a/b/c/d/" not in diag
	assert "/a/b/c/d/" not in intervals
	# all should start with tr_config/
	assert config.startswith("tr_config/")
	assert seeds.startswith("tr_config/")
	assert diag.startswith("tr_config/")
	assert intervals.startswith("tr_config/")
