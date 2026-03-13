# Track runner v3 specification

Status: v3, reflects implemented v3 modules as of 2026-03-12

This document describes the architecture of track_runner v3, a seed-driven
interval solver for tracking a single runner in handheld video footage.

## Overview

Track runner v3 reframes a handheld video so that a chosen runner stays
centered, with adaptive zoom. The core philosophy is:

> Human establishes identity. Machine interpolates geometry.

The user draws torso rectangles on a sample of frames (seeds). The solver
propagates a bounding box forward and backward from each seed, then scores
each inter-seed interval by how well the two directions agree. Weak intervals
trigger a review pass that asks the user for more seeds. Refinement repeats
until all intervals reach acceptable confidence or the user accepts the result.

v3 adds support for obstructed seeds with approximate bounding boxes,
interval-length-aware confidence scoring, and a PySide6-based annotation UI.

## Module map

| Module | Purpose |
| --- | --- |
| `track_runner.py` | Thin entry point: `import cli; cli.main()` |
| `cli.py` | Argument parsing, multi-pass orchestration, quality report |
| `config.py` | Config YAML loading, defaults, validation |
| `state_io.py` | JSON read/write for seeds and diagnostics files |
| `detection.py` | YOLOv8n ONNX person detection (HOG removed in v2) |
| `propagator.py` | Frame-to-frame local torso tracking between seeds |
| `hypothesis.py` | Competing path generation for ambiguous intervals |
| `scoring.py` | Interval confidence: agreement, identity, competitor margin |
| `interval_solver.py` | Per-interval bounded solving using seeds as anchors |
| `review.py` | Weak span identification and seed target generation |
| `seeding.py` | Interactive seed UI, jersey color extraction |
| `seed_editor.py` | Seed review and editing UI |
| `crop.py` | Adaptive crop trajectory from confidence-weighted positions |
| `encoder.py` | Video decode (OpenCV), crop apply, ffmpeg encode |
| `ui/workspace.py` | `AnnotationWindow(AppShell)` Qt main window with mode toolbar |
| `ui/frame_view.py` | `FrameView(QGraphicsView)` with cursor-anchored zoom |
| `ui/seed_controller.py` | `SeedController(QObject)` for seed collection |
| `ui/target_controller.py` | `TargetController(SeedController)` for targeted refinement |
| `ui/edit_controller.py` | `EditController(QObject)` for seed review and editing |
| `ui/overlay_items.py` | `RectItem`, `PreviewBoxItem`, `ScaleBarItem` overlays |
| `ui/status_presenter.py` | `StatusPresenter` QLabel for seed status display |
| `ui/theme.py` | Dark/light/system theme support |
| `ui/actions.py` | `make_action()` factory for toolbar actions |
| `ui/app_shell.py` | `AppShell(QMainWindow)` base class with theme toggle |

### Dependency graph

```
track_runner.py -> cli
cli -> config, state_io, detection, seeding, interval_solver, review, crop, encoder
interval_solver -> propagator, hypothesis, scoring
propagator -> detection, cv2, numpy
hypothesis -> propagator, scoring
scoring -> numpy
review -> scoring, state_io
seeding -> cv2, numpy, ui.seed_controller, ui.workspace
seed_editor -> ui.edit_controller, ui.workspace
crop -> numpy, math
encoder -> cv2, numpy, crop
config -> yaml, os
state_io -> json, os
ui.workspace -> ui.frame_view, ui.app_shell, ui.actions
ui.seed_controller -> ui.overlay_items, ui.status_presenter
ui.edit_controller -> ui.overlay_items, ui.status_presenter
```

## Data flow

