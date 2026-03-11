#!/usr/bin/env python3

"""
cli.py

CLI entry point for the track_runner tool.
Probes video metadata, loads or writes config, and runs the tracking pipeline.
"""

# Standard Library
import argparse
import os

# local repo modules
import config
import tools_common

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
		"--use-default-config", dest="use_default_config",
		action="store_true",
		help="Read the per-input default config file (error if missing)."
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
		"--write-debug-video", dest="write_debug_video",
		action="store_true",
		help="Write a debug visualization video."
	)
	parser.add_argument(
		"--keep-temp", dest="keep_temp", action="store_true",
		help="Keep temporary files under the cache directory."
	)
	parser.set_defaults(write_default_config=False)
	parser.set_defaults(use_default_config=False)
	parser.set_defaults(write_debug_video=False)
	parser.set_defaults(keep_temp=False)
	return parser.parse_args()

#============================================

def main() -> None:
	"""
	Main entry point for the track_runner CLI.
	"""
	args = parse_args()

	# validate input file
	tools_common.ensure_file_exists(args.input_file)

	# check required external dependencies
	tools_common.check_dependency("ffprobe")
	tools_common.check_dependency("ffmpeg")

	# resolve config path
	config_path = args.config_file
	if config_path is None:
		config_path = config.default_config_path(args.input_file)

	# handle --write-default-config: write and exit
	if args.write_default_config:
		cfg = config.default_config()
		config.write_config(config_path, cfg)
		print(f"wrote default config: {config_path}")
		return

	# load or create config
	if args.use_default_config:
		# must already exist
		cfg = config.load_config(config_path)
	elif args.config_file is not None:
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
	if args.write_debug_video:
		cfg.setdefault("settings", {})
		cfg["settings"].setdefault("experiment", {})
		cfg["settings"]["experiment"]["write_debug_video"] = True

	# probe video metadata
	print(f"probing video: {args.input_file}")
	video_info = tools_common.probe_video_stream(args.input_file)
	duration = tools_common.probe_duration_seconds(args.input_file)

	# display probe results
	print(f"  resolution: {video_info['width']}x{video_info['height']}")
	print(f"  fps:        {video_info['fps']:.4f} ({video_info['fps_fraction']})")
	print(f"  pix_fmt:    {video_info['pix_fmt']}")
	print(f"  duration:   {duration:.2f}s")

	# placeholder for the tracking loop
	print("Tracker loop not yet implemented")
	return

#============================================

if __name__ == "__main__":
	main()
