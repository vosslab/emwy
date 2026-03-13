# Track runner history

This document traces the evolution of the track runner tool from its original
Kalman-based design through the current interval solver architecture. Key
design decisions and their rationale are preserved here for future reference.

For the current technical specification, see
[docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md). For design
principles, see [docs/TRACK_RUNNER_DESIGN.md](docs/TRACK_RUNNER_DESIGN.md).

## v1: Kalman-based tracker (2026-03-09 to 2026-03-11)

The original design used YOLO person detection combined with a 7-state Kalman
filter (cx, cy, w, h, vx, vy, vh) with log-height for scale representation.
Bidirectional forward and backward passes were merged by picking the direction
with higher confidence at each frame.

### What worked

- The overall concept of seeding from user-drawn torso boxes
- YOLO person detection as the primary signal
- Interactive seeding UI with jersey color extraction
- Adaptive crop with exponential smoothing

### What did not work

- **Placeholder scoring**: 3 of 6 scoring terms were hardcoded at 0.5 and
  never implemented (path prior, motion compensation, reacquisition)
- **Size estimation**: tracker bounding boxes were 9-13x larger than the
  actual runner (median 8.8x too large)
- **YAML diagnostics**: 974 KB to 1.5 MB for a 4-minute video. Wrong format
  for per-frame data
- **Simple max-confidence merge**: picking the higher-confidence direction
  discarded useful signal from the lower-confidence direction
- **Covariance stability**: Kalman covariance inversion had numerical issues

### Modules planned but never built

- `path_prior.py`: motion priors based on track geometry
- `reacquisition.py`: state machine for re-finding a lost runner
- `motion_compensation.py`: camera motion estimation
- `report.py`: standalone quality reporting

### Measurement study

A seed variability study on two test videos (137s and 263s, 30fps, 1280x720)
quantified the challenges:

- Torso area varied 80 to 27,540 px squared (344x ratio)
- Jersey color was reliable only above 60 px runner height
- Runner covered 65-77% of frame width over a session
- Lap period was stable at 30-32 seconds
- The start-line phase (2-4 s stationary) had 40 px camera jitter

These findings drove the scale-gated color model and stationary lock in v2/v3.
The full study is archived at
[docs/archive/SEED_VARIABILITY_FINDINGS.md](docs/archive/SEED_VARIABILITY_FINDINGS.md).

## v2: Interval solver (2026-03-11)

v2 replaced the Kalman filter with a bounded interval solver. The core
insight was that seeds should be hard anchors, not initial conditions for a
filter. Each inter-seed interval is an independent bounded problem.

### Key architectural changes

- **Propagator** replaced Kalman predict/update with lightweight frame-to-frame
  local search using optical flow and patch correlation
- **Confidence-weighted fusion** replaced simple max-confidence selection.
  Forward and backward tracks are blended by confidence ratio when they agree
  (Dice >= 0.3)
- **Hypothesis generation** for ambiguous intervals: up to 3 competitor tracks
  are maintained to detect identity swaps
- **Structured review**: `review.py` identifies weak intervals and suggests
  seed targets. Replaces the manual `--add-seeds` approach
- **JSON serialization**: seeds and diagnostics moved from YAML to JSON,
  reducing file sizes by 3-5x
- **HOG fallback removed**: YOLO is required

### Design decisions

- **FWD/BWD independence**: the two propagation directions must not communicate
  during the first pass. Their disagreement is the primary uncertainty signal.
  Cross-talk would smooth away real ambiguity.
- **Three-metric scoring**: agreement (FWD/BWD Dice overlap), identity (jersey
  color match), and competitor margin (separation from nearest alternative).
  All three contribute to the confidence classification.

## v3: PySide6 UI + approximate seeds (2026-03-12 to present)

v3 extended the interval solver with support for uncertain seed positions, a
native Qt annotation UI, and several quality-of-life improvements.

### PySide6 annotation window

Replaced all OpenCV `cv2.namedWindow` popup loops with a persistent
PySide6-based `AnnotationWindow`. The migration was driven by limitations of
the OpenCV approach: no proper event loop, no theme support, no composited
overlays, and difficulty adding toolbar controls.

Design principle: "fast-pick first". Every annotation action has a keyboard
shortcut. Toolbar buttons exist for discovery. The window is a workspace
around a frame stream, not a project manager.

Controller pattern: `SeedController`, `TargetController`, and
`EditController` handle their respective modes as QObject event filters.
Mode switching rearranges the workspace without restarting.

Write-on-commit semantics: every annotation change saves immediately. No
undo stack. Re-editing is the correction model.

### Four drawing modes

Added approximate mode (`a` key) for fully hidden runners. The user draws a
larger area indicating the general region. Stored as `status: "approximate"`
with `torso_box`. Used as a weak interval endpoint (conf=0.3) but trajectory
is erased within 0.5 s because position is uncertain.