```
Pass 1: seeds
  User draws torso boxes at seed interval
  seeding.py -> seeds JSON

Pass 2: interval solve
  interval_solver: forward + backward propagation per interval
  scoring: agreement, identity, competitor margin per interval
  -> solved trajectory + interval diagnostics

Pass 3: review
  review.py identifies weak intervals (low confidence)
  -> seed targets for refinement pass

Refinement passes (--refine flag controls mode)
  User seeds weak regions
  interval_solver re-runs on updated seeds
  -> repeat until acceptable or user stops

Pass N: crop
  crop.py: smooth crop trajectory from solved positions + confidence
  -> per-frame crop rectangles

Pass N+1: encode
  encoder.py: apply crop, resize, ffmpeg encode
  audio mux from original
  -> final output video
```

## Drawing modes and seed statuses

The user annotates each seed frame using one of four drawing modes. Each mode
produces a seed with a specific status value and data fields.

### The four drawing modes

- **Visible**: the runner is fully visible. The user draws a precise torso box.
  Exact torso position and jersey color are known. Full tracking confidence.
- **Partial**: the runner is partially hidden (another runner crossing in front,
  a pole, etc.) but the torso position is still identifiable. The user draws a
  precise torso box. Jersey hue is unreliable. Used as an interval endpoint but
  excluded from the appearance model.
- **Approx** (`a` key): the runner is fully hidden behind an obstruction and
  the exact torso position cannot be determined. The user draws a larger area
  (bigger than a torso box) indicating the general region where the runner is
  believed to be. Stored as `status: "obstructed"` with `torso_box` holding
  the drawn area. No `jersey_hsv`. Used as a weak interval endpoint (conf=0.3)
  to guide the solver through the gap, but trajectory near the seed is erased
  because the position is uncertain.
- **Not in frame** (`n` key): the runner has physically left the camera frame.
  They are known to be off-screen past the edge of the visible area. This is a
  definite determination by the user, not a "cannot find" status. No position
  data exists. Triggers trajectory erasure within the erase radius.

### Approx vs not_in_frame

These are distinct conditions. `not_in_frame` means the runner is confirmed
outside the frame boundary (off-screen) -- there is no position to record.
Approx means the runner is still within the frame but fully hidden, and the
user draws a general area where they believe the runner to be. The approx area
gives the solver a directional hint; `not_in_frame` has no location at all.

### Properties by drawing mode

| Property | visible | partial | approx | not_in_frame |
| --- | --- | --- | --- | --- |
| Status value in data | `visible` | `partial` | `approximate` | `not_in_frame` |
| Box type | precise torso box | precise torso box | larger approx area | none |
| Has position data (cx/cy/w/h) | YES | YES | YES (uncertain) | NO |
| Has `torso_box` | YES | YES | YES | NO |
| Has `jersey_hsv` | YES | unreliable | NO | NO |
| Runner in frame | YES | YES | YES (hidden) | NO (off-screen) |
| Used as interval endpoint | YES | YES | YES (weak, conf=0.3) | NO |
| Used for appearance model | YES | NO | NO | NO |
| Triggers trajectory erasure | NO | NO | YES | YES |
| Default confidence | 1.0 | 1.0 | 0.3 | n/a |

## Valid seed modes

| Mode | Description |
| --- | --- |
| `initial` | First-pass seeding at regular intervals |
| `suggested_refine` | Refinement at solver-suggested weak-span frames |
| `interval_refine` | Refinement at evenly spaced frames across all intervals |
| `gap_refine` | Refinement at midpoints of large seedless gaps |
| `target_refine` | Targeted refinement via the target controller UI |
| `bbox_polish` | YOLO or consensus polish applied during seed editing |

## Confidence decision grid

`scoring.py` scores each interval using three aggregate metrics.

| Agreement | Separation (margin) | Confidence | Notes |
| --- | --- | --- | --- |
| > 0.5 | > 0.5 | `high` | Trusted |
| > 0.5 | > 0.2 | `good` | Acceptable, reason: `low_separation` |
| > 0.2 | > 0.1 | `fair` | Borderline |
| everything else | | `low` | Needs seed |

