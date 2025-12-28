#!/usr/bin/env python3

"""
Textual TUI wrapper for emwy renders.
"""

# Standard Library
import argparse
import os
import shlex
import sys
import threading
import time

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = script_dir
if os.path.basename(script_dir) == "tools":
	repo_root = os.path.dirname(script_dir)
if repo_root not in sys.path:
	sys.path.insert(0, repo_root)

# PIP3 modules
import textual.app
import textual.widgets

# local repo modules
from emwylib.core.project import EmwyProject
from emwylib.core import utils

#============================================

def parse_args():
	"""
	Parse command-line arguments.
	"""
	parser = argparse.ArgumentParser(description="emwy TUI wrapper")
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
	parser.set_defaults(keep_temp=False)
	args = parser.parse_args()
	return args

#============================================

class EmwyTuiApp(textual.app.App):
	BINDINGS = [
		("q", "quit", "Quit"),
	]

	CSS = """
	#status {
		padding: 1 2;
	}

	#log {
		height: 1fr;
		padding: 0 2;
	}
	"""

	def __init__(self, yaml_file: str, output_override: str = None,
		dry_run: bool = False, keep_temp: bool = False, cache_dir: str = None):
		super().__init__()
		self.yaml_file = yaml_file
		self.output_override = output_override
		self.dry_run = dry_run
		self.keep_temp = keep_temp
		self.cache_dir = cache_dir
		self.command_count = 0
		self.start_time = None
		self.error_text = None
		self.output_file = None
		self.status_widget = None
		self.log_widget = None

	#============================
	def compose(self):
		yield textual.widgets.Header()
		yield textual.widgets.Static("starting", id="status")
		yield textual.widgets.Log(id="log")
		yield textual.widgets.Footer()

	#============================
	def on_mount(self) -> None:
		self.status_widget = self.query_one("#status", textual.widgets.Static)
		self.log_widget = self.query_one("#log", textual.widgets.Log)
		self.start_time = time.time()
		thread = threading.Thread(target=self._run_project, daemon=True)
		thread.start()
		self.set_interval(0.5, self._refresh_status)

	#============================
	def _refresh_status(self) -> None:
		elapsed = time.time() - self.start_time if self.start_time else 0
		elapsed_text = f"{elapsed:.1f}s"
		if self.error_text is not None:
			status = f"failed after {elapsed_text}"
		else:
			status = f"running {self.command_count} commands in {elapsed_text}"
		if self.status_widget is not None:
			self.status_widget.update(status)

	#============================
	def _run_project(self) -> None:
		utils.set_quiet_mode(True)
		utils.set_command_reporter(self._report_command)
		try:
			project = EmwyProject(self.yaml_file,
				output_override=self.output_override,
				dry_run=self.dry_run,
				keep_temp=self.keep_temp,
				cache_dir=self.cache_dir)
			self.output_file = project.output.get('file')
			project.run()
		except Exception as exc:
			self.call_from_thread(self._set_error, str(exc))
		finally:
			utils.clear_command_reporter()
			utils.set_quiet_mode(False)
			self.call_from_thread(self._finish)

	#============================
	def _set_error(self, text: str) -> None:
		self.error_text = text
		if self.log_widget is not None:
			self.log_widget.write(f"error: {text}")

	#============================
	def _finish(self) -> None:
		if self.log_widget is None or self.status_widget is None:
			return
		if self.error_text is None:
			if self.output_file is None:
				self.log_widget.write("complete")
			else:
				self.log_widget.write(f"complete: {self.output_file}")
		else:
			self.log_widget.write("complete with errors")
		self.status_widget.update("done (press q to quit)")

	#============================
	def _report_command(self, event: dict) -> None:
		self.call_from_thread(self._handle_command_event, event)

	#============================
	def _handle_command_event(self, event: dict) -> None:
		if self.log_widget is None:
			return
		event_type = event.get('event')
		command = event.get('command', '')
		summary = self._summarize_command(command)
		if event_type == 'start':
			self.command_count += 1
			self.log_widget.write(summary)
		if event_type == 'end' and event.get('returncode', 0) != 0:
			code = event.get('returncode')
			self.log_widget.write(f"error ({code}): {summary}")

	#============================
	def _summarize_command(self, command: str) -> str:
		if command is None or command == "":
			return "command"
		try:
			parts = shlex.split(command)
		except ValueError:
			return command
		if len(parts) == 0:
			return command
		tool = os.path.basename(parts[0])
		output_file = None
		if "-o" in parts:
			index = parts.index("-o")
			if index + 1 < len(parts):
				output_file = parts[index + 1]
		if tool == "ffmpeg" and len(parts) > 1:
			output_file = parts[-1]
		if output_file is not None:
			output_file = os.path.basename(output_file)
			return f"{tool}: {output_file}"
		return f"{tool}: {command}"

#============================================

def main():
	args = parse_args()
	app = EmwyTuiApp(args.yamlfile,
		output_override=args.output_file,
		dry_run=args.dry_run,
		keep_temp=args.keep_temp,
		cache_dir=args.cache_dir)
	app.run()

#============================================

if __name__ == '__main__':
	main()
