"""Unit tests for track_runner.encoder module."""

# PIP3 modules
import numpy
import pytest

# local repo modules
import track_runner.encoder as enc_mod

from tr_test_helpers import HAS_TEST_VIDEO
from tr_test_helpers import TEST_VIDEO


#============================================
@pytest.mark.skipif(not HAS_TEST_VIDEO, reason="test video not found")
def test_encoder_video_reader_info() -> None:
	"""VideoReader.get_info returns dict with expected keys."""
	reader = enc_mod.VideoReader(TEST_VIDEO)
	info = reader.get_info()
	reader.close()
	for key in ("frame_count", "fps", "width", "height"):
		assert key in info, f"missing key: {key}"
	assert info["frame_count"] > 0
	assert info["fps"] > 0


#============================================
@pytest.mark.skipif(not HAS_TEST_VIDEO, reason="test video not found")
def test_encoder_video_reader_frame_shape() -> None:
	"""read_frame returns correct shape."""
	reader = enc_mod.VideoReader(TEST_VIDEO)
	info = reader.get_info()
	frame = reader.read_frame(0)
	reader.close()
	assert frame is not None
	assert frame.shape[0] == info["height"]
	assert frame.shape[1] == info["width"]
	assert frame.shape[2] == 3


#============================================
@pytest.mark.skipif(not HAS_TEST_VIDEO, reason="test video not found")
def test_encoder_video_reader_iteration() -> None:
	"""iterate yields (index, frame) tuples."""
	reader = enc_mod.VideoReader(TEST_VIDEO)
	frames_read = []
	for idx, frame in reader:
		frames_read.append((idx, frame.shape))
		if idx >= 4:
			break
	reader.close()
	assert len(frames_read) == 5
	for i, (idx, _) in enumerate(frames_read):
		assert idx == i


#============================================
def test_encoder_draw_debug_overlay_none_state() -> None:
	"""draw_debug_overlay_cropped handles None state without crashing."""
	frame = numpy.zeros((140, 200, 3), dtype=numpy.uint8)
	crop_rect = (50, 30, 200, 140)
	enc_mod.draw_debug_overlay_cropped(frame, None, crop_rect, 200, 140)
	# should have drawn some text (non-zero pixels)
	assert not numpy.all(frame == 0)


#============================================
def test_encoder_draw_debug_overlay_with_state() -> None:
	"""draw_debug_overlay_cropped draws on frame when given a v2 state."""
	frame = numpy.zeros((140, 200, 3), dtype=numpy.uint8)
	state = {
		"cx": 150.0, "cy": 100.0, "w": 40.0, "h": 80.0,
		"conf": 0.85, "source": "merged",
	}
	crop_rect = (50, 30, 200, 140)
	enc_mod.draw_debug_overlay_cropped(frame, state, crop_rect, 200, 140)
	assert not numpy.all(frame == 0)
