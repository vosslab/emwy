#!/usr/bin/env python3
"""
Assess visible zoom instability in rendered video using Fourier-Mellin registration.

Measures zoom scale between consecutive frames using log-polar FFT-based phase correlation,
tracks drift via reference-anchor estimation, and reports stability metrics.
"""

import argparse
import csv
import math
import os
import sys
from pathlib import Path

import cv2
import numpy

#============================================

def parse_args():
	"""
	Parse command-line arguments.
	"""
	parser = argparse.ArgumentParser(
		description="Assess pixel zoom stability using Fourier-Mellin phase correlation"
	)
	parser.add_argument(
		"-i", "--input", dest="input_file", default="",
		help="Single video file path"
	)
	parser.add_argument(
		"-d", "--directory", dest="input_dir", default="",
		help="Batch directory containing video files"
	)
	parser.add_argument(
		"-o", "--output", dest="output_dir", default="output_smoke",
		help="Output directory for results (default: output_smoke)"
	)
	parser.add_argument(
		"-n", "--max-frames", dest="max_frames", type=int, default=0,
		help="Maximum frames to analyze (0 = all, default: 0)"
	)
	parser.add_argument(
		"-s", "--start-frame", dest="start_frame", type=int, default=0,
		help="Start frame (default: 0)"
	)
	parser.add_argument(
		"-w", "--weighting", dest="weighting", default="edge_weighted",
		choices=["full", "edge_weighted", "side_strips"],
		help="Edge masking mode (default: edge_weighted)"
	)
	parser.add_argument(
		"-p", "--pattern", dest="pattern", default="*.mkv",
		help="Batch file glob pattern (default: *.mkv)"
	)
	parser.add_argument(
		"--crop-analysis", dest="crop_analysis", default="",
		help="Optional .analysis.yaml path for cross-reference"
	)
	parser.add_argument(
		"--estimator", dest="estimator", default="fourier_mellin",
		choices=["fourier_mellin"],
		help="Scale estimator method (default: fourier_mellin)"
	)
	args = parser.parse_args()
	return args

#============================================

def build_edge_mask(h: int, w: int, mode: str) -> numpy.ndarray:
	"""
	Build spatial edge weighting mask.

	Args:
		h: frame height
		w: frame width
		mode: 'full' (no masking), 'edge_weighted' (smoothstep radial),
		      'side_strips' (four independent border regions)

	Returns:
		mask array of shape (h, w) with values [0, 1]
	"""
	if mode == "full":
		return numpy.ones((h, w), dtype=numpy.float32)

	if mode == "edge_weighted":
		# normalized coordinates [-1, 1]
		y_norm = numpy.linspace(-1.0, 1.0, h).reshape(-1, 1)
		x_norm = numpy.linspace(-1.0, 1.0, w).reshape(1, -1)
		radius = numpy.sqrt(x_norm**2 + y_norm**2)

		# smoothstep from 0.4 to 0.7 normalized radius
		t = numpy.clip((radius - 0.4) / 0.3, 0.0, 1.0)
		edge_mask = t * t * (3.0 - 2.0 * t)
		return edge_mask.astype(numpy.float32)

	if mode == "side_strips":
		# return marker for side_strips; will be handled in analyze_video_zoom
		mask = numpy.zeros((h, w), dtype=numpy.int32)
		mask[:, :] = 1  # placeholder
		return mask

	return numpy.ones((h, w), dtype=numpy.float32)

#============================================

