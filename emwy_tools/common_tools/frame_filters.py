"""Image filters for annotation UIs and encode pipelines.

Pure functions that enhance video frames. Display filters improve visual
clarity during manual annotation. Encode filters reduce noise and
sharpen frames in the crop-and-encode pipeline.
"""

# PIP3 modules
import cv2
import numpy

#============================================

# ordered list of available filter presets (annotation UI cycle list)
FILTER_PRESETS = [
	"none", "bilateral", "clahe", "bilateral+clahe",
	"sharpen", "edge_enhance",
]

# encode filter registries: opencv filters run per-frame in python,
# ffmpeg filters run as -vf flags in the ffmpeg encode command
OPENCV_ENCODE_FILTERS = ["bilateral", "clahe", "sharpen", "denoise", "auto_levels"]
FFMPEG_ENCODE_FILTERS = ["hqdn3d", "nlmeans"]
ALL_ENCODE_FILTERS = OPENCV_ENCODE_FILTERS + FFMPEG_ENCODE_FILTERS

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
	if preset == "denoise":
		return apply_denoise(bgr)
	if preset == "auto_levels":
		return apply_auto_levels(bgr)
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


#============================================

def apply_denoise(bgr: numpy.ndarray) -> numpy.ndarray:
	"""Non-local means denoising for colored images.

	Strong spatial denoiser using fastNlMeansDenoisingColored.
	Good for removing compression artifacts and sensor noise
	while preserving edges.

	Args:
		bgr: Input BGR image.

	Returns:
		Denoised BGR image.
	"""
	result = cv2.fastNlMeansDenoisingColored(
		bgr, None, h=10, hForColorComponents=10,
		templateWindowSize=7, searchWindowSize=21,
	)
	return result


#============================================

def apply_auto_levels(bgr: numpy.ndarray) -> numpy.ndarray:
	"""Per-channel percentile histogram stretch.

	Computes the 1st and 99th percentile per BGR channel and
	linearly remaps pixel values to fill the 0-255 range. Helps
	correct washed-out or underexposed footage.

	Args:
		bgr: Input BGR image.

	Returns:
		Level-adjusted BGR image.
	"""
	result = numpy.empty_like(bgr)
	for ch in range(3):
		channel = bgr[:, :, ch]
		# compute 1st and 99th percentile bounds
		low = numpy.percentile(channel, 1)
		high = numpy.percentile(channel, 99)
		if high - low < 1:
			# avoid division by near-zero; channel is nearly flat
			result[:, :, ch] = channel
			continue
		# linear remap from [low, high] to [0, 255]
		scaled = (channel.astype(numpy.float32) - low) / (high - low) * 255.0
		result[:, :, ch] = numpy.clip(scaled, 0, 255).astype(numpy.uint8)
	return result


#============================================

def apply_filter_pipeline(bgr: numpy.ndarray, filter_list: list) -> numpy.ndarray:
	"""Apply opencv encode filters from a filter list in order.

	Skips any ffmpeg filter names in the list (those run in ffmpeg's
	-vf flag instead). Only applies filters from OPENCV_ENCODE_FILTERS.

	Args:
		bgr: Input BGR image.
		filter_list: Ordered list of filter name strings.

	Returns:
		Filtered BGR image after all applicable opencv filters.
	"""
	result = bgr
	for name in filter_list:
		if name not in OPENCV_ENCODE_FILTERS:
			# skip ffmpeg-only filters
			continue
		result = apply_filter(result, name)
	return result


#============================================

def get_ffmpeg_vf_string(filter_list: list) -> str:
	"""Build the ffmpeg -vf value string from a filter list.

	Extracts only ffmpeg filter names from the list, preserving
	order, and joins them with commas. Maps filter names to their
	ffmpeg equivalents.

	Args:
		filter_list: Ordered list of filter name strings.

	Returns:
		Comma-separated ffmpeg filter string, or empty string if none.
	"""
	# map encode filter names to ffmpeg -vf filter syntax
	ffmpeg_filter_map = {
		"hqdn3d": "hqdn3d",
		"nlmeans": "nlmeans",
	}
	parts = []
	for name in filter_list:
		if name in ffmpeg_filter_map:
			parts.append(ffmpeg_filter_map[name])
	result = ",".join(parts)
	return result
