#!/usr/bin/env python3
"""Batch encode experiment: crop-path stability variant comparison.

Encodes multiple config variants for selected test videos, runs analyze
on each, and produces a comparison table. Designed to run overnight and
leave outputs plus a markdown results table for morning review.

Outputs:
  output_smoke/experiment/
    {video}_{variant}.mkv          -- full encode
    {video}_{variant}_clip{N}.mkv  -- short clips around worst regions
    {video}_{variant}.analysis.yaml -- analyzer report
    results.md                      -- comparison table
    results.csv                     -- machine-readable comparison
"""

# Standard Library
import os
import csv
import copy
import json
import shutil
import subprocess
import time

# PIP3 modules
import yaml

# determine repo root
REPO_ROOT = subprocess.run(
	["git", "rev-parse", "--show-toplevel"],
	capture_output=True, text=True, check=True,
).stdout.strip()

import sys
sys.path.insert(0, os.path.join(REPO_ROOT, "emwy_tools", "track_runner"))
sys.path.insert(0, os.path.join(REPO_ROOT, "emwy_tools"))

# local repo modules
import state_io
import tr_config
import tr_crop
import interval_solver
import encode_analysis
import statistics

# clip extraction: seconds around worst instability regions
CLIP_DURATION = 15
CLIP_MARGIN = 5

# experiment output directory
EXPERIMENT_DIR = os.path.join(REPO_ROOT, "output_smoke", "experiment_7b")

# videos to test (all 7 with solved intervals)
EXPERIMENT_VIDEOS = {
	"canon_60d_600m_zoom.MP4": {
		"label": "canon_60d (fair reference, pre-stabilized)",
		"clip_times": [30, 60],
	},
	"Hononega-Orion_600m-IMG_3702.mkv": {
		"label": "IMG_3702 (failure case, high convergence error)",
		"clip_times": [66, 49, 60, 14],
	},
	"Hononega-Varsity_4x400m-IMG_3707.mkv": {
		"label": "IMG_3707 (relay extreme)",
		"clip_times": [30, 60],
	},
	"IMG_3627.MOV": {
		"label": "IMG_3627",
		"clip_times": [30, 60],
	},
	"IMG_3629.mkv": {
		"label": "IMG_3629 (dense refined)",
		"clip_times": [30, 60],
	},
	"IMG_3823.MP4": {
		"label": "IMG_3823 (strong zoom)",
		"clip_times": [30, 60],
	},
	"IMG_3830.MP4": {
		"label": "IMG_3830 (control video)",
		"clip_times": [40, 80],
	},
}

