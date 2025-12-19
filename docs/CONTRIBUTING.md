# Contributing Guide

## Getting Started
1. Install dependencies via `docs/INSTALL.md`.
2. Create a feature branch.
3. Run `pyflakes` and `pytest` before submitting pull requests.

## Coding Standards
- Follow `PYTHON_STYLE.md` (tabs only, `main()` entry point, type hints at function boundaries).
- Keep line length under 100 characters and prefer small, focused functions.
- Write docstrings using Google style.
- Media tool wrappers live under `emwylib/media` and should stay split by intent (extract, render, normalize, edit).

## Tests
- Place automated tests under `tests/` mirroring the package structure.
- Provide sample YAML files inside `samples/` when adding new format coverage.
- Update `docs/CHANGELOG.md` when behavior changes.

## Pull Requests
- Describe the motivation, approach, and any outstanding TODOs.
- Link issues or roadmap items.
- Ensure CI passes; failing builds will be blocked until fixed.
