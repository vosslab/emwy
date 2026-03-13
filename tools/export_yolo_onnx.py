#!/usr/bin/env python3
"""One-time helper: export yolov8n.pt to yolov8n.onnx.

Requires ultralytics (pip3 install ultralytics) but only needs to be
run once. After the ONNX file is cached at ~/.cache/track_runner/yolov8n.onnx,
the track_runner code never needs ultralytics again.

Usage:
    pip3 install ultralytics
    python3 tools/export_yolo_onnx.py
    pip3 uninstall ultralytics   # optional cleanup
"""

# Standard Library
import os

# PIP3 modules
import ultralytics

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "track_runner")
PT_URL = (
	"https://github.com/ultralytics/assets/releases/download/"
	"v8.2.0/yolov8n.pt"
)


#============================================
def main() -> None:
	"""Download yolov8n.pt and export to ONNX."""
	os.makedirs(CACHE_DIR, exist_ok=True)
	pt_path = os.path.join(CACHE_DIR, "yolov8n.pt")
	onnx_path = os.path.join(CACHE_DIR, "yolov8n.onnx")
	# check if ONNX already exists
	if os.path.isfile(onnx_path):
		file_size = os.path.getsize(onnx_path)
		print(f"ONNX file already exists at {onnx_path} ({file_size} bytes)")
		return
	# download .pt if needed
	if not os.path.isfile(pt_path):
		print(f"Downloading yolov8n.pt from {PT_URL}")
		import urllib.request
		urllib.request.urlretrieve(PT_URL, pt_path)
	# export to ONNX
	print(f"Exporting {pt_path} to ONNX...")
	model = ultralytics.YOLO(pt_path)
	result_path = model.export(format="onnx", imgsz=640)
	# move to desired location if needed
	if result_path and os.path.isfile(result_path):
		if os.path.realpath(result_path) != os.path.realpath(onnx_path):
			os.replace(result_path, onnx_path)
	# verify
	if os.path.isfile(onnx_path):
		file_size = os.path.getsize(onnx_path)
		print(f"ONNX weights ready at {onnx_path} ({file_size} bytes)")
	else:
		print("ERROR: export failed, no ONNX file produced")


if __name__ == "__main__":
	main()
