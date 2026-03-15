"""Keyboard input and signal handling for track_runner interactive controls.

Provides non-blocking key detection and graceful Ctrl-C handling so that
long-running solve and encode operations can be paused or quit without
losing already-computed progress.
"""

# Standard Library
import os
import sys
import time
import signal
import select


# module-level debug flag, set by callers to enable quit-chain tracing
QUIT_TRACE = False


#============================================
def _quit_trace(marker: str, **kwargs) -> None:
	"""Emit a timestamped quit-chain trace line when QUIT_TRACE is enabled.

	Args:
		marker: Trace marker name (e.g. KEY_POLL, KEY_HANDLE).
		**kwargs: Key-value pairs to include in the trace line.
	"""
	if not QUIT_TRACE:
		return
	pid = os.getpid()
	ts = time.time()
	parts = [f"{marker} pid={pid} t={ts:.3f}"]
	for k, v in kwargs.items():
		parts.append(f"{k}={v}")
	line = " ".join(parts)
	print(f"  [QUIT_TRACE] {line}", flush=True)


#============================================
class GracefulQuit(Exception):
	"""Raised when a graceful quit is requested during solve or encode."""
	pass


#============================================
class RunControl:
	"""Shared flag object for quit/pause state across solve and encode loops.

	Attributes:
		quit_requested: True when the user has pressed Q or Ctrl-C.
		paused: True while the run is paused (P key).
	"""

	def __init__(self) -> None:
		self.quit_requested = False
		self.paused = False
		self.quit_time = None

	def request_quit(self) -> None:
		"""Set the quit flag and record the time."""
		self.quit_requested = True
		if self.quit_time is None:
			import time
			self.quit_time = time.time()

	def quit_elapsed(self) -> float:
		"""Return seconds since quit was requested, or 0.0 if not requested.

		Returns:
			Elapsed seconds since request_quit() was called.
		"""
		if self.quit_time is None:
			return 0.0
		import time
		return time.time() - self.quit_time

	def check_quit(self) -> None:
		"""Raise GracefulQuit if quit has been requested.

		Raises:
			GracefulQuit: When quit_requested is True.
		"""
		if self.quit_requested:
			raise GracefulQuit("quit requested by user")


#============================================
class KeyInputReader:
	"""Context manager for non-blocking keyboard input in cbreak mode.

	On enter: saves terminal settings and sets cbreak mode for
	character-at-a-time input without echo.

	On exit: restores original terminal settings unconditionally.

	If stdin is not a TTY (piped input, CI), poll() always returns None.
	"""

	def __init__(self) -> None:
		self._old_settings = None
		self._is_tty = False

	def __enter__(self) -> "KeyInputReader":
		"""Enter cbreak mode if stdin is a TTY."""
		# stdin may not have fileno() in pytest or piped contexts
		try:
			fd = sys.stdin.fileno()
			self._is_tty = os.isatty(fd)
		except (AttributeError, OSError, ValueError):
			self._is_tty = False
		if self._is_tty:
			import termios
			import tty
			self._old_settings = termios.tcgetattr(sys.stdin)
			# set cbreak: character-at-a-time, no echo
			tty.setcbreak(sys.stdin.fileno())
		return self

	def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
		"""Restore original terminal settings and flush leftover input."""
		if self._old_settings is not None:
			import termios
			# flush any unread input so stray keypresses don't leak to the shell
			termios.tcflush(sys.stdin, termios.TCIFLUSH)
			termios.tcsetattr(
				sys.stdin, termios.TCSADRAIN, self._old_settings,
			)
			self._old_settings = None
		# do not suppress exceptions
		return False

	def poll(self) -> str | None:
		"""Non-blocking check for a keypress.

		Returns:
			Single character string if a key was pressed, None otherwise.
		"""
		if not self._is_tty:
			return None
		# zero-timeout select: returns immediately
		readable, _, _ = select.select([sys.stdin], [], [], 0)
		if readable:
			ch = sys.stdin.read(1)
			_quit_trace("KEY_POLL", ch=repr(ch))
			return ch
		return None

	def wait_for_key(self) -> str:
		"""Block until a key is pressed.

		Returns:
			Single character string of the key pressed.
		"""
		if not self._is_tty:
			# when not a TTY, return immediately with empty string
			return ""
		# blocking select: wait indefinitely
		select.select([sys.stdin], [], [])
		ch = sys.stdin.read(1)
		return ch


#============================================
def install_sigint_handler(run_control: RunControl) -> None:
	"""Install a SIGINT handler that sets the quit flag on first Ctrl-C.

	First Ctrl-C: sets run_control.quit_requested and prints a message.
	Second Ctrl-C: raises KeyboardInterrupt for force quit.

	Args:
		run_control: RunControl instance to flag on interrupt.
	"""
	# track whether first Ctrl-C has been received
	received = {"count": 0}

	def _handler(signum: int, frame: object) -> None:
		"""Handle SIGINT signal."""
		received["count"] += 1
		if received["count"] == 1:
			run_control.request_quit()
			_quit_trace("KEY_HANDLE", source="sigint", quit_requested=True)
			# print message directly (Rich may not be available here)
			print(
				"\n  Ctrl-C received, finishing current interval... "
				"(press Ctrl-C again to force quit)",
				flush=True,
			)
		else:
			# second Ctrl-C: force quit
			raise KeyboardInterrupt

	signal.signal(signal.SIGINT, _handler)


#============================================
def restore_default_sigint() -> None:
	"""Restore the default SIGINT handler."""
	signal.signal(signal.SIGINT, signal.default_int_handler)


#============================================
def handle_key(
	ch: str | None,
	run_control: RunControl,
	key_reader: KeyInputReader,
	progress: object = None,
) -> None:
	"""Process a polled key character for quit/pause behavior.

	Args:
		ch: Character from KeyInputReader.poll(), or None.
		run_control: RunControl instance to update.
		key_reader: KeyInputReader for blocking wait during pause.
		progress: Optional Rich Progress instance for console output.
	"""
	if ch is None:
		return
	lower = ch.lower()
	if lower == "q":
		run_control.request_quit()
		_quit_trace("KEY_HANDLE", quit_requested=True)
		msg = "  Q pressed, finishing current interval..."
		if progress is not None:
			progress.console.print(msg)
		else:
			print(msg, flush=True)
	elif lower == "p":
		msg_pause = "  paused -- press any key to resume"
		if progress is not None:
			progress.console.print(msg_pause)
		else:
			print(msg_pause, flush=True)
		run_control.paused = True
		# block until any key is pressed
		key_reader.wait_for_key()
		run_control.paused = False
		msg_resume = "  resumed"
		if progress is not None:
			progress.console.print(msg_resume)
		else:
			print(msg_resume, flush=True)
