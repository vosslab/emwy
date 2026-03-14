"""Unit tests for track_runner.state_io module."""

# Standard Library
import os
import json
import tempfile

# PIP3 modules
import pytest

# local repo modules
import track_runner.state_io as state_io_mod


#============================================
def test_state_io_seeds_round_trip() -> None:
	"""write_seeds then load_seeds returns same seeds list."""
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
	with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
		tmp_path = tmp.name
	state_io_mod.write_seeds(tmp_path, seeds_data)
	loaded = state_io_mod.load_seeds(tmp_path)
	assert loaded["seeds"][0]["frame_index"] == 150
	assert loaded[state_io_mod.SEEDS_HEADER_KEY] == state_io_mod.SEEDS_HEADER_VALUE
	os.unlink(tmp_path)


#============================================
def test_state_io_seeds_missing_file_returns_empty() -> None:
	"""load_seeds returns empty structure for non-existent file."""
	result = state_io_mod.load_seeds("/tmp/nonexistent_seeds_99999.json")
	assert "seeds" in result
	assert result["seeds"] == []


#============================================
def test_state_io_seeds_wrong_header_raises() -> None:
	"""load_seeds raises RuntimeError if header version is wrong."""
	bad_data = {"track_runner_seeds": 99, "seeds": []}
	with tempfile.NamedTemporaryFile(
		suffix=".json", mode="w", delete=False
	) as tmp:
		json.dump(bad_data, tmp)
		tmp_path = tmp.name
	with pytest.raises(RuntimeError):
		state_io_mod.load_seeds(tmp_path)
	os.unlink(tmp_path)


#============================================
def test_state_io_diagnostics_round_trip() -> None:
	"""write_diagnostics then load_diagnostics returns same data."""
	diag_data = {
		"intervals": [
			{"start_frame": 0, "end_frame": 100, "confidence": 0.9},
			{"start_frame": 100, "end_frame": 200, "agreement_score": 0.8},
		],
		"trajectory": [{"frame": 0, "x": 100}],
	}
	with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
		tmp_path = tmp.name
	state_io_mod.write_diagnostics(tmp_path, diag_data)
	loaded = state_io_mod.load_diagnostics(tmp_path)
	assert len(loaded["intervals"]) == 2
	assert loaded["intervals"][0]["start_frame"] == 0
	# score reconstruction: flat keys get grouped into interval_score sub-dict
	assert "interval_score" in loaded["intervals"][1]
	assert loaded["intervals"][1]["interval_score"]["agreement_score"] == 0.8
	assert loaded[state_io_mod.DIAGNOSTICS_HEADER_KEY] == state_io_mod.DIAGNOSTICS_HEADER_VALUE
	os.unlink(tmp_path)


#============================================
def test_state_io_diagnostics_missing_file_returns_empty() -> None:
	"""load_diagnostics returns empty structure for non-existent file."""
	result = state_io_mod.load_diagnostics("/tmp/nonexistent_diag_99999.json")
	assert state_io_mod.DIAGNOSTICS_HEADER_KEY in result


#============================================
def test_state_io_merge_seeds_no_duplicate_frames() -> None:
	"""merge_seeds never overwrites an existing frame entry."""
	existing = [{"frame": 10, "mode": "initial"}, {"frame": 20, "mode": "initial"}]
	new = [{"frame": 10, "mode": "gap_refine"}, {"frame": 30, "mode": "interval_refine"}]
	merged = state_io_mod.merge_seeds(existing, new)
	assert len(merged) == 3
	# original frame 10 entry must not be overwritten
	frame_10 = next(s for s in merged if s["frame"] == 10)
	assert frame_10["mode"] == "initial"
