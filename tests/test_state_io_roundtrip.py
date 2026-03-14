"""Round-trip tests for state_io load and write functions."""

# Standard Library
import os
import sys

# Ensure emwy_tools package is importable
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# local repo modules
from emwy_tools.track_runner import state_io

#============================================

def test_seeds_roundtrip(tmp_path) -> None:
	"""Write seeds data, load it back, verify frame_index and header.

	Creates a seeds file with one entry, writes it, reads it back,
	and verifies that the frame index and header version are preserved.
	"""
	seeds_data = {
		"video_file": "test.mov",
		"seeds": [
			{
				"frame_index": 150,
				"time_s": 5.0,
				"torso_box": [640, 360, 40, 60],
				"jersey_hsv": [120, 180, 200],
				"pass": 1,
				"source": "human",
				"mode": "initial",
			}
		],
	}
	tmp_file = tmp_path / "seeds.json"
	state_io.write_seeds(str(tmp_file), seeds_data)
	loaded = state_io.load_seeds(str(tmp_file))
	assert loaded["seeds"][0]["frame_index"] == 150
	assert loaded[state_io.SEEDS_HEADER_KEY] == state_io.SEEDS_HEADER_VALUE

#============================================

def test_diagnostics_roundtrip(tmp_path) -> None:
	"""Write diagnostics, load back, verify intervals and header.

	Creates a diagnostics file with interval data, writes it, reads it back,
	and verifies that the intervals and header version are preserved.
	"""
	diag_data = {
		"intervals": [1, 2, 3],
		"trajectory": [{"frame": 0, "x": 100}],
	}
	tmp_file = tmp_path / "diagnostics.json"
	state_io.write_diagnostics(str(tmp_file), diag_data)
	loaded_diag = state_io.load_diagnostics(str(tmp_file))
	assert loaded_diag["intervals"] == [1, 2, 3]
	assert loaded_diag[state_io.DIAGNOSTICS_HEADER_KEY] == state_io.DIAGNOSTICS_HEADER_VALUE

#============================================

def test_merge_seeds() -> None:
	"""Test merge_seeds with existing and new seeds.

	Verifies that new seeds are added only if their frame is not already
	present in the existing list, and that existing seeds are never
	overwritten.
	"""
	existing = [{"frame": 10, "mode": "initial"}, {"frame": 20, "mode": "initial"}]
	new = [{"frame": 10, "mode": "gap_refine"}, {"frame": 30, "mode": "interval_refine"}]
	merged = state_io.merge_seeds(existing, new)
	assert len(merged) == 3
	# frame 10 must be the original, not overwritten
	frame_10 = next(s for s in merged if s["frame"] == 10)
	assert frame_10["mode"] == "initial"

#============================================

def test_intervals_roundtrip(tmp_path) -> None:
	"""Write intervals, load back, verify header and count.

	Creates a solved-intervals file with one interval entry, writes it,
	reads it back, and verifies that the header version and interval
	count are preserved.
	"""
	intervals_data = {
		"solved_intervals": {
			"100|1731.50|629.50|39.00|59.00|450|1700.00|600.00|38.00|58.00": {
				"start_frame": 100,
				"end_frame": 450,
				"fused_track": [{"cx": 100.0, "cy": 200.0}],
			},
		},
	}
	tmp_file = tmp_path / "intervals.json"
	state_io.write_intervals(str(tmp_file), intervals_data)
	loaded_iv = state_io.load_intervals(str(tmp_file))
	assert loaded_iv[state_io.INTERVALS_HEADER_KEY] == state_io.INTERVALS_HEADER_VALUE
	assert len(loaded_iv["solved_intervals"]) == 1

#============================================

def test_interval_fingerprint_determinism() -> None:
	"""Verify deterministic fingerprint output from seed states.

	Creates two seed endpoint states and verifies that the same inputs
	always produce the same fingerprint string. The fingerprint encodes
	frame index and rounded position data.
	"""
	seed_a = {"frame_index": 100, "cx": 1731.5, "cy": 629.5, "w": 39.0, "h": 59.0}
	seed_b = {"frame_index": 450, "cx": 1700.0, "cy": 600.0, "w": 38.0, "h": 58.0}
	fp = state_io.interval_fingerprint(seed_a, seed_b)
	assert fp == "100|1731.50|629.50|39.00|59.00|450|1700.00|600.00|38.00|58.00"
	# same inputs must produce same fingerprint
	fp2 = state_io.interval_fingerprint(seed_a, seed_b)
	assert fp == fp2
