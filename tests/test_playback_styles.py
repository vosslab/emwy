
import os
import sys
import tempfile
import unittest
from decimal import Decimal

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

from emwylib.core.loader import ProjectLoader

#============================================

class PlaybackStyleTest(unittest.TestCase):
	#============================================
	def test_playback_style_applies_speed(self) -> None:
		"""Ensure playback style speed is applied to video and audio."""
		with tempfile.TemporaryDirectory() as temp_dir:
			asset_path = os.path.join(temp_dir, "clip.mkv")
			yaml_path = os.path.join(temp_dir, "project.yaml")
			with open(asset_path, "w") as asset_file:
				asset_file.write("")
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
			lines.append("  playback_styles:")
			lines.append("    fast: {speed: 4}")
			lines.append("")
			lines.append("timeline:")
			lines.append("  segments:")
			lines.append(
				"    - source: {asset: clip, in: \"00:00.0\", out: \"00:01.0\", "
				"style: fast}"
			)
			lines.append("")
			lines.append("output:")
			lines.append(f"  file: \"{os.path.join(temp_dir, 'out.mkv')}\"")
			with open(yaml_path, "w") as yaml_file:
				yaml_file.write("\n".join(lines))
				yaml_file.write("\n")
			project = ProjectLoader(yaml_path).load()
			video_speed = project.playlists["video_base"]["entries"][0]["speed"]
			audio_speed = project.playlists["audio_main"]["entries"][0]["speed"]
			self.assertEqual(video_speed, Decimal("4"))
			self.assertEqual(audio_speed, Decimal("4"))

	#============================================
	def test_playback_style_overlay_defaults(self) -> None:
		"""Ensure overlay templates can pull style from playback style."""
		with tempfile.TemporaryDirectory() as temp_dir:
			asset_path = os.path.join(temp_dir, "clip.mkv")
			yaml_path = os.path.join(temp_dir, "project.yaml")
			with open(asset_path, "w") as asset_file:
				asset_file.write("")
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
			lines.append("  playback_styles:")
			lines.append("    fast_forward: {speed: 4, overlay_text_style: fast_style}")
			lines.append("  overlay_text_styles:")
			lines.append("    fast_style: {kind: overlay_text_style, font_size: 48}")
			lines.append("")
			lines.append("timeline:")
			lines.append("  segments:")
			lines.append(
				"    - source: {asset: clip, in: \"00:00.0\", out: \"00:01.0\", "
				"style: fast_forward}"
			)
			lines.append("  overlays:")
			lines.append("    - id: fast_forward")
			lines.append("      apply:")
			lines.append("        kind: playback_style")
			lines.append("        style: fast_forward")
			lines.append("      template:")
			lines.append("        generator:")
			lines.append("          kind: overlay_text")
			lines.append("          text: \"Fast Forward {speed}X >>>\"")
			lines.append("")
			lines.append("output:")
			lines.append(f"  file: \"{os.path.join(temp_dir, 'out.mkv')}\"")
			with open(yaml_path, "w") as yaml_file:
				yaml_file.write("\n".join(lines))
				yaml_file.write("\n")
			project = ProjectLoader(yaml_path).load()
			overlay_playlist = project.playlists["video_overlay_fast_forward"]["entries"]
			generator_entries = [
				entry for entry in overlay_playlist
				if entry.get('type') == 'generator'
			]
			self.assertTrue(len(generator_entries) > 0)
			first_generator = generator_entries[0]
			self.assertEqual(first_generator["data"].get("style"), "fast_style")

#============================================

def main() -> None:
	"""Run the unit tests."""
	unittest.main()

#============================================

if __name__ == "__main__":
	main()
