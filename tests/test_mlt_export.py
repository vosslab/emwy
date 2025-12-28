#!/usr/bin/env python3

"""
Tests for MLT export behavior.
"""

# Standard Library
import os
import tempfile
import unittest
import xml.etree.ElementTree

# local repo modules
from emwylib.exporters.mlt import MltExporter

#============================================

def write_text_file(path: str, text: str) -> None:
	"""
	Write text to a file.

	Args:
		path: File path.
		text: Content to write.
	"""
	with open(path, 'w', encoding='utf-8') as handle:
		handle.write(text)
	return

#============================================

class MltExportTest(unittest.TestCase):
	#============================================
	def test_export_ignores_overlays(self) -> None:
		"""Ensure overlay tracks do not appear in exported MLT XML."""
		with tempfile.TemporaryDirectory() as temp_dir:
			source_file = os.path.join(temp_dir, "source.mp4")
			write_text_file(source_file, "x")
			yaml_file = os.path.join(temp_dir, "project.emwy.yaml")
			mlt_file = os.path.join(temp_dir, "project.mlt")
			yaml_text = "\n".join([
				"emwy: 2",
				"",
				"profile:",
				"  fps: \"30\"",
				"  resolution: [1920, 1080]",
				"  audio: {sample_rate: 48000, channels: mono}",
				"",
				"assets:",
				"  video:",
				f"    source: {{file: \"{source_file}\"}}",
				"",
				"timeline:",
				"  segments:",
				"    - source: {asset: source, in: \"00:00:00.000\", out: \"00:00:02.000\"}",
				"  overlays:",
				"    - id: fast_forward",
				"      geometry: [0.1, 0.4, 0.8, 0.2]",
				"      opacity: 0.9",
				"      apply:",
				"        kind: speed",
				"        stream: video",
				"        min_speed: 2",
				"      template:",
				"        generator:",
				"          kind: title_card",
				"          title: \"Fast Forward {speed}X >>>\"",
				"",
				"output:",
				"  file: \"out.mkv\"",
				"",
			])
			write_text_file(yaml_file, yaml_text)
			exporter = MltExporter(yaml_file, mlt_file)
			exporter.export()
			tree = xml.etree.ElementTree.parse(mlt_file)
			root = tree.getroot()
			playlists = root.findall('playlist')
			playlist_ids = [playlist.get('id', '') for playlist in playlists]
			for playlist_id in playlist_ids:
				self.assertNotIn("video_overlay_", playlist_id)
			multitracks = root.findall('.//multitrack')
			self.assertEqual(len(multitracks), 1)
			tracks = multitracks[0].findall('track')
			self.assertEqual(len(tracks), 2)

#============================================

def main() -> None:
	"""Run the unit tests."""
	unittest.main()

#============================================

if __name__ == "__main__":
	main()
