# AGENTS

## Purpose
This document lists the autonomous and human collaborators that interact with the emwy codebase so contributors know who to ping when making changes.

## Agents
- **Maintainer**: Reviews architecture proposals, owns release approval, and keeps the roadmap aligned with user needs.
- **Automation**: Runs CI pipelines (lint, unit tests, sample renders) and reports regressions back to the maintainer.
- **Spec Author**: Curates the EMWY YAML specification and translates feature requests into actionable format updates.
- **Codex Assistant**: Provides implementation help inside the Codex CLI, following the PYTHON_STYLE guide and maintaining documentation.

## Collaboration Flow
1. Spec Author proposes format changes in `docs/FORMAT.md`.
2. Maintainer prioritizes work in `docs/ROADMAP.md` and assigns tasks.
3. Codex Assistant implements the tasks, updating docs and code.
4. Automation validates the work and posts the results to pull requests.
