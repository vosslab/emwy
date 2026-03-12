#!/usr/bin/env python3
"""CLI entry point for the track_runner tool v2.

Multi-pass orchestration: seed collection, interval solving, refinement,
crop trajectory computation, and video encoding.

Subcommands:
  run     Full pipeline: seed -> solve -> encode (default workflow)
  seed    Collect/add seeds, save, exit
  edit    Review/fix/delete existing seeds interactively
  target  Add seeds at weak interval frames with FWD/BWD overlays
  solve   Full re-solve: clears prior results and solves all intervals fresh
  refine  Re-solve only changed/new intervals, reuse prior results
  encode  Encode from existing trajectory, no solving
"""

# Standard Library
import argparse
import json
import os
import queue
import shutil
import subprocess
import time

# local repo modules
import config
import state_io
import detection
import encoder
import seeding
import scoring
import seed_editor
import interval_solver
import review
import crop


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments with subcommands for track_runner v2.

	Returns:
		Parsed argparse.Namespace with a 'mode' attribute.
	"""
	parser = argparse.ArgumentParser(
		description="track_runner v2: multi-pass runner tracking and crop tool.",
	)
	# shared args on parent parser
	parser.add_argument(
		"-i", "--input", dest="input_file", required=True,
		help="Input video file path.",
	)
	parser.add_argument(
		"-c", "--config", dest="config_file", default=None,
		help="Config YAML file path.",
	)
	parser.add_argument(
		"-d", "--debug", dest="debug", action="store_true",
		help="Enable debug video output with tracking overlays.",
	)
	parser.add_argument(
		"-w", "--workers", dest="workers", type=int, default=None,
		help="Number of parallel workers (default: half of CPU cores).",
	)
	parser.add_argument(
		"--time-range", dest="time_range", type=str, default=None,
		help=(
			"Limit operations to time range in seconds. "
			"Format: 'START:END', 'START:', or ':END'. "
			"Examples: '30:120', '200:'."
		),
	)
	parser.add_argument(
		"--write-default-config", dest="write_default_config",
		action="store_true",
		help="Write the default config for this input and exit.",
	)
	parser.set_defaults(
		write_default_config=False,
		debug=False,
	)

	subparsers = parser.add_subparsers(dest="mode")

	# -- seed mode --
	seed_parser = subparsers.add_parser(
		"seed", help="Collect seeds, save, and exit.",
	)
	seed_parser.add_argument(
		"--seed-interval", dest="seed_interval", type=float, default=10.0,
		help="Interval in seconds between seed frames (default 10).",
	)

	# -- edit mode --
	edit_parser = subparsers.add_parser(
		"edit", help="Review/fix/delete existing seeds interactively.",
	)
	edit_parser.add_argument(
		"-s", "--severity", dest="severity", type=str, default=None,
		choices=("high", "medium", "low"),
		help="Filter seeds near weak intervals at this severity threshold.",
	)

	# -- target mode --
	target_parser = subparsers.add_parser(
		"target", help="Add seeds at weak interval frames with FWD/BWD overlays.",
	)
	target_parser.add_argument(
		"-s", "--severity", dest="severity", type=str, default=None,
		choices=("high", "medium", "low"),
		help="Minimum severity of weak intervals to target.",
	)
	target_parser.add_argument(
		"--seed-interval", dest="seed_interval", type=float, default=10.0,
		help="Interval in seconds between seed frames (default 10).",
	)

	# -- solve mode --
	subparsers.add_parser(
		"solve", help="Full re-solve: clears prior results and solves all intervals fresh.",
	)

	# -- refine mode --
	subparsers.add_parser(
		"refine", help="Re-solve only changed/new intervals, reuse prior results.",
	)

	# -- encode mode --
	encode_parser = subparsers.add_parser(
		"encode", help="Encode cropped video from existing trajectory.",
	)
	encode_parser.add_argument(
		"-o", "--output", dest="output_file", default=None,
		help="Output video file path (auto-generated if not provided).",
	)
	encode_parser.add_argument(
		"--aspect", dest="aspect", type=str, default=None,
		help="Override crop aspect ratio (e.g. '1:1', '16:9').",
	)
	encode_parser.add_argument(
		"--keep-temp", dest="keep_temp", action="store_true",
		help="Keep temporary files after encoding.",
	)

	# -- run mode (full pipeline) --
	run_parser = subparsers.add_parser(
		"run", help="Full pipeline: seed -> solve -> encode.",
	)
	run_parser.add_argument(
		"-o", "--output", dest="output_file", default=None,
		help="Output video file path (auto-generated if not provided).",
	)
	run_parser.add_argument(
		"--seed-interval", dest="seed_interval", type=float, default=10.0,
		help="Interval in seconds between seed frames (default 10).",
	)
	run_parser.add_argument(
		"--aspect", dest="aspect", type=str, default=None,
		help="Override crop aspect ratio (e.g. '1:1', '16:9').",
	)
	run_parser.add_argument(
		"--keep-temp", dest="keep_temp", action="store_true",
		help="Keep temporary files after encoding.",
	)
	run_parser.add_argument(
		"--refine", dest="refine", type=str, default=None,
		help=(
			"Refinement mode(s): 'suggested', 'interval', 'gap', or "
			"comma-separated combination."
		),
	)
	run_parser.add_argument(
		"--gap-threshold", dest="gap_threshold", type=float, default=8.0,
		help="Gap threshold in seconds for 'gap' refinement (default 8.0).",
	)
	run_parser.add_argument(
		"--ignore-diagnostics", dest="ignore_diagnostics",
		action="store_true",
		help="Force re-seeding even where solver thinks intervals are fine.",
	)
	run_parser.add_argument(
		"-s", "--severity", dest="severity", type=str, default=None,
		choices=("high", "medium", "low"),
		help="Minimum severity of weak intervals to refine.",
	)
	run_parser.add_argument(
		"--no-interactive-refine", dest="interactive_refine",
		action="store_false",
		help="Disable interactive refinement prompt after solve.",
	)
	run_parser.set_defaults(
		keep_temp=False,
		ignore_diagnostics=False,
		interactive_refine=True,
	)

	args = parser.parse_args()
	# default to 'run' mode when no subcommand is given
	if args.mode is None:
		args.mode = "run"
		# set run-mode defaults that would normally come from subparser
		if not hasattr(args, "output_file"):
			args.output_file = None
		if not hasattr(args, "seed_interval"):
			args.seed_interval = 10.0
		if not hasattr(args, "aspect"):
			args.aspect = None
		if not hasattr(args, "keep_temp"):
			args.keep_temp = False
		if not hasattr(args, "refine"):
			args.refine = None
		if not hasattr(args, "gap_threshold"):
			args.gap_threshold = 8.0
		if not hasattr(args, "ignore_diagnostics"):
			args.ignore_diagnostics = False
		if not hasattr(args, "severity"):
			args.severity = None
		if not hasattr(args, "interactive_refine"):
			args.interactive_refine = True
	return args


#============================================
def _probe_video(input_file: str) -> dict:
	"""Probe video metadata using mediainfo JSON output.

	Extracts resolution, fps, frame count, and duration from the first
	video track. Falls back to General track for frame count and duration
	when the Video track lacks them.

	Args:
		input_file: Path to the input video file.

	Returns:
		Dict with keys: width, height, fps, frame_count, duration_s.

	Raises:
		RuntimeError: If mediainfo fails or returns no video track.
	"""
	mediainfo_path = shutil.which("mediainfo")
	if mediainfo_path is None:
		raise RuntimeError("mediainfo not found in PATH")
	cmd = [mediainfo_path, "--Output=JSON", input_file]
	result = subprocess.run(cmd, capture_output=True, text=True)
	if result.returncode != 0:
		raise RuntimeError(f"mediainfo failed: {result.stderr.strip()}")
	data = json.loads(result.stdout)
	media = data.get("media")
	if media is None:
		raise RuntimeError(f"mediainfo returned no media for: {input_file}")
	tracks = media.get("track", [])
	# find the first Video track and General track
	video_track = None
	general_track = None
	for track in tracks:
		track_type = track.get("@type", "")
		if track_type == "Video" and video_track is None:
			video_track = track
		elif track_type == "General" and general_track is None:
			general_track = track
	if video_track is None:
		raise RuntimeError(f"no video track found in: {input_file}")
	# extract resolution
	width = int(video_track["Width"])
	height = int(video_track["Height"])
	# extract fps (mediainfo provides FrameRate as a decimal string)
	fps = float(video_track.get("FrameRate", "0"))
	if fps <= 0:
		raise RuntimeError(f"invalid fps from mediainfo: {input_file}")
	# extract frame count; fall back to General track, then duration * fps
	frame_count_str = video_track.get("FrameCount")
	if frame_count_str is None and general_track is not None:
		frame_count_str = general_track.get("FrameCount")
	duration_str = video_track.get("Duration")
	if duration_str is None and general_track is not None:
		duration_str = general_track.get("Duration")
	if frame_count_str is not None:
		frame_count = int(frame_count_str)
		duration_s = frame_count / fps
	elif duration_str is not None:
		duration_s = float(duration_str)
		frame_count = int(duration_s * fps)
	else:
		raise RuntimeError(f"no frame count or duration from mediainfo: {input_file}")
	info = {
		"width": width,
		"height": height,
		"fps": fps,
		"frame_count": frame_count,
		"duration_s": duration_s,
	}
	return info


#============================================
def _parse_time_range(time_range_str: str | None) -> tuple | None:
	"""Parse a 'START:END' time range string into a (start_s, end_s) tuple.

	Supports open-ended ranges: '200:' means from 200s to end,
	':500' means from start to 500s.

	Args:
		time_range_str: String like '30:120', '200:', ':500', or None.

	Returns:
		Tuple (start_s, end_s) where either may be None for open-ended
		ranges, or None if input is None.

	Raises:
		RuntimeError: If the string format is invalid.
	"""
	if time_range_str is None:
		return None
	parts = time_range_str.split(":")
	if len(parts) != 2:
		raise RuntimeError(
			f"Invalid --time-range format '{time_range_str}', expected 'START:END'"
		)
	# parse start, allowing empty string for open-ended start
	start_s = float(parts[0]) if parts[0].strip() else None
	# parse end, allowing empty string for open-ended end
	end_s = float(parts[1]) if parts[1].strip() else None
	return (start_s, end_s)


#============================================
def _print_quality_summary(diagnostics: dict, fps: float) -> None:
	"""Print a human-readable quality summary from diagnostics.

	Args:
		diagnostics: Dict from interval_solver.solve_all_intervals().
		fps: Video frame rate for time calculations.
	"""
	intervals = diagnostics.get("intervals", [])
	total = len(intervals)
	weak = sum(
		1 for iv in intervals
		if iv.get("interval_score", {}).get("confidence", "low") != "high"
	)
	print("")
	print(f"quality summary: {total - weak}/{total} intervals trusted")
	if review.needs_refinement(diagnostics):
		# compute severity breakdown for weak intervals
		high_count = 0
		medium_count = 0
		low_count = 0
		for iv in intervals:
			score = iv.get("interval_score", {})
			if score.get("confidence", "low") == "high":
				continue
			sev = review.classify_interval_severity(iv, fps)
			if sev == "high":
				high_count += 1
			elif sev == "medium":
				medium_count += 1
			else:
				low_count += 1
		print(f"  weakness breakdown: {high_count} high, "
			f"{medium_count} medium, {low_count} low severity")
		print(f"  hint: use --severity=high to focus on the "
			f"{high_count} worst intervals")
	else:
		print("  all intervals trusted -- tracking quality is good")
	print("")


#============================================
def _build_predictions_from_diagnostics(diagnostics: dict) -> dict:
	"""Build frame-indexed forward/backward prediction dict from solved intervals.

	Args:
		diagnostics: Dict from solve_all_intervals() with in-memory interval data.

	Returns:
		Dict mapping frame_index (int) to {"forward": {cx,cy,w,h}, "backward": {cx,cy,w,h}}.
	"""
	predictions = {}
	for iv in diagnostics.get("intervals", []):
		fwd_track = iv.get("forward_track")
		bwd_track = iv.get("backward_track")
		if fwd_track is None or bwd_track is None:
			# stored intervals may lack per-direction tracks
			continue
		start_frame = int(iv["start_frame"])
		n = min(len(fwd_track), len(bwd_track))
		for i in range(n):
			frame_idx = start_frame + i
			predictions[frame_idx] = {
				"forward": fwd_track[i],
				"backward": bwd_track[i],
			}
	return predictions


#============================================
def _load_prior_results(intervals_path: str) -> tuple:
	"""Load previously solved intervals and build a write-through callback.

	Returns the solved-intervals dict and a callback that persists new
	entries to disk immediately after each interval is solved.

	Args:
		intervals_path: Path to the solved-intervals JSON file.

	Returns:
		Tuple (prior_results_dict, on_interval_solved_callback).
	"""
	intervals_file = state_io.load_intervals(intervals_path)
	solved = intervals_file.get("solved_intervals", {})

	def _on_interval_solved(fingerprint: str, result: dict) -> None:
		"""Persist a newly solved interval to disk."""
		solved[fingerprint] = result
		intervals_file["solved_intervals"] = solved
		state_io.write_intervals(intervals_path, intervals_file)

	return (solved, _on_interval_solved)


#============================================
def _invalidate_intervals_for_frames(
	intervals_path: str,
	changed_frames: set,
) -> None:
	"""Remove solved intervals that touch any of the changed seed frames.

	Each fingerprint key encodes two seed frame indices separated by pipe
	characters. An interval is invalidated if either its start or end
	frame index appears in changed_frames.

	Args:
		intervals_path: Path to the solved-intervals JSON file.
		changed_frames: Set of frame_index ints that were modified.
	"""
	intervals_file = state_io.load_intervals(intervals_path)
	solved = intervals_file.get("solved_intervals", {})
	if not solved:
		return
	# extract frame indices from each fingerprint and check for overlap
	keys_to_remove = []
	for fp in solved:
		# fingerprint format: "frame|cx|cy|w|h|frame|cx|cy|w|h"
		parts = fp.split("|")
		# first frame index is parts[0], second is parts[5]
		start_fi = int(parts[0])
		end_fi = int(parts[5])
		if start_fi in changed_frames or end_fi in changed_frames:
			keys_to_remove.append(fp)
	if not keys_to_remove:
		print(f"  no solved intervals affected by {len(changed_frames)} changed seeds")
		return
	for key in keys_to_remove:
		del solved[key]
	intervals_file["solved_intervals"] = solved
	state_io.write_intervals(intervals_path, intervals_file)
	remaining = len(solved)
	print(f"  invalidated {len(keys_to_remove)} solved intervals "
		f"({remaining} remaining)")


#============================================
def _resolve_workers(args: argparse.Namespace) -> int:
	"""Resolve worker count from args or auto-detect.

	Args:
		args: Parsed argparse namespace.

	Returns:
		Number of workers to use.
	"""
	cpu_count = os.cpu_count()
	num_workers = getattr(args, "workers", None)
	if num_workers is None:
		num_workers = max(1, cpu_count // 2)
	print(f"  workers: {num_workers} (of {cpu_count} CPUs)")
	return num_workers


#============================================
def _load_and_deduplicate_seeds(seeds_path: str) -> list:
	"""Load seeds from disk and deduplicate by frame_index.

	Keeps latest pass when duplicates exist at the same frame.

	Args:
		seeds_path: Path to the seeds JSON file.

	Returns:
		Deduplicated list of seed dicts sorted by frame_index.
	"""
	seeds_data = state_io.load_seeds(seeds_path)
	seeds = seeds_data.get("seeds", [])
	if not seeds:
		return seeds
	# deduplicate: keep latest pass per frame
	seen_frames = {}
	for seed in seeds:
		fi = int(seed["frame_index"])
		if fi in seen_frames:
			existing = seen_frames[fi]
			if int(seed.get("pass", 1)) >= int(existing.get("pass", 1)):
				seen_frames[fi] = seed
		else:
			seen_frames[fi] = seed
	if len(seen_frames) < len(seeds):
		dropped = len(seeds) - len(seen_frames)
		print(f"  removed {dropped} duplicate seeds")
		seeds = sorted(seen_frames.values(), key=lambda s: int(s["frame_index"]))
		# write cleaned seeds back to disk
		seeds_data_out = {
			state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
			"seeds": seeds,
		}
		state_io.write_seeds(seeds_path, seeds_data_out)
		print(f"  saved {len(seeds)} deduplicated seeds")
	return seeds


#============================================
def _save_seeds_to_disk(seeds: list, seeds_path: str) -> None:
	"""Write seeds list to disk with proper header.

	Args:
		seeds: List of seed dicts.
		seeds_path: Output file path.
	"""
	seeds_data = {
		state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
		"seeds": seeds,
	}
	state_io.write_seeds(seeds_path, seeds_data)


#============================================
def _make_save_callback(seeds_path: str) -> object:
	"""Build an incremental save callback for crash-safe seed saving.

	Args:
		seeds_path: Path to the seeds JSON file.

	Returns:
		Callable that accepts a seeds list and writes it to disk.
	"""
	def _save(seeds_list: list) -> None:
		"""Write seeds to disk after each new seed is collected."""
		_save_seeds_to_disk(seeds_list, seeds_path)
	return _save


#============================================
def _validate_usable_seeds(seeds: list) -> tuple:
	"""Validate that enough usable seeds exist for solving.

	Args:
		seeds: List of seed dicts.

	Returns:
		Tuple of (usable_seeds, visible_count, partial_count).

	Raises:
		RuntimeError: If fewer than 2 usable seeds exist.
	"""
	usable_seeds = [
		s for s in seeds
		if s.get("status", "visible") in ("visible", "partial")
	]
	visible_count = sum(
		1 for s in usable_seeds
		if s.get("status", "visible") == "visible"
	)
	partial_count = sum(
		1 for s in usable_seeds if s.get("status") == "partial"
	)
	if len(usable_seeds) < 2:
		raise RuntimeError(
			f"need at least 2 usable seeds (visible or partial); "
			f"got {len(usable_seeds)} ({len(seeds)} total)"
		)
	# log absence seed counts if any exist
	not_in_frame_count = sum(
		1 for s in seeds if s.get("status") == "not_in_frame"
	)
	obstructed_count = sum(
		1 for s in seeds if s.get("status") == "obstructed"
	)
	if not_in_frame_count > 0 or obstructed_count > 0 or partial_count > 0:
		print(f"  seed status breakdown: "
			f"{visible_count} visible, {partial_count} partial, "
			f"{not_in_frame_count} not_in_frame, {obstructed_count} obstructed")
	return (usable_seeds, visible_count, partial_count)


#============================================
def _run_solve(
	args: argparse.Namespace,
	cfg: dict,
	seeds: list,
	video_info: dict,
	intervals_path: str,
	diag_path: str,
	num_workers: int,
	on_interval_complete: object = None,
) -> dict:
	"""Run the interval solver and write diagnostics.

	Args:
		args: Parsed argparse namespace.
		cfg: Configuration dict.
		seeds: List of seed dicts for solving.
		video_info: Video metadata dict.
		intervals_path: Path to solved-intervals file.
		diag_path: Path to write diagnostics.
		num_workers: Number of parallel workers.
		on_interval_complete: Optional callback for each solved interval.

	Returns:
		Diagnostics dict from solve_all_intervals().
	"""
	fps = video_info["fps"]
	usable_seeds, _, _ = _validate_usable_seeds(seeds)
	print(f"running interval solver "
		f"({len(usable_seeds)} usable seeds, {num_workers} workers)...")
	t_solve_start = time.time()
	prior_ivs, on_solved_cb = _load_prior_results(intervals_path)
	# build solver kwargs
	solve_kwargs = {
		"num_workers": num_workers,
		"debug": args.debug,
		"prior_intervals": prior_ivs,
		"on_interval_solved": on_solved_cb,
	}
	if on_interval_complete is not None:
		solve_kwargs["on_interval_complete"] = on_interval_complete
	with encoder.VideoReader(args.input_file) as reader:
		diagnostics = interval_solver.solve_all_intervals(
			reader, seeds,
			detection.create_detector(cfg),
			cfg, **solve_kwargs,
		)
	diagnostics["fps"] = fps
	t_solve_elapsed = time.time() - t_solve_start
	print(f"  solve complete ({t_solve_elapsed:.1f}s)")
	# write diagnostics to disk
	state_io.write_solver_diagnostics(diagnostics, diag_path, fps)
	print(f"  diagnostics written to {diag_path}")
	_print_quality_summary(diagnostics, fps)
	return diagnostics


#============================================
def _mode_seed(
	args: argparse.Namespace,
	cfg: dict,
	video_info: dict,
	seeds_path: str,
) -> None:
	"""Seed collection mode: collect seeds and save.

	Args:
		args: Parsed argparse namespace.
		cfg: Configuration dict.
		video_info: Video metadata dict.
		seeds_path: Path to the seeds JSON file.
	"""
	# parse optional time range
	time_range = _parse_time_range(args.time_range)
	# load existing seeds
	seeds_data = state_io.load_seeds(seeds_path)
	existing_seeds = seeds_data.get("seeds", [])
	# determine pass number
	if existing_seeds:
		print(f"loaded {len(existing_seeds)} existing seeds from {seeds_path}")
		existing_passes = [s.get("pass", 1) for s in existing_seeds]
		pass_number = max(existing_passes) + 1
	else:
		pass_number = 1
	# seed collection
	print(f"launching seed collection (pass {pass_number})...")
	seeds = seeding.collect_seeds(
		args.input_file,
		args.seed_interval,
		cfg,
		pass_number=pass_number,
		existing_seeds=existing_seeds if existing_seeds else None,
		frame_count_override=video_info["frame_count"],
		debug=args.debug,
		save_callback=_make_save_callback(seeds_path),
		time_range=time_range,
	)
	if not seeds:
		raise RuntimeError("no seeds collected")
	_save_seeds_to_disk(seeds, seeds_path)
	print(f"saved {len(seeds)} seeds to {seeds_path}")


#============================================
def _mode_edit(
	args: argparse.Namespace,
	cfg: dict,
	video_info: dict,
	seeds_path: str,
	diag_path: str,
	intervals_path: str,
) -> None:
	"""Seed editor mode: review/fix/delete existing seeds interactively.

	Args:
		args: Parsed argparse namespace.
		cfg: Configuration dict.
		video_info: Video metadata dict.
		seeds_path: Path to the seeds JSON file.
		diag_path: Path to diagnostics JSON file.
		intervals_path: Path to solved-intervals JSON file.
	"""
	seeds = _load_and_deduplicate_seeds(seeds_path)
	if not seeds:
		raise RuntimeError(f"no seeds to edit in {seeds_path}")
	print(f"loaded {len(seeds)} seeds from {seeds_path}")

	# back up seeds file before editing
	backup_path = seeds_path + ".bak"
	shutil.copy2(seeds_path, backup_path)
	print(f"  backup saved to {backup_path}")

	# build predictions and seed confidences from diagnostics if available
	predictions = None
	seed_confidences = None
	if os.path.isfile(diag_path):
		diag_data = state_io.load_diagnostics(diag_path)
		# try diagnostics file first (may lack per-frame tracks)
		if diag_data.get("intervals"):
			predictions = _build_predictions_from_diagnostics(diag_data)
			if predictions:
				print(f"  loaded predictions for {len(predictions)} frames")
			# compute seed confidence scores from interval diagnostics
			seed_confidences = scoring.compute_seed_confidences(
				seeds, diag_data.get("intervals", []),
			)
			if seed_confidences:
				print(f"  computed confidence for {len(seed_confidences)} seeds")

	# fallback: load predictions from solved intervals (has per-frame tracks)
	if not predictions and os.path.isfile(intervals_path):
		intervals_file = state_io.load_intervals(intervals_path)
		solved_intervals = intervals_file.get("solved_intervals", {})
		if solved_intervals:
			intervals_list = list(solved_intervals.values())
			predictions = _build_predictions_from_diagnostics(
				{"intervals": intervals_list}
			)
			if predictions:
				print(f"  loaded predictions for {len(predictions)} frames (from solved intervals)")

	# optionally filter by severity (show only seeds near weak intervals)
	frame_filter = None
	severity = getattr(args, "severity", None)
	if severity is not None and os.path.isfile(diag_path):
		fps = video_info["fps"]
		diag_data = state_io.load_diagnostics(diag_path)
		intervals = diag_data.get("intervals", [])
		# collect frame ranges from weak intervals at the severity threshold
		weak_frames = set()
		for iv in intervals:
			score = iv.get("interval_score", iv)
			confidence = score.get("confidence", "low")
			if confidence == "high":
				continue
			sev = review.classify_interval_severity(iv, fps)
			# include if severity meets threshold
			include = False
			if severity == "low":
				include = True
			elif severity == "medium" and sev in ("medium", "high"):
				include = True
			elif severity == "high" and sev == "high":
				include = True
			if include:
				start_f = int(iv.get("start_frame", 0))
				end_f = int(iv.get("end_frame", 0))
				# include seeds within the weak interval range
				for seed in seeds:
					fi = int(seed.get("frame_index", -1))
					if start_f <= fi <= end_f:
						weak_frames.add(fi)
		if weak_frames:
			frame_filter = weak_frames
			print(f"  severity filter: {len(weak_frames)} seeds near "
				f"{severity}+ severity intervals")
		else:
			print(f"  no seeds match severity={severity} filter, showing all")

	# run the editor
	edited_seeds, summary = seed_editor.edit_seeds(
		args.input_file, seeds, cfg,
		predictions=predictions,
		frame_filter=frame_filter,
		seed_confidences=seed_confidences,
		debug=args.debug,
	)

	# save if changes were made
	changes = summary["redrawn"] + summary["deleted"] + summary["status_changed"]
	if changes > 0:
		_save_seeds_to_disk(edited_seeds, seeds_path)
		print(f"saved {len(edited_seeds)} seeds to {seeds_path}")
		# invalidate only solved intervals that touch changed seeds
		changed_frames = summary.get("changed_frames", set())
		if changed_frames and os.path.isfile(intervals_path):
			_invalidate_intervals_for_frames(intervals_path, changed_frames)
	else:
		print("no changes made")


#============================================
def _mode_target(
	args: argparse.Namespace,
	cfg: dict,
	video_info: dict,
	seeds_path: str,
	diag_path: str,
	intervals_path: str,
) -> None:
	"""Target mode: add seeds at weak interval frames with FWD/BWD overlays.

	Loads solved intervals and diagnostics, generates refinement targets
	filtered by severity, builds FWD/BWD predictions, and launches the
	interactive seed collection UI at those frames.

	Args:
		args: Parsed argparse namespace.
		cfg: Configuration dict.
		video_info: Video metadata dict.
		seeds_path: Path to the seeds JSON file.
		diag_path: Path to diagnostics JSON file.
		intervals_path: Path to solved-intervals JSON file.
	"""
	fps = video_info["fps"]
	# require diagnostics from a prior solve
	if not os.path.isfile(diag_path):
		raise RuntimeError(
			f"no diagnostics found at {diag_path}. "
			f"Run 'solve' or 'run' first to generate interval data."
		)
	diag_data = state_io.load_diagnostics(diag_path)
	if not diag_data.get("intervals"):
		raise RuntimeError("diagnostics file has no intervals")

	# load seeds
	seeds = _load_and_deduplicate_seeds(seeds_path)
	if not seeds:
		raise RuntimeError(f"no seeds found in {seeds_path}")
	print(f"loaded {len(seeds)} seeds from {seeds_path}")

	# back up seeds before modifying
	backup_path = seeds_path + ".bak"
	shutil.copy2(seeds_path, backup_path)
	print(f"  backup saved to {backup_path}")

	# generate refinement targets with optional severity filter
	severity = getattr(args, "severity", None)
	seed_interval = getattr(args, "seed_interval", 10.0)
	target_frames = review.generate_refinement_targets(
		diag_data,
		mode="suggested",
		seed_interval=int(seed_interval * fps),
		severity=severity,
	)
	if not target_frames:
		sev_label = f" at {severity}+ severity" if severity else ""
		print(f"  no weak intervals found{sev_label}")
		return

	# rank frames by severity (worst intervals first) and cap count
	# high ~40, medium ~80, low/none ~160
	_severity_caps = {"high": 40, "medium": 80, "low": 160}
	max_targets = _severity_caps.get(severity, 160)
	if len(target_frames) > max_targets:
		print(f"  {len(target_frames)} candidate frames, "
			f"taking {max_targets} worst (spread evenly)")
	target_frames = review.rank_target_frames_by_severity(
		diag_data, target_frames, max_count=max_targets,
	)

	sev_label = f" ({severity}+ severity)" if severity else ""
	print(f"  {len(target_frames)} target frames from weak intervals{sev_label}")

	# build FWD/BWD predictions from diagnostics
	predictions = _build_predictions_from_diagnostics(diag_data)
	# fallback to solved intervals if diagnostics lack per-frame tracks
	if not predictions and os.path.isfile(intervals_path):
		intervals_file = state_io.load_intervals(intervals_path)
		solved_intervals = intervals_file.get("solved_intervals", {})
		if solved_intervals:
			intervals_list = list(solved_intervals.values())
			predictions = _build_predictions_from_diagnostics(
				{"intervals": intervals_list}
			)
	if predictions:
		print(f"  loaded predictions for {len(predictions)} frames")

	# determine pass number
	existing_passes = [s.get("pass", 1) for s in seeds]
	next_pass = max(existing_passes) + 1 if existing_passes else 2

	# collect seeds at target frames with predictions overlay
	print(f"  collecting seeds at {len(target_frames)} weak interval frames...")
	updated_seeds = seeding.collect_seeds_at_frames(
		args.input_file,
		target_frames,
		cfg,
		pass_number=next_pass,
		mode="target_refine",
		existing_seeds=seeds,
		predictions=predictions,
		debug=args.debug,
		save_callback=_make_save_callback(seeds_path),
	)
	# save updated seeds
	new_count = len(updated_seeds) - len(seeds)
	_save_seeds_to_disk(updated_seeds, seeds_path)
	print(f"saved {len(updated_seeds)} seeds to {seeds_path} "
		f"({new_count} new)")


#============================================
def _mode_solve(
	args: argparse.Namespace,
	cfg: dict,
	video_info: dict,
	seeds_path: str,
	diag_path: str,
	intervals_path: str,
) -> None:
	"""Solve mode: run interval solver, write diagnostics, exit.

	Non-interactive: solves, writes diagnostics, prints quality summary.

	Args:
		args: Parsed argparse namespace.
		cfg: Configuration dict.
		video_info: Video metadata dict.
		seeds_path: Path to the seeds JSON file.
		diag_path: Path to diagnostics JSON file.
		intervals_path: Path to solved-intervals JSON file.
	"""
	seeds = _load_and_deduplicate_seeds(seeds_path)
	if not seeds:
		raise RuntimeError(f"no seeds found in {seeds_path}")
	print(f"loaded {len(seeds)} seeds from {seeds_path}")

	# clear existing solved intervals to force full re-solve
	if os.path.isfile(intervals_path):
		os.remove(intervals_path)
		print("  cleared solved intervals (full re-solve)")

	num_workers = _resolve_workers(args)
	_run_solve(
		args, cfg, seeds, video_info,
		intervals_path, diag_path, num_workers,
	)


#============================================
def _mode_refine(
	args: argparse.Namespace,
	cfg: dict,
	video_info: dict,
	seeds_path: str,
	diag_path: str,
	intervals_path: str,
) -> None:
	"""Refine mode: re-solve only changed intervals, reuse prior results.

	Requires existing solved intervals from a prior solve. Only
	intervals whose fingerprint changed (due to edited seeds) are
	re-solved; prior results are reused for unchanged intervals.

	Args:
		args: Parsed argparse namespace.
		cfg: Configuration dict.
		video_info: Video metadata dict.
		seeds_path: Path to the seeds JSON file.
		diag_path: Path to diagnostics JSON file.
		intervals_path: Path to solved-intervals JSON file.
	"""
	seeds = _load_and_deduplicate_seeds(seeds_path)
	if not seeds:
		raise RuntimeError(f"no seeds found in {seeds_path}")
	print(f"loaded {len(seeds)} seeds from {seeds_path}")
	if not os.path.isfile(intervals_path):
		raise RuntimeError(
			f"no solved intervals at {intervals_path}; run 'solve' first"
		)
	num_workers = _resolve_workers(args)
	_run_solve(
		args, cfg, seeds, video_info,
		intervals_path, diag_path, num_workers,
	)


#============================================
def _mode_encode(
	args: argparse.Namespace,
	cfg: dict,
	video_info: dict,
	diag_path: str,
) -> None:
	"""Encode mode: encode cropped video from existing diagnostics.

	Args:
		args: Parsed argparse namespace.
		cfg: Configuration dict.
		video_info: Video metadata dict.
		diag_path: Path to diagnostics JSON file.
	"""
	# apply aspect override
	if getattr(args, "aspect", None) is not None:
		cfg.setdefault("processing", {})
		cfg["processing"]["crop_aspect"] = args.aspect

	# load diagnostics
	if not os.path.isfile(diag_path):
		raise RuntimeError(
			f"no diagnostics found at {diag_path}; run 'solve' first"
		)
	diag_data = state_io.load_diagnostics(diag_path)
	trajectory = diag_data.get("trajectory", [])
	if not trajectory:
		raise RuntimeError("diagnostics contain no trajectory data")

	num_workers = _resolve_workers(args)

	# compute crop trajectory
	print("computing crop trajectory...")
	crop_rects = crop.trajectory_to_crop_rects(trajectory, video_info, cfg)

	# resolve output path
	output_file = getattr(args, "output_file", None)
	if output_file is not None:
		output_path = output_file
	else:
		stem, ext = os.path.splitext(args.input_file)
		output_path = f"{stem}_tracked{ext}"

	# compute output crop dimensions from first crop rect
	if crop_rects:
		first_crop = crop_rects[0]
		crop_w = first_crop[2]
		crop_h = first_crop[3]
	else:
		crop_h = video_info["height"] // 2
		crop_w = crop_h
	# ensure even dimensions for codec compatibility
	crop_w = crop_w - (crop_w % 2)
	crop_h = crop_h - (crop_h % 2)

	# read output codec settings from config
	proc_cfg = cfg.get("processing", {})
	video_codec = proc_cfg.get("video_codec", "libx264")
	crf_value = int(proc_cfg.get("crf", 18))

	# encode
	temp_video = output_path + ".tmp.mp4"
	workers_enc_label = f" ({num_workers} workers)" if num_workers > 1 else ""
	print(f"encoding cropped video: {crop_w}x{crop_h}{workers_enc_label}")
	t_encode_start = time.time()

	# build frame_states for debug overlay
	frame_states_for_debug = None
	if args.debug:
		frame_states_for_debug = []
		for i, state in enumerate(trajectory):
			if state is not None:
				debug_state = {
					"cx": state["cx"],
					"cy": state["cy"],
					"w": state["w"],
					"h": state["h"],
					"conf": state.get("conf", 0.5),
					"source": state.get("source", "propagated"),
					"frame_index": i,
					"bbox": (state["cx"], state["cy"], state["w"], state["h"]),
				}
			else:
				debug_state = None
			frame_states_for_debug.append(debug_state)

	if num_workers > 1:
		encoder.encode_cropped_video_parallel(
			args.input_file, crop_rects, temp_video,
			crop_w, crop_h,
			codec=video_codec, crf=crf_value,
			frame_states=frame_states_for_debug,
			debug=args.debug,
			workers=num_workers,
		)
	else:
		with encoder.VideoReader(args.input_file) as reader:
			encoder.encode_cropped_video(
				reader, crop_rects, temp_video,
				crop_w, crop_h,
				codec=video_codec, crf=crf_value,
				frame_states=frame_states_for_debug,
				debug=args.debug,
			)
	t_encode_elapsed = time.time() - t_encode_start
	print(f"  encode complete ({t_encode_elapsed:.1f}s)")

	# mux audio
	print("muxing audio...")
	t_mux_start = time.time()
	encoder.copy_audio(args.input_file, temp_video, output_path)
	t_mux_elapsed = time.time() - t_mux_start
	print(f"  mux complete ({t_mux_elapsed:.1f}s)")

	# clean up temp file
	keep_temp = getattr(args, "keep_temp", False)
	if not keep_temp and os.path.isfile(temp_video) and os.path.isfile(output_path):
		os.remove(temp_video)
	print(f"\noutput: {output_path}")


#============================================
def _mode_run(
	args: argparse.Namespace,
	cfg: dict,
	video_info: dict,
	seeds_path: str,
	diag_path: str,
	intervals_path: str,
) -> None:
	"""Full pipeline mode: seed -> solve -> refine -> encode.

	Args:
		args: Parsed argparse namespace.
		cfg: Configuration dict.
		video_info: Video metadata dict.
		seeds_path: Path to the seeds JSON file.
		diag_path: Path to diagnostics JSON file.
		intervals_path: Path to solved-intervals JSON file.
	"""
	fps = video_info["fps"]
	time_range = _parse_time_range(args.time_range)

	# apply aspect override
	if getattr(args, "aspect", None) is not None:
		cfg.setdefault("processing", {})
		cfg["processing"]["crop_aspect"] = args.aspect

	# initialize YOLO detector
	print("initializing YOLO detector...")
	det = detection.create_detector(cfg)

	# load saved seeds (or start fresh)
	seeds_data = state_io.load_seeds(seeds_path)
	existing_seeds = seeds_data.get("seeds", [])

	if existing_seeds:
		print(f"loaded {len(existing_seeds)} existing seeds from {seeds_path}")
		seeds = existing_seeds
	else:
		# seed collection pass
		pass_number = 1
		seed_interval = getattr(args, "seed_interval", 10.0)
		print(f"launching seed collection (pass {pass_number})...")
		seeds = seeding.collect_seeds(
			args.input_file,
			seed_interval,
			cfg,
			pass_number=pass_number,
			existing_seeds=None,
			frame_count_override=video_info["frame_count"],
			debug=args.debug,
			save_callback=_make_save_callback(seeds_path),
			time_range=time_range,
		)
		if not seeds:
			raise RuntimeError("no seeds collected; cannot proceed without seeds")
		_save_seeds_to_disk(seeds, seeds_path)
		print(f"saved {len(seeds)} seeds to {seeds_path}")

	# deduplicate seeds
	seeds = _load_and_deduplicate_seeds(seeds_path)
	_validate_usable_seeds(seeds)
	solver_seeds = seeds

	num_workers = _resolve_workers(args)

	# run interval solver with weak-interval tracking
	weak_queue = queue.Queue()
	seeds_added_during_solve = 0

	def _on_interval_complete(result: dict) -> None:
		"""Callback fired when each interval finishes solving."""
		score = result.get("interval_score", {})
		confidence = score.get("confidence", "low")
		if confidence != "high":
			weak_queue.put(result)

	usable_seeds, _, _ = _validate_usable_seeds(seeds)
	print(f"running interval solver "
		f"({len(usable_seeds)} usable seeds, {num_workers} workers)...")

	t_solve_start = time.time()
	prior_ivs, on_solved_cb = _load_prior_results(intervals_path)
	with encoder.VideoReader(args.input_file) as reader:
		diagnostics = interval_solver.solve_all_intervals(
			reader, solver_seeds, det, cfg,
			num_workers=num_workers, debug=args.debug,
			on_interval_complete=_on_interval_complete,
			prior_intervals=prior_ivs,
			on_interval_solved=on_solved_cb,
		)
	diagnostics["fps"] = fps
	t_solve_elapsed = time.time() - t_solve_start
	print(f"  solve complete ({t_solve_elapsed:.1f}s)")

	# report weak intervals
	weak_count_during_solve = weak_queue.qsize()
	if weak_count_during_solve > 0:
		print(f"  {weak_count_during_solve} weak intervals detected during solve")

	state_io.write_solver_diagnostics(diagnostics, diag_path, fps)
	print(f"  diagnostics written to {diag_path}")
	_print_quality_summary(diagnostics, fps)

	# prompt for immediate seed collection if weak intervals were found
	seed_interval = getattr(args, "seed_interval", 10.0)
	severity = getattr(args, "severity", None)
	interactive_refine = getattr(args, "interactive_refine", True)

	if weak_count_during_solve > 0 and interactive_refine:
		target_frames = review.generate_refinement_targets(
			diagnostics,
			mode="suggested",
			seed_interval=int(seed_interval * fps),
			severity=severity,
		)
		if target_frames:
			sev_label = f"{severity}+ severity " if severity is not None else ""
			prompt_msg = (
				f"  {weak_count_during_solve} weak intervals found "
				f"({len(target_frames)} {sev_label}seed targets). "
				f"Add seeds now? [Y/n]: "
			)
			answer = input(prompt_msg).strip().lower()
			if answer in ("", "y", "yes"):
				existing_passes = [s.get("pass", 1) for s in seeds]
				next_pass = max(existing_passes) + 1 if existing_passes else 2
				predictions = _build_predictions_from_diagnostics(diagnostics)
				print("  collecting seeds at weak intervals...")
				seeds = seeding.collect_seeds_at_frames(
					args.input_file,
					target_frames,
					cfg,
					pass_number=next_pass,
					mode="solve_refine",
					existing_seeds=seeds,
					predictions=predictions,
					debug=args.debug,
					save_callback=_make_save_callback(seeds_path),
				)
				seeds_added_during_solve = len(seeds) - len(solver_seeds)
				_save_seeds_to_disk(seeds, seeds_path)
				print(f"  saved {len(seeds)} seeds to {seeds_path}")
				if seeds_added_during_solve > 0:
					solver_seeds = seeds
					print(
						f"  {seeds_added_during_solve} new seeds added. "
						f"Re-solving with updated seeds..."
					)
					t_resolve_start = time.time()
					prior_ivs, on_solved_cb = _load_prior_results(intervals_path)
					with encoder.VideoReader(args.input_file) as reader:
						diagnostics = interval_solver.solve_all_intervals(
							reader, solver_seeds, det, cfg,
							num_workers=num_workers, debug=args.debug,
							prior_intervals=prior_ivs,
							on_interval_solved=on_solved_cb,
						)
					diagnostics["fps"] = fps
					t_resolve_elapsed = time.time() - t_resolve_start
					print(f"  re-solve complete ({t_resolve_elapsed:.1f}s)")
					state_io.write_solver_diagnostics(
						diagnostics, diag_path, fps,
					)
					_print_quality_summary(diagnostics, fps)

	# interactive refinement loop
	max_interactive_passes = 5
	interactive_pass = 0
	refine_arg = getattr(args, "refine", None)
	if refine_arg is None and interactive_refine:
		while interactive_pass < max_interactive_passes:
			if not review.needs_refinement(diagnostics):
				break
			target_frames = review.generate_refinement_targets(
				diagnostics,
				mode="suggested",
				seed_interval=int(seed_interval * fps),
				severity=severity,
			)
			if not target_frames:
				break
			intervals = diagnostics.get("intervals", [])
			weak_count = sum(
				1 for iv in intervals
				if iv.get("interval_score", {}).get("confidence", "low") != "high"
			)
			sev_label = f"{severity}+ severity " if severity is not None else ""
			prompt_msg = (
				f"Found {weak_count} weak intervals "
				f"({len(target_frames)} {sev_label}seed targets). "
				f"Add seeds now? [Y/n]: "
			)
			answer = input(prompt_msg).strip().lower()
			if answer not in ("", "y", "yes"):
				break
			interactive_pass += 1
			existing_passes = [s.get("pass", 1) for s in seeds]
			next_pass = max(existing_passes) + 1 if existing_passes else 2
			predictions = _build_predictions_from_diagnostics(diagnostics)
			print(f"interactive refinement pass {interactive_pass}...")
			seeds = seeding.collect_seeds_at_frames(
				args.input_file,
				target_frames,
				cfg,
				pass_number=next_pass,
				mode="interactive_refine",
				existing_seeds=seeds,
				predictions=predictions,
				debug=args.debug,
				save_callback=_make_save_callback(seeds_path),
			)
			_save_seeds_to_disk(seeds, seeds_path)
			print(f"  saved {len(seeds)} seeds to {seeds_path}")
			solver_seeds = seeds
			print("re-solving with updated seeds...")
			t_resolve_start = time.time()
			prior_ivs, on_solved_cb = _load_prior_results(intervals_path)
			with encoder.VideoReader(args.input_file) as reader:
				diagnostics = interval_solver.solve_all_intervals(
					reader, solver_seeds, det, cfg,
					prior_intervals=prior_ivs,
					on_interval_solved=on_solved_cb,
				)
			diagnostics["fps"] = fps
			t_resolve_elapsed = time.time() - t_resolve_start
			print(f"  re-solve complete ({t_resolve_elapsed:.1f}s)")
			state_io.write_solver_diagnostics(diagnostics, diag_path, fps)
			_print_quality_summary(diagnostics, fps)

	# explicit refinement pass
	if refine_arg is not None:
		ignore_diag = getattr(args, "ignore_diagnostics", False)
		should_refine = (
			ignore_diag or review.needs_refinement(diagnostics)
		)
		if not should_refine:
			print("all intervals trusted -- skipping refinement")
		else:
			print(f"refinement mode: {refine_arg}")
			gap_threshold = getattr(args, "gap_threshold", 8.0)
			gap_threshold_frames = int(gap_threshold * fps)
			target_frames = review.generate_refinement_targets(
				diagnostics,
				mode=refine_arg,
				seed_interval=int(seed_interval * fps),
				gap_threshold=gap_threshold_frames,
				time_range=time_range,
				severity=severity,
			)
			if not target_frames:
				print("no refinement targets identified")
			else:
				print(f"  {len(target_frames)} refinement target frames")
				existing_passes = [s.get("pass", 1) for s in seeds]
				next_pass = max(existing_passes) + 1 if existing_passes else 2
				predictions = _build_predictions_from_diagnostics(diagnostics)
				seeds = seeding.collect_seeds_at_frames(
					args.input_file,
					target_frames,
					cfg,
					pass_number=next_pass,
					mode=refine_arg.split(",")[0] + "_refine",
					existing_seeds=seeds,
					predictions=predictions,
					debug=args.debug,
					save_callback=_make_save_callback(seeds_path),
				)
				_save_seeds_to_disk(seeds, seeds_path)
				print(f"  saved {len(seeds)} seeds to {seeds_path}")
				solver_seeds = seeds
				print("re-solving with updated seeds...")
				t_resolve_start = time.time()
				prior_ivs, on_solved_cb = _load_prior_results(intervals_path)
				with encoder.VideoReader(args.input_file) as reader:
					diagnostics = interval_solver.solve_all_intervals(
						reader, solver_seeds, det, cfg,
						prior_intervals=prior_ivs,
						on_interval_solved=on_solved_cb,
					)
				diagnostics["fps"] = fps
				t_resolve_elapsed = time.time() - t_resolve_start
				print(f"  re-solve complete ({t_resolve_elapsed:.1f}s)")
				state_io.write_solver_diagnostics(diagnostics, diag_path, fps)
				_print_quality_summary(diagnostics, fps)

	# encode the cropped output
	_mode_encode(args, cfg, video_info, diag_path)


#============================================
def main() -> None:
	"""Main entry point for the track_runner v2 CLI."""
	t_total_start = time.time()
	args = parse_args()

	# validate input file exists
	if not os.path.isfile(args.input_file):
		raise RuntimeError(f"input file not found: {args.input_file}")

	# verify required external tools are available
	for tool in ("mediainfo", "ffprobe", "ffmpeg"):
		if shutil.which(tool) is None:
			raise RuntimeError(f"{tool} not found in PATH")

	# resolve config path
	config_path = args.config_file
	if config_path is None:
		config_path = config.default_config_path(args.input_file)

	# paths for seeds, diagnostics, and solved intervals
	seeds_path = state_io.default_seeds_path(args.input_file)
	diag_path = state_io.default_diagnostics_path(args.input_file)
	intervals_path = state_io.default_intervals_path(args.input_file)

	# handle --write-default-config: write and exit
	if args.write_default_config:
		cfg = config.default_config()
		config.write_config(config_path, cfg)
		print(f"wrote default config: {config_path}")
		return

	# load or create config
	if os.path.isfile(config_path):
		cfg = config.load_config(config_path)
	else:
		cfg = config.default_config()
		config.write_config(config_path, cfg)
		print(f"wrote default config: {config_path}")
	config.validate_config(cfg)

	# probe video metadata
	print(f"probing video: {args.input_file}")
	video_info = _probe_video(args.input_file)
	fps = video_info["fps"]
	print(f"  resolution: {video_info['width']}x{video_info['height']}")
	print(f"  fps:        {fps:.4f}")
	print(f"  frames:     {video_info['frame_count']}")
	print(f"  duration:   {video_info['duration_s']:.2f}s")

	# dispatch to mode function
	mode = args.mode
	if mode == "seed":
		_mode_seed(args, cfg, video_info, seeds_path)
	elif mode == "edit":
		_mode_edit(args, cfg, video_info, seeds_path, diag_path, intervals_path)
	elif mode == "target":
		_mode_target(args, cfg, video_info, seeds_path, diag_path, intervals_path)
	elif mode == "solve":
		_mode_solve(args, cfg, video_info, seeds_path, diag_path, intervals_path)
	elif mode == "refine":
		_mode_refine(args, cfg, video_info, seeds_path, diag_path, intervals_path)
	elif mode == "encode":
		_mode_encode(args, cfg, video_info, diag_path)
	elif mode == "run":
		_mode_run(args, cfg, video_info, seeds_path, diag_path, intervals_path)
	else:
		raise RuntimeError(f"unknown mode: {mode}")

	# print total elapsed time
	t_total_elapsed = time.time() - t_total_start
	print(f"total time: {t_total_elapsed:.1f}s")


#============================================
if __name__ == "__main__":
	main()
