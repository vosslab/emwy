# File structure

This document describes the emwy repository layout and where different files
belong.

## Top-level layout

```
emwy/
+- AGENTS.md
+- Brewfile
+- CLAUDE.md
+- LICENSE
+- MANIFEST.in
+- README.md
+- emwy_cli.py
+- emwy_tui.py
+- pip_requirements.txt
+- pip_requirements-dev.txt
+- pyproject.toml
+- source_me.sh
+- devel/
+- docs/
+- emwylib/
+- emwy_tools/
+- samples/
+- tests/
`- tools/
```

Top-level highlights:

- [README.md](README.md): Project overview and quick start.
- [AGENTS.md](AGENTS.md): Agent workflow and coding guidance.
- [pyproject.toml](pyproject.toml): Packaging metadata and scripts.
- [pip_requirements.txt](pip_requirements.txt): Python dependencies.
- [source_me.sh](source_me.sh): Shell bootstrap (sets PYTHONPATH and environment).
- [emwy_cli.py](emwy_cli.py): Primary CLI entry point.
- [emwy_tui.py](emwy_tui.py): Textual TUI wrapper.

## Key subtrees

### Core library

Core pipeline code in [emwylib/](emwylib/):

```
emwylib/
  __init__.py
  version.py
  titlecard.py
  transforms.py
  ffmpeglib.py
  soxlib.py
  medialib.py
  core/
    __init__.py
    loader.py
    timeline.py
    renderer.py
    project.py
    utils.py
  media/
    __init__.py
    ffmpeg.py
    ffmpeg_extract.py
    ffmpeg_render.py
    sox.py
    sox_normalize.py
    sox_edit.py
  exporters/
    __init__.py
    mlt.py
```

### Tests

Tests and repo hygiene checks in [tests/](tests/):

```
tests/
  conftest.py
  check_ascii_compliance.py
  fix_ascii_compliance.py
  fix_whitespace.py
  font_utils.py
  git_file_utils.py
  render_titlecard.py
  test_ascii_compliance.py
  test_enabled_entries.py
  test_ffmpeg_overlays.py
  test_font_usage.py
  test_import_dot.py
  test_import_requirements.py
  test_import_star.py
  test_indentation.py
  test_init_files.py
  test_integration_render.py
  test_mlt_export.py
  test_playback_styles.py
  test_pyflakes_code_lint.py
  test_render_tooling.py
  test_shebangs.py
  test_speed_sync.py
  test_titlecard.py
  test_tui_metrics.py
  test_whitespace.py
```

Tool-specific tests in [emwy_tools/tests/](emwy_tools/tests/):

```
emwy_tools/tests/
  __init__.py
  conftest.py
  test_emwy_yaml_writer.py
  test_stabilize_building.py
  test_tools_common.py
  test_track_runner.py
```

### Tools

Helper scripts in [emwy_tools/](emwy_tools/):

```
emwy_tools/
  README.md
  run_tool.py
  tools_common.py
  emwy_yaml_writer.py
  config_silence.yml
  demo_codex.small.emwy.yaml
  tests/
  silence_annotator/
    __init__.py
    silence_annotator.py
    detection.py
    config.py
  stabilize_building/
    __init__.py
    stabilize_building.py
    stabilize.py
    crop.py
    config.py
  track_runner/
    __init__.py
    track_runner.py
    cli.py
    config.py
    crop.py
    detection.py
    encoder.py
    hypothesis.py
    interval_solver.py
    propagator.py
    review.py
    scoring.py
    seeding.py
    state_io.py
  video_scruncher/
    __init__.py
    video_scruncher.py
```

Standalone analysis scripts in [tools/](tools/):

```
tools/
  measure_seed_variability.py
  plot_seed_variability.py
```

### Development scripts

Release helpers in [devel/](devel/):

```
devel/
  commit_changelog.py
  submit_to_pypi.py
```

### Samples

Example projects in [samples/](samples/):

```
samples/
  gangnam.emwy.yaml
  runGangnam_v2.sh
  secret_of_51.emwy.yaml
