"""
Pytest coverage for emwylib.titlecard helpers.
"""

# Standard Library
import os
import sys

# PIP3 modules
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

# local repo modules
from emwylib import titlecard

#============================================

def test_load_font_missing_raises(tmp_path) -> None:
	"""
Ensure missing font file raises a RuntimeError.
	"""
	card = titlecard.TitleCard()
	card.fontfile = str(tmp_path / "missing_font.ttf")
	with pytest.raises(RuntimeError):
		card._load_font()

#============================================

def test_make_movie_uses_codec(monkeypatch, tmp_path) -> None:
	"""
Ensure the ffmpeg command uses the configured codec and output path.
	"""
	seen = {}

	def fake_run(cmd: str) -> None:
		seen["cmd"] = cmd

	monkeypatch.setattr(titlecard.utils, "runCmd", fake_run)
	card = titlecard.TitleCard()
	card.codec = "libx264"
	card.framerate = 30
	card.imgcode = "frame"
	card.outfile = "out.mkv"
	frames_dir = tmp_path / "frames"
	frames_dir.mkdir(parents=True, exist_ok=True)
	imglist = [str(frames_dir / f"{card.imgcode}00000.png")]
	card.makeMovieFromImages(imglist)
	cmd = seen.get("cmd", "")
	assert f" -codec:v {card.codec} " in cmd
	assert f" -r {card.framerate} " in cmd
	assert f"\"{os.path.join(str(frames_dir), f'{card.imgcode}%05d.png')}\"" in cmd
	assert f" \"{card.outfile}\" " in cmd
