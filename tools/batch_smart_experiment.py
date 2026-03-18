#!/usr/bin/env python3
"""Experiment 6: Smart mode vs direct_center baseline comparison.

Compares crop_mode='smart' (regime-switching) against the best
direct_center variant from Experiment 5 (B_tight_030) across all
7 test videos with solved intervals.

Phase 1: Analysis-only pass (fast, no encoding) to compare metrics.
Phase 2: Full encode for visual review (slow, launched separately).

Outputs:
  output_smoke/experiment6/
    results_analysis.md    -- metrics comparison table
    results_analysis.csv   -- machine-readable comparison
    regime_summary.md      -- regime classification per video
    {video}_{variant}.analysis.yaml  -- per-variant analysis
    {video}_{variant}.mkv  -- encoded video (phase 2 only)
"""

# Standard Library
import os
import csv
import copy
import json
import shutil
import subprocess
import sys
import time

# PIP3 modules
import yaml

# determine repo root
REPO_ROOT = subprocess.run(
	["git", "rev-parse", "--show-toplevel"],
	capture_output=True, text=True, check=True,
).stdout.strip()

sys.path.insert(0, os.path.join(REPO_ROOT, "emwy_tools", "track_runner"))
sys.path.insert(0, os.path.join(REPO_ROOT, "emwy_tools"))

# local repo modules
import state_io
import tr_config
import tr_crop
import interval_solver
import encode_analysis
import regime_classifier
import statistics

# experiment output directory
EXPERIMENT_DIR = os.path.join(REPO_ROOT, "output_smoke", "experiment6")

# clip extraction parameters
CLIP_DURATION = 15
CLIP_MARGIN = 5

