"""Tests for the key_input module: RunControl, GracefulQuit, KeyInputReader."""

# Standard Library
import os
import sys
import unittest.mock

# PIP3 modules
import pytest

# local repo modules
import git_file_utils

REPO_ROOT = git_file_utils.get_repo_root()
sys.path.insert(0, os.path.join(REPO_ROOT, "emwy_tools", "track_runner"))
import key_input


#============================================
def test_run_control_initial_state():
	"""RunControl starts with quit_requested=False and paused=False."""
	rc = key_input.RunControl()
	assert rc.quit_requested is False
	assert rc.paused is False


#============================================
def test_run_control_request_quit():
	"""request_quit() sets the quit_requested flag."""
	rc = key_input.RunControl()
	rc.request_quit()
	assert rc.quit_requested is True


#============================================
def test_run_control_check_quit_raises():
	"""check_quit() raises GracefulQuit when quit_requested is True."""
	rc = key_input.RunControl()
	rc.request_quit()
	with pytest.raises(key_input.GracefulQuit):
		rc.check_quit()


#============================================
def test_run_control_check_quit_no_raise():
	"""check_quit() does nothing when quit_requested is False."""
	rc = key_input.RunControl()
	# should not raise
	rc.check_quit()


#============================================
def test_graceful_quit_is_exception():
	"""GracefulQuit is a subclass of Exception, not KeyboardInterrupt."""
	assert issubclass(key_input.GracefulQuit, Exception)
	assert not issubclass(key_input.GracefulQuit, KeyboardInterrupt)


#============================================
def test_key_input_reader_noop_when_not_tty():
	"""KeyInputReader.poll() returns None when stdin is not a TTY."""
	# in pytest, stdin is typically not a TTY
	with key_input.KeyInputReader() as reader:
		result = reader.poll()
		assert result is None


#============================================
def test_key_input_reader_context_manager():
	"""KeyInputReader enters and exits without error."""
	with key_input.KeyInputReader() as reader:
		assert reader is not None
	# after exit, old_settings should be cleared
	assert reader._old_settings is None


#============================================
def test_key_input_reader_exception_safety():
	"""KeyInputReader restores terminal even when exception occurs."""
	with pytest.raises(ValueError):
		with key_input.KeyInputReader() as reader:
			raise ValueError("test error")
	# terminal settings should be restored (old_settings cleared)
	assert reader._old_settings is None


#============================================
def test_handle_key_none():
	"""handle_key with None does nothing."""
	rc = key_input.RunControl()
	reader = key_input.KeyInputReader()
	# should not raise or change state
	key_input.handle_key(None, rc, reader)
	assert rc.quit_requested is False
	assert rc.paused is False


#============================================
def test_handle_key_q_sets_quit():
	"""handle_key with 'q' sets quit_requested."""
	rc = key_input.RunControl()
	reader = key_input.KeyInputReader()
	key_input.handle_key("q", rc, reader)
	assert rc.quit_requested is True


#============================================
def test_handle_key_Q_sets_quit():
	"""handle_key with 'Q' sets quit_requested."""
	rc = key_input.RunControl()
	reader = key_input.KeyInputReader()
	key_input.handle_key("Q", rc, reader)
	assert rc.quit_requested is True


#============================================
def test_handle_key_p_pauses():
	"""handle_key with 'p' pauses and waits for key."""
	rc = key_input.RunControl()
	reader = key_input.KeyInputReader()
	# mock wait_for_key to return immediately
	with unittest.mock.patch.object(reader, "wait_for_key", return_value="x"):
		key_input.handle_key("p", rc, reader)
	# after resume, paused should be False
	assert rc.paused is False


#============================================
def test_install_sigint_handler():
	"""install_sigint_handler sets quit flag on first call."""
	rc = key_input.RunControl()
	key_input.install_sigint_handler(rc)
	# simulate first Ctrl-C by calling the handler directly
	import signal
	handler = signal.getsignal(signal.SIGINT)
	handler(signal.SIGINT, None)
	assert rc.quit_requested is True
	# restore default handler
	key_input.restore_default_sigint()


#============================================
def test_install_sigint_handler_second_raises():
	"""Second Ctrl-C raises KeyboardInterrupt."""
	rc = key_input.RunControl()
	key_input.install_sigint_handler(rc)
	import signal
	handler = signal.getsignal(signal.SIGINT)
	# first call sets flag
	handler(signal.SIGINT, None)
	# second call should raise
	with pytest.raises(KeyboardInterrupt):
		handler(signal.SIGINT, None)
	# restore default handler
	key_input.restore_default_sigint()
