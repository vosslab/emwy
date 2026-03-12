"""YOLO person detection for track_runner."""

# Standard Library
import os

# PIP3 modules
import cv2
import numpy

# Constants for YOLO nano ONNX model
# ONNX file is created once via tools/export_yolo_onnx.py and cached.
# No ultralytics pip dependency at runtime.
YOLO_WEIGHTS_FILENAME = "yolov8n.onnx"
YOLO_EXPECTED_ONNX_MIN = 5_000_000  # ~12-13MB
YOLO_EXPECTED_ONNX_MAX = 20_000_000
YOLO_INPUT_SIZE = 640
PERSON_CLASS_ID = 0  # COCO class 0 = person


#============================================
def ensure_yolo_weights(cache_dir: str | None = None) -> str:
	"""Get YOLOv8n ONNX weights from cache.

	Checks for the cached ONNX file. If missing, prints instructions
	for running the one-time export script.

	Args:
		cache_dir: Directory to look for the weights file.
			Defaults to ~/.cache/track_runner/.

	Returns:
		Path to the ONNX weights file, or empty string if not found.
	"""
	if cache_dir is None:
		cache_dir = os.path.join(
			os.path.expanduser("~"), ".cache", "track_runner"
		)
	onnx_path = os.path.join(cache_dir, YOLO_WEIGHTS_FILENAME)
	# return existing ONNX weights if valid
	if os.path.isfile(onnx_path):
		file_size = os.path.getsize(onnx_path)
		if YOLO_EXPECTED_ONNX_MIN <= file_size <= YOLO_EXPECTED_ONNX_MAX:
			return onnx_path
		print(f"WARNING: existing ONNX file has unexpected size "
			f"({file_size} bytes), please re-export")
	# ONNX file not found, print instructions
	print(f"YOLO ONNX weights not found at {onnx_path}")
	print("Run the one-time export script to create them:")
	print("  pip3 install ultralytics")
	print("  python3 tools/export_yolo_onnx.py")
	print("  pip3 uninstall ultralytics  # optional cleanup")
	return ""


