"""YOLO and HOG person detection for track_runner."""

# Standard Library
import os
import urllib.request

# PIP3 modules
import cv2
import numpy

# Constants for YOLO nano ONNX model
# No pre-exported yolov8n.onnx exists on GitHub releases.
# We download yolov8n.pt and export to ONNX via ultralytics if available,
# otherwise fall back to HOG detector.
YOLO_PT_URL = (
	"https://github.com/ultralytics/assets/releases/download/"
	"v8.2.0/yolov8n.pt"
)
YOLO_WEIGHTS_FILENAME = "yolov8n.onnx"
YOLO_PT_FILENAME = "yolov8n.pt"
YOLO_EXPECTED_ONNX_MIN = 5_000_000  # ~12-13MB
YOLO_EXPECTED_ONNX_MAX = 20_000_000
YOLO_INPUT_SIZE = 640
PERSON_CLASS_ID = 0  # COCO class 0 = person


#============================================
def _export_pt_to_onnx(pt_path: str, onnx_path: str) -> bool:
	"""Export a YOLO .pt model to ONNX format via ultralytics.

	Args:
		pt_path: Path to the .pt weights file.
		onnx_path: Desired output path for the ONNX file.

	Returns:
		True if export succeeded, False otherwise.
	"""
	try:
		import ultralytics
	except ImportError:
		print("WARNING: ultralytics not installed, cannot export to ONNX")
		return False
	print(f"Exporting {pt_path} to ONNX format...")
	model = ultralytics.YOLO(pt_path)
	# export writes to same directory as .pt file
	result_path = model.export(format="onnx", imgsz=640)
	if result_path and os.path.isfile(result_path):
		# move to desired location if different
		if os.path.realpath(result_path) != os.path.realpath(onnx_path):
			os.replace(result_path, onnx_path)
		return True
	return False


#============================================
def ensure_yolo_weights(cache_dir: str | None = None) -> str:
	"""Get YOLOv8n ONNX weights, downloading and exporting if needed.

	Checks for cached ONNX file first. If missing, downloads yolov8n.pt
	and exports to ONNX via ultralytics. Falls back gracefully if either
	download or export fails.

	Args:
		cache_dir: Directory to store the weights file.
			Defaults to ~/.cache/track_runner/.

	Returns:
		Path to the ONNX weights file, or empty string on failure.
	"""
	if cache_dir is None:
		cache_dir = os.path.join(
			os.path.expanduser("~"), ".cache", "track_runner"
		)
	os.makedirs(cache_dir, exist_ok=True)
	onnx_path = os.path.join(cache_dir, YOLO_WEIGHTS_FILENAME)
	# return existing ONNX weights if valid
	if os.path.isfile(onnx_path):
		file_size = os.path.getsize(onnx_path)
		if YOLO_EXPECTED_ONNX_MIN <= file_size <= YOLO_EXPECTED_ONNX_MAX:
			return onnx_path
		print(f"WARNING: existing ONNX file has unexpected size "
			f"({file_size} bytes), re-exporting")
		os.remove(onnx_path)
	# download .pt weights if not cached
	pt_path = os.path.join(cache_dir, YOLO_PT_FILENAME)
	if not os.path.isfile(pt_path):
		print(f"Downloading YOLOv8n weights from {YOLO_PT_URL}")
		try:
			urllib.request.urlretrieve(YOLO_PT_URL, pt_path)
		except Exception as err:
			print(f"WARNING: failed to download YOLO weights: {err}")
			return ""
	# export .pt to ONNX
	if not _export_pt_to_onnx(pt_path, onnx_path):
		return ""
	# validate exported file
	if not os.path.isfile(onnx_path):
		print("WARNING: ONNX export did not produce a file")
		return ""
	file_size = os.path.getsize(onnx_path)
	if not (YOLO_EXPECTED_ONNX_MIN <= file_size <= YOLO_EXPECTED_ONNX_MAX):
		print(f"WARNING: exported ONNX has unexpected size ({file_size})")
		os.remove(onnx_path)
		return ""
	print(f"YOLOv8n ONNX weights ready at {onnx_path}")
	return onnx_path


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
class HogDetector:
	"""Person detector using HOG + SVM (OpenCV built-in)."""

	#============================================
	def __init__(self, confidence_threshold: float = 0.25):
		"""Initialize the HOG person detector.

		Args:
			confidence_threshold: Minimum confidence to keep a detection.
		"""
		self.hog = cv2.HOGDescriptor()
		self.hog.setSVMDetector(
			cv2.HOGDescriptor_getDefaultPeopleDetector()
		)
		self.confidence_threshold = confidence_threshold

	#============================================
	def detect(self, frame: numpy.ndarray) -> list[dict]:
		"""Detect persons in a video frame using HOG.

		Args:
			frame: BGR image as a numpy array (H, W, 3).

		Returns:
			List of detection dicts with keys:
				bbox: [x, y, w, h] in original frame pixels (top-left corner)
				confidence: detection confidence weight
				class_id: always 0 (person)
		"""
		# detectMultiScale returns (rects, weights)
		rects, weights = self.hog.detectMultiScale(frame)
		results = []
		for i, rect in enumerate(rects):
			weight = float(weights[i])
			if weight < self.confidence_threshold:
				continue
			# rect is (x, y, w, h) already in frame coordinates
			detection = {
				"bbox": [int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])],
				"confidence": weight,
				"class_id": PERSON_CLASS_ID,
			}
			results.append(detection)
		return results


#============================================
def create_detector(config: dict) -> YoloDetector | HogDetector:
	"""Create a person detector based on config settings.

	Args:
		config: Configuration dict with settings.detection section.
			Expected keys under settings.detection:
				kind: "yolo" or "hog"
				confidence_threshold: float (optional, default 0.25)
				nms_threshold: float (optional, default 0.45)

	Returns:
		A YoloDetector or HogDetector instance.
	"""
	# extract detection settings with defaults
	settings = config.get("settings", {})
	detection = settings.get("detection", {})
	kind = detection.get("kind", "yolo")
	confidence_threshold = float(detection.get("confidence_threshold", 0.25))
	nms_threshold = float(detection.get("nms_threshold", 0.45))
	# try YOLO first if requested
	if kind == "yolo":
		weights_path = ensure_yolo_weights()
		if weights_path:
			det = YoloDetector(
				weights_path,
				confidence_threshold=confidence_threshold,
				nms_threshold=nms_threshold,
			)
			# store config for parallel worker recreation
			det._config = config
			return det
		# fall back to HOG if weights unavailable
		print("WARNING: YOLO weights unavailable, falling back to HOG detector")
	# HOG detector
	det = HogDetector(confidence_threshold=confidence_threshold)
	# store config for parallel worker recreation
	det._config = config
	return det
