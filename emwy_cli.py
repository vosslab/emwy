#!/usr/bin/env python3

# Standard Library
import os
import time
import argparse

# PIP3 modules
import yaml

# local repo modules
from emwylib.core.project import EmwyProject
from emwylib.core import utils

#============================================

def parse_args():
	"""
	Parse command-line arguments.
	"""
	parser = argparse.ArgumentParser(description="CLI Movie Editor")
	parser.add_argument('-y', '--yaml', dest='yamlfile', required=True,
		help='main yaml file that outlines the processing to do')
	parser.add_argument('-o', '--output', dest='output_file',
		help='override output file from yaml')
	parser.add_argument('-n', '--dry-run', dest='dry_run', action='store_true',
		help='validate only, do not render')
	parser.add_argument('-c', '--cache-dir', dest='cache_dir',
		help='directory for temporary render files')
	parser.add_argument('-k', '--keep-temp', dest='keep_temp',
		help='keep temporary render files', action='store_true')
	parser.add_argument('-K', '--no-keep-temp', dest='keep_temp',
		help='remove temporary render files', action='store_false')
	parser.add_argument('-p', '--dump-plan', dest='dump_plan', action='store_true',
		help='print compiled playlists after planning')
	parser.add_argument('-d', '--debug', dest='debug_log', action='store_true',
		help='write debug log to emwy_cli.log in the current directory')
	parser.set_defaults(keep_temp=False)
	args = parser.parse_args()
	return args

#============================================

def make_debug_reporter(log_path: str):
	"""
	Build a command reporter that logs events to a file and prints to stdout.
	"""
	def reporter(event: dict) -> None:
		event_type = event.get('event')
		command = event.get('command', '')
		index = event.get('index')
		total = event.get('total')
		timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
		if event_type == 'start':
			# print to stdout like the default runCmd path
			prefix = utils.command_prefix(index, total)
			if prefix:
				print("")
				rich_text = utils.highlight_command(prefix)
				if hasattr(rich_text, '__rich_console__'):
					from rich.console import Console
					console = Console()
					console.print(rich_text, style="bold cyan")
				else:
					print(prefix)
			rich_cmd = utils.highlight_command(command)
			if hasattr(rich_cmd, '__rich_console__'):
				from rich.console import Console
				console = Console()
				console.print(rich_cmd)
			else:
				print(command)
			# write to log
			with open(log_path, "a", encoding="utf-8") as handle:
				handle.write(f"[{timestamp}] start: {command}\n")
		elif event_type == 'end':
			returncode = event.get('returncode', 0)
			seconds = event.get('seconds', 0.0)
			if returncode != 0:
				# print error to stdout
				print(f"error ({returncode}): {command}")
				with open(log_path, "a", encoding="utf-8") as handle:
					handle.write(f"[{timestamp}] error ({returncode}): {command}\n")
			else:
				with open(log_path, "a", encoding="utf-8") as handle:
					handle.write(f"[{timestamp}] end ({seconds:.3f}s): {command}\n")
		elif event_type == 'warning':
			warning_msg = event.get('message', '')
			print(f"WARNING: {warning_msg}")
			with open(log_path, "a", encoding="utf-8") as handle:
				handle.write(f"[{timestamp}] warning: {warning_msg}\n")
				# write full detail to debug log only
				detail = event.get('detail')
				if detail:
					handle.write(f"[{timestamp}] warning detail:\n{detail}\n")
	return reporter

#============================================

def main():
	args = parse_args()
	log_path = None
	if args.debug_log:
		log_path = os.path.join(os.getcwd(), "emwy_cli.log")
		# reset the log file
		with open(log_path, "w", encoding="utf-8"):
			pass
		print(f"debug log: {log_path}")
		reporter = make_debug_reporter(log_path)
		utils.set_command_reporter(reporter)
	project = EmwyProject(args.yamlfile, output_override=args.output_file,
		dry_run=args.dry_run, keep_temp=args.keep_temp, cache_dir=args.cache_dir)
	if args.dump_plan:
		project.validate()
		plan = {
			'stack': project.stack,
			'playlists': project.playlists,
		}
		print(yaml.safe_dump(plan, sort_keys=False))
		return
	if args.debug_log:
		# set command total for progress tracking
		command_total = project._renderer._estimate_command_total()
		utils.set_command_total(command_total)
	project.run()
	if args.debug_log:
		utils.clear_command_reporter()
		utils.set_command_total(None)
		print(f"debug log written to: {log_path}")


if __name__ == '__main__':
	main()
