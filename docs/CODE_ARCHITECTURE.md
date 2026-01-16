# Code architecture

This document describes the emwy code layout and the main execution paths.

## Overview

emwy is a command-line video editor that parses YAML projects into a compiled
timeline and renders segments with ffmpeg/sox before muxing outputs. MLT XML is
an optional export format, not the primary render path.

## Major components

### Entry points

- [emwy_cli.py](emwy_cli.py): Primary CLI entry point that parses args and runs
  [emwylib/core/project.py](emwylib/core/project.py).
- [emwy_tui.py](emwy_tui.py): Textual TUI wrapper that drives the same render
  pipeline with progress and logging views.
- [emwylib/exporters/mlt.py](emwylib/exporters/mlt.py): MLT XML exporter entry
  point (`python3 -m emwylib.exporters.mlt`).

### Core pipeline

- [emwylib/core/loader.py](emwylib/core/loader.py): Parses YAML projects into a
  `ProjectData` model and applies defaults.
- [emwylib/core/timeline.py](emwylib/core/timeline.py): Expands timeline
  segments into compiled playback stacks and overlay tracks.
- [emwylib/core/renderer.py](emwylib/core/renderer.py): Executes the render plan
  with ffmpeg/sox and muxes outputs with mkvmerge.
- [emwylib/core/project.py](emwylib/core/project.py): Orchestrates loader,
  timeline, and renderer via `EmwyProject`.
- [emwylib/core/utils.py](emwylib/core/utils.py): Shared helpers and formatting.

### Media helpers

- [emwylib/media/](emwylib/media/): Low-level ffmpeg/sox wrappers used by the
  renderer.
- [emwylib/ffmpeglib.py](emwylib/ffmpeglib.py), [emwylib/soxlib.py](emwylib/soxlib.py),
  [emwylib/medialib.py](emwylib/medialib.py): Additional media utilities.
- [emwylib/titlecard.py](emwylib/titlecard.py): Title and chapter card image
  generation.
- [emwylib/transforms.py](emwylib/transforms.py): RGB transform helpers.

### Exporters

- [emwylib/exporters/](emwylib/exporters/): Export formats (currently MLT XML).

### Tools

- [tools/silence_annotator.py](tools/silence_annotator.py): Generate EMWY YAML
  from audio silence detection.
- [tools/stabilize_building.py](tools/stabilize_building.py): Global
  stabilization tool for existing media.
- [tools/video_scruncher.py](tools/video_scruncher.py): Video compression helper.

## Data flow

Typical render flow:

```
project.emwy.yaml
  |
  v
loader.py (parse + defaults)
  |
  v
ProjectData
  |
  v
timeline.py (compile segments and overlays)
  |
  v
renderer.py (ffmpeg/sox renders + mkvmerge mux)
  |
  v
output.mkv
```

MLT export branches after compilation and writes XML instead of rendering.

## Testing and verification

- [tests/](tests/): pytest-style test files and helpers.
- [tests/run_pyflakes.sh](tests/run_pyflakes.sh): Pyflakes static analysis.
- [tests/run_ascii_compliance.py](tests/run_ascii_compliance.py): ASCII and
  ISO-8859-1 compliance scan.
- [tests/check_ascii_compliance.py](tests/check_ascii_compliance.py): Per-file
  ASCII/ISO-8859-1 checker.

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the preferred test workflow.

## Extension points

- **New YAML fields**: Update [emwylib/core/loader.py](emwylib/core/loader.py)
  and propagate to [emwylib/core/timeline.py](emwylib/core/timeline.py) and
  [emwylib/core/renderer.py](emwylib/core/renderer.py).
- **Timeline behavior**: Extend [emwylib/core/timeline.py](emwylib/core/timeline.py).
- **Rendering and codecs**: Extend [emwylib/core/renderer.py](emwylib/core/renderer.py)
  and [emwylib/media/](emwylib/media/).
- **New generators**: Add modules under [emwylib/](emwylib/) or extend
  [emwylib/titlecard.py](emwylib/titlecard.py).
- **New export formats**: Add modules under [emwylib/exporters/](emwylib/exporters/).
- **New import formats**: Create [emwylib/importers/](emwylib/importers/) when
  import support is implemented.
- **Standalone tools**: Add scripts under [tools/](tools/) and document them in
  [docs/TOOLS.md](docs/TOOLS.md).

## Known gaps

- `pyproject.toml` registers a console script at `emwy:main`, but there is no
  `emwy.py` module in the repo. Verify the intended packaging entry point.
- [emwylib/importers/](emwylib/importers/) does not exist yet; import support is
  specified in [docs/IMPORT_MLT_XML_SPEC.md](docs/IMPORT_MLT_XML_SPEC.md) but not
  implemented.
