"""Smoke tests for FrameReader sequential fallback.

Creates a synthetic 300-frame video and verifies that FrameReader
can read frames reliably, including when seeking is broken.
Also tests against real video files in TRACK_VIDEOS/ with random
non-sequential access patterns.
"""

# Standard Library
import os
import sys
import random

# PIP3 modules
import cv2
import numpy
import pytest

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()
sys.path.insert(0, os.path.join(REPO_ROOT, "emwy_tools", "track_runner"))
import frame_reader


# synthetic video parameters
SYNTH_WIDTH = 720
SYNTH_HEIGHT = 480
SYNTH_FPS = 30
SYNTH_TOTAL_FRAMES = 300

# real video directory
TRACK_VIDEOS_DIR = os.path.join(REPO_ROOT, "TRACK_VIDEOS")

# video file extensions to look for
VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".avi")


#============================================
@pytest.fixture(scope="module")
def synth_video(tmp_path_factory):
	"""Create a synthetic 300-frame video with frame numbers burned in.

	Each frame has a unique solid color and the frame number drawn
	as white text so frames are visually distinguishable.
	"""
	video_dir = tmp_path_factory.mktemp("synth_video")
	video_path = str(video_dir / "test_video.mp4")
	# use mp4v codec for broad compatibility
	fourcc = cv2.VideoWriter_fourcc(*"mp4v")
	writer = cv2.VideoWriter(video_path, fourcc, SYNTH_FPS, (SYNTH_WIDTH, SYNTH_HEIGHT))
	if not writer.isOpened():
		pytest.skip("cv2.VideoWriter cannot create mp4v video on this system")
	for i in range(SYNTH_TOTAL_FRAMES):
		# generate a unique color per frame using modular arithmetic
		b = (i * 7) % 256
		g = (i * 13) % 256
		r = (i * 23) % 256
		# create solid color frame
		frame = numpy.full((SYNTH_HEIGHT, SYNTH_WIDTH, 3), (b, g, r), dtype=numpy.uint8)
		# burn frame number as white text
		cv2.putText(
			frame, str(i),
			(50, 240), cv2.FONT_HERSHEY_SIMPLEX, 3.0,
			(255, 255, 255), 4,
		)
		writer.write(frame)
	writer.release()
	return video_path


#============================================
def _find_track_videos() -> list:
	"""Find video files in TRACK_VIDEOS/ directory.

	Returns:
		List of absolute paths to video files, or empty list if
		the directory does not exist.
	"""
	if not os.path.isdir(TRACK_VIDEOS_DIR):
		return []
	videos = []
	for filename in os.listdir(TRACK_VIDEOS_DIR):
		# check extension case-insensitively
		if filename.lower().endswith(VIDEO_EXTENSIONS):
			full_path = os.path.join(TRACK_VIDEOS_DIR, filename)
			if os.path.isfile(full_path):
				videos.append(full_path)
	return sorted(videos)


#============================================
def test_basic_read(synth_video):
	"""FrameReader reads every 30th frame with 0 failures."""
	reader = frame_reader.FrameReader(
		synth_video, SYNTH_FPS, SYNTH_TOTAL_FRAMES, debug=True,
	)
	# read every 30th frame (10 candidates)
	candidates = list(range(0, SYNTH_TOTAL_FRAMES, 30))
	failures = 0
	for idx in candidates:
		result = reader.read_frame(idx)
		if result is None:
			failures += 1
	reader.close()
	assert failures == 0, f"expected 0 failures, got {failures}/{len(candidates)}"


#============================================
def test_sequential_fallback(synth_video, monkeypatch):
	"""All candidates read via sequential fallback when seeking is broken."""
	# monkeypatch cv2.VideoCapture.set to always return False
	# this simulates broken seeking (strategies 1-3 fail)
	def broken_set(self, prop_id, value):
		"""Simulate broken seeking by ignoring all set calls."""
		return False
	monkeypatch.setattr(cv2.VideoCapture, "set", broken_set)

	reader = frame_reader.FrameReader(
		synth_video, SYNTH_FPS, SYNTH_TOTAL_FRAMES, debug=True,
	)
	# read every 30th frame (10 candidates) in ascending order
	candidates = list(range(0, SYNTH_TOTAL_FRAMES, 30))
	failures = 0
	for idx in candidates:
		result = reader.read_frame(idx)
		if result is None:
			failures += 1
	reader.close()
	assert failures == 0, f"expected 0 failures with sequential fallback, got {failures}"


#============================================
def test_backward_scrub(synth_video):
	"""FrameReader handles backward scrub (frame 200 then frame 100)."""
	reader = frame_reader.FrameReader(
		synth_video, SYNTH_FPS, SYNTH_TOTAL_FRAMES, debug=True,
	)
	# read frame 200 first
	frame_200 = reader.read_frame(200)
	assert frame_200 is not None, "failed to read frame 200"
	# read frame 100 (backward from 200)
	frame_100 = reader.read_frame(100)
	assert frame_100 is not None, "failed to read frame 100 (backward scrub)"
	reader.close()


#============================================
def test_random_nonsequential_real_video():
	"""Read 20 random frames in random order from a random TRACK_VIDEOS/ file.

	Picks one video at random, probes its frame count with OpenCV,
	then requests 20 randomly chosen frames in shuffled (non-sequential)
	order. All reads must succeed.
	"""
	videos = _find_track_videos()
	if not videos:
		pytest.skip("no video files found in TRACK_VIDEOS/")
	# pick a random video
	rng = random.Random(42)
	video_path = rng.choice(videos)
	video_name = os.path.basename(video_path)
	print(f"\n  selected video: {video_name}")
	# probe with OpenCV to get fps and frame count
	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		pytest.skip(f"cannot open video: {video_name}")
	fps = cap.get(cv2.CAP_PROP_FPS)
	total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
	cap.release()
	if fps <= 0 or total_frames < 100:
		pytest.skip(f"video too short or bad metadata: {video_name}")
	print(f"  fps={fps:.2f}, total_frames={total_frames}")
	# pick 20 random frame indices across the video
	num_samples = 20
	candidates = rng.sample(range(total_frames), min(num_samples, total_frames))
	# shuffle to ensure non-sequential order (forward and backward jumps)
	rng.shuffle(candidates)
	print(f"  reading {len(candidates)} frames in random order: "
		f"{candidates[:5]}... (showing first 5)")
	# read all frames with FrameReader
	reader = frame_reader.FrameReader(video_path, fps, total_frames, debug=True)
	failures = []
	for idx in candidates:
		result = reader.read_frame(idx)
		if result is None:
			failures.append(idx)
	reader.close()
	fail_msg = (
		f"{len(failures)}/{len(candidates)} frames failed to read "
		f"from {video_name}: {failures}"
	)
	assert len(failures) == 0, fail_msg
