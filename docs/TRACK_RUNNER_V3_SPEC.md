# Track runner v3 specification

Status: v3, reflects implemented modules as of 2026-03-13

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

v3 adds support for approximate seeds with uncertain bounding boxes,
interval-length-aware confidence scoring, post-fuse refinement with soft
spatial priors, multi-seed anchored interpolation, a PySide6-based annotation
UI, and a configurable encode filter pipeline.

See [docs/TRACK_RUNNER_DESIGN.md](docs/TRACK_RUNNER_DESIGN.md) for design
philosophy. See [docs/TRACK_RUNNER_HISTORY.md](docs/TRACK_RUNNER_HISTORY.md)
for evolution from v1 and v2.

## Module map

### Core engine

| Module | Lines | Purpose |
| --- | --- | --- |
| `track_runner.py` | ~8 | Thin entry point: `import cli; cli.main()` |
| `cli.py` | ~1200 | Argument parsing, multi-pass orchestration, quality report |
| `config.py` | ~350 | Config YAML loading, defaults, schema validation |
| `state_io.py` | ~200 | JSON read/write for seeds, diagnostics, and intervals |
| `detection.py` | ~300 | YOLOv8n ONNX person detection |
| `propagator.py` | ~400 | Frame-to-frame optical flow + patch correlation tracking |
| `hypothesis.py` | ~250 | Competing path generation for ambiguous intervals |
| `scoring.py` | ~250 | Interval confidence: agreement, identity, competitor margin |
| `interval_solver.py` | ~1400 | Per-interval bounded solving, fusion, refinement, anchoring |
| `review.py` | ~200 | Weak span identification and seed target generation |
| `seeding.py` | ~620 | Interactive seed UI, jersey color/histogram extraction |
| `seed_editor.py` | ~100 | Seed review and editing UI entry point |
| `crop.py` | ~340 | Adaptive crop trajectory from confidence-weighted positions |
| `encoder.py` | ~470 | Video decode (OpenCV), crop apply, ffmpeg encode |

### UI package (`ui/`)

| Module | Purpose |
| --- | --- |
| `workspace.py` | `AnnotationWindow(AppShell)` Qt main window with mode toolbar |
| `frame_view.py` | `FrameView(QGraphicsView)` with cursor-anchored zoom |
| `seed_controller.py` | `SeedController(QObject)` for seed collection |
| `target_controller.py` | `TargetController(SeedController)` for targeted refinement |
| `edit_controller.py` | `EditController(QObject)` for seed review and editing |
| `overlay_items.py` | `RectItem`, `PreviewBoxItem`, `ScaleBarItem` overlays |
| `status_presenter.py` | `StatusPresenter` QLabel for seed status display |
| `theme.py` | Dark/light/system theme support |
| `actions.py` | `make_action()` factory for toolbar actions |
| `app_shell.py` | `AppShell(QMainWindow)` base class with theme toggle |

### Shared utilities (`common_tools/`)

| Module | Purpose |
| --- | --- |
| `tools_common.py` | Video metadata, time formatting, shared helpers |
| `frame_reader.py` | OpenCV video frame reader with seek |
| `emwy_yaml_writer.py` | EMWY YAML output writer |
| `frame_filters.py` | Display-only and encode image filters |

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
encoder -> cv2, numpy, crop, common_tools.frame_filters
config -> yaml, os
state_io -> json, os
ui.workspace -> ui.frame_view, ui.app_shell, ui.actions
ui.seed_controller -> ui.overlay_items, ui.status_presenter
ui.edit_controller -> ui.overlay_items, ui.status_presenter
```

## CLI subcommands

The tool supports 7 modes (default is `run`):

| Mode | Purpose |
| --- | --- |
| `run` | Full pipeline: seed, solve, encode |
| `seed` | Collect seeds interactively, save, exit |
| `edit` | Review, fix, and delete existing seeds |
| `target` | Add seeds at weak interval frames with FWD/BWD overlays |
| `solve` | Full re-solve: clears prior results, solves all intervals |
| `refine` | Re-solve only changed/new intervals, reuse prior results |
| `encode` | Encode cropped video from existing trajectory |

### CLI flags

| Flag | Dest | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `-i`, `--input` | `input_file` | str | required | Input video path |
| `-o`, `--output` | `output_file` | str | `{stem}_tracked{ext}` | Output path |
| `-c`, `--config` | `config_file` | str | `{input}.track_runner.config.yaml` | Config YAML |
| `--seed-interval` | `seed_interval` | float | config value | Override seeding interval |
| `--aspect` | `aspect` | str | config value | Override crop aspect ratio |
| `-d`, `--debug` | `debug` | flag | False | Draw debug overlay on output |
| `--refine` | `refine` | str | `suggested` | Refinement mode |
| `--gap-threshold` | `gap_threshold` | float | 15.0 | Min seedless gap for gap mode |
| `--time-range` | `time_range` | str | None | Restrict to `HH:MM:SS-HH:MM:SS` |
| `--ignore-diagnostics` | `ignore_diagnostics` | flag | False | Re-solve from seeds |
| `-F`, `--encode-filters` | `encode_filters` | str | config value | Comma-separated filter names |
| `-s`, `--severity` | `severity` | str | None | Filter by severity (edit/target) |

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
  encoder.py: apply crop, resize, optional filters, ffmpeg encode
  audio mux from original
  -> final output video
```

