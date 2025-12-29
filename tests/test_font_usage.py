#!/usr/bin/env python3

"""
Unit tests for custom font usage.
"""

# Standard Library
import os
import sys
import tempfile

# PIP3 modules
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# tests helpers
TESTS_DIR = os.path.abspath(os.path.dirname(__file__))
if TESTS_DIR not in sys.path:
	sys.path.insert(0, TESTS_DIR)
from font_utils import find_system_ttf

# local repo modules
from emwylib.core import renderer as renderer_module
from emwylib.core.renderer import Renderer

#============================================

CUSTOM_FONT_PATH = find_system_ttf()
HAVE_CUSTOM_FONT = CUSTOM_FONT_PATH is not None
SKIP_FONT_REASON = "missing system TTF/OTF font"

#============================================

class _StubProject:
	def __init__(self):
		self.profile = {
			'width': 320,
			'height': 240,
		}

#============================================

@pytest.mark.skipif(not HAVE_CUSTOM_FONT, reason=SKIP_FONT_REASON)
def test_custom_font_used_in_card_render(monkeypatch) -> None:
	"""
	Ensure custom font files are passed to PIL ImageFont.truetype.
	"""
	captured = {}
	original = renderer_module.PIL.ImageFont.truetype

	def _wrapped(path, size):
		captured['path'] = path
		return original(path, size)

	monkeypatch.setattr(renderer_module.PIL.ImageFont, "truetype", _wrapped)
	renderer = Renderer(_StubProject())
	with tempfile.TemporaryDirectory() as temp_dir:
		output_path = os.path.join(temp_dir, "card.png")
		renderer._render_color_card_image(
			"Custom Font",
			"#000000",
			output_path,
			CUSTOM_FONT_PATH,
			32,
			"#ffffff"
		)
		assert os.path.exists(output_path)
	assert captured.get('path') == CUSTOM_FONT_PATH
