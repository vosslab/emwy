
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

from emwylib.core.loader import ProjectLoader

#============================================

class SpeedSyncTest(unittest.TestCase):
	#============================================
	def test_mismatched_speed_raises(self) -> None:
		"""Ensure audio/video speed mismatches are rejected."""
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
			lines.append("")
			lines.append("timeline:")
			lines.append("  segments:")
			lines.append(
				"    - source: {asset: clip, in: \"00:00.0\", out: \"00:01.0\", "
				"video: {speed: 2}, audio: {speed: 1}}"
			)
			lines.append("")
			lines.append("output:")
			lines.append(f"  file: \"{os.path.join(temp_dir, 'out.mkv')}\"")
			with open(yaml_path, "w") as yaml_file:
				yaml_file.write("\n".join(lines))
				yaml_file.write("\n")
			with self.assertRaises(RuntimeError):
				ProjectLoader(yaml_path).load()

#============================================

def main() -> None:
	"""Run the unit tests."""
	unittest.main()

#============================================

if __name__ == "__main__":
	main()