## Drawing modes and seed statuses

The user annotates each seed frame using one of four drawing modes.

### The four drawing modes

- **Visible**: the runner is fully visible. The user draws a precise torso box.
  Exact torso position and jersey color are known. Full tracking confidence.
- **Partial**: the runner is partially hidden (another runner crossing, a pole,
  etc.) but the torso position is identifiable. Precise torso box drawn.
  Jersey hue is unreliable. Used as an interval endpoint but excluded from the
  appearance model.
- **Approximate** (`a` key): the runner is fully hidden behind an obstruction
  and the exact torso position cannot be determined. The user draws a larger
  area indicating the general region. Stored as `status: "approximate"` with
  `torso_box` holding the drawn area. No `jersey_hsv`. Used as a weak interval
  endpoint (conf=0.3). Trajectory near the seed is erased because position is
  uncertain.
- **Not in frame** (`n` key): the runner has physically left the camera frame.
  Confirmed off-screen past the edge. No position data. Triggers trajectory
  erasure within the erase radius.

### Approximate vs not_in_frame

These are distinct conditions. `not_in_frame` means the runner is confirmed
outside the frame boundary (off-screen). Approximate means the runner is within
the frame but fully hidden, and the user draws a general area. The approximate
area gives the solver a directional hint; `not_in_frame` has no location at all.

### Properties by drawing mode

| Property | visible | partial | approximate | not_in_frame |
| --- | --- | --- | --- | --- |
| Status value in JSON | `visible` | `partial` | `approximate` | `not_in_frame` |
| Box type | precise torso | precise torso | larger approximate area | none |
| Has `torso_box` | YES | YES | YES | NO |
| Has `jersey_hsv` | YES | unreliable | NO | NO |
| Runner in frame | YES | YES | YES (hidden) | NO (off-screen) |
| Interval endpoint | YES | YES | YES (weak, conf=0.3) | NO |
| Appearance model | YES | NO | NO | NO |
| Trajectory erasure | NO | NO | YES (0.5 s) | YES (1.0 s) |
| Default confidence | 1.0 | 1.0 | 0.3 | n/a |

## Valid seed modes

Seeds carry a `mode` field recording how they were created.

| Mode | Description |
| --- | --- |
| `initial` | First-pass seeding at regular intervals |
| `suggested_refine` | Refinement at solver-suggested weak-span frames |
| `interval_refine` | Refinement at evenly spaced frames across all intervals |
| `gap_refine` | Refinement at midpoints of large seedless gaps |
| `target_refine` | Targeted refinement via the target controller UI |
| `bbox_polish` | YOLO or consensus polish applied during seed editing |
| `edit_redraw` | Seed redrawn by user during editing |
| `solve_refine` | Solver-generated refinement |
| `interactive_refine` | Interactive refinement during a session |

## Core algorithm: bounded interval solver

The interval solver treats each inter-seed span as an independent bounded
problem. Seeds are hard anchors. Within each interval the solver runs forward
propagation (from the left seed) and backward propagation (from the right
seed), then fuses the two tracks into a scored result.

### Forward and backward propagation

`propagator.py` advances a bounding box one frame at a time using two
complementary signals:

