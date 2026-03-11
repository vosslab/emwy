"""Video encoding module for track_runner.

Handles video decoding via OpenCV VideoCapture, cropping via numpy,
and encoding via ffmpeg subprocess pipe.
"""

# Standard Library
import os
import shutil
import subprocess

# PIP3 modules
import cv2
import numpy

# local repo modules
import crop


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

	#============================================
	def __iter__(self):
		"""Yield (frame_index, frame) tuples from the start.

		Yields:
			Tuple of (int, numpy.ndarray) for each frame.
		"""
		# reset to beginning of video
		self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
		frame_index = 0
		while True:
			ret, frame = self.cap.read()
			if not ret:
				break
			yield (frame_index, frame)
			frame_index += 1

	#============================================
	def read_frame(self, frame_index: int) -> numpy.ndarray | None:
		"""Read a specific frame by index.

		Args:
			frame_index: 0-based frame number.

		Returns:
			Frame as numpy array (BGR), or None if beyond end.
		"""
		if frame_index < 0 or frame_index >= self.frame_count:
			return None
		# seek to the requested frame
		self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
		ret, frame = self.cap.read()
		if not ret:
			return None
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
	):
		"""Start ffmpeg pipe for encoding.

		Args:
			output_path: Path for output video file.
			width: Output frame width in pixels.
			height: Output frame height in pixels.
			fps: Output frame rate.
			codec: Video codec (default libx264).
			crf: Constant Rate Factor (default 18).

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
			output_path,
		]
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

		Raises:
			RuntimeError: If ffmpeg exits with a non-zero return code.
		"""
		if self.process is None:
			return
		# close stdin to signal end of input
		if self.process.stdin is not None:
			self.process.stdin.close()
		# wait for ffmpeg to finish
		self.process.wait()
		returncode = self.process.returncode
		if returncode != 0:
			# read stderr for the error message
			stderr_output = ""
			if self.process.stderr is not None:
				stderr_output = self.process.stderr.read().decode(
					"utf-8", errors="replace"
				)
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


#============================================
def _input_has_audio(input_path: str) -> bool:
	"""Check whether a video file contains an audio stream.

	Args:
		input_path: Path to the video file.

	Returns:
		True if at least one audio stream is detected.
	"""
	ffprobe_path = shutil.which("ffprobe")
	if ffprobe_path is None:
		raise RuntimeError("ffprobe not found in PATH")
	cmd = [
		ffprobe_path,
		"-v", "error",
		"-select_streams", "a",
		"-show_entries", "stream=index",
		"-of", "csv=p=0",
		input_path,
	]
	result = subprocess.run(cmd, capture_output=True, text=True)
	# if any audio stream index was printed, audio exists
	has_audio = len(result.stdout.strip()) > 0
	return has_audio


#============================================
def copy_audio(
	input_path: str,
	video_path: str,
	output_path: str,
) -> None:
	"""Mux audio from input video with video from cropped output.

	If the input file has no audio stream, the video file is
	copied directly to the output path.

	Args:
		input_path: Path to original video with audio.
		video_path: Path to cropped video (video only).
		output_path: Path for the final muxed output.
	"""
	# check if the original input has audio
	if not _input_has_audio(input_path):
		print(f"No audio stream in {input_path}, copying video only")
		shutil.copy2(video_path, output_path)
		return
	ffmpeg_path = shutil.which("ffmpeg")
	if ffmpeg_path is None:
		raise RuntimeError("ffmpeg not found in PATH")
	cmd = [
		ffmpeg_path,
		"-y",
		"-i", video_path,
		"-i", input_path,
		"-c:v", "copy",
		"-c:a", "aac",
		"-map", "0:v:0",
		"-map", "1:a:0",
		"-shortest",
		output_path,
	]
	# print the command for debugging
	print(f"Muxing audio: {' '.join(cmd)}")
	result = subprocess.run(cmd, capture_output=True, text=True)
	if result.returncode != 0:
		raise RuntimeError(
			f"ffmpeg mux failed with code {result.returncode}: "
			f"{result.stderr}"
		)


#============================================
def encode_cropped_video(
	reader: VideoReader,
	crop_rects: list,
	output_path: str,
	crop_width: int,
	crop_height: int,
	codec: str = "libx264",
	crf: int = 18,
	frame_states: list | None = None,
	debug: bool = False,
) -> None:
	"""Read all frames, apply crops, and write encoded output.

	When debug=True and frame_states is provided, draws tracking
	bounding box and info overlay on the cropped frames.

	Args:
		reader: An open VideoReader instance.
		crop_rects: List of (x, y, w, h) tuples, one per frame.
		output_path: Path for the output video file.
		crop_width: Output frame width after resize.
		crop_height: Output frame height after resize.
		codec: Video codec (default libx264).
		crf: Constant Rate Factor (default 18).
		frame_states: List of per-frame state dicts from tracker.
		debug: If True, draw tracking overlay on cropped frames.
	"""
	info = reader.get_info()
	fps = info["fps"]
	writer = VideoWriter(
		output_path, crop_width, crop_height, fps,
		codec=codec, crf=crf,
	)
	frame_count = len(crop_rects)
	for frame_idx, frame in reader:
		# stop once we have processed all provided crop rects
		if frame_idx >= frame_count:
			break
		# crop the frame using the crop module
		crop_rect = crop_rects[frame_idx]
		cropped = crop.apply_crop(frame, crop_rect)
		# resize to the exact output dimensions for consistency
		resized = cv2.resize(cropped, (crop_width, crop_height))
		# draw debug overlay on the cropped frame when requested
		if debug and frame_states is not None:
			state = frame_states[frame_idx] if frame_idx < len(frame_states) else None
			draw_debug_overlay_cropped(
				resized, state, crop_rect, crop_width, crop_height,
			)
		writer.write_frame(resized)
	writer.close()


