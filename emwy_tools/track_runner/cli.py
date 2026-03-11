#!/usr/bin/env python3
"""CLI entry point for the track_runner tool v2.

Multi-pass orchestration: seed collection, interval solving, refinement,
crop trajectory computation, and video encoding.
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
import interval_solver
import review
import crop


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments for track_runner v2.

	Returns:
		Parsed argparse.Namespace.
	"""
	parser = argparse.ArgumentParser(
		description="track_runner v2: multi-pass runner tracking and crop tool."
	)
	parser.add_argument(
		"-i", "--input", dest="input_file", required=True,
		help="Input video file path.",
	)
	parser.add_argument(
		"-o", "--output", dest="output_file", default=None,
		help="Output video file path (auto-generated if not provided).",
	)
	parser.add_argument(
		"-c", "--config", dest="config_file", default=None,
		help="Config YAML file path.",
	)
	parser.add_argument(
		"--write-default-config", dest="write_default_config",
		action="store_true",
		help="Write the default config for this input and exit.",
	)
	parser.add_argument(
		"--seed-interval", dest="seed_interval", type=float, default=10.0,
		help="Interval in seconds between seed frames (default 10).",
	)
	parser.add_argument(
		"--aspect", dest="aspect", type=str, default=None,
		help="Override crop aspect ratio (e.g. '1:1', '16:9').",
	)
	parser.add_argument(
		"-d", "--debug", dest="debug", action="store_true",
		help="Enable debug video output with tracking overlays.",
	)
	parser.add_argument(
		"--keep-temp", dest="keep_temp", action="store_true",
		help="Keep temporary files after encoding.",
	)
	parser.add_argument(
		"-w", "--workers", dest="workers", type=int, default=None,
		help="Number of parallel workers for solving and encoding (default: half of CPU cores).",
	)
	parser.add_argument(
		"--refine", dest="refine", type=str, default=None,
		help=(
			"Refinement mode(s): 'suggested', 'interval', 'gap', or comma-separated "
			"combination. Run after initial solve to add seeds and re-solve."
		),
	)
	parser.add_argument(
		"--gap-threshold", dest="gap_threshold", type=float, default=8.0,
		help="Gap threshold in seconds for 'gap' refinement mode (default 8.0).",
	)
	parser.add_argument(
		"--time-range", dest="time_range", type=str, default=None,
		help=(
			"Limit refinement to time range 'START:END' in seconds, "
			"e.g. '30:120'."
		),
	)
	parser.add_argument(
		"--ignore-diagnostics", dest="ignore_diagnostics", action="store_true",
		help="Force re-seeding even where solver thinks intervals are fine.",
	)
	parser.add_argument(
		"--seed-only", dest="seed_only", action="store_true",
		help="Collect seeds (pass 1) and save, then exit before interval solving.",
	)
	parser.add_argument(
		"--no-interactive-refine", dest="interactive_refine",
		action="store_false",
		help="Disable interactive refinement prompt after solve.",
	)
	parser.set_defaults(
		write_default_config=False,
		debug=False,
		keep_temp=False,
		ignore_diagnostics=False,
		seed_only=False,
		interactive_refine=True,
	)
	return parser.parse_args()


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

	Args:
		time_range_str: String like '30:120' or None.

	Returns:
		Tuple (start_s, end_s) as floats, or None if input is None.

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
	start_s = float(parts[0])
	end_s = float(parts[1])
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
		print("  some intervals need refinement -- run with --refine=suggested")
	else:
		print("  all intervals trusted -- tracking quality is good")
	print("")


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

	# paths for seeds and diagnostics (derived from input file)
	seeds_path = state_io.default_seeds_path(args.input_file)
	diag_path = state_io.default_diagnostics_path(args.input_file)

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

	# apply CLI aspect override into config
	if args.aspect is not None:
		cfg.setdefault("processing", {})
		cfg["processing"]["crop_aspect"] = args.aspect

	# probe video metadata
	print(f"probing video: {args.input_file}")
	video_info = _probe_video(args.input_file)
	fps = video_info["fps"]
	print(f"  resolution: {video_info['width']}x{video_info['height']}")
	print(f"  fps:        {fps:.4f}")
	print(f"  frames:     {video_info['frame_count']}")
	print(f"  duration:   {video_info['duration_s']:.2f}s")

	# store fps in diagnostics dict for later use by review module
	fps_for_diag = fps

	# initialize YOLO detector
	print("initializing YOLO detector...")
	det = detection.create_detector(cfg)

	# load saved seeds (or start fresh)
	seeds_data = state_io.load_seeds(seeds_path)
	existing_seeds = seeds_data.get("seeds", [])

	if existing_seeds and not args.seed_only:
		print(f"loaded {len(existing_seeds)} existing seeds from {seeds_path}")
		seeds = existing_seeds
	else:
		# determine pass number from existing seeds
		if existing_seeds:
			print(f"loaded {len(existing_seeds)} existing seeds from {seeds_path}")
			existing_passes = [s.get("pass", 1) for s in existing_seeds]
			pass_number = max(existing_passes) + 1
		else:
			pass_number = 1
		# build incremental save callback to avoid losing seeds on crash
		def save_seeds_incrementally(seeds_list: list) -> None:
			"""Write seeds to disk after each new seed is collected."""
			data = {
				state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
				"seeds": seeds_list,
			}
			state_io.write_seeds(seeds_path, data)
		# seed collection: collect new seeds (appending to any existing)
		print(f"launching seed collection (pass {pass_number})...")
		seeds = seeding.collect_seeds(
			args.input_file,
			args.seed_interval,
			cfg,
			pass_number=pass_number,
			existing_seeds=existing_seeds if existing_seeds else None,
			frame_count_override=video_info["frame_count"],
			debug=args.debug,
			save_callback=save_seeds_incrementally,
		)
		if not seeds:
			raise RuntimeError("no seeds collected; cannot proceed without seeds")
		# save seeds to JSON
		seeds_data_out = {
			state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
			"seeds": seeds,
		}
		state_io.write_seeds(seeds_path, seeds_data_out)
		print(f"saved {len(seeds)} seeds to {seeds_path}")

	# deduplicate seeds by frame_index: keep latest pass, remove older duplicates
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
		print(f"  removed {dropped} duplicate seeds from {seeds_path}")
		seeds = sorted(seen_frames.values(), key=lambda s: int(s["frame_index"]))
		# write cleaned seeds back to disk
		seeds_data_out = {
			state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
			"seeds": seeds,
		}
		state_io.write_seeds(seeds_path, seeds_data_out)
		print(f"  saved {len(seeds)} deduplicated seeds")

	# early exit if --seed-only was requested
	if args.seed_only:
		print(f"seed-only mode: {len(seeds)} seeds saved, exiting before solve")
		return

	# validate: need at least 2 visible seeds for interval solving
	visible_seeds = [
		s for s in seeds if s.get("status", "visible") == "visible"
	]
	if len(visible_seeds) < 2:
		raise RuntimeError(
			f"need at least 2 visible seeds; "
			f"got {len(visible_seeds)} ({len(seeds)} total)"
		)

	# seeds already contain cx, cy, w, h, frame_index from _build_seed_dict()
	solver_seeds = seeds

	# resolve worker count (auto-detect if not specified)
	cpu_count = os.cpu_count()
	num_workers = args.workers
	if num_workers is None:
		num_workers = max(1, cpu_count // 2)
	print(f"  workers: {num_workers} (of {cpu_count} CPUs)")

	# run interval solver with weak-interval tracking callback
	print(f"running interval solver ({len(visible_seeds)} visible seeds, {num_workers} workers)...")
	# queue to collect weak interval results during solving
	weak_queue = queue.Queue()
	seeds_added_during_solve = 0

	def _on_interval_complete(result: dict) -> None:
		"""Callback fired when each interval finishes solving.

		Puts weak intervals on the queue for interactive seed requesting.
		"""
		score = result.get("interval_score", {})
		confidence = score.get("confidence", "low")
		if confidence != "high":
			weak_queue.put(result)

	t_solve_start = time.time()
	with encoder.VideoReader(args.input_file) as reader:
		diagnostics = interval_solver.solve_all_intervals(
			reader, solver_seeds, det, cfg,
			num_workers=num_workers, debug=args.debug,
			on_interval_complete=_on_interval_complete,
		)
	# inject fps for review module
	diagnostics["fps"] = fps_for_diag
	t_solve_elapsed = time.time() - t_solve_start
	print(f"  solve complete ({t_solve_elapsed:.1f}s)")

	# report weak intervals found during solve
	weak_count_during_solve = weak_queue.qsize()
	if weak_count_during_solve > 0:
		print(f"  {weak_count_during_solve} weak intervals detected during solve")

	# write diagnostics
	state_io.write_solver_diagnostics(diagnostics, diag_path, fps_for_diag)
	print(f"  diagnostics written to {diag_path}")

	# print per-interval summary (always)
	_print_quality_summary(diagnostics, fps_for_diag)

	# prompt for immediate seed collection if weak intervals were found
	if weak_count_during_solve > 0 and args.interactive_refine:
		target_frames = review.generate_refinement_targets(
			diagnostics,
			mode="suggested",
			seed_interval=int(args.seed_interval * fps_for_diag),
		)
		if target_frames:
			# check if user wants to add seeds right away
			prompt_msg = (
				f"  {weak_count_during_solve} weak intervals found "
				f"({len(target_frames)} seed targets). "
				f"Add seeds now? [Y/n]: "
			)
			answer = input(prompt_msg).strip().lower()
			if answer in ("", "y", "yes"):
				# determine pass number
				existing_passes = [s.get("pass", 1) for s in seeds]
				next_pass = max(existing_passes) + 1 if existing_passes else 2
				# build incremental save callback
				def _save_during_solve(seeds_list: list) -> None:
					"""Write seeds to disk during solve-time refinement."""
					data = {
						state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
						"seeds": seeds_list,
					}
					state_io.write_seeds(seeds_path, data)
				# collect seeds at target frames
				print("  collecting seeds at weak intervals...")
				seeds = seeding.collect_seeds_at_frames(
					args.input_file,
					target_frames,
					cfg,
					pass_number=next_pass,
					mode="solve_refine",
					existing_seeds=seeds,
					debug=args.debug,
					save_callback=_save_during_solve,
				)
				# count new seeds added
				seeds_added_during_solve = len(seeds) - len(solver_seeds)
				# save updated seeds
				seeds_data_out = {
					state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
					"seeds": seeds,
				}
				state_io.write_seeds(seeds_path, seeds_data_out)
				print(f"  saved {len(seeds)} seeds to {seeds_path}")
				# re-solve with updated seeds
				if seeds_added_during_solve > 0:
					solver_seeds = seeds
					print(
						f"  {seeds_added_during_solve} new seeds added. "
						f"Re-solving with updated seeds..."
					)
					t_resolve_start = time.time()
					with encoder.VideoReader(args.input_file) as reader:
						diagnostics = interval_solver.solve_all_intervals(
							reader, solver_seeds, det, cfg,
							num_workers=num_workers, debug=args.debug,
						)
					diagnostics["fps"] = fps_for_diag
					t_resolve_elapsed = time.time() - t_resolve_start
					print(f"  re-solve complete ({t_resolve_elapsed:.1f}s)")
					state_io.write_solver_diagnostics(
						diagnostics, diag_path, fps_for_diag,
					)
					_print_quality_summary(diagnostics, fps_for_diag)

	# interactive refinement loop: prompt user to add seeds at weak spots
	max_interactive_passes = 5
	interactive_pass = 0
	if args.refine is None and args.interactive_refine:
		while interactive_pass < max_interactive_passes:
			# check if refinement is needed
			if not review.needs_refinement(diagnostics):
				break
			# generate refinement targets
			target_frames = review.generate_refinement_targets(
				diagnostics,
				mode="suggested",
				seed_interval=int(args.seed_interval * fps_for_diag),
			)
			if not target_frames:
				break
			# count weak intervals for the prompt
			intervals = diagnostics.get("intervals", [])
			weak_count = sum(
				1 for iv in intervals
				if iv.get("interval_score", {}).get("confidence", "low") != "high"
			)
			# prompt the user
			prompt_msg = (
				f"Found {weak_count} weak intervals "
				f"({len(target_frames)} seed targets). "
				f"Add seeds now? [Y/n]: "
			)
			answer = input(prompt_msg).strip().lower()
			if answer not in ("", "y", "yes"):
				break
			interactive_pass += 1
			# determine pass number
			existing_passes = [s.get("pass", 1) for s in seeds]
			next_pass = max(existing_passes) + 1 if existing_passes else 2
			# build incremental save callback
			def _save_interactive(seeds_list: list) -> None:
				"""Write seeds to disk during interactive refinement."""
				data = {
					state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
					"seeds": seeds_list,
				}
				state_io.write_seeds(seeds_path, data)
			# collect seeds at target frames
			print(f"interactive refinement pass {interactive_pass}...")
			seeds = seeding.collect_seeds_at_frames(
				args.input_file,
				target_frames,
				cfg,
				pass_number=next_pass,
				mode="interactive_refine",
				existing_seeds=seeds,
				debug=args.debug,
				save_callback=_save_interactive,
			)
			# save updated seeds
			seeds_data_out = {
				state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
				"seeds": seeds,
			}
			state_io.write_seeds(seeds_path, seeds_data_out)
			print(f"  saved {len(seeds)} seeds to {seeds_path}")
			# re-solve with updated seeds
			solver_seeds = seeds
			print("re-solving with updated seeds...")
			t_resolve_start = time.time()
			with encoder.VideoReader(args.input_file) as reader:
				diagnostics = interval_solver.solve_all_intervals(
					reader, solver_seeds, det, cfg,
				)
			diagnostics["fps"] = fps_for_diag
			t_resolve_elapsed = time.time() - t_resolve_start
			print(f"  re-solve complete ({t_resolve_elapsed:.1f}s)")
			# write updated diagnostics
			state_io.write_solver_diagnostics(diagnostics, diag_path, fps_for_diag)
			# print updated quality summary
			_print_quality_summary(diagnostics, fps_for_diag)

	# refinement pass: if requested and tracking is not already perfect
	if args.refine is not None:
		should_refine = (
			args.ignore_diagnostics or review.needs_refinement(diagnostics)
		)
		if not should_refine:
			print("all intervals trusted -- skipping refinement")
		else:
			print(f"refinement mode: {args.refine}")
			# parse optional time range
			time_range = _parse_time_range(args.time_range)
			gap_threshold_frames = int(args.gap_threshold * fps_for_diag)
			# compute seed targets using review module
			target_frames = review.generate_refinement_targets(
				diagnostics,
				mode=args.refine,
				seed_interval=int(args.seed_interval * fps_for_diag),
				gap_threshold=gap_threshold_frames,
				time_range=time_range,
			)
			if not target_frames:
				print("no refinement targets identified")
			else:
				print(f"  {len(target_frames)} refinement target frames")
				# determine pass number from highest existing pass
				existing_passes = [s.get("pass", 1) for s in seeds]
				next_pass = max(existing_passes) + 1 if existing_passes else 2
				# build incremental save callback for refinement
				def save_refine_incrementally(seeds_list: list) -> None:
					"""Write seeds to disk after each refinement seed."""
					data = {
						state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
						"seeds": seeds_list,
					}
					state_io.write_seeds(seeds_path, data)
				# run refinement seed collection
				seeds = seeding.collect_seeds_at_frames(
					args.input_file,
					target_frames,
					cfg,
					pass_number=next_pass,
					mode=args.refine.split(",")[0] + "_refine",
					existing_seeds=seeds,
					debug=args.debug,
					save_callback=save_refine_incrementally,
				)
				# save updated seeds
				seeds_data_out = {
					state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
					"seeds": seeds,
				}
				state_io.write_seeds(seeds_path, seeds_data_out)
				print(f"  saved {len(seeds)} seeds to {seeds_path}")
				# re-solve with updated seeds
				solver_seeds = seeds
				print("re-solving with updated seeds...")
				t_resolve_start = time.time()
				with encoder.VideoReader(args.input_file) as reader:
					diagnostics = interval_solver.solve_all_intervals(
						reader, solver_seeds, det, cfg,
					)
				diagnostics["fps"] = fps_for_diag
				t_resolve_elapsed = time.time() - t_resolve_start
				print(f"  re-solve complete ({t_resolve_elapsed:.1f}s)")
				state_io.write_solver_diagnostics(diagnostics, diag_path, fps_for_diag)
				_print_quality_summary(diagnostics, fps_for_diag)

	# compute crop trajectory from final solved trajectory
	print("computing crop trajectory...")
	trajectory = diagnostics.get("trajectory", [])
	crop_rects = crop.trajectory_to_crop_rects(trajectory, video_info, cfg)

	# resolve output path
	if args.output_file is not None:
		output_path = args.output_file
	else:
		stem, ext = os.path.splitext(args.input_file)
		output_path = f"{stem}_tracked{ext}"

	# compute output crop dimensions from first crop rect
	if crop_rects:
		first_crop = crop_rects[0]
		crop_w = first_crop[2]
		crop_h = first_crop[3]
	else:
		# fallback: square crop at half height
		crop_h = video_info["height"] // 2
		crop_w = crop_h
	# ensure even dimensions for codec compatibility
	crop_w = crop_w - (crop_w % 2)
	crop_h = crop_h - (crop_h % 2)

	# read output codec settings from config
	proc_cfg = cfg.get("processing", {})
	video_codec = proc_cfg.get("video_codec", "libx264")
	crf_value = int(proc_cfg.get("crf", 18))

	# encode cropped output video (video only, no audio)
	temp_video = output_path + ".tmp.mp4"
	workers_enc_label = f" ({num_workers} workers)" if num_workers > 1 else ""
	print(f"encoding cropped video: {crop_w}x{crop_h}{workers_enc_label}")
	t_encode_start = time.time()
	# build frame_states list for debug overlay (use trajectory states)
	frame_states_for_debug = None
	if args.debug:
		frame_states_for_debug = []
		for i, state in enumerate(trajectory):
			if state is not None:
				# convert to encoder-compatible format
				debug_state = {
					"cx": state["cx"],
					"cy": state["cy"],
					"w": state["w"],
					"h": state["h"],
					"confidence": state.get("conf", 0.5),
					"source": state.get("source", "propagated"),
					"frame_index": i,
					"bbox": (state["cx"], state["cy"], state["w"], state["h"]),
				}
			else:
				debug_state = None
			frame_states_for_debug.append(debug_state)

	# use parallel encoding when multiple workers are available
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

	# mux audio from original input
	print("muxing audio...")
	t_mux_start = time.time()
	encoder.copy_audio(args.input_file, temp_video, output_path)
	t_mux_elapsed = time.time() - t_mux_start
	print(f"  mux complete ({t_mux_elapsed:.1f}s)")

	# clean up temp file unless --keep-temp
	if not args.keep_temp and os.path.isfile(temp_video) and os.path.isfile(output_path):
		os.remove(temp_video)

	# print total elapsed time
	t_total_elapsed = time.time() - t_total_start
	print(f"\noutput: {output_path}")
	print(f"total time: {t_total_elapsed:.1f}s")


#============================================
if __name__ == "__main__":
	main()
