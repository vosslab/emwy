#!/usr/bin/env python3

"""
Pytest coverage for the stabilize_building tool.
"""

# Standard Library
import json
import os
import shutil
import subprocess
import sys
import tempfile

# PIP3 modules
import pytest
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

#============================================

AV_TOOLS = ("ffmpeg", "ffprobe")
MISSING_AV_TOOLS = [tool for tool in AV_TOOLS if shutil.which(tool) is None]
HAVE_AV_TOOLS = len(MISSING_AV_TOOLS) == 0
SKIP_AV_REASON = f"missing tools: {', '.join(MISSING_AV_TOOLS)}"

#============================================

def _run(cmd: list[str], cwd: str | None = None, ok: bool = True) -> subprocess.CompletedProcess:
	proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
	if ok and proc.returncode != 0:
		raise RuntimeError(f"command failed: {cmd}\n{proc.stderr.strip()}")
	return proc

#============================================

def _have_vidstab_filters() -> bool:
	if not HAVE_AV_TOOLS:
		return False
	proc = _run(["ffmpeg", "-hide_banner", "-filters"], ok=True)
	return ("vidstabdetect" in proc.stdout) and ("vidstabtransform" in proc.stdout)

#============================================

def _make_shaky_clip(path: str) -> None:
	"""
	Generate a tiny shaky video clip (synthetic) for vid.stab testing.
	"""
	_run([
		"ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
		"-f", "lavfi", "-i", "testsrc=size=320x240:rate=30",
		"-t", "2",
		"-vf", "crop=iw-40:ih-40:x=20+10*sin(2*PI*t):y=20+10*cos(2*PI*t),pad=320:240:20:20:black",
		"-pix_fmt", "yuv420p",
		path,
	])
	return

#============================================

def _make_single_jerk_clip(path: str) -> None:
	"""
	Generate a tiny shaky clip with a single large jerk on one frame.
	"""
	_run([
		"ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
		"-f", "lavfi", "-i", "testsrc=size=320x240:rate=30",
		"-t", "2",
		"-vf", "crop=iw-40:ih-40:x=20+if(eq(n\\,30)\\,80\\,0):y=20,pad=320:240:20:20:black",
		"-pix_fmt", "yuv420p",
		path,
	])
	return

#============================================

def _probe_wh(path: str) -> tuple[int, int]:
	proc = _run([
		"ffprobe", "-v", "error",
		"-select_streams", "v:0",
		"-show_entries", "stream=width,height",
		"-of", "json",
		path,
	])
	data = json.loads(proc.stdout)
	stream = data["streams"][0]
	return int(stream["width"]), int(stream["height"])

#============================================

@pytest.mark.skipif(not HAVE_AV_TOOLS, reason=SKIP_AV_REASON)
def test_stabilize_building_smoke_success() -> None:
	if not _have_vidstab_filters():
		pytest.skip("ffmpeg missing vid.stab filters")
	with tempfile.TemporaryDirectory(prefix="stabilize-build-test-") as temp_dir:
		input_path = os.path.join(temp_dir, "shaky.mp4")
		_make_shaky_clip(input_path)
		output_path = os.path.join(temp_dir, "out.mkv")
		default_config_path = f"{input_path}.stabilize_building.config.yaml"
		assert not os.path.exists(default_config_path)
		config_path = os.path.join(temp_dir, "config.yaml")
		cache_dir = os.path.join(temp_dir, "cache")
		lines = []
		lines.append("stabilize_building: 1")
		lines.append("settings:")
		lines.append("  engine:")
		lines.append("    kind: vidstab")
		lines.append("    detect:")
		lines.append("      shakiness: 5")
		lines.append("      accuracy: 15")
		lines.append("      stepsize: 6")
		lines.append("      mincontrast: 0.25")
		lines.append("      reference_frame: 1")
		lines.append("    transform:")
		lines.append("      optalgo: opt")
		lines.append("      smoothing: 0")
		lines.append("  crop:")
		lines.append("    min_area_ratio: 0.05")
		lines.append("    min_height_px: 80")
		lines.append("    center_safe_margin: 0.10")
		lines.append("  border:")
		lines.append("    mode: crop_only")
		lines.append("  rejection:")
		lines.append("    max_missing_fraction: 0.0")
		lines.append("    max_mad_fraction: 0.75")
		lines.append("    max_scale_jump: 0.50")
		lines.append("    max_abs_angle_rad: 1.0")
		lines.append("    max_abs_zoom_percent: 10.0")
		lines.append("  io:")
		lines.append(f"    cache_dir: \"{cache_dir}\"")
		lines.append("    report_format: yaml")
		lines.append("")
		with open(config_path, "w", encoding="utf-8") as handle:
			handle.write("\n".join(lines))
		tool_path = os.path.join(REPO_ROOT, "tools", "stabilize_building.py")
		proc = _run([
			sys.executable,
			tool_path,
			"-i", input_path,
			"-o", output_path,
			"-c", config_path,
			"--duration", "2",
		], ok=True)
		assert proc.returncode == 0
		assert os.path.isfile(output_path)
		report_path = f"{output_path}.stabilize_building.report.yaml"
		assert os.path.isfile(report_path)
		with open(report_path, "r", encoding="utf-8") as handle:
			report = yaml.safe_load(handle)
		assert report["result"]["pass"] is True
		assert report["result"]["mode"] == "crop_only"
		crop = report["crop"]["rect"]
		assert crop["w"] > 0
		assert crop["h"] > 0
		in_w, in_h = _probe_wh(input_path)
		out_w, out_h = _probe_wh(output_path)
		assert (in_w, in_h) == (out_w, out_h)
	return

