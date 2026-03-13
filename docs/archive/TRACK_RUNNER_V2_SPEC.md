# Track runner v2 specification

Status: Draft, reflects implemented v2 modules as of 2026-03-11

This document describes the architecture of track_runner v2, a seed-driven
interval solver for tracking a single runner in handheld video footage.

## Overview

Track runner v2 reframes a handheld video so that a chosen runner stays
centered, with adaptive zoom. The core philosophy is:

> Human establishes identity. Machine interpolates geometry.

The user draws torso rectangles on a sample of frames (seeds). The solver
propagates a bounding box forward and backward from each seed, then scores
each inter-seed interval by how well the two directions agree. Weak intervals
trigger a review pass that asks the user for more seeds. Refinement repeats
until all intervals reach acceptable confidence or the user accepts the result.

This replaces the v1 Kalman-only bidirectional tracker with a structured
interval solver that makes weak regions explicit and recoverable.

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
| `crop.py` | Adaptive crop trajectory from confidence-weighted positions |
| `encoder.py` | Video decode (OpenCV), crop apply, ffmpeg encode |

### Dependency graph

```
track_runner.py -> cli
cli -> config, state_io, detection, seeding, interval_solver, review, crop, encoder
interval_solver -> propagator, hypothesis, scoring
propagator -> detection, cv2, numpy
hypothesis -> propagator, scoring
scoring -> numpy
review -> scoring, state_io
seeding -> cv2, numpy
crop -> numpy, math
encoder -> cv2, numpy, crop
config -> yaml, os
state_io -> json, os
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

Valid `mode` values: `initial`, `suggested_refine`, `interval_refine`, `gap_refine`.

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
      "mode": "initial"
    },
    {
      "frame": 300,
      "time_s": 10.0,
      "status": "not_in_frame",
      "pass": 1,
      "source": "human",
      "mode": "initial"
    }
  ]
}
```

Absence markers use a `status` field with value `not_in_frame` or `obstructed`.
Visible seeds use `torso_box` (top-left `[x, y, w, h]`) and `jersey_hsv`.

`merge_seeds()` in `state_io.py` preserves existing seeds: new seeds at frames
already present are silently skipped (existing seed wins).

### Diagnostics JSON

Path: `{input}.track_runner.diagnostics.json`

Header key `track_runner_diagnostics` must equal `2`.

JSON format reduces file size by 3-5x compared to v1 YAML for per-frame arrays.
Typical size for a 4-minute video is under 500 KB.

```json
{
  "track_runner_diagnostics": 2,
  "video_file": "race.mov",
  "fps": 30.0,
  "total_frames": 5400,
  "intervals": [
    {
      "start_frame": 0,
      "end_frame": 300,
      "agreement_score": 0.91,
      "identity_score": 0.74,
      "competitor_margin": 0.62,
      "confidence": "high",
      "failure_reasons": []
    },
    {
      "start_frame": 300,
      "end_frame": 600,
      "agreement_score": 0.43,
      "identity_score": 0.55,
      "competitor_margin": 0.18,
      "confidence": "low",
      "failure_reasons": ["low_agreement", "likely_identity_swap"]
    }
  ],
  "trajectory": [
    {"frame": 0, "cx": 960.0, "cy": 540.0, "w": 120.0, "h": 300.0, "source": "seed"},
    {"frame": 1, "cx": 962.3, "cy": 539.1, "w": 121.0, "h": 300.5, "source": "propagated"}
  ]
}
```

## Core algorithm: bounded interval solver

The interval solver treats each inter-seed span as an independent bounded
problem. Seeds are hard anchors. Within each interval the solver runs a
forward propagation (from the left seed) and a backward propagation (from
the right seed), then fuses the two tracks into a scored result.

### Forward and backward propagation

`propagator.py` advances a bounding box one frame at a time using YOLO
detections and a lightweight local-search matcher. There is no Kalman filter
in v2. The propagator returns a list of per-frame state dicts:

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

## Confidence decision grid

`scoring.py` scores each interval using three aggregate metrics.

| Agreement | Separation (margin) | Confidence | Notes |
| --- | --- | --- | --- |
| High (> 0.8) | High (> 0.5) | `high` | Accept |
| High (> 0.8) | Low (<= 0.5) | `low` | Reason: `low_separation` |
| Low (<= 0.8) | Any | `low` | Reason: `low_agreement` |

Additional flags appended to `failure_reasons` regardless of confidence:

