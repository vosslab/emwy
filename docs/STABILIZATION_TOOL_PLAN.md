# Stabilization tool plan

This document captures the process-level spec and an implementation plan for a standalone
"bird on a building" stabilization tool: a mostly static subject (bird) on a mostly static global
reference frame (building), with unintended camera motion.

This is global stabilization. It does not do subject tracking, reframing, or motion isolation.

Implementation direction: this ships as a standalone tool (like `tools/silence_annotator.py`), not as
new fields in the core EMWY YAML v2 authoring spec.

## Process spec

### Scope and intent

This process addresses video segments where:

- The subject of interest is mostly stationary relative to the scene.
- Camera motion is unintended (handheld shake, wind, vibration).
- Background provides sufficient visual structure for motion estimation.
- Camera motion is small enough that there is meaningful frame overlap after compensation.

Typical examples include wildlife on structures, static interviews, signage, or architecture filmed
handheld.

Mental model: the building is the global reference frame. We perform global alignment so the
building appears static, which keeps the bird watchable because it stays on the building.

This process is not designed for intentional global motion (pans, tilts, walks, fly-throughs). It
should intentionally fail when the global reference frame (building) can no longer be kept in-frame
with a stable crop (crop infeasible).

### Conceptual model

Stabilization is treated as a video-domain transform applied to a selected time range before
encoding a stabilized output file.

The transform estimates camera motion over time and applies a compensating motion so that the
scene appears stable in the output.

Audio, subtitles, and metadata are not altered by stabilization.

### Authoring semantics

- Stabilization is opt-in per tool run, and optionally per selected time range (or ranges) within a
  run.
- When enabled, the author is expressing intent: "remove unintended camera motion from this
  material, and fail if the building cannot be kept in-frame with a stable crop."
- The stabilized output is a derived source media file, not a YAML feature.
- Stabilization does not change editorial segment boundaries, titles, or timing semantics; it
  produces a better input for later editing.
- Stabilization may require cropping and constant zoom; the tool enforces a single static crop and
  fails if crop constraints cannot be met.

### Ordering guarantees

When stabilization is enabled for a tool run (on a selected time range):

1. The source time range is selected first. (default whole movie)
2. Stabilization is applied to that selected range.
3. Crop-to-content is applied (single static crop rectangle) and scaled back to output resolution.
4. The stabilized output file is encoded.

This ensures motion estimation is performed on the original camera motion, not on already-altered
frames.

Any later emwy transforms apply after stabilization because the stabilized output is used as a
normal asset.

### Determinism and reproducibility

Determinism definition for this tool:

- Identical inputs: input file identity + selected range(s) + tool settings + toolchain fingerprint.
- Identical tool version.

stabilization results must not depend on wall-clock time, system state, or unrelated segments.

Notes:

- emwy does not require bitwise reproducibility across different ffmpeg builds or platforms.
- Cache reuse must be correctness-preserving. Cache keys must include any inputs that can change the
  stabilized result (including a toolchain fingerprint).

### Border and framing behavior

Stabilization may require compensating for camera motion that moves content outside the original
frame.

The process guarantees:

- Output resolution remains constant for the stabilized output.
- No uninitialized pixels appear in the output.
- Cropping and scaling are consistent across frames.

Default strategy (recommended):

- Crop-to-content with a single, stable crop rectangle over the entire segment (static crop).
- Scale that crop back to the output resolution (a constant zoom for the segment).
- Never introduce borders in the default mode.

If no single static crop rectangle can satisfy crop constraints (including the center safe region),
stabilization must fail explicitly rather than outputting borders, jitter, or extreme zoom.

This crop-only strategy is intentionally strict. It is designed for the "bird on a building" case
where the building is the global reference frame; if the building leaves the frame, stabilization is
expected to fail.

### Performance and reuse

- Motion estimation is treated as an expensive analysis step.
- The process may reuse previously computed motion information when the inputs are identical.
- Reuse must be transparent to the author and must not affect output correctness.

### Failure behavior

If stabilization cannot be reliably computed:

- The system must fail explicitly, not silently degrade.
- The failure message should state that global stabilization is unsuitable for the material.

The process must not partially stabilize or produce visually unstable output without warning.

In particular, the system must fail when no single static crop rectangle can satisfy the crop
constraints (see "Tool surface") while keeping the building/reference frame in view.

