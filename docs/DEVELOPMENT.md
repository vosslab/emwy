# Development guide

## Getting started
1. Install dependencies via [INSTALL.md](INSTALL.md).
2. Create a feature branch.
3. Run `pyflakes` and `pytest` before submitting pull requests.

## Coding standards
- Follow [PYTHON_STYLE.md](PYTHON_STYLE.md) (tabs only, `main()` entry point, type hints at function boundaries).
- Keep line length under 100 characters and prefer small, focused functions.
- Write docstrings using Google style.
- Media tool wrappers live under `emwylib/media` and should stay split by intent (extract, render, normalize, edit).
- Review [CODE_ARCHITECTURE.md](CODE_ARCHITECTURE.md) before making large refactors.

## Tests
- Place automated tests under `tests/` mirroring the package structure.
- Provide sample YAML files inside `samples/` when adding new format coverage.
- Update [CHANGELOG.md](CHANGELOG.md) when behavior changes.

## Pull requests
- Describe the motivation, approach, and any outstanding TODOs.
- Link issues or roadmap items.
- Ensure CI passes; failing builds will be blocked until fixed.
