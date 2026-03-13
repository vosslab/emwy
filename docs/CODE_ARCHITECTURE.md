# Code architecture

This document describes the emwy code layout and the main execution paths.

## Overview

emwy is a command-line video editor that parses YAML projects into a compiled
timeline and renders segments with ffmpeg/sox before muxing outputs. MLT XML is
an optional export format, not the primary render path.

The repo also includes standalone tools under [emwy_tools/](emwy_tools/) for
tasks like runner tracking, silence annotation, and video stabilization.

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

- [emwy_tools/silence_annotator/](emwy_tools/silence_annotator/): Generate EMWY YAML
  from audio silence detection.
- [emwy_tools/stabilize_building/](emwy_tools/stabilize_building/): Global
  stabilization tool for existing media.
- [emwy_tools/track_runner/](emwy_tools/track_runner/): Seed-driven runner
  tracking and video reframing from handheld footage (v2 interval solver).
- [emwy_tools/video_scruncher/](emwy_tools/video_scruncher/): Video compression
  helper (placeholder).
- [tools/](tools/): Standalone analysis scripts (seed variability measurement
  and plotting).

### track_runner v2 architecture

The track_runner is a seed-driven interval solver that interpolates geometry
between human-provided anchor points. The human establishes identity; the
machine interpolates geometry. Modules are organized by responsibility:

- [emwy_tools/track_runner/cli.py](emwy_tools/track_runner/cli.py): Argparse,
  multi-pass orchestration, seed format conversion.
- [emwy_tools/track_runner/config.py](emwy_tools/track_runner/config.py): YAML
  config load/write/validate (human-edited settings).
- [emwy_tools/track_runner/state_io.py](emwy_tools/track_runner/state_io.py):
  JSON read/write for seeds and diagnostics (machine-managed data).
- [emwy_tools/track_runner/propagator.py](emwy_tools/track_runner/propagator.py):
  Frame-to-frame torso tracking using pyramidal Lucas-Kanade optical flow
  and patch correlation.
- [emwy_tools/track_runner/hypothesis.py](emwy_tools/track_runner/hypothesis.py):
  Competing path generation, identity scoring, competitor margin computation.
- [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py):
  Per-interval bounded solving, forward/backward track fusion, cyclical prior
  detection, trajectory stitching.
- [emwy_tools/track_runner/scoring.py](emwy_tools/track_runner/scoring.py):
  Interval confidence metrics (agreement, meeting point errors, confidence
  classification).
- [emwy_tools/track_runner/review.py](emwy_tools/track_runner/review.py): Weak
  span identification and suggested seed frames with failure reasons.
- [emwy_tools/track_runner/seeding.py](emwy_tools/track_runner/seeding.py):
  Interactive seed collection with multi-pass refinement workflow.
- [emwy_tools/track_runner/crop.py](emwy_tools/track_runner/crop.py): Adaptive
  crop controller with exponential smoothing, trajectory-to-crop-rect
  conversion with gap filling.
- [emwy_tools/track_runner/detection.py](emwy_tools/track_runner/detection.py):
  YOLO person detection as a supporting cue (not the tracking backbone).
- [emwy_tools/track_runner/encoder.py](emwy_tools/track_runner/encoder.py):
  Video reader/writer, audio copy, debug overlay drawing.

Three canonical state types flow through these modules without mixing:

- **Tracking state** (`cx, cy, w, h, conf, source`): where the torso is per frame.
- **Hypothesis state**: tracking state plus identity score, competitor margin,
  and failure reasons.
- **Crop state** (`crop_cx, crop_cy, crop_size`): output crop rectangle,
  downstream of tracking.

See [docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md) for the full
specification.

## Data flow

### EMWY render flow

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

### track_runner flow

```
Pass 1: human seeds (interactive, --seed-interval N)
  |
  v
interval_solver (split timeline into seed-to-seed intervals)
  |
  +-- per interval:
  |     propagator: forward from seed A, backward from seed B
  |     hypothesis: generate and score competing paths
  |     scoring: agreement + identity + competitor margin
  |
  v
diagnostics (per-interval confidence, failure reasons)
  |
  v
review (identify weak spans, suggest reseed frames)
  |
  v
Pass 2+: user re-seeds (--refine suggested|interval|gaps)
  |
  v
crop.py (smooth crop from final trajectory)
  |
  v
encoder.py (render output video)
```

## Testing and verification

- [tests/](tests/): pytest-style test files and helpers.
- [tests/test_pyflakes_code_lint.py](tests/test_pyflakes_code_lint.py): Pyflakes
  static analysis gate.
- [tests/test_ascii_compliance.py](tests/test_ascii_compliance.py): ASCII and
  ISO-8859-1 compliance gate.
- [tests/check_ascii_compliance.py](tests/check_ascii_compliance.py): Per-file
  ASCII/ISO-8859-1 checker.
- [emwy_tools/tests/](emwy_tools/tests/): Tool-specific tests including
  track_runner unit tests (54 tests covering all v2 modules).

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
- **Standalone tools**: Add sub-packages under [emwy_tools/](emwy_tools/) and
  document them in [docs/TOOLS.md](docs/TOOLS.md).
- **track_runner cues**: Add new tracking cues in
  [emwy_tools/track_runner/propagator.py](emwy_tools/track_runner/propagator.py)
  and wire them into
  [emwy_tools/track_runner/interval_solver.py](emwy_tools/track_runner/interval_solver.py).

## Known gaps

- `pyproject.toml` registers a console script at `emwy:main`, but there is no
  `emwy.py` module in the repo. Verify the intended packaging entry point.
- [emwylib/importers/](emwylib/importers/) does not exist yet; import support is
  specified in [docs/IMPORT_MLT_XML_SPEC.md](docs/IMPORT_MLT_XML_SPEC.md) but not
  implemented.
