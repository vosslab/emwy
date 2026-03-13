"""Video encoding module for track_runner.

Handles video decoding via OpenCV VideoCapture, cropping via numpy,
and encoding via ffmpeg subprocess pipe.
"""

# Standard Library
import os
import shutil
import subprocess
import concurrent.futures

# PIP3 modules
import cv2
import numpy
import rich.progress

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
	# wrap reader with rich progress bar
	with rich.progress.Progress(
		rich.progress.TextColumn("{task.description}"),
		rich.progress.BarColumn(),
		rich.progress.TaskProgressColumn(),
		rich.progress.TimeRemainingColumn(),
	) as progress:
		task = progress.add_task("  encoding", total=frame_count)
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
			progress.update(task, advance=1)
	writer.close()


#============================================
# color constants for debug overlay drawing (v2)
_COLOR_ACCEPTED = (0, 255, 0)        # solid green: accepted torso track
_COLOR_FORWARD = (255, 128, 0)       # dashed blue: forward track box
_COLOR_BACKWARD = (0, 128, 255)      # dashed orange: backward track box
_COLOR_COMPETITOR = (0, 0, 255)      # red: best competitor box (low margin)
_COLOR_LOST = (0, 0, 200)           # dark red: no tracking data


#============================================
def _source_color(source: str) -> tuple:
	"""Return a BGR color for a v2 tracking source label.

	Args:
		source: Frame source string (seed, propagated, merged).

	Returns:
		Tuple of (B, G, R) color values.
	"""
	color_map = {
		"seed": (0, 255, 128),        # bright green-teal for seed frames
		"propagated": (0, 200, 255),  # yellow-orange for propagated frames
		"merged": (255, 200, 0),      # cyan-blue for merged frames
	}
	color = color_map.get(source, _COLOR_LOST)
	return color


#============================================
def _draw_dashed_rect(
	frame: numpy.ndarray,
	x1: int,
	y1: int,
	x2: int,
	y2: int,
	color: tuple,
	thickness: int = 2,
	dash_len: int = 10,
) -> None:
	"""Draw a dashed rectangle on the frame in-place.

	Args:
		frame: BGR image to draw on.
		x1: Left edge of the rectangle.
		y1: Top edge of the rectangle.
		x2: Right edge of the rectangle.
		y2: Bottom edge of the rectangle.
		color: BGR color tuple.
		thickness: Line thickness in pixels.
		dash_len: Length of each dash segment in pixels.
	"""
	# top edge: left to right
	x = x1
	while x < x2:
		x_end = min(x + dash_len, x2)
		cv2.line(frame, (x, y1), (x_end, y1), color, thickness)
		x += 2 * dash_len
	# bottom edge: left to right
	x = x1
	while x < x2:
		x_end = min(x + dash_len, x2)
		cv2.line(frame, (x, y2), (x_end, y2), color, thickness)
		x += 2 * dash_len
	# left edge: top to bottom
	y = y1
	while y < y2:
		y_end = min(y + dash_len, y2)
		cv2.line(frame, (x1, y), (x1, y_end), color, thickness)
		y += 2 * dash_len
	# right edge: top to bottom
	y = y1
	while y < y2:
		y_end = min(y + dash_len, y2)
		cv2.line(frame, (x2, y), (x2, y_end), color, thickness)
		y += 2 * dash_len


#============================================
def _box_to_crop_coords(
	box: list,
	crop_rect: tuple,
	out_w: int,
	out_h: int,
) -> tuple:
	"""Convert a [cx, cy, w, h] full-frame box to crop-space pixel coords.

	Args:
		box: [cx, cy, w, h] in full-frame coordinates.
		crop_rect: (x, y, w, h) crop region in full-frame coordinates.
		out_w: Output frame width in pixels.
		out_h: Output frame height in pixels.

	Returns:
		Tuple of (x1, y1, x2, y2) pixel coordinates in crop-space.
	"""
	crop_x, crop_y, crop_w, crop_h = crop_rect
	scale_x = out_w / crop_w if crop_w > 0 else 1.0
	scale_y = out_h / crop_h if crop_h > 0 else 1.0
	bcx, bcy, bw, bh = box
	# transform center from full-frame to crop-space
	cx_in_crop = (bcx - crop_x) * scale_x
	cy_in_crop = (bcy - crop_y) * scale_y
	bw_scaled = bw * scale_x
	bh_scaled = bh * scale_y
	x1 = int(cx_in_crop - bw_scaled / 2.0)
	y1 = int(cy_in_crop - bh_scaled / 2.0)
	x2 = int(cx_in_crop + bw_scaled / 2.0)
	y2 = int(cy_in_crop + bh_scaled / 2.0)
	return (x1, y1, x2, y2)