1. **Lucas-Kanade optical flow**: Shi-Tomasi features (up to 50 corners,
   quality 0.01, min distance 5, block size 5) tracked with LK pyramidal
   flow (window 15x15, 3 pyramid levels, 30 iterations, epsilon 0.01).
   Requires at least 4 valid flow vectors.

2. **Patch correlation**: Template matching of the previous torso crop
   against a search region (20 px margin around predicted position).

The two estimates are blended using scale-gated weights:

| Runner height | Flow weight | Correlation weight | Rationale |
| --- | --- | --- | --- |
| > 60 px (large) | 0.4 | 0.6 | Appearance reliable |
| 30-60 px (medium) | 0.6 | 0.4 | Balanced |
| < 30 px (small) | 1.0 | 0.0 | Appearance is noise |

**Stationary lock**: When 5 consecutive frames show near-zero displacement
(< 3% of box dimension), the propagator locks position to prevent drift
from camera jitter.

**Confidence decay**: Each propagated frame decays confidence by 0.97.
Floor is 0.1. Seeds start at 1.0 (visible/partial) or 0.3 (approximate).

**Per-frame state**:

```
{"cx": float, "cy": float, "w": float, "h": float,
 "conf": float, "source": str}
```

`source` values: `seed`, `detected`, `propagated`, `absent`.

### Confidence-weighted fusion

After forward and backward propagation the interval solver fuses the two
tracks. At each frame, if the Dice overlap coefficient >= 0.3 (boxes agree),
the fused position is a confidence-weighted average:

```
fused_cx = (fwd_conf * fwd_cx + bwd_conf * bwd_cx) / (fwd_conf + bwd_conf)
```

Same for `cy`, `w`, `h`. Fused confidence = `Dice * max(fwd_conf, bwd_conf)`.

When Dice < 0.3 (disagreement), the higher-confidence direction is used
directly.

### Post-fuse refinement pass

After the first-pass independent FWD/BWD propagation and fusion, a refinement
pass re-propagates each interval using the fused track as a soft spatial prior.
This reduces mid-interval wobble where both passes had decayed confidence.

Pipeline order:

1. Independent FWD/BWD propagation (first pass)
2. Fuse (first pass)
3. **Refinement**: re-run FWD/BWD with fused track as soft prior, re-fuse
4. Anchor-to-seeds regularization
5. Stamp confidence + erasure
6. Crop

The refinement pass is always on. It does not affect identity scoring or
seed recommendation, which use the first-pass diagnostic signal.

Prior weight formula:

```
prior_weight = min(0.3, fused_conf * 0.3)
```

The prior only affects `cx`/`cy`, not `w`/`h`. Low-confidence fused frames
produce near-zero prior weight, preventing error reinforcement.

At each propagated frame:

```
new_cx = (1 - prior_weight) * flow_cx + prior_weight * prior_cx
new_cy = (1 - prior_weight) * flow_cy + prior_weight * prior_cy
```

The prior is keyed by absolute frame index to eliminate alignment bugs
between forward and backward passes.

### Multi-seed anchored interpolation

After stitching intervals, a post-stitch correction pass fits a local
windowed curve through nearby seeds and nudges low-confidence frames toward
the fit. This exploits the weak kinematic prior that distance runners exhibit
locally smooth image-plane motion.

`_collect_anchor_knots()` and any seed-to-trajectory conversion must use
top-level `cx`/`cy` or compute center from `torso_box` top-left coordinates;
`torso_box[0:2]` are never center coordinates.

**Seed window**: the nearest 4 seeds on each side of the current frame.
`CubicSpline` with natural boundary conditions fits `cx`/`cy`; `PCHIP` in
log-space fits `w`/`h` to avoid overshoot on scale changes. With only 2 knots,
the fit degenerates to linear interpolation.

**Blend gains** scale with uncertainty:

- `cx`/`cy` blend: `0.5 * (1 - conf)^2`
- `w`/`h` blend: `0.3 * (1 - conf)^2`

Visible seeds are hard-pinned. Partial seeds guide the fit but are not pinned.

**Displacement caps**:

- `dx` capped at 25% of `w`
- `dy` capped at 25% of `h`
- `dw` capped at 15% of `w`
- `dh` capped at 15% of `h`

**Proximity skip**: frames within 7 of any seed (~0.23 s at 30 fps) are not
corrected. No extrapolation past the first and last seed.

**Deduplication**: when multiple seeds fall on the same frame, visible seeds
are preferred over partial. Among same-status seeds, the larger `torso_box`
area wins.

