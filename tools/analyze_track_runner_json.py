#!/usr/bin/env python3
"""Analyze track runner v3 JSON data and produce text report, CSVs, and summary JSON."""

# Standard Library
import os
import csv
import json
import math
import glob
import argparse
import datetime
import statistics
import subprocess

SCRIPT_VERSION = "1.0.0"

# size bins from the v1/v2 seed variability study
SIZE_BINS = [
	("tiny", 0, 15),
	("small", 15, 30),
	("medium", 30, 60),
	("large", 60, 120),
	("xlarge", 120, float("inf")),
]

# valid seed statuses recognized by the v3 system
KNOWN_STATUSES = frozenset([
	"visible", "partial", "approximate", "not_in_frame",
])

# valid seed modes
KNOWN_MODES = frozenset([
	"initial", "suggested_refine", "interval_refine", "gap_refine",
	"edit_redraw", "solve_refine", "interactive_refine", "bbox_polish",
	"target_refine",
])


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments."""
	parser = argparse.ArgumentParser(
		description="Analyze track runner v3 JSON data files"
	)
	parser.add_argument(
		'-i', '--input', dest='input_dir', type=str,
		default=None,
		help="Directory containing track runner JSON files (default: TRACK_VIDEOS/)"
	)
	parser.add_argument(
		'-o', '--output', dest='output_dir', type=str,
		default=None,
		help="Output directory for CSVs and summary JSON (default: output_smoke/)"
	)
	args = parser.parse_args()
	return args


#============================================
def get_repo_root() -> str:
	"""Get the repository root using git."""
	result = subprocess.run(
		["git", "rev-parse", "--show-toplevel"],
		capture_output=True, text=True, check=True,
	)
	repo_root = result.stdout.strip()
	return repo_root


#============================================
def discover_videos(input_dir: str) -> dict:
	"""Discover video JSON triples in the input directory.

	Returns:
		Dict mapping video_name to dict with keys: seeds_path, intervals_path,
		diagnostics_path (each may be None if the file does not exist).
	"""
	# find all seeds files
	seeds_files = sorted(glob.glob(
		os.path.join(input_dir, "*.track_runner.seeds.json")
	))
	videos = {}
	for sf in seeds_files:
		basename = os.path.basename(sf)
		# extract video name by removing .track_runner.seeds.json
		video_name = basename.replace(".track_runner.seeds.json", "")
		prefix = os.path.join(input_dir, video_name + ".track_runner")
		intervals_path = prefix + ".intervals.json"
		diagnostics_path = prefix + ".diagnostics.json"
		videos[video_name] = {
			"seeds_path": sf,
			"intervals_path": intervals_path if os.path.isfile(intervals_path) else None,
			"diagnostics_path": diagnostics_path if os.path.isfile(diagnostics_path) else None,
		}
	return videos


#============================================
def load_json_file(path: str) -> dict:
	"""Load a JSON file and return its contents."""
	with open(path, "r") as f:
		data = json.load(f)
	return data


#============================================
def torso_linear_size(seed: dict) -> float:
	"""Compute linear size from torso_box as sqrt(w*h)."""
	box = seed.get("torso_box")
	if box is None:
		return 0.0
	# torso_box is [x, y, w, h]
	w = box[2]
	h = box[3]
	linear = math.sqrt(w * h)
	return linear


#============================================
def torso_area(seed: dict) -> float:
	"""Compute area from torso_box."""
	box = seed.get("torso_box")
	if box is None:
		return 0.0
	area = box[2] * box[3]
	return area


#============================================
def size_bin_label(linear_size: float) -> str:
	"""Return the size bin label for a given linear size."""
	for label, lo, hi in SIZE_BINS:
		if lo <= linear_size < hi:
			return label
	return "unknown"


#============================================
def percentile(sorted_values: list, p: float) -> float:
	"""Compute p-th percentile from a sorted list (0-100 scale)."""
	if not sorted_values:
		return 0.0
	n = len(sorted_values)
	# linear interpolation method
	k = (p / 100.0) * (n - 1)
	f = math.floor(k)
	c = math.ceil(k)
	if f == c:
		return sorted_values[int(k)]
	d0 = sorted_values[int(f)] * (c - k)
	d1 = sorted_values[int(c)] * (k - f)
	result = d0 + d1
	return result


#============================================
def analyze_seeds(seeds_data: dict, fps: float) -> dict:
	"""Analyze seeds JSON data. Returns metrics dict.

	Covers plan items 1-6: seed coverage, seeding modes, torso area variability,
	position range, jersey color variability, seed gap analysis.
	"""
	seeds = seeds_data.get("seeds", [])
	total = len(seeds)
	if total == 0:
		return {"total_seeds": 0, "warning": "no seeds found"}

	# -- item 1: seed coverage --
	status_counts = {}
	known_total = 0
	unknown_total = 0
	for s in seeds:
		st = s.get("status", "MISSING")
		status_counts[st] = status_counts.get(st, 0) + 1
		if st in KNOWN_STATUSES:
			known_total += 1
		else:
			unknown_total += 1
	# reconciliation check
	reconciliation_ok = (known_total + unknown_total) == total
	reconciliation_warning = None
	if not reconciliation_ok:
		reconciliation_warning = (
			f"status counts do not reconcile: "
			f"known={known_total} + unknown={unknown_total} != total={total}"
		)
	if unknown_total > 0:
		reconciliation_warning = (
			f"{unknown_total} seeds have unknown/legacy status: "
			+ ", ".join(
				f"{st}={c}" for st, c in sorted(status_counts.items())
				if st not in KNOWN_STATUSES
			)
		)
	# compute frame range
	frames = [s["frame_index"] for s in seeds]
	min_frame = min(frames)
	max_frame = max(frames)
	frame_span = max_frame - min_frame + 1
	duration_s = frame_span / fps if fps > 0 else 0.0
	# density
	seeds_per_minute = (total / duration_s) * 60 if duration_s > 0 else 0.0
	seeds_per_1k_frames = (total / frame_span) * 1000 if frame_span > 0 else 0.0

	# -- item 2: seeding modes --
	mode_counts = {}
	for s in seeds:
		m = s.get("mode", "MISSING")
		mode_counts[m] = mode_counts.get(m, 0) + 1

	# filter to seeds with valid torso_box for spatial analysis
	# visible and partial/approximate seeds all have torso_box
	spatial_seeds = [s for s in seeds if s.get("torso_box") is not None]

	# -- item 3: torso area variability --
	areas = [torso_area(s) for s in spatial_seeds]
	linear_sizes = [torso_linear_size(s) for s in spatial_seeds]
	area_stats = {}
	if areas:
		area_stats = {
			"count": len(areas),
			"min": min(areas),
			"max": max(areas),
			"mean": statistics.mean(areas),
			"median": statistics.median(areas),
			"ratio": max(areas) / min(areas) if min(areas) > 0 else float("inf"),
		}
	# size bin distribution
	bin_counts = {}
	for ls in linear_sizes:
		bl = size_bin_label(ls)
		bin_counts[bl] = bin_counts.get(bl, 0) + 1

	# -- item 4: position range --
	cx_values = [s["cx"] for s in spatial_seeds if "cx" in s]
	cy_values = [s["cy"] for s in spatial_seeds if "cy" in s]
	position_stats = {}
	if cx_values and cy_values:
		position_stats = {
			"cx_min": min(cx_values),
			"cx_max": max(cx_values),
			"cx_range": max(cx_values) - min(cx_values),
			"cx_mean": statistics.mean(cx_values),
			"cy_min": min(cy_values),
			"cy_max": max(cy_values),
			"cy_range": max(cy_values) - min(cy_values),
			"cy_mean": statistics.mean(cy_values),
		}

	# -- item 5: jersey color variability (HSV) --
	# collect HSV values grouped by size bin
	hsv_by_bin = {}
	all_hues = []
	all_sats = []
	all_vals = []
	for s in spatial_seeds:
		hsv = s.get("jersey_hsv")
		if hsv is None or len(hsv) < 3:
			continue
		h, sat, v = hsv[0], hsv[1], hsv[2]
		all_hues.append(h)
		all_sats.append(sat)
		all_vals.append(v)
		ls = torso_linear_size(s)
		bl = size_bin_label(ls)
		if bl not in hsv_by_bin:
			hsv_by_bin[bl] = {"hues": [], "sats": [], "vals": []}
		hsv_by_bin[bl]["hues"].append(h)
		hsv_by_bin[bl]["sats"].append(sat)
		hsv_by_bin[bl]["vals"].append(v)
	hsv_overall = {}
	if all_hues:
		hsv_overall = {
			"hue_mean": statistics.mean(all_hues),
			"hue_std": statistics.stdev(all_hues) if len(all_hues) > 1 else 0.0,
			"hue_range": max(all_hues) - min(all_hues),
			"sat_mean": statistics.mean(all_sats),
			"val_mean": statistics.mean(all_vals),
		}
	hsv_by_size = {}
	for bl, data in hsv_by_bin.items():
		hues = data["hues"]
		hsv_by_size[bl] = {
			"count": len(hues),
			"hue_mean": statistics.mean(hues),
			"hue_std": statistics.stdev(hues) if len(hues) > 1 else 0.0,
			"hue_range": max(hues) - min(hues),
		}

	# -- item 6: seed gap analysis --
	sorted_frames = sorted(set(frames))
	gaps = []
	for i in range(1, len(sorted_frames)):
		gap_frames = sorted_frames[i] - sorted_frames[i - 1]
		gaps.append(gap_frames)
	gap_stats = {}
	if gaps:
		max_gap = max(gaps)
		max_gap_s = max_gap / fps if fps > 0 else 0.0
		# desert regions: gaps > 5 seconds
		desert_threshold = 5.0 * fps
		deserts = [g for g in gaps if g > desert_threshold]
		gap_stats = {
			"max_gap_frames": max_gap,
			"max_gap_s": round(max_gap_s, 2),
			"mean_gap_frames": round(statistics.mean(gaps), 1),
			"desert_count": len(deserts),
		}

	result = {
		"total_seeds": total,
		"known_status_total": known_total,
		"unknown_status_total": unknown_total,
		"reconciliation_warning": reconciliation_warning,
		"status_counts": status_counts,
		"mode_counts": mode_counts,
		"seeds_per_minute": round(seeds_per_minute, 1),
		"seeds_per_1k_frames": round(seeds_per_1k_frames, 1),
		"frame_range": [min_frame, max_frame],
		"frame_span": frame_span,
		"duration_s": round(duration_s, 1),
		"area_stats": area_stats,
		"size_bin_counts": bin_counts,
		"position_stats": position_stats,
		"hsv_overall": hsv_overall,
		"hsv_by_size": hsv_by_size,
		"gap_stats": gap_stats,
	}
	return result


#============================================
def analyze_intervals(intervals_data: dict) -> dict:
	"""Analyze intervals JSON data. Returns metrics dict.

	Covers plan items 7-12: interval statistics, confidence breakdown,
	failure analysis, score distributions, meeting point error, fused track quality.
	"""
	solved = intervals_data.get("solved_intervals", {})
	count = len(solved)
	if count == 0:
		return {"interval_count": 0, "warning": "no solved intervals found"}

	# -- item 7: interval statistics --
	durations = []
	# -- item 8: confidence breakdown --
	conf_counts = {"high": 0, "good": 0, "fair": 0, "low": 0}
	# -- item 9: failure analysis --
	failure_counts = {}
	# -- item 10: score distributions --
	agreement_scores = []
	identity_scores = []
	margins = []
	# -- item 11: meeting point error --
	center_errs = []
	scale_errs = []
	# -- item 12: fused track quality --
	total_fused_points = 0
	merged_count = 0
	propagated_count = 0
	seed_count = 0
	fuse_flag_count = 0

	for key, interval in solved.items():
		# duration
		start = interval.get("start_frame", 0)
		end = interval.get("end_frame", 0)
		dur = end - start
		durations.append(dur)

		# scores
		score = interval.get("interval_score", {})
		conf = score.get("confidence", "unknown")
		if conf in conf_counts:
			conf_counts[conf] += 1
		# failure reasons
		for reason in score.get("failure_reasons", []):
			failure_counts[reason] = failure_counts.get(reason, 0) + 1
		# numeric scores
		if "agreement_score" in score:
			agreement_scores.append(score["agreement_score"])
		if "identity_score" in score:
			identity_scores.append(score["identity_score"])
		if "competitor_margin" in score:
			margins.append(score["competitor_margin"])
		# meeting point error
		for mpe in score.get("meeting_point_error", []):
			if "center_err_px" in mpe:
				center_errs.append(mpe["center_err_px"])
			if "scale_err_pct" in mpe:
				scale_errs.append(mpe["scale_err_pct"])
		# fused track quality
		fused = interval.get("fused_track", [])
		for pt in fused:
			total_fused_points += 1
			src = pt.get("source", "")
			if src == "merged":
				merged_count += 1
			elif src == "propagated":
				propagated_count += 1
			elif src == "seed":
				seed_count += 1
			if pt.get("fuse_flag", False):
				fuse_flag_count += 1

	# build distribution summaries
	durations_sorted = sorted(durations)
	agreement_sorted = sorted(agreement_scores)
	identity_sorted = sorted(identity_scores)
	margins_sorted = sorted(margins)
	center_errs_sorted = sorted(center_errs)
	scale_errs_sorted = sorted(scale_errs)

	result = {
		"interval_count": count,
		"duration_stats": _dist_summary(durations_sorted),
		"confidence_counts": conf_counts,
		"confidence_pcts": {
			k: round(100.0 * v / count, 1) for k, v in conf_counts.items()
		},
		"failure_counts": failure_counts,
		"agreement_dist": _dist_summary(agreement_sorted),
		"identity_dist": _dist_summary(identity_sorted),
		"margin_dist": _dist_summary(margins_sorted),
		"center_err_dist": _dist_summary(center_errs_sorted),
		"scale_err_dist": _dist_summary(scale_errs_sorted),
		"fused_track_quality": {
			"total_points": total_fused_points,
			"merged": merged_count,
			"propagated": propagated_count,
			"seed": seed_count,
			"fuse_flag_count": fuse_flag_count,
			"merged_pct": round(100.0 * merged_count / total_fused_points, 1) if total_fused_points > 0 else 0.0,
			"fuse_flag_pct": round(100.0 * fuse_flag_count / total_fused_points, 1) if total_fused_points > 0 else 0.0,
		},
	}
	return result


#============================================
def _dist_summary(sorted_vals: list) -> dict:
	"""Build a distribution summary dict from sorted values."""
	if not sorted_vals:
		return {}
	summary = {
		"count": len(sorted_vals),
		"min": round(sorted_vals[0], 4),
		"max": round(sorted_vals[-1], 4),
		"mean": round(statistics.mean(sorted_vals), 4),
		"median": round(statistics.median(sorted_vals), 4),
		"p10": round(percentile(sorted_vals, 10), 4),
		"p25": round(percentile(sorted_vals, 25), 4),
		"p75": round(percentile(sorted_vals, 75), 4),
		"p90": round(percentile(sorted_vals, 90), 4),
	}
	return summary


#============================================
def analyze_diagnostics(diag_data: dict) -> dict:
	"""Analyze diagnostics JSON data. Returns metrics dict.

	Covers plan items 13-14: per-frame confidence tier totals,
	failure reason frequencies at per-frame granularity.
	"""
	intervals = diag_data.get("intervals", [])
	if not intervals:
		return {"frame_count": 0, "warning": "no diagnostic intervals found"}

	# -- item 13: confidence tier totals --
	conf_counts = {"high": 0, "medium": 0, "low": 0}
	# -- item 14: failure reason frequencies --
	failure_counts = {}
	total = len(intervals)

	for entry in intervals:
		conf = entry.get("confidence", "unknown")
		if conf in conf_counts:
			conf_counts[conf] += 1
		for reason in entry.get("failure_reasons", []):
			failure_counts[reason] = failure_counts.get(reason, 0) + 1

	# score distributions from diagnostics
	agreement_scores = sorted([
		e["agreement_score"] for e in intervals if "agreement_score" in e
	])
	identity_scores = sorted([
		e["identity_score"] for e in intervals if "identity_score" in e
	])
	margins = sorted([
		e["competitor_margin"] for e in intervals if "competitor_margin" in e
	])

	# cyclical prior if present
	cyclical = diag_data.get("cyclical_prior")

	result = {
		"frame_count": total,
		"confidence_counts": conf_counts,
		"confidence_pcts": {
			k: round(100.0 * v / total, 1) for k, v in conf_counts.items()
		},
		"failure_counts": failure_counts,
		"agreement_dist": _dist_summary(agreement_scores),
		"identity_dist": _dist_summary(identity_scores),
		"margin_dist": _dist_summary(margins),
		"cyclical_prior": cyclical,
	}
	return result


#============================================
def cross_video_summary(all_results: dict) -> dict:
	"""Cross-video normalized comparisons.

	Covers plan items 15-16: size vs confidence, seed density vs low-confidence rate.
	"""
	rows = []
	for video_name, result in all_results.items():
		seed_info = result.get("seeds", {})
		interval_info = result.get("intervals", {})
		if seed_info.get("total_seeds", 0) == 0:
			continue
		if interval_info.get("interval_count", 0) == 0:
			continue
		# median torso area
		median_area = seed_info.get("area_stats", {}).get("median", 0)
		# confidence breakdown from intervals
		conf_pcts = interval_info.get("confidence_pcts", {})
		low_pct = conf_pcts.get("low", 0.0)
		high_pct = conf_pcts.get("high", 0.0)
		# seed density
		seeds_per_min = seed_info.get("seeds_per_minute", 0.0)
		rows.append({
			"video": video_name,
			"median_torso_area": round(median_area, 1),
			"seeds_per_minute": seeds_per_min,
			"high_confidence_pct": high_pct,
			"low_confidence_pct": low_pct,
		})
	result = {"comparison_rows": rows}
	return result


#============================================
def format_report(all_results: dict, cross: dict) -> str:
	"""Format a text report from all results."""
	lines = []
	lines.append("=" * 72)
	lines.append("Track Runner v3 JSON Analysis Report")
	lines.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")
	lines.append(f"Script version: {SCRIPT_VERSION}")
	lines.append("=" * 72)

	for video_name in sorted(all_results.keys()):
		result = all_results[video_name]
		lines.append("")
		lines.append("-" * 72)
		lines.append(f"VIDEO: {video_name}")
		lines.append("-" * 72)

		# --- seeds ---
		seed = result.get("seeds", {})
		if seed.get("total_seeds", 0) == 0:
			lines.append("  No seeds found.")
			continue

		lines.append("")
		lines.append("  SEED COVERAGE")
		lines.append(f"    Total seeds: {seed['total_seeds']}")
		# status breakdown
		for st, ct in sorted(seed.get("status_counts", {}).items()):
			lines.append(f"      {st}: {ct}")
		if seed.get("reconciliation_warning"):
			lines.append(f"    WARNING: {seed['reconciliation_warning']}")
		lines.append(f"    Seeds/minute: {seed['seeds_per_minute']}")
		lines.append(f"    Seeds/1000 frames: {seed['seeds_per_1k_frames']}")
		lines.append(f"    Frame range: {seed['frame_range'][0]} - {seed['frame_range'][1]}")
		lines.append(f"    Duration: {seed['duration_s']}s")

		# modes
		lines.append("")
		lines.append("  SEEDING MODES")
		for m, ct in sorted(seed.get("mode_counts", {}).items(), key=lambda x: -x[1]):
			lines.append(f"    {m}: {ct}")

		# torso area
		area = seed.get("area_stats", {})
		if area:
			lines.append("")
			lines.append("  TORSO AREA VARIABILITY")
			lines.append(f"    Count: {area['count']}")
			lines.append(f"    Min: {area['min']:.0f} px^2")
			lines.append(f"    Max: {area['max']:.0f} px^2")
			lines.append(f"    Mean: {area['mean']:.0f} px^2")
			lines.append(f"    Median: {area['median']:.0f} px^2")
			lines.append(f"    Ratio (max/min): {area['ratio']:.1f}x")
		bins = seed.get("size_bin_counts", {})
		if bins:
			lines.append("    Size bins (linear sqrt(w*h)):")
			for label, lo, hi in SIZE_BINS:
				ct = bins.get(label, 0)
				hi_str = f"{hi:.0f}" if hi != float("inf") else "+"
				lines.append(f"      {label} ({lo}-{hi_str}px): {ct}")

		# position
		pos = seed.get("position_stats", {})
		if pos:
			lines.append("")
			lines.append("  POSITION RANGE")
			lines.append(f"    X range: {pos['cx_min']:.0f} - {pos['cx_max']:.0f} (span {pos['cx_range']:.0f}px)")
			lines.append(f"    Y range: {pos['cy_min']:.0f} - {pos['cy_max']:.0f} (span {pos['cy_range']:.0f}px)")

		# HSV
		hsv = seed.get("hsv_overall", {})
		if hsv:
			lines.append("")
			lines.append("  JERSEY HSV (overall)")
			lines.append(f"    Hue: mean={hsv['hue_mean']:.1f}, std={hsv['hue_std']:.1f}, range={hsv['hue_range']}")
			lines.append(f"    Sat: mean={hsv['sat_mean']:.1f}")
			lines.append(f"    Val: mean={hsv['val_mean']:.1f}")
		hsv_size = seed.get("hsv_by_size", {})
		if hsv_size:
			lines.append("    Hue by size bin:")
			for label, lo, hi in SIZE_BINS:
				if label in hsv_size:
					d = hsv_size[label]
					lines.append(
						f"      {label} (n={d['count']}): "
						f"mean={d['hue_mean']:.1f}, std={d['hue_std']:.1f}, range={d['hue_range']}"
					)

		# gap analysis
		gap = seed.get("gap_stats", {})
		if gap:
			lines.append("")
			lines.append("  SEED GAP ANALYSIS")
			lines.append(f"    Max gap: {gap['max_gap_frames']} frames ({gap['max_gap_s']}s)")
			lines.append(f"    Mean gap: {gap['mean_gap_frames']} frames")
			lines.append(f"    Desert regions (>5s): {gap['desert_count']}")

		# --- intervals ---
		intv = result.get("intervals", {})
		if intv.get("interval_count", 0) > 0:
			lines.append("")
			lines.append("  INTERVAL STATISTICS")
			lines.append(f"    Count: {intv['interval_count']}")
			dur = intv.get("duration_stats", {})
			if dur:
				lines.append(
					f"    Duration (frames): min={dur['min']}, "
					f"max={dur['max']}, mean={dur['mean']}, median={dur['median']}"
				)
			lines.append("")
			lines.append("  CONFIDENCE BREAKDOWN")
			for tier in ["high", "good", "fair", "low"]:
				ct = intv["confidence_counts"].get(tier, 0)
				pct = intv["confidence_pcts"].get(tier, 0.0)
				lines.append(f"    {tier}: {ct} ({pct}%)")
			lines.append("")
			lines.append("  FAILURE REASONS")
			for reason, ct in sorted(intv.get("failure_counts", {}).items(), key=lambda x: -x[1]):
				lines.append(f"    {reason}: {ct}")
			# score distributions
			for score_name in ["agreement", "identity", "margin"]:
				dist = intv.get(f"{score_name}_dist", {})
				if dist:
					lines.append(f"    {score_name}: "
						f"min={dist['min']}, p25={dist['p25']}, "
						f"median={dist['median']}, p75={dist['p75']}, max={dist['max']}")
			# meeting point error
			ce = intv.get("center_err_dist", {})
			if ce:
				lines.append(f"    center_err_px: "
					f"min={ce['min']}, median={ce['median']}, "
					f"p90={ce['p90']}, max={ce['max']}")
			se = intv.get("scale_err_dist", {})
			if se:
				lines.append(f"    scale_err_pct: "
					f"min={se['min']}, median={se['median']}, "
					f"p90={se['p90']}, max={se['max']}")
			# fused quality
			fq = intv.get("fused_track_quality", {})
			if fq:
				lines.append("")
				lines.append("  FUSED TRACK QUALITY")
				lines.append(f"    Total points: {fq['total_points']}")
				lines.append(f"    Merged: {fq['merged']} ({fq['merged_pct']}%)")
				lines.append(f"    Propagated: {fq['propagated']}")
				lines.append(f"    Seed: {fq['seed']}")
				lines.append(f"    Fuse flags: {fq['fuse_flag_count']} ({fq['fuse_flag_pct']}%)")
		else:
			lines.append("")
			lines.append("  No intervals data found.")

		# --- diagnostics ---
		diag = result.get("diagnostics", {})
		if diag.get("frame_count", 0) > 0:
			lines.append("")
			lines.append("  DIAGNOSTICS")
			lines.append(f"    Diagnostic intervals: {diag['frame_count']}")
			lines.append("    Confidence tiers:")
			for tier in ["high", "medium", "low"]:
				ct = diag["confidence_counts"].get(tier, 0)
				pct = diag["confidence_pcts"].get(tier, 0.0)
				lines.append(f"      {tier}: {ct} ({pct}%)")
			if diag.get("failure_counts"):
				lines.append("    Failure reasons:")
				for reason, ct in sorted(diag["failure_counts"].items(), key=lambda x: -x[1]):
					lines.append(f"      {reason}: {ct}")
			cyc = diag.get("cyclical_prior")
			if cyc:
				lines.append(f"    Cyclical prior: period={cyc.get('period_s', '?')}s, "
					f"correlation={cyc.get('correlation', '?')}")
		else:
			lines.append("")
			lines.append("  No diagnostics file found.")

	# --- cross-video summary ---
	lines.append("")
	lines.append("=" * 72)
	lines.append("CROSS-VIDEO COMPARISON")
	lines.append("=" * 72)
	rows = cross.get("comparison_rows", [])
	if rows:
		lines.append("")
		lines.append(f"  {'Video':<35} {'Med.Area':>10} {'Seeds/min':>10} {'High%':>8} {'Low%':>8}")
		lines.append(f"  {'-'*35} {'-'*10} {'-'*10} {'-'*8} {'-'*8}")
		for r in rows:
			lines.append(
				f"  {r['video']:<35} "
				f"{r['median_torso_area']:>10.0f} "
				f"{r['seeds_per_minute']:>10.1f} "
				f"{r['high_confidence_pct']:>7.1f}% "
				f"{r['low_confidence_pct']:>7.1f}%"
			)
	else:
		lines.append("  Not enough data for cross-video comparison.")

	lines.append("")
	report = "\n".join(lines)
	return report


#============================================
def write_csv(all_results: dict, output_dir: str) -> list:
	"""Write per-video CSVs to output_dir. Returns list of written paths."""
	written = []
	for video_name in sorted(all_results.keys()):
		result = all_results[video_name]
		seed = result.get("seeds", {})
		intv = result.get("intervals", {})
		if seed.get("total_seeds", 0) == 0 and intv.get("interval_count", 0) == 0:
			continue

		# write a summary CSV with key metrics
		# sanitize video name for filename
		safe_name = video_name.replace(".", "_").replace(" ", "_")
		csv_path = os.path.join(output_dir, f"track_runner_analysis_{safe_name}.csv")
		rows = []

		# seed metrics
		rows.append(["metric", "value"])
		rows.append(["total_seeds", seed.get("total_seeds", 0)])
		for st, ct in sorted(seed.get("status_counts", {}).items()):
			rows.append([f"status_{st}", ct])
		rows.append(["seeds_per_minute", seed.get("seeds_per_minute", 0)])
		rows.append(["seeds_per_1k_frames", seed.get("seeds_per_1k_frames", 0)])
		area = seed.get("area_stats", {})
		for k in ["min", "max", "mean", "median", "ratio"]:
			if k in area:
				rows.append([f"torso_area_{k}", round(area[k], 2)])
		# interval metrics
		rows.append(["interval_count", intv.get("interval_count", 0)])
		for tier in ["high", "good", "fair", "low"]:
			ct = intv.get("confidence_counts", {}).get(tier, 0)
			rows.append([f"confidence_{tier}", ct])
		for reason, ct in sorted(intv.get("failure_counts", {}).items()):
			rows.append([f"failure_{reason}", ct])

		with open(csv_path, "w", newline="") as f:
			writer = csv.writer(f)
			for row in rows:
				writer.writerow(row)
		written.append(csv_path)
	return written


#============================================
def write_summary_json(all_results: dict, cross: dict, video_paths: dict, output_dir: str) -> str:
	"""Write summary JSON to output_dir. Returns the written path."""
	summary = {
		"script_version": SCRIPT_VERSION,
		"analysis_date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
		"input_files": {},
		"videos": {},
		"cross_video": cross,
	}
	for video_name in sorted(all_results.keys()):
		# record discovered input files
		paths = video_paths.get(video_name, {})
		summary["input_files"][video_name] = {
			"seeds": paths.get("seeds_path"),
			"intervals": paths.get("intervals_path"),
			"diagnostics": paths.get("diagnostics_path"),
		}
		# record per-video summary
		result = all_results[video_name]
		summary["videos"][video_name] = result

	json_path = os.path.join(output_dir, "track_runner_analysis_summary.json")
	with open(json_path, "w") as f:
		json.dump(summary, f, indent=2, default=str)
	return json_path


#============================================
def get_fps_for_video(video_name: str, input_dir: str) -> float:
	"""Get fps for a video from its config YAML, or default to 30.0."""
	config_path = os.path.join(input_dir, video_name + ".track_runner.config.yaml")
	if os.path.isfile(config_path):
		import yaml
		with open(config_path) as f:
			config = yaml.safe_load(f)
		if config and "fps" in config:
			return float(config["fps"])
	# try diagnostics file for fps
	diag_path = os.path.join(input_dir, video_name + ".track_runner.diagnostics.json")
	if os.path.isfile(diag_path):
		with open(diag_path) as f:
			data = json.load(f)
		if "fps" in data:
			return float(data["fps"])
	# default
	return 30.0


#============================================
def main() -> None:
	"""Main entry point."""
	args = parse_args()

	# determine directories
	repo_root = get_repo_root()
	input_dir = args.input_dir
	if input_dir is None:
		input_dir = os.path.join(repo_root, "TRACK_VIDEOS")
	output_dir = args.output_dir
	if output_dir is None:
		output_dir = os.path.join(repo_root, "output_smoke")

	# ensure output directory exists
	os.makedirs(output_dir, exist_ok=True)

	# discover videos
	videos = discover_videos(input_dir)
	if not videos:
		print(f"ERROR: no track runner seeds files found in {input_dir}")
		raise RuntimeError(f"no seeds files in {input_dir}")

	print(f"Discovered {len(videos)} videos with seed data:")
	for name, paths in sorted(videos.items()):
		has_int = "YES" if paths["intervals_path"] else "NO"
		has_diag = "YES" if paths["diagnostics_path"] else "NO"
		print(f"  {name}: intervals={has_int}, diagnostics={has_diag}")
	print()

	# analyze each video
	all_results = {}
	for video_name in sorted(videos.keys()):
		paths = videos[video_name]
		fps = get_fps_for_video(video_name, input_dir)
		print(f"Analyzing {video_name} (fps={fps})...")

		result = {}

		# load and analyze seeds
		seeds_data = load_json_file(paths["seeds_path"])
		result["seeds"] = analyze_seeds(seeds_data, fps)

		# load and analyze intervals
		if paths["intervals_path"]:
			intervals_data = load_json_file(paths["intervals_path"])
			result["intervals"] = analyze_intervals(intervals_data)
		else:
			result["intervals"] = {"interval_count": 0, "warning": "no intervals file found"}

		# load and analyze diagnostics
		if paths["diagnostics_path"]:
			diag_data = load_json_file(paths["diagnostics_path"])
			result["diagnostics"] = analyze_diagnostics(diag_data)
		else:
			result["diagnostics"] = {"frame_count": 0, "warning": "no diagnostics file found"}

		all_results[video_name] = result

	# cross-video summary
	cross = cross_video_summary(all_results)

	# format and print report
	report = format_report(all_results, cross)
	print(report)

	# write output files
	csv_paths = write_csv(all_results, output_dir)
	for p in csv_paths:
		print(f"Wrote CSV: {p}")

	json_path = write_summary_json(all_results, cross, videos, output_dir)
	print(f"Wrote summary JSON: {json_path}")


#============================================
if __name__ == "__main__":
	main()