#============================================
def _compute_overlay_scale(
	out_h: int,
	box_h_px: float = 0.0,
) -> float:
	"""Compute a draw-scale factor for debug overlay elements.

	Scales relative to 1080p as the reference resolution, then adjusts
	down when the tracked box is small relative to the frame (zoomed out).

	Args:
		out_h: Output frame height in pixels.
		box_h_px: Tracked box height in crop-space pixels (0 if unknown).

	Returns:
		Float scale factor (1.0 at 1080p with box filling ~30% of frame).
	"""
	# base scale: normalize to 1080p
	res_scale = out_h / 1080.0
	# box scale: how much of the frame the runner fills
	if box_h_px > 0 and out_h > 0:
		fill_ratio = box_h_px / out_h
		# clamp: don't go below 0.3x or above 1.0x from box size
		box_factor = max(0.3, min(1.0, fill_ratio / 0.3))
	else:
		box_factor = 0.5
	scale = res_scale * box_factor
	# floor at 0.25 so things stay visible on very small outputs
	scale = max(0.25, scale)
	return scale


#============================================
# overlay transparency: 0.0 = invisible, 1.0 = opaque
_OVERLAY_ALPHA_BOXES = 0.55
_OVERLAY_ALPHA_TEXT = 0.70


#============================================
def draw_debug_overlay_cropped(
	frame: numpy.ndarray,
	state: dict | None,
	crop_rect: tuple,
	out_w: int,
	out_h: int,
	debug_state: dict | None = None,
) -> None:
	"""Draw v2 tracking debug overlay on a cropped/resized frame in-place.

	Transforms tracking boxes from full-frame center coords into
	crop-space pixel coords. Draws accepted torso track (solid green),
	forward/backward track boxes (dashed), competitor box (red), and
	text labels for confidence, source, and interval ID.

	All drawing elements scale with output resolution and tracked box
	size, so overlays remain proportional whether zoomed in or out.
	Boxes and text are drawn with transparency via alpha blending.

	Args:
		frame: BGR image (already cropped and resized to out_w x out_h).
		state: v2 per-frame state dict with keys: cx, cy, w, h, conf,
			source. None if the frame had no tracking data.
		crop_rect: Crop rectangle as (x, y, w, h) in full-frame coords.
		out_w: Output frame width in pixels.
		out_h: Output frame height in pixels.
		debug_state: Optional dict with additional debug boxes and labels:
			- "forward_box": [cx, cy, w, h] or None
			- "backward_box": [cx, cy, w, h] or None
			- "competitor_box": [cx, cy, w, h] or None
			- "confidence_label": "HIGH" / "MED" / "LOW"
			- "interval_id": str like "150-450"
	"""
	if state is None:
		# no tracking data: scale text to output resolution
		s = _compute_overlay_scale(out_h)
		font_scale = max(0.3, 0.5 * s)
		thickness = max(1, int(1.5 * s))
		cv2.putText(
			frame, "NO DATA", (10, int(25 * s)),
			cv2.FONT_HERSHEY_SIMPLEX, font_scale, _COLOR_LOST, thickness,
		)
		return

	# extract v2 state fields
	source = state.get("source", "")
	conf = state["conf"]
	cx = state.get("cx")
	cy = state.get("cy")
	w = state.get("w")
	h = state.get("h")

	# compute box height in crop-space pixels for scale computation
	box_h_px = 0.0
	if h is not None:
		crop_x, crop_y, crop_w, crop_h = crop_rect
		scale_y = out_h / crop_h if crop_h > 0 else 1.0
		box_h_px = h * scale_y

	# compute drawing scale from resolution and box size
	s = _compute_overlay_scale(out_h, box_h_px)

	# scaled drawing parameters
	# line thickness: 1px at small scale, up to 2-3px at full scale
	thin_line = max(1, int(1.0 * s))
	med_line = max(1, int(1.5 * s))
	outline_line = max(1, int(2.5 * s))
	# crosshair length scales with box size
	cross_len = max(4, int(8 * s))
	# text sizes
	font_scale_large = max(0.25, 0.45 * s)
	font_scale_med = max(0.2, 0.38 * s)
	font_scale_small = max(0.2, 0.35 * s)
	text_thick = max(1, int(1.2 * s))
	# dash length for dashed rects
	dash_len = max(4, int(8 * s))
	# confidence bar dimensions
	bar_w = max(30, int(70 * s))
	bar_h = max(4, int(8 * s))
	# text vertical positions
	text_y1 = max(12, int(22 * s))
	text_y2 = max(24, int(42 * s))

	# resolve debug_state values safely
	if debug_state is None:
		debug_state = {}
	forward_box = debug_state.get("forward_box")
	backward_box = debug_state.get("backward_box")
	competitor_box = debug_state.get("competitor_box")
	confidence_label = debug_state.get("confidence_label", "")
	interval_id = debug_state.get("interval_id", "")

	# draw all boxes and crosshair on an overlay for alpha blending
	overlay = frame.copy()

	# draw dashed blue forward track box when available
	if forward_box is not None:
		fx1, fy1, fx2, fy2 = _box_to_crop_coords(forward_box, crop_rect, out_w, out_h)
		_draw_dashed_rect(overlay, fx1, fy1, fx2, fy2, _COLOR_FORWARD,
			thickness=thin_line, dash_len=dash_len)

	# draw dashed orange backward track box when available
	if backward_box is not None:
		bx1, by1, bx2, by2 = _box_to_crop_coords(backward_box, crop_rect, out_w, out_h)
		_draw_dashed_rect(overlay, bx1, by1, bx2, by2, _COLOR_BACKWARD,
			thickness=thin_line, dash_len=dash_len)

	# draw red competitor box when present (low margin situation)
	if competitor_box is not None:
		rx1, ry1, rx2, ry2 = _box_to_crop_coords(competitor_box, crop_rect, out_w, out_h)
		cv2.rectangle(overlay, (rx1, ry1), (rx2, ry2), (0, 0, 0), outline_line)
		cv2.rectangle(overlay, (rx1, ry1), (rx2, ry2), _COLOR_COMPETITOR, med_line)

	# draw accepted torso track as solid green box
	if cx is not None and cy is not None and w is not None and h is not None:
		accepted_box = [cx, cy, w, h]
		ax1, ay1, ax2, ay2 = _box_to_crop_coords(accepted_box, crop_rect, out_w, out_h)
		# black outline for contrast against any background
		cv2.rectangle(overlay, (ax1, ay1), (ax2, ay2), (0, 0, 0), outline_line)
		# solid green accepted track box
		cv2.rectangle(overlay, (ax1, ay1), (ax2, ay2), _COLOR_ACCEPTED, med_line)
		# crosshair at box center
		cross_cx = int((ax1 + ax2) / 2)
		cross_cy = int((ay1 + ay2) / 2)
		cv2.line(overlay, (cross_cx - cross_len, cross_cy),
			(cross_cx + cross_len, cross_cy), (0, 0, 0), med_line)
		cv2.line(overlay, (cross_cx, cross_cy - cross_len),
			(cross_cx, cross_cy + cross_len), (0, 0, 0), med_line)
		cv2.line(overlay, (cross_cx - cross_len, cross_cy),
			(cross_cx + cross_len, cross_cy), _COLOR_ACCEPTED, thin_line)
		cv2.line(overlay, (cross_cx, cross_cy - cross_len),
			(cross_cx, cross_cy + cross_len), _COLOR_ACCEPTED, thin_line)

	# blend box overlay onto frame with transparency
	cv2.addWeighted(overlay, _OVERLAY_ALPHA_BOXES, frame, 1.0 - _OVERLAY_ALPHA_BOXES, 0, frame)

	# draw text on a separate overlay for text transparency
	text_overlay = frame.copy()

	# build top-left info text: source and confidence value
	source_color = _source_color(source)
	source_label = f"src:{source}" if source else "src:unknown"
	text_x = max(4, int(6 * s))
	cv2.putText(text_overlay, source_label, (text_x, text_y1),
		cv2.FONT_HERSHEY_SIMPLEX, font_scale_large, source_color, text_thick)

	# confidence label: HIGH / MED / LOW from debug_state, or compute fallback
	if confidence_label:
		conf_text = f"conf:{confidence_label} ({conf:.2f})"
	else:
		conf_text = f"conf:{conf:.2f}"
	cv2.putText(text_overlay, conf_text, (text_x, text_y2),
		cv2.FONT_HERSHEY_SIMPLEX, font_scale_med, source_color, text_thick)

	# interval ID in bottom-left corner when provided
	if interval_id:
		interval_text = f"[{interval_id}]"
		cv2.putText(
			text_overlay, interval_text, (text_x, out_h - max(6, int(8 * s))),
			cv2.FONT_HERSHEY_SIMPLEX, font_scale_small, (200, 200, 200), thin_line,
		)

	# draw confidence bar in top-right corner
	bar_x = out_w - bar_w - max(4, int(6 * s))
	bar_y = max(4, int(6 * s))
	# background bar (dark gray)
	cv2.rectangle(text_overlay, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50, 50, 50), -1)
	# filled portion scales with conf value
	fill_w = int(bar_w * max(0.0, min(1.0, conf)))
	# color: green at 1.0, red at 0.0
	bar_g = int(255 * conf)
	bar_r = int(255 * (1.0 - conf))
	bar_color = (0, bar_g, bar_r)
	cv2.rectangle(text_overlay, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), bar_color, -1)

	# blend text overlay onto frame
	cv2.addWeighted(text_overlay, _OVERLAY_ALPHA_TEXT, frame, 1.0 - _OVERLAY_ALPHA_TEXT, 0, frame)


