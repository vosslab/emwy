#!/usr/bin/env python3

"""
Pytest coverage for overlay ffmpeg behavior.
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

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# local repo modules
from emwylib.core.project import EmwyProject
from emwylib.core import utils

#============================================

REQUIRED_TOOLS = ("ffmpeg", "ffprobe", "mkvmerge")
MISSING_TOOLS = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
HAVE_TOOLS = len(MISSING_TOOLS) == 0
SKIP_TOOLS_REASON = f"missing tools: {', '.join(MISSING_TOOLS)}"

#============================================

def _run(cmd: str) -> None:
	"""
	Run a shell command, raising on failure.
	"""
	subprocess.run(cmd, shell=True, check=True,
		stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

#============================================

def _write_overlay_yaml(path: str, asset_path: str, output_path: str) -> None:
	"""
	Write a minimal overlay project yaml.
	"""
	lines = []
	lines.append("emwy: 2")
	lines.append("")
	lines.append("profile:")
	lines.append("  fps: 25")
	lines.append("  resolution: [320, 240]")
	lines.append("  audio: {sample_rate: 48000, channels: mono}")
	lines.append("")
	lines.append("assets:")
	lines.append("  video:")
	lines.append(f"    source: {{file: \"{asset_path}\"}}")
	lines.append("  overlay_text_styles:")
	lines.append("    label_style:")
	lines.append("      kind: overlay_text_style")
	lines.append("      font_size: 32")
	lines.append("      text_color: \"#ffffff\"")
	lines.append("      background: {kind: transparent}")
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	lines.append("    - source: {asset: source, in: \"00:00.0\", out: \"00:01.0\"}")
	lines.append("  overlays:")
	lines.append("    - id: label")
	lines.append("      geometry: [0.1, 0.1, 0.8, 0.2]")
	lines.append("      opacity: 0.9")
	lines.append("      segments:")
	lines.append("        - generator:")
	lines.append("            kind: overlay_text")
	lines.append("            text: \"Overlay\"")
	lines.append("            duration: \"00:01.0\"")
	lines.append("            style: label_style")
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: \"{output_path}\"")
	with open(path, "w") as handle:
		handle.write("\n".join(lines))
		handle.write("\n")

#============================================

def _probe_stream_types(path: str) -> set:
	"""
	Return stream types (video/audio/etc) from ffprobe.
	"""
	cmd = f"ffprobe -v error -show_entries stream=codec_type -of json \"{path}\""
	payload = subprocess.check_output(cmd, shell=True).decode("utf-8")
	data = json.loads(payload)
	return {stream.get("codec_type") for stream in data.get("streams", [])}

#============================================

def _probe_pix_fmt(path: str) -> str:
	"""
	Return the pixel format for the first video stream.
	"""
	cmd = (
		f"ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt "
		f"-of json \"{path}\""
	)
	payload = subprocess.check_output(cmd, shell=True).decode("utf-8")
	data = json.loads(payload)
	streams = data.get("streams", [])
	if len(streams) == 0:
		return None
	return streams[0].get("pix_fmt")

#============================================

@pytest.mark.skipif(not HAVE_TOOLS, reason=SKIP_TOOLS_REASON)
def test_overlay_render_smoke() -> None:
	"""
	Ensure overlays render and output includes audio/video streams.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		source_path = os.path.join(temp_dir, "source.mp4")
		output_path = os.path.join(temp_dir, "out.mkv")
		yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
		cmd = (
			"ffmpeg -y "
			"-f lavfi -i testsrc=size=320x240:rate=25 "
			"-f lavfi -i sine=frequency=1000:sample_rate=48000 "
			"-t 1 -shortest "
			"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
			"-c:a aac -ac 1 "
			f"\"{source_path}\""
		)
		_run(cmd)
		_write_overlay_yaml(yaml_path, source_path, output_path)
		project = EmwyProject(yaml_path)
		project.run()
		assert os.path.exists(output_path)
		stream_types = _probe_stream_types(output_path)
		assert "video" in stream_types
		assert "audio" in stream_types

#============================================

@pytest.mark.skipif(not HAVE_TOOLS, reason=SKIP_TOOLS_REASON)
def test_overlay_track_pixel_format() -> None:
	"""
	Ensure overlay tracks keep alpha-capable pixel formats.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		source_path = os.path.join(temp_dir, "source.mp4")
		output_path = os.path.join(temp_dir, "out.mkv")
		yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
		cmd = (
			"ffmpeg -y "
			"-f lavfi -i testsrc=size=320x240:rate=25 "
			"-f lavfi -i sine=frequency=1000:sample_rate=48000 "
			"-t 1 -shortest "
			"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
			"-c:a aac -ac 1 "
			f"\"{source_path}\""
		)
		_run(cmd)
		_write_overlay_yaml(yaml_path, source_path, output_path)
		project = EmwyProject(yaml_path, cache_dir=temp_dir, keep_temp=True)
		overlay_id = project.stack["overlays"][0]["b"]
		overlay_file = project._renderer._render_overlay_playlist(overlay_id, 1)
		assert os.path.exists(overlay_file)
		pix_fmt = _probe_pix_fmt(overlay_file)
		assert pix_fmt is not None
		assert "a" in pix_fmt

#============================================

def test_overlay_opacity_command_format(monkeypatch) -> None:
	"""
	Ensure overlay opacity uses numeric colorchannelmixer coefficients.
	"""
	with tempfile.TemporaryDirectory() as temp_dir:
		source_path = os.path.join(temp_dir, "source.mkv")
		output_path = os.path.join(temp_dir, "out.mkv")
		yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
		with open(source_path, "w") as handle:
			handle.write("")
		_write_overlay_yaml(yaml_path, source_path, output_path)
		project = EmwyProject(yaml_path, cache_dir=temp_dir, keep_temp=True)
		base_file = os.path.join(temp_dir, "base.mkv")
		overlay_file = os.path.join(temp_dir, "overlay.mkv")
		composite_file = os.path.join(temp_dir, "composite.mkv")
		for path in (base_file, overlay_file):
			with open(path, "w") as handle:
				handle.write("")
		captured = {}

		def _fake_run(cmd: str) -> None:
			"""
			Capture the command and create the output file.
			"""
			captured["cmd"] = cmd
			with open(composite_file, "w") as handle:
				handle.write("ok")

		monkeypatch.setattr(utils, "runCmd", _fake_run)
		overlay = {
			'geometry': [0.0, 0.0, 1.0, 1.0],
			'opacity': 0.75,
			'in_frames': 0,
			'out_frames': int(project.profile['fps']),
		}
		project._renderer._composite_overlay(base_file, overlay_file, composite_file, overlay)
		cmd = captured.get("cmd", "")
		assert "colorchannelmixer=aa=0.75" in cmd
		assert "aa=0.75*a" not in cmd