# Experiment 7b (composition + piecewise zoom stabilization): 2x2 factorial design.
#
# Prior experiments:
#   1-4: axis-isolated overrides, all indistinguishable (fill_ratio=0.1 root cause)
#   5: tighter fill ratio + containment + zoom constraint -- fixed first-order problem
#   6: smart mode v1a -- rocking-boat on IMG_3702, baseline_dc was better
#   7: zoom-event damping (single-frame detector) -- missed multi-frame transitions
#
# This experiment tests two independent improvements to the direct_center baseline:
#   - Composition: torso anchor at 38% from top (more room for legs/feet)
#   - Zoom stabilization: sliding-window 3-mode (transition/settling/normal)
#     constraint that treats crop height as a noisy time series
#
# Config keys:
#   crop_torso_anchor: 0.38 or 0.50 (default centered)
#   crop_zoom_stabilization: True/False
VARIANTS = {
	"A_baseline_dc": {
		"description": "Current direct_center: centered torso, scalar zoom constraint",
		"overrides": {
			"crop_mode": "direct_center",
			"crop_aspect": "16:9",
			"crop_fill_ratio": 0.30,
			"crop_torso_anchor": 0.50,
			"crop_zoom_stabilization": False,
			"video_codec": "libx264",
			"crf": 18,
			"encode_filters": ["bilateral", "auto_levels", "hqdn3d"],
		},
	},
	"B_torso_38": {
		"description": "Composition offset only: torso at 38% from top",
		"overrides": {
			"crop_mode": "direct_center",
			"crop_aspect": "16:9",
			"crop_fill_ratio": 0.30,
			"crop_torso_anchor": 0.38,
			"crop_zoom_stabilization": False,
			"video_codec": "libx264",
			"crf": 18,
			"encode_filters": ["bilateral", "auto_levels", "hqdn3d"],
		},
	},
	"C_zoom_stabilized": {
		"description": "Piecewise zoom stabilization only, centered torso",
		"overrides": {
			"crop_mode": "direct_center",
			"crop_aspect": "16:9",
			"crop_fill_ratio": 0.30,
			"crop_torso_anchor": 0.50,
			"crop_zoom_stabilization": True,
			"video_codec": "libx264",
			"crf": 18,
			"encode_filters": ["bilateral", "auto_levels", "hqdn3d"],
		},
	},
	"D_zoom_stabilized_torso_38": {
		"description": "Piecewise zoom stabilization + torso at 38% from top",
		"overrides": {
			"crop_mode": "direct_center",
			"crop_aspect": "16:9",
			"crop_fill_ratio": 0.30,
			"crop_torso_anchor": 0.38,
			"crop_zoom_stabilization": True,
			"video_codec": "libx264",
			"crf": 18,
			"encode_filters": ["bilateral", "auto_levels", "hqdn3d"],
		},
	},
}


#============================================
def apply_overrides(base_cfg: dict, overrides: dict) -> dict:
	"""Apply variant overrides to a base config.

	Args:
		base_cfg: Base configuration dict.
		overrides: Dict of processing keys to override.

	Returns:
		New config dict with overrides applied.
	"""
	cfg = copy.deepcopy(base_cfg)
	proc = cfg.setdefault("processing", {})
	for key, value in overrides.items():
		proc[key] = value
	return cfg


#============================================
def probe_video(video_path: str) -> dict:
	"""Probe video metadata via mediainfo.

	Args:
		video_path: Path to video file.

	Returns:
		Dict with width, height, fps, frame_count, duration_s.
	"""
	cmd = ["mediainfo", "--Output=JSON", video_path]
	result = subprocess.run(cmd, capture_output=True, text=True)
	if result.returncode != 0:
		raise RuntimeError(f"mediainfo failed: {result.stderr}")
	info_json = json.loads(result.stdout)
	tracks = info_json.get("media", {}).get("track", [])
	video_track = None
	general_track = None
	for t in tracks:
		if t.get("@type") == "Video":
			video_track = t
		elif t.get("@type") == "General":
			general_track = t
	if video_track is None:
		raise RuntimeError(f"no video track in {video_path}")
	width = int(video_track["Width"])
	height = int(video_track["Height"])
	fps = float(video_track.get("FrameRate", "30.0"))
	frame_count = int(
		video_track.get("FrameCount") or general_track.get("FrameCount", 0)
	)
	duration_s = float(
		video_track.get("Duration") or general_track.get("Duration", 0)
	)
	return {
		"width": width, "height": height, "fps": fps,
		"frame_count": frame_count, "duration_s": duration_s,
	}


#============================================
def load_trajectory(video_name: str, data_dir: str, video_info: dict) -> tuple:
	"""Load and reconstruct trajectory for a video.

	Args:
		video_name: Video filename.
		data_dir: Path to tr_config directory.
		video_info: Video metadata dict.

	Returns:
		Tuple of (trajectory, interval_results, all_seeds).
	"""
	prefix = os.path.join(data_dir, video_name + ".track_runner")
	intervals_path = prefix + ".intervals.json"
	seeds_path = prefix + ".seeds.json"
	# load intervals
	intervals_file = state_io.load_intervals(intervals_path)
	solved = intervals_file.get("solved_intervals", {})
	interval_results = sorted(
		solved.values(), key=lambda r: int(r["start_frame"]),
	)
	# stitch trajectory
	trajectory = interval_solver.stitch_trajectories(interval_results)
	# load seeds and anchor
	all_seeds = []
	if os.path.isfile(seeds_path):
		seeds_data = state_io.load_seeds(seeds_path)
		all_seeds = seeds_data.get("seeds", [])
		trajectory = interval_solver.anchor_to_seeds(trajectory, all_seeds)
		fps = video_info["fps"]
		trajectory = interval_solver._apply_trajectory_erasure(
			trajectory, all_seeds, fps,
		)
	return (trajectory, interval_results, all_seeds)


