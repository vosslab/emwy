"""state_io.py

JSON read/write for track_runner seeds and diagnostics files.

Seeds files store human and computed seed points for runner tracking.
Diagnostics files store interval and trajectory data for debugging.
"""

# Standard Library
import json
import os

#============================================

# header key and version for seeds JSON files
SEEDS_HEADER_KEY = "track_runner_seeds"
SEEDS_HEADER_VALUE = 2

# header key and version for diagnostics JSON files
DIAGNOSTICS_HEADER_KEY = "track_runner_diagnostics"
DIAGNOSTICS_HEADER_VALUE = 2

# valid mode values for seed entries
VALID_SEED_MODES = frozenset(
	["initial", "suggested_refine", "interval_refine", "gap_refine"]
)

#============================================

def default_seeds_path(input_file: str) -> str:
	"""Return the default seeds JSON file path for a given input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Seeds JSON file path.
	"""
	seeds_path = f"{input_file}.track_runner.seeds.json"
	return seeds_path


#============================================

def default_diagnostics_path(input_file: str) -> str:
	"""Return the default diagnostics JSON file path for a given input file.

	Args:
		input_file: Input media file path.

	Returns:
		str: Diagnostics JSON file path.
	"""
	diag_path = f"{input_file}.track_runner.diagnostics.json"
	return diag_path


#============================================

def load_seeds(path: str) -> dict:
	"""Load a seeds JSON file and validate the header.

	Returns an empty seeds structure if the file does not exist.

	Args:
		path: Path to the seeds JSON file.

	Returns:
		dict: Parsed seeds data with validated header, or empty structure.

	Raises:
		RuntimeError: If the file exists but header version is wrong.
	"""
	# return empty structure if file does not exist
	if not os.path.isfile(path):
		return {SEEDS_HEADER_KEY: SEEDS_HEADER_VALUE, "seeds": []}
	with open(path, "r") as fh:
		data = json.load(fh)
	if not isinstance(data, dict):
		raise RuntimeError(f"seeds file did not parse as a mapping: {path}")
	# validate the header key and version
	header_val = data.get(SEEDS_HEADER_KEY)
	if header_val != SEEDS_HEADER_VALUE:
		raise RuntimeError(
			f"seeds file header mismatch in {path}: "
			f"expected {SEEDS_HEADER_KEY}={SEEDS_HEADER_VALUE}, got {header_val}"
		)
	return data


#============================================

def write_seeds(path: str, seeds_data: dict) -> None:
	"""Write seeds data to a JSON file.

	Ensures the required header key is present before writing.

	Args:
		path: Output file path.
		seeds_data: Seeds dictionary to write (must include 'seeds' list).
	"""
	# ensure header version is set correctly before writing
	seeds_data[SEEDS_HEADER_KEY] = SEEDS_HEADER_VALUE
	with open(path, "w") as fh:
		json.dump(seeds_data, fh, indent=2)
	return


#============================================

def load_diagnostics(path: str) -> dict:
	"""Load a diagnostics JSON file and validate the header.

	Returns an empty diagnostics structure if the file does not exist.

	Args:
		path: Path to the diagnostics JSON file.

	Returns:
		dict: Parsed diagnostics data with validated header, or empty structure.

	Raises:
		RuntimeError: If the file exists but header version is wrong.
	"""
	# return empty structure if file does not exist
	if not os.path.isfile(path):
		return {DIAGNOSTICS_HEADER_KEY: DIAGNOSTICS_HEADER_VALUE}
	with open(path, "r") as fh:
		data = json.load(fh)
	if not isinstance(data, dict):
		raise RuntimeError(f"diagnostics file did not parse as a mapping: {path}")
	# validate the header key and version
	header_val = data.get(DIAGNOSTICS_HEADER_KEY)
	if header_val != DIAGNOSTICS_HEADER_VALUE:
		raise RuntimeError(
			f"diagnostics file header mismatch in {path}: "
			f"expected {DIAGNOSTICS_HEADER_KEY}={DIAGNOSTICS_HEADER_VALUE}, got {header_val}"
		)
	return data


#============================================

def write_diagnostics(path: str, diagnostics_data: dict) -> None:
	"""Write diagnostics data to a JSON file.

	Ensures the required header key is present before writing.

	Args:
		path: Output file path.
		diagnostics_data: Diagnostics dictionary to write.
	"""
	# ensure header version is set correctly before writing
	diagnostics_data[DIAGNOSTICS_HEADER_KEY] = DIAGNOSTICS_HEADER_VALUE
	with open(path, "w") as fh:
		json.dump(diagnostics_data, fh, indent=2)
	return


