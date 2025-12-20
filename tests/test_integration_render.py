#!/usr/bin/env python3

"""
Integration tests for the render pipeline.
"""

# Standard Library
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import PIL.Image

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

from emwylib.core.project import EmwyProject

#============================================

REQUIRED_TOOLS = ("ffmpeg", "ffprobe", "mkvmerge")
MISSING_TOOLS = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
HAVE_TOOLS = len(MISSING_TOOLS) == 0
SKIP_TOOLS_REASON = f"missing tools: {', '.join(MISSING_TOOLS)}"

EXTRA_TOOLS = ("sox",)
MISSING_EXTRA = [tool for tool in EXTRA_TOOLS if shutil.which(tool) is None]
HAVE_EXTRA_TOOLS = len(MISSING_EXTRA) == 0
SKIP_SILENCE_REASON = "missing tools or deps: "
SKIP_SILENCE_REASON += ", ".join(MISSING_TOOLS + MISSING_EXTRA)

#============================================

def _run(cmd: str) -> None:
	subprocess.run(cmd, shell=True, check=True,
		stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

#============================================

def _write_yaml(path: str, asset_path: str, output_path: str) -> None:
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
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	lines.append("    - source: {asset: source, in: \"00:00.0\", out: \"00:01.0\"}")
	lines.append("    - source: {asset: source, in: \"00:01.0\", out: \"00:02.0\"}")
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: \"{output_path}\"")
	with open(path, "w") as handle:
		handle.write("\n".join(lines))
		handle.write("\n")

#============================================

def _probe_stream_types(path: str) -> set:
	cmd = f"ffprobe -v error -show_entries stream=codec_type -of json \"{path}\""
	payload = subprocess.check_output(cmd, shell=True).decode("utf-8")
	data = json.loads(payload)
	return {stream.get("codec_type") for stream in data.get("streams", [])}

#============================================

def _probe_duration(path: str) -> float:
	cmd = f"ffprobe -v error -show_entries format=duration -of json \"{path}\""
	payload = subprocess.check_output(cmd, shell=True).decode("utf-8")
	data = json.loads(payload)
	duration = data.get("format", {}).get("duration")
	return float(duration) if duration is not None else 0.0

#============================================