#============================================
def _encode_segment(
	video_path: str,
	crop_rects_chunk: list,
	output_path: str,
	crop_width: int,
	crop_height: int,
	start_frame: int,
	codec: str,
	crf: int,
	frame_states_chunk: list | None,
	debug: bool,
	worker_id: int,
	total_workers: int,
) -> str:
	"""Encode one segment of the video in a worker process.

	Each worker opens its own VideoReader and ffmpeg pipe. Module-level
	function so it is picklable for ProcessPoolExecutor.

	Args:
		video_path: Path to input video file.
		crop_rects_chunk: Crop rects for this segment's frames.
		output_path: Output path for the segment file.
		crop_width: Output frame width.
		crop_height: Output frame height.
		start_frame: First frame index for this segment.
		codec: Video codec string.
		crf: Constant Rate Factor.
		frame_states_chunk: Per-frame state dicts for debug overlay, or None.
		debug: If True, draw debug overlay.
		worker_id: Worker index for progress bar positioning.
		total_workers: Total number of workers for display.

	Returns:
		Path to the encoded segment file.
	"""
	reader = VideoReader(video_path)
	info = reader.get_info()
	fps = info["fps"]
	writer = VideoWriter(
		output_path, crop_width, crop_height, fps,
		codec=codec, crf=crf,
	)
	chunk_size = len(crop_rects_chunk)
	# rich progress bar for this worker
	with rich.progress.Progress(
		rich.progress.TextColumn("{task.description}"),
		rich.progress.BarColumn(),
		rich.progress.TaskProgressColumn(),
		rich.progress.TimeRemainingColumn(),
	) as progress:
		task = progress.add_task(
			f"  worker {worker_id + 1}/{total_workers}",
			total=chunk_size,
		)
		# seek to start_frame and read sequentially
		reader.cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
		for local_idx in range(chunk_size):
			ret, frame = reader.cap.read()
			if not ret:
				break
			# crop and resize
			crop_rect = crop_rects_chunk[local_idx]
			cropped = crop.apply_crop(frame, crop_rect)
			resized = cv2.resize(cropped, (crop_width, crop_height))
			# draw debug overlay when requested
			if debug and frame_states_chunk is not None:
				state = frame_states_chunk[local_idx] if local_idx < len(frame_states_chunk) else None
				draw_debug_overlay_cropped(
					resized, state, crop_rect, crop_width, crop_height,
				)
			writer.write_frame(resized)
			progress.update(task, advance=1)
	writer.close()
	reader.close()
	return output_path


