import os
import subprocess
import sys

import pytest

# use git rev-parse per REPO_STYLE.md -- not derived from __file__
REPO_ROOT = subprocess.check_output(
	["git", "rev-parse", "--show-toplevel"],
	text=True,
).strip()
EMWY_TOOLS_DIR = os.path.join(REPO_ROOT, "emwy_tools")
TESTS_DIR = os.path.join(REPO_ROOT, "tests")

# add emwy_tools/ so shared modules (tools_common, emwy_yaml_writer) are importable
if EMWY_TOOLS_DIR not in sys.path:
	sys.path.insert(0, EMWY_TOOLS_DIR)
# add tests/ so git_file_utils is importable
if TESTS_DIR not in sys.path:
	sys.path.insert(0, TESTS_DIR)

# add sub-package directories so sibling imports work when loaded via package paths
# (e.g. track_runner.encoder doing "import tr_crop" needs track_runner/ on sys.path)
for subpkg in ("track_runner", "silence_annotator", "stabilize_building"):
	subpkg_dir = os.path.join(EMWY_TOOLS_DIR, subpkg)
	if os.path.isdir(subpkg_dir) and subpkg_dir not in sys.path:
		sys.path.insert(0, subpkg_dir)

# add emwy_tools/tests/ so tr_test_helpers is importable from test files
EMWY_TESTS_DIR = os.path.join(EMWY_TOOLS_DIR, "tests")
if EMWY_TESTS_DIR not in sys.path:
	sys.path.insert(0, EMWY_TESTS_DIR)


@pytest.fixture
def repo_root() -> str:
	return REPO_ROOT