Minimum failure decision rule (single boolean):

- Compute a single static crop rectangle for the stabilized range.
- Fail if any crop constraint (`min_area_ratio`, `min_height_px`, `center_safe_margin`) cannot be met
  by that one static crop rectangle over the entire stabilized range.

Minimum "unreliable analysis" conditions (non-exhaustive):

- Motion analysis output is empty or malformed.
- Missing transforms fraction > 0.05 (or transforms cannot be aligned to frames reliably).
- Motion path is wildly inconsistent (proxy for chasing noise), for example `mad(tx)/width > 0.5` or
  `mad(ty)/height > 0.5`.
- Scale continuity suggests zoom/non-rigid motion, for example
  `max_i(abs((s[i+1] / s[i]) - 1)) > 0.15`.

### Non-goals

This process explicitly does not attempt:

- Subject-following stabilization.
- Reframing to keep a moving subject centered.
- Rolling-shutter correction.
- Optical flow interpolation or frame synthesis.

Those are separate processes with different assumptions.

### Relationship to other emwy features

- Stabilization composes cleanly with segment titles, notes, and chapter generation.
- Stabilization is orthogonal to audio processing.
- Stabilization can be applied to assets by generating a stabilized derived media file, without
  changing the author-facing timeline model or YAML spec.

### User-facing mental model

From the author's perspective:

"I marked this segment as shaky. emwy stabilizes the camera motion, keeps the subject in place,
and gives me a clean, steady clip of the same moment."

No additional structural complexity is exposed in the project file.

## Integration approach (tool)

The goal is opt-in stabilization without changing the project's authoring model (still
`timeline.segments`) and without introducing new authoring fields in the EMWY YAML v2 spec (see
[docs/FORMAT.md](FORMAT.md)).

Instead of adding YAML fields, the tool produces derived stabilized media files that can be used as
normal `assets.video` entries in standard EMWY YAML.

Unlike `tools/silence_annotator.py` (which generates an EMWY YAML project to edit), this tool emits
an optimized stabilized video file. For "bird on a building," stabilization is media preparation,
not editing intent.

Why a separate tool is the right move:

- Stabilization is expensive analysis plus a transform. It is closer to "make a better source" than
  "edit the story."
- It avoids contaminating the main YAML spec with engine semantics and failure thresholds.
- It keeps the authoring surface human: segments stay about content, not camera math.
- It lets you stabilize once, then reuse the stabilized asset across multiple projects.

Inputs:

- Input media file.
- Output file path.
- Optional time range to stabilize (default: full file).
- Crop-only, static crop as the only supported border mode.
- Explicit failure thresholds: `min_area_ratio`, `min_height_px`, `center_safe_margin`.

Outputs:

- A stabilized video file (duration matches the selected range).
- A sidecar report (YAML or JSON) capturing:
  - parameters used
  - toolchain fingerprint
  - pass/fail
  - chosen crop rectangle and resulting zoom
  - warnings

Failure behavior:

- Exit non-zero on unsuitable footage.
- Never silently produces borders or adaptive zoom.
- Subtitles are pass-through only (copied/ignored); warn that crop can remove visible subtitle
  regions.

Example usage pattern (no new schema):

```yaml
timeline:
  segments:
    - source:
        asset: shaky_clip_stabilized
        in: "00:10.0"
        out: "00:25.0"
```

Notes:

- A derived stabilized asset is just another media file; emwy renders it normally.
- For strict "select range first" semantics, the tool should support stabilizing a specified time
  range (or a list of ranges) rather than always stabilizing an entire asset. Whole-asset
  stabilization is allowed, but it changes the semantics: the crop/fail decision then applies to the
  entire asset.

### Tool surface (draft)

The primary user knobs for the "bird on a building" case are:

- `smoothing`: steadiness vs lag/crop trade-off.
- Crop constraints: `min_area_ratio`, `min_height_px`, `center_safe_margin`.

A more detailed (still emwy-centric) tool config shape can be used, for example:

```yaml
stabilize_building: 1
settings:
  engine:
    kind: vidstab
    detect:
      shakiness: 5
      accuracy: 15
    transform:
      smoothing: 30
  crop:
    mode: crop_to_content
    min_area_ratio: 0.25
    min_height_px: 480
    center_safe_margin: 0.10
```