#============================================
def encode_cropped_video_parallel(
	video_path: str,
	crop_rects: list,
	output_path: str,
	crop_width: int,
	crop_height: int,
	codec: str = "libx264",
	crf: int = 18,
	frame_states: list | None = None,
	debug: bool = False,
	workers: int = 4,
) -> None:
	"""Encode cropped video using parallel worker processes.

	Splits the frame range into chunks, encodes each chunk in a separate
	process with its own VideoReader and ffmpeg pipe, then concatenates
	the segment files with mkvmerge.

	Falls back to single-threaded encoding if workers <= 1.

	Args:
		video_path: Path to input video file.
		crop_rects: List of (x, y, w, h) tuples, one per frame.
		output_path: Path for the output video file.
		crop_width: Output frame width after resize.
		crop_height: Output frame height after resize.
		codec: Video codec (default libx264).
		crf: Constant Rate Factor (default 18).
		frame_states: List of per-frame state dicts from tracker.
		debug: If True, draw tracking overlay on cropped frames.
		workers: Number of parallel encoding workers.
	"""
	# fall back to sequential if only 1 worker
	if workers <= 1:
		with VideoReader(video_path) as reader:
			encode_cropped_video(
				reader, crop_rects, output_path,
				crop_width, crop_height,
				codec=codec, crf=crf,
				frame_states=frame_states, debug=debug,
			)
		return

	frame_count = len(crop_rects)
	# cap workers to frame count
	actual_workers = min(workers, frame_count)
	# compute chunk boundaries
	chunk_size = frame_count // actual_workers
	remainder = frame_count % actual_workers

	segments = []
	offset = 0
	for w_idx in range(actual_workers):
		# distribute remainder frames across first workers
		this_chunk = chunk_size + (1 if w_idx < remainder else 0)
		end_offset = offset + this_chunk
		# slice crop_rects and frame_states for this chunk
		rects_chunk = crop_rects[offset:end_offset]
		states_chunk = None
		if frame_states is not None:
			states_chunk = frame_states[offset:end_offset]
		# segment output file path
		seg_path = f"{output_path}.seg{w_idx:03d}.mp4"
		segments.append({
			"path": seg_path,
			"rects": rects_chunk,
			"states": states_chunk,
			"start_frame": offset,
			"worker_id": w_idx,
		})
		offset = end_offset

	# launch workers with ProcessPoolExecutor
	seg_paths = []
	with concurrent.futures.ProcessPoolExecutor(max_workers=actual_workers) as pool:
		futures = []
		for seg in segments:
			future = pool.submit(
				_encode_segment,
				video_path,
				seg["rects"],
				seg["path"],
				crop_width, crop_height,
				seg["start_frame"],
				codec, crf,
				seg["states"],
				debug,
				seg["worker_id"],
				actual_workers,
			)
			futures.append((future, seg["path"]))
		# collect results in order
		for future, seg_path in futures:
			future.result()
			seg_paths.append(seg_path)

	# concatenate segments with mkvmerge
	mkvmerge_path = shutil.which("mkvmerge")
	if mkvmerge_path is None:
		raise RuntimeError("mkvmerge not found in PATH for segment concatenation")
	# build mkvmerge command: first file + subsequent with '+'
	concat_cmd = [mkvmerge_path, "-o", output_path]
	for idx, seg_path in enumerate(seg_paths):
		if idx > 0:
			concat_cmd.append("+")
		concat_cmd.append(seg_path)
	result = subprocess.run(concat_cmd, capture_output=True, text=True)
	if result.returncode not in (0, 1):
		# mkvmerge returns 1 for warnings, 2 for errors
		raise RuntimeError(
			f"mkvmerge concat failed (code {result.returncode}): {result.stderr}"
		)

	# clean up segment temp files
	for seg_path in seg_paths:
		if os.path.isfile(seg_path):
			os.remove(seg_path)