#============================================

def merge_seeds(existing_seeds: list, new_seeds: list) -> list:
	"""Merge new seeds into an existing seeds list.

	New seeds never overwrite existing seeds at the same frame number.
	Seeds at frames not already in existing_seeds are appended.

	Args:
		existing_seeds: List of existing seed dicts, each with a 'frame' key.
		new_seeds: List of new seed dicts to merge in.

	Returns:
		list: Merged list of seed dicts with no duplicate frame entries.
	"""
	# build a set of frame numbers already present in existing seeds
	existing_frames = {seed["frame"] for seed in existing_seeds}
	# start with a copy of the existing seeds list
	merged = list(existing_seeds)
	# append only new seeds whose frame is not already present
	for seed in new_seeds:
		frame_num = seed["frame"]
		if frame_num not in existing_frames:
			merged.append(seed)
			# track this frame so duplicates within new_seeds are also skipped
			existing_frames.add(frame_num)
	return merged


#============================================
def write_solver_diagnostics(
	diagnostics: dict,
	path: str,
	fps: float,
) -> None:
	"""Serialize interval solver diagnostics to a JSON file.

	Strips non-serializable objects and builds a compact summary
	from the raw solver output before writing.

	Args:
		diagnostics: Dict from interval_solver.solve_all_intervals().
		path: Output JSON file path.
		fps: Video fps for inclusion in the file.
	"""
	# build a JSON-safe summary (do not write full per-frame trajectory)
	intervals_summary = []
	for iv in diagnostics.get("intervals", []):
		score = iv.get("interval_score", {})
		entry = {
			"start_frame": iv["start_frame"],
			"end_frame": iv["end_frame"],
			"start_s": round(iv["start_frame"] / max(1.0, fps), 3),
			"end_s": round(iv["end_frame"] / max(1.0, fps), 3),
			"agreement_score": round(
				float(score.get("agreement_score", 0.0)), 4,
			),
			"identity_score": round(
				float(score.get("identity_score", 0.0)), 4,
			),
			"competitor_margin": round(
				float(score.get("competitor_margin", 0.0)), 4,
			),
			"confidence": score.get("confidence", "low"),
			"failure_reasons": score.get("failure_reasons", []),
		}
		intervals_summary.append(entry)

	# preserve cyclical prior if detected
	cyclical = diagnostics.get("cyclical_prior")
	cyclical_safe = None
	if cyclical is not None:
		cyclical_safe = {
			"period_frames": int(cyclical.get("period_frames", 0)),
			"period_s": round(
				float(cyclical.get("period_s", 0.0)), 3,
			),
			"correlation": round(
				float(cyclical.get("correlation", 0.0)), 4,
			),
		}

	diag_out = {
		DIAGNOSTICS_HEADER_KEY: DIAGNOSTICS_HEADER_VALUE,
		"fps": round(fps, 6),
		"intervals": intervals_summary,
		"cyclical_prior": cyclical_safe,
	}
	write_diagnostics(path, diag_out)


#============================================

# round-trip self-check for load/write pairs
if __name__ == "__main__":
	import tempfile
	# test seeds round-trip
	seeds_data = {
		"video_file": "test.mov",
		"seeds": [
			{
				"frame": 150,
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
	write_seeds(tmp_path, seeds_data)
	loaded = load_seeds(tmp_path)
	assert loaded["seeds"][0]["frame"] == 150
	assert loaded[SEEDS_HEADER_KEY] == SEEDS_HEADER_VALUE
	os.unlink(tmp_path)

	# test diagnostics round-trip
	diag_data = {
		"intervals": [1, 2, 3],
		"trajectory": [{"frame": 0, "x": 100}],
	}
	with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
		tmp_path = tmp.name
	write_diagnostics(tmp_path, diag_data)
	loaded_diag = load_diagnostics(tmp_path)
	assert loaded_diag["intervals"] == [1, 2, 3]
	assert loaded_diag[DIAGNOSTICS_HEADER_KEY] == DIAGNOSTICS_HEADER_VALUE
	os.unlink(tmp_path)

	# test merge_seeds
	existing = [{"frame": 10, "mode": "initial"}, {"frame": 20, "mode": "initial"}]
	new = [{"frame": 10, "mode": "gap_refine"}, {"frame": 30, "mode": "interval_refine"}]
	merged = merge_seeds(existing, new)
	assert len(merged) == 3
	# frame 10 must be the original, not overwritten
	frame_10 = next(s for s in merged if s["frame"] == 10)
	assert frame_10["mode"] == "initial"
	print("all round-trip checks passed")
