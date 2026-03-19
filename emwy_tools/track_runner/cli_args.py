"""Argparse setup functions for track_runner CLI.

Provides argument parser configuration for all track_runner subcommands.
"""

# Standard Library
import argparse

# local repo modules
import ui.base_controller as base_controller_module


#============================================
def _add_seed_interval_arg(parser: argparse.ArgumentParser) -> None:
	"""Register -I/--seed-interval on a subparser.

	Args:
		parser: Subparser to add the argument to.
	"""
	parser.add_argument(
		"-I", "--seed-interval", dest="seed_interval", type=float, default=10.0,
		help="Interval in seconds between seed frames (default 10).",
	)


#============================================
def _add_severity_arg(parser: argparse.ArgumentParser, help_text: str) -> None:
	"""Register -s/--severity on a subparser.

	Args:
		parser: Subparser to add the argument to.
		help_text: Help string describing the severity filter for this mode.
	"""
	parser.add_argument(
		"-s", "--severity", dest="severity", type=str, default=None,
		choices=("high", "medium", "low"),
		help=help_text,
	)


#============================================
def _add_encode_args(parser: argparse.ArgumentParser) -> None:
	"""Register encoding-related arguments on a subparser.

	Args:
		parser: Subparser to add arguments to.
	"""
	parser.add_argument(
		"-o", "--output", dest="output_file", default=None,
		help="Output video file path (auto-generated if not provided).",
	)
	parser.add_argument(
		"--aspect", dest="aspect", type=str, default=None,
		help="Override crop aspect ratio (e.g. '1:1', '16:9').",
	)
	parser.add_argument(
		"--keep-temp", dest="keep_temp", action="store_true",
		help="Keep temporary files after encoding.",
	)
	parser.add_argument(
		"-F", "--encode-filters", dest="encode_filters", type=str,
		default=None,
		help=(
			"Comma-separated filter pipeline for encode output "
			"(overrides config). Example: bilateral,hqdn3d"
		),
	)


#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments with subcommands for track_runner v2.

	Returns:
		Parsed argparse.Namespace with a 'mode' attribute.
	"""
	# Global options go on the main parser so they can precede the
	# subcommand: track_runner.py -i VIDEO seed --start 45
	parser = argparse.ArgumentParser(
		description="track_runner v2: multi-pass runner tracking and crop tool.",
		epilog=(
			"Global options (-i, -d, --time-range, etc.) must appear "
			"before the subcommand. "
			"Example: track_runner.py -i VIDEO seed --start 45"
		),
	)
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
			"Limit processing to time range in seconds "
			"(global option, must appear before the subcommand). "
			"Format: 'START:END', 'START:', or ':END'. "
			"Examples: '30:120', '200:'."
		),
	)
	parser.set_defaults(
		debug=False,
	)

	subparsers = parser.add_subparsers(dest="mode")

	# -- seed mode (interactive) --
	seed_parser = subparsers.add_parser(
		"seed", help="Collect seeds, save, and exit.",
	)
	_add_seed_interval_arg(seed_parser)
	base_controller_module.BaseAnnotationController.add_argparse_args(seed_parser)

	# -- edit mode (interactive) --
	edit_parser = subparsers.add_parser(
		"edit", help="Review/fix/delete existing seeds interactively.",
	)
	_add_severity_arg(edit_parser, "Filter seeds near weak intervals at this severity threshold.")
	base_controller_module.BaseAnnotationController.add_argparse_args(edit_parser)

	# -- target mode (interactive) --
	target_parser = subparsers.add_parser(
		"target", help="Add seeds at weak interval frames with FWD/BWD overlays.",
	)
	_add_severity_arg(target_parser, "Minimum severity of weak intervals to target.")
	_add_seed_interval_arg(target_parser)
	base_controller_module.BaseAnnotationController.add_argparse_args(target_parser)

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
	_add_encode_args(encode_parser)

	# -- analyze mode --
	analyze_parser = subparsers.add_parser(
		"analyze", help="Analyze crop path stability before encoding.",
	)
	analyze_parser.add_argument(
		"--aspect", dest="aspect", type=str, default=None,
		help="Override crop aspect ratio (e.g. '1:1', '16:9').",
	)

	args = parser.parse_args()
	# no subcommand given: print help and exit
	if args.mode is None:
		parser.print_help()
		raise SystemExit(0)
	return args