#============================================

@pytest.mark.skipif(not HAVE_AV_TOOLS, reason=SKIP_AV_REASON)
def test_stabilize_building_no_config_uses_code_defaults() -> None:
	if not _have_vidstab_filters():
		pytest.skip("ffmpeg missing vid.stab filters")
	with tempfile.TemporaryDirectory(prefix="stabilize-build-test-") as temp_dir:
		input_path = os.path.join(temp_dir, "shaky.mp4")
		_make_shaky_clip(input_path)
		output_path = os.path.join(temp_dir, "out.mkv")
		default_config_path = f"{input_path}.stabilize_building.config.yaml"
		assert not os.path.exists(default_config_path)
		tool_path = os.path.join(REPO_ROOT, "tools", "stabilize_building.py")
		proc = _run([
			sys.executable,
			tool_path,
			"-i", input_path,
			"-o", output_path,
			"--duration", "2",
		], ok=True)
		assert proc.returncode == 0
		assert os.path.isfile(output_path)
		assert not os.path.exists(default_config_path)
		report_path = f"{output_path}.stabilize_building.report.yaml"
		assert os.path.isfile(report_path)
		with open(report_path, "r", encoding="utf-8") as handle:
			report = yaml.safe_load(handle)
		assert report["config_source"] == "code_defaults"
		assert report["config_path"] is None
	return

#============================================

@pytest.mark.skipif(not HAVE_AV_TOOLS, reason=SKIP_AV_REASON)
def test_stabilize_building_fails_on_strict_crop() -> None:
	if not _have_vidstab_filters():
		pytest.skip("ffmpeg missing vid.stab filters")
	with tempfile.TemporaryDirectory(prefix="stabilize-build-test-") as temp_dir:
		input_path = os.path.join(temp_dir, "shaky.mp4")
		_make_shaky_clip(input_path)
		output_path = os.path.join(temp_dir, "out.mkv")
		config_path = os.path.join(temp_dir, "config.yaml")
		cache_dir = os.path.join(temp_dir, "cache")
		lines = []
		lines.append("stabilize_building: 1")
		lines.append("settings:")
		lines.append("  engine:")
		lines.append("    kind: vidstab")
		lines.append("    detect:")
		lines.append("      shakiness: 5")
		lines.append("      accuracy: 15")
		lines.append("      stepsize: 6")
		lines.append("      mincontrast: 0.25")
		lines.append("      reference_frame: 1")
		lines.append("    transform:")
		lines.append("      optalgo: opt")
		lines.append("      smoothing: 0")
		lines.append("  crop:")
		lines.append("    min_area_ratio: 0.99")
		lines.append("    min_height_px: 200")
		lines.append("    center_safe_margin: 0.10")
		lines.append("  border:")
		lines.append("    mode: crop_only")
		lines.append("  rejection:")
		lines.append("    max_missing_fraction: 0.0")
		lines.append("    max_mad_fraction: 0.75")
		lines.append("    max_scale_jump: 0.50")
		lines.append("    max_abs_angle_rad: 1.0")
		lines.append("    max_abs_zoom_percent: 10.0")
		lines.append("  io:")
		lines.append(f"    cache_dir: \"{cache_dir}\"")
		lines.append("    report_format: yaml")
		lines.append("")
		with open(config_path, "w", encoding="utf-8") as handle:
			handle.write("\n".join(lines))
		tool_path = os.path.join(REPO_ROOT, "tools", "stabilize_building.py")
		proc = _run([
			sys.executable,
			tool_path,
			"-i", input_path,
			"-o", output_path,
			"-c", config_path,
			"--duration", "2",
		], ok=False)
		assert proc.returncode != 0
		report_path = f"{output_path}.stabilize_building.report.yaml"
		assert os.path.isfile(report_path)
		with open(report_path, "r", encoding="utf-8") as handle:
			report = yaml.safe_load(handle)
		assert report["result"]["pass"] is False
	return

