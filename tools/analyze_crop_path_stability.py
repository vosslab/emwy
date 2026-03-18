#!/usr/bin/env python3
"""Cross-video crop-path stability analysis for track runner V4 findings.

Runs encode_analysis.analyze_crop_stability() and analyze_solver_context()
across all test videos with solved intervals, producing per-video metric
summaries and a cross-video comparison table.

Outputs:
  - Per-video analysis YAML files in tr_config/
  - Summary CSV to output_smoke/
  - Console report for inclusion in findings doc
"""

# Standard Library
import os
import csv
import json
import glob
import argparse
import statistics
import subprocess

# determine repo root for imports
REPO_ROOT = subprocess.run(
	["git", "rev-parse", "--show-toplevel"],
	capture_output=True, text=True, check=True,
).stdout.strip()

# add track_runner and tools to path for imports
import sys
sys.path.insert(0, os.path.join(REPO_ROOT, "emwy_tools", "track_runner"))
sys.path.insert(0, os.path.join(REPO_ROOT, "emwy_tools"))

# local repo modules
import state_io
import tr_config
import tr_crop
import interval_solver
import encode_analysis


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments.

	Returns:
		Parsed argparse namespace.
	"""
	parser = argparse.ArgumentParser(
		description="Cross-video crop-path stability analysis for V4 findings",
	)
	parser.add_argument(
		"-i", "--input", dest="input_dir", type=str, default=None,
		help="Directory containing tr_config data files (default: tr_config/)",
	)
	parser.add_argument(
		"-o", "--output", dest="output_dir", type=str, default=None,
		help="Output directory for CSV (default: output_smoke/)",
	)
	args = parser.parse_args()
	return args


#============================================
def discover_videos(data_dir: str) -> dict:
	"""Discover videos with solved intervals in the data directory.

	Args:
		data_dir: Path to tr_config directory.

	Returns:
		Dict mapping short video name to paths dict with keys:
		seeds_path, intervals_path, diagnostics_path, config_path.
	"""
	# find all intervals files
	pattern = os.path.join(data_dir, "*.track_runner.intervals.json")
	intervals_files = sorted(glob.glob(pattern))
	videos = {}
	for ipath in intervals_files:
		basename = os.path.basename(ipath)
		# extract video name by removing .track_runner.intervals.json
		video_name = basename.replace(".track_runner.intervals.json", "")
		prefix = os.path.join(data_dir, video_name + ".track_runner")
		seeds_path = prefix + ".seeds.json"
		diag_path = prefix + ".diagnostics.json"
		config_path = prefix + ".config.yaml"
		videos[video_name] = {
			"intervals_path": ipath,
			"seeds_path": seeds_path if os.path.isfile(seeds_path) else None,
			"diagnostics_path": diag_path if os.path.isfile(diag_path) else None,
			"config_path": config_path if os.path.isfile(config_path) else None,
		}
	return videos


#============================================
def probe_video(video_path: str) -> dict:
	"""Probe video metadata via mediainfo.

	Args:
		video_path: Path to video file.

	Returns:
		Dict with width, height, fps, frame_count, duration_s.
	"""
	cmd = [
		"mediainfo", "--Output=JSON", video_path,
	]
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
	fps_str = video_track.get("FrameRate", "30.0")
	fps = float(fps_str)
	frame_count = int(video_track.get("FrameCount") or general_track.get("FrameCount", 0))
	duration_s = float(video_track.get("Duration") or general_track.get("Duration", 0))
	video_info = {
		"width": width,
		"height": height,
		"fps": fps,
		"frame_count": frame_count,
		"duration_s": duration_s,
	}
	return video_info


#============================================
def analyze_one_video(
	video_name: str,
	paths: dict,
	video_dir: str,
) -> dict:
	"""Run full crop-path analysis on one video.

	Args:
		video_name: Video filename.
		paths: Dict with intervals_path, seeds_path, diagnostics_path, config_path.
		video_dir: Directory containing the actual video files.

	Returns:
		Dict with keys: video_name, video_info, analysis, solver_context,
		or None if analysis cannot be performed.
	"""
	print(f"\n--- {video_name} ---")
	# find actual video file
	video_path = os.path.join(video_dir, video_name)
	if not os.path.isfile(video_path):
		print(f"  video file not found: {video_path}, skipping")
		return None
	# probe video
	video_info = probe_video(video_path)
	print(f"  {video_info['width']}x{video_info['height']}"
		+ f" {video_info['fps']}fps"
		+ f" {video_info['frame_count']} frames"
		+ f" ({video_info['duration_s']:.1f}s)")
	# load config
	if paths["config_path"] is not None:
		cfg = tr_config.load_config(paths["config_path"])
	else:
		cfg = tr_config.default_config()
	# load intervals
	intervals_file = state_io.load_intervals(paths["intervals_path"])
	solved = intervals_file.get("solved_intervals", {})
	if not solved:
		print("  no solved intervals, skipping")
		return None
	interval_results = sorted(
		solved.values(), key=lambda r: int(r["start_frame"]),
	)
	print(f"  {len(interval_results)} solved intervals")
	# stitch trajectory
	trajectory = interval_solver.stitch_trajectories(interval_results)
	# load seeds and apply anchoring
	all_seeds = []
	if paths["seeds_path"] is not None:
		seeds_data = state_io.load_seeds(paths["seeds_path"])
		all_seeds = seeds_data.get("seeds", [])
		trajectory = interval_solver.anchor_to_seeds(trajectory, all_seeds)
		fps = video_info["fps"]
		trajectory = interval_solver._apply_trajectory_erasure(
			trajectory, all_seeds, fps,
		)
	print(f"  trajectory: {len(trajectory)} frames, {len(all_seeds)} seeds")
	if not trajectory:
		print("  empty trajectory after anchoring, skipping")
		return None
	# compute crop rects
	crop_rects = tr_crop.trajectory_to_crop_rects(trajectory, video_info, cfg)
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
	print(f"  output: {crop_w}x{crop_h}")
	# run analysis
	analysis = encode_analysis.analyze_crop_stability(
		crop_rects, trajectory, crop_w, crop_h, fps,
	)
	solver_context = encode_analysis.analyze_solver_context(
		interval_results, all_seeds, fps,
	)
	print(f"  dominant symptom: {analysis['dominant_symptom']}")
	print(f"  center jerk p95: {analysis['motion_stability']['center_jerk_p95']}")
	print(f"  height jerk p95: {analysis['motion_stability']['height_jerk_p95']}")
	print(f"  crop size CV: {analysis['motion_stability']['crop_size_cv']}")
	print(f"  chatter: {analysis['motion_stability']['quantization_chatter_fraction'] * 100:.1f}%")
	print(f"  low conf: {analysis['confidence']['low_conf_fraction'] * 100:.1f}%")
	print(f"  instability regions: {len(analysis['instability_regions'])}")
	# composition metrics
	comp = analysis.get("composition", {})
	if comp:
		print("  composition:")
		print(f"    center offset p95: {comp.get('center_offset_p95', 'N/A')}")
		print(f"    edge margin p05: {comp.get('edge_margin_p05', 'N/A')}")
		print(f"    edge touch count: {comp.get('edge_touch_count', 'N/A')}")
		print(f"    bad frame fraction: {comp.get('bad_frame_fraction', 'N/A')}")
		print(f"    bad run max length: {comp.get('bad_run_max_length', 'N/A')}")
	comp = analysis.get("composition", {})
	if comp:
		print(f"  center offset p95: {comp.get('center_offset_p95', 'N/A')}")
		print(f"  edge touch count: {comp.get('edge_touch_count', 'N/A')}")
		print(f"  bad frame fraction: {comp.get('bad_frame_fraction', 'N/A')}")
	result = {
		"video_name": video_name,
		"video_info": video_info,
		"analysis": analysis,
		"solver_context": solver_context,
		"output_size": [crop_w, crop_h],
	}
	return result


#============================================
def write_comparison_csv(results: list, output_path: str) -> None:
	"""Write cross-video comparison CSV.

	Args:
		results: List of per-video result dicts.
		output_path: CSV output file path.
	"""
	fieldnames = [
		"video", "duration_s", "frames", "fps", "output_w", "output_h",
		"center_jerk_p50", "center_jerk_p95", "center_jerk_max",
		"height_jerk_p50", "height_jerk_p95", "height_jerk_max",
		"crop_size_cv", "quantization_chatter_fraction",
		"mean_confidence", "low_conf_fraction",
		"instability_regions", "dominant_symptom",
		"seed_density", "desert_count",
		"fwd_bwd_convergence_median", "fwd_bwd_convergence_p90",
		"identity_score_median", "competitor_margin_median",
		"center_offset_p95", "edge_margin_p05", "edge_touch_count",
		"bad_frame_fraction", "bad_run_max_length",
		"bad_center_fraction", "bad_edge_fraction", "bad_zoom_fraction",
	]
	with open(output_path, "w", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=fieldnames)
		writer.writeheader()
		for r in results:
			analysis = r["analysis"]
			solver = r["solver_context"]
			motion = analysis["motion_stability"]
			conf = analysis["confidence"]
			comp = analysis.get("composition", {})
			row = {
				"video": r["video_name"],
				"duration_s": r["video_info"]["duration_s"],
				"frames": analysis["summary"]["frames"],
				"fps": r["video_info"]["fps"],
				"output_w": r["output_size"][0],
				"output_h": r["output_size"][1],
				"center_jerk_p50": motion["center_jerk_p50"],
				"center_jerk_p95": motion["center_jerk_p95"],
				"center_jerk_max": motion["center_jerk_max"],
				"height_jerk_p50": motion["height_jerk_p50"],
				"height_jerk_p95": motion["height_jerk_p95"],
				"height_jerk_max": motion["height_jerk_max"],
				"crop_size_cv": motion["crop_size_cv"],
				"quantization_chatter_fraction": motion["quantization_chatter_fraction"],
				"mean_confidence": conf["mean"],
				"low_conf_fraction": conf["low_conf_fraction"],
				"instability_regions": len(analysis["instability_regions"]),
				"dominant_symptom": analysis["dominant_symptom"],
				"seed_density": solver["seed_density"],
				"desert_count": solver["desert_count"],
				"fwd_bwd_convergence_median": solver["fwd_bwd_convergence_median"],
				"fwd_bwd_convergence_p90": solver["fwd_bwd_convergence_p90"],
				"identity_score_median": solver["identity_score_median"],
				"competitor_margin_median": solver["competitor_margin_median"],
				"center_offset_p95": comp.get("center_offset_p95", "N/A"),
				"edge_margin_p05": comp.get("edge_margin_p05", "N/A"),
				"edge_touch_count": comp.get("edge_touch_count", "N/A"),
				"bad_frame_fraction": comp.get("bad_frame_fraction", "N/A"),
				"bad_run_max_length": comp.get("bad_run_max_length", "N/A"),
				"bad_center_fraction": comp.get("bad_center_fraction", "N/A"),
				"bad_edge_fraction": comp.get("bad_edge_fraction", "N/A"),
				"bad_zoom_fraction": comp.get("bad_zoom_fraction", "N/A"),
			}
			writer.writerow(row)
	print(f"\nwrote: {output_path}")


#============================================
def print_comparison_table(results: list) -> None:
	"""Print a formatted markdown comparison table to console.

	Args:
		results: List of per-video result dicts.
	"""
	# short names for display
	def short_name(name: str) -> str:
		"""Truncate video name for table display."""
		if len(name) > 25:
			truncated = name[:22] + "..."
			return truncated
		return name

	print("\n\n## Cross-video crop-path stability comparison\n")
	# header
	header_cols = [
		"Video", "Dur(s)", "CJerk p95", "HJerk p95",
		"SizeCV", "Chatter%", "LowConf%", "Regions", "Symptom",
	]
	header_line = "| " + " | ".join(header_cols) + " |"
	sep_line = "| " + " | ".join(["---"] * len(header_cols)) + " |"
	print(header_line)
	print(sep_line)
	for r in results:
		a = r["analysis"]
		m = a["motion_stability"]
		c = a["confidence"]
		cols = [
			short_name(r["video_name"]),
			f"{r['video_info']['duration_s']:.0f}",
			f"{m['center_jerk_p95']:.2f}",
			f"{m['height_jerk_p95']:.2f}",
			f"{m['crop_size_cv']:.3f}",
			f"{m['quantization_chatter_fraction'] * 100:.1f}",
			f"{c['low_conf_fraction'] * 100:.1f}",
			f"{len(a['instability_regions'])}",
			a["dominant_symptom"],
		]
		row_line = "| " + " | ".join(cols) + " |"
		print(row_line)
	# solver context table
	print("\n\n## Solver context comparison\n")
	header_cols2 = [
		"Video", "Seeds/min", "Deserts",
		"Conv med", "Conv p90",
		"ID score", "Margin",
	]
	header_line2 = "| " + " | ".join(header_cols2) + " |"
	sep_line2 = "| " + " | ".join(["---"] * len(header_cols2)) + " |"
	print(header_line2)
	print(sep_line2)
	for r in results:
		s = r["solver_context"]
		cols2 = [
			short_name(r["video_name"]),
			f"{s['seed_density']:.1f}",
			f"{s['desert_count']}",
			f"{s['fwd_bwd_convergence_median']:.1f}",
			f"{s['fwd_bwd_convergence_p90']:.1f}",
			f"{s['identity_score_median']:.3f}",
			f"{s['competitor_margin_median']:.3f}",
		]
		row_line2 = "| " + " | ".join(cols2) + " |"
		print(row_line2)
	# composition quality table
	print("\n\n## Composition quality comparison\n")
	header_cols3 = [
		"Video", "CtrOff p95", "EdgeM p05", "EdgeTouch",
		"BadFr%", "BadRun", "BadCtr%", "BadEdg%", "BadZm%",
	]
	header_line3 = "| " + " | ".join(header_cols3) + " |"
	sep_line3 = "| " + " | ".join(["---"] * len(header_cols3)) + " |"
	print(header_line3)
	print(sep_line3)
	for r in results:
		a = r["analysis"]
		comp = a.get("composition", {})
		cols3 = [
			short_name(r["video_name"]),
			f"{comp.get('center_offset_p95', 'N/A')}",
			f"{comp.get('edge_margin_p05', 'N/A')}",
			f"{comp.get('edge_touch_count', 'N/A')}",
			f"{comp.get('bad_frame_fraction', 'N/A') * 100 if isinstance(comp.get('bad_frame_fraction'), (int, float)) else 'N/A'}",
			f"{comp.get('bad_run_max_length', 'N/A')}",
			f"{comp.get('bad_center_fraction', 'N/A') * 100 if isinstance(comp.get('bad_center_fraction'), (int, float)) else 'N/A'}",
			f"{comp.get('bad_edge_fraction', 'N/A') * 100 if isinstance(comp.get('bad_edge_fraction'), (int, float)) else 'N/A'}",
			f"{comp.get('bad_zoom_fraction', 'N/A') * 100 if isinstance(comp.get('bad_zoom_fraction'), (int, float)) else 'N/A'}",
		]
		row_line3 = "| " + " | ".join(str(c) for c in cols3) + " |"
		print(row_line3)


#============================================
def main() -> None:
	"""Main entry point for cross-video crop-path analysis."""
	args = parse_args()
	# resolve data directory
	data_dir = args.input_dir
	if data_dir is None:
		data_dir = os.path.join(REPO_ROOT, "tr_config")
	# resolve output directory
	output_dir = args.output_dir
	if output_dir is None:
		output_dir = os.path.join(REPO_ROOT, "output_smoke")
	os.makedirs(output_dir, exist_ok=True)
	# resolve video directory (TRACK_VIDEOS/ in repo)
	video_dir = os.path.join(REPO_ROOT, "TRACK_VIDEOS")
	if not os.path.isdir(video_dir):
		raise RuntimeError(f"video directory not found: {video_dir}")
	print(f"data dir:  {data_dir}")
	print(f"video dir: {video_dir}")
	print(f"output:    {output_dir}")
	# discover videos
	videos = discover_videos(data_dir)
	print(f"\nfound {len(videos)} videos with solved intervals")
	# analyze each video
	results = []
	for video_name in sorted(videos.keys()):
		paths = videos[video_name]
		result = analyze_one_video(video_name, paths, video_dir)
		if result is not None:
			results.append(result)
			# also write per-video analysis YAML
			analysis_path = os.path.join(
				data_dir, video_name + ".encode_analysis.yaml",
			)
			encode_analysis.write_analysis_yaml(
				result["analysis"], result["solver_context"], analysis_path,
			)
	if not results:
		print("\nno videos could be analyzed")
		return
	# write cross-video CSV
	csv_path = os.path.join(output_dir, "crop_path_stability.csv")
	write_comparison_csv(results, csv_path)
	# print comparison tables
	print_comparison_table(results)
	# summary
	print(f"\n\nanalyzed {len(results)} videos")
	print(f"CSV: {csv_path}")


#============================================
if __name__ == "__main__":
	main()
