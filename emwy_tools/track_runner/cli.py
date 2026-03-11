#!/usr/bin/env python3

"""
cli.py

CLI entry point for the track_runner tool.
Probes video metadata, loads or writes config, and runs the tracking pipeline.
"""

# Standard Library
import argparse
import os
import time

# PIP3 modules
import numpy

# local repo modules
import config
import detection
import encoder
import seeding
import tools_common
import tracker

#============================================

def parse_args() -> argparse.Namespace:
	"""
	Parse command-line arguments.

	Returns:
		argparse.Namespace: Parsed CLI args.
	"""
	parser = argparse.ArgumentParser(
		description="Track runner: detect, track, and crop a subject in video."
	)
	parser.add_argument(
		"-i", "--input", dest="input_file", required=True,
		help="Input media file path."
	)
	parser.add_argument(
		"-o", "--output", dest="output_file", default=None,
		help="Output cropped media file path."
	)
	parser.add_argument(
		"-c", "--config", dest="config_file", default=None,
		help="Optional config YAML path."
	)
	parser.add_argument(
		"--write-default-config", dest="write_default_config",
		action="store_true",
		help="Write the default config file for this input and exit."
	)
	parser.add_argument(
		"--seed-interval", dest="seed_interval", type=float,
		default=None,
		help="Override config seeding.interval_seconds."
	)
	parser.add_argument(
		"--aspect", dest="aspect", type=str, default=None,
		help="Override config crop aspect ratio (e.g. '1:1', '16:9')."
	)
	parser.add_argument(
		"-d", "--debug", dest="debug",
		action="store_true",
		help="Draw tracking bounding box overlay on the output video."
	)
	parser.add_argument(
		"--keep-temp", dest="keep_temp", action="store_true",
		help="Keep temporary files under the cache directory."
	)
	parser.add_argument(
		"--add-seeds", dest="add_seeds", action="store_true",
		help="Open seed UI to add seeds, merge with existing, and re-track."
	)
	parser.add_argument(
		"-w", "--workers", dest="workers", type=int, default=None,
		help="Number of parallel detection workers (default: half of CPU cores)."
	)
	parser.set_defaults(write_default_config=False)
	parser.set_defaults(debug=False)
	parser.set_defaults(keep_temp=False)
	parser.set_defaults(add_seeds=False)
	return parser.parse_args()

#============================================

def _merge_streak_lists(streaks_a: list, streaks_b: list) -> list:
	"""Merge two streak lists, combining overlapping regions.

	Converts (start, length) tuples to intervals, merges overlaps,
	converts back, and sorts by length descending.

	Args:
		streaks_a: List of (start_frame, length) tuples.
		streaks_b: List of (start_frame, length) tuples.

	Returns:
		Merged list of (start_frame, length) tuples, longest first.
	"""
	# convert to (start, end) intervals
	intervals = []
	for start, length in streaks_a:
		intervals.append((start, start + length))
	for start, length in streaks_b:
		intervals.append((start, start + length))
	if not intervals:
		return []
	# sort by start
	intervals.sort(key=lambda x: x[0])
	# merge overlapping intervals
	merged = [intervals[0]]
	for start, end in intervals[1:]:
		prev_start, prev_end = merged[-1]
		if start <= prev_end:
			# overlapping or adjacent, extend
			merged[-1] = (prev_start, max(prev_end, end))
		else:
			merged.append((start, end))
	# convert back to (start, length), sort by length descending
	result = [(s, e - s) for s, e in merged]
	result.sort(key=lambda x: x[1], reverse=True)
	return result


#============================================

def _collect_predictions_for_streaks(
	forward_states: list, backward_states: list, bad_streaks: list,
) -> list:
	"""Collect forward/backward predictions for frames in bad streaks.

	Args:
		forward_states: Per-frame state dicts from forward tracking pass.
		backward_states: Per-frame state dicts from backward tracking pass.
		bad_streaks: List of (start_frame, length) tuples.

	Returns:
		List of prediction dicts with frame_index, forward, and backward keys.
	"""
	# build set of frame indices covered by bad streaks
	bad_frames = set()
	for start, length in bad_streaks:
		for fi in range(start, start + length):
			bad_frames.add(fi)
	predictions = []
	for fi in sorted(bad_frames):
		if fi >= len(forward_states) or fi >= len(backward_states):
			continue
		entry = {"frame_index": fi}
		# forward prediction
		fwd = forward_states[fi]
		if fwd is not None:
			entry["forward"] = {
				"bbox": list(fwd["bbox"]),
				"source": fwd["source"],
				"confidence": round(fwd["confidence"], 4),
			}
		# backward prediction
		bwd = backward_states[fi]
		if bwd is not None:
			entry["backward"] = {
				"bbox": list(bwd["bbox"]),
				"source": bwd["source"],
				"confidence": round(bwd["confidence"], 4),
			}
		predictions.append(entry)
	return predictions


#============================================

