#!/usr/bin/env python3
"""Generate matplotlib plots of seed variability signals for track_runner.

Produces a multi-panel figure per video showing raw and smoothed signals
for torso area, center position, jersey HSV, and diagnostics comparison.
Saves PNG files to output_smoke/.
"""

# Standard Library
import os
import sys
import glob
import argparse

# PIP3 modules
import yaml
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# local repo modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tests'))
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()

DEFAULT_FRAME_WIDTH = 1280
DEFAULT_FRAME_HEIGHT = 720
DEFAULT_FPS = 30.0
SMOOTH_WINDOW_SEC = 15.0


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments."""
	parser = argparse.ArgumentParser(
		description="Plot seed variability signals for track_runner videos"
	)
	parser.add_argument(
		'-i', '--input', dest='input_files', nargs='+',
		help="Seed YAML file path(s). Defaults to all in TRACK_VIDEOS/"
	)
	parser.add_argument(
		'-o', '--output-dir', dest='output_dir',
		default=os.path.join(REPO_ROOT, "output_smoke"),
		help="Output directory for plots"
	)
	parser.add_argument(
		'-f', '--fps', dest='fps', type=float, default=DEFAULT_FPS,
		help="Video frame rate (default: 30.0)"
	)
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
	diag_path = seed_path.replace(".seeds.yaml", ".diagnostics.yaml")
	return diag_path


#============================================
def split_seeds(seeds: list) -> tuple:
	"""Split seed list into visible and absent entries."""
	visible = []
	absent = []
	for s in seeds:
		if 'status' in s:
			absent.append(s)
		else:
			visible.append(s)
	return visible, absent


#============================================
def running_average(times: list, values: list, window_sec: float) -> tuple:
	"""Apply a running average to a time-value signal.

	Args:
		times: list of time values (seconds)
		values: list of corresponding values
		window_sec: window size in seconds

	Returns:
		(smoothed_times, smoothed_values) as separate lists
	"""
	if not times:
		return [], []
	half_window = window_sec / 2.0
	n = len(times)
	sm_times = []
	sm_vals = []
	left = 0
	right = 0
	window_sum = 0.0
	window_count = 0
	for i in range(n):
		t_center = times[i]
		while right < n and times[right] <= t_center + half_window:
			window_sum += values[right]
			window_count += 1
			right += 1
		while left < n and times[left] < t_center - half_window:
			window_sum -= values[left]
			window_count -= 1
			left += 1
		avg = window_sum / window_count if window_count > 0 else 0.0
		sm_times.append(t_center)
		sm_vals.append(avg)
	return sm_times, sm_vals


#============================================
def extract_signals(visible: list, diagnostics: dict,
		frame_w: int, frame_h: int) -> dict:
	"""Extract all signal data from visible seeds.

	Returns:
		dict with keys: times, area, cx, cy, hue, sat, val,
		diag_times, diag_area, seed_area_at_diag
	"""
	times = [s['time_seconds'] for s in visible]
	areas = [s['torso_box'][2] * s['torso_box'][3] for s in visible]
	cx_vals = [s['torso_box'][0] + s['torso_box'][2] / 2.0 for s in visible]
	cy_vals = [s['torso_box'][1] + s['torso_box'][3] / 2.0 for s in visible]
	h_vals = [s['jersey_hsv'][0] for s in visible]
	s_vals = [s['jersey_hsv'][1] for s in visible]
	v_vals = [s['jersey_hsv'][2] for s in visible]

	signals = {
		'times': times,
		'area': areas,
		'cx': cx_vals,
		'cy': cy_vals,
		'hue': h_vals,
		'sat': s_vals,
		'val': v_vals,
	}

	# diagnostics bbox area comparison
	if diagnostics:
		bbox_all = diagnostics.get('bbox_all_frames', [])
		if bbox_all:
			diag_lookup = {}
			for entry in bbox_all:
				fi = int(entry[0])
				diag_lookup[fi] = entry[1:]

			diag_times = []
			diag_areas = []
			seed_areas_at_diag = []
			for s in visible:
				fi = s['frame_index']
				if fi not in diag_lookup:
					continue
				seed_area = s['torso_box'][2] * s['torso_box'][3]
				if seed_area <= 0:
					continue
				dbox = diag_lookup[fi]
				diag_area = dbox[2] * dbox[3]
				if diag_area <= 0:
					continue
				diag_times.append(s['time_seconds'])
				diag_areas.append(diag_area)
				seed_areas_at_diag.append(seed_area)
			signals['diag_times'] = diag_times
			signals['diag_area'] = diag_areas
			signals['seed_area_at_diag'] = seed_areas_at_diag

	return signals


#============================================
def plot_video(seed_path: str, fps: float, output_dir: str) -> None:
	"""Generate variability plots for one video."""
	basename = os.path.basename(seed_path)
	video_name = basename.replace('.track_runner.seeds.yaml', '')

	print(f"Processing: {video_name}")

	# load data
	seed_data = load_yaml_file(seed_path)
	seeds = seed_data.get('seeds', [])
	if not seeds:
		print(f"  No seeds in {seed_path}")
		return
	visible, absent = split_seeds(seeds)
	if len(visible) < 5:
		print(f"  Too few visible seeds ({len(visible)})")
		return

	# load diagnostics
	diag_path = diagnostics_path_for_seeds(seed_path)
	diagnostics = None
	if os.path.exists(diag_path):
		diagnostics = load_yaml_file(diag_path)

	signals = extract_signals(visible, diagnostics, DEFAULT_FRAME_WIDTH, DEFAULT_FRAME_HEIGHT)
	times = signals['times']

	# compute smoothed signals
	sm_t_area, sm_area = running_average(times, signals['area'], SMOOTH_WINDOW_SEC)
	sm_t_cx, sm_cx = running_average(times, signals['cx'], SMOOTH_WINDOW_SEC)
	sm_t_cy, sm_cy = running_average(times, signals['cy'], SMOOTH_WINDOW_SEC)
	sm_t_hue, sm_hue = running_average(times, signals['hue'], SMOOTH_WINDOW_SEC)
	sm_t_sat, sm_sat = running_average(times, signals['sat'], SMOOTH_WINDOW_SEC)
	sm_t_val, sm_val = running_average(times, signals['val'], SMOOTH_WINDOW_SEC)

	# create figure with subplots
	has_diag = 'diag_times' in signals and len(signals['diag_times']) > 0
	# 6 panels: area, cx, cy, hue, saturation+value, diag comparison
	n_panels = 6 if has_diag else 5
	fig, axes = plt.subplots(n_panels, 1, figsize=(14, 3.0 * n_panels), sharex=True)
	fig.suptitle(f"Seed Variability: {video_name}", fontsize=14, fontweight='bold')

	# mark absent seed locations on all panels
	absent_times = [s['time_seconds'] for s in absent]

	# panel 0: torso area
	ax = axes[0]
	ax.scatter(times, signals['area'], s=8, alpha=0.4, color='steelblue', label='raw')
	ax.plot(sm_t_area, sm_area, color='darkblue', linewidth=2, label=f'smoothed ({SMOOTH_WINDOW_SEC:.0f}s)')
	for at in absent_times:
		ax.axvline(at, color='red', alpha=0.3, linewidth=0.8)
	ax.set_ylabel('Torso Area (px^2)')
	ax.set_title('Runner Apparent Size (torso area)')
	ax.legend(loc='upper right', fontsize=8)
	ax.grid(True, alpha=0.3)

	# panel 1: center X
	ax = axes[1]
	ax.scatter(times, signals['cx'], s=8, alpha=0.4, color='forestgreen', label='raw')
	ax.plot(sm_t_cx, sm_cx, color='darkgreen', linewidth=2, label=f'smoothed ({SMOOTH_WINDOW_SEC:.0f}s)')
	for at in absent_times:
		ax.axvline(at, color='red', alpha=0.3, linewidth=0.8)
	ax.set_ylabel('Center X (px)')
	ax.set_title('Horizontal Position (center X)')
	ax.legend(loc='upper right', fontsize=8)
	ax.grid(True, alpha=0.3)

	# panel 2: center Y
	ax = axes[2]
	ax.scatter(times, signals['cy'], s=8, alpha=0.4, color='darkorange', label='raw')
	ax.plot(sm_t_cy, sm_cy, color='saddlebrown', linewidth=2, label=f'smoothed ({SMOOTH_WINDOW_SEC:.0f}s)')
	for at in absent_times:
		ax.axvline(at, color='red', alpha=0.3, linewidth=0.8)
	ax.set_ylabel('Center Y (px)')
	ax.set_title('Vertical Position (center Y)')
	ax.legend(loc='upper right', fontsize=8)
	ax.grid(True, alpha=0.3)
	# invert Y so up=up visually
	ax.invert_yaxis()

	# panel 3: hue
	ax = axes[3]
	ax.scatter(times, signals['hue'], s=8, alpha=0.4, color='purple', label='raw H')
	ax.plot(sm_t_hue, sm_hue, color='darkviolet', linewidth=2, label=f'smoothed H ({SMOOTH_WINDOW_SEC:.0f}s)')
	for at in absent_times:
		ax.axvline(at, color='red', alpha=0.3, linewidth=0.8)
	ax.set_ylabel('Hue (0-180)')
	ax.set_title('Jersey Hue (H channel)')
	ax.set_ylim(0, 180)
	ax.legend(loc='upper right', fontsize=8)
	ax.grid(True, alpha=0.3)

	# panel 4: saturation and value
	ax = axes[4]
	ax.scatter(times, signals['sat'], s=6, alpha=0.3, color='teal', label='raw S')
	ax.scatter(times, signals['val'], s=6, alpha=0.3, color='goldenrod', label='raw V')
	ax.plot(sm_t_sat, sm_sat, color='darkcyan', linewidth=2, label=f'smoothed S ({SMOOTH_WINDOW_SEC:.0f}s)')
	ax.plot(sm_t_val, sm_val, color='darkgoldenrod', linewidth=2, label=f'smoothed V ({SMOOTH_WINDOW_SEC:.0f}s)')
	for at in absent_times:
		ax.axvline(at, color='red', alpha=0.3, linewidth=0.8)
	ax.set_ylabel('S / V (0-255)')
	ax.set_title('Jersey Saturation & Value')
	ax.set_ylim(0, 255)
	ax.legend(loc='upper right', fontsize=8)
	ax.grid(True, alpha=0.3)

	# panel 5: diagnostics area vs seed area (if available)
	if has_diag:
		ax = axes[5]
		dt = signals['diag_times']
		# plot both areas on log scale
		ax.scatter(dt, signals['seed_area_at_diag'], s=8, alpha=0.5,
			color='forestgreen', label='Seed torso area (ground truth)')
		ax.scatter(dt, signals['diag_area'], s=8, alpha=0.5,
			color='crimson', label='Diagnostics bbox area (tracker)')
		ax.set_ylabel('Area (px^2)')
		ax.set_title('Tracker BBox vs Ground Truth Seed Area')
		ax.set_yscale('log')
		ax.legend(loc='upper right', fontsize=8)
		ax.grid(True, alpha=0.3)

	# shared x label
	axes[-1].set_xlabel('Time (seconds)')

	plt.tight_layout()
	# save
	out_path = os.path.join(output_dir, f"seed_variability_{video_name}.png")
	fig.savefig(out_path, dpi=150, bbox_inches='tight')
	plt.close(fig)
	print(f"  Saved: {out_path}")


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
		raise SystemExit(1)

	# ensure output directory exists
	os.makedirs(args.output_dir, exist_ok=True)

	print(f"Found {len(seed_files)} seed file(s)")
	print(f"Output directory: {args.output_dir}")

	for seed_path in seed_files:
		plot_video(seed_path, args.fps, args.output_dir)

	print("Done.")


#============================================
if __name__ == '__main__':
	main()
