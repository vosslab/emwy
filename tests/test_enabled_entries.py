#!/usr/bin/env python3

import os
import sys
import tempfile
import unittest
from decimal import Decimal

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

from emwylib.core import utils
from emwylib.core.loader import ProjectLoader

#============================================

def _write_project_yaml(path: str, asset_path: str, output_path: str) -> None:
	"""Write a minimal v2 project with one disabled entry.

	Args:
		path: YAML output path.
		asset_path: Media asset path.
		output_path: Output file path.
	"""
	lines = []
	lines.append("emwy: 2")
	lines.append("")
	lines.append("profile:")
	lines.append("  fps: 30")
	lines.append("  resolution: [1920, 1080]")
	lines.append("  audio: {sample_rate: 48000, channels: stereo}")
	lines.append("")
	lines.append("assets:")
	lines.append("  video:")
	lines.append(f"    clip: {{file: \"{asset_path}\"}}")
	lines.append("")
	lines.append("timeline:")
	lines.append("  segments:")
	lines.append(
		"    - source: {asset: clip, in: \"00:00.0\", out: \"00:01.0\", "
		"enabled: false}"
	)
	lines.append("    - source: {asset: clip, in: \"00:01.0\", out: \"00:03.0\"}")
	lines.append("")
	lines.append("output:")
	lines.append(f"  file: \"{output_path}\"")
	with open(path, "w") as yaml_file:
		yaml_file.write("\n".join(lines))
		yaml_file.write("\n")

#============================================

class EnabledEntriesTest(unittest.TestCase):
	#============================================
	def test_disabled_entries_are_skipped(self) -> None:
		"""Ensure disabled entries do not affect playlist timing."""
		with tempfile.TemporaryDirectory() as temp_dir:
			asset_path = os.path.join(temp_dir, "clip.mkv")
			output_path = os.path.join(temp_dir, "out.mkv")
			yaml_path = os.path.join(temp_dir, "project.yaml")
			with open(asset_path, "w") as asset_file:
				asset_file.write("")
			_write_project_yaml(yaml_path, asset_path, output_path)
			project = ProjectLoader(yaml_path).load()
			video_playlist = project.playlists["video_base"]
			audio_playlist = project.playlists["audio_main"]
			self.assertEqual(len(video_playlist["entries"]), 1)
			self.assertEqual(len(audio_playlist["entries"]), 1)
			expected_frames = utils.frames_from_seconds(
				Decimal("2.0"),
				project.profile["fps"]
			)
			self.assertEqual(video_playlist["duration_frames"], expected_frames)
			self.assertEqual(audio_playlist["duration_frames"], expected_frames)

#============================================

def main() -> None:
	"""Run the unit tests."""
	unittest.main()

#============================================

if __name__ == "__main__":
	main()
