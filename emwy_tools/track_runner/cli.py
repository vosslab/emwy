#!/usr/bin/env python3
"""CLI entry point for the track_runner tool v2.

Multi-pass orchestration: seed collection, interval solving, refinement,
crop trajectory computation, and video encoding.
"""

# Standard Library
import argparse
import os
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
		help="Number of parallel detection workers.",
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
	parser.set_defaults(
		write_default_config=False,
		debug=False,
		keep_temp=False,
		ignore_diagnostics=False,
	)
	return parser.parse_args()


#============================================
def _probe_video(input_file: str) -> dict:
	"""Probe video metadata using ffprobe.

	Args:
		input_file: Path to the input video file.

	Returns:
		Dict with keys: width, height, fps, frame_count, duration_s.

	Raises:
		RuntimeError: If ffprobe fails or cannot parse output.
	"""
	ffprobe_path = shutil.which("ffprobe")
	if ffprobe_path is None:
		raise RuntimeError("ffprobe not found in PATH")
	# query video stream properties
	cmd = [
		ffprobe_path,
		"-v", "error",
		"-select_streams", "v:0",
		"-show_entries",
		"stream=width,height,r_frame_rate,nb_frames,duration",
		"-of", "csv=p=0",
		input_file,
	]
	result = subprocess.run(cmd, capture_output=True, text=True)
	if result.returncode != 0:
		raise RuntimeError(
			f"ffprobe failed: {result.stderr.strip()}"
		)
	parts = result.stdout.strip().split(",")
	if len(parts) < 5:
		raise RuntimeError(
			f"ffprobe output unexpected format: {result.stdout!r}"
		)
	width = int(parts[0])
	height = int(parts[1])
	# fps may be a fraction like "30000/1001"
	fps_parts = parts[2].split("/")
	if len(fps_parts) == 2:
		fps = float(fps_parts[0]) / float(fps_parts[1])
	else:
		fps = float(fps_parts[0])
	# nb_frames may be "N/A"; fall back to duration * fps
	nb_frames_str = parts[3].strip()
	duration_str = parts[4].strip()
	if nb_frames_str.isdigit():
		frame_count = int(nb_frames_str)
		duration_s = frame_count / fps if fps > 0 else 0.0
	else:
		duration_s = float(duration_str) if duration_str not in ("N/A", "") else 0.0
		frame_count = int(duration_s * fps) if fps > 0 else 0
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
def _seeds_to_solver_format(seeds: list) -> list:
	"""Convert seeding-format seeds to interval_solver format.

	Seeding produces torso_box as [x, y, w, h] (top-left origin) and
	uses 'frame' as the key. The interval solver expects cx, cy, w, h
	(center origin) and 'frame_index'.

	Args:
		seeds: List of seed dicts from seeding module.

	Returns:
		List of seed dicts with cx, cy, w, h, frame_index keys added.
	"""
	converted = []
	for seed in seeds:
		out = dict(seed)
		# convert torso_box [x, y, w, h] to center format
		box = seed.get("torso_box", [0, 0, 0, 0])
		x, y, w, h = float(box[0]), float(box[1]), float(box[2]), float(box[3])
		out["cx"] = x + w / 2.0
		out["cy"] = y + h / 2.0
		out["w"] = w
		out["h"] = h
		# map frame -> frame_index
		out["frame_index"] = int(seed.get("frame", 0))
		converted.append(out)
	return converted


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

	# verify ffmpeg and ffprobe are available
	for tool in ("ffprobe", "ffmpeg"):
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

	if existing_seeds:
		print(f"loaded {len(existing_seeds)} existing seeds from {seeds_path}")
		seeds = existing_seeds
	else:
		# pass 1: initial seed collection
		print("launching initial seed collection (pass 1)...")
		seeds = seeding.collect_seeds(
			args.input_file,
			args.seed_interval,
			cfg,
			pass_number=1,
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

	# validate: need at least 2 visible seeds for interval solving
	visible_seeds = [
		s for s in seeds if s.get("status", "visible") == "visible"
	]
	if len(visible_seeds) < 2:
		raise RuntimeError(
			f"need at least 2 visible seeds; "
			f"got {len(visible_seeds)} ({len(seeds)} total)"
		)

	# convert seeds to solver format (torso_box -> cx/cy, frame -> frame_index)
	solver_seeds = _seeds_to_solver_format(seeds)

	# run interval solver
	print(f"running interval solver ({len(visible_seeds)} visible seeds)...")
	t_solve_start = time.time()
	with encoder.VideoReader(args.input_file) as reader:
		diagnostics = interval_solver.solve_all_intervals(
			reader, solver_seeds, det, cfg,
		)
	# inject fps for review module
	diagnostics["fps"] = fps_for_diag
	t_solve_elapsed = time.time() - t_solve_start
	print(f"  solve complete ({t_solve_elapsed:.1f}s)")

	# write diagnostics
	state_io.write_solver_diagnostics(diagnostics, diag_path, fps_for_diag)
	print(f"  diagnostics written to {diag_path}")

	# print per-interval summary (always)
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
				# run refinement seed collection
				seeds = seeding.collect_seeds_at_frames(
					args.input_file,
					target_frames,
					cfg,
					pass_number=next_pass,
					mode=args.refine.split(",")[0] + "_refine",
					existing_seeds=seeds,
				)
				# save updated seeds
				seeds_data_out = {
					state_io.SEEDS_HEADER_KEY: state_io.SEEDS_HEADER_VALUE,
					"seeds": seeds,
				}
				state_io.write_seeds(seeds_path, seeds_data_out)
				print(f"  saved {len(seeds)} seeds to {seeds_path}")
				# re-solve with updated seeds
				solver_seeds = _seeds_to_solver_format(seeds)
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
	print(f"encoding cropped video: {crop_w}x{crop_h}")
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
