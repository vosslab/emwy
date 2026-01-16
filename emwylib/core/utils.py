#!/usr/bin/env python3

import os
import re
import subprocess
import time
from decimal import Decimal
from fractions import Fraction

#============================================

_command_reporter = None
_quiet_mode = False
_command_total = None
_command_index = 0
_rich_console = None
_rich_highlighter = None

#============================================

def set_command_reporter(reporter) -> None:
	"""
	Register a callback for command events.
	"""
	global _command_reporter
	_command_reporter = reporter
	return

#============================================

def clear_command_reporter() -> None:
	"""
	Remove the command event callback.
	"""
	global _command_reporter
	_command_reporter = None
	return

#============================================

def set_quiet_mode(enabled: bool) -> None:
	"""
	Toggle quiet mode to suppress command prints.
	"""
	global _quiet_mode
	_quiet_mode = bool(enabled)
	return

#============================================

def is_quiet_mode() -> bool:
	return _quiet_mode

#============================================

def set_command_total(total) -> None:
	"""
	Set the expected total number of commands.
	"""
	global _command_total
	global _command_index
	if total is None:
		_command_total = None
		_command_index = 0
		return
	_command_total = int(total)
	_command_index = 0
	return

#============================================

def _next_command_index() -> int:
	global _command_index
	_command_index += 1
	return _command_index

#============================================

def _command_prefix(index: int, total) -> str:
	if total is None or total <= 0:
		return ""
	return f"CMD {index} of {total}"

#============================================

def command_prefix(index: int, total) -> str:
	"""
	Return a command prefix string for display.
	"""
	return _command_prefix(index, total)

#============================================

def _ensure_rich_printer() -> None:
	global _rich_console
	global _rich_highlighter
	if _rich_console is not None and _rich_highlighter is not None:
		return
	try:
		from rich.console import Console
		from rich.highlighter import RegexHighlighter
		from rich.theme import Theme
	except ImportError:
		return
	class CommandHighlighter(RegexHighlighter):
		highlights = [
			r"(?P<cmd_codec>\bpcm_s16le\b|\blibx265\b|\blibx264\b|\baac\b|\bffv1\b)",
			r"(?P<cmd_flag>--?[A-Za-z0-9][A-Za-z0-9_-]*)",
			r"(?P<cmd_float>\b\d+\.\d+\b)",
			r"(?P<cmd_int>\b\d+\b)(?!\.\d)",
			r"(?P<cmd_string>'[^']*'|\"[^\"]*\")",
			r"(?P<cmd_path>(?:/|~|\\./|\\.\\./)[^\\s'\"`]+)",
		]
	theme = Theme({
		"cmd_codec": "magenta",
		"cmd_flag": "bright_magenta",
		"cmd_float": "bright_blue",
		"cmd_int": "bright_blue",
		"cmd_string": "yellow",
		"cmd_path": "yellow",
	})
	_rich_console = Console(theme=theme)
	_rich_highlighter = CommandHighlighter()
	return

#============================================

def highlight_command(cmd: str):
	"""
	Return a rich Text renderable for a command when available.
	"""
	_ensure_rich_printer()
	if _rich_highlighter is None:
		return cmd
	return _rich_highlighter(cmd)

#============================================

def runCmd(cmd: str) -> None:
	showcmd = cmd.strip()
	showcmd = re.sub(r"\s+", " ", showcmd)
	start_time = time.time()
	index = _next_command_index()
	prefix = _command_prefix(index, _command_total)
	has_prefix = prefix != ""
	if _command_reporter is not None:
		_command_reporter({
			'event': 'start',
			'command': showcmd,
			'index': index,
			'total': _command_total,
		})
	elif not _quiet_mode:
		_ensure_rich_printer()
		if _rich_console is not None and _rich_highlighter is not None:
			if has_prefix:
				_rich_console.print("")
				_rich_console.print(prefix, style="bold cyan")
			_rich_console.print(_rich_highlighter(showcmd))
		else:
			if has_prefix:
				print("")
				print(prefix)
				print(showcmd)
			else:
				print(f"CMD: '{showcmd}'")
	try:
		proc = subprocess.Popen(showcmd, shell=True, stderr=subprocess.PIPE,
			stdout=subprocess.PIPE)
	except ValueError as exc:
		if "fds_to_keep" in str(exc):
			proc = subprocess.Popen(showcmd, shell=True, stderr=subprocess.PIPE,
				stdout=subprocess.PIPE, close_fds=False)
		else:
			raise
	stdout_data, stderr_data = proc.communicate()
	duration = time.time() - start_time
	if _command_reporter is not None:
		_command_reporter({
			'event': 'end',
			'command': showcmd,
			'returncode': proc.returncode,
			'seconds': duration,
			'index': index,
			'total': _command_total,
		})
	if proc.returncode != 0:
		error_text = ""
		if stderr_data:
			error_text = stderr_data.decode("utf-8", errors="replace").strip()
		if error_text == "" and stdout_data:
			error_text = stdout_data.decode("utf-8", errors="replace").strip()
		if error_text != "":
			raise RuntimeError(
				f"command failed ({proc.returncode}): {showcmd}\n"
				f"stderr: {error_text}"
			)
		raise RuntimeError(f"command failed ({proc.returncode}): {showcmd}")
	return