#============================================
def encode_variant(
	video_name: str,
	video_path: str,
	trajectory: list,
	video_info: dict,
	cfg: dict,
	variant_name: str,
	output_dir: str,
	solver_context: dict,
	workers: int = 2,
) -> dict:
	"""Encode one variant and run analysis.

	Args:
		video_name: Video filename.
		video_path: Full path to input video.
		trajectory: Reconstructed trajectory list.
		video_info: Video metadata dict.
		cfg: Configuration dict with variant overrides applied.
		variant_name: Short name for this variant.
		output_dir: Directory for output files.
		solver_context: Solver context dict (shared across variants).
		workers: Number of encode workers.

	Returns:
		Dict with variant metrics and file paths.
	"""
	# compute crop rects with this config
	frame_width = video_info["width"]
	frame_height = video_info["height"]
	crop_rects = tr_crop.trajectory_to_crop_rects(trajectory, video_info, cfg)
	# apply experiment overrides if any are configured
	crop_rects = tr_crop.apply_experiment_overrides(
		crop_rects, trajectory, frame_width, frame_height, cfg,
	)
	# compute output dimensions
	proc_cfg = cfg.get("processing", {})
	user_resolution = proc_cfg.get("output_resolution")
	if user_resolution is not None:
		crop_w = int(user_resolution[0])
		crop_h = int(user_resolution[1])
	elif crop_rects:
		all_widths = [r[2] for r in crop_rects]
		all_heights = [r[3] for r in crop_rects]
		crop_w = int(statistics.median(all_widths))
		crop_h = int(statistics.median(all_heights))
	else:
		crop_h = video_info["height"] // 2
		crop_w = crop_h
	crop_w = crop_w - (crop_w % 2)
	crop_h = crop_h - (crop_h % 2)
	fps = video_info["fps"]
	# run analysis
	analysis = encode_analysis.analyze_crop_stability(
		crop_rects, trajectory, crop_w, crop_h, fps,
	)
	# build output filename
	stem = os.path.splitext(video_name)[0]
	output_name = f"{stem}_{variant_name}.mkv"
	output_path = os.path.join(output_dir, output_name)
	# write analysis YAML
	analysis_yaml_path = os.path.join(
		output_dir, f"{stem}_{variant_name}.analysis.yaml",
	)
	encode_analysis.write_analysis_yaml(analysis, solver_context, analysis_yaml_path)
	# encode: use the track_runner CLI to encode with overridden config
	# write a temporary config file for this variant
	temp_config_path = os.path.join(output_dir, f"_temp_{variant_name}.yaml")
	with open(temp_config_path, "w") as f:
		yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
	# build encode command
	encode_cmd = [
		sys.executable,
		os.path.join(REPO_ROOT, "emwy_tools", "track_runner", "cli.py"),
		"-i", video_path,
		"-c", temp_config_path,
		"-w", str(workers),
		"encode",
		"-o", output_path,
	]
	# resolve encode filters from config
	encode_filters = proc_cfg.get("encode_filters", [])
	if encode_filters:
		filter_str = ",".join(encode_filters)
		encode_cmd.extend(["-F", filter_str])
	elif "encode_filters" in proc_cfg and not encode_filters:
		# explicitly empty: override with no filters
		encode_cmd.extend(["-F", ""])
	print(f"\n  encoding {variant_name}: {crop_w}x{crop_h}")
	print(f"  cmd: {' '.join(encode_cmd)}")
	t_start = time.time()
	result = subprocess.run(encode_cmd, capture_output=True, text=True)
	t_elapsed = time.time() - t_start
	if result.returncode != 0:
		print(f"  ENCODE FAILED (code {result.returncode})")
		print(f"  stderr: {result.stderr[-500:]}")
		return None
	print(f"  encode complete ({t_elapsed:.0f}s)")
	# clean up temp config
	if os.path.isfile(temp_config_path):
		os.remove(temp_config_path)
	# build result row
	motion = analysis["motion_stability"]
	conf = analysis["confidence"]
	comp = analysis.get("composition", {})
	# normalized convergence: convergence_median / crop_width as percentage
	conv_med = solver_context["fwd_bwd_convergence_median"]
	conv_width_pct = round(conv_med / crop_w * 100, 2) if crop_w > 0 else 0.0
	# zoom stabilization diagnostics: detect phases on raw height signal
	import numpy
	# trajectory may contain None entries for unsolved gaps
	traj_slice = trajectory[:len(crop_rects)]
	raw_h = numpy.array([
		t["h"] if t is not None else 0.0 for t in traj_slice
	])
	trans_mask, settle_mask = tr_crop._detect_zoom_phases(raw_h)
	n_total = len(raw_h)
	n_transitions = int(trans_mask.sum())
	n_settling = int(settle_mask.sum())
	n_normal = n_total - n_transitions - n_settling
	# count transition blocks (contiguous True runs)
	trans_block_count = 0
	in_block = False
	for val in trans_mask:
		if val and not in_block:
			trans_block_count += 1
			in_block = True
		elif not val:
			in_block = False
	# crop height variance from output rects
	crop_heights = numpy.array([r[3] for r in crop_rects], dtype=float)
	crop_h_var = float(numpy.var(crop_heights))
	# torso vertical position in crop (fraction from top)
	torso_positions = []
	for i in range(len(crop_rects)):
		_, cy_rect, _, h_rect = crop_rects[i]
		if h_rect > 0 and i < len(trajectory) and trajectory[i] is not None:
			torso_cy = trajectory[i]["cy"]
			pos = (torso_cy - cy_rect) / h_rect
			torso_positions.append(pos)
	torso_pos_arr = numpy.array(torso_positions) if torso_positions else numpy.array([0.5])
	torso_pos_median = float(numpy.median(torso_pos_arr))
	torso_pos_p95 = float(numpy.percentile(torso_pos_arr, 95))
	# fraction of frames where torso is in desired upper band (< 0.42)
	torso_upper_frac = float(numpy.mean(torso_pos_arr < 0.42))
	row = {
		"video": video_name,
		"variant": variant_name,
		"output_file": output_name,
		"crop_w": crop_w,
		"crop_h": crop_h,
		"center_jerk_p95": motion["center_jerk_p95"],
		"height_jerk_p95": motion["height_jerk_p95"],
		"crop_size_cv": motion["crop_size_cv"],
		"chatter_pct": round(motion["quantization_chatter_fraction"] * 100, 1),
		"low_conf_pct": round(conf["low_conf_fraction"] * 100, 1),
		"conv_width_pct": conv_width_pct,
		"regions": len(analysis["instability_regions"]),
		"dominant_symptom": analysis["dominant_symptom"],
		# composition metrics
		"center_offset_p95": comp.get("center_offset_p95", 0.0),
		"edge_touch_count": comp.get("edge_touch_count", 0),
		"bad_frame_pct": round(comp.get("bad_frame_fraction", 0.0) * 100, 1),
		"bad_center_pct": round(comp.get("bad_center_fraction", 0.0) * 100, 1),
		"bad_edge_pct": round(comp.get("bad_edge_fraction", 0.0) * 100, 1),
		"bad_zoom_pct": round(comp.get("bad_zoom_fraction", 0.0) * 100, 1),
		"bad_run_max": comp.get("bad_run_max_length", 0),
		# zoom stabilization diagnostics
		"zoom_trans_blocks": trans_block_count,
		"trans_pct": round(n_transitions / n_total * 100, 1) if n_total > 0 else 0.0,
		"settle_pct": round(n_settling / n_total * 100, 1) if n_total > 0 else 0.0,
		"normal_pct": round(n_normal / n_total * 100, 1) if n_total > 0 else 0.0,
		"crop_h_var": round(crop_h_var, 1),
		# composition diagnostics
		"torso_pos_median": round(torso_pos_median, 3),
		"torso_pos_p95": round(torso_pos_p95, 3),
		"torso_upper_frac": round(torso_upper_frac * 100, 1),
		"encode_time_s": round(t_elapsed, 0),
		"analysis_yaml": os.path.basename(analysis_yaml_path),
	}
	return row


