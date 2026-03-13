"""Adaptive crop trajectory module for track_runner.

Computes smoothed crop rectangles that follow a tracked subject,
using exponential smoothing with deadband and velocity capping.
Pure numpy, no other dependencies.
"""

# Standard Library
import math

# PIP3 modules
import numpy


#============================================
def parse_aspect_ratio(aspect_str: str) -> float:
	"""Parse an aspect ratio string into a float.

	Args:
		aspect_str: Ratio string like '16:9', '4:3', or '1:1'.

	Returns:
		Float value of width divided by height.

	Raises:
		RuntimeError: If the string is not in 'W:H' format or
			contains non-numeric parts.
	"""
	parts = aspect_str.split(":")
	if len(parts) != 2:
		raise RuntimeError(
			f"Invalid aspect ratio format '{aspect_str}', expected 'W:H'"
		)
	try:
		w = float(parts[0])
		h = float(parts[1])
	except ValueError:
		raise RuntimeError(
			f"Non-numeric aspect ratio '{aspect_str}'"
		)
	if h == 0:
		raise RuntimeError(
			f"Aspect ratio height cannot be zero: '{aspect_str}'"
		)
	ratio = w / h
	return ratio


#============================================
class CropController:
	"""Adaptive crop controller that smoothly follows a tracked target.

	Uses exponential smoothing with deadband, confidence modulation,
	and velocity capping to produce stable crop trajectories.
	"""

	def __init__(
		self,
		frame_width: int,
		frame_height: int,
		aspect_ratio: float = 1.0,
		target_fill_ratio: float = 0.30,
		far_fill_ratio: float = 0.50,
		far_threshold_px: int = 120,
		very_far_fill_ratio: float = 0.65,
		very_far_threshold_px: int = 60,
		smoothing_attack: float = 0.15,
		smoothing_release: float = 0.05,
		max_crop_velocity: float = 30.0,
		min_crop_size: int = 200,
		deadband_fraction: float = 0.02,
	):
		"""Initialize the crop controller.

		Args:
			frame_width: Width of the source video frame in pixels.
			frame_height: Height of the source video frame in pixels.
			aspect_ratio: Output crop width/height ratio (1.0 for square).
			target_fill_ratio: Fraction of crop height the target should fill (baseline).
			far_fill_ratio: Fill ratio when runner is small (far away).
			far_threshold_px: Bbox height at which far_fill_ratio fully applies.
			very_far_fill_ratio: Fill ratio when runner is very small (very far away).
			very_far_threshold_px: Bbox height at which very_far_fill_ratio fully applies.
			smoothing_attack: Alpha for large corrections (fast response).
			smoothing_release: Alpha for small corrections (slow drift).
			max_crop_velocity: Maximum pixels the crop center can move per frame.
			min_crop_size: Minimum crop height in pixels.
			deadband_fraction: Fraction of crop size below which errors are ignored.
		"""
		self.frame_width = frame_width
		self.frame_height = frame_height
		self.aspect_ratio = aspect_ratio
		self.target_fill_ratio = target_fill_ratio
		self.far_fill_ratio = far_fill_ratio
		self.far_threshold_px = far_threshold_px
		self.very_far_fill_ratio = very_far_fill_ratio
		self.very_far_threshold_px = very_far_threshold_px
		self.smoothing_attack = smoothing_attack
		self.smoothing_release = smoothing_release
		self.max_crop_velocity = max_crop_velocity
		self.min_crop_size = min_crop_size
		self.deadband_fraction = deadband_fraction
		# Smoothed crop state, initialized on first update
		self.smooth_cx = None
		self.smooth_cy = None
		self.smooth_size = None

	#============================================
	def update(
		self,
		state: dict,
	) -> tuple:
		"""Update crop position given a tracking state dict.

		Args:
			state: Tracking state with keys:
				'cx' (float): center x of tracked subject in pixels,
				'cy' (float): center y of tracked subject in pixels,
				'w' (float): bounding box width in pixels,
				'h' (float): bounding box height in pixels,
				'conf' (float): tracking confidence 0.0 to 1.0,
				'source' (str): source label for the tracking state.

		Returns:
			Tuple of (crop_x, crop_y, crop_w, crop_h) as integer pixel
			coordinates where crop_x, crop_y is the top-left corner.
		"""
		fw = self.frame_width
		fh = self.frame_height
		tcx = state["cx"]
		tcy = state["cy"]
		# bounding box width is not used; only height drives fill ratio
		th = state["h"]
		confidence = state["conf"]

		# Step 1: compute adaptive fill ratio based on runner height
		# three tiers: very far, far, and normal with linear interpolation
		if th <= self.very_far_threshold_px:
			# very far: tightest crop
			fill = self.very_far_fill_ratio
		elif th <= self.far_threshold_px:
			# interpolate between very_far and far fill ratios
			t = (th - self.very_far_threshold_px) / (self.far_threshold_px - self.very_far_threshold_px)
			fill = self.very_far_fill_ratio + t * (self.far_fill_ratio - self.very_far_fill_ratio)
		elif th >= self.far_threshold_px * 3:
			# normal/close: baseline fill ratio
			fill = self.target_fill_ratio
		else:
			# interpolate between far and baseline fill ratios
			t = (th - self.far_threshold_px) / (self.far_threshold_px * 2)
			fill = self.far_fill_ratio + t * (self.target_fill_ratio - self.far_fill_ratio)
		desired_crop_h = th / fill
		# clamp crop height to valid range
		desired_crop_h = max(self.min_crop_size, min(desired_crop_h, fh))
		# compute crop width from aspect ratio
		desired_crop_w = desired_crop_h * self.aspect_ratio
		# clamp crop width to frame width
		if desired_crop_w > fw:
			desired_crop_w = float(fw)
			# adjust height to maintain aspect ratio
			desired_crop_h = desired_crop_w / self.aspect_ratio

		# Step 2: desired center is the target center
		desired_cx = tcx
		desired_cy = tcy

		# Step 3: first frame snaps directly to desired values
		if self.smooth_cx is None:
			self.smooth_cx = desired_cx
			self.smooth_cy = desired_cy
			self.smooth_size = desired_crop_h
		else:
			# Step 4: exponential smoothing with deadband
			# threshold for choosing attack vs release alpha
			attack_threshold = self.deadband_fraction * self.smooth_size * 4.0
			deadband = self.deadband_fraction * self.smooth_size

			# save old values for velocity capping
			old_cx = self.smooth_cx
			old_cy = self.smooth_cy

			# smooth center x
			error_cx = desired_cx - self.smooth_cx
			if abs(error_cx) >= deadband:
				alpha = self.smoothing_attack if abs(error_cx) > attack_threshold else self.smoothing_release
				alpha *= confidence
				# floor prevents crop from freezing at very low confidence
				alpha = max(alpha, 0.02)
				self.smooth_cx += alpha * error_cx

			# smooth center y
			error_cy = desired_cy - self.smooth_cy
			if abs(error_cy) >= deadband:
				alpha = self.smoothing_attack if abs(error_cy) > attack_threshold else self.smoothing_release
				alpha *= confidence
				alpha = max(alpha, 0.02)
				self.smooth_cy += alpha * error_cy

			# smooth crop size
			error_size = desired_crop_h - self.smooth_size
			if abs(error_size) >= deadband:
				alpha = self.smoothing_attack if abs(error_size) > attack_threshold else self.smoothing_release
				alpha *= confidence
				alpha = max(alpha, 0.02)
				self.smooth_size += alpha * error_size

			# Step 5: cap per-frame velocity on center
			delta_cx = self.smooth_cx - old_cx
			if abs(delta_cx) > self.max_crop_velocity:
				# clamp to max velocity, preserving sign
				self.smooth_cx = old_cx + math.copysign(self.max_crop_velocity, delta_cx)

			delta_cy = self.smooth_cy - old_cy
			if abs(delta_cy) > self.max_crop_velocity:
				self.smooth_cy = old_cy + math.copysign(self.max_crop_velocity, delta_cy)

		# Step 6: compute integer crop rectangle
		crop_h = self.smooth_size
		crop_w = crop_h * self.aspect_ratio
		crop_x = self.smooth_cx - crop_w / 2.0
		crop_y = self.smooth_cy - crop_h / 2.0

		# clamp to frame bounds
		crop_x = max(0.0, min(crop_x, fw - crop_w))
		crop_y = max(0.0, min(crop_y, fh - crop_h))

		result = (int(crop_x), int(crop_y), int(crop_w), int(crop_h))
		return result

	#============================================
	def reset(self) -> None:
		"""Reset smoother state."""
		self.smooth_cx = None
		self.smooth_cy = None
		self.smooth_size = None

	#============================================
	def get_state(self) -> dict | None:
		"""Return current smoothed state or None if uninitialized."""
		if self.smooth_cx is None:
			return None
		state = {
			"cx": self.smooth_cx,
			"cy": self.smooth_cy,
			"size": self.smooth_size,
		}
		return state