### Hypothesis generation

For intervals where propagator confidence drops below thresholds,
`hypothesis.py` generates competing path candidates. Up to 3 competitor
tracks are maintained. Competitors are YOLO detections that overlap the
target by IoU >= 0.3, with minimum height 20 px. Each competitor is matched
across frames by IoU >= 0.2.

**Competitor identity scoring** is scale-gated:

| Runner height | Method |
| --- | --- |
| < 30 px | return 0.5 (uninformative) |
| 30-60 px | HSV comparison only |
| >= 60 px | 60% HSV + 40% template correlation |

**Competitor margin**: `0.7 * position_distance + 0.3 * appearance_distance`.
A margin < 0.2 flags `likely_identity_swap`.

### Trajectory erasure

When the runner is off-screen or fully hidden, the solver erases trajectory
data near that frame.

| Drawing mode | Erase radius | Endpoint | Reason |
| --- | --- | --- | --- |
| visible | no erasure | yes (accurate) | precise torso box |
| partial | no erasure | yes (accurate) | precise torso box |
| approximate | 0.5 s | yes (weak) | uncertain position |
| not_in_frame | 1.0 s | no | runner off-screen |

Erasure decisions are centralized in `_apply_trajectory_erasure()`. Both
solve and encode paths pass all seeds; the function decides what to erase.

### Cyclical prior detection

`_detect_cyclical_prior()` looks for repeating patterns in the trajectory
(minimum 900 frames, period 25-40 s). When a cyclical period is detected, it
can inform seed placement and gap analysis.

## Confidence scoring

`scoring.py` scores each interval using three aggregate metrics.

### Confidence decision grid

| Agreement | Separation (margin) | Confidence | Notes |
| --- | --- | --- | --- |
| > 0.5 | > 0.5 | `high` | Trusted |
| > 0.5 | > 0.2 | `good` | Acceptable |
| > 0.2 | > 0.1 | `fair` | Borderline |
| else | | `low` | Needs seed |

Additional failure reasons regardless of confidence:

- `likely_identity_swap`: competitor margin < 0.2
- `weak_appearance`: identity score < 0.4

### Interval-length-aware scoring

For intervals of 5 frames or fewer, the confidence tier is promoted by one
level (low to fair, fair to good). The promotion never reaches high. This
compensates for inherent noise in FWD/BWD agreement on very short intervals.

### Interval severity classification

`review.py` classifies intervals for refinement prioritization:

- **high**: agreement < 0.2, or `likely_identity_swap`, or (margin < 0.2 and
  agreement < 0.4)
- **medium**: agreement < 0.4, or margin < 0.2 with good agreement
- **low**: everything else

Short-interval demotion: intervals under 10 frames are unconditionally
demoted from high to medium.

Duration-based promotion: intervals longer than 10 s are promoted one level
(low to medium, medium to high).

## Refinement modes

The `--refine` flag controls which intervals trigger a new seeding round.

### suggested

Default mode. `review.py` identifies the worst intervals by confidence and
failure reason. Seed targets are placed at midpoints of low-confidence
intervals. `likely_identity_swap` intervals get targets at `start + len // 3`.

### interval

Re-seeds every inter-seed interval regardless of confidence.

### gap

Re-seeds only the largest seedless gaps (controlled by `--gap-threshold`,
default 15 s).

## Crop controller

`crop.py` operates as a virtual camera operator, producing smooth crop
trajectories from the confidence-weighted tracker output.

### Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `crop_mode` | `smooth` | Crop algorithm: `smooth` (online lag-based) or `direct_center` (offline centering) |
| `target_fill_ratio` | 0.30 | Subject height / crop height |
| `smoothing_attack` | 0.15 | Alpha for large position errors (smooth mode only) |
| `smoothing_release` | 0.05 | Alpha for small position errors (smooth mode only) |
| `max_crop_velocity` | 30.0 | Max px/frame crop movement (smooth mode only) |
| `min_crop_size` | 200 | Minimum crop dimension in pixels |
| `deadband_fraction` | 0.02 | Fraction of crop size for deadband (smooth mode only) |
| `crop_post_smooth_strength` | 0.0 | EMA alpha for position smoothing (0 = disabled) |
| `crop_post_smooth_size_strength` | 0.0 | EMA alpha for size smoothing (0 = auto in smooth mode) |
| `crop_post_smooth_max_velocity` | 0.0 | Final center velocity cap after smoothing (0 = no cap) |

