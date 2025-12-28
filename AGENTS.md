# AGENTS

## Purpose
This document lists the autonomous and human collaborators that interact with the emwy codebase so contributors know who to ping when making changes.

## Agents
- **Maintainer**: Reviews architecture proposals, owns release approval, and keeps the roadmap aligned with user needs.
- **Automation**: Runs CI pipelines (lint, unit tests, sample renders) and reports regressions back to the maintainer.
- **Spec Author**: Curates the EMWY YAML specification and translates feature requests into actionable format updates.
- **Codex Assistant**: Provides implementation help inside the Codex CLI, following the PYTHON_STYLE guide and maintaining documentation.

## Codex Guidance (Future)
- Treat `timeline.segments` as the authoring surface; `playlists`/`stack` are compiled-only and should not appear in user-facing YAML.
- Preserve the playback/overlay split: `playback_styles` for speed, `overlay_text_styles` for overlay visuals, and overlay templates only in `timeline.overlays`.
- Keep `emwy_cli.py` as the primary CLI entry point and `emwy_tui.py` as the TUI display; mirror CLI behavior in `emwy_tui.py` where practical.

## Collaboration Flow
1. Spec Author proposes format changes in [docs/FORMAT.md](docs/FORMAT.md).
2. Maintainer prioritizes work in [docs/ROADMAP.md](docs/ROADMAP.md) and assigns tasks.
3. Codex Assistant implements the tasks, updating docs and code.
4. Automation validates the work and posts the results to pull requests.

## Coding Style
See Python coding style in docs/PYTHON_STYLE.md.
See Markdown style in docs/MARKDOWN_STYLE.md.
When making edits, document them in docs/CHANGELOG.md.
See repo style in docs/REPO_STYLE.md.
Agents may run programs in the tests folder, including smoke tests and pyflakes/mypy runner scripts.
