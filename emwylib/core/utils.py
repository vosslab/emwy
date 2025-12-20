#!/usr/bin/env python3

import os
import re
import subprocess
import time
from decimal import Decimal
from fractions import Fraction

#============================================

def runCmd(cmd: str) -> None:
	showcmd = cmd.strip()
	showcmd = re.sub("  *", " ", showcmd)
	print(f"CMD: '{showcmd}'")
	proc = subprocess.Popen(showcmd, shell=True, stderr=subprocess.PIPE,
		stdout=subprocess.PIPE)
	proc.communicate()
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