```

## Generated artifacts

Ignored or regenerated outputs include:

- `report_*.txt`: Lint and analysis reports (git-ignored).
- `__pycache__/`, `*.pyc`: Python bytecode artifacts.
- `build/`, `dist/`, `*.egg-info/`: Packaging outputs.
- `.pytest_cache/`, `.mypy_cache/`: Test and type-check caches.
- `*.mkv`, `*.mp4`, `*.avi`: Video outputs (ignored by default).
- `output_smoke/`: Smoke test output directory.
- `TRACK_VIDEOS/`: Test video inputs (local only, not committed).

Temporary render files default to a per-run temp directory (see `--cache-dir` in
[docs/USAGE.md](docs/USAGE.md)).

## Documentation map

Documentation lives in [docs/](docs/):

- [docs/INSTALL.md](docs/INSTALL.md): System dependencies and install steps.
- [docs/USAGE.md](docs/USAGE.md): CLI workflows and example commands.
- [docs/TOOLS.md](docs/TOOLS.md): Tooling and helper scripts.
- [docs/DEBUGGING.md](docs/DEBUGGING.md): Common errors and diagnostics.
- [docs/COOKBOOK.md](docs/COOKBOOK.md): Editing recipes.
- [docs/FAQ.md](docs/FAQ.md): Common questions and design notes.
- [docs/EMWY_YAML_v1_SPEC.md](docs/EMWY_YAML_v1_SPEC.md): Legacy v1 spec.
- [docs/EMWY_YAML_v2_SPEC.md](docs/EMWY_YAML_v2_SPEC.md): Current v2 spec.
- [docs/FORMAT.md](docs/FORMAT.md): Project file overview.
- [docs/CLI.md](docs/CLI.md): CLI usage and flags.
- [docs/MLT_INTEROP.md](docs/MLT_INTEROP.md): EMWY and MLT mapping notes.
- [docs/EXPORT_MLT_XML_SPEC.md](docs/EXPORT_MLT_XML_SPEC.md): MLT export spec.
- [docs/IMPORT_MLT_XML_SPEC.md](docs/IMPORT_MLT_XML_SPEC.md): Draft import spec.
- [docs/SHOTCUT.md](docs/SHOTCUT.md): Shotcut compatibility notes.
- [docs/CODE_ARCHITECTURE.md](docs/CODE_ARCHITECTURE.md): Code layout and data flow.
- [docs/FILE_STRUCTURE.md](docs/FILE_STRUCTURE.md): Repository layout (this doc).
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md): Developer workflows.
- [docs/REPO_STYLE.md](docs/REPO_STYLE.md): Repo conventions.
- [docs/PYTHON_STYLE.md](docs/PYTHON_STYLE.md): Python coding conventions.
- [docs/MARKDOWN_STYLE.md](docs/MARKDOWN_STYLE.md): Documentation style.
- [docs/CHANGELOG.md](docs/CHANGELOG.md): User-facing change history.
- [docs/RELEASE_HISTORY.md](docs/RELEASE_HISTORY.md): Release log.
- [docs/ROADMAP.md](docs/ROADMAP.md): Planned work.
- [docs/TODO.md](docs/TODO.md): Backlog tasks.
- [docs/SECURITY.md](docs/SECURITY.md): Security notes.
- [docs/AUTHORS.md](docs/AUTHORS.md): Maintainers and contributors.
- [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md): Current v3 track
  runner spec (seed-driven interval solver with PySide6 UI).
- [docs/TRACK_RUNNER_DESIGN.md](docs/TRACK_RUNNER_DESIGN.md): Track runner design
  philosophy and principles.
- [docs/TRACK_RUNNER_HISTORY.md](docs/TRACK_RUNNER_HISTORY.md): Track runner evolution
  from v1 through v3.
- [docs/STABILIZATION_TOOL_PLAN.md](docs/STABILIZATION_TOOL_PLAN.md): Stabilization plan.
- Archived specs in `docs/archive/`: v1 plan, v1 spec, v2 spec, seed findings.

Root-level docs:

- [README.md](README.md): Project overview.
- [AGENTS.md](AGENTS.md): Agent collaboration guidance.
- [LICENSE](LICENSE): License text.

## Where to add new work

- **Core pipeline**: Add or update modules in [emwylib/core/](emwylib/core/).
- **Media processing**: Add helpers in [emwylib/media/](emwylib/media/).
- **Export formats**: Add modules in [emwylib/exporters/](emwylib/exporters/).
- **Import formats**: Create [emwylib/importers/](emwylib/importers/) when needed.
- **New generators**: Extend [emwylib/titlecard.py](emwylib/titlecard.py) or add
  a new module under [emwylib/](emwylib/).
- **Tests**: Add pytest files under [tests/](tests/) using `test_*.py` names.
- **Tool tests**: Add pytest files under [emwy_tools/tests/](emwy_tools/tests/).
- **Docs**: Add docs under [docs/](docs/) using SCREAMING_SNAKE_CASE names and
  update [docs/CHANGELOG.md](docs/CHANGELOG.md).
- **Tools**: Add sub-packages under [emwy_tools/](emwy_tools/) and document them
  in [docs/TOOLS.md](docs/TOOLS.md).
- **Analysis scripts**: Add standalone scripts under [tools/](tools/).
- **Samples**: Add example projects under [samples/](samples/) with `.emwy.yaml`
  extensions.