Previously, hidden runners could only be marked `not_in_frame` (off-screen)
which provided no position hint at all. Approximate seeds give the solver a
directional guide through occlusion gaps.

The four modes: visible, partial, approximate, not_in_frame. See
[docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md) for the full
property table.

### Interval-length-aware confidence

Short intervals (5 frames or fewer) get promoted one confidence tier. The
FWD/BWD propagator barely advances on these spans, making agreement metrics
unreliable. Without promotion, densely-seeded regions produced many false
"low confidence" intervals that wasted refinement effort.

Short intervals (under 10 frames) are also unconditionally demoted from
high to medium severity, because FWD/BWD metrics are noisy and high severity
would waste seed-targeting effort.

### Post-fuse refinement pass

After independent FWD/BWD propagation and fusion, a refinement pass
re-propagates with the fused track as a soft spatial prior (weight capped
at 0.3, scaled by fused confidence). This reduces mid-interval wobble where
both directions had decayed confidence and drifted independently.

The refinement pass only affects output geometry. Scoring and seed
recommendation still use the first-pass diagnostic signal. This preserves
the disagreement-as-signal principle from v2.

### Multi-seed anchored interpolation

Post-stitch correction fits local windowed splines (CubicSpline for position,
PCHIP in log-space for size) through nearby seeds and nudges low-confidence
frames toward the fit. Visible seeds are hard-pinned; partial seeds guide
but are not pinned. Displacement caps and a proximity skip zone prevent
over-correction.

### Consolidated trajectory erasure

Erasure logic was unified into `_apply_trajectory_erasure()` after a bug
where the solve path and encode path made different erasure decisions. Now
both paths pass all seeds and the function decides what to erase based on
status and torso_box presence.

### Encode filter pipeline

Added configurable filter pipeline for encode output: OpenCV per-frame
filters (bilateral, clahe, sharpen, denoise, auto_levels) run first, then
ffmpeg temporal filters (hqdn3d, nlmeans). Activated by cropping into noisy
source footage where artifacts amplify.

### Display-only frame filters

Added bilateral, CLAHE, sharpen, and edge-enhance filters to the annotation
UI to help annotators see detail in difficult footage. Filters are
display-only and do not affect YOLO detection or jersey color extraction.

### Visual semantics centralization

Visual styles were previously scattered across 6+ files with inconsistent
colors between UI and encoder (e.g. seed visible was `#22C55E` in UI but
`(0,255,0)` BGR in encoder). A YAML semantic palette
(`overlay_styles.yaml`) now serves as the single source of visual truth.
The config captures shared overlay semantics (color, line style, opacity,
thickness tier), not low-level rendering details (dash patterns, font sizes,
DPI math).

### common_tools package

Shared modules (`tools_common.py`, `frame_reader.py`, `emwy_yaml_writer.py`)
were consolidated into `emwy_tools/common_tools/` via `git mv`. Promotion
rule: a module earns shared location by having 2+ real consumers.

## Key design decisions (cross-version)

These decisions shaped the tool across versions and remain load-bearing:

- **Human identity, machine geometry.** The user identifies the runner; the
  machine interpolates position between identifications. This division has
  held since v1.
- **FWD/BWD must stay independent in first pass.** Coupling the two
  propagation directions during the first pass would smooth away real
  uncertainty. Coupling happens only in the post-fuse refinement, and only
  for geometry, not scoring.
- **Dual scoring.** First-pass diagnostic for seed recommendation; refined
  geometry for output quality. Prevents refinement from hiding identity
  ambiguity under smooth trajectories.
- **Write-on-commit annotation.** No undo stack. Every committed annotation
  saves immediately. Correction is re-editing, not undoing.
- **Jersey color is size-gated.** Reliable above 60 px, noise below 30 px.
  Empirically validated by the seed variability study.
- **Erasure decisions are centralized.** Both solve and encode paths pass
  all seeds to one erasure function. Pre-filtering in callers caused a
  divergence bug in early v3.

## Archived documents

- [docs/archive/TRACK_RUNNER_TOOL_PLAN.md](docs/archive/TRACK_RUNNER_TOOL_PLAN.md) -- v1 original design plan
- [docs/archive/TRACK_RUNNER_SPEC.md](docs/archive/TRACK_RUNNER_SPEC.md) -- v1 as-built specification
- [docs/archive/TRACK_RUNNER_V2_SPEC.md](docs/archive/TRACK_RUNNER_V2_SPEC.md) -- v2 interval solver spec
- [docs/archive/SEED_VARIABILITY_FINDINGS.md](docs/archive/SEED_VARIABILITY_FINDINGS.md) -- v1-era seed measurement study