Additional flags appended to `failure_reasons` regardless of confidence:

- `likely_identity_swap`: competitor margin < 0.2 (a strong competitor exists)
- `weak_appearance`: identity score < 0.4 (jersey color match is poor)

### Interval-length-aware scoring

For intervals of 5 frames or fewer, the confidence tier is promoted by one
level (low -> fair, fair -> good). This compensates for the inherent noise
in FWD/BWD agreement on very short intervals where the propagator barely
advances. The promotion never reaches "high" -- at most "good".

This reduces false negatives on densely-seeded regions where 1-2 frame
intervals dominate and agreement scores are meaningless.

## Trajectory erasure

When the runner is off-screen (not_in_frame) or fully hidden (approx), the
solver erases trajectory data near that frame to prevent the propagator from
tracking a wrong person through a gap. Approx seeds guide the solver as weak
endpoints, but the trajectory near the seed is still erased because the
position is uncertain. The erase radius differs by drawing mode:

| Drawing mode | Erase radius | Endpoint | Reason |
| --- | --- | --- | --- |
| visible | no erasure | yes (accurate) | precise torso box, fully visible |
| partial | no erasure | yes (accurate) | precise torso box, position known |
| approx | 0.5 s | yes (weak) | larger area, uncertain position |
| not_in_frame | 1.0 s | no | runner off-screen, no position |

## Core algorithm: bounded interval solver

The interval solver treats each inter-seed span as an independent bounded
problem. Seeds are hard anchors. Within each interval the solver runs a
forward propagation (from the left seed) and a backward propagation (from
the right seed), then fuses the two tracks into a scored result.

### Forward and backward propagation

`propagator.py` advances a bounding box one frame at a time using YOLO
detections and a lightweight local-search matcher. There is no Kalman filter.
The propagator returns a list of per-frame state dicts:

```
{"cx": float, "cy": float, "w": float, "h": float, "conf": float, "source": str}
```

`source` values: `seed`, `detected`, `propagated`, `absent`.

### Hypothesis generation

For intervals where the propagator confidence drops below a threshold,
`hypothesis.py` generates competing path candidates. Each hypothesis
represents an alternative runner trajectory through the interval. The
solver selects the hypothesis with the best scoring outcome.

### Confidence-weighted fusion

After forward and backward propagation the interval solver fuses the two
tracks. At each frame the fused position is a confidence-weighted average:

```
fused_cx = (fwd_conf * fwd_cx + bwd_conf * bwd_cx) / (fwd_conf + bwd_conf)
```

Same formula for `cy`, `w`, and `h`. When one direction has zero confidence
the other direction is used directly.

## Refinement modes

The `--refine` flag controls which intervals trigger a new seeding round.

### suggested

Default mode. The `review.py` module identifies the worst intervals by
confidence and failure reason. Seed targets are placed at midpoints of
low-confidence intervals. The user seeds only those frames.

### interval

Re-seeds every inter-seed interval regardless of confidence. Useful for
a first-pass review of a new video when overall quality is unknown.

### gap

Re-seeds only the largest seedless gaps (controlled by `--gap-threshold`).
Gap threshold defaults to 15 seconds; gaps shorter than this are skipped.

## CLI arguments

| Flag | Dest | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `-i`, `--input` | `input_file` | str | required | Input video path |
| `-o`, `--output` | `output_file` | str | `{stem}_tracked{ext}` | Output path |
| `-c`, `--config` | `config_file` | str | `{input}.track_runner.config.yaml` | Config YAML path |
| `--seed-interval` | `seed_interval` | float | config value | Override `seeding.interval_seconds` |
| `--aspect` | `aspect` | str | config value | Override crop aspect ratio (e.g. `1:1`) |
| `-d`, `--debug` | `debug` | flag | False | Draw debug overlay on output video |
| `--refine` | `refine` | str | `suggested` | Refinement mode: `suggested`, `interval`, or `gap` |
| `--gap-threshold` | `gap_threshold` | float | 15.0 | Min seedless gap in seconds to trigger gap refinement |
| `--time-range` | `time_range` | str | None | Restrict processing to `HH:MM:SS-HH:MM:SS` range |
| `--ignore-diagnostics` | `ignore_diagnostics` | flag | False | Ignore existing diagnostics and re-solve from seeds |