@unittest.skipUnless(HAVE_TOOLS, SKIP_TOOLS_REASON)
class RenderIntegrationTest(unittest.TestCase):
	#============================================
	def test_render_two_segments_av(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			source_path = os.path.join(temp_dir, "source.mp4")
			output_path = os.path.join(temp_dir, "out.mkv")
			yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
			cmd = (
				"ffmpeg -y "
				"-f lavfi -i testsrc=size=320x240:rate=25 "
				"-f lavfi -i sine=frequency=1000:sample_rate=48000 "
				"-t 2 -shortest "
				"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
				"-c:a aac -ac 1 "
				f"\"{source_path}\""
			)
			_run(cmd)
			_write_yaml(yaml_path, source_path, output_path)
			project = EmwyProject(yaml_path)
			project.run()
			self.assertTrue(os.path.exists(output_path))
			stream_types = _probe_stream_types(output_path)
			self.assertIn("video", stream_types)
			self.assertIn("audio", stream_types)
			duration = _probe_duration(output_path)
			self.assertGreater(duration, 1.8)
			self.assertLess(duration, 2.2)

	#============================================
	def test_render_chapter_card_image(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			background_path = os.path.join(temp_dir, "chapter_bg.png")
			output_path = os.path.join(temp_dir, "card.mkv")
			yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
			image = PIL.Image.new("RGB", (640, 360), color=(12, 18, 24))
			image.save(background_path)
			lines = []
			lines.append("emwy: 2")
			lines.append("")
			lines.append("profile:")
			lines.append("  fps: 25")
			lines.append("  resolution: [320, 240]")
			lines.append("  audio: {sample_rate: 48000, channels: mono}")
			lines.append("")
			lines.append("assets:")
			lines.append("  image:")
			lines.append(f"    chapter_bg: {{file: \"{background_path}\"}}")
			lines.append("  cards:")
			lines.append("    chapter_style:")
			lines.append("      kind: chapter_card_style")
			lines.append("      font_size: 48")
			lines.append("      text_color: \"#ffffff\"")
			lines.append("      background: {kind: image, asset: chapter_bg}")
			lines.append("")
			lines.append("timeline:")
			lines.append("  segments:")
			lines.append("    - generator:")
			lines.append("        kind: chapter_card")
			lines.append("        title: \"Chapter 1\"")
			lines.append("        duration: \"00:02.0\"")
			lines.append("        style: chapter_style")
			lines.append("        fill_missing: {audio: silence}")
			lines.append("")
			lines.append("output:")
			lines.append(f"  file: \"{output_path}\"")
			with open(yaml_path, "w") as handle:
				handle.write("\n".join(lines))
				handle.write("\n")
			project = EmwyProject(yaml_path)
			project.run()
			self.assertTrue(os.path.exists(output_path))
			stream_types = _probe_stream_types(output_path)
			self.assertIn("video", stream_types)
			self.assertIn("audio", stream_types)
			duration = _probe_duration(output_path)
			self.assertGreater(duration, 1.8)
			self.assertLess(duration, 2.2)

	#============================================
	def test_render_title_card_gradient(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			output_path = os.path.join(temp_dir, "titlecard.mkv")
			yaml_path = os.path.join(temp_dir, "project.emwy.yaml")
			lines = []
			lines.append("emwy: 2")
			lines.append("")
			lines.append("profile:")
			lines.append("  fps: 25")
			lines.append("  resolution: [320, 240]")
			lines.append("  audio: {sample_rate: 48000, channels: mono}")
			lines.append("")
			lines.append("assets:")
			lines.append("  cards:")
			lines.append("    title_style:")
			lines.append("      kind: chapter_card_style")
			lines.append("      font_size: 48")
			lines.append("      text_color: \"#ffffff\"")
			lines.append("      background:")
			lines.append("        kind: gradient")
			lines.append("        from: \"#101820\"")
			lines.append("        to: \"#2b5876\"")
			lines.append("        direction: vertical")
			lines.append("")
			lines.append("timeline:")
			lines.append("  segments:")
			lines.append("    - generator:")
			lines.append("        kind: title_card")
			lines.append("        title: \"Welcome\"")
			lines.append("        duration: \"00:02.0\"")
			lines.append("        style: title_style")
			lines.append("        fill_missing: {audio: silence}")
			lines.append("")
			lines.append("output:")
			lines.append(f"  file: \"{output_path}\"")
			with open(yaml_path, "w") as handle:
				handle.write("\n".join(lines))
				handle.write("\n")
			project = EmwyProject(yaml_path)
			project.run()
			self.assertTrue(os.path.exists(output_path))
			stream_types = _probe_stream_types(output_path)
			self.assertIn("video", stream_types)
			self.assertIn("audio", stream_types)
			duration = _probe_duration(output_path)
			self.assertGreater(duration, 1.8)
			self.assertLess(duration, 2.2)

#============================================

@unittest.skipUnless(HAVE_TOOLS and HAVE_EXTRA_TOOLS, SKIP_SILENCE_REASON)
class SilenceAnnotatorIntegrationTest(unittest.TestCase):
	#============================================
	def test_silence_annotator_roundtrip(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			source_path = os.path.join(temp_dir, "source.mp4")
			cmd = (
				"ffmpeg -y "
				"-f lavfi -i testsrc=size=320x240:rate=25 "
				"-f lavfi -i sine=frequency=1000:sample_rate=48000 "
				"-t 2 -shortest "
				"-filter:a \"volume=0:enable='between(t,0,1)'\" "
				"-c:v libx264 -preset ultrafast -crf 30 -pix_fmt yuv420p "
				"-c:a aac -ac 1 "
				f"\"{source_path}\""
			)
			_run(cmd)
			annotator = os.path.join(REPO_ROOT, "tools", "silence_annotator.py")
			cmd = (
				f"\"{sys.executable}\" \"{annotator}\" "
				f"-i \"{source_path}\" -s 0.5 -m 0.5 -S 4 -C 1"
			)
			_run(cmd)
			yaml_path = f"{source_path}.emwy.yaml"
			self.assertTrue(os.path.exists(yaml_path))
			project = EmwyProject(yaml_path)
			project.run()
			self.assertTrue(os.path.exists(project.output["file"]))
			duration = _probe_duration(project.output["file"])
			self.assertGreater(duration, 1.0)
			self.assertLess(duration, 1.6)

#============================================

def main() -> None:
	"""Run the unit tests."""
	unittest.main()

#============================================

if __name__ == "__main__":
	main()