**Alpha floor**: smoothing alpha is clamped to `max(alpha, 0.02)` so the
crop always responds, even at low confidence.

**Velocity capping**: per-frame crop displacement clamped to 30 px with sign
preservation.

### Direct-center crop mode

`crop_mode: direct_center` replaces the online `CropController` with a pure
offline signal-processing pipeline. It centers the crop directly on the dense
solved trajectory (post-propagation, post-fusion, post-refinement,
post-anchoring), then smooths with forward-backward EMA. No deadband, no
attack/release alpha, no online state.

This mode treats telephoto crop generation as a reframing problem: the operator
already kept the runner roughly centered, and the system refines that framing.
Recommended for telephoto footage where the runner fills most of the frame.

Pipeline:

1. Extract `cx`, `cy`, `h` from solved trajectory
2. Compute crop size from `h / fill_ratio` and aspect ratio
3. Apply forward-backward EMA to position (`crop_post_smooth_strength`) and
   size (`crop_post_smooth_size_strength`)
4. Guard minimum positive size from `crop_min_size`
5. Reconstruct and clamp rectangles to frame bounds
6. Optional final velocity cap on center
   (`crop_post_smooth_max_velocity`)
7. Re-clamp to frame bounds
8. Convert to integer tuples using `round()` for crop stability

The `smooth` mode (existing `CropController`) remains the default in M1.
Set `crop_mode: direct_center` explicitly in config to use the new mode.

### Post-smoothing (offline)

An optional offline forward-backward EMA smoother runs after the online crop
pass. This reduces residual crop jitter for telephoto footage where small
bbox noise translates to visible crop movement.

The smoother decomposes crop rectangles into center (cx, cy) and size (w, h)
signals, applies forward-backward EMA independently, reconstructs
rectangles, clamps to frame bounds, and applies an optional final velocity
cap on the center.

Pipeline order:

1. Online crop pass (existing `CropController`)
2. Optional forward-backward EMA on cx, cy (position) and w, h (size)
3. Reconstruct rectangles from smoothed center + size
4. Clamp to frame bounds
5. Optional final velocity cap on center only
6. Re-clamp to frame bounds

### Telephoto preset

For tight-zoom footage (e.g., 600mm lens), add these values to the
`processing` section:

```yaml
processing:
  crop_mode: direct_center
  crop_post_smooth_strength: 0.10
  crop_post_smooth_size_strength: 0.05
  crop_post_smooth_max_velocity: 12.0
  crop_max_velocity: 12.0
```

Lower alpha means heavier smoothing. Position alpha 0.10 provides moderate
stabilization. Size alpha 0.05 smooths zoom changes more aggressively.
The final velocity cap of 12.0 px/frame is a safety rail on the rendered
path.

**Output resolution**: defaults to the median of all crop rectangle dimensions.
Can be overridden with `output_resolution: [width, height]` in config.

## Detection

YOLOv8n via ONNX runtime. No HOG fallback.

| Parameter | Value |
| --- | --- |
| Model | `yolov8n.onnx` |
| Input size | 640 px |
| Confidence threshold | 0.25 |
| NMS threshold | 0.45 |
| Class | person (COCO class 0) |
| ROI padding | 3.0x bbox size |
| Min ROI crop | 320 px |

## Encode pipeline

`encoder.py` decodes frames with OpenCV, applies crop rectangles, optionally
runs filters, and encodes with ffmpeg.

### Encode filters

Two filter engines, applied in order: OpenCV per-frame filters run first,
then ffmpeg temporal filters.

**OpenCV filters** (per-frame):

| Filter | Parameters |
| --- | --- |
| `bilateral` | d=9, sigmaColor=75, sigmaSpace=75 |
| `clahe` | clipLimit=2.0, tileGridSize=(8, 8) |
| `sharpen` | gain=1.5 |
| `denoise` | h=10, hColor=10, template=7, search=21 |
| `auto_levels` | 1st-99th percentile per channel |

**FFmpeg filters** (temporal):

| Filter | Description |
| --- | --- |
| `hqdn3d` | High-quality 3D denoiser |
| `nlmeans` | Non-local means denoiser |

When any encode filter is active, resize uses `cv2.INTER_LANCZOS4` instead
of `cv2.INTER_LINEAR`.

