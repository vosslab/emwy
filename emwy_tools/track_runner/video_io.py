"""Video I/O classes for reading and writing video frames.

Provides VideoReader for reading frames via OpenCV VideoCapture,
and VideoWriter for encoding frames via ffmpeg subprocess pipe.
"""

# Standard Library
import os
import shutil
import subprocess

# PIP3 modules
import cv2
import numpy


#============================================
class VideoReader:
	"""Read video frames using OpenCV VideoCapture."""

	def __init__(self, video_path: str):
		"""Open video file for reading.

		Args:
			video_path: Path to input video file.

		Raises:
			RuntimeError: If the video file cannot be opened.
		"""
		if not os.path.isfile(video_path):
			raise RuntimeError(f"Video file not found: {video_path}")
		self.video_path = video_path
		self.cap = cv2.VideoCapture(video_path)
		if not self.cap.isOpened():
			raise RuntimeError(f"Cannot open video: {video_path}")
		# store video metadata
		self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
		self.fps = self.cap.get(cv2.CAP_PROP_FPS)
		self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
		self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
		# track position so sequential reads skip expensive seeks
		self._next_frame = 0

	#============================================
	def __iter__(self):
		"""Yield (frame_index, frame) tuples from the start.

		Yields:
			Tuple of (int, numpy.ndarray) for each frame.
		"""
		# reset to beginning of video
		self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
		self._next_frame = 0
		frame_index = 0
		while True:
			ret, frame = self.cap.read()
			if not ret:
				break
			self._next_frame = frame_index + 1
			yield (frame_index, frame)
			frame_index += 1

	#============================================
	def read_frame(self, frame_index: int) -> numpy.ndarray | None:
		"""Read a specific frame by index.

		Skips the seek when reading the next consecutive frame, which
		avoids an expensive MKV keyframe search on every call.

		Args:
			frame_index: 0-based frame number.

		Returns:
			Frame as numpy array (BGR), or None if beyond end.
		"""
		if frame_index < 0 or frame_index >= self.frame_count:
			return None
		# only seek when the requested frame is not the next in sequence
		if frame_index != self._next_frame:
			self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
		ret, frame = self.cap.read()
		if not ret:
			return None
		self._next_frame = frame_index + 1
		return frame

	#============================================
	def get_info(self) -> dict:
		"""Return video metadata dict.

		Returns:
			Dict with keys: frame_count, fps, width, height.
		"""
		info = {
			"frame_count": self.frame_count,
			"fps": self.fps,
			"width": self.width,
			"height": self.height,
		}
		return info

	#============================================
	def close(self) -> None:
		"""Release the video capture."""
		if self.cap is not None:
			self.cap.release()
			self.cap = None

	#============================================
	def __enter__(self):
		return self

	#============================================
	def __exit__(self, *args):
		self.close()


#============================================
class VideoWriter:
	"""Write cropped video frames via ffmpeg pipe."""

	def __init__(
		self,
		output_path: str,
		width: int,
		height: int,
		fps: float,
		codec: str = "libx264",
		crf: int = 18,
		vf_string: str = "",
	):
		"""Start ffmpeg pipe for encoding.

		Args:
			output_path: Path for output video file.
			width: Output frame width in pixels.
			height: Output frame height in pixels.
			fps: Output frame rate.
			codec: Video codec (default libx264).
			crf: Constant Rate Factor (default 18).
			vf_string: Optional ffmpeg -vf filter string (e.g. "hqdn3d").

		Raises:
			RuntimeError: If ffmpeg is not found on the system.
		"""
		self.output_path = output_path
		self.width = width
		self.height = height
		# verify ffmpeg is available
		ffmpeg_path = shutil.which("ffmpeg")
		if ffmpeg_path is None:
			raise RuntimeError("ffmpeg not found in PATH")
		# build the ffmpeg command for raw frame input
		cmd = [
			ffmpeg_path,
			"-y",
			"-f", "rawvideo",
			"-vcodec", "rawvideo",
			"-s", f"{width}x{height}",
			"-pix_fmt", "bgr24",
			"-r", str(fps),
			"-i", "-",
			"-an",
			"-vcodec", codec,
			"-crf", str(crf),
			"-pix_fmt", "yuv420p",
		]
		# insert ffmpeg video filters when provided
		if vf_string:
			cmd.extend(["-vf", vf_string])
		cmd.append(output_path)
		# start ffmpeg subprocess with piped stdin
		self.process = subprocess.Popen(
			cmd,
			stdin=subprocess.PIPE,
			stderr=subprocess.PIPE,
		)

	#============================================
	def write_frame(self, frame: numpy.ndarray) -> None:
		"""Write one frame to the encoder pipe.

		Args:
			frame: BGR image of the expected output dimensions.

		Raises:
			RuntimeError: If the pipe has already been closed.
		"""
		if self.process is None or self.process.stdin is None:
			raise RuntimeError("VideoWriter is already closed")
		# write raw frame bytes to ffmpeg stdin
		raw_bytes = frame.tobytes()
		self.process.stdin.write(raw_bytes)

	#============================================
	def close(self) -> None:
		"""Close the ffmpeg pipe and wait for completion.

		Uses communicate() to drain stderr while waiting, avoiding a
		deadlock when ffmpeg stderr output fills the OS pipe buffer.

		Raises:
			RuntimeError: If ffmpeg exits with a non-zero return code.
		"""
		if self.process is None:
			return
		# communicate() closes stdin, drains stderr, and waits atomically
		# (manual stdin.close + wait deadlocks if stderr pipe fills up)
		_, stderr_bytes = self.process.communicate()
		returncode = self.process.returncode
		if returncode != 0:
			stderr_output = ""
			if stderr_bytes:
				stderr_output = stderr_bytes.decode("utf-8", errors="replace")
			self.process = None
			raise RuntimeError(
				f"ffmpeg exited with code {returncode}: {stderr_output}"
			)
		self.process = None

	#============================================
	def __enter__(self):
		return self

	#============================================
	def __exit__(self, *args):
		self.close()
