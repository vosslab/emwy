"""Unit tests for tools_common shared utilities."""

# Standard Library
import os
import tempfile

# PIP3 modules
import pytest

# local repo modules
import tools_common

#============================================

def test_ensure_file_exists_passes_for_real_file() -> None:
	"""ensure_file_exists does not raise for an existing file."""
	with tempfile.NamedTemporaryFile(delete=False) as tmp:
		tmp_path = tmp.name
	tools_common.ensure_file_exists(tmp_path)
	os.unlink(tmp_path)

#============================================

def test_ensure_file_exists_raises_for_missing() -> None:
	"""ensure_file_exists raises RuntimeError for missing file."""
	with pytest.raises(RuntimeError, match="file not found"):
		tools_common.ensure_file_exists(os.path.join(tempfile.gettempdir(), "nonexistent_file_abc123.xyz"))

#============================================

def test_check_dependency_passes_for_python() -> None:
	"""check_dependency does not raise for python3."""
	tools_common.check_dependency("python3")

#============================================

def test_check_dependency_raises_for_missing() -> None:
	"""check_dependency raises RuntimeError for missing command."""
	with pytest.raises(RuntimeError, match="missing dependency"):
		tools_common.check_dependency("nonexistent_command_xyz_999")

#============================================

def test_parse_time_seconds_none() -> None:
	"""parse_time_seconds(None) returns None."""
	assert tools_common.parse_time_seconds(None) is None

#============================================

def test_parse_time_seconds_empty() -> None:
	"""parse_time_seconds('') returns None."""
	assert tools_common.parse_time_seconds("") is None

#============================================

def test_parse_time_seconds_plain_float() -> None:
	"""parse_time_seconds('12.5') returns 12.5."""
	assert tools_common.parse_time_seconds("12.5") == 12.5

#============================================

def test_parse_time_seconds_hhmmss() -> None:
	"""parse_time_seconds('01:02:03') returns 3723.0."""
	result = tools_common.parse_time_seconds("01:02:03")
	assert abs(result - 3723.0) < 0.001

#============================================

def test_parse_time_seconds_invalid_format() -> None:
	"""parse_time_seconds('01:02') raises RuntimeError."""
	with pytest.raises(RuntimeError):
		tools_common.parse_time_seconds("01:02")

#============================================

def test_fps_fraction_to_float_integer() -> None:
	"""fps_fraction_to_float('30') returns 30.0."""
	assert tools_common.fps_fraction_to_float("30") == 30.0

#============================================

def test_fps_fraction_to_float_fraction() -> None:
	"""fps_fraction_to_float('30000/1001') returns ~29.97."""
	result = tools_common.fps_fraction_to_float("30000/1001")
	assert abs(result - 29.97) < 0.01

#============================================

def test_fps_fraction_to_float_zero_denominator() -> None:
	"""fps_fraction_to_float('30/0') raises RuntimeError."""
	with pytest.raises(RuntimeError, match="invalid fps denominator"):
		tools_common.fps_fraction_to_float("30/0")