Configure via `--encode-filters bilateral,hqdn3d` on CLI or
`processing.encode_filters` in config YAML.

### Display-only filters

`common_tools/frame_filters.py` provides display-only filters for the
annotation UI. These do not affect detection or color extraction.

Presets: `none`, `bilateral`, `clahe`, `bilateral+clahe`, `sharpen`,
`edge_enhance`.

### Debug overlay

When `-d` is set, the encoder draws tracking data on output frames. Colors and
styles are loaded from [emwy_tools/track_runner/overlay_styles.yaml](emwy_tools/track_runner/overlay_styles.yaml)
via `overlay_config`. Semantic roles:

- **Accepted box**: solid, colored by tracking source (seed status on seed frames)
- **Forward track**: dashed, prediction color
- **Backward track**: dashed, prediction color
- **Competitor**: solid, competitor color
- **Lost/no data**: lost color for status text

All elements scale with output resolution and box size. Transparency values
(box blending, text blending) are configured in `encoder_overlay` section of
the YAML.

### Parallel encoding

`encode_cropped_video_parallel()` splits the video into segments and encodes
with 4 worker processes, then concatenates.

### Video output

| Parameter | Default |
| --- | --- |
| Codec | libx264 |
| CRF | 18 |
| Container | inferred from extension |

## Annotation UI

PySide6-based annotation window replacing OpenCV popup loops.

### Window structure

`AnnotationWindow(AppShell)` contains `FrameView(QGraphicsView)` as central
widget, with a mode toolbar and status bar. Mode toolbar has mutually-exclusive
Seed/Target/Edit actions.

### Mode accent colors

| Mode | Color |
| --- | --- |
| Seed | `#0D9488` (teal) |
| Target | `#3B82F6` (blue) |
| Edit | `#8B5CF6` (purple) |

### Status colors

| Status | Color |
| --- | --- |
| visible | `#22C55E` (green) |
| partial | `#F59E0B` (amber) |
| approximate | `#F97316` (orange) |
| not_in_frame | `#94A3B8` (slate) |

### Zoom

Cursor-anchored zoom: 1.25x per wheel tick, clamped 0.5x to 10x. Scale bar
appears in top-right corner when zoom > 1.05x.

### Scrub step sizes

`[` and `]` keys cycle through presets: 0.1s, 0.2s, 0.5s, 1.0s, 2.0s, 5.0s.
Hold Alt for 5x multiplier, Shift for 2x multiplier.

### Keyboard shortcuts (seed controller)

| Key | Action |
| --- | --- |
| ESC, q | Quit |
| SPACE | Skip frame |
| LEFT/RIGHT | Navigate frames |
| `[`, `]` | Decrease/increase step size |
| n | Mark not_in_frame |
| p | Mark partial |
| a | Draw approximate area |
| f | Use FWD/BWD average position |
| mouse drag | Draw torso box |

### Theme

`apply_theme(app, mode)` supports dark, light, and system modes. Dark palette:
bg `#0F0F23`, text `#F8FAFC`, accent `#E11D48`.

## File formats

All companion files derive from the input filename stem.

### Config YAML

Path: `{input}.track_runner.config.yaml`

Header key `track_runner` must equal `2`.

```yaml
track_runner: 2
detection:
  model: "yolov8n"
  confidence_threshold: 0.25
processing:
  crop_aspect: "1:1"
  crop_fill_ratio: 0.30
  video_codec: "libx264"
  crf: 18
  encode_filters: []
  output_resolution: [1280, 720]  # optional
```

### Overlay styles YAML

Path: `emwy_tools/track_runner/overlay_styles.yaml`

Centralized visual palette for all UI and encoder overlays. Loaded once per
process by `overlay_config.py`. Semantic layers:

- `seed_status`: annotation state colors (visible, partial, approximate, not_in_frame)
- `predictions`: algorithm output colors (forward, backward)
- `tracking_source`: debug overlay source colors (detection, propagated, merged, etc.)
- `workspace_mode`: editing mode accent colors (seed, target, edit)
- `draw_mode_badge`: drawing sub-mode badge colors (approximate, partial)
- `preview_box`: user-drawn confirmation box color and opacity
- `encoder_overlay`: debug overlay blending (box_opacity, text_opacity)
- `defaults`: inherited fill_opacity, line_style, thickness_tier
- `thickness_tiers`: named scale multipliers (normal=1.0, heavy=2.0)