def compute_fft_log_polar(
	gray: numpy.ndarray,
	edge_mask: numpy.ndarray,
	hann_window: numpy.ndarray
) -> numpy.ndarray:
	"""
	Compute log-polar transform of FFT magnitude spectrum.

	Args:
		gray: grayscale frame (uint8), shape (h, w)
		edge_mask: spatial mask (float32), shape (h, w)
		hann_window: Hann window, shape (h, w)

	Returns:
		log-polar magnitude, shape (h, w)
	"""
	h, w = gray.shape
	weighted = gray.astype(numpy.float64) * edge_mask * hann_window
	F = numpy.abs(numpy.fft.fftshift(numpy.fft.fft2(weighted)))

	# avoid log(0)
	F = numpy.maximum(F, 1e-6)
	magnitude = numpy.log(F)

	center = (w // 2, h // 2)
	max_radius = min(h, w) // 2
	log_polar = cv2.warpPolar(
		magnitude, (w, h), center, max_radius,
		cv2.WARP_POLAR_LOG | cv2.INTER_LINEAR
	)
	return log_polar.astype(numpy.float32)

#============================================

def estimate_scale_fourier_mellin(
	lp_prev: numpy.ndarray,
	lp_curr: numpy.ndarray,
	max_radius: int,
	width: int
) -> tuple:
	"""
	Estimate scale from log-polar phase correlation.

	Args:
		lp_prev: log-polar from previous frame, shape (h, w)
		lp_curr: log-polar from current frame, shape (h, w)
		max_radius: maximum radius used in log-polar transform
		width: frame width

	Returns:
		(scale, confidence) where scale in (0.5, 2.0) typical range,
		confidence in [0, 1] (correlation peak height)
	"""
	try:
		# phase correlation for scale shift in log-polar space
		# shift_x corresponds to log-scale axis
		(shift_x, shift_y), response = cv2.phaseCorrelate(lp_prev, lp_curr)

		# convert shift_x (pixels in log-polar) to actual scale factor
		# formula: scale = exp(-shift_x * ln(max_radius) / width)
		# (negative sign: phase correlation shift is inverted relative to log-polar axis)
		conversion_const = math.log(max_radius) / width
		log_scale = -shift_x * conversion_const
		scale = math.exp(log_scale)

		# clamp scale to sensible range
		scale = max(0.80, min(1.25, scale))

		return (scale, response)
	except Exception:
		return (1.0, 0.0)

#============================================

def analyze_video_zoom(
	video_path: str,
	start_frame: int,
	max_frames: int,
	weighting: str,
	estimator: str
) -> dict:
	"""
	Analyze zoom stability in a single video file.

	Args:
		video_path: path to video file
		start_frame: frame index to start from
		max_frames: max frames to analyze (0 = all)
		weighting: edge masking mode
		estimator: scale estimator method

	Returns:
		dict with keys: frame_data, summary, analysis_info, valid_frames,
		anchor_scale, local_scale, zoom_velocity_log, zoom_jerk
	"""
	cap = cv2.VideoCapture(video_path)
	if not cap.isOpened():
		raise ValueError(f"Cannot open video: {video_path}")

	width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
	height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
	fps = cap.get(cv2.CAP_PROP_FPS)
	total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

	# determine frame range
	if max_frames <= 0:
		max_frames = total_frames - start_frame
	end_frame = min(start_frame + max_frames, total_frames)
	frames_to_analyze = end_frame - start_frame

	# confidence and scale thresholds
	confidence_threshold = 0.1
	scale_lower = 0.80
	scale_upper = 1.25

	# set up edge masking
	if weighting == "side_strips":
		# side_strips mode: four independent regions
		edge_masks = _build_side_strip_masks(height, width)
	else:
		edge_mask = build_edge_mask(height, width, weighting)

	# precompute Hann window
	hann_window = numpy.outer(
		numpy.hanning(height), numpy.hanning(width)
	).astype(numpy.float32)

	# anchor frame for reference-anchor scale estimation
	anchor_interval = 300
	anchor_refresh_at = anchor_interval

	max_radius = min(height, width) // 2

	# initialize tracking arrays
	frame_data = []
	local_scale = []
	anchor_scale = []
	zoom_velocity_log = []
	zoom_jerk = []
	valid_frames = []

	# skip to start_frame
	for _ in range(start_frame):
		cap.read()

	lp_prev = None
	lp_anchor = None
	cumulative_zoom_raw = 0.0
	cumulative_zoom_display = 0.0
	last_valid_zoom_velocity_log = 0.0
	correlation_values = []
	failed_frame_count = 0

	print(f"Analyzing {frames_to_analyze} frames...")

	for frame_idx in range(frames_to_analyze):
		ret, frame = cap.read()
		if not ret:
			break

		absolute_frame = start_frame + frame_idx
		time_s = absolute_frame / fps

		gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

		# compute log-polar
		if weighting == "side_strips":
			lp_curr = _compute_side_strip_log_polar(
				gray, edge_masks, hann_window, max_radius, width
			)
		else:
			lp_curr = compute_fft_log_polar(gray, edge_mask, hann_window)

		# frame 0: initialize
		if lp_prev is None:
			lp_prev = lp_curr
			lp_anchor = lp_curr
			frame_data.append({
				"frame": absolute_frame,
				"time_s": time_s,
				"local_scale": 1.0,
				"cumulative_zoom_raw": 0.0,
				"cumulative_zoom_display": 0.0,
				"anchor_scale": 1.0,
				"zoom_velocity_log": 0.0,
				"zoom_velocity": 0.0,
				"zoom_jerk": 0.0,
				"correlation": 1.0,
			})
			valid_frames.append(True)
			local_scale.append(1.0)
			anchor_scale.append(1.0)
			zoom_velocity_log.append(0.0)
			zoom_jerk.append(0.0)
			if (frame_idx + 1) % 100 == 0:
				print(f"  frame {frame_idx + 1}/{frames_to_analyze} "
					f"({100.0 * (frame_idx + 1) / frames_to_analyze:.1f}%)")
			lp_prev = lp_curr
			continue

		# local scale (frame i-1 to i)
		if estimator == "fourier_mellin":
			local_scale_val, correlation = estimate_scale_fourier_mellin(
				lp_prev, lp_curr, max_radius, width
			)
		else:
			local_scale_val, correlation = (1.0, 0.0)

		# validate scale and correlation
		is_valid = (
			correlation >= confidence_threshold and
			scale_lower <= local_scale_val <= scale_upper
		)

		if not is_valid:
			failed_frame_count += 1
			local_scale_val = 1.0
			correlation = 0.0

		# anchor scale (frame 0 to i)
		if lp_anchor is not None:
			anchor_scale_val, _ = estimate_scale_fourier_mellin(
				lp_anchor, lp_curr, max_radius, width
			)
			anchor_scale_val = max(0.80, min(1.25, anchor_scale_val))
		else:
			anchor_scale_val = 1.0

		# accumulate zoom
		log_scale = math.log(local_scale_val)
		cumulative_zoom_raw += log_scale
		if is_valid:
			last_valid_zoom_velocity_log = log_scale
		cumulative_zoom_display += last_valid_zoom_velocity_log

		# linear velocity
		zoom_velocity_val = local_scale_val - 1.0

		# jerk
		if frame_idx == 1:
			zoom_jerk_val = abs(log_scale - 0.0)
		else:
			zoom_jerk_val = abs(log_scale - zoom_velocity_log[frame_idx - 1])

		frame_data.append({
			"frame": absolute_frame,
			"time_s": time_s,
			"local_scale": local_scale_val,
			"cumulative_zoom_raw": cumulative_zoom_raw,
			"cumulative_zoom_display": cumulative_zoom_display,
			"anchor_scale": anchor_scale_val,
			"zoom_velocity_log": log_scale,
			"zoom_velocity": zoom_velocity_val,
			"zoom_jerk": zoom_jerk_val,
			"correlation": correlation,
		})

		valid_frames.append(is_valid)
		local_scale.append(local_scale_val)
		anchor_scale.append(anchor_scale_val)
		zoom_velocity_log.append(log_scale)
		zoom_jerk.append(zoom_jerk_val)
		correlation_values.append(correlation)

		# anchor refresh every 300 frames (for runs > 480)
		if frames_to_analyze > 480 and frame_idx >= anchor_refresh_at:
			lp_anchor = lp_curr
			anchor_refresh_at += anchor_interval

		if (frame_idx + 1) % 100 == 0:
			print(f"  frame {frame_idx + 1}/{frames_to_analyze} "
				f"({100.0 * (frame_idx + 1) / frames_to_analyze:.1f}%)")

		lp_prev = lp_curr

	cap.release()

	# compute summary
	summary = compute_zoom_summary(frame_data, fps)

	# analysis info
	analysis_info = {
		"input_file": video_path,
		"width": width,
		"height": height,
		"fps": fps,
		"total_frames": total_frames,
		"start_frame": start_frame,
		"end_frame": end_frame,
		"frames_analyzed": len(frame_data),
		"estimator": estimator,
		"weighting": weighting,
		"confidence_threshold": confidence_threshold,
		"scale_lower": scale_lower,
		"scale_upper": scale_upper,
		"max_radius": max_radius,
		"failed_frames": failed_frame_count,
	}

	return {
		"frame_data": frame_data,
		"summary": summary,
		"analysis_info": analysis_info,
		"valid_frames": valid_frames,
	}

#============================================

def _build_side_strip_masks(h: int, w: int) -> list:
	"""
	Build four side-strip masks for independent estimation.

	Returns:
		list of 4 masks (top, bottom, left, right)
	"""
	strip_width = int(0.15 * w)
	strip_height = int(0.15 * h)

	masks = []

	# top strip
	top_mask = numpy.zeros((h, w), dtype=numpy.float32)
	top_mask[:strip_height, :] = 1.0
	masks.append(top_mask)

	# bottom strip
	bottom_mask = numpy.zeros((h, w), dtype=numpy.float32)
	bottom_mask[-strip_height:, :] = 1.0
	masks.append(bottom_mask)

	# left strip
	left_mask = numpy.zeros((h, w), dtype=numpy.float32)
	left_mask[:, :strip_width] = 1.0
	masks.append(left_mask)

	# right strip
	right_mask = numpy.zeros((h, w), dtype=numpy.float32)
	right_mask[:, -strip_width:] = 1.0
	masks.append(right_mask)

	return masks

#============================================

def _compute_side_strip_log_polar(
	gray: numpy.ndarray,
	edge_masks: list,
	hann_window: numpy.ndarray,
	max_radius: int,
	width: int
) -> numpy.ndarray:
	"""
	Compute log-polar using median of four independent side-strip estimates.

	For side_strips mode, each strip is weighted independently, and the
	scale estimate is the median of valid strip results.

	Returns:
		log-polar array (averaged or fused representation)
	"""
	h, w = gray.shape
	scales = []

	for mask in edge_masks:
		weighted = (
			gray.astype(numpy.float64) *
			mask.astype(numpy.float32) *
			hann_window
		)
		F = numpy.abs(numpy.fft.fftshift(numpy.fft.fft2(weighted)))
		F = numpy.maximum(F, 1e-6)
		magnitude = numpy.log(F)

		center = (w // 2, h // 2)
		log_polar = cv2.warpPolar(
			magnitude, (w, h), center, max_radius,
			cv2.WARP_POLAR_LOG | cv2.INTER_LINEAR
		)
		scales.append(log_polar.astype(numpy.float32))

	# return average for simplicity (future: per-strip tracking)
	result = numpy.mean(scales, axis=0)
	return result.astype(numpy.float32)

#============================================

def compute_zoom_summary(frame_data: list, fps: float) -> dict:
	"""
	Compute summary statistics from frame-level zoom data.

	Args:
		frame_data: list of frame dictionaries
		fps: frames per second

	Returns:
		dict with zoom stability metrics
	"""
	if not frame_data:
		return {}

	local_scales = [f["local_scale"] for f in frame_data]
	zoom_velocity_logs = [f["zoom_velocity_log"] for f in frame_data]
	zoom_velocities = [f["zoom_velocity"] for f in frame_data]
	zoom_jerks = [f["zoom_jerk"] for f in frame_data]
	correlations = [f["correlation"] for f in frame_data]

	# filter out invalid frames (NaN or out-of-range)
	valid_scales = [s for s in local_scales if 0.80 <= s <= 1.25]
	valid_logs = [z for z in zoom_velocity_logs if abs(z) < 0.5]
	valid_velocities = [v for v in zoom_velocities if abs(v) < 0.25]
	valid_jerks = [j for j in zoom_jerks if j >= 0]

	if not valid_logs:
		valid_logs = zoom_velocity_logs

	# zoom range
	zoom_range = max(valid_scales) - min(valid_scales) if valid_scales else 0.0

	# coefficient of variation
	zoom_mean = numpy.mean(valid_scales) if valid_scales else 1.0
	zoom_std = numpy.std(valid_scales) if valid_scales else 0.0
	zoom_cv = zoom_std / zoom_mean if zoom_mean > 0 else 0.0

	# percentiles
	def safe_percentile(data, p):
		return float(numpy.percentile(data, p)) if data else 0.0

	zoom_velocity_log_median = safe_percentile(valid_logs, 50)
	zoom_velocity_log_p95 = safe_percentile(valid_logs, 95)
	zoom_velocity_log_max = max(abs(v) for v in valid_logs) if valid_logs else 0.0

	zoom_velocity_median = safe_percentile(valid_velocities, 50)
	zoom_velocity_p95 = safe_percentile(valid_velocities, 95)
	zoom_velocity_max = max(abs(v) for v in valid_velocities) if valid_velocities else 0.0

	zoom_jerk_p95 = safe_percentile(valid_jerks, 95)

	# bounce count (zero-crossings in zoom_velocity_log above noise)
	noise_threshold = 0.0005
	bounce_count = 0
	for i in range(1, len(valid_logs)):
		if (valid_logs[i] > noise_threshold and
			valid_logs[i - 1] <= noise_threshold):
			bounce_count += 1
		elif (valid_logs[i] < -noise_threshold and
			valid_logs[i - 1] >= -noise_threshold):
			bounce_count += 1

	# bounce rate per second
	duration_s = len(frame_data) / fps if fps > 0 else 1.0
	bounce_rate_per_s = bounce_count / duration_s if duration_s > 0 else 0.0

	# drift per minute
	if frame_data:
		final_cumulative = frame_data[-1]["cumulative_zoom_display"]
		drift_per_minute = (final_cumulative / duration_s) * 60.0 if duration_s > 0 else 0.0
	else:
		drift_per_minute = 0.0

	# correlation stats
	correlation_mean = numpy.mean(correlations) if correlations else 0.0
	correlation_min = min(correlations) if correlations else 0.0

	# valid frame fraction
	valid_frame_count = sum(
		1 for f in frame_data
		if (0.80 <= f["local_scale"] <= 1.25)
	)
	valid_frame_fraction = (
		valid_frame_count / len(frame_data) if frame_data else 0.0
	)

	summary = {
		"zoom_range": zoom_range,
		"zoom_cv": zoom_cv,
		"zoom_velocity_log_median": zoom_velocity_log_median,
		"zoom_velocity_log_p95": zoom_velocity_log_p95,
		"zoom_velocity_log_max": zoom_velocity_log_max,
		"zoom_velocity_median": zoom_velocity_median,
		"zoom_velocity_p95": zoom_velocity_p95,
		"zoom_velocity_max": zoom_velocity_max,
		"zoom_jerk_p95": zoom_jerk_p95,
		"bounce_count": int(bounce_count),
		"bounce_rate_per_s": bounce_rate_per_s,
		"drift_per_minute": drift_per_minute,
		"correlation_mean": correlation_mean,
		"correlation_min": correlation_min,
		"valid_frame_fraction": valid_frame_fraction,
		"valid_pair_count": valid_frame_count,
	}

	return summary

#============================================

def write_zoom_csv(frame_data: list, output_path: str) -> None:
	"""
	Write frame-level data to CSV.

	Columns: frame, time_s, local_scale, cumulative_zoom_raw,
	cumulative_zoom_display, anchor_scale, zoom_velocity_log,
	zoom_velocity, zoom_jerk, correlation
	"""
	if not frame_data:
		return

	with open(output_path, "w", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=frame_data[0].keys())
		writer.writeheader()
		writer.writerows(frame_data)

#============================================

def write_zoom_yaml(summary: dict, analysis_info: dict, output_path: str) -> None:
	"""
	Write summary and analysis info to YAML format.
	"""
	# simple YAML writer (no external dependency)
	lines = []
	lines.append("pixel_zoom_assessment: 1")
	lines.append(f"input_file: \"{analysis_info.get('input_file', 'unknown')}\"")
	lines.append("")

	# video info
	lines.append("video_info:")
	lines.append(f"  width: {analysis_info.get('width', 0)}")
	lines.append(f"  height: {analysis_info.get('height', 0)}")
	lines.append(f"  fps: {analysis_info.get('fps', 0):.2f}")
	lines.append(f"  total_frames: {analysis_info.get('total_frames', 0)}")
	lines.append("")

	# analysis range
	lines.append("analysis_range:")
	lines.append(f"  start_frame: {analysis_info.get('start_frame', 0)}")
	lines.append(f"  end_frame: {analysis_info.get('end_frame', 0)}")
	lines.append(f"  frames_analyzed: {analysis_info.get('frames_analyzed', 0)}")
	lines.append("")

	# algorithm
	lines.append("algorithm:")
	lines.append(f"  method: {analysis_info.get('estimator', 'unknown')}")
	lines.append(f"  weighting: {analysis_info.get('weighting', 'unknown')}")
	lines.append(f"  confidence_threshold: {analysis_info.get('confidence_threshold', 0.1)}")
	lines.append(f"  max_radius: {analysis_info.get('max_radius', 0)}")
	lines.append("")

	# zoom stability
	lines.append("zoom_stability:")
	for key, value in sorted(summary.items()):
		if isinstance(value, float):
			lines.append(f"  {key}: {value:.6g}")
		else:
			lines.append(f"  {key}: {value}")
	lines.append(f"  failed_frames: {analysis_info.get('failed_frames', 0)}")

	with open(output_path, "w") as f:
		f.write("\n".join(lines) + "\n")

#============================================

def format_zoom_report(summary: dict, analysis_info: dict) -> str:
	"""
	Format a human-readable console report.
	"""
	lines = []
	lines.append("\n=== pixel zoom assessment ===")
	lines.append(f"  input:              {Path(analysis_info.get('input_file', 'unknown')).name}")

	frames_analyzed = analysis_info.get("frames_analyzed", 0)
	fps = analysis_info.get("fps", 1.0)
	duration_s = frames_analyzed / fps if fps > 0 else 0.0

	lines.append(f"  frames:             {frames_analyzed} ({duration_s:.1f}s "
		f"at {fps:.2f}fps)")

	lines.append("")
	lines.append("  algorithm:")
	lines.append(f"    method:           {analysis_info.get('estimator', 'unknown')}")
	lines.append(f"    weighting:        {analysis_info.get('weighting', 'unknown')}")

	lines.append("")
	lines.append("  zoom stability:")
	lines.append(f"    range:            {summary.get('zoom_range', 0):.6f}")
	lines.append(f"    cv:               {summary.get('zoom_cv', 0):.6f}")
	lines.append(f"    velocity (log) median: {summary.get('zoom_velocity_log_median', 0):.6f}")
	lines.append(f"    velocity (log) p95:    {summary.get('zoom_velocity_log_p95', 0):.6f}")
	lines.append(f"    velocity (log) max:    {summary.get('zoom_velocity_log_max', 0):.6f}")
	lines.append(f"    velocity median:  {summary.get('zoom_velocity_median', 0):.6f}")
	lines.append(f"    velocity p95:     {summary.get('zoom_velocity_p95', 0):.6f}")
	lines.append(f"    velocity max:     {summary.get('zoom_velocity_max', 0):.6f}")
	lines.append(f"    jerk p95:         {summary.get('zoom_jerk_p95', 0):.6f}")
	lines.append(f"    bounce count:     {summary.get('bounce_count', 0)}")
	lines.append(f"    bounce rate/s:    {summary.get('bounce_rate_per_s', 0):.3f}")
	lines.append(f"    drift per min:    {summary.get('drift_per_minute', 0):.6f}")
	lines.append(f"    correlation mean: {summary.get('correlation_mean', 0):.3f}")
	lines.append(f"    valid frames:     {summary.get('valid_pair_count', 0)} "
		f"({summary.get('valid_frame_fraction', 0) * 100:.1f}%)")

	return "\n".join(lines)

#============================================

def run_batch_analysis(
	directory: str,
	pattern: str,
	start_frame: int,
	max_frames: int,
	weighting: str,
	estimator: str,
	output_dir: str
) -> list:
	"""
	Analyze all videos matching pattern in directory.

	Returns:
		list of result dicts with keys: filename, summary, analysis_info
	"""
	from glob import glob

	dir_path = Path(directory)
	search_path = dir_path / pattern
	video_files = sorted(glob(str(search_path)))

	if not video_files:
		print(f"No videos matching {pattern} in {directory}")
		return []

	results = []
	for video_file in video_files:
		print(f"\nProcessing: {Path(video_file).name}")
		try:
			analysis = analyze_video_zoom(
				video_file, start_frame, max_frames, weighting, estimator
			)
			results.append({
				"filename": Path(video_file).name,
				"filepath": video_file,
				"summary": analysis["summary"],
				"analysis_info": analysis["analysis_info"],
			})
		except Exception as e:
			print(f"  ERROR: {e}")

	return results

#============================================

def write_batch_comparison_csv(batch_results: list, output_path: str) -> None:
	"""
	Write batch comparison CSV with one row per video.

	Columns include filename and key summary metrics.
	"""
	if not batch_results:
		return

	# extract key metrics
	rows = []
	for result in batch_results:
		row = {
			"filename": result["filename"],
			"zoom_range": result["summary"].get("zoom_range", 0),
			"zoom_cv": result["summary"].get("zoom_cv", 0),
			"bounce_rate_per_s": result["summary"].get("bounce_rate_per_s", 0),
			"zoom_velocity_log_p95": result["summary"].get("zoom_velocity_log_p95", 0),
			"drift_per_minute": result["summary"].get("drift_per_minute", 0),
			"valid_frame_fraction": result["summary"].get("valid_frame_fraction", 0),
		}
		rows.append(row)

	if rows:
		with open(output_path, "w", newline="") as f:
			writer = csv.DictWriter(f, fieldnames=rows[0].keys())
			writer.writeheader()
			writer.writerows(rows)

#============================================

def format_batch_comparison_table(batch_results: list) -> str:
	"""
	Format batch results as markdown comparison table.

	Sorted by bounce_rate_per_s descending (worst first).
	"""
	if not batch_results:
		return "No results"

	# sort by bounce_rate_per_s descending
	sorted_results = sorted(
		batch_results,
		key=lambda r: r["summary"].get("bounce_rate_per_s", 0),
		reverse=True
	)

	lines = []
	lines.append("\n=== Batch Comparison (sorted by bounce rate, worst first) ===\n")
	lines.append("| filename | zoom_range | bounce_rate/s | velocity_p95 | valid_fraction |")
	lines.append("|---|---|---|---|---|")

	for result in sorted_results:
		filename = result["filename"]
		s = result["summary"]
		zoom_range = s.get("zoom_range", 0)
		bounce_rate = s.get("bounce_rate_per_s", 0)
		velocity_p95 = s.get("zoom_velocity_log_p95", 0)
		valid_frac = s.get("valid_frame_fraction", 0)

		lines.append(
			f"| {filename} | {zoom_range:.6f} | {bounce_rate:.3f} | "
			f"{velocity_p95:.6f} | {valid_frac:.2%} |"
		)

	return "\n".join(lines)

#============================================

def main():
	"""
	Main entry point.
	"""
	args = parse_args()

	# ensure output directory exists
	os.makedirs(args.output_dir, exist_ok=True)

	if args.input_file:
		# single file mode
		print(f"Analyzing single file: {args.input_file}")
		analysis = analyze_video_zoom(
			args.input_file,
			args.start_frame,
			args.max_frames,
			args.weighting,
			args.estimator
		)

		# write outputs
		base_name = Path(args.input_file).stem
		csv_path = os.path.join(args.output_dir, f"{base_name}.zoom.csv")
		yaml_path = os.path.join(args.output_dir, f"{base_name}.zoom.yaml")

		write_zoom_csv(analysis["frame_data"], csv_path)
		write_zoom_yaml(analysis["summary"], analysis["analysis_info"], yaml_path)

		# print report
		report = format_zoom_report(analysis["summary"], analysis["analysis_info"])
		print(report)
		print(f"\n  wrote: {yaml_path}")

	elif args.input_dir:
		# batch mode
		print(f"Batch analysis: {args.input_dir} pattern={args.pattern}")
		batch_results = run_batch_analysis(
			args.input_dir,
			args.pattern,
			args.start_frame,
			args.max_frames,
			args.weighting,
			args.estimator,
			args.output_dir
		)

		# write batch CSV
		csv_path = os.path.join(args.output_dir, "pixel_zoom_comparison.csv")
		write_batch_comparison_csv(batch_results, csv_path)

		# print comparison table
		table = format_batch_comparison_table(batch_results)
		print(table)
		print(f"\n  wrote: {csv_path}")

	else:
		print("ERROR: Specify either -i (single file) or -d (directory)")
		sys.exit(1)

#============================================

if __name__ == "__main__":
	main()
