# Code architecture

This document describes the emwy code layout and where new features belong.

## Overview

emwy is a command-line video editor that compiles YAML project files into rendered video output. The pipeline is:

1. **Load**: YAML is parsed into a normalized project model.
2. **Compile**: Timeline segments are expanded into a renderable plan and compiled playlists for exporters.
3. **Render**: The renderer runs ffmpeg/sox per segment, muxes A/V, and concatenates the results.
4. **Export**: Optional exporters (MLT) read the compiled model.

MLT XML is an optional export format, not the canonical render path.

## Major components

### Entry points

- `emwy_cli.py`: Primary CLI entry point. Parses arguments and runs `EmwyProject`.
- `emwy_tui.py`: Textual TUI wrapper for interactive renders with progress dashboard.
- `emwylib/exporters/mlt.py`: MLT XML export entry point (`python3 -m emwylib.exporters.mlt`).

### Core library (`emwylib/core/`)

- `loader.py`: Parses YAML v2 and builds a `ProjectData` instance. Handles defaults, timeline segment parsing, and basic validation.
- `timeline.py`: Timeline compiler that expands segments into compiled playlists/stack. Handles overlays, playback styles, and segment expansion.
- `renderer.py`: Executes the render plan using ffmpeg/sox and muxes the final output with mkvmerge.
- `project.py`: Orchestrates loader, timeline, and renderer. Exposes `EmwyProject` used by entry points.
- `utils.py`: Shared utility functions for time formatting, path handling, and common helpers.

### Media wrappers (`emwylib/media/`)

- `ffmpeg.py`: High-level ffmpeg interface.
- `ffmpeg_extract.py`: Low-level ffmpeg extraction commands.
- `ffmpeg_render.py`: Low-level ffmpeg rendering commands.
- `sox.py`: High-level sox interface.
- `sox_normalize.py`: Sox audio normalization helpers.
- `sox_edit.py`: Sox audio editing operations.

### Top-level library modules (`emwylib/`)

- `titlecard.py`: Title card and chapter card image generation using Pillow/numpy.
- `transforms.py`: Affine color transforms for images (RGBTransform class).
- `ffmpeglib.py`: Additional ffmpeg helpers.
- `soxlib.py`: Additional sox helpers.
- `medialib.py`: Media inspection and metadata utilities.
- `version.py`: Package version string.

### Exporters (`emwylib/exporters/`)

- `mlt.py`: Generates MLT XML from v2 YAML projects. Uses lxml.

## Data flow

End-to-end flow for a typical render:

```
.emwy.yaml
   |
   v
loader.py (parse + validate)
   |
   v
ProjectData instance
   |
   v
timeline.py (expand segments, compile playlists)
   |
   v
Render plan (compiled stack/playlists)
   |
   v
renderer.py (per-segment ffmpeg/sox, mkvmerge concat)
   |
   v
output.mkv
```

Optional MLT export branches after the compile step and writes XML instead of rendering.

## Testing and verification

Tests live in `tests/`:

- `test_*.py`: pytest test files covering YAML parsing, rendering, overlays, playback styles, and TUI metrics.
- `run_pyflakes.sh`: Static analysis runner for pyflakes.
- `font_utils.py`, `render_titlecard.py`: Test helpers.

Run tests with:

```bash
pytest tests/
```

Run static analysis with:

```bash
./tests/run_pyflakes.sh
```

## Extension points

- **New YAML fields**: Update `emwylib/core/loader.py` first, then propagate to timeline and renderer as needed.
- **Timeline behavior** (segment compilation, overlays, transitions): Update `emwylib/core/timeline.py`.
- **Rendering changes** (filters, codecs, mux rules): Update `emwylib/core/renderer.py`.
- **New video transforms** (stabilization, color grading): Add to `emwylib/media/` and wire through renderer.
- **Interchange formats** (OTIO, Shotcut): Add under `emwylib/exporters/` or future `emwylib/importers/`.
- **New generator types** (title cards, overlays): Extend `emwylib/titlecard.py` or add new generator modules.

## Known gaps

- `emwylib/importers/` does not exist yet. MLT import is documented but not implemented.
- No subject-tracking or rolling-shutter correction transforms.
