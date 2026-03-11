"""
crop.py

Crop rectangle computation and border fill for stabilize_building.
"""

# Standard Library
import math
import subprocess

# local repo modules
import tools_common

#============================================

def compute_constraint_crop_rect(width: int, height: int, min_area_ratio: float,
	min_height_px: int, center_safe_margin: float) -> dict:
	"""
	Compute a centered crop rectangle that satisfies crop constraints.

	This is used as the fixed crop for border-fill fallback evaluation.

	Args:
		width: Frame width.
		height: Frame height.
		min_area_ratio: Minimum crop area ratio.
		min_height_px: Minimum crop height.
		center_safe_margin: Normalized safe margin inset (0..0.5).

	Returns:
		dict: Crop rectangle {x,y,w,h} or empty {w:0,h:0}.
	"""
	aspect = float(width) / float(height)
	safe_h = float(height) * (1.0 - 2.0 * float(center_safe_margin))
	required_h = max(float(min_height_px), safe_h)
	required_area = float(min_area_ratio) * float(width) * float(height)
	if required_area > 0:
		h_area = math.sqrt(required_area / aspect)
		required_h = max(required_h, h_area)
	if required_h > float(height):
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	required_w = required_h * aspect
	if required_w > float(width):
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	crop_w = int(math.floor(required_w))
	crop_h = int(math.floor(required_h))
	if crop_w <= 0 or crop_h <= 0:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	if crop_w > width:
		crop_w = width
	if crop_h > height:
		crop_h = height
	crop_x = int((width - crop_w) // 2)
	crop_y = int((height - crop_h) // 2)
	return {"x": crop_x, "y": crop_y, "w": crop_w, "h": crop_h}

#============================================

def compute_minimum_centered_crop(width: int, height: int, min_area_ratio: float,
	min_height_px: int) -> dict:
	"""
	Compute the smallest centered crop rectangle that satisfies basic constraints.

	Args:
		width: Frame width.
		height: Frame height.
		min_area_ratio: Minimum crop area ratio.
		min_height_px: Minimum crop height.

	Returns:
		dict: Crop rectangle {x,y,w,h} or empty {w:0,h:0}.
	"""
	aspect = float(width) / float(height)
	required_h = float(min_height_px)
	required_area = float(min_area_ratio) * float(width) * float(height)
	if required_area > 0:
		h_area = math.sqrt(required_area / aspect)
		required_h = max(required_h, h_area)
	if required_h > float(height):
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	required_w = required_h * aspect
	if required_w > float(width):
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	crop_w = int(math.ceil(required_w))
	crop_h = int(math.ceil(required_h))
	if crop_w <= 0 or crop_h <= 0:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	if crop_w > width or crop_h > height:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	crop_x = int((width - crop_w) // 2)
	crop_y = int((height - crop_h) // 2)
	return {"x": crop_x, "y": crop_y, "w": crop_w, "h": crop_h}

#============================================

def compute_valid_bbox(width: int, height: int, dx: float, dy: float) -> tuple[float, float, float, float]:
	"""
	Compute the valid pixel bbox after applying stabilization translation.

	Args:
		width: Frame width.
		height: Frame height.
		dx: Per-frame dx from global motion path.
		dy: Per-frame dy from global motion path.

	Returns:
		tuple[float,float,float,float]: (left, top, right, bottom).
	"""
	shift_x = -float(dx)
	shift_y = -float(dy)
	left = max(0.0, shift_x)
	right = min(float(width), float(width) + shift_x)
	top = max(0.0, shift_y)
	bottom = min(float(height), float(height) + shift_y)
	return left, top, right, bottom

#============================================

def compute_fill_budget(transforms: list, width: int, height: int, crop_rect: dict,
	max_area_ratio: float, max_frames_ratio: float, max_consecutive_frames: int) -> dict:
	"""
	Compute fill budget usage for a fixed crop rectangle over a motion path.

	Args:
		transforms: Per-frame motion transforms.
		width: Frame width.
		height: Frame height.
		crop_rect: Fixed crop rectangle in source pixels.
		max_area_ratio: Maximum fill area ratio allowed per frame.
		max_frames_ratio: Maximum fraction of frames allowed to need fill.
		max_consecutive_frames: Maximum run of consecutive frames allowed to need fill.

	Returns:
		dict: Fill stats including pass/fail.
	"""
	cx = float(crop_rect["x"])
	cy = float(crop_rect["y"])
	cw = float(crop_rect["w"])
	ch = float(crop_rect["h"])
	if cw <= 0 or ch <= 0:
		return {"pass": False, "reason": "invalid crop rectangle"}
	area = cw * ch
	total_frames = 0
	frames_with_fill = 0
	max_fill_ratio = 0.0
	max_gap_px = 0.0
	current_run = 0
	max_run = 0
	for item in transforms:
		if item.get("missing") or item.get("is_reference"):
			continue
		total_frames += 1
		left, top, right, bottom = compute_valid_bbox(width, height, item["dx"], item["dy"])
		ix0 = max(cx, left)
		iy0 = max(cy, top)
		ix1 = min(cx + cw, right)
		iy1 = min(cy + ch, bottom)
		iw = max(0.0, ix1 - ix0)
		ih = max(0.0, iy1 - iy0)
		inter_area = iw * ih
		fill_area = max(0.0, area - inter_area)
		fill_ratio = fill_area / area if area > 0 else 1.0
		if fill_ratio > max_fill_ratio:
			max_fill_ratio = fill_ratio
		needs_fill = fill_area > 0.0
		if needs_fill:
			frames_with_fill += 1
			current_run += 1
			if current_run > max_run:
				max_run = current_run
		else:
			current_run = 0
		gap_left = max(0.0, cx - left)
		gap_right = max(0.0, (cx + cw) - right)
		gap_top = max(0.0, cy - top)
		gap_bottom = max(0.0, (cy + ch) - bottom)
		max_gap_px = max(max_gap_px, gap_left, gap_right, gap_top, gap_bottom)
	frames_ratio = float(frames_with_fill) / float(total_frames) if total_frames > 0 else 1.0
	pass_budget = True
	reasons = []
	if max_fill_ratio > float(max_area_ratio):
		pass_budget = False
		reasons.append("max_area_ratio exceeded")
	if frames_ratio > float(max_frames_ratio):
		pass_budget = False
		reasons.append("max_frames_ratio exceeded")
	if max_consecutive_frames >= 0 and max_run > int(max_consecutive_frames):
		pass_budget = False
		reasons.append("max_consecutive_frames exceeded")
	return {
		"pass": pass_budget,
		"reasons": reasons,
		"total_frames": total_frames,
		"frames_with_fill": frames_with_fill,
		"frames_ratio": frames_ratio,
		"max_consecutive_frames": max_run,
		"max_fill_area_ratio": max_fill_ratio,
		"max_gap_px": max_gap_px,
	}

#============================================

def compute_static_crop(width: int, height: int, transforms: list) -> dict:
	"""
	Compute a single static crop rectangle from per-frame translations.

	Args:
		width: Frame width.
		height: Frame height.
		transforms: Per-frame transforms.

	Returns:
		dict: Crop rectangle {x,y,w,h} in source pixels.
	"""
	left = 0.0
	top = 0.0
	right = float(width)
	bottom = float(height)
	for item in transforms:
		if item.get("missing"):
			continue
		shift_x = -float(item["dx"])
		shift_y = -float(item["dy"])
		frame_left = max(0.0, shift_x)
		frame_right = min(float(width), float(width) + shift_x)
		frame_top = max(0.0, shift_y)
		frame_bottom = min(float(height), float(height) + shift_y)
		left = max(left, frame_left)
		right = min(right, frame_right)
		top = max(top, frame_top)
		bottom = min(bottom, frame_bottom)
	x0 = int(math.ceil(left))
	y0 = int(math.ceil(top))
	x1 = int(math.floor(right))
	y1 = int(math.floor(bottom))
	raw_w = x1 - x0
	raw_h = y1 - y0
	if raw_w <= 0 or raw_h <= 0:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	desired_aspect = float(width) / float(height)
	if float(raw_w) / float(raw_h) > desired_aspect:
		crop_h = raw_h
		crop_w = int(math.floor(float(crop_h) * desired_aspect))
	else:
		crop_w = raw_w
		crop_h = int(math.floor(float(crop_w) / desired_aspect))
	if crop_w <= 0 or crop_h <= 0:
		return {"x": 0, "y": 0, "w": 0, "h": 0}
	crop_x = x0 + (raw_w - crop_w) // 2
	crop_y = y0 + (raw_h - crop_h) // 2
	return {"x": int(crop_x), "y": int(crop_y), "w": int(crop_w), "h": int(crop_h)}

#============================================

def crop_constraints_ok(width: int, height: int, crop_rect: dict,
	min_area_ratio: float, min_height_px: int, center_safe_margin: float) -> tuple[bool, list]:
	"""
	Check crop constraints.

	Args:
		width: Frame width.
		height: Frame height.
		crop_rect: Crop rectangle dict.
		min_area_ratio: Minimum area ratio.
		min_height_px: Minimum crop height in pixels.
		center_safe_margin: Normalized safe margin.

	Returns:
		tuple[bool, list]: (ok, reasons)
	"""
	reasons = []
	cw = int(crop_rect.get("w", 0))
	ch = int(crop_rect.get("h", 0))
	cx = int(crop_rect.get("x", 0))
	cy = int(crop_rect.get("y", 0))
	if cw <= 0 or ch <= 0:
		reasons.append("crop rectangle is empty")
		return False, reasons
	if cw > width or ch > height:
		reasons.append("crop rectangle exceeds frame bounds")
		return False, reasons
	if cx < 0 or cy < 0 or (cx + cw) > width or (cy + ch) > height:
		reasons.append("crop rectangle is out of bounds")
		return False, reasons
	area_ratio = (float(cw) * float(ch)) / (float(width) * float(height))
	if area_ratio < float(min_area_ratio):
		reasons.append("crop area below min_area_ratio")
	if ch < int(min_height_px):
		reasons.append("crop height below min_height_px")
	safe_left = float(width) * float(center_safe_margin)
	safe_top = float(height) * float(center_safe_margin)
	safe_right = float(width) - safe_left
	safe_bottom = float(height) - safe_top
	if float(cx) > safe_left or float(cy) > safe_top:
		reasons.append("crop does not include center safe region (left/top)")
	if float(cx + cw) < safe_right or float(cy + ch) < safe_bottom:
		reasons.append("crop does not include center safe region (right/bottom)")
	return len(reasons) == 0, reasons

#============================================

def crop_basic_constraints_ok(width: int, height: int, crop_rect: dict,
	min_area_ratio: float, min_height_px: int) -> tuple[bool, list]:
	"""
	Check crop constraints without enforcing a center safe region.

	Args:
		width: Frame width.
		height: Frame height.
		crop_rect: Crop rectangle dict.
		min_area_ratio: Minimum crop area ratio.
		min_height_px: Minimum crop height in pixels.

	Returns:
		tuple[bool, list]: (ok, reasons)
	"""
	reasons = []
	cw = int(crop_rect.get("w", 0))
	ch = int(crop_rect.get("h", 0))
	cx = int(crop_rect.get("x", 0))
	cy = int(crop_rect.get("y", 0))
	if cw <= 0 or ch <= 0:
		reasons.append("crop rectangle is empty")
		return False, reasons
	if cw > width or ch > height:
		reasons.append("crop rectangle exceeds frame bounds")
		return False, reasons
	if cx < 0 or cy < 0 or (cx + cw) > width or (cy + ch) > height:
		reasons.append("crop rectangle is out of bounds")
		return False, reasons
	area_ratio = (float(cw) * float(ch)) / (float(width) * float(height))
	if area_ratio < float(min_area_ratio):
		reasons.append("crop area below min_area_ratio")
	if ch < int(min_height_px):
		reasons.append("crop height below min_height_px")
	return len(reasons) == 0, reasons

#============================================

def compute_center_patch_median_color(input_file: str, width: int, height: int,
	start_seconds: float | None, duration_seconds: float | None,
	patch_fraction: float, sample_frames: int) -> dict:
	"""
	Compute a deterministic fill color from a center patch sampled over time.

	This uses ffmpeg to extract a 1x1 RGB sample of a center patch on N frames.
	The final fill color is the per-channel median over those samples.

	Args:
		input_file: Input media file.
		width: Frame width.
		height: Frame height.
		start_seconds: Optional start time for sampling.
		duration_seconds: Optional duration for sampling.
		patch_fraction: Patch fraction of width/height (0..0.5).
		sample_frames: Number of samples.

	Returns:
		dict: {"color": "#rrggbb", "samples": sample_frames}.
	"""
	import stabilize
	start = 0.0 if start_seconds is None else float(start_seconds)
	if duration_seconds is None:
		total = tools_common.probe_duration_seconds(input_file)
		duration = max(0.0, total - start)
	else:
		duration = float(duration_seconds)
	if duration <= 0:
		raise RuntimeError("invalid duration for fill color sampling")
	patch_w = max(1, int(round(float(width) * float(patch_fraction))))
	patch_h = max(1, int(round(float(height) * float(patch_fraction))))
	if patch_w > width:
		patch_w = width
	if patch_h > height:
		patch_h = height
	patch_x = int((width - patch_w) // 2)
	patch_y = int((height - patch_h) // 2)
	reds = []
	greens = []
	blues = []
	count = int(sample_frames)
	if count <= 0:
		raise RuntimeError("sample_frames must be positive")
	for i in range(count):
		t = start + ((float(i) + 0.5) * duration / float(count))
		cmd = [
			"ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
			"-ss", f"{t}",
			"-i", input_file,
			"-frames:v", "1",
			"-an", "-sn",
			"-vf", f"crop={patch_w}:{patch_h}:{patch_x}:{patch_y},scale=1:1:flags=area,format=rgb24",
			"-f", "rawvideo",
			"-",
		]
		proc = subprocess.run(cmd, capture_output=True)
		if proc.returncode != 0:
			raise RuntimeError("ffmpeg failed while sampling fill color")
		data = proc.stdout
		if len(data) < 3:
			raise RuntimeError("ffmpeg did not return RGB bytes for fill color")
		reds.append(float(data[0]))
		greens.append(float(data[1]))
		blues.append(float(data[2]))
	color = stabilize.rgb_hex(int(round(median(reds))), int(round(median(greens))), int(round(median(blues))))
	return {"color": color, "samples": count, "patch_fraction": float(patch_fraction)}

#============================================

def median(values: list[float]) -> float:
	"""
	Compute median of a list of floats.

	Args:
		values: Values list.

	Returns:
		float: Median value.
	"""
	if len(values) == 0:
		raise RuntimeError("median() requires at least one value")
	items = sorted(values)
	mid = len(items) // 2
	if len(items) % 2 == 1:
		return float(items[mid])
	return (float(items[mid - 1]) + float(items[mid])) / 2.0

#============================================

def mad(values: list[float]) -> float:
	"""
	Compute median absolute deviation of a list of floats.

	Args:
		values: Values list.

	Returns:
		float: MAD value.
	"""
	center = median(values)
	dev = [abs(v - center) for v in values]
	return median(dev)
