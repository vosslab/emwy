#!/usr/bin/env python3

"""
run_tool.py

Dispatcher for emwy_tools sub-packages. Lists available tools or
runs one by name, passing through any extra arguments.
"""

# Standard Library
import os
import sys
import subprocess
import argparse

# tool name -> (relative script path, one-line description)
TOOLS: dict = {
	"silence_annotator": (
		"silence_annotator/silence_annotator.py",
		"detect silence and emit EMWY v2 timeline YAML",
	),
	"stabilize_building": (
		"stabilize_building/stabilize_building.py",
		"global stabilize video and emit sidecar report",
	),
	"track_runner": (
		"track_runner/track_runner.py",
		"track a runner and produce cropped/reframed output",
	),
	"video_scruncher": (
		"video_scruncher/video_scruncher.py",
		"time-lapse video compression (not yet implemented)",
	),
}

#============================================
def print_tool_list() -> None:
	"""Print a formatted table of available tools to stdout."""
	print("Available emwy tools:\n")
	# find the longest tool name for alignment
	max_name = max(len(name) for name in TOOLS)
	for name, (script, description) in TOOLS.items():
		print(f"  {name:<{max_name}}  {description}")
	print(f"\nUsage: python {os.path.basename(__file__)} <tool_name> [-- tool_args...]")

#============================================
def parse_args() -> argparse.Namespace:
	"""Parse command-line arguments."""
	parser = argparse.ArgumentParser(
		description="Dispatcher for emwy_tools sub-packages.",
	)
	parser.add_argument(
		"tool_name", nargs="?", default=None,
		choices=list(TOOLS.keys()),
		help="tool to run (omit to list available tools)",
	)
	parser.add_argument(
		"tool_args", nargs=argparse.REMAINDER,
		help="arguments passed through to the selected tool",
	)
	args = parser.parse_args()
	return args

#============================================
def main() -> None:
	"""Dispatch to a tool or print the tool list."""
	args = parse_args()

	if args.tool_name is None:
		print_tool_list()
		return

	# resolve the tool script relative to this file
	tools_dir = os.path.dirname(os.path.abspath(__file__))
	rel_path, _description = TOOLS[args.tool_name]
	script_path = os.path.join(tools_dir, rel_path)

	if not os.path.isfile(script_path):
		print(f"Error: tool script not found: {script_path}", file=sys.stderr)
		sys.exit(1)

	# strip leading '--' separator if present
	passthrough = args.tool_args
	if passthrough and passthrough[0] == "--":
		passthrough = passthrough[1:]

	# run the tool script with the same interpreter
	cmd = [sys.executable, script_path] + passthrough
	result = subprocess.run(cmd)
	sys.exit(result.returncode)

#============================================
if __name__ == "__main__":
	main()