#============================================
def apply_crop(frame: numpy.ndarray, crop_rect: tuple) -> numpy.ndarray:
	"""Apply a crop rectangle to a frame array.

	If the crop extends beyond frame bounds, the out-of-bounds area
	is filled with black (zero padding).

	Args:
		frame: Source frame as a numpy array (H, W, C) or (H, W).
		crop_rect: (x, y, w, h) integer pixel coordinates for the crop.

	Returns:
		Cropped numpy array with the requested dimensions.
	"""
	fh, fw = frame.shape[:2]
	cx, cy, cw, ch = crop_rect

	# determine if the crop is fully inside the frame
	src_x1 = max(cx, 0)
	src_y1 = max(cy, 0)
	src_x2 = min(cx + cw, fw)
	src_y2 = min(cy + ch, fh)

	# offsets into the output where the valid pixels go
	dst_x1 = src_x1 - cx
	dst_y1 = src_y1 - cy
	dst_x2 = dst_x1 + (src_x2 - src_x1)
	dst_y2 = dst_y1 + (src_y2 - src_y1)

	# allocate output filled with black
	if frame.ndim == 3:
		out_shape = (ch, cw, frame.shape[2])
	else:
		out_shape = (ch, cw)
	output = numpy.zeros(out_shape, dtype=frame.dtype)

	# copy the valid region
	if src_x2 > src_x1 and src_y2 > src_y1:
		output[dst_y1:dst_y2, dst_x1:dst_x2] = frame[src_y1:src_y2, src_x1:src_x2]

	return output


