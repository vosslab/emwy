"""Shared test helpers for track_runner test modules."""

# Standard Library
import os

# PIP3 modules
import cv2
import numpy

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

# paths for optional integration tests
YOLO_WEIGHTS_PATH = os.path.join(
	os.path.expanduser("~"), ".cache", "track_runner", "yolov8n.onnx"
)
HAS_YOLO_WEIGHTS = os.path.isfile(YOLO_WEIGHTS_PATH)
TEST_VIDEO = os.path.join(REPO_ROOT, "TRACK_VIDEOS", "Track_Test-1.mov")
HAS_TEST_VIDEO = os.path.isfile(TEST_VIDEO)


#============================================
def _make_track_state(cx: float, cy: float, w: float, h: float) -> dict:
	"""Build a minimal v2 tracking state dict."""
	return {"cx": cx, "cy": cy, "w": w, "h": h, "conf": 0.9, "source": "propagated"}


#============================================
def _make_crop_state(cx: float, cy: float, h: float, conf: float = 1.0) -> dict:
	"""Build a minimal v2 tracking state dict for crop tests."""
	return {"cx": cx, "cy": cy, "w": h * 0.5, "h": h, "conf": conf, "source": "propagated"}


#============================================
def _make_test_diagnostics(confidence: str = "low", reasons: list | None = None) -> dict:
	"""Build a minimal diagnostics dict for review tests."""
	if reasons is None:
		reasons = ["low_agreement"]
	return {
		"fps": 30.0,
		"intervals": [
			{
				"start_frame": 0,
				"end_frame": 300,
				"interval_score": {
					"confidence": "high",
					"failure_reasons": [],
					"agreement_score": 0.9,
					"identity_score": 0.85,
					"competitor_margin": 0.75,
				},
			},
			{
				"start_frame": 300,
				"end_frame": 600,
				"interval_score": {
					"confidence": confidence,
					"failure_reasons": reasons,
					"agreement_score": 0.3,
					"identity_score": 0.8,
					"competitor_margin": 0.7,
				},
			},
		],
	}


#============================================
def _make_trajectory(
	n_frames: int,
	cx: float = 640.0,
	cy: float = 360.0,
	w: float = 100.0,
	h: float = 150.0,
	conf: float = 0.5,
) -> list:
	"""Create a uniform trajectory for testing anchor_to_seeds."""
	trajectory = []
	for i in range(n_frames):
		state = {
			"cx": cx, "cy": cy, "w": w, "h": h,
			"conf": conf, "source": "merged",
		}
		trajectory.append(state)
	return trajectory


#============================================
def _make_seed(
	frame_index: int,
	cx: float = 640.0,
	cy: float = 360.0,
	w: float = 100.0,
	h: float = 150.0,
	status: str = "visible",
) -> dict:
	"""Create a seed dict for testing anchor_to_seeds."""
	# torso_box stores [x, y, w, h] (top-left corner)
	tx = cx - w / 2.0
	ty = cy - h / 2.0
	seed = {
		"frame_index": frame_index,
		"status": status,
		"torso_box": [tx, ty, w, h],
		"cx": cx,
		"cy": cy,
		"w": w,
		"h": h,
		"pass": 1,
	}
	return seed


#============================================
def _make_solid_patch(bgr_color: tuple, size: int = 80) -> numpy.ndarray:
	"""Create a solid-color BGR patch for testing.

	Args:
		bgr_color: (B, G, R) tuple for the patch color.
		size: Side length of the square patch in pixels.

	Returns:
		BGR numpy array of shape (size, size, 3).
	"""
	patch = numpy.zeros((size, size, 3), dtype=numpy.uint8)
	patch[:, :] = bgr_color
	return patch


#============================================
def _make_appearance_model(bgr_color: tuple, size: int = 80) -> dict:
	"""Build a minimal appearance model from a solid-color patch.

	Args:
		bgr_color: (B, G, R) tuple for the model color.
		size: Side length of the square patch.

	Returns:
		Appearance model dict with hsv_mean, template, and hs_histogram.
	"""
	patch = _make_solid_patch(bgr_color, size)
	hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
	hsv_mean = (
		float(numpy.mean(hsv[:, :, 0])),
		float(numpy.mean(hsv[:, :, 1])),
		float(numpy.mean(hsv[:, :, 2])),
	)
	# compute 2D HS histogram matching propagator.build_appearance_model
	hs_histogram = cv2.calcHist(
		[hsv], [0, 1], None,
		[30, 32], [0, 180, 0, 256],
	)
	cv2.normalize(hs_histogram, hs_histogram, alpha=1.0, norm_type=cv2.NORM_L1)
	model = {
		"hsv_mean": hsv_mean,
		"template": patch.copy(),
		"hs_histogram": hs_histogram,
		"seed_status": "",
	}
	return model


#============================================
def _make_fused_track(n_frames: int, occlusion_frames: list) -> list:
	"""Build a minimal fused track with occlusion_risk flags.

	Args:
		n_frames: Total number of frames.
		occlusion_frames: List of frame indices (0-based) with occlusion.

	Returns:
		List of state dicts with occlusion_risk set.
	"""
	track = []
	for i in range(n_frames):
		state = {
			"cx": 100.0, "cy": 100.0, "w": 50.0, "h": 80.0,
			"conf": 0.8, "source": "merged", "fuse_flag": False,
			"occlusion_risk": i in occlusion_frames,
		}
		track.append(state)
	return track


#============================================
def _make_synthetic_trajectory(
	n_frames: int,
	cx_func: callable,
	cy_func: callable,
	h_val: float = 100.0,
) -> list:
	"""Helper to build a dense trajectory list for direct-center tests.

	Args:
		n_frames: Number of frames to generate.
		cx_func: Callable(i) -> float for center x at frame i.
		cy_func: Callable(i) -> float for center y at frame i.
		h_val: Constant bounding box height.

	Returns:
		List of tracking state dicts.
	"""
	trajectory = []
	for i in range(n_frames):
		state = {
			"cx": cx_func(i),
			"cy": cy_func(i),
			"w": h_val * 0.5,
			"h": h_val,
			"conf": 0.9,
			"source": "propagated",
		}
		trajectory.append(state)
	return trajectory


#============================================
def _make_direct_center_config(overrides: dict = None) -> dict:
	"""Helper to build a config dict for direct-center tests.

	Args:
		overrides: Optional dict of processing keys to override.

	Returns:
		Config dict with crop_mode='direct_center'.
	"""
	processing = {
		"crop_mode": "direct_center",
		"crop_aspect": "16:9",
		"crop_fill_ratio": 0.30,
		"crop_min_size": 50,
		"crop_post_smooth_strength": 0.0,
		"crop_post_smooth_size_strength": 0.0,
		"crop_post_smooth_max_velocity": 0.0,
	}
	if overrides:
		processing.update(overrides)
	config = {"processing": processing}
	return config
