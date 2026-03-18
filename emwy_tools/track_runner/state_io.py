"""state_io.py

JSON read/write for track_runner seeds and diagnostics files.

Seeds files store human and computed seed points for runner tracking.
Diagnostics files store interval and trajectory data for debugging.
"""

# Standard Library
import json
import os
import tempfile

#============================================

# header key and version for seeds JSON files
SEEDS_HEADER_KEY = "track_runner_seeds"
SEEDS_HEADER_VALUE = 2

# header key and version for diagnostics JSON files
DIAGNOSTICS_HEADER_KEY = "track_runner_diagnostics"
DIAGNOSTICS_HEADER_VALUE = 2

# header key and version for solved-intervals JSON files
INTERVALS_HEADER_KEY = "track_runner_intervals"
INTERVALS_HEADER_VALUE = 1

# valid mode values for seed entries
VALID_SEED_MODES = frozenset(
	["initial", "suggested_refine", "interval_refine", "gap_refine",
	"edit_redraw", "solve_refine", "interactive_refine", "bbox_polish",
	"target_refine"]
)

# flag to avoid repeating legacy obstructed-seed warnings on every save
_WARNED_LEGACY_OBSTRUCTED = False

#============================================

def _set_warned_legacy() -> None:
	"""Set the warned flag so legacy obstructed warnings print only once."""
	global _WARNED_LEGACY_OBSTRUCTED
	_WARNED_LEGACY_OBSTRUCTED = True

#============================================

def validate_seed(seed: dict) -> int | None:
	"""Validate a seed dict and return frame index if legacy issue found.

	Args:
		seed: Seed dictionary to validate.

	Returns:
		Frame index if approximate seed is missing torso_box, else None.
	"""
	status = seed.get("status")
	# legacy "obstructed" without torso_box is a data problem
	if status == "obstructed":
		if "torso_box" not in seed or seed["torso_box"] is None:
			frame_idx = seed.get("frame_index")
			return frame_idx
	# "approximate" should always have torso_box
	if status == "approximate":
		if "torso_box" not in seed or seed["torso_box"] is None:
			frame_idx = seed.get("frame_index")
			return frame_idx
	return None

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
	# backfill "conf" for seeds created before field was added
	# migrate legacy "obstructed" with torso_box to "approximate"
	# drop legacy "obstructed" without torso_box (unusable, no position data)
	if "seeds" in data and isinstance(data["seeds"], list):
		cleaned = []
		dropped_count = 0
		for seed in data["seeds"]:
			if "conf" not in seed:
				seed["conf"] = None
			status = seed.get("status")
			if status == "obstructed":
				if seed.get("torso_box") is not None:
					# has approx area, migrate to "approximate"
					seed["status"] = "approximate"
				else:
					# legacy obstructed without position data, drop it
					dropped_count += 1
					continue
			cleaned.append(seed)
		if dropped_count > 0:
			print(f"  dropped {dropped_count} legacy obstructed seed(s) "
				f"with no position data")
		# sort seeds by frame_index so consumers always get time-ordered data
		data["seeds"] = sorted(
			cleaned,
			key=lambda s: int(s["frame_index"]),
		)
	return data


#============================================

def write_seeds(path: str, seeds_data: dict) -> None:
	"""Write seeds data to a JSON file with atomic write semantics.

	Ensures the required header key is present before writing and validates
	all seeds. Uses atomic rename to prevent data corruption.

	Args:
		path: Output file path.
		seeds_data: Seeds dictionary to write (must include 'seeds' list).

	Raises:
		ValueError: If any seed fails validation.
	"""
	# validate all seeds before writing; collect legacy warnings
	if "seeds" in seeds_data and isinstance(seeds_data["seeds"], list):
		bad_frames = []
		for seed in seeds_data["seeds"]:
			bad_frame = validate_seed(seed)
			if bad_frame is not None:
				bad_frames.append(bad_frame)
		if bad_frames and not _WARNED_LEGACY_OBSTRUCTED:
			_set_warned_legacy()
			print(f"  warning: {len(bad_frames)} approx seed(s) missing "
				f"torso_box (use 'a' key to fix): frames {bad_frames}")

	# ensure header version is set correctly before writing
	seeds_data[SEEDS_HEADER_KEY] = SEEDS_HEADER_VALUE
	# sort seeds by frame_index for human-readable output
	if "seeds" in seeds_data and isinstance(seeds_data["seeds"], list):
		seeds_data["seeds"] = sorted(
			seeds_data["seeds"],
			key=lambda s: int(s["frame_index"]),
		)

	# write to temp file in same directory (same filesystem for atomic rename)
	dir_path = os.path.dirname(os.path.abspath(path))
	fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp.json")
	try:
		with os.fdopen(fd, "w") as fh:
			json.dump(seeds_data, fh, indent=2)
		# atomic rename - never truncates original until new content is ready
		os.replace(tmp_path, path)
	except Exception:
		# clean up temp file if anything failed before replace
		if os.path.exists(tmp_path):
			os.unlink(tmp_path)
		raise


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
	# reconstruct interval_score sub-dict from flat on-disk fields
	# write_solver_diagnostics flattens interval_score to top-level keys,
	# but consumers expect iv["interval_score"]["confidence"] etc.
	_score_keys = (
		"agreement_score", "identity_score", "competitor_margin",
		"confidence", "failure_reasons",
	)
	for iv in data.get("intervals", []):
		if not isinstance(iv, dict):
			continue
		if "interval_score" not in iv:
			score = {}
			for key in _score_keys:
				if key in iv:
					score[key] = iv[key]
			iv["interval_score"] = score
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
	# atomic write: temp file + rename to avoid corrupt file on interruption
	dir_path = os.path.dirname(os.path.abspath(path))
	fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp.json")
	try:
		with os.fdopen(fd, "w") as fh:
			json.dump(diagnostics_data, fh, indent=2)
		os.replace(tmp_path, path)
	except Exception:
		if os.path.exists(tmp_path):
			os.unlink(tmp_path)
		raise