#============================================
def extract_clips(
	video_path: str,
	clip_times: list,
	stem: str,
	variant_name: str,
	output_dir: str,
) -> list:
	"""Extract short clips around specified times from an encoded video.

	Args:
		video_path: Path to the full encoded video.
		clip_times: List of center times in seconds.
		stem: Video stem name.
		variant_name: Variant label.
		output_dir: Output directory.

	Returns:
		List of clip output paths.
	"""
	if not os.path.isfile(video_path):
		return []
	ffmpeg_path = shutil.which("ffmpeg")
	if ffmpeg_path is None:
		print("  ffmpeg not found, skipping clip extraction")
		return []
	clips = []
	for idx, center_time in enumerate(clip_times):
		start = max(0, center_time - CLIP_MARGIN)
		clip_name = f"{stem}_{variant_name}_clip{idx}.mkv"
		clip_path = os.path.join(output_dir, clip_name)
		cmd = [
			ffmpeg_path, "-y",
			"-ss", str(start),
			"-i", video_path,
			"-t", str(CLIP_DURATION),
			"-c", "copy",
			clip_path,
		]
		result = subprocess.run(cmd, capture_output=True, text=True)
		if result.returncode == 0:
			clips.append(clip_name)
		else:
			print(f"  clip extraction failed: {clip_name}")
	return clips