## File formats

All three files are derived from the input filename stem.

### Config YAML

Path: `{input}.track_runner.config.yaml`

Header key `track_runner` must equal `2`. Required top-level sections:
`detection` and `processing`.

```yaml
track_runner: 2
detection:
  model: yolov8n
  confidence_threshold: 0.25
processing:
  crop_aspect: "1:1"
  crop_fill_ratio: 0.30
  video_codec: libx264
  crf: 18
```

### Seeds JSON

Path: `{input}.track_runner.seeds.json`

Header key `track_runner_seeds` must equal `2`.
Each seed entry has a `frame` key (integer frame index).
The `mode` field records how the seed was created.

Valid `mode` values: `initial`, `suggested_refine`, `interval_refine`,
`gap_refine`, `target_refine`, `bbox_polish`.

```json
{
  "track_runner_seeds": 2,
  "video_file": "race.mov",
  "seeds": [
    {
      "frame": 150,
      "time_s": 5.0,
      "torso_box": [640, 360, 40, 60],
      "jersey_hsv": [120, 180, 200],
      "pass": 1,
      "source": "human",
      "mode": "initial",
      "status": "visible"
    },
    {
      "frame": 300,
      "time_s": 10.0,
      "status": "not_in_frame",
      "pass": 1,
      "source": "human",
      "mode": "initial"
    },
    {
      "frame": 450,
      "time_s": 15.0,
      "status": "obstructed",
      "torso_box": [500, 300, 80, 120],
      "pass": 2,
      "source": "human",
      "mode": "suggested_refine"
    }
  ]
}
```

### Diagnostics JSON

Path: `{input}.track_runner.diagnostics.json`

Header key `track_runner_diagnostics` must equal `2`.

## Differences from v2

| Area | v2 | v3 |
| --- | --- | --- |
| Drawing modes | visible, partial, not_in_frame | visible, partial, approx (`a` key), not_in_frame |
| Approx seeds | no approx mode existed | weak endpoints (conf=0.3) guide solver; trajectory still erased |
| Trajectory erasure | erases near not_in_frame only | erases near approx (0.5s) and not_in_frame (1.0s) |
| Confidence tiers | 4-tier (high/good/fair/low) | 4-tier with short-interval promotion (<= 5 frames bumps one tier) |
| Annotation UI | OpenCV cv2.namedWindow loops | PySide6 AnnotationWindow with dark theme and cursor-anchored zoom |
| Seed modes | initial, suggested_refine, interval_refine, gap_refine | adds target_refine, bbox_polish |
| Seed validation | none | validate_seed() warns on approx seeds missing torso_box |

## Differences from v1

| Area | v1 | v3 |
| --- | --- | --- |
| Tracking algorithm | 7-state Kalman filter | Bounded interval solver |
| Propagator | Kalman predict/update | Local search propagator (no Kalman) |
| Interval scoring | Per-frame confidence only | Agreement + identity + competitor margin |
| Review workflow | `--add-seeds` (manual) | Structured review pass with seed targets |
| Seeds format | YAML (`track_runner_seeds: 1`) | JSON (`track_runner_seeds: 2`) |
| Diagnostics format | YAML (~1 MB per 4 min) | JSON (~500 KB per 4 min) |
| Config format | YAML (`track_runner: 1`) | YAML (`track_runner: 2`) |
| Detection fallback | HOG if YOLO unavailable | YOLO required; no HOG fallback |
| Annotation UI | OpenCV popup windows | PySide6 native Qt windows |
