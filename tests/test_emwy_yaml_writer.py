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
			playback_styles={
				'content': 1.0,
				'fast_forward': 4.0,
			},
			segment_style_map={
				'content': 'content',
				'silence': 'fast_forward',
			},
		)
		self.assertIn("timeline:", yaml_text)
		self.assertIn("segments:", yaml_text)
		self.assertNotIn("playlists:", yaml_text)
		self.assertNotIn("stack:", yaml_text)
		self.assertIn("assets:", yaml_text)
		self.assertIn("video:", yaml_text)
		self.assertIn("playback_styles:", yaml_text)
		self.assertNotIn("assets:\n  audio:", yaml_text)
		self.assertIn("asset: source", yaml_text)
		self.assertIn("style: content", yaml_text)
		self.assertIn("style: fast_forward", yaml_text)
		self.assertNotIn("video: {speed", yaml_text)
		self.assertNotIn("audio: {speed", yaml_text)
		self.assertNotIn("overlays:", yaml_text)

	#============================================
	def test_build_silence_timeline_yaml_with_overlay(self) -> None:
		"""Ensure overlay output includes a fast-forward template."""
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
			overlay_text_template="Fast Forward {speed}X >>>",
			overlay_geometry=[0.1, 0.4, 0.8, 0.2],
			overlay_opacity=0.9,
			playback_styles={
				'content': 1.0,
				'fast_forward': 4.0,
			},
			segment_style_map={
				'content': 'content',
				'silence': 'fast_forward',
			},
			overlay_apply_style="fast_forward",
		)
		self.assertIn("overlays:", yaml_text)
		self.assertIn("apply:", yaml_text)
		self.assertIn("template:", yaml_text)
		self.assertIn("overlay_text_styles:", yaml_text)
		self.assertIn("kind: overlay_text", yaml_text)
		self.assertIn("playback_styles:", yaml_text)
		self.assertIn("background: {kind: transparent}", yaml_text)
		self.assertIn("Fast Forward {speed}X >>>", yaml_text)
		self.assertIn("kind: playback_style", yaml_text)
		self.assertIn("style: fast_forward", yaml_text)

	#============================================
	def test_build_silence_timeline_yaml_with_overlay_animation(self) -> None:
		"""Ensure overlay animation settings render into YAML."""
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
			overlay_text_template="Fast Forward {speed}X {animate}",
			overlay_animate={
				'kind': 'cycle',
				'values': ['>', '>>', '>>>'],
				'cadence': 0.5,
			},
			overlay_geometry=[0.1, 0.4, 0.8, 0.2],
			overlay_opacity=0.9,
			playback_styles={
				'content': 1.0,
				'fast_forward': 4.0,
			},
			segment_style_map={
				'content': 'content',
				'silence': 'fast_forward',
			},
			overlay_apply_style="fast_forward",
		)
		self.assertIn("animate:", yaml_text)
		self.assertIn("values: [\">\", \">>\", \">>>\"]", yaml_text)
		self.assertIn("cadence: 0.5", yaml_text)

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
