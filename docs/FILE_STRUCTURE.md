# File structure

This document describes the emwy repository layout and where different files
belong.

## Top-level layout

```
emwy/
+- AGENTS.md
+- Brewfile
+- LICENSE
+- MANIFEST.in
+- README.md
+- ascii_compliance.txt
+- emwy_cli.py
+- emwy_tui.py
+- pip_requirements.txt
+- pyproject.toml
+- pyflakes.txt
+- shebang_report.txt
+- devel/
+- docs/
+- emwylib/
+- samples/
+- tests/
`- tools/
```

Top-level highlights:

- [README.md](README.md): Project overview and quick start.
- [AGENTS.md](AGENTS.md): Agent workflow and coding guidance.
- [pyproject.toml](pyproject.toml): Packaging metadata and scripts.
- [pip_requirements.txt](pip_requirements.txt): Python dependencies.
- [emwy_cli.py](emwy_cli.py): Primary CLI entry point.
- [emwy_tui.py](emwy_tui.py): Textual TUI wrapper.
- [ascii_compliance.txt](ascii_compliance.txt): ASCII compliance report output.
- [pyflakes.txt](pyflakes.txt): Pyflakes report output.
- [shebang_report.txt](shebang_report.txt): Shebang scan report output.

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
  check_ascii_compliance.py
  font_utils.py
  render_titlecard.py
  run_ascii_compliance.py
  run_pyflakes.sh
  test_emwy_yaml_writer.py
  test_enabled_entries.py
  test_ffmpeg_overlays.py
  test_font_usage.py
  test_indentation.py
  test_integration_render.py
  test_mlt_export.py
  test_playback_styles.py
  test_render_tooling.py
  test_repo_hygiene.py
  test_shebangs.py
  test_speed_sync.py
  test_stabilize_building_tool.py
  test_tui_metrics.py
```

### Tools

Helper scripts in [tools/](tools/):

```
tools/
  README.md
  config_silence.yml
  demo_codex.small.emwy.yaml
  emwy_yaml_writer.py
  silence_annotator.py
  stabilize_building.py
  video_scruncher.py
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

- [ascii_compliance.txt](ascii_compliance.txt): Output from
  [tests/run_ascii_compliance.py](tests/run_ascii_compliance.py).
- [pyflakes.txt](pyflakes.txt): Output from [tests/run_pyflakes.sh](tests/run_pyflakes.sh).
- [shebang_report.txt](shebang_report.txt): Output from
  [tests/test_shebangs.py](tests/test_shebangs.py).
- `__pycache__/`, `*.pyc`: Python bytecode artifacts.
- `build/`, `dist/`, `*.egg-info/`: Packaging outputs.
- `.pytest_cache/`, `.mypy_cache/`: Test and type-check caches.
- `*.mkv`, `*.mp4`, `*.avi`: Video outputs (ignored by default).

Temporary render files default to a per-run temp directory (see `--cache-dir` in
[docs/CLI.md](docs/CLI.md)).

## Documentation map

Documentation lives in [docs/](docs/):

- [docs/INSTALL.md](docs/INSTALL.md): System dependencies and install steps.
- [docs/CLI.md](docs/CLI.md): CLI usage and flags.
- [docs/FORMAT.md](docs/FORMAT.md): YAML project format overview.
- [docs/TOOLS.md](docs/TOOLS.md): Tooling and helper scripts.
- [docs/DEBUGGING.md](docs/DEBUGGING.md): Common errors and diagnostics.
- [docs/COOKBOOK.md](docs/COOKBOOK.md): Editing recipes.
- [docs/FAQ.md](docs/FAQ.md): Common questions and design notes.
- [docs/EMWY_YAML_v1_SPEC.md](docs/EMWY_YAML_v1_SPEC.md): Legacy v1 spec.
- [docs/EMWY_YAML_v2_SPEC.md](docs/EMWY_YAML_v2_SPEC.md): Current v2 spec.
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
- [docs/STABILIZATION_TOOL_PLAN.md](docs/STABILIZATION_TOOL_PLAN.md): Stabilization plan.

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
- **Docs**: Add docs under [docs/](docs/) using SCREAMING_SNAKE_CASE names and
  update [docs/CHANGELOG.md](docs/CHANGELOG.md).
- **Tools**: Add scripts under [tools/](tools/) and document them in
  [docs/TOOLS.md](docs/TOOLS.md).
- **Samples**: Add example projects under [samples/](samples/) with `.emwy.yaml`
  extensions.
