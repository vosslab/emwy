"""Shared geometric and drawing utilities for bounding boxes.

All bounding boxes use center-format dicts with keys cx, cy, w, h (float
values, pixel coordinates). Conversion helpers preserve exact arithmetic
to match the inline patterns they replace.
"""

# PIP3 modules
import cv2
import numpy


#============================================
def center_to_corners(
	cx: float,
	cy: float,
	w: float,
	h: float,
) -> tuple:
	"""Convert center-format box to corner coordinates.

	Pure float arithmetic with no rounding or clamping.

	Args:
		cx: Center x coordinate.
		cy: Center y coordinate.
		w: Box width.
		h: Box height.

	Returns:
		Tuple (x1, y1, x2, y2) as floats.
	"""
	x1 = cx - w / 2.0
	y1 = cy - h / 2.0
	x2 = cx + w / 2.0
	y2 = cy + h / 2.0
	result = (x1, y1, x2, y2)
	return result


#============================================
def clamp_box_to_frame(
	cx: float,
	cy: float,
	w: float,
	h: float,
	frame_w: int,
	frame_h: int,
) -> tuple:
	"""Convert center-format box to clamped integer corner coordinates.

	Converts center to corners, clamps to [0, frame_w) x [0, frame_h),
	and truncates to int via int() (toward zero). Matches the existing
	inline pattern: int(max(0, cx - w / 2.0)).

	Degenerate boxes (w <= 0 or h <= 0) may produce x2 <= x1 or y2 <= y1.
	Callers are responsible for checking degenerate results.

	Args:
		cx: Center x coordinate.
		cy: Center y coordinate.
		w: Box width.
		h: Box height.
		frame_w: Frame width in pixels.
		frame_h: Frame height in pixels.

	Returns:
		Tuple (x1, y1, x2, y2) as ints, clamped to frame bounds.
	"""
	x1 = int(max(0, cx - w / 2.0))
	y1 = int(max(0, cy - h / 2.0))
	x2 = int(min(frame_w, cx + w / 2.0))
	y2 = int(min(frame_h, cy + h / 2.0))
	result = (x1, y1, x2, y2)
	return result


#============================================
def compute_iou(box_a: dict, box_b: dict) -> float:
	"""Compute Intersection over Union for two center-format bounding boxes.

	Args:
		box_a: Dict with cx, cy, w, h keys.
		box_b: Dict with cx, cy, w, h keys.

	Returns:
		IoU value in [0.0, 1.0]. Returns 0.0 for degenerate or zero-union boxes.
	"""
	# convert center format to corner coordinates
	ax1 = box_a["cx"] - box_a["w"] / 2.0
	ay1 = box_a["cy"] - box_a["h"] / 2.0
	ax2 = box_a["cx"] + box_a["w"] / 2.0
	ay2 = box_a["cy"] + box_a["h"] / 2.0

	bx1 = box_b["cx"] - box_b["w"] / 2.0
	by1 = box_b["cy"] - box_b["h"] / 2.0
	bx2 = box_b["cx"] + box_b["w"] / 2.0
	by2 = box_b["cy"] + box_b["h"] / 2.0

	# intersection rectangle
	ix1 = max(ax1, bx1)
	iy1 = max(ay1, by1)
	ix2 = min(ax2, bx2)
	iy2 = min(ay2, by2)

	inter_w = max(0.0, ix2 - ix1)
	inter_h = max(0.0, iy2 - iy1)
	inter_area = inter_w * inter_h

	# individual areas
	area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
	area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
	union_area = area_a + area_b - inter_area

	if union_area <= 0.0:
		return 0.0

	iou = inter_area / union_area
	return float(iou)


#============================================
def draw_transparent_rect(
	frame: numpy.ndarray,
	x1: int,
	y1: int,
	x2: int,
	y2: int,
	color: tuple,
	alpha: float,
	border: int = 2,
) -> None:
	"""Draw a filled rectangle with alpha blending and a solid border.

	Modifies frame in-place. Creates an overlay copy, draws a filled
	rectangle on it, alpha-blends back onto the frame, then draws
	a solid border on top.

	Args:
		frame: BGR image array to draw on (modified in-place).
		x1: Left edge pixel coordinate.
		y1: Top edge pixel coordinate.
		x2: Right edge pixel coordinate (exclusive).
		y2: Bottom edge pixel coordinate (exclusive).
		color: BGR color tuple for fill and border.
		alpha: Opacity of the filled rectangle (0.0 to 1.0).
		border: Border thickness in pixels.
	"""
	# create overlay for alpha blending
	overlay = frame.copy()
	cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
	cv2.addWeighted(overlay, alpha, frame, 1.0 - alpha, 0, frame)
	# draw solid border on top
	cv2.rectangle(frame, (x1, y1), (x2, y2), color, border)