# videos to test (all 7 with solved intervals)
EXPERIMENT_VIDEOS = {
	"canon_60d_600m_zoom.MP4": {
		"label": "canon_60d (fair reference)",
		"clip_times": [30, 60],
	},
	"Hononega-Orion_600m-IMG_3702.mkv": {
		"label": "IMG_3702 (failure case)",
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

# Experiment 6 variants: baseline direct_center vs smart mode
# Both use the best Experiment 5 settings as a foundation
VARIANTS = {
	"baseline_dc": {
		"description": "direct_center with tight framing + constraints (Exp5 winner)",
		"overrides": {
			"crop_mode": "direct_center",
			"crop_fill_ratio": 0.3,
			"crop_containment_radius": 0.20,
			"crop_max_height_change": 0.005,
			"crop_post_smooth_strength": 0.03,
			"crop_post_smooth_size_strength": 0.0,
			"crop_post_smooth_max_velocity": 15.0,
		},
	},
	"smart_v1a": {
		"description": "smart mode: regime-switching controller with composition rules",
		"overrides": {
			"crop_mode": "smart",
			"crop_fill_ratio": 0.3,
			"crop_containment_radius": 0.20,
			"crop_max_height_change": 0.005,
			"crop_post_smooth_strength": 0.03,
			"crop_post_smooth_size_strength": 0.0,
			"crop_post_smooth_max_velocity": 15.0,
		},
	},
}


#============================================
def apply_overrides(base_cfg: dict, overrides: dict) -> dict:
	"""Apply variant overrides to a base config."""
	cfg = copy.deepcopy(base_cfg)
	proc = cfg.setdefault("processing", {})
	for key, value in overrides.items():
		proc[key] = value
	return cfg


#============================================
def probe_video(video_path: str) -> dict:
	"""Probe video metadata via mediainfo."""
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
	"""Load and reconstruct trajectory for a video."""
	prefix = os.path.join(data_dir, video_name + ".track_runner")
	intervals_path = prefix + ".intervals.json"
	seeds_path = prefix + ".seeds.json"
	intervals_file = state_io.load_intervals(intervals_path)
	solved = intervals_file.get("solved_intervals", {})
	interval_results = sorted(
		solved.values(), key=lambda r: int(r["start_frame"]),
	)
	trajectory = interval_solver.stitch_trajectories(interval_results)
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
def analyze_variant(
	video_name: str,
	trajectory: list,
	video_info: dict,
	cfg: dict,
	variant_name: str,
	output_dir: str,
	solver_context: dict,
) -> dict:
	"""Run analysis for one variant (no encoding).

	Args:
		video_name: Video filename.
		trajectory: Reconstructed trajectory list.
		video_info: Video metadata dict.
		cfg: Configuration dict with variant overrides applied.
		variant_name: Short name for this variant.
		output_dir: Directory for output files.
		solver_context: Solver context dict.

	Returns:
		Dict with variant metrics.
	"""
	# compute crop rects with this config
	crop_rects = tr_crop.trajectory_to_crop_rects(trajectory, video_info, cfg)
	# compute output dimensions
	if crop_rects:
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
	# write analysis YAML
	stem = os.path.splitext(video_name)[0]
	analysis_yaml_path = os.path.join(
		output_dir, f"{stem}_{variant_name}.analysis.yaml",
	)
	# run regime classification for both variants (diagnostic)
	regime_spans = regime_classifier.classify_regimes(trajectory, video_info)
	regime_summary_line = regime_classifier.format_regime_summary(
		regime_spans, video_info["frame_count"],
	)
	encode_analysis.write_analysis_yaml(
		analysis, solver_context, analysis_yaml_path,
		regime_spans=regime_spans,
	)
	# build result row
	motion = analysis["motion_stability"]
	conf = analysis["confidence"]
	comp = analysis.get("composition", {})
	conv_med = solver_context["fwd_bwd_convergence_median"]
	conv_width_pct = round(conv_med / crop_w * 100, 2) if crop_w > 0 else 0.0
	row = {
		"video": video_name,
		"variant": variant_name,
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
		"center_offset_p95": comp.get("center_offset_p95", 0.0),
		"edge_touch_count": comp.get("edge_touch_count", 0),
		"bad_frame_pct": round(comp.get("bad_frame_fraction", 0.0) * 100, 1),
		"bad_center_pct": round(comp.get("bad_center_fraction", 0.0) * 100, 1),
		"bad_edge_pct": round(comp.get("bad_edge_fraction", 0.0) * 100, 1),
		"bad_zoom_pct": round(comp.get("bad_zoom_fraction", 0.0) * 100, 1),
		"bad_run_max": comp.get("bad_run_max_length", 0),
		"regime_summary": regime_summary_line,
	}
	return row


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

	Returns:
		Dict with variant metrics and file paths, or None on failure.
	"""
	crop_rects = tr_crop.trajectory_to_crop_rects(trajectory, video_info, cfg)
	# compute output dimensions
	if crop_rects:
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
	# write temp config and encode
	temp_config_path = os.path.join(output_dir, f"_temp_{variant_name}.yaml")
	with open(temp_config_path, "w") as f:
		yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
	proc_cfg = cfg.get("processing", {})
	encode_cmd = [
		sys.executable,
		os.path.join(REPO_ROOT, "emwy_tools", "track_runner", "cli.py"),
		"-i", video_path,
		"-c", temp_config_path,
		"-w", str(workers),
		"encode",
		"-o", output_path,
	]
	encode_filters = proc_cfg.get("encode_filters", [])
	if encode_filters:
		filter_str = ",".join(encode_filters)
		encode_cmd.extend(["-F", filter_str])
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
	conv_med = solver_context["fwd_bwd_convergence_median"]
	conv_width_pct = round(conv_med / crop_w * 100, 2) if crop_w > 0 else 0.0
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
		"center_offset_p95": comp.get("center_offset_p95", 0.0),
		"edge_touch_count": comp.get("edge_touch_count", 0),
		"bad_frame_pct": round(comp.get("bad_frame_fraction", 0.0) * 100, 1),
		"bad_center_pct": round(comp.get("bad_center_fraction", 0.0) * 100, 1),
		"bad_edge_pct": round(comp.get("bad_edge_fraction", 0.0) * 100, 1),
		"bad_zoom_pct": round(comp.get("bad_zoom_fraction", 0.0) * 100, 1),
		"bad_run_max": comp.get("bad_run_max_length", 0),
		"encode_time_s": round(t_elapsed, 0),
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
	"""Extract short clips from an encoded video."""
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
def write_analysis_results(rows: list, output_dir: str) -> None:
	"""Write analysis-only comparison table."""
	csv_path = os.path.join(output_dir, "results_analysis.csv")
	fieldnames = [
		"video", "variant",
		"center_jerk_p95", "height_jerk_p95", "crop_size_cv",
		"chatter_pct", "low_conf_pct",
		"center_offset_p95", "edge_touch_count",
		"bad_frame_pct", "bad_center_pct", "bad_edge_pct",
		"bad_zoom_pct", "bad_run_max",
		"regime_summary",
	]
	with open(csv_path, "w", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
		writer.writeheader()
		for row in rows:
			writer.writerow(row)
	# markdown report
	md_path = os.path.join(output_dir, "results_analysis.md")
	with open(md_path, "w") as f:
		f.write("# Experiment 6: Smart mode vs direct_center\n\n")
		f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M')}\n\n")
		# variant descriptions
		f.write("## Variants\n\n")
		for name, info in VARIANTS.items():
			f.write(f"- **{name}**: {info['description']}\n")
		# regime classification summary
		f.write("\n## Regime classification per video\n\n")
		for row in rows:
			if row["variant"] == "smart_v1a":
				vname = row["video"]
				if len(vname) > 30:
					vname = vname[:27] + "..."
				f.write(f"- {vname}: {row.get('regime_summary', 'N/A')}\n")
		# motion stability table
		f.write("\n## Motion stability comparison\n\n")
		cols = [
			"Video", "Variant", "CJerk p95", "HJerk p95",
			"SizeCV", "Chatter%", "LowConf%",
		]
		f.write("| " + " | ".join(cols) + " |\n")
		f.write("| " + " | ".join(["---"] * len(cols)) + " |\n")
		for row in rows:
			vname = row["video"]
			if len(vname) > 20:
				vname = vname[:17] + "..."
			line_cols = [
				vname, row["variant"],
				str(row["center_jerk_p95"]),
				str(row["height_jerk_p95"]),
				str(row["crop_size_cv"]),
				str(row["chatter_pct"]),
				str(row["low_conf_pct"]),
			]
			f.write("| " + " | ".join(line_cols) + " |\n")
		# composition table
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
				vname, row["variant"],
				str(row.get("center_offset_p95", "N/A")),
				str(row.get("edge_touch_count", "N/A")),
				str(row.get("bad_frame_pct", "N/A")),
				str(row.get("bad_center_pct", "N/A")),
				str(row.get("bad_edge_pct", "N/A")),
				str(row.get("bad_zoom_pct", "N/A")),
				str(row.get("bad_run_max", "N/A")),
			]
			f.write("| " + " | ".join(comp_line) + " |\n")
		# delta summary
		f.write("\n## Per-video delta (smart - baseline)\n\n")
		f.write("Negative = smart is better for jerk/chatter/bad metrics.\n")
		f.write("Positive = smart is better for edge margins.\n\n")
		delta_cols = [
			"Video", "dCJerk95", "dHJerk95", "dSizeCV",
			"dBadFr%", "dBadEdg%", "dBadZm%",
		]
		f.write("| " + " | ".join(delta_cols) + " |\n")
		f.write("| " + " | ".join(["---"] * len(delta_cols)) + " |\n")
		# group by video
		by_video = {}
		for row in rows:
			vid = row["video"]
			by_video.setdefault(vid, {})[row["variant"]] = row
		for vid, variants in by_video.items():
			if "baseline_dc" not in variants or "smart_v1a" not in variants:
				continue
			base = variants["baseline_dc"]
			smart = variants["smart_v1a"]
			vname = vid
			if len(vname) > 20:
				vname = vname[:17] + "..."
			d_cj = round(smart["center_jerk_p95"] - base["center_jerk_p95"], 2)
			d_hj = round(smart["height_jerk_p95"] - base["height_jerk_p95"], 2)
			d_cv = round(smart["crop_size_cv"] - base["crop_size_cv"], 3)
			d_bf = round(smart["bad_frame_pct"] - base["bad_frame_pct"], 1)
			d_be = round(smart["bad_edge_pct"] - base["bad_edge_pct"], 1)
			d_bz = round(smart["bad_zoom_pct"] - base["bad_zoom_pct"], 1)
			f.write(f"| {vname} | {d_cj} | {d_hj} | {d_cv}"
				+ f" | {d_bf} | {d_be} | {d_bz} |\n")
		# evaluation criteria
		f.write("\n## Evaluation criteria (Milestone B)\n\n")
		f.write("- Smart mode 'same or better' on all 4 dimensions for >= 5/7 videos\n")
		f.write("- Smart mode 'better' on >= 1 dimension for failure cases (3702, 3707)\n")
		f.write("- 4 dimensions: lateral comfort (CJerk), zoom comfort (HJerk/SizeCV),\n")
		f.write("  subject lock (BadCenter/BadEdge), watchability (BadFrame/BadRun)\n")
	print(f"\nwrote: {csv_path}")
	print(f"wrote: {md_path}")


#============================================
def write_encode_results(rows: list, output_dir: str) -> None:
	"""Write encode comparison table (with timing)."""
	csv_path = os.path.join(output_dir, "results_encode.csv")
	fieldnames = [
		"video", "variant", "output_file",
		"center_jerk_p95", "height_jerk_p95", "crop_size_cv",
		"chatter_pct", "low_conf_pct",
		"center_offset_p95", "edge_touch_count",
		"bad_frame_pct", "bad_center_pct", "bad_edge_pct",
		"bad_zoom_pct", "bad_run_max",
		"encode_time_s",
	]
	with open(csv_path, "w", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
		writer.writeheader()
		for row in rows:
			writer.writerow(row)
	print(f"wrote: {csv_path}")


#============================================
def main() -> None:
	"""Run the smart mode experiment."""
	import argparse
	parser = argparse.ArgumentParser(
		description="Experiment 6: smart mode vs direct_center baseline",
	)
	parser.add_argument(
		"-p", "--phase", dest="phase", type=int, default=1,
		help="Phase: 1=analysis only, 2=analysis+encode",
	)
	parser.add_argument(
		"-w", "--workers", dest="workers", type=int, default=2,
		help="Encode workers (phase 2 only)",
	)
	args = parser.parse_args()
	os.makedirs(EXPERIMENT_DIR, exist_ok=True)
	data_dir = os.path.join(REPO_ROOT, "tr_config")
	video_dir = os.path.join(REPO_ROOT, "TRACK_VIDEOS")
	analysis_rows = []
	encode_rows = []
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
		# load trajectory
		trajectory, interval_results, all_seeds = load_trajectory(
			video_name, data_dir, vinfo,
		)
		print(f"  trajectory: {len(trajectory)} frames, {len(all_seeds)} seeds")
		# load base config
		config_path = os.path.join(
			data_dir, video_name + ".track_runner.config.yaml",
		)
		if os.path.isfile(config_path):
			base_cfg = tr_config.load_config(config_path)
		else:
			base_cfg = tr_config.default_config()
		# solver context (shared)
		solver_context = encode_analysis.analyze_solver_context(
			interval_results, all_seeds, vinfo["fps"],
		)
		conv_med = solver_context["fwd_bwd_convergence_median"]
		print(f"  solver: conv_med={conv_med:.1f}px"
			+ f" seeds/min={solver_context['seed_density']}")
		# phase 1: analysis only
		for variant_name in sorted(VARIANTS.keys()):
			variant_info = VARIANTS[variant_name]
			print(f"\n  analyzing {variant_name}...")
			cfg = apply_overrides(base_cfg, variant_info["overrides"])
			row = analyze_variant(
				video_name, trajectory, vinfo, cfg,
				variant_name, EXPERIMENT_DIR, solver_context,
			)
			analysis_rows.append(row)
			print(f"    {row['regime_summary']}")
			print(f"    CJerk95={row['center_jerk_p95']}"
				+ f" HJerk95={row['height_jerk_p95']}"
				+ f" SizeCV={row['crop_size_cv']}"
				+ f" BadFr={row['bad_frame_pct']}%")
		# phase 2: encode (if requested)
		if args.phase >= 2:
			for variant_name in sorted(VARIANTS.keys()):
				variant_info = VARIANTS[variant_name]
				print(f"\n--- encoding {variant_name} ---")
				cfg = apply_overrides(base_cfg, variant_info["overrides"])
				row = encode_variant(
					video_name, video_path, trajectory, vinfo,
					cfg, variant_name, EXPERIMENT_DIR,
					solver_context=solver_context,
					workers=args.workers,
				)
				if row is not None:
					encode_rows.append(row)
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
						print(f"  extracted {len(clips)} clips")
	# write results
	if analysis_rows:
		write_analysis_results(analysis_rows, EXPERIMENT_DIR)
	if encode_rows:
		write_encode_results(encode_rows, EXPERIMENT_DIR)
	print(f"\n{'=' * 60}")
	print("EXPERIMENT COMPLETE")
	print(f"outputs: {EXPERIMENT_DIR}")
	print(f"{'=' * 60}")


#============================================
if __name__ == "__main__":
	main()