#============================================
def create_crop_controller(
	config: dict,
	frame_width: int,
	frame_height: int,
) -> CropController:
	"""Factory to create a CropController from a config dictionary.

	Reads crop settings from config['processing'] and returns
	a configured CropController instance.

	Args:
		config: Project configuration dictionary with a 'processing' section.
		frame_width: Width of the source video frame.
		frame_height: Height of the source video frame.

	Returns:
		Configured CropController instance.

	Raises:
		KeyError: If config is missing 'processing' or required keys.
	"""
	# require the processing section and crop_aspect key
	processing = config["processing"]
	aspect_str = processing["crop_aspect"]
	aspect_ratio = parse_aspect_ratio(aspect_str)

	# crop_fill_ratio is in the default config schema, require it
	target_fill_ratio = float(processing["crop_fill_ratio"])
	# tuning parameters with sensible defaults
	smoothing_attack = float(processing.get("crop_smoothing_attack", 0.15))
	smoothing_release = float(processing.get("crop_smoothing_release", 0.05))
	max_crop_velocity = float(processing.get("crop_max_velocity", 30.0))
	min_crop_size = int(processing.get("crop_min_size", 200))
	far_fill_ratio = float(processing.get("crop_far_fill_ratio", 0.50))
	far_threshold_px = int(processing.get("crop_far_threshold_px", 120))
	very_far_fill_ratio = float(processing.get("crop_very_far_fill_ratio", 0.65))
	very_far_threshold_px = int(processing.get("crop_very_far_threshold_px", 60))

	controller = CropController(
		frame_width=frame_width,
		frame_height=frame_height,
		aspect_ratio=aspect_ratio,
		target_fill_ratio=target_fill_ratio,
		far_fill_ratio=far_fill_ratio,
		far_threshold_px=far_threshold_px,
		very_far_fill_ratio=very_far_fill_ratio,
		very_far_threshold_px=very_far_threshold_px,
		smoothing_attack=smoothing_attack,
		smoothing_release=smoothing_release,
		max_crop_velocity=max_crop_velocity,
		min_crop_size=min_crop_size,
	)
	return controller