#============================================
def write_results(rows: list, output_dir: str) -> None:
	"""Write comparison table as CSV and markdown.

	Args:
		rows: List of result dicts.
		output_dir: Output directory.
	"""
	# CSV
	csv_path = os.path.join(output_dir, "results.csv")
	fieldnames = [
		"video", "variant", "output_file",
		"center_jerk_p95", "height_jerk_p95", "crop_size_cv",
		"chatter_pct", "low_conf_pct", "conv_width_pct",
		"regions", "dominant_symptom",
		"center_offset_p95", "edge_touch_count",
		"bad_frame_pct", "bad_center_pct", "bad_edge_pct",
		"bad_zoom_pct", "bad_run_max",
		"zoom_trans_blocks", "trans_pct", "settle_pct", "normal_pct",
		"crop_h_var",
		"torso_pos_median", "torso_pos_p95", "torso_upper_frac",
		"encode_time_s",
	]
	with open(csv_path, "w", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
		writer.writeheader()
		for row in rows:
			writer.writerow(row)
	# markdown
	md_path = os.path.join(output_dir, "results.md")
	with open(md_path, "w") as f:
		f.write("# Encode experiment results\n\n")
		f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M')}\n\n")
		# variant descriptions
		f.write("## Variants\n\n")
		for name, info in VARIANTS.items():
			f.write(f"- **{name}**: {info['description']}\n")
			overrides = info["overrides"]
			if overrides:
				for k, v in overrides.items():
					f.write(f"  - `{k}: {v}`\n")
		f.write("\n## Motion stability comparison\n\n")
		# header
		cols = [
			"Video", "Variant", "CJerk p95", "HJerk p95",
			"SizeCV", "Chatter%", "LowConf%", "Conv/W%",
			"Regions", "Symptom", "Time(s)",
		]
		f.write("| " + " | ".join(cols) + " |\n")
		f.write("| " + " | ".join(["---"] * len(cols)) + " |\n")
		for row in rows:
			# short video name for display
			vname = row["video"]
			if len(vname) > 20:
				vname = vname[:17] + "..."
			line_cols = [
				vname,
				row["variant"],
				str(row["center_jerk_p95"]),
				str(row["height_jerk_p95"]),
				str(row["crop_size_cv"]),
				str(row["chatter_pct"]),
				str(row["low_conf_pct"]),
				str(row["conv_width_pct"]),
				str(row["regions"]),
				row["dominant_symptom"],
				str(int(row["encode_time_s"])),
			]
			f.write("| " + " | ".join(line_cols) + " |\n")
		# composition quality table
		f.write("\n## Composition quality comparison\n\n")
		comp_cols = [
			"Video", "Variant", "CtrOff p95", "EdgeTouch",
			"BadFr%", "BadCtr%", "BadEdg%", "BadZm%", "BadRun",
		]
		f.write("| " + " | ".join(comp_cols) + " |\n")
		f.write("| " + " | ".join(["---"] * len(comp_cols)) + " |\n")
		for row in rows:
			vname = row["video"]
			if len(vname) > 20:
				vname = vname[:17] + "..."
			comp_line = [
				vname,
				row["variant"],
				str(row.get("center_offset_p95", "N/A")),
				str(row.get("edge_touch_count", "N/A")),
				str(row.get("bad_frame_pct", "N/A")),
				str(row.get("bad_center_pct", "N/A")),
				str(row.get("bad_edge_pct", "N/A")),
				str(row.get("bad_zoom_pct", "N/A")),
				str(row.get("bad_run_max", "N/A")),
			]
			f.write("| " + " | ".join(comp_line) + " |\n")
		# zoom stabilization diagnostics table
		f.write("\n## Zoom stabilization diagnostics\n\n")
		zoom_cols = [
			"Video", "Variant", "ZoomBlocks", "Trans%",
			"Settle%", "Normal%", "CropHVar", "Size",
		]
		f.write("| " + " | ".join(zoom_cols) + " |\n")
		f.write("| " + " | ".join(["---"] * len(zoom_cols)) + " |\n")
		for row in rows:
			vname = row["video"]
			if len(vname) > 20:
				vname = vname[:17] + "..."
			zoom_line = [
				vname,
				row["variant"],
				str(row.get("zoom_trans_blocks", 0)),
				str(row.get("trans_pct", 0.0)),
				str(row.get("settle_pct", 0.0)),
				str(row.get("normal_pct", 0.0)),
				str(row.get("crop_h_var", 0.0)),
				f"{row['crop_w']}x{row['crop_h']}",
			]
			f.write("| " + " | ".join(zoom_line) + " |\n")
		# torso composition diagnostics table
		f.write("\n## Torso composition diagnostics\n\n")
		torso_cols = [
			"Video", "Variant", "TorsoMed", "TorsoP95",
			"Upper%",
		]
		f.write("| " + " | ".join(torso_cols) + " |\n")
		f.write("| " + " | ".join(["---"] * len(torso_cols)) + " |\n")
		for row in rows:
			vname = row["video"]
			if len(vname) > 20:
				vname = vname[:17] + "..."
			torso_line = [
				vname,
				row["variant"],
				str(row.get("torso_pos_median", "N/A")),
				str(row.get("torso_pos_p95", "N/A")),
				str(row.get("torso_upper_frac", "N/A")),
			]
			f.write("| " + " | ".join(torso_line) + " |\n")
		# pass criteria section
		f.write("\n## Pass criteria\n\n")
		f.write("- C reduces `height_jerk_p95` on IMG_3702 vs A\n")
		f.write("- C produces smaller output resolution on multimodal videos (IMG_3702, IMG_3629)\n")
		f.write("- C does not regress on canon_60d\n")
		f.write("- B places torso measurably higher in frame than A\n")
		f.write("- D combines both improvements without regression\n")
		f.write("- `bad_frame_fraction < 0.05` (< 5%)\n")
		f.write("- `height_jerk_p95 < 5.0`\n")
		f.write("\n## How to review\n\n")
		f.write("1. Watch the `_clip*.mkv` files side by side\n")
		f.write("2. Rate each 0-3 for: jitter, zoom pumping, drift, shake\n")
		f.write("3. Compare your ratings against the metrics in the table\n")
		f.write("4. Full encodes are available for promising variants\n")
	print(f"\nwrote: {csv_path}")
	print(f"wrote: {md_path}")


#============================================
def main() -> None:
	"""Run the batch encode experiment."""
	os.makedirs(EXPERIMENT_DIR, exist_ok=True)
	data_dir = os.path.join(REPO_ROOT, "tr_config")
	video_dir = os.path.join(REPO_ROOT, "TRACK_VIDEOS")
	all_rows = []
	for video_name, video_info_dict in EXPERIMENT_VIDEOS.items():
		video_path = os.path.join(video_dir, video_name)
		if not os.path.isfile(video_path):
			print(f"SKIP: {video_path} not found")
			continue
		print(f"\n{'=' * 60}")
		print(f"VIDEO: {video_info_dict['label']}")
		print(f"{'=' * 60}")
		# probe video
		vinfo = probe_video(video_path)
		print(f"  {vinfo['width']}x{vinfo['height']} {vinfo['fps']}fps"
			+ f" {vinfo['frame_count']} frames ({vinfo['duration_s']:.1f}s)")
		# load trajectory (shared across variants -- solver output is fixed)
		trajectory, interval_results, all_seeds = load_trajectory(
			video_name, data_dir, vinfo,
		)
		print(f"  trajectory: {len(trajectory)} frames, {len(all_seeds)} seeds")
		# use default config as base (single source of truth)
		base_cfg = tr_config.read_default_config()
		# compute solver context once (shared across all variants for this video)
		solver_context = encode_analysis.analyze_solver_context(
			interval_results, all_seeds, vinfo["fps"],
		)
		conv_med = solver_context["fwd_bwd_convergence_median"]
		print(f"  solver: conv_med={conv_med:.1f}px"
			+ f" seeds/min={solver_context['seed_density']}")
		# encode each variant
		for variant_name in sorted(VARIANTS.keys()):
			variant_info = VARIANTS[variant_name]
			print(f"\n--- variant {variant_name} ---")
			print(f"  {variant_info['description']}")
			cfg = apply_overrides(base_cfg, variant_info["overrides"])
			row = encode_variant(
				video_name, video_path, trajectory, vinfo,
				cfg, variant_name, EXPERIMENT_DIR,
				solver_context=solver_context,
				workers=2,
			)
			if row is not None:
				all_rows.append(row)
				# extract clips
				stem = os.path.splitext(video_name)[0]
				encoded_path = os.path.join(
					EXPERIMENT_DIR, row["output_file"],
				)
				clips = extract_clips(
					encoded_path,
					video_info_dict["clip_times"],
					stem, variant_name,
					EXPERIMENT_DIR,
				)
				if clips:
					row["clips"] = clips
					print(f"  extracted {len(clips)} clips")
	# write comparison table
	if all_rows:
		write_results(all_rows, EXPERIMENT_DIR)
	print(f"\n{'=' * 60}")
	print("EXPERIMENT COMPLETE")
	print(f"outputs: {EXPERIMENT_DIR}")
	print(f"{'=' * 60}")


#============================================
if __name__ == "__main__":
	main()
