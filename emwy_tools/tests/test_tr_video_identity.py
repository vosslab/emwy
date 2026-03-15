#!/usr/bin/env python3
"""Tests for emwy_tools/track_runner/tr_video_identity.py."""

# Standard Library
import os

# local repo modules (conftest.py adds track_runner/ to sys.path)
import tr_video_identity

#============================================

def _sample_video_info() -> dict:
	"""Return a sample video_info dict for testing."""
	info = {
		"width": 1920,
		"height": 1080,
		"fps": 29.97,
		"frame_count": 54000,
		"duration_s": 1801.8,
	}
	return info

#============================================

def _sample_identity() -> dict:
	"""Return a sample identity dict for comparison tests."""
	identity = {
		"basename": "lecture.mkv",
		"size_bytes": 1234567890,
		"width": 1920,
		"height": 1080,
		"fps": 29.97,
		"frame_count": 54000,
		"duration_s": 1801.8,
	}
	return identity

#============================================

def test_make_video_identity_fields(tmp_path):
	"""make_video_identity produces all expected fields."""
	# create a temp file with known size
	test_file = os.path.join(str(tmp_path), "lecture.mkv")
	with open(test_file, "wb") as fh:
		fh.write(b"x" * 1024)
	video_info = _sample_video_info()
	identity = tr_video_identity.make_video_identity(test_file, video_info)
	assert identity["basename"] == "lecture.mkv"
	assert identity["size_bytes"] == 1024
	assert identity["width"] == 1920
	assert identity["height"] == 1080
	assert identity["fps"] == 29.97
	assert identity["frame_count"] == 54000
	assert identity["duration_s"] == 1801.8

#============================================

def test_make_video_identity_basename_only(tmp_path):
	"""make_video_identity uses only the basename, not the full path."""
	test_file = os.path.join(str(tmp_path), "deep", "path", "clip.mp4")
	os.makedirs(os.path.dirname(test_file))
	with open(test_file, "wb") as fh:
		fh.write(b"data")
	video_info = _sample_video_info()
	identity = tr_video_identity.make_video_identity(test_file, video_info)
	assert identity["basename"] == "clip.mp4"

#============================================

def test_compare_exact_match():
	"""Identical identities produce no mismatches."""
	stored = _sample_identity()
	current = _sample_identity()
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert mismatches == []

#============================================

def test_compare_basename_mismatch():
	"""Different basenames produce a mismatch."""
	stored = _sample_identity()
	current = _sample_identity()
	current["basename"] = "other.mkv"
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert len(mismatches) == 1
	assert "basename" in mismatches[0]

#============================================

def test_compare_size_bytes_mismatch():
	"""Different file sizes produce a mismatch."""
	stored = _sample_identity()
	current = _sample_identity()
	current["size_bytes"] = 9999999999
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert len(mismatches) == 1
	assert "size_bytes" in mismatches[0]

#============================================

def test_compare_width_mismatch():
	"""Different widths produce a mismatch."""
	stored = _sample_identity()
	current = _sample_identity()
	current["width"] = 1280
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert len(mismatches) == 1
	assert "width" in mismatches[0]

#============================================

def test_compare_height_mismatch():
	"""Different heights produce a mismatch."""
	stored = _sample_identity()
	current = _sample_identity()
	current["height"] = 720
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert len(mismatches) == 1
	assert "height" in mismatches[0]

#============================================

def test_compare_fps_within_tolerance():
	"""FPS difference within 0.01 produces no mismatch."""
	stored = _sample_identity()
	current = _sample_identity()
	# 0.005 difference is within 0.01 tolerance
	current["fps"] = 29.975
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert mismatches == []

#============================================

def test_compare_fps_outside_tolerance():
	"""FPS difference beyond 0.01 produces a mismatch."""
	stored = _sample_identity()
	current = _sample_identity()
	current["fps"] = 30.0
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert len(mismatches) == 1
	assert "fps" in mismatches[0]

#============================================

def test_compare_duration_within_tolerance():
	"""Duration difference within 0.5s produces no mismatch."""
	stored = _sample_identity()
	current = _sample_identity()
	current["duration_s"] = 1802.1
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert mismatches == []

#============================================

def test_compare_duration_outside_tolerance():
	"""Duration difference beyond 0.5s produces a mismatch."""
	stored = _sample_identity()
	current = _sample_identity()
	current["duration_s"] = 1803.0
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert len(mismatches) == 1
	assert "duration_s" in mismatches[0]

#============================================

def test_compare_frame_count_mismatch():
	"""Different frame counts produce a mismatch."""
	stored = _sample_identity()
	current = _sample_identity()
	current["frame_count"] = 54001
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert len(mismatches) == 1
	assert "frame_count" in mismatches[0]

#============================================

def test_compare_missing_field_skipped():
	"""Missing fields in stored identity are silently skipped."""
	stored = {"basename": "lecture.mkv", "width": 1920}
	current = _sample_identity()
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	# only basename and width can be compared; both match
	assert mismatches == []

#============================================

def test_compare_multiple_mismatches():
	"""Multiple field differences produce multiple mismatch messages."""
	stored = _sample_identity()
	current = _sample_identity()
	current["basename"] = "other.mkv"
	current["width"] = 1280
	current["fps"] = 60.0
	mismatches = tr_video_identity.compare_video_identity(stored, current)
	assert len(mismatches) == 3
