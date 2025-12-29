#!/usr/bin/env python3

"""
Unit tests for emwy_tui metrics helpers.
"""

# Standard Library
import os
import sys
import types

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
	sys.path.insert(0, REPO_ROOT)

from emwy_tui import EmwyTuiApp

#============================================

def _make_app_stub() -> types.SimpleNamespace:
	"""
	Create a stub object for metrics helpers.
	"""
	stub = types.SimpleNamespace()
	stub.command_total = None
	stub.command_count = 0
	stub.command_durations = []
	return stub

#============================================

def test_format_duration_boundaries() -> None:
	"""
	Ensure duration formatting switches at minute/hour boundaries.
	"""
	stub = _make_app_stub()
	assert EmwyTuiApp._format_duration(stub, 12.4) == "12.4s"
	assert EmwyTuiApp._format_duration(stub, 60.0) == "1m 00.0s"
	assert EmwyTuiApp._format_duration(stub, 3661.2) == "1h 01m 01.2s"

#============================================

def test_estimate_remaining_seconds() -> None:
	"""
	Ensure estimated time uses median + stdev per command.
	"""
	stub = _make_app_stub()
	stub.command_total = 10
	stub.command_count = 4
	stub.command_durations = [1.0, 1.5, 2.5]
	eta = EmwyTuiApp._estimate_remaining_seconds(stub)
	assert pytest.approx(eta, rel=1e-3) == 19.112486080158
