"""Display-only image filters for annotation UIs.

Pure functions that enhance video frames for visual clarity during
manual annotation. Filters do not affect detection or color extraction.
"""

# PIP3 modules
import cv2
import numpy

#============================================

# ordered list of available filter presets
FILTER_PRESETS = [
	"none", "bilateral", "clahe", "bilateral+clahe",
	"sharpen", "edge_enhance",
]

#============================================

def get_filter_presets() -> list:
	"""Return the ordered list of filter preset names.

	Returns:
		List of preset name strings.
	"""
	return list(FILTER_PRESETS)

#============================================

def get_next_preset(current: str) -> str:
	"""Cycle to the next filter preset.

	Args:
		current: Name of the current preset.

	Returns:
		Name of the next preset in the cycle.
	"""
	idx = FILTER_PRESETS.index(current) if current in FILTER_PRESETS else -1
	next_idx = (idx + 1) % len(FILTER_PRESETS)
	result = FILTER_PRESETS[next_idx]
	return result

#============================================

def apply_filter(bgr: numpy.ndarray, preset: str) -> numpy.ndarray:
	"""Apply a named display filter to a BGR frame.

	Args:
		bgr: Input BGR image as numpy array.
		preset: Filter preset name from FILTER_PRESETS.

	Returns:
		Filtered BGR image (may be a new array or the original).
	"""
	if preset == "none":
		return bgr
	if preset == "bilateral":
		return apply_bilateral(bgr)
	if preset == "clahe":
		return apply_clahe(bgr)
	if preset == "sharpen":
		return apply_sharpen(bgr)
	if preset == "bilateral+clahe":
		return apply_bilateral_clahe(bgr)
	if preset == "edge_enhance":
		return apply_edge_enhance(bgr)
	# unknown preset, return unchanged
	return bgr

#============================================

def apply_bilateral(bgr: numpy.ndarray) -> numpy.ndarray:
	"""Bilateral filter: smooths noise while preserving edges.

	Args:
		bgr: Input BGR image.

	Returns:
		Filtered BGR image.
	"""
	result = cv2.bilateralFilter(bgr, d=9, sigmaColor=75, sigmaSpace=75)
	return result

#============================================

def apply_clahe(bgr: numpy.ndarray) -> numpy.ndarray:
	"""CLAHE adaptive contrast enhancement on the L channel.

	Converts to LAB, applies CLAHE to the lightness channel,
	then converts back. Good for low-light footage.

	Args:
		bgr: Input BGR image.

	Returns:
		Contrast-enhanced BGR image.
	"""
	# convert BGR to LAB color space
	lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
	# split into channels
	l_channel, a_channel, b_channel = cv2.split(lab)
	# apply CLAHE to lightness channel
	clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
	l_enhanced = clahe.apply(l_channel)
	# merge channels back and convert to BGR
	lab_enhanced = cv2.merge([l_enhanced, a_channel, b_channel])
	result = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)
	return result

#============================================

def apply_bilateral_clahe(bgr: numpy.ndarray) -> numpy.ndarray:
	"""Bilateral noise reduction followed by CLAHE contrast enhancement.

	Smooths noise first, then boosts local contrast. Best for noisy
	low-light footage where neither filter alone is sufficient.

	Args:
		bgr: Input BGR image.

	Returns:
		Denoised and contrast-enhanced BGR image.
	"""
	smoothed = apply_bilateral(bgr)
	result = apply_clahe(smoothed)
	return result

#============================================

def apply_sharpen(bgr: numpy.ndarray) -> numpy.ndarray:
	"""Unsharp mask sharpening to make silhouettes pop.

	Subtracts a Gaussian blur from the original with gain
	to enhance edges.

	Args:
		bgr: Input BGR image.

	Returns:
		Sharpened BGR image.
	"""
	# create blurred version for unsharp mask
	blurred = cv2.GaussianBlur(bgr, (0, 0), sigmaX=3)
	# apply unsharp mask: original + gain * (original - blurred)
	gain = 1.5
	result = cv2.addWeighted(bgr, 1.0 + gain, blurred, -gain, 0)
	return result

#============================================

def apply_edge_enhance(bgr: numpy.ndarray) -> numpy.ndarray:
	"""Blend original with Laplacian edge map for edge highlighting.

	Adds a subtle edge overlay to help distinguish person outlines
	against cluttered backgrounds.

	Args:
		bgr: Input BGR image.

	Returns:
		Edge-enhanced BGR image.
	"""
	# convert to grayscale for edge detection
	gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
	# compute Laplacian edges
	edges = cv2.Laplacian(gray, cv2.CV_64F)
	# take absolute value and convert to uint8
	edges_abs = numpy.uint8(numpy.clip(numpy.abs(edges), 0, 255))
	# convert single channel edges to 3-channel for blending
	edges_bgr = cv2.cvtColor(edges_abs, cv2.COLOR_GRAY2BGR)
	# blend original with edge map
	blend_weight = 0.3
	result = cv2.addWeighted(bgr, 1.0, edges_bgr, blend_weight, 0)
	return result