Notes:

- "No motion" target: the intent is a static building view. `smoothing` is not a request for residual
  motion; it is a way to smooth the estimated camera path before applying the compensating transform.
  After the transform, any remaining motion should be treated as estimation error, not a feature.
- Failure thresholds: if the crop needed to keep the building in-frame would fall below
  `min_area_ratio` of the original pixels or below `min_height_px` (for example 480p, or 240p for a
  more permissive mode), the system must fail.
- Definitions (process-level):
  - `min_area_ratio`: the area of the chosen static crop rectangle divided by the original frame
    area; it is evaluated on the crop rectangle before scaling back to the output resolution.
  - `min_height_px`: the height (in source pixels) of the chosen static crop rectangle before
    scaling back to the output resolution.
  - Both `min_area_ratio` and `min_height_px` must be satisfied simultaneously.
  - `center_safe_margin`: define a normalized "safe region" rectangle centered in the frame with
    margin `m` on all sides (x/y from `m` to `1 - m`); the safe region must remain fully inside the
    chosen crop rectangle for the entire stabilized range.

Crop feasibility principle (process-level):

- Derive a single static crop rectangle from the motion path as the intersection of per-frame valid
  pixel regions under the inverse transforms:
  - Let `T[i]` be the per-frame transform from motion estimation (translation + scale only).
  - For each frame `i`, compute `bbox[i]`, the axis-aligned bounding box of original frame pixels
    that remain valid after compensating by `T[i]`. One way to compute `bbox[i]` is to map the
    original frame corners by the inverse of `T[i]` and take their bounding box.
  - Define `crop_rect = intersect(bbox[0], bbox[1], ..., bbox[n-1])`.
  - If `crop_rect` is empty, there is no static crop that keeps the building/reference frame in all
    frames, so fail.
  - Evaluate `min_area_ratio`, `min_height_px`, and `center_safe_margin` against `crop_rect`, and
    fail if any constraint cannot be satisfied.

If motion estimation completes but `crop_rect` fails crop constraints, the footage is unsuitable for
this method and the tool must still fail (crop infeasible).

## Implementation plan (tool)

This plan focuses on behavior and guarantees. It deliberately avoids locking in a specific
stabilization engine, but it requires that any chosen engine can meet determinism and border
stability guarantees.

### Engine choice (draft)

The simplest emwy-friendly FOSS engine for this case is vid.stab via ffmpeg:

- `vidstabdetect` produces a motion analysis file (expensive).
- `vidstabtransform` applies the stabilization (cheap relative to detect).

If we implement this engine, we should treat it as one backend under
`settings.engine.kind` in the tool config, and keep the tool surface stable even if we later add
engines.

### Pipeline and ordering

For a stabilization run (on a selected range), apply transforms in this order:

1. Select the segment time range (trim).
2. Stabilization (analysis + transform).
3. Crop-to-content (single crop rectangle for the entire range) and scale back to output resolution.
4. Encode the stabilized video.

This preserves the guarantee that motion estimation sees the original camera motion, not frames that
have already been altered by later transforms.

### Two-pass execution (vid.stab)

vid.stab requires analysis then application.

Pass 1: detect motion:

```bash
ffmpeg -y -i INPUT \
  <exact same trim as pass 2> \
  -vf "vidstabdetect=shakiness=S:accuracy=A:result=TRANSFORMS.trf" \
  -f null -
```

Pass 2: apply stabilization:

```bash
ffmpeg -y -i INPUT \
  <exact same trim as pass 1> \
  -vf "vidstabtransform=input=TRANSFORMS.trf:smoothing=SM:optzoom=0:zoom=0" \
  OUTPUT
```

Important: the trim must be deterministic and identical in both passes. Avoid relying on fast
keyframe seeking (`-ss` before `-i`) unless we can prove it decodes the same frames for both passes.
Prefer accurate seeking (`-ss` after `-i`) or a filter-based trim that is driven by the project's
compiled frame numbers.

For this method, engine-level border handling and zoom are disabled (`optzoom=0`, `zoom=0`). All
framing behavior is enforced by the tool's crop-to-content step so the crop/fail rules are
consistent.

#### Pass contract

To keep performance predictable and the caching model clean, the tool's contract is:

- Exactly two video decode passes per unique analysis:
  1. motion analysis
  2. transform + crop + encode
