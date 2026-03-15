"""tr_video_identity.py

Video identity fingerprinting for track_runner data files.

Builds a metadata-based identity block from video probe info and file
size, and compares stored identity against current video to detect
mismatches. Identity is heuristic (metadata-based, not content-hashed).
"""

# Standard Library
import os

#============================================

def make_video_identity(input_file: str, video_info: dict) -> dict:
	"""Build a video identity dict from file metadata and probe info.

	Args:
		input_file: Path to the input video file.
		video_info: Dict from _probe_video() with keys:
			width, height, fps, frame_count, duration_s.

	Returns:
		dict: Identity block with basename, size_bytes, width, height,
			fps, frame_count, duration_s.
	"""
	basename = os.path.basename(input_file)
	size_bytes = os.path.getsize(input_file)
	identity = {
		"basename": basename,
		"size_bytes": size_bytes,
		"width": video_info["width"],
		"height": video_info["height"],
		"fps": video_info["fps"],
		"frame_count": video_info["frame_count"],
		"duration_s": video_info["duration_s"],
	}
	return identity

#============================================

def compare_video_identity(stored: dict, current: dict) -> list:
	"""Compare stored video identity against current video identity.

	Returns a list of human-readable mismatch messages. An empty list
	means the identities match within tolerances.

	Comparison rules:
		- basename, width, height, size_bytes: exact match
		- fps: within 0.01
		- duration_s: within 0.5s
		- frame_count: exact match

	Args:
		stored: Identity dict from a previously saved data file.
		current: Identity dict from the current video.

	Returns:
		list: Mismatch message strings (empty if all fields match).
	"""
	mismatches = []
	# exact match fields
	for field in ("basename", "width", "height", "size_bytes"):
		stored_val = stored.get(field)
		current_val = current.get(field)
		if stored_val is None or current_val is None:
			continue
		if stored_val != current_val:
			msg = f"{field}: stored={stored_val}, current={current_val}"
			mismatches.append(msg)
	# fps: tolerant comparison within 0.01
	stored_fps = stored.get("fps")
	current_fps = current.get("fps")
	if stored_fps is not None and current_fps is not None:
		if abs(float(stored_fps) - float(current_fps)) > 0.01:
			msg = f"fps: stored={stored_fps}, current={current_fps}"
			mismatches.append(msg)
	# duration_s: tolerant comparison within 0.5s
	stored_dur = stored.get("duration_s")
	current_dur = current.get("duration_s")
	if stored_dur is not None and current_dur is not None:
		if abs(float(stored_dur) - float(current_dur)) > 0.5:
			msg = f"duration_s: stored={stored_dur}, current={current_dur}"
			mismatches.append(msg)
	# frame_count: exact match
	stored_fc = stored.get("frame_count")
	current_fc = current.get("frame_count")
	if stored_fc is not None and current_fc is not None:
		if int(stored_fc) != int(current_fc):
			msg = f"frame_count: stored={stored_fc}, current={current_fc}"
			mismatches.append(msg)
	return mismatches
