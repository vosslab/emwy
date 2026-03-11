"""
tools_common.py

Shared utility functions for emwy tools.
Consolidates duplicated helpers from silence_annotator, stabilize_building,
and track_runner.
"""

# Standard Library
import json
import os
import shlex
import shutil
import subprocess

#============================================

def ensure_file_exists(filepath: str) -> None:
	"""
	Ensure a file exists.

	Args:
		filepath: File path to verify.
	"""
	if not os.path.isfile(filepath):
		raise RuntimeError(f"file not found: {filepath}")
	return

#============================================

def check_dependency(cmd_name: str) -> None:
	"""
	Ensure a required external command exists.

	Args:
		cmd_name: Command to locate.
	"""
	if shutil.which(cmd_name) is None:
		raise RuntimeError(f"missing dependency: {cmd_name}")
	return

#============================================

def run_process(cmd: list, cwd: str | None = None,
	capture_output: bool = True) -> subprocess.CompletedProcess:
	"""
	Run a subprocess command.

	Args:
		cmd: Command list to execute.
		cwd: Working directory.
		capture_output: Capture stdout and stderr when True.

	Returns:
		subprocess.CompletedProcess: Completed process.
	"""
	showcmd = shlex.join(cmd)
	print(f"CMD: '{showcmd}'")
	proc = subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=True)
	if proc.returncode != 0:
		stderr_text = proc.stderr.strip()
		raise RuntimeError(f"command failed: {showcmd}\n{stderr_text}")
	return proc

#============================================

def parse_time_seconds(value: str | None) -> float | None:
	"""
	Parse a time value into seconds.

	Args:
		value: None, seconds string, or HH:MM:SS[.ms].

	Returns:
		float | None: Parsed seconds.
	"""
	if value is None:
		return None
	text = str(value).strip()
	if text == "":
		return None
	if ":" not in text:
		return float(text)
	parts = text.split(":")
	if len(parts) != 3:
		raise RuntimeError("time must be seconds or HH:MM:SS[.ms]")
	hours = float(parts[0])
	minutes = float(parts[1])
	seconds = float(parts[2])
	if hours < 0 or minutes < 0 or seconds < 0:
		raise RuntimeError("time components must be non-negative")
	return hours * 3600.0 + minutes * 60.0 + seconds

#============================================

def fps_fraction_to_float(value: str) -> float:
	"""
	Convert an ffprobe frame-rate fraction string to float.

	Args:
		value: Fraction string like "30000/1001" or "30/1".

	Returns:
		float: FPS value.
	"""
	text = str(value).strip()
	if "/" in text:
		num_text, den_text = text.split("/", 1)
		num = float(num_text)
		den = float(den_text)
		if den == 0:
			raise RuntimeError("invalid fps denominator")
		return num / den
	return float(text)

#============================================

def probe_video_stream(input_file: str) -> dict:
	"""
	Probe video stream metadata using ffprobe.

	Args:
		input_file: Media file path.

	Returns:
		dict: Video metadata fields.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-select_streams", "v:0",
		"-show_entries",
		"stream=width,height,r_frame_rate,avg_frame_rate,pix_fmt",
		"-of", "json",
		input_file,
	]
	proc = run_process(cmd, capture_output=True)
	data = json.loads(proc.stdout)
	streams = data.get("streams", [])
	if len(streams) == 0:
		raise RuntimeError("no video stream found for metadata")
	stream = streams[0]
	width = int(stream.get("width", 0))
	height = int(stream.get("height", 0))
	if width <= 0 or height <= 0:
		raise RuntimeError("invalid video resolution from ffprobe")
	# prefer r_frame_rate, fall back to avg_frame_rate
	fps_value = stream.get("r_frame_rate")
	if fps_value is None or fps_value == "0/0":
		fps_value = stream.get("avg_frame_rate")
	if fps_value is None or fps_value == "0/0":
		raise RuntimeError("invalid frame rate from ffprobe")
	result = {
		"width": width,
		"height": height,
		"fps_fraction": fps_value,
		"fps": fps_fraction_to_float(fps_value),
		"pix_fmt": stream.get("pix_fmt", "yuv420p"),
	}
	return result

#============================================

def probe_duration_seconds(input_file: str) -> float:
	"""
	Probe media duration in seconds using ffprobe.

	Args:
		input_file: Media file path.

	Returns:
		float: Duration in seconds.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-show_entries", "format=duration",
		"-of", "default=nw=1:nk=1",
		input_file,
	]
	proc = run_process(cmd, capture_output=True)
	text = proc.stdout.strip()
	if text == "":
		raise RuntimeError("ffprobe did not return duration")
	seconds = float(text)
	if seconds <= 0:
		raise RuntimeError("ffprobe returned non-positive duration")
	return seconds