- Crop feasibility evaluation (selecting the single static crop rectangle and checking constraints)
  operates on analysis metadata (per-frame transforms), not on decoded frames.
- Crop + scale are fused into pass 2 (no extra video pass).
- No adaptive per-frame cropping or zooming is performed.

Optional optimization (not required behavior):

- Analysis padding: analyze a small window before/after the selected range to improve edge stability,
  while still applying transform/crop/encode only to the requested range.

#### Algorithmic decisions (v1)

These are the key "how" decisions that keep the tool deterministic and implementable without
guesswork.

- Motion data adapter:
  - Treat the backend transforms file (`.trf`) as an internal engine artifact (opaque handoff
    between pass 1 and pass 2).
  - Derive a per-frame global motion path from that `.trf` using a backend adapter that emits one
    transform per frame in order (for example: vidstabtransform `debug=1` producing
    `global_motions.trf`).
  - Parse per-frame transforms into `T[i] = (dx, dy, zoom_percent)` (translation in pixels + zoom in
    percent). Reject malformed/NaN values and any unsupported components (rotation/shear).
- Frame boundary alignment:
  - Convert time range to integer frames once, and use that same frame range for both analysis and
    application.
  - Prefer filter-based trim by frame index (for example `trim=start_frame=...:end_frame=...`) over
    keyframe seeking so pass 1 and pass 2 decode identical frame sequences.
- Effective motion path:
  - Crop feasibility must be computed from the same effective motion path that will be applied
    during stabilization.
  - If the backend applies smoothing, compute crop feasibility using the same backend-smoothed
    motion path (not raw/noisy transforms) so feasibility matches the final output.
- Crop feasibility:
  - Use the `crop_rect` intersection method described under "Crop feasibility principle".
  - Apply constraints as one boolean (fail if any constraint fails).
- Unreliable analysis:
  - Use the minimum reliability checks in "Failure behavior" (missing transforms, MAD translation,
    scale continuity) in addition to crop infeasible checks.

#### Suggested implementation flow

1. Parse CLI args and tool config.
2. Resolve selected range(s) to exact frame boundaries.
3. Run motion analysis pass for each unique analysis key.
4. Derive and parse per-frame global transforms from analysis data (backend adapter) and validate.
5. Compute `crop_rect` and evaluate constraints; fail if crop infeasible.
7. Run application pass: transform + crop + scale + encode.
8. Write a sidecar report capturing inputs, toolchain fingerprint, crop, zoom, and pass/fail.

### Determinism and caching gotchas

This section folds in implementation risks that matter for meeting the process guarantees.

- Trim determinism: the detect and transform passes must decode the same frames. Use the same trim
  strategy in both passes and prefer frame-index-driven trimming to avoid timestamp drift.
- Cache key independence: cache and intermediate naming must not depend on segment index/order.
  Derive keys only from the inputs that define correctness.
- Cache key completeness: include anything that changes the frames vid.stab sees, including project
  fps normalization, any pre-stabilization scaling, pixel format, and engine parameters. If those
  change, the cached analysis must be treated as invalid.
- Crop-to-content vs engine options: the recommended mode is a single crop rectangle computed over
  the whole stabilized range (based on the stabilized transforms), then a constant scale back to the output
  resolution. This is separate from vid.stab's own border behavior, and it should be where we
  enforce "center content must remain in frame" and "crop infeasible" failure rules.
- Avoid adaptive border jitter: adaptive zoom can visibly breathe and violates the "no motion"
  target. Do not implement adaptive zoom for this method.
- Toolchain reproducibility: bitwise reproducibility may require holding the ffmpeg/vid.stab build
  constant. This plan always includes a toolchain fingerprint in cache keys and in the "identical
  inputs" definition for determinism.
- Failure behavior: vid.stab does not always provide a clean "unsuitable" signal. Add heuristics to
  detect unreliable results (empty or malformed `.trf`, extreme shifts, warnings) and fail loudly.
- Intentional global motion detection: reject pans/tilts/walks by failing when no single static crop
  rectangle satisfies the crop constraints for the whole stabilized range. This is the single source
  of truth for "crop infeasible" failure.
- Zoom detection: this method assumes no intentional zoom. If the segment cannot be represented with
  a single static crop and constant scale while meeting crop constraints, fail explicitly.

