#!/usr/bin/env python3

"""
Textual TUI wrapper for emwy renders.
"""

# Standard Library
import argparse
import os
import re
import shlex
import statistics
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
from rich.text import Text

# local repo modules
from emwylib.core.project import EmwyProject
from emwylib.core import utils

#============================================

NORD_COLORS = {
	'background': "#2E3440",
	'foreground': "#D8DEE9",
	'dim': "#4C566A",
	'header': "#88C0D0",
	'command': "#ECEFF4",
	'flags': "#81A1C1",
	'numbers': "#B48EAD",
	'paths': "#A3BE8C",
	'strings': "#EBCB8B",
	'error': "#BF616A",
}

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
		color: #88C0D0;
	}

	#metrics {
		height: 1fr;
	}

	#project_title {
		height: 1;
		color: #88C0D0;
	}

	#project_info {
		height: 1fr;
	}

	#footer_note {
		height: 1;
		color: #4C566A;
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
		self.command_durations = []
		self.cached_eta_seconds = None
		self.cached_total_estimate = None
		self.current_summary = ""
		self.start_time = None
		self.finish_time = None
		self.error_text = None
		self.output_file = None
		self.metrics_widget = None
		self.project_widget = None
		self.log_widget = None
		self.finished = False
		self.command_styles = self._build_command_styles()
		self.debug_mode = debug_log
		self.log_path = None
		self.log_lock = threading.Lock()
		if self.debug_mode:
			self.log_path = os.path.join(os.getcwd(), "emwy_tui.log")
			self._reset_log()
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
			self.call_from_thread(self._set_calculating_total)
			self.output_file = project.output.get('file')
			self.command_total = project._renderer._estimate_command_total()
			utils.set_command_total(self.command_total)
			self.call_from_thread(self._set_command_total_ready, self.command_total)
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
			self.log_widget.write(
				Text(f"error: {text}", style=f"bold {NORD_COLORS['error']}")
			)

	#============================
	def _finish(self) -> None:
		if self.log_widget is None or self.metrics_widget is None:
			return
		self.finished = True
		if self.start_time is not None and self.finish_time is None:
			self.finish_time = time.time() - self.start_time
		if self.error_text is None:
			if self.output_file is None:
				self.log_widget.write("complete")
				self._write_log("complete")
			else:
				self._write_complete_banner()
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
			prefix = utils.command_prefix(self.command_count, self.command_total)
			if prefix:
				self.log_widget.write("")
				self.log_widget.write(Text(prefix, style=f"bold {NORD_COLORS['header']}"))
			self.log_widget.write(self._highlight_command(command))
			self._write_log(f"start: {command}")
			self._update_metrics()
		if event_type == 'end' and event.get('returncode', 0) != 0:
			seconds = event.get('seconds')
			if isinstance(seconds, (int, float)):
				self.command_durations.append(seconds)
			self._update_eta_cache()
			code = event.get('returncode')
			self.log_widget.write(
				Text(f"error ({code}): {summary}", style=f"bold {NORD_COLORS['error']}")
			)
			self._write_log(f"error ({code}): {command}")
			self._update_metrics()
		if event_type == 'end' and event.get('returncode', 0) == 0:
			seconds = event.get('seconds', 0.0)
			if isinstance(seconds, (int, float)):
				self.command_durations.append(seconds)
			self._update_eta_cache()
			self._write_log(f"end ({seconds:.3f}s): {command}")
			self._update_metrics()

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
	def _reset_log(self) -> None:
		if not self.debug_mode or self.log_path is None:
			return
		with self.log_lock:
			with open(self.log_path, "w", encoding="utf-8"):
				return

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
		if self.start_time is None:
			elapsed = 0.0
		elif self.finished:
			elapsed = self.finish_time or (time.time() - self.start_time)
		else:
			elapsed = time.time() - self.start_time
		if self.finished:
			status = "done"
		elif self.error_text is not None:
			status = "failed"
		else:
			status = "running"
		eta_text = "N/A"
		if self.cached_eta_seconds is not None:
			eta_text = self._format_duration_estimate(self.cached_eta_seconds)
		elif self.command_total is not None:
			eta_text = "gathering samples"
		metrics = Text()
		status_style = NORD_COLORS['foreground']
		if status == "failed":
			status_style = NORD_COLORS['error']
		elif status == "done":
			status_style = NORD_COLORS['paths']
		metrics.append("Status: ", style=NORD_COLORS['dim'])
		metrics.append(status, style=status_style)
		metrics.append("\n")
		metrics.append("Elapsed: ", style=NORD_COLORS['dim'])
		metrics.append(self._format_duration(elapsed), style=NORD_COLORS['numbers'])
		if self.cached_total_estimate is not None:
			metrics.append(" / ", style=NORD_COLORS['dim'])
			metrics.append(
				self._format_duration_estimate(self.cached_total_estimate),
				style=NORD_COLORS['numbers'],
			)
			metrics.append(" (est)", style=NORD_COLORS['dim'])
		metrics.append("\n")
		metrics.append("Commands: ", style=NORD_COLORS['dim'])
		metrics.append(f"{self.command_count}", style=NORD_COLORS['numbers'])
		if self.command_total:
			metrics.append(f"/{self.command_total}", style=NORD_COLORS['numbers'])
		metrics.append(" | ETA: ", style=NORD_COLORS['dim'])
		eta_style = NORD_COLORS['numbers']
		if eta_text in ("N/A", "gathering samples"):
			eta_style = NORD_COLORS['dim']
		metrics.append(eta_text, style=eta_style)
		metrics.append("\n")
		metrics.append("Current: ", style=NORD_COLORS['dim'])
		metrics.append(self.current_summary, style=NORD_COLORS['foreground'])
		self.metrics_widget.update(metrics)

	#============================
	def _update_project_info(self) -> None:
		if self.project_widget is None:
			return
		project = Text()
		project.append("YAML: ", style=NORD_COLORS['dim'])
		project.append(self.yaml_file, style=NORD_COLORS['paths'])
		project.append("\n")
		output_value = self.output_override or self.output_file or "N/A"
		project.append("Output: ", style=NORD_COLORS['dim'])
		output_style = NORD_COLORS['paths']
		if output_value == "N/A":
			output_style = NORD_COLORS['dim']
		project.append(output_value, style=output_style)
		project.append("\n")
		cache_value = self.cache_dir or "default"
		project.append("Cache: ", style=NORD_COLORS['dim'])
		cache_style = NORD_COLORS['paths']
		if cache_value == "default":
			cache_style = NORD_COLORS['dim']
		project.append(cache_value, style=cache_style)
		project.append("\n")
		project.append("Keep temp: ", style=NORD_COLORS['dim'])
		project.append(
			"yes" if self.keep_temp else "no",
			style=NORD_COLORS['paths'] if self.keep_temp else NORD_COLORS['foreground'],
		)
		project.append("\n")
		project.append("Dry run: ", style=NORD_COLORS['dim'])
		project.append(
			"yes" if self.dry_run else "no",
			style=NORD_COLORS['paths'] if self.dry_run else NORD_COLORS['foreground'],
		)
		if self.debug_mode and self.log_path is not None:
			project.append("\n")
			project.append("Debug log: ", style=NORD_COLORS['dim'])
			project.append(self.log_path, style=NORD_COLORS['paths'])
		self.project_widget.update(project)

	#============================
	def _set_calculating_total(self) -> None:
		self.current_summary = "calculating command total"
		self.cached_eta_seconds = None
		self.cached_total_estimate = None
		if self.log_widget is not None:
			self.log_widget.write("Calculating command total...")
		self._write_log("calculating command total")
		self._update_metrics()

	#============================
	def _set_command_total_ready(self, total: int) -> None:
		if self.log_widget is not None:
			self.log_widget.write(f"Command total: {total}")
		self._write_log(f"command total: {total}")
		self._update_metrics()

	#============================
	def _build_command_styles(self) -> list:
		return [
			(re.compile(r"\bpcm_s16le\b|\blibx265\b|\blibx264\b|\baac\b|\bffv1\b"),
				NORD_COLORS['foreground']),
			(re.compile(r"--?[A-Za-z0-9][A-Za-z0-9_-]*"), NORD_COLORS['flags']),
			(re.compile(r"\b\d+\.\d+\b"), NORD_COLORS['numbers']),
			(re.compile(r"\b\d+\b(?!\.\d)"), NORD_COLORS['numbers']),
			(re.compile(r"'[^']*'|\"[^\"]*\""), NORD_COLORS['strings']),
			(re.compile(r"(?:/|~|\./|\.\./)[^\s'\"`]+"), NORD_COLORS['paths']),
		]

	#============================
	def _highlight_command(self, command: str):
		if command is None or command == "":
			return ""
		text = Text(command, style=f"bold {NORD_COLORS['command']}")
		for pattern, style in self.command_styles:
			for match in pattern.finditer(command):
				text.stylize(style, match.start(), match.end())
		return text

	#============================
	def _write_complete_banner(self) -> None:
		if self.log_widget is None:
			return
		lines = [
			"  ____ ___  __  __ ____  _     _____ _____ _____ _ ",
			" / ___/ _ \\|  \\/  |  _ \\| |   | ____|_   _| ____| |",
			"| |  | | | | |\\/| | |_) | |   |  _|   | | |  _| | |",
			"| |__| |_| | |  | |  __/| |___| |___  | | | |___|_|",
			" \\____\\___/|_|  |_|_|   |_____|_____| |_| |_____(_)",
		]
		self.log_widget.write("")
		for line in lines:
			self.log_widget.write(line)
		self._write_log("complete banner")

	#============================
	def _estimate_remaining_seconds(self):
		if self.command_total is None or self.command_total <= 0:
			return None
		if len(self.command_durations) == 0:
			return None
		remaining = self.command_total - self.command_count
		if remaining <= 0:
			return 0.0
		median = statistics.median(self.command_durations)
		stdev = statistics.pstdev(self.command_durations)
		expected_cmd = median + stdev
		if expected_cmd < 0:
			expected_cmd = 0.0
		return expected_cmd * (remaining + 3)

	#============================
	def _update_eta_cache(self) -> None:
		if self.command_total is None or self.command_total <= 0:
			self.cached_eta_seconds = None
			self.cached_total_estimate = None
			return
		if len(self.command_durations) < 8:
			self.cached_eta_seconds = None
			self.cached_total_estimate = None
			return
		eta_seconds = self._estimate_remaining_seconds()
		if eta_seconds is None:
			self.cached_eta_seconds = None
			self.cached_total_estimate = None
			return
		elapsed = time.time() - self.start_time if self.start_time else 0.0
		self.cached_eta_seconds = eta_seconds
		self.cached_total_estimate = elapsed + eta_seconds

	#============================
	def _format_duration(self, seconds: float) -> str:
		if seconds < 60:
			return f"{seconds:.1f}s"
		minutes = int(seconds // 60)
		remaining = seconds - (minutes * 60)
		seconds_text = f"{remaining:04.1f}"
		if seconds_text.startswith(" "):
			seconds_text = f"0{seconds_text[1:]}"
		if minutes < 60:
			return f"{minutes}m {seconds_text}s"
		hours = int(minutes // 60)
		minutes = minutes - (hours * 60)
		return f"{hours}h {minutes:02d}m {seconds_text}s"

	#============================
	def _format_duration_estimate(self, seconds: float) -> str:
		rounded = int(seconds)
		if seconds > rounded:
			rounded += 1
		if rounded < 60:
			return f"{rounded:d}s"
		minutes = rounded // 60
		remaining = rounded - (minutes * 60)
		if minutes < 60:
			return f"{minutes}m {remaining:02d}s"
		hours = minutes // 60
		minutes = minutes - (hours * 60)
		return f"{hours}h {minutes:02d}m {remaining:02d}s"

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