#============================================

@pytest.mark.skipif(not HAVE_AV_TOOLS, reason=SKIP_AV_REASON)
def test_stabilize_building_fill_fallback_succeeds() -> None:
	if not _have_vidstab_filters():
		pytest.skip("ffmpeg missing vid.stab filters")
	with tempfile.TemporaryDirectory(prefix="stabilize-build-test-") as temp_dir:
		input_path = os.path.join(temp_dir, "jerk.mp4")
		_make_single_jerk_clip(input_path)
		output_path = os.path.join(temp_dir, "out.mkv")
		config_path = os.path.join(temp_dir, "config.yaml")
		cache_dir = os.path.join(temp_dir, "cache")
		lines = []
		lines.append("stabilize_building: 1")
		lines.append("settings:")
		lines.append("  engine:")
		lines.append("    kind: vidstab")
		lines.append("    detect:")
		lines.append("      shakiness: 5")
		lines.append("      accuracy: 15")
		lines.append("      stepsize: 6")
		lines.append("      mincontrast: 0.25")
		lines.append("      reference_frame: 1")
		lines.append("    transform:")
		lines.append("      optalgo: opt")
		lines.append("      smoothing: 0")
		lines.append("  crop:")
		lines.append("    min_area_ratio: 0.90")
		lines.append("    min_height_px: 200")
		lines.append("    center_safe_margin: 0.10")
		lines.append("  border:")
		lines.append("    mode: crop_prefer_fill_fallback")
		lines.append("    fill:")
		lines.append("      kind: center_patch_median")
		lines.append("      patch_fraction: 0.10")
		lines.append("      sample_frames: 3")
		lines.append("      max_area_ratio: 0.40")
		lines.append("      max_frames_ratio: 0.10")
		lines.append("      max_consecutive_frames: 1")
		lines.append("  rejection:")
		lines.append("    max_missing_fraction: 0.0")
		lines.append("    max_mad_fraction: 1.0")
		lines.append("    max_scale_jump: 1.0")
		lines.append("    max_abs_angle_rad: 3.14")
		lines.append("    max_abs_zoom_percent: 100.0")
		lines.append("  io:")
		lines.append(f"    cache_dir: \"{cache_dir}\"")
		lines.append("    report_format: yaml")
		lines.append("")
		with open(config_path, "w", encoding="utf-8") as handle:
			handle.write("\n".join(lines))
		tool_path = os.path.join(REPO_ROOT, "tools", "stabilize_building.py")
		proc = _run([
			sys.executable,
			tool_path,
			"-i", input_path,
			"-o", output_path,
			"-c", config_path,
			"--duration", "2",
		], ok=True)
		assert proc.returncode == 0
		assert os.path.isfile(output_path)
		report_path = f"{output_path}.stabilize_building.report.yaml"
		assert os.path.isfile(report_path)
		with open(report_path, "r", encoding="utf-8") as handle:
			report = yaml.safe_load(handle)
		assert report["result"]["pass"] is True
		assert report["result"]["mode"] == "fill_fallback"
		assert "fill_color" in report["border"]
	return
