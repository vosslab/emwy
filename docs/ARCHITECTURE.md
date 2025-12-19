# Architecture

This document describes the current emwy code layout and where new features belong.

## High-Level Flow
1. **Load**: YAML is parsed into a normalized project model.
2. **Plan**: Timeline planning expands conveniences such as paired audio.
3. **Render**: The renderer runs ffmpeg/sox and produces the final output.
4. **Export**: Optional exporters (MLT, future OTIO) read the project model.

MLT XML is treated as the canonical compiled form, even when rendering natively.

## Core Modules
- `emwylib/core/loader.py`
  - Parses YAML v2 and builds a `ProjectData` instance.
  - Handles defaults, playlist entry parsing, and basic validation.
- `emwylib/core/timeline.py`
  - Timeline planner that expands paired audio and checks track alignment.
- `emwylib/core/renderer.py`
  - Executes the render plan using ffmpeg/sox and muxes the final output.
- `emwylib/core/project.py`
  - Orchestrates loader, timeline, and renderer. Exposes `EmwyProject` used by the CLI.

## Media Wrappers
- `emwylib/media/ffmpeg_extract.py` and `emwylib/media/ffmpeg_render.py`
  - Low-level ffmpeg wrappers. Split by intent: extraction vs. rendering.
- `emwylib/media/sox_normalize.py` and `emwylib/media/sox_edit.py`
  - Sox helpers, split into normalization vs. editing operations.

## Exporters
- `emwylib/exporters/mlt.py`
  - Generates MLT XML from v2 YAML. Uses lxml.

## Where to Add New Features
- **New YAML fields**: update `emwylib/core/loader.py` first.
- **Timeline behavior** (paired audio, transitions, overlays): update `emwylib/core/timeline.py`.
- **Rendering changes** (filters, codecs, mux rules): update `emwylib/core/renderer.py`.
- **Interchange formats** (OTIO, Shotcut): add under `emwylib/exporters/` or future `emwylib/importers/`.

## Testing
- Unit tests should focus on parsing and timing rules.
- Integration tests should use tiny generated assets to keep runtimes short.