#============================================
def compute_crop_trajectory(
	trajectory: list,
	frame_width: int,
	frame_height: int,
	config: dict,
) -> list:
	"""Compute a smoothed crop rectangle for each frame in a trajectory.

	Creates a CropController from config, feeds each tracking state through
	it in order, and returns the resulting crop rectangles.

	Args:
		trajectory: List of tracking state dicts, one per frame. Each dict
			must have keys 'cx', 'cy', 'w', 'h', 'conf', and 'source'.
		frame_width: Width of the source video frame in pixels.
		frame_height: Height of the source video frame in pixels.
		config: Project configuration dictionary passed to create_crop_controller.

	Returns:
		List of (crop_x, crop_y, crop_w, crop_h) tuples, one per frame,
		as integer pixel coordinates where crop_x, crop_y is the top-left corner.
	"""
	controller = create_crop_controller(config, frame_width, frame_height)
	crop_rects = []
	for state in trajectory:
		rect = controller.update(state)
		crop_rects.append(rect)
	return crop_rects


#============================================
def trajectory_to_crop_rects(
	trajectory: list,
	video_info: dict,
	config: dict,
) -> list:
	"""Compute crop rectangles from a solved trajectory with gap filling.

	Fills None gaps in the trajectory with a center-frame fallback state
	before passing to compute_crop_trajectory. Pads or trims to match
	the total frame count from video_info.

	Args:
		trajectory: List of tracking state dicts from interval_solver.
			May contain None entries for unsolved frames.
		video_info: Dict with frame_count, width, height, fps.
		config: Project configuration dict.

	Returns:
		List of (x, y, w, h) crop rectangles, one per frame.
	"""
	frame_width = video_info["width"]
	frame_height = video_info["height"]
	total_frames = video_info["frame_count"]

	# fill any None gaps by holding last known position with decaying confidence
	# instead of snapping to center-frame which pulls the crop away from the runner
	last_known = None
	full_trajectory = []
	for i in range(total_frames):
		if i < len(trajectory) and trajectory[i] is not None:
			full_trajectory.append(trajectory[i])
			last_known = trajectory[i]
		elif last_known is not None:
			# hold last known position with reduced confidence
			hold_state = {
				"cx": last_known["cx"],
				"cy": last_known["cy"],
				"w": last_known["w"],
				"h": last_known["h"],
				"conf": 0.15,
				"source": "hold_last",
			}
			full_trajectory.append(hold_state)
		else:
			# no prior position yet, use center-frame as last resort
			fallback = {
				"cx": frame_width / 2.0,
				"cy": frame_height / 2.0,
				"w": float(frame_width) * 0.3,
				"h": float(frame_height) * 0.5,
				"conf": 0.1,
				"source": "fallback",
			}
			full_trajectory.append(fallback)

	# compute smoothed crop trajectory
	crop_rects = compute_crop_trajectory(
		full_trajectory, frame_width, frame_height, config,
	)
	return crop_rects