#============================================
# color constants for debug overlay drawing
_COLOR_DETECTED = (0, 255, 0)       # green
_COLOR_PREDICTED = (0, 255, 255)    # yellow
_COLOR_INTERPOLATED = (0, 165, 255) # orange
_COLOR_LOST = (0, 0, 255)          # red


#============================================
def _source_color(source: str) -> tuple:
	"""Return a BGR color for a tracking source label.

	Args:
		source: Frame source string (detected, predicted, interpolated, lost).

	Returns:
		Tuple of (B, G, R) color values.
	"""
	color_map = {
		"detected": _COLOR_DETECTED,
		"predicted": _COLOR_PREDICTED,
		"interpolated": _COLOR_INTERPOLATED,
		"lost": _COLOR_LOST,
	}
	color = color_map.get(source, _COLOR_LOST)
	return color


#============================================
def draw_debug_overlay_cropped(
	frame: numpy.ndarray,
	state: dict | None,
	crop_rect: tuple,
	out_w: int,
	out_h: int,
) -> None:
	"""Draw tracking debug overlay on a cropped/resized frame in-place.

	Transforms the tracked bounding box from full-frame center coords
	into crop-space pixel coords and draws it, along with source label
	and confidence bar.

	Args:
		frame: BGR image (already cropped and resized to out_w x out_h).
		state: Per-frame state dict with bbox, source, confidence,
			frame_index. None if the frame had no tracking data.
		crop_rect: Crop rectangle as (x, y, w, h) in full-frame coords.
		out_w: Output frame width in pixels.
		out_h: Output frame height in pixels.
	"""
	if state is None:
		# no tracking data for this frame
		cv2.putText(
			frame, "NO DATA", (10, 30),
			cv2.FONT_HERSHEY_SIMPLEX, 0.7, _COLOR_LOST, 2,
		)
		return

	source = state.get("source", "lost")
	confidence = state.get("confidence", 0.0)
	frame_idx = state.get("frame_index", 0)
	bbox = state.get("bbox")
	color = _source_color(source)

	# crop origin and scale factors for coordinate transform
	crop_x, crop_y, crop_w, crop_h = crop_rect
	scale_x = out_w / crop_w if crop_w > 0 else 1.0
	scale_y = out_h / crop_h if crop_h > 0 else 1.0

	# draw tracked bounding box (center format: cx, cy, w, h)
	if bbox is not None:
		bcx, bcy, bw, bh = bbox
		# transform from full-frame to crop-space coords
		cx_in_crop = (bcx - crop_x) * scale_x
		cy_in_crop = (bcy - crop_y) * scale_y
		bw_scaled = bw * scale_x
		bh_scaled = bh * scale_y
		x1 = int(cx_in_crop - bw_scaled / 2.0)
		y1 = int(cy_in_crop - bh_scaled / 2.0)
		x2 = int(cx_in_crop + bw_scaled / 2.0)
		y2 = int(cy_in_crop + bh_scaled / 2.0)
		# black outline for contrast against any background
		cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 0), 5)
		# colored rectangle on top
		cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
		# crosshair at bbox center
		cross_cx = int(cx_in_crop)
		cross_cy = int(cy_in_crop)
		cross_len = 12
		cv2.line(frame, (cross_cx - cross_len, cross_cy), (cross_cx + cross_len, cross_cy), (0, 0, 0), 3)
		cv2.line(frame, (cross_cx, cross_cy - cross_len), (cross_cx, cross_cy + cross_len), (0, 0, 0), 3)
		cv2.line(frame, (cross_cx - cross_len, cross_cy), (cross_cx + cross_len, cross_cy), color, 1)
		cv2.line(frame, (cross_cx, cross_cy - cross_len), (cross_cx, cross_cy + cross_len), color, 1)
		# show box coordinates below frame label
		box_label = f"box: {x1},{y1} {x2-x1}x{y2-y1}"
		cv2.putText(frame, box_label, (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

	# draw frame info text in top-left
	label = f"F:{frame_idx} {source} conf={confidence:.2f}"
	cv2.putText(
		frame, label, (10, 30),
		cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2,
	)

	# draw confidence bar in top-right corner
	bar_w = 100
	bar_h = 12
	bar_x = out_w - bar_w - 10
	bar_y = 10
	# background bar (dark gray)
	cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50, 50, 50), -1)
	# filled portion (green to red gradient via confidence)
	fill_w = int(bar_w * max(0.0, min(1.0, confidence)))
	# color: green at 1.0, red at 0.0
	bar_g = int(255 * confidence)
	bar_r = int(255 * (1.0 - confidence))
	bar_color = (0, bar_g, bar_r)
	cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), bar_color, -1)