def _find_worst_streaks(
	frame_states: list, min_streak: int = 30, max_targets: int = 24,
) -> list:
	"""Find the worst missed-detection streaks as (midpoint, length) tuples.

	Scans frame_states for consecutive predicted-only runs longer
	than min_streak. Returns tuples sorted longest-first, capped at
	max_targets.

	Args:
		frame_states: List of per-frame state dicts from tracker.
		min_streak: Minimum consecutive misses to count as a bad region.
		max_targets: Maximum number of target streaks to return.

	Returns:
		List of (midpoint_frame, streak_length) tuples, longest first.
	"""
	streaks = []
	start = None
	length = 0
	for s in frame_states:
		# count predicted, interpolated, and absent as missed-detection frames
		if s["source"] in ("predicted", "interpolated", "absent"):
			if start is None:
				start = s["frame_index"]
			length += 1
		else:
			if length >= min_streak:
				streaks.append((start, length))
			start = None
			length = 0
	# handle streak at end of video
	if length >= min_streak and start is not None:
		streaks.append((start, length))
	# sort by streak length, longest first
	streaks.sort(key=lambda x: x[1], reverse=True)
	return streaks[:max_targets]


#============================================

def _streaks_to_seed_frames(streaks: list, fps: float) -> list:
	"""Convert bad streaks into seed frame targets.

	For short streaks, places one seed at the midpoint.
	For long streaks, places seeds every ~5 seconds across the
	streak so a single seed does not have to cover too large a gap.

	Args:
		streaks: List of (start_frame, length) tuples from _find_worst_streaks.
		fps: Video frame rate for computing spacing.

	Returns:
		List of (frame_index, parent_streak_length) tuples,
		sorted chronologically.
	"""
	# spacing between seeds within a long streak (~5 seconds)
	seed_spacing = int(round(fps * 5.0))
	if seed_spacing < 1:
		seed_spacing = 1
	targets = []
	for streak_start, streak_len in streaks:
		# how many seeds to place in this streak
		num_seeds = max(1, streak_len // seed_spacing)
		# space them evenly across the streak
		step = streak_len / (num_seeds + 1)
		for i in range(num_seeds):
			frame_idx = int(streak_start + step * (i + 1))
			targets.append((frame_idx, streak_len))
	# sort chronologically
	targets.sort(key=lambda x: x[0])
	return targets


#============================================

def _find_seedless_gaps(
	seeds: list, total_frames: int, fps: float,
	min_gap_seconds: float = 15.0, max_targets: int = 12,
) -> list:
	"""Find large stretches of video with no seeds and place seed targets.

	Identifies gaps between existing seeds that exceed min_gap_seconds,
	then places seed targets every ~5 seconds within those gaps.

	Args:
		seeds: List of seed dicts with frame_index keys.
		total_frames: Total number of frames in the video.
		fps: Video frame rate.
		min_gap_seconds: Minimum gap duration in seconds to qualify.
		max_targets: Maximum number of seed targets to return.

	Returns:
		List of (frame_index, gap_length) tuples sorted chronologically,
		longest gaps prioritized before capping at max_targets.
	"""
	# collect frame indices from visible seeds only (skip absence markers)
	seed_frames = sorted([
		int(s["frame_index"]) for s in seeds
		if s.get("status", "visible") == "visible"
	])
	# add implicit boundaries
	boundaries = [0] + seed_frames + [total_frames]
	# compute gaps between consecutive boundary points
	min_gap_frames = int(min_gap_seconds * fps)
	gaps = []
	for i in range(len(boundaries) - 1):
		gap_start = boundaries[i]
		gap_end = boundaries[i + 1]
		gap_len = gap_end - gap_start
		if gap_len >= min_gap_frames:
			gaps.append((gap_start, gap_end, gap_len))
	# sort by gap length descending for prioritization
	gaps.sort(key=lambda g: g[2], reverse=True)
	# place seed targets within qualifying gaps (~5 sec spacing)
	seed_spacing = int(round(fps * 5.0))
	if seed_spacing < 1:
		seed_spacing = 1
	targets = []
	for gap_start, gap_end, gap_len in gaps:
		num_seeds = max(1, gap_len // seed_spacing)
		step = gap_len / (num_seeds + 1)
		for i in range(num_seeds):
			frame_idx = int(gap_start + step * (i + 1))
			targets.append((frame_idx, gap_len))
	# cap at max_targets (longest gaps already first)
	targets = targets[:max_targets]
	# sort chronologically for output
	targets.sort(key=lambda x: x[0])
	return targets


#============================================

def _find_stall_regions(
	bbox_positions: list, fps: float, frame_width: int,
	min_stall_seconds: float = 3.0, max_targets: int = 12,
	skip_start_seconds: float = 5.0, skip_end_seconds: float = 5.0,
) -> list:
	"""Find regions where the tracked bbox barely moves (possible wrong target).

	Scans bbox center positions for stretches where total displacement
	stays below a threshold, indicating the tracker may have latched
	onto a stationary person.

	Args:
		bbox_positions: List of [frame_idx, cx, cy] from diagnostics.
		fps: Video frame rate.
		frame_width: Width of the video frame for threshold calculation.
		min_stall_seconds: Minimum stall duration in seconds.
		max_targets: Maximum number of stall regions to return.
		skip_start_seconds: Skip this many seconds at the start.
		skip_end_seconds: Skip this many seconds at the end.

	Returns:
		List of (midpoint_frame, stall_length) tuples, sorted longest first,
		capped at max_targets.
	"""
	if not bbox_positions or fps <= 0:
		return []
	# build frame-to-position lookup
	pos_by_frame = {}
	for entry in bbox_positions:
		pos_by_frame[entry[0]] = (entry[1], entry[2])
	if not pos_by_frame:
		return []
	# determine skip boundaries
	all_frames = sorted(pos_by_frame.keys())
	first_frame = all_frames[0]
	last_frame = all_frames[-1]
	skip_start_frame = first_frame + int(skip_start_seconds * fps)
	skip_end_frame = last_frame - int(skip_end_seconds * fps)
	# movement threshold: 2% of frame width
	move_threshold = 0.02 * frame_width
	# sliding window approach: find runs of low movement
	min_stall_frames = int(min_stall_seconds * fps)
	# filter to valid range
	valid_frames = [f for f in all_frames if skip_start_frame <= f <= skip_end_frame]
	if len(valid_frames) < min_stall_frames:
		return []
	stall_regions = []
	window_start = 0
	while window_start < len(valid_frames):
		# try to extend a stall window from this position
		start_cx, start_cy = pos_by_frame[valid_frames[window_start]]
		window_end = window_start + 1
		while window_end < len(valid_frames):
			cx, cy = pos_by_frame[valid_frames[window_end]]
			# check displacement from window start
			dx = abs(cx - start_cx)
			dy = abs(cy - start_cy)
			displacement = (dx * dx + dy * dy) ** 0.5
			if displacement > move_threshold:
				break
			window_end += 1
		# check if the stall window is long enough
		stall_len = valid_frames[min(window_end, len(valid_frames) - 1)] - valid_frames[window_start]
		if stall_len >= min_stall_frames:
			stall_start = valid_frames[window_start]
			stall_regions.append((stall_start, stall_len))
			# skip past this region
			window_start = window_end
		else:
			window_start += 1
	# sort by stall length descending
	stall_regions.sort(key=lambda x: x[1], reverse=True)
	stall_regions = stall_regions[:max_targets]
	# convert to midpoint targets
	targets = []
	for stall_start, stall_len in stall_regions:
		midpoint = stall_start + stall_len // 2
		targets.append((midpoint, stall_len))
	return targets


#============================================

def _find_big_movement_regions(
	bbox_all_frames: list, fps: float, frame_width: int,
	movement_threshold: float = 0.15, min_region_frames: int = 3,
	max_targets: int = 12,
	skip_start_seconds: float = 5.0, skip_end_seconds: float = 5.0,
) -> list:
	"""Find regions with sudden large bbox displacement (possible wrong-person switch).

	Computes per-frame displacement normalized by person height and frame gap.
	Groups nearby flagged frames into regions and returns midpoint targets.

	Args:
		bbox_all_frames: List of [frame_idx, cx, cy, w, h] for all frames.
		fps: Video frame rate.
		frame_width: Width of the video frame (unused, reserved for future normalization).
		movement_threshold: Displacement / person_height threshold per frame gap.
		min_region_frames: Minimum flagged frames to form a region.
		max_targets: Maximum number of target regions to return.
		skip_start_seconds: Skip this many seconds at the start.
		skip_end_seconds: Skip this many seconds at the end.

	Returns:
		List of (midpoint_frame, region_length) tuples sorted by severity,
		capped at max_targets.
	"""
	if len(bbox_all_frames) < 2 or fps <= 0:
		return []
	# determine skip boundaries
	first_frame = bbox_all_frames[0][0]
	last_frame = bbox_all_frames[-1][0]
	skip_start_frame = first_frame + int(skip_start_seconds * fps)
	skip_end_frame = last_frame - int(skip_end_seconds * fps)
	# compute per-frame normalized displacement
	flagged_frames = []
	for i in range(1, len(bbox_all_frames)):
		prev = bbox_all_frames[i - 1]
		curr = bbox_all_frames[i]
		frame_idx = curr[0]
		# skip frames outside valid range
		if frame_idx < skip_start_frame or frame_idx > skip_end_frame:
			continue
		# frame gap between consecutive entries
		frame_gap = curr[0] - prev[0]
		if frame_gap <= 0:
			continue
		# displacement in pixels
		dx = curr[1] - prev[1]
		dy = curr[2] - prev[2]
		displacement = (dx * dx + dy * dy) ** 0.5
		# normalize by person height (average of prev and curr)
		person_h = (prev[4] + curr[4]) / 2.0
		if person_h <= 0:
			continue
		# per-frame normalized displacement
		norm_disp = (displacement / person_h) / frame_gap
		if norm_disp >= movement_threshold:
			flagged_frames.append(frame_idx)
	if not flagged_frames:
		return []
	# group nearby flagged frames into regions
	# frames within fps of each other are grouped together
	group_dist = int(fps)
	regions = []
	region_start = flagged_frames[0]
	region_end = flagged_frames[0]
	region_count = 1
	for fi in flagged_frames[1:]:
		if fi - region_end <= group_dist:
			region_end = fi
			region_count += 1
		else:
			if region_count >= min_region_frames:
				region_len = region_end - region_start + 1
				regions.append((region_start, region_len, region_count))
			region_start = fi
			region_end = fi
			region_count = 1
	# handle last region
	if region_count >= min_region_frames:
		region_len = region_end - region_start + 1
		regions.append((region_start, region_len, region_count))
	# sort by severity (flagged frame count descending)
	regions.sort(key=lambda r: r[2], reverse=True)
	regions = regions[:max_targets]
	# convert to midpoint targets
	targets = []
	for region_start, region_len, _ in regions:
		midpoint = region_start + region_len // 2
		targets.append((midpoint, region_len))
	return targets


#============================================

def _find_area_change_regions(
	bbox_all_frames: list, fps: float,
	area_change_threshold: float = 0.50, min_region_frames: int = 3,
	max_targets: int = 12,
	skip_start_seconds: float = 5.0, skip_end_seconds: float = 5.0,
) -> list:
	"""Find regions with sudden bbox area changes (possible wrong target).

	Computes per-frame area change ratio and flags frames where the
	area changes by more than the threshold.

	Args:
		bbox_all_frames: List of [frame_idx, cx, cy, w, h] for all frames.
		fps: Video frame rate.
		area_change_threshold: Fractional area change threshold per frame gap.
		min_region_frames: Minimum flagged frames to form a region.
		max_targets: Maximum number of target regions to return.
		skip_start_seconds: Skip this many seconds at the start.
		skip_end_seconds: Skip this many seconds at the end.

	Returns:
		List of (midpoint_frame, region_length) tuples sorted by severity,
		capped at max_targets.
	"""
	if len(bbox_all_frames) < 2 or fps <= 0:
		return []
	# determine skip boundaries
	first_frame = bbox_all_frames[0][0]
	last_frame = bbox_all_frames[-1][0]
	skip_start_frame = first_frame + int(skip_start_seconds * fps)
	skip_end_frame = last_frame - int(skip_end_seconds * fps)
	# compute per-frame area change ratio
	flagged_frames = []
	for i in range(1, len(bbox_all_frames)):
		prev = bbox_all_frames[i - 1]
		curr = bbox_all_frames[i]
		frame_idx = curr[0]
		if frame_idx < skip_start_frame or frame_idx > skip_end_frame:
			continue
		frame_gap = curr[0] - prev[0]
		if frame_gap <= 0:
			continue
		# compute areas (w * h)
		area_prev = prev[3] * prev[4]
		area_curr = curr[3] * curr[4]
		if area_prev <= 0:
			continue
		# per-frame area change ratio
		area_change = abs(area_curr - area_prev) / area_prev / frame_gap
		if area_change >= area_change_threshold:
			flagged_frames.append(frame_idx)
	if not flagged_frames:
		return []
	# group nearby flagged frames into regions
	group_dist = int(fps)
	regions = []
	region_start = flagged_frames[0]
	region_end = flagged_frames[0]
	region_count = 1
	for fi in flagged_frames[1:]:
		if fi - region_end <= group_dist:
			region_end = fi
			region_count += 1
		else:
			if region_count >= min_region_frames:
				region_len = region_end - region_start + 1
				regions.append((region_start, region_len, region_count))
			region_start = fi
			region_end = fi
			region_count = 1
	# handle last region
	if region_count >= min_region_frames:
		region_len = region_end - region_start + 1
		regions.append((region_start, region_len, region_count))
	# sort by severity (flagged frame count descending)
	regions.sort(key=lambda r: r[2], reverse=True)
	regions = regions[:max_targets]
	# convert to midpoint targets
	targets = []
	for region_start, region_len, _ in regions:
		midpoint = region_start + region_len // 2
		targets.append((midpoint, region_len))
	return targets


#============================================

def _generate_interval_targets(
	seeds: list, total_frames: int, fps: float,
	interval_seconds: float,
) -> list:
	"""Generate seed targets at regular intervals, skipping near existing seeds.

	Args:
		seeds: List of existing seed dicts with 'frame_index' and 'status'.
		total_frames: Total number of frames in the video.
		fps: Video frame rate.
		interval_seconds: Seconds between interval targets.

	Returns:
		List of (frame_index, interval_length) tuples.
	"""
	# compute frame interval from seconds
	frame_interval = int(round(fps * interval_seconds))
	if frame_interval < 1:
		return []
	# build set of existing visible seed frame indices
	existing_frames = set()
	for seed in seeds:
		if seed.get("status", "visible") == "visible":
			existing_frames.add(seed["frame_index"])
	# dedup distance: skip targets within 2*fps frames of an existing seed
	dedup_dist = int(2 * fps)
	targets = []
	for fi in range(0, total_frames, frame_interval):
		# check if any existing seed is too close
		too_close = False
		for ef in existing_frames:
			if abs(fi - ef) < dedup_dist:
				too_close = True
				break
		if not too_close:
			targets.append((fi, frame_interval))
	return targets


#============================================

def _tracking_quality_grade(
	detect_pct: float, max_streak: int, fps: float,
	jerk_count: int = 0,
) -> str:
	"""Return a letter grade for tracking quality.

	Args:
		detect_pct: Percentage of frames with a detection match.
		max_streak: Longest consecutive missed-detection run in frames.
		fps: Video frame rate for converting streak to seconds.
		jerk_count: Number of jerk regions detected (wrong-person switches).

	Returns:
		Grade string like "A", "B", "C", "D", or "F".
	"""
	# convert max streak to seconds of drift
	max_streak_sec = max_streak / fps if fps > 0 else max_streak
	# grade based on detection rate and worst drift
	if detect_pct >= 85.0 and max_streak_sec < 2.0:
		grade = "A"
	elif detect_pct >= 70.0 and max_streak_sec < 5.0:
		grade = "B"
	elif detect_pct >= 50.0 and max_streak_sec < 10.0:
		grade = "C"
	elif detect_pct >= 30.0 and max_streak_sec < 20.0:
		grade = "D"
	else:
		grade = "F"
	# downgrade by one letter if jerk regions exist
	# (wrong-person tracking is serious even with high detection rate)
	if jerk_count > 0 and grade != "F":
		grade_order = ["A", "B", "C", "D", "F"]
		idx = grade_order.index(grade)
		grade = grade_order[min(idx + 1, len(grade_order) - 1)]
	return grade


#============================================

def _print_quality_report(
	detected_count: int, predicted_count: int, lost_count: int,
	max_streak: int, detect_pct: float,
	bad_streaks: list, fps: float, seed_count: int,
	crop_width: int, crop_height: int, total_frames: int,
	output_path: str, detect_interval: int = 1,
	prev_diag: dict | None = None,
	interpolated_count: int = 0,
	absent_count: int = 0,
	jerk_count: int = 0,
) -> None:
	"""Print a quality-focused tracking summary.

	Args:
		detected_count: Frames with a detection match.
		predicted_count: Frames using Kalman prediction only.
		lost_count: Frames marked lost.
		max_streak: Longest consecutive missed run.
		detect_pct: Detection percentage.
		bad_streaks: List of (start_frame, length) tuples for bad regions.
		fps: Video frame rate.
		seed_count: Number of seeds used.
		crop_width: Output crop width.
		crop_height: Output crop height.
		total_frames: Total frame count.
		output_path: Path to the output file.
		detect_interval: Detection runs every N frames.
		prev_diag: Previous tracking_diagnostics dict for comparison.
		interpolated_count: Frames smoothed by gap interpolation.
		absent_count: Frames marked as absent.
		jerk_count: Number of jerk regions detected.
	"""
	grade = _tracking_quality_grade(detect_pct, max_streak, fps, jerk_count=jerk_count)
	max_streak_sec = max_streak / fps if fps > 0 else 0
	# compute detection hit rate: of frames where detection ran,
	# how many got a match
	detect_attempts = total_frames // detect_interval if detect_interval > 0 else total_frames
	hit_rate = 100.0 * detected_count / detect_attempts if detect_attempts > 0 else 0.0
	print("")
	print(f"output: {output_path}")
	print(f"  quality:       {grade}")
	print(f"  frames:        {total_frames}")
	print(f"  detected:      {detected_count}/{detect_attempts} attempts ({hit_rate:.0f}% hit rate)")
	if interpolated_count > 0:
		interp_pct = 100.0 * interpolated_count / total_frames
		print(f"  interpolated:  {interpolated_count} ({interp_pct:.0f}% smoothed)")
	print(f"  predicted:     {predicted_count}")
	if absent_count > 0:
		absent_pct = 100.0 * absent_count / total_frames
		print(f"  absent:        {absent_count} ({absent_pct:.0f}% marked absent)")
	if lost_count > 0:
		print(f"  lost:          {lost_count}")
	if jerk_count > 0:
		print(f"  jerk regions:  {jerk_count} (possible wrong-person switches)")
	print(f"  max streak:    {max_streak} frames ({max_streak_sec:.1f}s)")
	print(f"  seeds used:    {seed_count}")
	print(f"  crop size:     {crop_width}x{crop_height}")
	# show before/after comparison when re-seeding
	if prev_diag:
		prev_pct = prev_diag.get("detect_pct", 0)
		prev_streak = prev_diag.get("max_streak", 0)
		prev_streak_sec = prev_streak / fps if fps > 0 else 0
		prev_regions = len(prev_diag.get("bad_streaks", []))
		print("")
		print("  before/after comparison:")
		# detection rate change
		pct_delta = detect_pct - prev_pct
		pct_arrow = "+" if pct_delta >= 0 else ""
		print(f"    detection:  {prev_pct:.1f}% -> {detect_pct:.1f}% ({pct_arrow}{pct_delta:.1f}%)")
		# max streak change
		print(f"    max streak: {prev_streak} ({prev_streak_sec:.1f}s) -> {max_streak} ({max_streak_sec:.1f}s)")
		# problem region count change
		print(f"    problems:   {prev_regions} -> {len(bad_streaks)}")
	# show problem regions sorted chronologically
	if bad_streaks:
		print("")
		# sort by start frame for readability
		sorted_streaks = sorted(bad_streaks, key=lambda s: s[0])
		print(f"  problem regions ({len(sorted_streaks)}):")
		for start_frame, streak_len in sorted_streaks:
			time_str = f"{start_frame / fps:.1f}s"
			dur_str = f"{streak_len / fps:.1f}s"
			# how many seeds --add-seeds would place in this streak
			seed_spacing = int(round(fps * 5.0))
			num_seeds = max(1, streak_len // seed_spacing)
			print(f"    {time_str} -- {streak_len} frames ({dur_str} of drift, {num_seeds} seed(s) needed)")
	# quality verdict and next steps
	print("")
	if grade in ("A", "B"):
		print("  tracking quality is good")
	elif grade == "C":
		print("  tracking quality is fair -- adding seeds at problem regions will help")
		print("  run with --add-seeds to improve")
	else:
		print("  tracking quality is poor -- additional seeds needed")
		print(f"  run with --add-seeds to target the {len(bad_streaks)} problem region(s)")
		if seed_count < 5:
			print("  consider also reducing --seed-interval for more initial seeds")


#============================================

def _merge_seeds(existing: list, new_seeds: list) -> list:
	"""Merge new seeds into existing seeds, sorted by frame_index.

	If a new seed has the same frame_index as an existing one,
	the new seed replaces the existing one.

	Args:
		existing: List of existing seed dicts.
		new_seeds: List of new seed dicts to merge in.

	Returns:
		Merged list of seed dicts sorted by frame_index.
	"""
	# build lookup from existing seeds
	by_frame = {}
	for seed in existing:
		fi = int(seed["frame_index"])
		by_frame[fi] = seed
	# new seeds overwrite at same frame_index
	for seed in new_seeds:
		fi = int(seed["frame_index"])
		by_frame[fi] = seed
	# sort by frame index
	merged = sorted(by_frame.values(), key=lambda s: int(s["frame_index"]))
	return merged


#============================================

def _sanitize_seeds_for_yaml(seeds: list) -> list:
	"""Convert seed dicts to plain Python types for safe YAML serialization.

	Strips numpy arrays (like color_histogram) and converts numpy
	scalars to native Python ints/floats so yaml.safe_load can
	read the file back.

	Args:
		seeds: List of seed dicts from seeding module.

	Returns:
		List of seed dicts with only YAML-safe types.
	"""
	clean_seeds = []
	for seed in seeds:
		clean = {}
		for key, val in seed.items():
			# skip numpy arrays entirely (color_histogram)
			if isinstance(val, numpy.ndarray):
				continue
			# convert numpy scalars to native Python types
			if isinstance(val, (numpy.integer,)):
				clean[key] = int(val)
			elif isinstance(val, (numpy.floating,)):
				clean[key] = float(val)
			# convert lists/tuples that may contain numpy types
			elif isinstance(val, (list, tuple)):
				clean[key] = [
					int(v) if isinstance(v, numpy.integer)
					else float(v) if isinstance(v, numpy.floating)
					else v
					for v in val
				]
			else:
				clean[key] = val
		clean_seeds.append(clean)
	return clean_seeds

#============================================

def main() -> None:
	"""
	Main entry point for the track_runner CLI.
	"""
	t_total_start = time.time()
	args = parse_args()

	# resolve worker count
	if args.workers is not None:
		num_workers = max(1, args.workers)
	else:
		num_workers = max(1, (os.cpu_count() or 2) // 2)

	# validate input file
	tools_common.ensure_file_exists(args.input_file)

	# check required external dependencies
	tools_common.check_dependency("ffprobe")
	tools_common.check_dependency("ffmpeg")

	# resolve config path
	config_path = args.config_file
	if config_path is None:
		config_path = config.default_config_path(args.input_file)

	# compute seeds and diagnostics file paths from input file
	seeds_path = config.default_seeds_path(args.input_file)
	diagnostics_path = config.default_diagnostics_path(args.input_file)

	# handle --write-default-config: write and exit
	if args.write_default_config:
		cfg = config.default_config()
		config.write_config(config_path, cfg)
		print(f"wrote default config: {config_path}")
		return

	# load or create config
	if args.config_file is not None:
		# explicit config path supplied
		cfg = config.load_config(config_path)
	elif os.path.isfile(config_path):
		# default path exists, load it
		cfg = config.load_config(config_path)
	else:
		# no config file found, write defaults and use them
		cfg = config.default_config()
		config.write_config(config_path, cfg)
		print(f"wrote default config: {config_path}")

	# validate the loaded config
	config.validate_config(cfg)

	# apply CLI overrides into the config
	if args.seed_interval is not None:
		cfg.setdefault("settings", {})
		cfg["settings"].setdefault("seeding", {})
		cfg["settings"]["seeding"]["interval_seconds"] = (
			args.seed_interval
		)
	if args.aspect is not None:
		cfg.setdefault("settings", {})
		cfg["settings"].setdefault("crop", {})
		cfg["settings"]["crop"]["aspect"] = args.aspect
	# probe video metadata
	print(f"probing video: {args.input_file}")
	video_info = tools_common.probe_video_stream(args.input_file)
	duration = tools_common.probe_duration_seconds(args.input_file)

	# display probe results
	print(f"  resolution: {video_info['width']}x{video_info['height']}")
	print(f"  fps:        {video_info['fps']:.4f} ({video_info['fps_fraction']})")
	print(f"  pix_fmt:    {video_info['pix_fmt']}")
	print(f"  duration:   {duration:.2f}s")

	# create YOLO detector
	print("initializing YOLO detector...")
	det = detection.create_detector(cfg)

	# collect seeds (interactive UI or from saved config)
	seeding_cfg = cfg.get("settings", {}).get("seeding", {})
	interval_sec = float(seeding_cfg.get("interval_seconds", 30.0))
	min_seeds = int(seeding_cfg.get("min_seeds", 1))
	# load pre-saved seeds from separate seeds file
	saved_seeds = config.load_seeds(seeds_path)
	# load previous diagnostics for before/after comparison
	prev_diag = config.load_diagnostics(diagnostics_path) or None
	if args.add_seeds:
		# --add-seeds: read saved diagnostics from previous render,
		# find problem regions, seedless gaps, and stall regions,
		# open seed UI at those frames, merge, and re-track
		if not saved_seeds:
			raise RuntimeError(
				"--add-seeds requires existing seeds in config; "
				"run without --add-seeds first"
			)
		diag = config.load_diagnostics(diagnostics_path)
		fps = video_info["fps"]
		total_frames = int(duration * fps)
		# source 1: problem-region streak targets
		saved_streaks = diag.get("bad_streaks", [])
		streak_tuples = [(s[0], s[1]) for s in saved_streaks]
		streak_targets = _streaks_to_seed_frames(streak_tuples, fps)
		# source 2: seedless gap targets
		gap_targets = _find_seedless_gaps(saved_seeds, total_frames, fps)
		# source 3: stall region targets
		bbox_positions = diag.get("bbox_positions", [])
		stall_targets = _find_stall_regions(
			bbox_positions, fps, video_info["width"],
		)
		# source 4: big movement region targets (possible wrong-person switches)
		bbox_all_frames = diag.get("bbox_all_frames", [])
		movement_targets = _find_big_movement_regions(
			bbox_all_frames, fps, video_info["width"],
		)
		# source 5: area change region targets (sudden size shifts)
		area_targets = _find_area_change_regions(
			bbox_all_frames, fps,
		)
		# source 6: regular interval targets (when --seed-interval is provided)
		if args.seed_interval is not None:
			interval_targets = _generate_interval_targets(
				saved_seeds, total_frames, fps, args.seed_interval,
			)
		else:
			interval_targets = []
		# bail only if all six sources are empty
		all_empty = (
			not streak_targets and not gap_targets and not stall_targets
			and not movement_targets and not area_targets
			and not interval_targets
		)
		if all_empty:
			print("no problem regions, seedless gaps, stall, movement, area change, or interval targets found")
			print("tracking looks good -- no additional seeds needed")
			return
		# merge all target sources into one combined list
		all_targets = []
		for fi, parent_len in streak_targets:
			all_targets.append((fi, parent_len, "problem"))
		for fi, gap_len in gap_targets:
			all_targets.append((fi, gap_len, "gap"))
		for fi, stall_len in stall_targets:
			all_targets.append((fi, stall_len, "stall"))
		for fi, move_len in movement_targets:
			all_targets.append((fi, move_len, "movement"))
		for fi, area_len in area_targets:
			all_targets.append((fi, area_len, "area_change"))
		for fi, ivl_len in interval_targets:
			all_targets.append((fi, ivl_len, "interval"))
		# sort chronologically
		all_targets.sort(key=lambda x: x[0])
		# deduplicate: skip any target within 2*fps frames of a prior target
		dedup_dist = int(2 * fps)
		deduped = []
		for target in all_targets:
			if deduped and abs(target[0] - deduped[-1][0]) < dedup_dist:
				continue
			deduped.append(target)
		all_targets = deduped
		target_frames = [t[0] for t in all_targets]
		# show the user what we found
		print(f"existing seeds: {len(saved_seeds)}")
		n_problem = sum(1 for t in all_targets if t[2] == "problem")
		n_gap = sum(1 for t in all_targets if t[2] == "gap")
		n_stall = sum(1 for t in all_targets if t[2] == "stall")
		n_movement = sum(1 for t in all_targets if t[2] == "movement")
		n_area = sum(1 for t in all_targets if t[2] == "area_change")
		n_interval = sum(1 for t in all_targets if t[2] == "interval")
		print(f"seed targets: {len(target_frames)} frames to review")
		print(f"  {n_problem} problem-region, {n_gap} gap, {n_stall} stall, {n_movement} movement, {n_area} area-change, {n_interval} interval")
		for fi, region_len, source in all_targets:
			time_str = f"{fi / fps:.1f}s"
			dur_str = f"{region_len / fps:.1f}s"
			print(f"  frame {fi} ({time_str}) -- {source} ({dur_str})")
		# build predictions lookup for overlay display
		saved_predictions = diag.get("predictions", [])
		predictions_by_frame = {}
		for pred in saved_predictions:
			predictions_by_frame[pred["frame_index"]] = pred
		# launch seed UI at the target frames
		print("launching seed UI at target regions...")
		new_seeds = seeding.collect_seeds_at_frames(
			args.input_file, target_frames, cfg, detector=det,
			predictions=predictions_by_frame,
		)
		if not new_seeds:
			print("no new seeds added")
			return
		# merge new seeds with existing
		seeds = _merge_seeds(saved_seeds, new_seeds)
		print(f"merged seeds: {len(seeds)} total")
	elif saved_seeds:
		print(f"using {len(saved_seeds)} saved seeds from config")
		seeds = seeding.collect_seeds(
			args.input_file, interval_sec, cfg,
			detector=det, pre_provided_seeds=saved_seeds,
		)
	else:
		print("launching seed selection UI...")
		seeds = seeding.collect_seeds(
			args.input_file, interval_sec, cfg, detector=det,
		)

	# validate minimum seed count (only visible seeds count)
	visible_seeds = [
		s for s in seeds if s.get("status", "visible") == "visible"
	]
	if len(visible_seeds) < min_seeds:
		raise RuntimeError(
			f"need at least {min_seeds} visible seed(s), "
			f"got {len(visible_seeds)} ({len(seeds)} total including absence markers)"
		)

	# save seeds to separate seeds file
	# strip numpy arrays so yaml.safe_load can read the file back
	clean_seeds = _sanitize_seeds_for_yaml(seeds)
	config.write_seeds(seeds_path, clean_seeds)
	print(f"saved {len(seeds)} seeds to {seeds_path}")

	# build video_info dict for tracker
	reader_info = {
		"width": video_info["width"],
		"height": video_info["height"],
		"fps": video_info["fps"],
		"frame_count": int(duration * video_info["fps"]),
	}

	# run the tracking loop
	print(f"running tracker ({num_workers} workers)...")
	t_track_start = time.time()
	crop_rects, frame_states, forward_states, backward_states = tracker.run_tracker(
		args.input_file, seeds, cfg, det, reader_info, duration,
		num_workers=num_workers,
	)
	t_track_elapsed = time.time() - t_track_start
	print(f"  tracked {len(crop_rects)} frames ({t_track_elapsed:.1f}s)")

	# count frame sources for summary
	detected_count = sum(1 for s in frame_states if s["source"] == "detected")
	predicted_count = sum(1 for s in frame_states if s["source"] == "predicted")
	interpolated_count = sum(1 for s in frame_states if s["source"] == "interpolated")
	lost_count = sum(1 for s in frame_states if s["source"] == "lost")
	absent_count = sum(1 for s in frame_states if s["source"] == "absent")

	# compute additional diagnostics
	total_count = len(frame_states)
	detect_pct = 100.0 * detected_count / total_count if total_count > 0 else 0.0
	# find max consecutive missed streak (predicted only, not interpolated)
	max_streak = 0
	cur_streak = 0
	for s in frame_states:
		if s["source"] == "predicted":
			cur_streak += 1
			if cur_streak > max_streak:
				max_streak = cur_streak
		else:
			cur_streak = 0

	# resolve output path
	if args.output_file is not None:
		output_path = args.output_file
	else:
		stem, ext = os.path.splitext(args.input_file)
		output_path = f"{stem}_tracked{ext}"

	# compute crop output dimensions from first crop rect
	first_crop = crop_rects[0]
	crop_width = first_crop[2]
	crop_height = first_crop[3]
	# ensure even dimensions for codec compatibility
	crop_width = crop_width - (crop_width % 2)
	crop_height = crop_height - (crop_height % 2)

	# read output codec settings from config
	output_cfg = cfg.get("settings", {}).get("output", {})
	video_codec = output_cfg.get("video_codec", "libx264")
	crf_value = int(output_cfg.get("crf", 18))

	# encode video output
	temp_video = output_path + ".tmp.mp4"
	if args.debug:
		print(f"encoding cropped video with debug overlay: {crop_width}x{crop_height}")
	else:
		print(f"encoding cropped video: {crop_width}x{crop_height}")
	t_encode_start = time.time()
	with encoder.VideoReader(args.input_file) as reader:
		encoder.encode_cropped_video(
			reader, crop_rects, temp_video,
			crop_width, crop_height,
			codec=video_codec, crf=crf_value,
			frame_states=frame_states, debug=args.debug,
		)
	t_encode_elapsed = time.time() - t_encode_start
	print(f"  encode complete ({t_encode_elapsed:.1f}s)")

	# mux audio from original into final output
	print("muxing audio...")
	t_mux_start = time.time()
	encoder.copy_audio(args.input_file, temp_video, output_path)
	t_mux_elapsed = time.time() - t_mux_start
	print(f"  mux complete ({t_mux_elapsed:.1f}s)")

	# clean up temp file
	if os.path.isfile(temp_video) and os.path.isfile(output_path):
		os.remove(temp_video)

	# analyze streaks and jerk regions, then merge for --add-seeds
	bad_streaks = _find_worst_streaks(frame_states)
	jerk_regions = tracker.find_jerk_regions(frame_states, cfg)
	if jerk_regions:
		print(f"  jerk detection: {len(jerk_regions)} region(s) with sudden bbox jumps")
	# merge prediction-gap streaks with jerk regions
	all_bad_streaks = _merge_streak_lists(bad_streaks, jerk_regions)
	# collect per-frame predictions for bad streak frames
	pred_data = _collect_predictions_for_streaks(
		forward_states, backward_states, all_bad_streaks,
	)
	# write diagnostics to separate diagnostics file
	# NOTE: bbox_positions uses s["bbox"][0] + s["bbox"][2] / 2 on already-centered
	# bbox (cx, cy, w, h), so the "center" is actually cx + w/2. This is wrong but
	# _find_stall_regions uses relative displacement so the offset cancels out.
	diag_data = {
		"bad_streaks": [[start, length] for start, length in all_bad_streaks],
		"jerk_regions": [[start, length] for start, length in jerk_regions],
		"predictions": pred_data,
		"max_streak": max_streak,
		"detected_count": detected_count,
		"predicted_count": predicted_count,
		"interpolated_count": interpolated_count,
		"absent_count": absent_count,
		"detect_pct": round(detect_pct, 1),
		"bbox_positions": [
			[s["frame_index"], int(s["bbox"][0] + s["bbox"][2] / 2), int(s["bbox"][1] + s["bbox"][3] / 2)]
			for s in frame_states
			if s["source"] == "detected" and s.get("bbox")
		],
		# full bbox data for all frames (movement and area change detection)
		"bbox_all_frames": [
			[s["frame_index"], float(s["bbox"][0]), float(s["bbox"][1]), float(s["bbox"][2]), float(s["bbox"][3])]
			for s in frame_states
			if s.get("bbox")
		],
	}
	config.write_diagnostics(diagnostics_path, diag_data)

	# print quality report with before/after when re-seeding
	compare_diag = prev_diag if args.add_seeds else None
	detect_cfg = cfg.get("settings", {}).get("detection", {})
	detect_interval = int(detect_cfg.get("detect_interval", 5))
	_print_quality_report(
		detected_count, predicted_count, lost_count,
		max_streak, detect_pct,
		all_bad_streaks, video_info["fps"], len(seeds),
		crop_width, crop_height, total_count,
		output_path, detect_interval=detect_interval,
		prev_diag=compare_diag,
		interpolated_count=interpolated_count,
		absent_count=absent_count,
		jerk_count=len(jerk_regions),
	)

	# print total wall-clock time
	t_total_elapsed = time.time() - t_total_start
	print(f"\ntotal time: {t_total_elapsed:.1f}s")

#============================================

if __name__ == "__main__":
	main()
