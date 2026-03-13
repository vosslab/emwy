# Track runner design philosophy

This document explains the principles behind the track runner architecture.
For the technical specification, see
[docs/TRACK_RUNNER_V3_SPEC.md](docs/TRACK_RUNNER_V3_SPEC.md). For evolution
history, see [docs/TRACK_RUNNER_HISTORY.md](docs/TRACK_RUNNER_HISTORY.md).

## Core principle

> Human establishes identity. Machine interpolates geometry.

The user identifies who the runner is. The machine figures out where the runner
is between those identifications. This division is fundamental: people are good
at recognition, machines are good at frame-to-frame geometry. Mixing the two
roles leads to the tracker either losing the runner (too much machine autonomy)
or requiring constant human supervision (too little).

## Why bounded interval solving

Seeds are hard anchors, not suggestions. Each inter-seed interval is solved
independently with forward and backward propagation from the bracketing seeds.

Benefits of this design:

- **Parallelizable**: intervals have no cross-talk, so they can be solved
  concurrently.
- **Debuggable**: a bad interval can be diagnosed in isolation by inspecting
  its forward and backward tracks.
- **Incrementally refinable**: adding a seed splits one interval into two.
  Only the two new intervals need re-solving.
- **Disagreement is signal**: when forward and backward propagation disagree,
  that disagreement honestly reflects uncertainty. The solver does not hide it.

## Signal hierarchy

Person detection (YOLO) is the hero signal. It provides the most reliable
position estimate when a detection exists.

When detection is absent, the propagator bridges the gap using optical flow
and patch correlation, with confidence decaying per frame.

Jersey color is size-gated:

- **> 60 px** (runner height): color is rock-solid (hue std < 6). Appearance
  gets 60% weight in the blend.
- **30-60 px**: color is unreliable. Balanced 40% weight.
- **< 30 px**: color is pure noise. Appearance is suppressed entirely.

After 1-2 laps on a track, cyclical priors become available. The runner
returns to roughly the same image-plane positions every lap period.

## Dual scoring philosophy

The first-pass FWD/BWD propagation is intentionally independent. The
disagreement between directions is the honest uncertainty probe. This raw
diagnostic signal drives:

- Interval confidence scoring (agreement, identity, competitor margin)
- Seed recommendation (which intervals need more seeds)
- Severity classification (how urgently an interval needs attention)

The refinement pass then re-propagates with the fused track as a soft prior,
producing smoother geometry for output. Refinement improves position accuracy
but must not replace the diagnostic signal. If refinement were used for
scoring, it would mask real identity ambiguity under smooth geometry.

Rule: scoring uses first-pass signal; output uses refined geometry.

## Separation of concerns

Four distinct jobs, four distinct systems:

- **Tracker** follows accurately (interval_solver, propagator, hypothesis).
  Its job is to locate the runner at every frame with honest confidence.
- **Crop** moves smoothly (crop.py). It acts as a virtual camera operator:
  exponential smoothing, velocity capping, deadband. Crop quality is about
  cinematic feel, not tracking accuracy.
- **Annotation** captures identity (UI controllers, seeding). Its job is to
  collect ground truth efficiently from the user.
- **Encoder** produces output (encoder.py). It handles decode, resize,
  optional filters, and ffmpeg encoding.

These systems communicate through well-defined interfaces (trajectory arrays,
crop rectangles, seed JSON) rather than sharing internal state.

## Annotation UI principles

### Fast-pick first

Keyboard shortcuts are the primary path. The user should be able to annotate a
frame in under 2 seconds: navigate with arrow keys, draw a box with the mouse,
move to the next frame. Toolbar buttons exist for discovery, not daily use.

### Write-on-commit

Every annotation change is saved immediately. There is no undo stack. The
correction model is re-annotation: if you made a mistake, edit the seed.
This eliminates a class of bugs around session state, unsaved changes, and
crash recovery.

### Workspace, not project manager

The annotation window is a workspace around a frame stream. It shows the
current frame, the current seed status, and overlay previews. It does not
manage files, projects, or render queues. Mode switching (seed, target, edit)
rearranges the workspace without restarting.

## Trajectory erasure philosophy

When the runner is genuinely not visible (hidden or off-screen), the solver
must not pretend to know where they are. Erasing trajectory near those frames
prevents the propagator from confidently tracking a wrong person through a gap.

Approximate seeds provide a directional hint (the user drew a general area)
but the position is still uncertain, so trajectory is erased in a short radius.
Not-in-frame seeds have no position at all, so a longer erasure radius is used.

The erasure decision is centralized in one function. Both solve and encode
paths pass all seeds; the function decides what to erase. This prevents
divergence between what the solver computed and what the encoder renders.

## What this tool is not

- **Not a general object tracker.** It tracks a single pre-identified subject
  in footage where the operator already framed the runner. Multi-object
  tracking is a different problem.
- **Not a search-and-discover tool.** The user tells the tool who to follow.
  The tool does not search for interesting subjects.
- **Not a template matcher.** Runner appearance changes with pose, distance,
  lighting, and occlusion. Pure template matching fails on these changes.
  The tool uses detection + motion + gated appearance instead.

## Visual encoding principles

Overlay visuals use a consistent semantic encoding across the UI and encoder
debug output. The mapping is defined in `overlay_styles.yaml` and loaded by
`overlay_config.py`.

- **Color** conveys semantic state: what the annotation means (seed status,
  prediction direction, tracking source). Each semantic role has one color
  used identically in the UI and encoder.
- **Line style** conveys certainty: solid lines for confirmed/user-authored
  positions, dashed lines for inferred/predicted positions.
- **Opacity** conveys spatial extent: low fill opacity (~6%) lets the video
  show through overlay boxes without obscuring the frame.
- **Thickness** conveys emphasis tier: heavy (2x) for user-authored seed
  boxes, normal (1x) for algorithm predictions. Emphasis is about authorship,
  not state.