#============================================


#============================================

def parse_fps(raw_fps) -> Fraction:
	if raw_fps is None:
		raise RuntimeError("profile.fps is required")
	if isinstance(raw_fps, int):
		return Fraction(raw_fps, 1)
	if isinstance(raw_fps, float):
		return Fraction(str(raw_fps))
	if isinstance(raw_fps, str):
		if '/' in raw_fps:
			parts = raw_fps.split('/')
			return Fraction(int(parts[0]), int(parts[1]))
		return Fraction(raw_fps)
	raise RuntimeError("profile.fps must be int, float, or fraction string")

#============================================

def parse_timecode(raw_time) -> Decimal:
	if raw_time is None:
		raise RuntimeError("time value is required")
	if isinstance(raw_time, int):
		return Decimal(raw_time)
	if isinstance(raw_time, float):
		return Decimal(str(raw_time))
	if isinstance(raw_time, str):
		value = raw_time.strip()
		if value.endswith('@frame'):
			raise RuntimeError("frame override values are not supported yet")
		if ':' not in value:
			return Decimal(value)
		parts = value.split(':')
		seconds = Decimal(parts.pop())
		minutes = Decimal(parts.pop())
		hours = Decimal(0)
		if len(parts) > 0:
			hours = Decimal(parts.pop())
		return hours * Decimal(3600) + minutes * Decimal(60) + seconds
	raise RuntimeError("time values must be int, float, or timecode string")

#============================================

def round_half_up_fraction(value: Fraction) -> int:
	numerator = value.numerator
	denominator = value.denominator
	whole = numerator // denominator
	remainder = numerator - (whole * denominator)
	if remainder * 2 > denominator:
		return whole + 1
	if remainder * 2 == denominator:
		return whole + 1
	return whole

#============================================

def frames_from_seconds(seconds: Decimal, fps: Fraction) -> int:
	seconds_fraction = Fraction(str(seconds))
	frame_fraction = seconds_fraction * fps
	return round_half_up_fraction(frame_fraction)

#============================================

def seconds_from_frames(frames: int, fps: Fraction) -> float:
	seconds_fraction = Fraction(frames, 1) / fps
	return float(seconds_fraction)

#============================================

def decimal_to_fraction(value: Decimal) -> Fraction:
	return Fraction(str(value))

#============================================

def parse_speed(speed_value, default_speed: Decimal) -> Decimal:
	if speed_value is None:
		return default_speed
	if isinstance(speed_value, int):
		return Decimal(speed_value)
	if isinstance(speed_value, float):
		return Decimal(str(speed_value))
	return Decimal(str(speed_value))

#============================================

def normalize_channels(raw_channels) -> tuple:
	if raw_channels is None:
		return (2, 'stereo')
	channels = str(raw_channels).lower()
	if channels == 'mono':
		return (1, 'mono')
	if channels == 'stereo':
		return (2, 'stereo')
	raise RuntimeError("profile.audio.channels must be mono or stereo")

#============================================

def ensure_file_exists(filepath: str) -> None:
	if not os.path.exists(filepath):
		raise RuntimeError(f"file not found: {filepath}")
	return

#============================================

def make_timestamp() -> str:
	datestamp = time.strftime("%y%b%d").lower()
	uppercase = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	hourstamp = uppercase[(time.localtime()[3]) % 26]
	minstamp = f"{time.localtime()[4]:02d}"
	secstamp = uppercase[(time.localtime()[5]) % 26]
	timestamp = datestamp + hourstamp + minstamp + secstamp
	return timestamp
