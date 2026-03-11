import os
import subprocess

import pytest

# use git rev-parse per REPO_STYLE.md -- not derived from __file__
REPO_ROOT = subprocess.check_output(
	["git", "rev-parse", "--show-toplevel"],
	text=True,
).strip()
SKIP_ENV = "SKIP_REPO_HYGIENE"

# set PYTHONPATH so subprocesses (e.g. silence_annotator) can find shared modules
_emwy_tools_dir = os.path.join(REPO_ROOT, "emwy_tools")
_existing = os.environ.get("PYTHONPATH", "")
if _emwy_tools_dir not in _existing.split(os.pathsep):
	os.environ["PYTHONPATH"] = _emwy_tools_dir + os.pathsep + _existing if _existing else _emwy_tools_dir


#============================================
@pytest.fixture
def repo_root() -> str:
	"""
	Provide the repository root path.
	"""
	return REPO_ROOT


#============================================
def pytest_addoption(parser) -> None:
	"""
	Add repo hygiene options.
	"""
	group = parser.getgroup("repo-hygiene")
	group.addoption(
		"--no-ascii-fix",
		action="store_true",
		help="Disable auto-fix for ASCII compliance tests.",
	)


#============================================
@pytest.fixture
def skip_repo_hygiene() -> bool:
	"""
	Check whether repo hygiene tests should be skipped.
	"""
	return os.environ.get(SKIP_ENV) == "1"


#============================================
@pytest.fixture
def ascii_fix_enabled(request) -> bool:
	"""
	Check whether ASCII compliance auto-fix is enabled.
	"""
	return not request.config.getoption("--no-ascii-fix")
