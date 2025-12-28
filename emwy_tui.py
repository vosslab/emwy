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
import traceback

script_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = script_dir
if os.path.basename(script_dir) == "tools":
	repo_root = os.path.dirname(script_dir)
if repo_root not in sys.path:
	sys.path.insert(0, repo_root)

# PIP3 modules
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import RichLog, Static

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
	parser.add_argument('-d', '--debug', dest='debug_log', action='store_true',
		help='write debug log to emwy_tui.log in the current directory')
	parser.set_defaults(keep_temp=False)
	args = parser.parse_args()
	return args

#============================================

class EmwyTuiApp(App):
	BINDINGS = [
		("q", "quit", "Quit"),
	]

	CSS = """
	#root {
		height: 1fr;
	}

	#top_row {
		height: 30%;
		min-height: 8;
	}

	#left_panel {
		width: 40%;
		height: 1fr;
		border: solid gray;
	}

	#right_panel {
		width: 60%;
		height: 1fr;
		border: solid gray;
	}

	#metrics_title {
		height: 1;
	}

	#metrics {
		height: 1fr;
	}

	#project_title {
		height: 1;
	}

	#project_info {
		height: 1fr;
	}

	#footer_note {
		height: 1;
	}

	#log {
		height: 1fr;
		border: solid gray;
	}
	"""

	def __init__(self, yaml_file: str, output_override: str = None,
		dry_run: bool = False, keep_temp: bool = False, cache_dir: str = None,
		debug_log: bool = False):
		super().__init__()
		self.yaml_file = yaml_file
		self.output_override = output_override
		self.dry_run = dry_run
		self.keep_temp = keep_temp
		self.cache_dir = cache_dir
		self.command_count = 0
		self.command_total = None
		self.current_summary = ""
		self.start_time = None
		self.error_text = None
		self.output_file = None
		self.metrics_widget = None
		self.project_widget = None
		self.log_widget = None
		self.finished = False
		self.debug_mode = debug_log
		self.log_path = None
		self.log_lock = threading.Lock()
		if self.debug_mode:
			self.log_path = os.path.join(os.getcwd(), "emwy_tui.log")
			self._write_log(f"debug log: {self.log_path}")

	#============================
	def compose(self) -> ComposeResult:
		yield Static("EMWY TUI", id="header")
		with Vertical(id="root"):
			with Horizontal(id="top_row"):
				with Vertical(id="left_panel"):
					yield Static("Dashboard", id="metrics_title")
					yield Static("", id="metrics")
					yield Static("Press q to quit", id="footer_note")
				with Vertical(id="right_panel"):
					yield Static("Project", id="project_title")
					yield Static("", id="project_info")
			yield RichLog(id="log", wrap=True, highlight=False)

	#============================
	def on_mount(self) -> None:
		self.metrics_widget = self.query_one("#metrics", Static)
		self.project_widget = self.query_one("#project_info", Static)
		self.log_widget = self.query_one(RichLog)
		self.start_time = time.time()
		self._update_project_info()
		if self.debug_mode and self.log_widget is not None and self.log_path is not None:
			self.log_widget.write(f"debug log: {self.log_path}")
		thread = threading.Thread(target=self._run_project, daemon=True)
		thread.start()
		self.set_interval(0.5, self._refresh_status)

	#============================
	def _refresh_status(self) -> None:
		self._update_metrics()

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
			self.command_total = project._renderer._estimate_command_total()
			utils.set_command_total(self.command_total)
			self.call_from_thread(self._update_project_info)
			project.run()
		except Exception as exc:
			self.call_from_thread(self._set_error, str(exc), traceback.format_exc())
		finally:
			utils.set_command_total(None)
			utils.clear_command_reporter()
			utils.set_quiet_mode(False)
			self.call_from_thread(self._finish)

	#============================
	def _set_error(self, text: str, trace_text: str = None) -> None:
		self.error_text = text
		if trace_text:
			self._write_log(trace_text)
		if self.log_widget is not None:
			self.log_widget.write(f"error: {text}")

	#============================
	def _finish(self) -> None:
		if self.log_widget is None or self.metrics_widget is None:
			return
		self.finished = True
		if self.error_text is None:
			if self.output_file is None:
				self.log_widget.write("complete")
				self._write_log("complete")
			else:
				self.log_widget.write(f"complete: {self.output_file}")
				self._write_log(f"complete: {self.output_file}")
		else:
			self.log_widget.write("complete with errors")
			self._write_log("complete with errors")
		self._update_metrics()

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
			self.command_count = event.get('index', self.command_count + 1)
			self.command_total = event.get('total', self.command_total)
			self.current_summary = summary
			self.log_widget.write(summary)
			self._write_log(f"start: {command}")
			self._update_metrics()
		if event_type == 'end' and event.get('returncode', 0) != 0:
			code = event.get('returncode')
			self.log_widget.write(f"error ({code}): {summary}")
			self._write_log(f"error ({code}): {command}")
		if event_type == 'end' and event.get('returncode', 0) == 0:
			seconds = event.get('seconds', 0.0)
			self._write_log(f"end ({seconds:.3f}s): {command}")

	#============================
	def _write_log(self, message: str) -> None:
		if not self.debug_mode or self.log_path is None:
			return
		timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
		line = f"[{timestamp}] {message}\n"
		with self.log_lock:
			with open(self.log_path, "a", encoding="utf-8") as handle:
				handle.write(line)

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

	#============================
	def _update_metrics(self) -> None:
		if self.metrics_widget is None:
			return
		elapsed = time.time() - self.start_time if self.start_time else 0.0
		elapsed_text = f"{elapsed:.1f}s"
		if self.finished:
			status = "done"
		elif self.error_text is not None:
			status = "failed"
		else:
			status = "running"
		command_line = f"{self.command_count}"
		if self.command_total:
			command_line = f"{self.command_count}/{self.command_total}"
		metrics = (
			f"Status: {status}\n"
			f"Elapsed: {elapsed_text}\n"
			f"Commands: {command_line}\n"
			f"Current: {self.current_summary}"
		)
		self.metrics_widget.update(metrics)

	#============================
	def _update_project_info(self) -> None:
		if self.project_widget is None:
			return
		lines = [
			f"YAML: {self.yaml_file}",
			f"Output: {self.output_override or self.output_file or 'N/A'}",
			f"Cache: {self.cache_dir or 'default'}",
			f"Keep temp: {'yes' if self.keep_temp else 'no'}",
			f"Dry run: {'yes' if self.dry_run else 'no'}",
		]
		if self.debug_mode and self.log_path is not None:
			lines.append(f"Debug log: {self.log_path}")
		self.project_widget.update("\n".join(lines))

#============================================

def main():
	args = parse_args()
	sys.argv = [arg for arg in sys.argv if arg not in ("-d", "--debug")]
	app = EmwyTuiApp(args.yamlfile,
		output_override=args.output_file,
		dry_run=args.dry_run,
		keep_temp=args.keep_temp,
		cache_dir=args.cache_dir,
		debug_log=args.debug_log)
	app.run()

#============================================

if __name__ == '__main__':
	main()