### Requirements

- Opt-in via a tool that produces derived stabilized media.
- Ordering: select time range, stabilize, crop-to-content, encode.
- Deterministic: stabilized result is deterministic given identical inputs, parameters, emwy
  version, and toolchain fingerprint.
- Border handling: constant resolution, no uninitialized pixels, stable across frames.
- Explicit failure when unsuitable.
- Transparent reuse of expensive motion estimation across identical inputs.
- Audio/subtitles: copy through unchanged (no timing edits, no re-authoring); subtitles may be
  visually cropped and are not repositioned.

### Scope

In:

- Stabilization for selected source ranges (video stream only).
- Reusable analysis caching keyed by identical inputs.
- Crop-only framing with a single static crop rectangle per output.

Out:

- Subject tracking, reframing, rolling-shutter correction, optical-flow synthesis.
- Any changes to audio/subtitle timing or semantics.

### Files and entry points

- Tool script: `tools/` (new tool alongside `tools/silence_annotator.py`)
- Tool docs: `docs/TOOLS.md`, `tools/README.md`
- Shared helpers (ffmpeg, cache, time parsing): reuse existing utilities where practical

### Data model changes

- None in the EMWY YAML v2 spec. The tool consumes its own config file and produces derived media
  plus a sidecar report (YAML or JSON).

### Action items

[ ] Add a new tool script under `tools/` with a CLI similar to `silence_annotator.py` (input media,
    optional in/out range(s), optional config file, deterministic outputs).
[ ] Add config file support with a tool-specific header (for example `stabilize_building: 1`) and
    auto-write a default config if missing.
[ ] Add a runtime prerequisite check for vid.stab support (detect presence of `vidstabdetect` and
    `vidstabtransform` in `ffmpeg -filters`) and fail with a clear error if unavailable.
[ ] Implement a two-stage pipeline: analysis (motion estimation) then transform application; store
    analysis output in the cache when inputs are identical.
[ ] Define cache keys so reuse is transparent and correctness-preserving; include the toolchain
    fingerprint and the selected range(s) in the cache key.
[ ] Implement crop-to-content as a dedicated step with stable behavior (a single crop rectangle per
    stabilized output) and explicit failure thresholds (`min_area_ratio`, `min_height_px`, safe
    region).
[ ] Write a sidecar report (YAML or JSON) capturing settings, toolchain fingerprint, pass/fail,
    chosen crop rectangle, resulting zoom, and warnings.
[ ] Copy audio/subtitle streams through unchanged (no timing edits); document that subtitles may be
    visually cropped but are not rewritten.
[ ] Add unit tests for config parsing, cache key computation, and crop feasibility checks.
[ ] Update `docs/TOOLS.md` and `tools/README.md` with usage and config examples.

### Testing and validation

- Add pytest coverage for config parsing/validation and for crop feasibility thresholds.
- Add deterministic tests for cache key computation and reuse behavior.
- If integration assets are added, include a test that validates deterministic results across two
  runs with identical inputs and toolchain fingerprint.

Transform-only test suite idea (no video needed):

- Provide synthetic motion traces `T[i] = (tx, ty, s)` and assert expected `crop_rect` and pass/fail.
- Cases:
  - Zero motion (crop is full frame, pass).
  - Mild shake (crop slightly smaller, pass above thresholds).
  - Pan/tilt drift (crop infeasible, fail).
  - Scale jump (fail scale continuity).
  - Missing transforms fraction > 0.05 (fail).
  - Safe region not contained (fail).

### Risks and edge cases

- Bitwise determinism can be difficult across platforms/ffmpeg builds; achieving the guarantee may
  require constraining intermediate encoding modes to deterministic settings.
- Some footage is inherently unsuitable for global stabilization (low texture, moving background,
  large motion blur); detection thresholds must be tuned to prefer explicit failure over unstable
  output.
- Crop feasibility thresholds must be calibrated so this tool fails early rather than producing an
  over-zoomed result on footage with intentional motion.

### Open questions

- What is the minimal CLI surface: single in/out range vs multiple ranges (segment list)?
- Should whole-asset stabilization be supported, or require explicit ranges to preserve strict
  "select range first" semantics?
- Should we allow analysis padding (detect on a small window around the segment) to improve motion
  estimation while still applying the transform only to the segment range?
