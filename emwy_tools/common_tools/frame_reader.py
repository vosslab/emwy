"""Reliable frame reader for video tools.

Wraps cv2.VideoCapture with multiple seeking strategies and a sequential
fallback for codecs where random-access seeking is unreliable.

When all strategies fail (common with HEVC in QuickTime MOV containers),
the reader automatically remuxes the video to MKV via mkvmerge and retries.
The temp MKV is cleaned up on close().
"""

# Standard Library
import os
import shutil
import subprocess
import tempfile

# PIP3 modules
import cv2
import numpy


#============================================
class FrameReader:
	"""Read video frames reliably using multiple seek strategies.

	Tries five strategies in order:
	1. Seek by milliseconds on the existing capture
	2. Seek by frame index on the existing capture
	3. Reopen capture and seek by frame index
	4. Sequential forward read on a dedicated capture (never touched by 1-3)
	5. Remux to MKV via mkvmerge, reopen all captures, retry from strategy 1

	Strategies 1-3 share one cv2.VideoCapture (self._cap) for seek-based access.
	Strategy 4 uses a separate cv2.VideoCapture (self._seq_cap) so that seek
	operations in 1-3 never corrupt the sequential reader's position.

	Strategy 5 fires once: on first all-fail it remuxes the source video to a
	temp MKV file, reopens both captures on the MKV, and retries. This fixes
	HEVC/H.265 in QuickTime MOV containers where OpenCV cannot seek at all.

	Strategy 4 is efficient when candidates are processed in ascending order,
	since total sequential reads across all candidates is at most total_frames.

	Args:
		video_path: Path to the video file.
		fps: Video frame rate (frames per second).
		total_frames: Total number of frames in the video.
		debug: If True, print per-frame strategy results.
	"""

	#============================================
	def __init__(self, video_path: str, fps: float, total_frames: int, debug: bool = False):
		"""Initialize FrameReader with a video file.

		Args:
			video_path: Path to the video file.
			fps: Video frame rate.
			total_frames: Total number of frames in the video.
			debug: Enable verbose per-frame debug output.
		"""
		self._video_path = video_path
		self._fps = fps
		self._total_frames = total_frames
		self._debug = debug
		# path currently used for captures (changes if remuxed)
		self._active_path = video_path
		# temp MKV path, set if remux occurs
		self._temp_mkv = None
		# whether remux has already been attempted (only try once)
		self._remux_attempted = False
		# seek-based capture used by strategies 1-3
		self._cap = cv2.VideoCapture(video_path)
		if not self._cap.isOpened():
			raise RuntimeError(f"cannot open video: {video_path}")
		# dedicated sequential capture used only by strategy 4
		# lazily opened on first sequential read to avoid wasting resources
		self._seq_cap = None
		# sequential position tracker (-1 means not initialized)
		self._seq_pos = -1

	#============================================
	def read_frame(self, frame_idx: int) -> numpy.ndarray | None:
		"""Read a single frame by index, trying multiple strategies.

		Args:
			frame_idx: Target frame index (0-based).

		Returns:
			BGR frame as numpy array, or None if all strategies fail.
		"""
		results = {}

		# strategy 1: seek by milliseconds
		time_msec = (frame_idx / self._fps) * 1000.0
		self._cap.set(cv2.CAP_PROP_POS_MSEC, time_msec)
		ret, frame = self._cap.read()
		if ret:
			results["seek_msec"] = "OK"
			self._print_debug(frame_idx, results)
			return frame
		results["seek_msec"] = "FAIL"

		# strategy 2: seek by frame index
		self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
		ret, frame = self._cap.read()
		if ret:
			results["seek_frame"] = "OK"
			self._print_debug(frame_idx, results)
			return frame
		results["seek_frame"] = "FAIL"

		# strategy 3: reopen seek capture and seek by frame index
		self._cap.release()
		self._cap = cv2.VideoCapture(self._active_path)
		if self._cap.isOpened():
			self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
			ret, frame = self._cap.read()
			if ret:
				results["reopen"] = "OK"
				self._print_debug(frame_idx, results)
				return frame
		results["reopen"] = "FAIL"

		# strategy 4: sequential forward read on dedicated capture
		frame = self._sequential_read(frame_idx)
		if frame is not None:
			results["sequential"] = "OK"
			self._print_debug(frame_idx, results)
			return frame
		results["sequential"] = "FAIL"

		# strategy 5: remux to MKV and retry (one-shot, never retried)
		if not self._remux_attempted:
			remuxed = self._remux_to_mkv()
			if remuxed:
				results["remux"] = "OK"
				# retry strategies 1-4 on the remuxed file
				frame = self._retry_after_remux(frame_idx, results)
				if frame is not None:
					self._print_debug(frame_idx, results)
					return frame
			else:
				results["remux"] = "FAIL"

		self._print_debug(frame_idx, results)
		return None

	#============================================
	def _remux_to_mkv(self) -> bool:
		"""Remux the source video to a temporary MKV file via mkvmerge.

		HEVC/H.265 in QuickTime MOV containers causes OpenCV seek failures.
		Remuxing to MKV (lossless, just repackaging) fixes the seeking.

		Returns:
			True if remux succeeded and captures were reopened.
		"""
		self._remux_attempted = True
		# check if mkvmerge is available
		mkvmerge_path = shutil.which("mkvmerge")
		if mkvmerge_path is None:
			if self._debug:
				print("  remux: mkvmerge not found, skipping")
			return False
		# create temp MKV file next to the original video
		video_dir = os.path.dirname(self._video_path) or "."
		video_base = os.path.basename(self._video_path)
		stem = os.path.splitext(video_base)[0]
		# use tempfile to get a unique name, but keep it in the same directory
		fd, temp_path = tempfile.mkstemp(suffix=".mkv", prefix=f".{stem}_remux_", dir=video_dir)
		os.close(fd)
		print(f"  remuxing to MKV for reliable seeking: {video_base}")
		# run mkvmerge to remux (lossless, just repackages the streams)
		cmd = [mkvmerge_path, self._video_path, "-o", temp_path]
		result = subprocess.run(cmd, capture_output=True, text=True)
		if result.returncode not in (0, 1):
			# mkvmerge returns 1 for warnings, 2 for errors
			if self._debug:
				print(f"  remux failed: {result.stderr.strip()}")
			# clean up partial temp file
			if os.path.isfile(temp_path):
				os.remove(temp_path)
			return False
		self._temp_mkv = temp_path
		self._active_path = temp_path
		# release old captures and reopen on the MKV
		self._cap.release()
		self._cap = cv2.VideoCapture(temp_path)
		if self._seq_cap is not None:
			self._seq_cap.release()
			self._seq_cap = None
		self._seq_pos = -1
		if not self._cap.isOpened():
			if self._debug:
				print("  remux: cannot open remuxed MKV")
			return False
		print("  remux complete, reopened on MKV")
		return True

	#============================================
	def _retry_after_remux(self, frame_idx: int, results: dict) -> numpy.ndarray | None:
		"""Retry strategies 1-4 after successful remux.

		Args:
			frame_idx: Target frame index.
			results: Strategy results dict to update.

		Returns:
			BGR frame as numpy array, or None if still failing.
		"""
		# retry strategy 1: seek by msec on remuxed file
		time_msec = (frame_idx / self._fps) * 1000.0
		self._cap.set(cv2.CAP_PROP_POS_MSEC, time_msec)
		ret, frame = self._cap.read()
		if ret:
			results["retry_seek_msec"] = "OK"
			return frame
		results["retry_seek_msec"] = "FAIL"
		# retry strategy 2: seek by frame index on remuxed file
		self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
		ret, frame = self._cap.read()
		if ret:
			results["retry_seek_frame"] = "OK"
			return frame
		results["retry_seek_frame"] = "FAIL"
		# retry strategy 4: sequential on remuxed file
		frame = self._sequential_read(frame_idx)
		if frame is not None:
			results["retry_sequential"] = "OK"
			return frame
		results["retry_sequential"] = "FAIL"
		return None

	#============================================
	def _sequential_read(self, frame_idx: int) -> numpy.ndarray | None:
		"""Read forward sequentially to the target frame.

		Uses a dedicated capture (self._seq_cap) that is never touched
		by seek-based strategies, so its position is always reliable.

		If target is behind the current sequential position, reopens
		the capture from the beginning.

		Args:
			frame_idx: Target frame index.

		Returns:
			BGR frame as numpy array, or None on failure.
		"""
		# if target is behind current position or cap not initialized, reopen
		if self._seq_cap is None or frame_idx <= self._seq_pos or self._seq_pos < 0:
			if self._seq_cap is not None:
				self._seq_cap.release()
			self._seq_cap = cv2.VideoCapture(self._active_path)
			if not self._seq_cap.isOpened():
				return None
			self._seq_pos = -1

		# read forward, discarding frames until we reach target
		frame = None
		while self._seq_pos < frame_idx:
			ret, frame = self._seq_cap.read()
			if not ret:
				return None
			self._seq_pos += 1

		# self._seq_pos should now equal frame_idx
		return frame

	#============================================
	def _print_debug(self, frame_idx: int, results: dict) -> None:
		"""Print per-frame debug output showing strategy results.

		Args:
			frame_idx: Frame index that was read.
			results: Dict mapping strategy name to "OK" or "FAIL".
		"""
		if not self._debug:
			return
		# build a compact status string
		parts = []
		strategy_order = (
			"seek_msec", "seek_frame", "reopen", "sequential",
			"remux", "retry_seek_msec", "retry_seek_frame", "retry_sequential",
		)
		for strategy in strategy_order:
			if strategy in results:
				parts.append(f"{strategy}={results[strategy]}")
		status_str = " ".join(parts)
		print(f"  frame {frame_idx}: {status_str}")

	#============================================
	def close(self) -> None:
		"""Release video captures and clean up temp MKV if created."""
		if self._cap is not None:
			self._cap.release()
			self._cap = None
		if self._seq_cap is not None:
			self._seq_cap.release()
			self._seq_cap = None
		# remove temporary remuxed MKV
		if self._temp_mkv is not None and os.path.isfile(self._temp_mkv):
			os.remove(self._temp_mkv)
			if self._debug:
				print(f"  cleaned up temp MKV: {self._temp_mkv}")
			self._temp_mkv = None