- `likely_identity_swap`: competitor margin < 0.2 (a strong competitor exists)
- `weak_appearance`: identity score < 0.4 (jersey color match is poor)

Agreement is computed by `compute_agreement()` in `scoring.py`. It normalizes
per-frame center error by runner height so a 5 px error for a small runner is
penalized more than 5 px for a large runner. Center error weight is 0.7;
scale error weight is 0.3.

## Scale-gated cue weights

Detection cue weights are adjusted by the apparent runner size to compensate
for reduced YOLO reliability at small scales.

| Apparent size (bbox height) | Primary cue | Secondary cue |
| --- | --- | --- |
| > 60 px | Appearance (YOLO confidence, jersey color) | Motion |
| 30 - 60 px | Balanced | Balanced |
| < 30 px | Motion (optical flow, displacement) | Appearance |

At small scales the propagator falls back to motion-based matching because
YOLO detection quality degrades before the runner disappears entirely.

## Special modes

### Stationary lock

When a seed marks the runner as stationary (low velocity over multiple
consecutive seeds), the interval solver locks the bounding box center
and only updates scale. This prevents the tracker from drifting onto a
different nearby person who is moving.

Stationary lock activates when the center displacement between consecutive
visible seeds is below 2% of frame width per second.

### Cyclical prior

When the input is a loop course (runner passes the same camera position
repeatedly), the solver can use earlier detected appearances as a prior
for later intervals. This mode is enabled via config and is useful for
marathon footage where the runner's jersey color is a reliable identity
signal across laps.

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
This is equivalent to the v1 `--add-seeds` path and is best for videos
where seeds are sparse but existing intervals are already high-confidence.
Gap threshold defaults to 15 seconds; gaps shorter than this are skipped.

## Debug output

### Debug video overlay

Enabled with `-d` / `--debug`. Each frame shows:

- Bounding box outline with color indicating source:
  - Green: detected (YOLO match found in this frame)
  - Blue: propagated forward from a seed
  - Orange: propagated backward from a seed
  - Red: lost (no detection and no confident propagation)
- Crosshair at bbox center
- Confidence bar in the top-right corner (green at 1.0 fading to red at 0.0)
- Frame index, source label, and confidence value as text

### Forensic JSON

The diagnostics JSON written after each solve pass contains:

- Per-interval agreement, identity, competitor margin, confidence, and failure reasons
- Full per-frame trajectory with source label
- Interval boundaries used for the solve

This file is read by `review.py` to compute seed targets for the next pass
and is also useful for offline debugging of tracking failures.

### Console output

After each solve pass the CLI prints a quality report:

```
Interval results:
  Total intervals:  24
  High confidence:  19  (79%)
  Low confidence:    5  (21%)

  Failure reasons:
    low_agreement        3
    low_separation       2
    likely_identity_swap 1

Worst intervals:
  frames 0300-0600   agreement=0.43  [low_agreement, likely_identity_swap]
  frames 1200-1500   agreement=0.61  [low_separation]
  ...

Overall grade: B
```

The letter grade is based on the fraction of high-confidence intervals:
A >= 90%, B >= 75%, C >= 60%, D >= 40%, F < 40%.

## Differences from v1

| Area | v1 | v2 |
| --- | --- | --- |
| Tracking algorithm | 7-state Kalman filter | Bounded interval solver |
| Propagator | Kalman predict/update | Local search propagator (no Kalman) |
| Interval scoring | Per-frame confidence only | Agreement + identity + competitor margin |
| Review workflow | `--add-seeds` (manual) | Structured review pass with seed targets |
| Seeds format | YAML (`track_runner_seeds: 1`) | JSON (`track_runner_seeds: 2`) |
| Diagnostics format | YAML (~1 MB per 4 min) | JSON (~500 KB per 4 min) |
| Config format | YAML (`track_runner: 1`) | YAML (`track_runner: 2`) |
| Detection fallback | HOG if YOLO unavailable | YOLO required; no HOG fallback |
| Scoring terms | 3 real + 3 placeholder (0.5) | All terms computed from evidence |
| Seed merge policy | New overwrites same frame | Existing wins (new is skipped) |
| Refinement CLI | `--add-seeds` only | `--refine suggested|interval|gap` |

The Kalman filter (`kalman.py`) and the v1 tracker pipeline (`tracker.py`)
are deleted in v2. The interval solver, propagator, hypothesis, and review
modules replace their functionality.