Visual encoding model:

- **Color** = semantic state (what the annotation means)
- **Line style** (solid/dashed) = object certainty (confirmed vs inferred)
- **Opacity/fill** = spatial extent without blocking the frame
- **Thickness** = emphasis tier (confirmed/authored vs inferred/predicted)

### Seeds JSON

Path: `{input}.track_runner.seeds.json`

Header key `track_runner_seeds` must equal `2`.

**Coordinate convention**: `torso_box` stores `[x, y, w, h]` where `x, y` is
the **top-left corner** of the bounding rectangle. The seed also carries `cx`,
`cy` (center coordinates, computed as `x + w/2`, `y + h/2`) and `w`, `h` at the
top level for direct use by the solver and encoder. Code that needs the center
must use `cx`/`cy`, never `torso_box[0]`/`torso_box[1]`.

```json
{
  "track_runner_seeds": 2,
  "video_file": "race.mov",
  "seeds": [
    {
      "frame": 150,
      "time_s": 5.0,
      "torso_box": [620, 330, 40, 60],
      "cx": 640.0,
      "cy": 360.0,
      "w": 40.0,
      "h": 60.0,
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
      "status": "approximate",
      "torso_box": [460, 240, 80, 120],
      "cx": 500.0,
      "cy": 300.0,
      "w": 80.0,
      "h": 120.0,
      "pass": 2,
      "source": "human",
      "mode": "suggested_refine"
    }
  ]
}
```

Valid `status` values: `visible`, `partial`, `approximate`, `not_in_frame`.

Legacy `"obstructed"` seeds are migrated on load: those with `torso_box`
become `"approximate"`, those without are dropped.

Valid `mode` values: `initial`, `suggested_refine`, `interval_refine`,
`gap_refine`, `target_refine`, `bbox_polish`, `edit_redraw`, `solve_refine`,
`interactive_refine`.

### Diagnostics JSON

Path: `{input}.track_runner.diagnostics.json`

Header key `track_runner_diagnostics` must equal `2`.

Contains per-interval results: forward track, backward track, fused track,
interval scores, failure reasons.

### Intervals JSON

Path: `{input}.track_runner.intervals.json`

Header key `track_runner_intervals` must equal `1`.

Stores interval fingerprints for incremental refinement. Each fingerprint
encodes start/end seed frame and position so that `refine` mode can detect
which intervals have changed.

## Key constants

| Component | Parameter | Value |
| --- | --- | --- |
| Propagator | Confidence decay/frame | 0.97 |
| Propagator | Confidence floor | 0.1 |
| Propagator | Prior weight scale | 0.3 |
| Propagator | Stationary streak threshold | 5 frames |
| Propagator | Stationary displacement fraction | 0.03 |
| Propagator | Patch search margin | 20 px |
| Propagator | Min flow features | 4 |
| Interval solver | Dice agreement threshold | 0.3 |
| Scoring | Agreement threshold (high) | > 0.5 |
| Scoring | Margin threshold (high) | > 0.5 |
| Scoring | Short interval promotion | <= 5 frames |
| Hypothesis | Min competitor height | 20 px |
| Hypothesis | Max competitors | 3 |
| Hypothesis | Target overlap IoU | 0.3 |
| Hypothesis | Competitor match IoU | 0.2 |
| Crop | Target fill ratio | 0.30 |
| Crop | Smoothing attack | 0.15 |
| Crop | Smoothing release | 0.05 |
| Crop | Max velocity | 30.0 px/frame |
| Crop | Alpha floor | 0.02 |
| Anchor | Proximity skip | 7 frames |
| Anchor | Blend scale (cx/cy) | 0.5 |
| Anchor | Blend scale (w/h) | 0.3 |
| Anchor | Max displacement (cx/cy) | 25% of dimension |
| Anchor | Max displacement (w/h) | 15% of dimension |
| Anchor | Window seeds | 4 per side |
| Erasure | Approx radius | 0.5 s |
| Erasure | Not-in-frame radius | 1.0 s |
| Review | Short interval demotion | < 10 frames |
| Review | Duration promotion threshold | 10.0 s |
| Detection | Confidence threshold | 0.25 |
| Detection | NMS threshold | 0.45 |
| Encoder | Default CRF | 18 |
