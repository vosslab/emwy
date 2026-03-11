#!/usr/bin/env python3
"""Measure real-world seed variability for track_runner.

Loads seed and diagnostics YAML files and prints a comprehensive variability
report covering size, position, color, cyclical patterns, and tracker accuracy.
"""

# Standard Library
import os
import sys
import csv
import math
import glob
import argparse
import statistics

# PIP3 modules
import yaml

# local repo modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests'))
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

# video resolution for the Track_Test videos (1280x720)
# used for normalizing bbox areas as fraction of frame
DEFAULT_FRAME_WIDTH = 1280
DEFAULT_FRAME_HEIGHT = 720
DEFAULT_FPS = 30.0


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments."""
	parser = argparse.ArgumentParser(
		description="Measure seed variability for track_runner videos"
	)
	parser.add_argument(
		'-i', '--input', dest='input_files', nargs='+',
		help="Seed YAML file path(s). Defaults to all in TRACK_VIDEOS/"
	)
	parser.add_argument(
		'-f', '--fps', dest='fps', type=float, default=DEFAULT_FPS,
		help="Video frame rate (default: 30.0)"
	)
	parser.add_argument(
		'-c', '--csv', dest='csv_dir',
		default=os.path.join(REPO_ROOT, "output_smoke"),
		help="Output directory for CSV files (default: output_smoke/)"
	)
	parser.add_argument(
		'-C', '--no-csv', dest='write_csv', action='store_false',
		help="Disable CSV output"
	)
	parser.set_defaults(write_csv=True)
	args = parser.parse_args()
	return args


#============================================
def load_yaml_file(filepath: str) -> dict:
	"""Load a YAML file and return its contents."""
	with open(filepath, 'r') as f:
		data = yaml.safe_load(f)
	return data


#============================================
def find_seed_files() -> list:
	"""Find all seed YAML files in TRACK_VIDEOS/."""
	pattern = os.path.join(REPO_ROOT, "TRACK_VIDEOS", "*.track_runner.seeds.yaml")
	files = sorted(glob.glob(pattern))
	return files


#============================================
def diagnostics_path_for_seeds(seed_path: str) -> str:
	"""Derive diagnostics file path from seed file path."""
	# seeds: foo.mov.track_runner.seeds.yaml
	# diag:  foo.mov.track_runner.diagnostics.yaml
	diag_path = seed_path.replace(".seeds.yaml", ".diagnostics.yaml")
	return diag_path


#============================================
def split_seeds(seeds: list) -> tuple:
	"""Split seed list into visible and absent entries.

	Returns:
		(visible_seeds, absent_seeds) where visible have torso_box
		and absent have status field.
	"""
	visible = []
	absent = []
	for s in seeds:
		if 'status' in s:
			absent.append(s)
		else:
			visible.append(s)
	return visible, absent


#============================================
def print_section(title: str) -> None:
	"""Print a formatted section header."""
	print(f"\n{'=' * 60}")
	print(f"  {title}")
	print(f"{'=' * 60}")


#============================================
def print_subsection(title: str) -> None:
	"""Print a formatted subsection header."""
	print(f"\n--- {title} ---")


#============================================
def fmt_stats(values: list, label: str, fmt: str = ".1f") -> None:
	"""Print min/max/mean/median/std for a list of values."""
	if not values:
		print(f"  {label}: no data")
		return
	mn = min(values)
	mx = max(values)
	mean = statistics.mean(values)
	med = statistics.median(values)
	std = statistics.stdev(values) if len(values) > 1 else 0.0
	print(f"  {label}:")
	print(f"    min={mn:{fmt}}  max={mx:{fmt}}  mean={mean:{fmt}}  median={med:{fmt}}  std={std:{fmt}}")


#============================================
def measure_seed_coverage(seeds: list, visible: list, absent: list,
		diagnostics: dict, fps: float) -> None:
	"""Metric 1: Seed coverage statistics."""
	print_subsection("1. Seed Coverage")

	total_seeds = len(seeds)
	visible_count = len(visible)
	absent_count = len(absent)
	print(f"  Visible seeds: {visible_count}")
	print(f"  Absence markers: {absent_count}")
	print(f"  Total seeds: {total_seeds}")

	# total frames from diagnostics
	if diagnostics:
		det = diagnostics.get('detected_count', 0)
		pred = diagnostics.get('predicted_count', 0)
		interp = diagnostics.get('interpolated_count', 0)
		diag_absent = diagnostics.get('absent_count', 0)
		total_frames = det + pred + interp + diag_absent
		print(f"  Total frames (from diagnostics): {total_frames}")
		print(f"    detected={det}  predicted={pred}  interpolated={interp}  absent={diag_absent}")
		if total_frames > 0:
			density = 100.0 * total_seeds / total_frames
			print(f"  Seed density: {density:.1f}% of total frames")
	else:
		# estimate from seed frame range
		if seeds:
			frame_indices = [s['frame_index'] for s in seeds]
			total_frames = max(frame_indices) - min(frame_indices) + 1
			print(f"  Estimated frame range: {total_frames} frames")
		else:
			total_frames = 0

	# largest gap between consecutive seeds
	if len(seeds) >= 2:
		frame_indices = sorted(s['frame_index'] for s in seeds)
		gaps = []
		for i in range(1, len(frame_indices)):
			gap = frame_indices[i] - frame_indices[i - 1]
			gaps.append(gap)
		max_gap = max(gaps)
		max_gap_sec = max_gap / fps
		print(f"  Largest gap between seeds: {max_gap} frames ({max_gap_sec:.1f}s)")

		# count desert regions (gaps > 5 seconds)
		desert_threshold = int(5.0 * fps)
		deserts = [g for g in gaps if g > desert_threshold]
		print(f"  Desert regions (>{5.0:.0f}s gaps): {len(deserts)}")
		if deserts:
			desert_secs = [g / fps for g in sorted(deserts, reverse=True)]
			# show top 5 largest deserts
			top = desert_secs[:5]
			top_str = ", ".join(f"{d:.1f}s" for d in top)
			print(f"    Largest deserts: {top_str}")


#============================================
def measure_start_line(visible: list, fps: float) -> None:
	"""Metric 2: Start line static measurement."""
	print_subsection("2. Start Line Static Phase")

	if len(visible) < 3:
		print("  Not enough visible seeds for start line analysis")
		return

	# get initial position
	first = visible[0]
	start_x = first['torso_box'][0] + first['torso_box'][2] / 2.0
	start_y = first['torso_box'][1] + first['torso_box'][3] / 2.0
	start_h = first['torso_box'][3]

	# threshold: 2x torso height from starting position
	threshold = 2.0 * start_h

	# scan seeds to find when cumulative displacement exceeds threshold
	static_end_idx = 0
	for i, s in enumerate(visible):
		cx = s['torso_box'][0] + s['torso_box'][2] / 2.0
		cy = s['torso_box'][1] + s['torso_box'][3] / 2.0
		dist = math.sqrt((cx - start_x) ** 2 + (cy - start_y) ** 2)
		if dist > threshold:
			static_end_idx = i
			break
	else:
		# never exceeded threshold, entire sequence is static
		static_end_idx = len(visible)

	if static_end_idx < 2:
		# check if first seed gap is large (sparse seeding during static phase)
		if len(visible) >= 2:
			gap_frames = visible[1]['frame_index'] - visible[0]['frame_index']
			gap_sec = gap_frames / fps
			print("  Static phase too short to analyze (< 2 seeds)")
			print(f"  Note: gap to second seed is {gap_frames} frames ({gap_sec:.1f}s)")
			print("  Consider adding more seeds during the start-line phase")
		else:
			print("  Static phase too short to analyze (< 2 seeds)")
		return

	static_seeds = visible[:static_end_idx]
	duration_frames = static_seeds[-1]['frame_index'] - static_seeds[0]['frame_index']
	duration_sec = duration_frames / fps

	print(f"  Static phase duration: {duration_sec:.1f}s ({duration_frames} frames, {len(static_seeds)} seeds)")

	# measure torso area, position, and HSV during static phase
	areas = [s['torso_box'][2] * s['torso_box'][3] for s in static_seeds]
	cx_vals = [s['torso_box'][0] + s['torso_box'][2] / 2.0 for s in static_seeds]
	cy_vals = [s['torso_box'][1] + s['torso_box'][3] / 2.0 for s in static_seeds]

	fmt_stats(areas, "Torso area (px^2)")
	fmt_stats(cx_vals, "Center X (px)")
	fmt_stats(cy_vals, "Center Y (px)")

	# HSV during static phase
	h_vals = [s['jersey_hsv'][0] for s in static_seeds]
	s_vals = [s['jersey_hsv'][1] for s in static_seeds]
	v_vals = [s['jersey_hsv'][2] for s in static_seeds]
	fmt_stats(h_vals, "Jersey H (hue)")
	fmt_stats(s_vals, "Jersey S (saturation)")
	fmt_stats(v_vals, "Jersey V (value)")

	# total drift during static period
	last = static_seeds[-1]
	last_cx = last['torso_box'][0] + last['torso_box'][2] / 2.0
	last_cy = last['torso_box'][1] + last['torso_box'][3] / 2.0
	drift = math.sqrt((last_cx - start_x) ** 2 + (last_cy - start_y) ** 2)
	# normalize by torso height
	drift_norm = drift / start_h if start_h > 0 else 0.0
	print(f"  Total drift: {drift:.1f}px ({drift_norm:.2f}x torso height)")


#============================================
def measure_size_variability(visible: list, fps: float) -> list:
	"""Metric 3: Runner apparent size variability.

	Returns:
		list of (time_seconds, area) tuples for cyclical analysis.
	"""
	print_subsection("3. Runner Apparent Size (torso area)")

	areas = [s['torso_box'][2] * s['torso_box'][3] for s in visible]
	times = [s['time_seconds'] for s in visible]

	fmt_stats(areas, "Torso area (px^2)")

	if areas:
		area_ratio = max(areas) / min(areas) if min(areas) > 0 else float('inf')
		print(f"  Area ratio (max/min): {area_ratio:.1f}x")

	# per-frame area change rate between consecutive seeds
	area_changes = []
	for i in range(1, len(visible)):
		a1 = visible[i - 1]['torso_box'][2] * visible[i - 1]['torso_box'][3]
		a2 = visible[i]['torso_box'][2] * visible[i]['torso_box'][3]
		if a1 > 0:
			change_rate = abs(a2 - a1) / a1
			area_changes.append(change_rate)
	if area_changes:
		fmt_stats(area_changes, "Per-step area change rate (fraction)")

	# return time-area signal for cyclical analysis
	signal = list(zip(times, areas))
	return signal


#============================================
def measure_movement_variability(visible: list, fps: float,
		frame_w: int, frame_h: int) -> tuple:
	"""Metric 4: Frame movement variability.

	Returns:
		(cx_signal, cy_signal) as lists of (time, value) tuples.
	"""
	print_subsection("4. Frame Movement (torso center)")

	cx_vals = [s['torso_box'][0] + s['torso_box'][2] / 2.0 for s in visible]
	cy_vals = [s['torso_box'][1] + s['torso_box'][3] / 2.0 for s in visible]
	times = [s['time_seconds'] for s in visible]

	fmt_stats(cx_vals, "Center X (px)")
	fmt_stats(cy_vals, "Center Y (px)")

	# x-range and y-range as fraction of frame
	if cx_vals:
		x_range = (max(cx_vals) - min(cx_vals)) / frame_w
		y_range = (max(cy_vals) - min(cy_vals)) / frame_h
		print(f"  X range: {max(cx_vals) - min(cx_vals):.0f}px ({x_range:.1%} of frame width)")
		print(f"  Y range: {max(cy_vals) - min(cy_vals):.0f}px ({y_range:.1%} of frame height)")

	# per-step displacement normalized by torso height
	displacements = []
	dx_vals = []
	dy_vals = []
	for i in range(1, len(visible)):
		cx1 = visible[i - 1]['torso_box'][0] + visible[i - 1]['torso_box'][2] / 2.0
		cy1 = visible[i - 1]['torso_box'][1] + visible[i - 1]['torso_box'][3] / 2.0
		cx2 = visible[i]['torso_box'][0] + visible[i]['torso_box'][2] / 2.0
		cy2 = visible[i]['torso_box'][1] + visible[i]['torso_box'][3] / 2.0
		h = visible[i]['torso_box'][3]
		if h > 0:
			dx = abs(cx2 - cx1) / h
			dy = abs(cy2 - cy1) / h
			dist = math.sqrt((cx2 - cx1) ** 2 + (cy2 - cy1) ** 2) / h
			displacements.append(dist)
			dx_vals.append(dx)
			dy_vals.append(dy)
	if displacements:
		fmt_stats(displacements, "Per-step displacement (x torso height)")
		fmt_stats(dx_vals, "Per-step dx (x torso height)", fmt=".2f")
		fmt_stats(dy_vals, "Per-step dy (x torso height)", fmt=".2f")

	cx_signal = list(zip(times, cx_vals))
	cy_signal = list(zip(times, cy_vals))
	return cx_signal, cy_signal


#============================================
def measure_color_variability(visible: list) -> tuple:
	"""Metric 5: Jersey color variability.

	Returns:
		(h_signal, s_signal, v_signal) as lists of (time, value) tuples.
	"""
	print_subsection("5. Jersey Color Variability (HSV)")

	h_vals = [s['jersey_hsv'][0] for s in visible]
	s_vals = [s['jersey_hsv'][1] for s in visible]
	v_vals = [s['jersey_hsv'][2] for s in visible]
	times = [s['time_seconds'] for s in visible]

	fmt_stats(h_vals, "Hue (H)")
	fmt_stats(s_vals, "Saturation (S)")
	fmt_stats(v_vals, "Value (V)")

	if h_vals:
		h_range = max(h_vals) - min(h_vals)
		v_range = max(v_vals) - min(v_vals)
		print(f"  Hue range: {h_range} (out of 180)")
		print(f"  Value range: {v_range} (out of 255)")
		print("  Note: high variability is expected due to outdoor lighting,")
		print("  camera auto-exposure, and track shadows")

	h_signal = list(zip(times, h_vals))
	s_signal = list(zip(times, s_vals))
	v_signal = list(zip(times, v_vals))
	return h_signal, s_signal, v_signal


#============================================
def measure_torso_vs_full(visible: list) -> None:
	"""Metric 6: Torso box vs full person box relationship."""
	print_subsection("6. Torso Box vs Full Person Box")

	area_ratios = []
	containment_count = 0
	for s in visible:
		tb = s['torso_box']
		fp = s['full_person_box']
		torso_area = tb[2] * tb[3]
		full_area = fp[2] * fp[3]
		if torso_area > 0 and full_area > 0:
			ratio = full_area / torso_area
			area_ratios.append(ratio)

		# check containment: is torso center inside full_person_box?
		tcx = tb[0] + tb[2] / 2.0
		tcy = tb[1] + tb[3] / 2.0
		# full_person_box is [x, y, w, h] top-left format
		if (fp[0] <= tcx <= fp[0] + fp[2]) and (fp[1] <= tcy <= fp[1] + fp[3]):
			containment_count += 1

	fmt_stats(area_ratios, "Area ratio (full/torso)")

	if visible:
		contain_pct = 100.0 * containment_count / len(visible)
		print(f"  Torso center inside full box: {containment_count}/{len(visible)} ({contain_pct:.1f}%)")


#============================================
def measure_diag_vs_seed(visible: list, diagnostics: dict,
		frame_w: int, frame_h: int) -> None:
	"""Metric 7: Seed area vs diagnostics bbox area comparison."""
	print_subsection("7. Diagnostics BBox vs Seed Area")

	if not diagnostics:
		print("  No diagnostics file available")
		return

	bbox_all = diagnostics.get('bbox_all_frames', [])
	if not bbox_all:
		print("  No bbox_all_frames in diagnostics")
		return

	# build lookup: frame_index -> [cx, cy, w, h]
	diag_lookup = {}
	for entry in bbox_all:
		fi = int(entry[0])
		diag_lookup[fi] = entry[1:]

	frame_area = frame_w * frame_h
	ratios = []
	seed_pcts = []
	diag_pcts = []

	for s in visible:
		fi = s['frame_index']
		if fi not in diag_lookup:
			continue
		# seed torso area
		seed_area = s['torso_box'][2] * s['torso_box'][3]
		if seed_area <= 0:
			continue
		# diagnostics bbox area (cx, cy, w, h)
		dbox = diag_lookup[fi]
		diag_area = dbox[2] * dbox[3]
		if diag_area <= 0:
			continue

		ratio = diag_area / seed_area
		ratios.append(ratio)
		seed_pcts.append(100.0 * seed_area / frame_area)
		diag_pcts.append(100.0 * diag_area / frame_area)

	if not ratios:
		print("  No matching frames between seeds and diagnostics")
		return

	print(f"  Matched frames: {len(ratios)}")
	fmt_stats(ratios, "Diag area / seed area ratio")
	fmt_stats(seed_pcts, "Seed area (% of frame)", fmt=".2f")
	fmt_stats(diag_pcts, "Diag area (% of frame)", fmt=".2f")

	# highlight the size mismatch
	mean_ratio = statistics.mean(ratios)
	if mean_ratio > 5:
		print(f"  WARNING: diagnostics bbox is ~{mean_ratio:.0f}x larger than seed torso")
		print("  The current tracker drastically overestimates runner size")


#============================================
def running_average(signal: list, window_sec: float) -> list:
	"""Apply a running average to a time-value signal.

	Uses a sliding window approach for efficiency. Signal must be sorted
	by time (which it naturally is from seed frame order).

	Args:
		signal: list of (time, value) tuples sorted by time
		window_sec: window size in seconds

	Returns:
		list of (time, smoothed_value) tuples
	"""
	if not signal:
		return []
	half_window = window_sec / 2.0
	n = len(signal)
	smoothed = []
	# use two-pointer sliding window
	left = 0
	right = 0
	window_sum = 0.0
	window_count = 0
	for i in range(n):
		t_center = signal[i][0]
		# expand right boundary
		while right < n and signal[right][0] <= t_center + half_window:
			window_sum += signal[right][1]
			window_count += 1
			right += 1
		# shrink left boundary
		while left < n and signal[left][0] < t_center - half_window:
			window_sum -= signal[left][1]
			window_count -= 1
			left += 1
		avg = window_sum / window_count if window_count > 0 else 0.0
		smoothed.append((t_center, avg))
	return smoothed


#============================================
def find_peaks_and_troughs(signal: list) -> tuple:
	"""Find local peaks and troughs in a smoothed signal.

	Returns:
		(peaks, troughs) as lists of (time, value) tuples
	"""
	if len(signal) < 3:
		return [], []
	peaks = []
	troughs = []
	for i in range(1, len(signal) - 1):
		prev_val = signal[i - 1][1]
		curr_val = signal[i][1]
		next_val = signal[i + 1][1]
		if curr_val > prev_val and curr_val > next_val:
			peaks.append(signal[i])
		elif curr_val < prev_val and curr_val < next_val:
			troughs.append(signal[i])
	return peaks, troughs


#============================================
def filter_close_extrema(extrema: list, min_sep: float,
		keep_max: bool = True) -> list:
	"""Filter extrema that are too close together.

	When two extrema are within min_sep seconds, keep the one with the
	larger value (for peaks) or smaller value (for troughs).

	Args:
		extrema: list of (time, value) tuples
		min_sep: minimum separation in seconds
		keep_max: if True keep larger values (peaks), else smaller (troughs)

	Returns:
		filtered list of (time, value) tuples
	"""
	if not extrema:
		return []
	filtered = [extrema[0]]
	for i in range(1, len(extrema)):
		# check distance to last kept extremum
		if extrema[i][0] - filtered[-1][0] < min_sep:
			# too close -- keep the more extreme one
			if keep_max:
				if extrema[i][1] > filtered[-1][1]:
					filtered[-1] = extrema[i]
			else:
				if extrema[i][1] < filtered[-1][1]:
					filtered[-1] = extrema[i]
		else:
			filtered.append(extrema[i])
	return filtered


#============================================
def measure_cyclical_patterns(area_signal: list, cx_signal: list,
		cy_signal: list) -> None:
	"""Metric 8: Cyclical pattern analysis (lap detection)."""
	print_subsection("8. Cyclical Pattern Analysis (Lap Detection)")

	# use a window of ~15 seconds (quarter of expected ~60s lap period)
	window_sec = 15.0
	signals = {
		'area': area_signal,
		'center_x': cx_signal,
	}

	for name, raw_signal in signals.items():
		if len(raw_signal) < 10:
			print(f"  {name}: not enough data points")
			continue

		# duration of signal
		duration = raw_signal[-1][0] - raw_signal[0][0]
		if duration < 30:
			print(f"  {name}: video too short for lap detection ({duration:.0f}s)")
			continue

		# smooth the signal
		smoothed = running_average(raw_signal, window_sec)

		# find peaks and troughs on smoothed signal
		peaks, troughs = find_peaks_and_troughs(smoothed)

		# filter out peaks that are too close together (< 20s apart)
		# keep only the tallest peak in each cluster
		min_peak_sep = 20.0
		peaks = filter_close_extrema(peaks, min_peak_sep, keep_max=True)
		troughs = filter_close_extrema(troughs, min_peak_sep, keep_max=False)

		if len(peaks) < 2:
			print(f"  {name}: fewer than 2 peaks detected, cannot measure laps")
			continue

		# peak-to-peak periods
		periods = []
		for i in range(1, len(peaks)):
			period = peaks[i][0] - peaks[i - 1][0]
			periods.append(period)

		mean_period = statistics.mean(periods)
		std_period = statistics.stdev(periods) if len(periods) > 1 else 0.0

		# amplitude: average peak minus average trough
		peak_vals = [p[1] for p in peaks]
		trough_vals = [t[1] for t in troughs]
		avg_peak = statistics.mean(peak_vals) if peak_vals else 0
		avg_trough = statistics.mean(trough_vals) if trough_vals else 0
		amplitude = avg_peak - avg_trough

		# regularity: coefficient of variation of periods
		regularity = std_period / mean_period if mean_period > 0 else 0

		print(f"\n  Signal: {name}")
		print(f"    Peaks detected: {len(peaks)}")
		print(f"    Troughs detected: {len(troughs)}")
		print(f"    Complete laps: {len(periods)}")
		print(f"    Estimated lap period: {mean_period:.1f}s (std={std_period:.1f}s)")
		print(f"    Amplitude (peak-trough): {amplitude:.1f}")
		print(f"    Regularity (CV of period): {regularity:.3f}")
		if regularity < 0.1:
			print("    -> Very regular laps")
		elif regularity < 0.2:
			print("    -> Moderately regular laps")
		else:
			print("    -> Irregular lap timing")

		# print individual period values
		period_str = ", ".join(f"{p:.1f}s" for p in periods)
		print(f"    Individual periods: [{period_str}]")


#============================================
def write_csv_signals(video_name: str, visible: list, diagnostics: dict,
		area_signal: list, cx_signal: list, cy_signal: list,
		csv_dir: str) -> None:
	"""Write raw and smoothed signal data to CSV files.

	Creates two CSV files per video:
	- *_raw.csv: per-seed raw measurements
	- *_smoothed.csv: running-averaged signals
	"""
	os.makedirs(csv_dir, exist_ok=True)

	# raw CSV: one row per visible seed
	raw_path = os.path.join(csv_dir, f"seed_variability_{video_name}_raw.csv")
	# build diagnostics lookup for area comparison
	diag_lookup = {}
	if diagnostics:
		for entry in diagnostics.get('bbox_all_frames', []):
			fi = int(entry[0])
			diag_lookup[fi] = entry[1:]

	with open(raw_path, 'w', newline='') as f:
		writer = csv.writer(f)
		writer.writerow([
			'frame_index', 'time_seconds',
			'torso_x', 'torso_y', 'torso_w', 'torso_h', 'torso_area',
			'torso_cx', 'torso_cy',
			'full_x', 'full_y', 'full_w', 'full_h', 'full_area',
			'jersey_h', 'jersey_s', 'jersey_v',
			'diag_cx', 'diag_cy', 'diag_w', 'diag_h', 'diag_area',
		])
		for s in visible:
			tb = s['torso_box']
			fp = s['full_person_box']
			fi = s['frame_index']
			torso_area = tb[2] * tb[3]
			full_area = fp[2] * fp[3]
			tcx = tb[0] + tb[2] / 2.0
			tcy = tb[1] + tb[3] / 2.0
			# diagnostics values at this frame
			if fi in diag_lookup:
				dbox = diag_lookup[fi]
				d_cx, d_cy, d_w, d_h = dbox[0], dbox[1], dbox[2], dbox[3]
				d_area = d_w * d_h
			else:
				d_cx = d_cy = d_w = d_h = d_area = ''
			writer.writerow([
				fi, s['time_seconds'],
				tb[0], tb[1], tb[2], tb[3], torso_area,
				tcx, tcy,
				fp[0], fp[1], fp[2], fp[3], full_area,
				s['jersey_hsv'][0], s['jersey_hsv'][1], s['jersey_hsv'][2],
				d_cx, d_cy, d_w, d_h, d_area,
			])
	print(f"  CSV (raw): {raw_path}")

	# smoothed CSV: running-averaged signals at each seed time
	sm_path = os.path.join(csv_dir, f"seed_variability_{video_name}_smoothed.csv")
	window_sec = 15.0
	# compute smoothed versions
	times = [t for t, _ in area_signal]
	area_vals = [v for _, v in area_signal]
	cx_vals = [v for _, v in cx_signal]
	cy_vals = [v for _, v in cy_signal]
	# jersey HSV
	h_vals = [s['jersey_hsv'][0] for s in visible]
	s_vals = [s['jersey_hsv'][1] for s in visible]
	v_vals = [s['jersey_hsv'][2] for s in visible]

	sm_area = running_average(list(zip(times, area_vals)), window_sec)
	sm_cx = running_average(list(zip(times, cx_vals)), window_sec)
	sm_cy = running_average(list(zip(times, cy_vals)), window_sec)
	sm_h = running_average(list(zip(times, h_vals)), window_sec)
	sm_s = running_average(list(zip(times, s_vals)), window_sec)
	sm_v = running_average(list(zip(times, v_vals)), window_sec)

	with open(sm_path, 'w', newline='') as f:
		writer = csv.writer(f)
		writer.writerow([
			'time_seconds',
			'area_raw', 'area_smoothed',
			'cx_raw', 'cx_smoothed',
			'cy_raw', 'cy_smoothed',
			'hue_raw', 'hue_smoothed',
			'sat_raw', 'sat_smoothed',
			'val_raw', 'val_smoothed',
		])
		for i in range(len(times)):
			writer.writerow([
				times[i],
				area_vals[i], sm_area[i][1],
				cx_vals[i], sm_cx[i][1],
				cy_vals[i], sm_cy[i][1],
				h_vals[i], sm_h[i][1],
				s_vals[i], sm_s[i][1],
				v_vals[i], sm_v[i][1],
			])
	print(f"  CSV (smoothed): {sm_path}")


#============================================
def analyze_video(seed_path: str, fps: float, csv_dir: str = None) -> None:
	"""Run all variability measurements for one video."""
	basename = os.path.basename(seed_path)
	# extract video name (remove .track_runner.seeds.yaml)
	video_name = basename.replace('.track_runner.seeds.yaml', '')

	print_section(f"Seed Variability Report: {video_name}")
	print(f"  Seed file: {seed_path}")
	print(f"  FPS: {fps}")

	# load seed data
	seed_data = load_yaml_file(seed_path)
	seeds = seed_data.get('seeds', [])
	if not seeds:
		print("  ERROR: No seeds found in file")
		return

	visible, absent = split_seeds(seeds)
	print(f"  Seeds loaded: {len(seeds)} total ({len(visible)} visible, {len(absent)} absent)")

	# load diagnostics if available
	diag_path = diagnostics_path_for_seeds(seed_path)
	diagnostics = None
	if os.path.exists(diag_path):
		print(f"  Diagnostics file: {diag_path}")
		diagnostics = load_yaml_file(diag_path)
	else:
		print("  Diagnostics file: not found")

	# frame dimensions
	frame_w = DEFAULT_FRAME_WIDTH
	frame_h = DEFAULT_FRAME_HEIGHT

	# run all metrics
	measure_seed_coverage(seeds, visible, absent, diagnostics, fps)
	measure_start_line(visible, fps)
	area_signal = measure_size_variability(visible, fps)
	cx_signal, cy_signal = measure_movement_variability(visible, fps, frame_w, frame_h)
	measure_color_variability(visible)
	measure_torso_vs_full(visible)
	measure_diag_vs_seed(visible, diagnostics, frame_w, frame_h)
	measure_cyclical_patterns(area_signal, cx_signal, cy_signal)

	# write CSV if requested
	if csv_dir:
		write_csv_signals(video_name, visible, diagnostics,
			area_signal, cx_signal, cy_signal, csv_dir)


#============================================
def main() -> None:
	"""Main entry point."""
	args = parse_args()

	if args.input_files:
		seed_files = args.input_files
	else:
		seed_files = find_seed_files()

	if not seed_files:
		print("No seed files found.")
		print(f"  Searched: {os.path.join(REPO_ROOT, 'TRACK_VIDEOS', '*.track_runner.seeds.yaml')}")
		raise SystemExit(1)

	print(f"Found {len(seed_files)} seed file(s)")

	csv_dir = args.csv_dir if args.write_csv else None
	for seed_path in seed_files:
		analyze_video(seed_path, args.fps, csv_dir=csv_dir)

	print(f"\n{'=' * 60}")
	print("  Done.")
	print(f"{'=' * 60}")


#============================================
if __name__ == '__main__':
	main()