#============================================
class YoloDetector:
	"""Person detector using YOLOv8 ONNX model via OpenCV DNN."""

	#============================================
	def __init__(
		self,
		model_path: str,
		confidence_threshold: float = 0.25,
		nms_threshold: float = 0.45,
	):
		"""Initialize the YOLO detector.

		Args:
			model_path: Path to the YOLOv8 ONNX weights file.
			confidence_threshold: Minimum confidence to keep a detection.
			nms_threshold: IoU threshold for non-maximum suppression.
		"""
		self.net = cv2.dnn.readNetFromONNX(model_path)
		self.confidence_threshold = confidence_threshold
		self.nms_threshold = nms_threshold

	#============================================
	def detect(self, frame: numpy.ndarray) -> list[dict]:
		"""Detect persons in a video frame.

		Args:
			frame: BGR image as a numpy array (H, W, 3).

		Returns:
			List of detection dicts with keys:
				bbox: [x, y, w, h] in original frame pixels (top-left corner)
				confidence: detection confidence score
				class_id: always 0 (person)
		"""
		frame_h, frame_w = frame.shape[:2]
		# preprocess: letterbox to 640x640 without cropping
		blob = cv2.dnn.blobFromImage(
			frame,
			scalefactor=1 / 255.0,
			size=(YOLO_INPUT_SIZE, YOLO_INPUT_SIZE),
			swapRB=True,
			crop=False,
		)
		self.net.setInput(blob)
		# forward pass: output shape [1, 84, 8400]
		outputs = self.net.forward()
		# transpose to [8400, 84] for easier parsing
		predictions = outputs[0].transpose()
		# compute letterbox scale and offsets
		scale = min(
			YOLO_INPUT_SIZE / frame_h,
			YOLO_INPUT_SIZE / frame_w,
		)
		offset_x = (YOLO_INPUT_SIZE - frame_w * scale) / 2.0
		offset_y = (YOLO_INPUT_SIZE - frame_h * scale) / 2.0
		# collect candidate boxes and scores for person class
		boxes = []
		scores = []
		for row in predictions:
			# first 4 values are cx, cy, w, h in 640x640 space
			cx, cy, bw, bh = row[0], row[1], row[2], row[3]
			# remaining 80 values are class scores
			class_scores = row[4:84]
			class_id = int(numpy.argmax(class_scores))
			score = float(class_scores[class_id])
			# only keep person detections above threshold
			if class_id != PERSON_CLASS_ID:
				continue
			if score < self.confidence_threshold:
				continue
			# convert center coords to top-left corner in 640 space
			x_640 = cx - bw / 2.0
			y_640 = cy - bh / 2.0
			# scale back to original frame coordinates
			x_real = (x_640 - offset_x) / scale
			y_real = (y_640 - offset_y) / scale
			w_real = bw / scale
			h_real = bh / scale
			# clamp to frame boundaries
			x_real = max(0.0, x_real)
			y_real = max(0.0, y_real)
			w_real = min(w_real, frame_w - x_real)
			h_real = min(h_real, frame_h - y_real)
			# skip degenerate boxes
			if w_real < 1.0 or h_real < 1.0:
				continue
			boxes.append([int(x_real), int(y_real), int(w_real), int(h_real)])
			scores.append(score)
		# apply non-maximum suppression
		if len(boxes) == 0:
			return []
		indices = cv2.dnn.NMSBoxes(
			boxes, scores,
			self.confidence_threshold, self.nms_threshold,
		)
		# build result list
		results = []
		for idx in indices:
			# NMSBoxes returns flat array or nested depending on version
			i = int(idx) if numpy.ndim(idx) == 0 else int(idx[0])
			detection = {
				"bbox": boxes[i],
				"confidence": scores[i],
				"class_id": PERSON_CLASS_ID,
			}
			results.append(detection)
		return results

	#============================================
	def detect_roi(
		self,
		frame: numpy.ndarray,
		roi_center: tuple[float, float],
		roi_size: tuple[float, float],
		padding_factor: float = 3.0,
	) -> list[dict]:
		"""Detect persons in a frame region-of-interest (ROI).

		Crops a region around a predicted bounding box and runs YOLO detection
		on the crop, then transforms detections back to full-frame coordinates.

		Args:
			frame: BGR image as a numpy array (H, W, 3).
			roi_center: (cx, cy) tuple of the predicted bbox center in pixels.
			roi_size: (w, h) tuple of the predicted bbox size in pixels.
			padding_factor: Expansion factor for the crop region relative to
				the bbox size. Default 3.0 means the crop is 3x the bbox size.

		Returns:
			List of detection dicts with keys:
				bbox: [x, y, w, h] in original frame pixels (top-left corner)
				confidence: detection confidence score
				class_id: always 0 (person)
		"""
		frame_h, frame_w = frame.shape[:2]
		cx, cy = roi_center
		w, h = roi_size

		# Compute crop region: expand bbox by padding_factor
		crop_w = w * padding_factor
		crop_h = h * padding_factor

		# Enforce minimum crop size of 320x320 for YOLO context
		min_crop_size = 320.0
		crop_w = max(crop_w, min_crop_size)
		crop_h = max(crop_h, min_crop_size)

		# Compute crop top-left corner
		x1 = cx - crop_w / 2.0
		y1 = cy - crop_h / 2.0

		# Clamp to frame boundaries
		x1 = max(0.0, x1)
		y1 = max(0.0, y1)
		x2 = x1 + crop_w
		y2 = y1 + crop_h

		# Adjust if crop exceeds frame bounds
		if x2 > frame_w:
			x2 = frame_w
			x1 = max(0.0, x2 - crop_w)
		if y2 > frame_h:
			y2 = frame_h
			y1 = max(0.0, y2 - crop_h)

		# Convert to integer pixel coordinates
		x1 = int(x1)
		y1 = int(y1)
		x2 = int(x2)
		y2 = int(y2)

		# Crop the frame using numpy slicing: [y1:y2, x1:x2]
		crop = frame[y1:y2, x1:x2]

		# Run YOLO detection on the crop
		detections = self.detect(crop)

		# Transform detections back to full-frame coordinates
		for detection in detections:
			bbox = detection["bbox"]
			# bbox is [x, y, w, h] relative to crop; offset by (x1, y1)
			bbox[0] += x1
			bbox[1] += y1
			detection["bbox"] = bbox

		return detections


#============================================
def create_detector(config: dict) -> YoloDetector:
	"""Create a YOLO person detector from config settings.

	Args:
		config: Configuration dict with settings.detection section.
			Expected keys under settings.detection:
				confidence_threshold: float (optional, default 0.25)
				nms_threshold: float (optional, default 0.45)

	Returns:
		A YoloDetector instance.

	Raises:
		RuntimeError: If YOLO weights cannot be obtained.
	"""
	# extract detection settings with defaults
	settings = config.get("settings", {})
	detection = settings.get("detection", {})
	confidence_threshold = float(detection.get("confidence_threshold", 0.25))
	nms_threshold = float(detection.get("nms_threshold", 0.45))
	# obtain YOLO weights, raise on failure
	weights_path = ensure_yolo_weights()
	if not weights_path:
		msg = "YOLO ONNX weights not found. Run the one-time export:\n"
		msg += "  pip3 install ultralytics\n"
		msg += "  python3 tools/export_yolo_onnx.py\n"
		msg += "  pip3 uninstall ultralytics  # optional cleanup"
		raise RuntimeError(msg)
	det = YoloDetector(
		weights_path,
		confidence_threshold=confidence_threshold,
		nms_threshold=nms_threshold,
	)
	# store config for parallel worker recreation
	det._config = config
	return det