#============================================

def load_intervals(path: str) -> dict:
	"""Load a solved-intervals JSON file and validate the header.

	Returns an empty intervals structure if the file does not exist.

	Args:
		path: Path to the solved-intervals JSON file.

	Returns:
		dict: Parsed intervals data with validated header, or empty structure.

	Raises:
		RuntimeError: If the file exists but header version is wrong.
	"""
	# return empty structure if file does not exist
	if not os.path.isfile(path):
		return {INTERVALS_HEADER_KEY: INTERVALS_HEADER_VALUE, "solved_intervals": {}}
	with open(path, "r") as fh:
		data = json.load(fh)
	if not isinstance(data, dict):
		raise RuntimeError(f"intervals file did not parse as a mapping: {path}")
	# validate the header key and version
	header_val = data.get(INTERVALS_HEADER_KEY)
	if header_val != INTERVALS_HEADER_VALUE:
		raise RuntimeError(
			f"intervals file header mismatch in {path}: "
			f"expected {INTERVALS_HEADER_KEY}={INTERVALS_HEADER_VALUE}, got {header_val}"
		)
	return data


#============================================

def write_intervals(path: str, intervals_data: dict) -> None:
	"""Write solved-intervals data to a JSON file.

	Ensures the required header key is present before writing.

	Args:
		path: Output file path.
		intervals_data: Intervals dictionary to write.
	"""
	# ensure header version is set correctly before writing
	intervals_data[INTERVALS_HEADER_KEY] = INTERVALS_HEADER_VALUE
	# atomic write: temp file + rename to avoid corrupt file on interruption
	dir_path = os.path.dirname(os.path.abspath(path))
	fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp.json")
	try:
		with os.fdopen(fd, "w") as fh:
			json.dump(intervals_data, fh, indent=2)
		os.replace(tmp_path, path)
	except Exception:
		if os.path.exists(tmp_path):
			os.unlink(tmp_path)
		raise


#============================================

def interval_fingerprint(seed_start: dict, seed_end: dict) -> str:
	"""Compute a deterministic lookup key from two seed endpoint states.

	The fingerprint encodes frame_index and position (cx, cy, w, h rounded
	to 2 decimal places) for both seeds. Any change in seed position or
	frame index produces a different key, so stale results are never reused.

	Args:
		seed_start: Seed state dict at the start of the interval.
		seed_end: Seed state dict at the end of the interval.

	Returns:
		String fingerprint like "100|1731.50|629.50|39.00|59.00|450|1700.00|600.00|38.00|58.00".
	"""
	parts = []
	for seed in (seed_start, seed_end):
		fi = int(seed["frame_index"])
		cx = round(float(seed["cx"]), 2)
		cy = round(float(seed["cy"]), 2)
		w = round(float(seed["w"]), 2)
		h = round(float(seed["h"]), 2)
		parts.append(f"{fi}|{cx:.2f}|{cy:.2f}|{w:.2f}|{h:.2f}")
	fingerprint = "|".join(parts)
	return fingerprint


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
		score = iv["interval_score"]
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
	# preserve video_identity if provided in the input diagnostics
	video_identity = diagnostics.get("video_identity")
	if video_identity is not None:
		diag_out["video_identity"] = video_identity
	write_diagnostics(path, diag_out)


#============================================

# round-trip self-check for load/write pairs
if __name__ == "__main__":
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

	# test solved-intervals round-trip
	intervals_data = {
		"solved_intervals": {
			"100|1731.50|629.50|39.00|59.00|450|1700.00|600.00|38.00|58.00": {
				"start_frame": 100,
				"end_frame": 450,
				"fused_track": [{"cx": 100.0, "cy": 200.0}],
			},
		},
	}
	with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
		tmp_path = tmp.name
	write_intervals(tmp_path, intervals_data)
	loaded_iv = load_intervals(tmp_path)
	assert loaded_iv[INTERVALS_HEADER_KEY] == INTERVALS_HEADER_VALUE
	assert len(loaded_iv["solved_intervals"]) == 1
	os.unlink(tmp_path)

	# test interval_fingerprint determinism
	seed_a = {"frame_index": 100, "cx": 1731.5, "cy": 629.5, "w": 39.0, "h": 59.0}
	seed_b = {"frame_index": 450, "cx": 1700.0, "cy": 600.0, "w": 38.0, "h": 58.0}
	fp = interval_fingerprint(seed_a, seed_b)
	assert fp == "100|1731.50|629.50|39.00|59.00|450|1700.00|600.00|38.00|58.00"
	# same inputs must produce same fingerprint
	fp2 = interval_fingerprint(seed_a, seed_b)
	assert fp == fp2

	print("all round-trip checks passed")
