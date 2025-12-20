#!/usr/bin/env python3

"""
Unit tests for tools/emwy_yaml_writer.py.
"""

# Standard Library
import os
import sys
import unittest

# local repo modules
TOOLS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "tools"))
if TOOLS_DIR not in sys.path:
	sys.path.insert(0, TOOLS_DIR)
import emwy_yaml_writer

#============================================

class EmwyYamlWriterTest(unittest.TestCase):
	#============================================
	def test_build_silence_timeline_yaml(self) -> None:
		"""Ensure timeline.segments output with merged A/V entries."""
		profile = {
			'fps': "30",
			'width': 1920,
			'height': 1080,
			'sample_rate': 48000,
			'channels': "mono",
		}
		segments = [
			{
				'kind': 'content',
				'start_tc': "00:00:00.000",
				'end_tc': "00:00:02.000",
			},
			{
				'kind': 'silence',
				'start_tc': "00:00:02.000",
				'end_tc': "00:00:03.000",
			},
		]
		yaml_text = emwy_yaml_writer.build_silence_timeline_yaml(
			"clip.mp4",
			"out.mkv",
			profile,
			"source",
			segments,
			4.0,
			1.0,
		)
		self.assertIn("timeline:", yaml_text)
		self.assertIn("segments:", yaml_text)
		self.assertNotIn("playlists:", yaml_text)
		self.assertNotIn("stack:", yaml_text)
		self.assertIn("assets:", yaml_text)
		self.assertIn("video:", yaml_text)
		self.assertNotIn("assets:\n  audio:", yaml_text)
		self.assertIn("asset: source", yaml_text)
		self.assertEqual(yaml_text.count("video: {speed"), 1)
		self.assertEqual(yaml_text.count("audio: {speed"), 1)

	#============================================
	def test_yaml_quote(self) -> None:
		"""Ensure YAML quoting escapes quotes and backslashes."""
		value = "path\\with\"quote"
		quoted = emwy_yaml_writer.yaml_quote(value)
		self.assertEqual(quoted, "\"path\\\\with\\\"quote\"")

	#============================================
	def test_format_speed(self) -> None:
		"""Ensure speed formatting trims trailing zeros."""
		self.assertEqual(emwy_yaml_writer.format_speed(1.0), "1")
		self.assertEqual(emwy_yaml_writer.format_speed(1.5), "1.5")
		self.assertEqual(emwy_yaml_writer.format_speed(2.125), "2.125")

#============================================

def main() -> None:
	"""Run the unit tests."""
	unittest.main()

#============================================

if __name__ == "__main__":
	main()
