# Plan: Runner Tracking and Reframing Tool

## Context

Handheld footage of a distance runner going around a track needs to be cropped and
reframed to follow the runner, producing a zoomed-in output video. The camera operator
is actively panning in an elliptical path to keep the runner in frame -- this is
**moving-camera subject tracking with operator-driven global motion**.

The camera is handheld (iPhone 16 Pro Max with motion reduction, or Canon SLR with
optical image stabilization). Hardware stabilization reduces jitter but does not eliminate
it. The operator deliberately pans, tilts, and sometimes zooms to follow the runner.

This means the runner tends to stay **near the center of frame** for much of the video.
The tool's job is not to discover a tiny runner in a wide static shot -- it is to
**refine the operator's framing**: remove jitter, improve centering, normalize zoom,
and recover from tracking misses.

This is fundamentally different from `stabilize_building.py` which handles static subjects
with camera shake. This tool handles a moving subject with a moving camera -- both the
subject and the frame of reference are moving.

**Goal**: A standalone tool under `tools/` that produces a cropped/reframed video file
following a single runner, with adaptive zoom to maintain consistent apparent runner size.

## Expected input video characteristics

**Camera setup:**
- Handheld camera (iPhone 16 Pro Max or Canon SLR), not tripod-mounted
- Simple tripods do not work -- the camera must pan in an elliptical path to follow
  the runner around the track
- iPhone has motion reduction setting enabled; Canon has optical image stabilization (IS)
- Hardware stabilization reduces jitter but does not eliminate it -- expect residual
  shake plus deliberate panning/tilting to follow the runner
- Operator stands trackside, seeing roughly 1/3 to 1/2 of the track at any moment
- Standard video resolution (1080p typical, 4K possible from iPhone/Canon)

**Key implication of operator panning:**
- The runner stays roughly near the center of frame most of the time
- The entire background moves frame-to-frame due to deliberate panning
- Image-space coordinates reflect camera behavior as much as runner behavior
- Background subtraction (MOG2) is unreliable because nothing is truly static
- Path priors in raw image coordinates are weak because the camera is moving too
- The problem is closer to "detect-and-refine" than "search-and-discover"

**Runner behavior:**
- Single target runner to follow, identified by jersey color
- Runner moves around the track, getting closer (near side) and farther (far side)
- On the near side, runner may fill most of the frame (large, detailed)
- On the far side, runner may be quite small (50-150px tall)
- This creates significant scale variation (possibly 3-5x between near and far)
- Arms and legs swing wildly - no fixed rigid shape to template-match
- Torso rotates as runner turns corners - jersey appearance changes with pose
- Speed varies: acceleration, deceleration, steady-state running

**Scene complexity:**
- Other runners present, especially at the start (crowded pack) and during passing
- Other runners may wear similar jersey colors
- Spectators, officials, and equipment may be visible in frame
- Shadows, lighting changes (time of day, cloud cover)
- Track markings, lane lines, fences, bleachers as background
- Possible flags, trees, or other objects moving in wind

**Typical filming scenarios (in order of difficulty):**
1. Solo runner on empty track, clear weather, steady hand - easiest
2. Solo runner, shaky handheld or changing light - moderate
3. Multiple runners, target has unique color - moderate
4. Race start with crowded pack - hard (target occluded by others)
5. Passing maneuver with similar jerseys nearby - hard
6. Far-side runner in poor light with camera shake - hard (small target, low contrast,
   jittery frame)

**User interaction model:**
- User runs the tool, provides input video and output path
- Tool shows frames at intervals (every 10-30 seconds of video)
- User draws a rectangle around the runner's **upper torso** in each displayed frame
  - Upper torso chosen because it is more stable across stride phases than full body
  - User boxes will be inconsistent (too large, too small, off-center) - tool must
    handle this
  - Tool normalizes boxes and aggregates across seeds for robust initialization
- User can skip frames where runner is not clearly visible
- After seeding, tool processes the entire video automatically
- Output: cropped/reframed video + sidecar report + optional debug video

## Design principles

- This is **detect-and-stabilize**, not search-and-discover -- the operator already
  did most of the work keeping the runner in frame
- **Person detection is the hero** -- the most trustworthy signal for handheld footage
- Track the runner as a moving, deformable, multi-cue region - not a rigid template
- Use centroid/center-of-mass, not template matching (appearance changes as runner turns)
- **Separate tracking state from crop state** -- tracker follows accurately, crop moves
  smoothly like a virtual camera operator refining the real operator's work
- Jersey color is a tie-breaker/identity check, not the primary signal
- **Classical motion cues are suspicious strangers** until proven useful -- with a panning
  camera, raw motion and background subtraction are contaminated by camera movement
- **Baseline first, modular expansion from the start** -- get a working tracker with
  evaluation harness early, then add cues only when metrics show they help
- Multi-file modular structure so each subsystem is in its own file

## Signal priority (strongest to weakest)

For handheld panning footage, detection carries much more weight than classical cues:

1. **Person detection** (YOLO nano, every N frames -- the backbone)
2. **Temporal prediction** (Kalman filter -- smooths and bridges gaps between detections)
3. **Jersey / appearance identity cue** (tie-breaker when multiple candidates nearby)
4. **Size consistency** (plausible human box at expected scale for current distance)
5. **Path prior** (weak local regularizer only -- rejects implausible short-term jumps,
   does not encode track shape, because camera panning makes image-space paths unreliable)
6. **Residual motion cue** (experimental, probably off by default -- requires camera-motion
   compensation to be useful at all, and even then likely low value with panning footage)

## File structure

Multi-file package under `tools/track_runner/`:

```
tools/track_runner/
  __init__.py              # empty (per PYTHON_STYLE)
  cli.py                   # parse_args, main(), config loading, video probing
  seeding.py               # interactive rectangle UI, jersey color extraction, appearance model
  kalman.py                # Kalman filter (create, predict, update, state)
  detection.py             # YOLO detector, HOG fallback
  motion_compensation.py   # global camera motion estimation, frame alignment (optional)
  scoring.py               # hard gates + weighted candidate scoring
  path_prior.py            # weak local spline from seeds, distance computation
  reacquisition.py         # confidence monitoring, search widening, snap-back
  tracker.py               # tracking loop: forward, backward, merge trajectories
  crop.py                  # adaptive zoom, exponential smoothing, virtual camera
  encoder.py               # OpenCV decode + numpy crop + ffmpeg pipe
  report.py                # sidecar YAML report + debug video overlay
  config.py                # default config, config schema, validation

tools/config_track_runner.yml   # example/default config

tests/test_track_runner.py                # unit tests per module
tests/generate_track_clips.py             # synthetic challenge clip generator
tests/evaluate_tracker.py                 # automated metric computation
tests/run_ablation.py                     # ablation runner (headless, agent-runnable)
tests/data/track_runner_challenge/        # generated synthetic clips + ground truth
tests/data/track_runner_real/             # short real clips + sparse manual annotations

docs/TRACK_RUNNER_TOOL_PLAN.md            # design doc
docs/TRACK_RUNNER_EXPERIMENTS.md          # variants, metrics, current best settings
```

Entry point: `python -m tools.track_runner` or `python tools/track_runner/cli.py`

Each module is independently importable and testable. No circular dependencies.
Modules communicate through plain dicts and numpy arrays, not shared global state.

### Common tracked representation

- Detector returns full-person boxes (YOLO person class)
- User seeds upper-torso rectangles
- Internal tracking uses **full-person center and height** as the canonical state
- Jersey/appearance color features derived from the **upper subregion** of the
  tracked box (more stable across stride phases)

**Seed-to-full-person initialization:**
On each seed frame, run the person detector automatically. Choose the person
detection box that best overlaps the user's torso rectangle. Initialize canonical
tracking state (center, height) from that full-person detection. Use the user's
torso rectangle only for appearance/color extraction. If no person detection
overlaps the user box, fall back to estimating full-person height as
`torso_height * 2.5` and shifting center down by `torso_height * 0.5`.

## Interactive seeding phase (`seeding.py`)

1. Run: `source source_me.sh && python tools/track_runner/cli.py -i video.mp4 -o tracked.mp4`
2. Tool probes video (duration, resolution, fps)
3. Displays frames at configurable intervals (default 10s, `--seed-interval`) via `cv2.imshow()`
4. Prompt text on frame: **"Draw a rectangle around the runner's upper torso"**
   - User click-drags a rectangle (upper torso, not full body)
   - Upper torso is more consistent across poses than full body (legs/arms vary wildly)
   - Expect inconsistent boxes from user - extract center, height, and color model
     from whatever rectangle is drawn; do not assume precise boundaries
   - Press spacebar to skip a frame where runner is not clearly visible
5. From each rectangle, extract:
   - Center position (cx, cy)
   - Height and aspect ratio (used to initialize Kalman state)
   - Jersey color: median HSV from the rectangle interior
   - Color histogram of rectangle as appearance descriptor
6. Optional: user draws polygon ROI for the track area (`--draw-roi` flag)
   - Note: with panning camera, a static image-space ROI ages badly as the camera
     drifts. ROI is advisory only and should be used loosely (wide margins) or
     transformed with estimated camera motion if `motion_compensation` is enabled.
7. Multiple seed frames collected; user presses ESC/q when done
8. Minimum 1 seed required to run baseline tracker; minimum 3 seeds to enable spline prior
9. Seed data saved to config YAML (`--write-config`)
10. **Single pass produces a final video** -- the tool always outputs a complete
    result from whatever seeds it has. The user can watch and be done.
11. **Optional refinement**: if the user wants a better result, seeds persist in
    the config YAML across runs. The user can:
    - Come back with `--add-seeds` to add more seeds at specific trouble spots
    - Use `--suggest-seeds` which reads the sidecar report and shows only frames
      where confidence was low or tracking was lost, for targeted re-seeding
    - Re-run tracking with the enriched seed set for improved output
    - This is never required, just available for users who want to iterate

**Seed placement tips** (shown to user during seeding):
- At least one seed in a clear, unoccluded segment
- If possible, one near a crowded or passing moment
- If possible, one at a different apparent scale (near vs far side)
- More seeds generally help, but diminishing returns past 8-10

**Handling inconsistent user boxes:**
- Normalize each box to a canonical aspect ratio (e.g., clamp to 0.3-0.8 w/h for upper torso)
- Use median of all seed box sizes as the initial scale estimate, not any single box
- Color model aggregated across all seed boxes (median HSV + std-based range)
- Outlier seed boxes (size > 2x median) flagged with a warning

## Kalman filter (`kalman.py`)

State vector: `[cx, cy, log_h, aspect, vx, vy, v_log_h]`

- `log_h` handles multiplicative scale change naturally (runner distance varies)
- Aspect ratio observed weakly (people have roughly stable aspect)
- Fewer oscillation modes than tracking w and h independently
- Note: with panning camera, `vx` and `vy` reflect combined runner + camera motion
  in image space. This is fine for short-term prediction (next few frames), but
  means velocity is not a pure runner-motion signal. Detection resets keep it honest.

## Person detection (`detection.py`)

**Primary**: YOLO via OpenCV DNN (no ultralytics dependency)
- OpenCV natively supports YOLOv5/v7/v8/v9/v10/YOLOX with built-in pre/post-processing
- Use YOLOv8n (nano) as default: `yolov8n.onnx`, input 640x640
- Key preprocessing: `scale=1/255`, `mean=0.0`, `paddingmode=2` (aspect-preserving resize),
  `padvalue=144.0`, `swapRB=false`
- Output tensor: `[BxNxC+4]` (no separate objectness score in v8)
- NMS applied via `cv2.dnn.NMSBoxes()` after forward pass
- Use `cv2.dnn.blobFromImage()` with `Image2BlobParams` for correct preprocessing
- Detect every N frames (default 4, configurable)
- Between detections: Kalman prediction bridges the gap
- **Must validate ONNX model early**: write a tiny standalone detector test that confirms
  expected input size, preprocessing, NMS, and output parsing before building the pipeline
  around it. Do not let detector integration become an implicit science project.
- Filter detections to person class only (COCO class 0)

**Fallback**: HOG if YOLO weights unavailable

**Because detection is the hero for handheld footage:**
- Detector quality matters more than with a fixed camera
- Ablation should test model size (yolov8n vs yolov8s) if runtime permits
- Detector cadence (N) should also be ablated: N = 1, 2, 4, 8
- When detector returns nothing: rely on Kalman prediction with decaying confidence,
  do not fall back to motion cues by default

## Candidate scoring (`scoring.py`)

**Hard gates first** (reject before scoring):
- Must be inside search region around Kalman prediction (radius =
  `max(min_search_radius, k * predicted_height)`, default k=1.5, min=100)
- Must satisfy plausible aspect ratio (configurable, default 1.5 to 4.0 h/w)
- Area must be within sane scale band (0.3x to 3.0x predicted size)
- Must overlap allowed ROI polygon if provided (loosely, with wide margins)

**Score surviving candidates** (all terms normalized 0-1):
```
score = w_detect  * detector_confidence
      + w_predict * (1 - dist_to_prediction / max_search_radius)
      + w_color   * jersey_color_fraction
      + w_size    * (1 - abs(log_h_diff) / tolerance)
      + w_path    * (1 - dist_to_spline / max_path_distance)
      + w_motion  * residual_motion_score
```

Default weights (detection-heavy for handheld):
- w_detect = 0.30, w_predict = 0.25, w_color = 0.15
- w_size = 0.15, w_path = 0.10, w_motion = 0.05

Note: w_motion defaults to 0.05 (nearly decorative) because with panning camera,
raw motion cues are contaminated. May be set to 0.0 if ablation shows no benefit.

## Camera motion compensation (`motion_compensation.py`, optional)

**This is a first-class architectural decision, not a footnote.**

For handheld panning footage, the entire background moves frame-to-frame. Any cue
that depends on image-space stability (background subtraction, path priors, even
Kalman velocity) is contaminated by camera motion.

**v1 approach: detector-first, no camera compensation**
- Person detection and temporal prediction form the core tracker
- Classical motion cues are disabled by default
- This is the pragmatic road and likely sufficient

**v2 option: explicit camera-motion compensation**
- Estimate frame-to-frame global camera motion via feature matching + RANSAC
  (affine or homography)
- Exclude the tracked runner region from the transform estimation
- Maintain both raw image coordinates and motion-compensated coordinates
- Feed compensated coordinates to path prior and optional residual motion cue
- This module exists in the file structure from the start but is not required
  for baseline tracking

**Design choice**: v1 ships with `motion_compensation.py` as a stub with the
interface defined. The ablation harness tests whether enabling it helps.
Default config has `camera_compensation.enabled: false`.

## Path prior (`path_prior.py`)

**Demoted for handheld footage.**

Because the camera is actively panning to follow the runner, global image-space
path geometry is only weakly informative. The runner may stay near frame center
for long stretches, and the image path reflects camera behavior as much as
runner behavior.

- If seed count < 3: no spline, just local motion prior (Kalman only)
- If seed count >= 3: fit parametric spline (scipy) through seed box centers
- Indexed by cumulative arc length, not monotonic x
- Used as a **weak local regularizer** only -- rejects implausible short-term
  jumps rather than encoding the track shape
- Scale prior: secondary to online tracked scale (recent boxes first, seed
  interpolation second)
- If camera compensation is enabled, spline can optionally be defined in
  compensated coordinates (more meaningful but still soft)
- Soft constraint in scoring with low weight (w_path = 0.10)
- **Be ruthless**: if ablation shows the path prior does not measurably help, cut it.
  No need to keep decorative geometry around.

## Reacquisition logic (`reacquisition.py`)

When per-frame confidence drops below threshold:
- Keep predicting for configurable window (default 15 frames)
- Gradually widen search radius (1.5x per 5 frames)
- Run person detection every frame during reacquisition
- Compare candidates against stored appearance descriptor (color histogram)
- Snap back only when candidate exceeds strong score threshold
- If fails after max window, mark gap as lost in trajectory

## Bidirectional tracking (`tracker.py`)

- From each seed frame, track forward and backward
- Merge overlapping trajectories using **confidence-weighted** average:
  - Weight by both distance from seed AND local per-frame confidence
  - Predicted-only frames get lower merge weight than observed frames
  - Frames in reacquisition state get lower merge weight
  - Avoids averaging good track with nonsense track just because both are equidistant
- Handles crowded start: seed in clear section, track backward into crowd
- Short gaps filled with smooth interpolation; long gaps marked lost

## Crop trajectory (`crop.py`)

The crop controller is effectively building a **synthetic stabilized shot** around the
runner. Because the camera operator is already trying to keep the runner in frame, the
crop is refining the operator's work:
- Removing residual jitter and shake
- Improving centering on the runner
- Normalizing zoom to maintain consistent runner size
- Recovering gracefully from operator misses or fast motion

**Adaptive zoom** (best-effort, not perfect):
- Target: runner fills configurable fraction of crop height (default 30%)
- Derived from tracked `log_h`: `crop_h = exp(log_h) / target_fill_ratio`
- Scale learned online from tracker, regularized by seed-based interpolation
- On the near side of the track, the runner may fill most of the source frame,
  so the crop cannot zoom out further than 1:1. When the runner is too close,
  fall back to accepting the full source frame fitted into the crop aspect ratio.
  Runner will appear larger than target. Output video always keeps fixed output
  dimensions; when source frame is used at 1:1, pad with black (letterbox/pillarbox)
  to maintain the configured aspect ratio.
- On the far side, high zoom degrades image quality - clamp to `max_zoom` and accept
  that the runner will appear smaller than target at extreme distances
- The zoom range is inherently limited by source resolution; this is a physical
  constraint, not a software limitation

**Crop smoothing** (separate from tracker, heavier smoothing):
- Exponential smoothing with separate attack/release rates
  - Attack: faster response when runner changes direction (default 0.15)
  - Release: slower drift for gentle motion (default 0.05)
- **Confidence-aware smoothing**:
  - High confidence: normal smoothing rates
  - Low confidence / lost: hold crop more aggressively, drift slowly on prediction only
  - After reacquisition: ease back gradually rather than snap (unless error is very large)
- **Handheld-specific concern**: crop smoothing must suppress hand jitter while
  preserving intentional subject-following motion. Too much smoothing lags behind
  deliberate camera pan; too little passes through shake. The attack/release
  asymmetry helps: fast response to large motion (real panning), slow response
  to small jitter (shake).
- **Deadband**: small tracking error below threshold -> do not move crop. Suppresses
  micro-jitter without adding lag. Threshold scales with crop size.
- Capped per-frame crop velocity to prevent wild jumps
- Crop center and zoom smoothed independently
- Clamp crop rectangle to frame bounds

**Aspect ratio**: configurable via `--aspect`, default 1:1

## Video encoding (`encoder.py`)

Decode frames via OpenCV, crop in numpy, pipe to ffmpeg encoder:
- Maximum control over per-frame crop
- Copy audio stream via separate mux step
- H.264 output with configurable CRF

## Debug video + report (`report.py`)

`--write-debug-video` overlays per frame:
- Predicted box (Kalman), chosen candidate box
- Score breakdown (per-cue contribution bars)
- Crop window rectangle, confidence / lost state
- Frame number and per-frame confidence score
- Candidate count after hard gating
- Update source label: detected / predicted / reacquired / merged

Sidecar YAML report (`{output}.track_runner.report.yaml`):
- Settings, seed data, jersey color model
- Per-frame confidence, trajectory stats (gaps, reacquisitions)
- **Trajectory jump anomaly count** (frames where tracked center jumps > 2x predicted
  distance)
  - Note: this is a suspicious motion heuristic, not true identity error measurement
- Crop statistics (zoom range, velocity stats, crop lag)

## Evaluation harness (agent-runnable, no human in the loop)

The evaluation is fully automated so AI agents can run experiments headless.

### Synthetic challenge clips (`tests/generate_track_clips.py`)

Each clip is 3-10 seconds, generated via OpenCV with known ground-truth trajectory.
Generator writes both the video and a ground-truth YAML with per-frame bounding boxes.

**Static-camera clips** (basic tracking):
- `straight_run`: colored rectangle moving left-to-right at constant speed/scale
- `approaching`: rectangle grows (runner getting closer)
- `receding`: rectangle shrinks (runner moving away)
- `curve`: rectangle follows smooth arc path
- `scale_change`: significant size variation
- `occlusion`: rectangle disappears for N frames then reappears
- `two_runners`: target rectangle + distractor rectangle crossing nearby (tests identity)
- `speed_change`: acceleration and deceleration
- `direction_change`: reversal mid-clip

**Handheld-camera clips** (simulate operator panning):
- `handheld_jitter`: target near center with global frame jitter (translation noise)
- `handheld_pan`: smooth global panning with target staying roughly centered
- `handheld_pan_plus_jitter`: combined deliberate pan + shake noise
- `handheld_zoom_drift`: slow global zoom change simulating operator adjusting
- `handheld_with_distractor`: panning camera + second moving rectangle nearby

Each clip has `{clip_name}.ground_truth.yaml` with per-frame boxes.
Handheld clips generate motion in world space internally, but save per-frame
**image-space ground-truth boxes** after applying the simulated camera transform.
The evaluator compares tracker output against these rendered image-space boxes.

### Automated evaluator (`tests/evaluate_tracker.py`)

Computes metrics from tracker sidecar report vs ground truth:

**Tracking correctness** (computed only on labeled frames, not interpolated):
- Center error (mean/median/p95 pixels)
- IoU with ground truth boxes
- Valid track fraction: frames with a valid target
- Target association accuracy: on synthetic two-runner clips, whether tracked box
  matches target GT identity (not distractor). On real clips, fraction of labeled
  frames where tracked box overlaps the target annotation above IoU threshold.

**Tracking stability**:
- Trajectory jump anomaly count (center jumps > 2x predicted distance)
- Reacquisition latency (frames from loss to stable re-lock)

**Crop quality**:
- Runner-inside-crop rate
- Edge safety rate (runner not too close to crop border)
- Crop jerk (frame-to-frame acceleration of crop center)
- Zoom jitter (frame-to-frame zoom oscillation)
- **Crop lag** (frame offset that maximizes cross-correlation between target-center
  velocity and crop-center velocity over valid segments; lower is better)
- **Successful framing rate** (summary metric): fraction of frames where target is
  visible AND inside safe crop region AND crop lag below threshold. One-line
  scoreboard for quick ablation ranking.

Output: JSON summary per clip + aggregate scores.

### Ablation runner (`tests/run_ablation.py`)

Runs tracker on all clips with config variants, prints comparison table.
Seeds injected programmatically from ground truth (no interactive UI).

**Ablation ladder** (each adds one cue to the previous, ordered by expected value
for handheld footage):
- A: Detector-only bidirectional association from seeds (no Kalman, dumb baseline)
- B: A + Kalman prediction (smoothing and gap bridging)
- C: B + detector every N frames instead of every frame (Kalman interpolation)
- D: C + reacquisition logic
- E: D + color / appearance tie-breaker
- F: E + weak path prior
- G1: F + no motion cue (control)
- G2: F + raw local motion cue (likely bad with panning)
- G3: F + camera-compensated residual motion cue

Detector sub-ablations:
- Cadence: N = 1, 2, 4, 8
- Model size: yolov8n vs yolov8s (if runtime permits)

**Two tiers of evaluation**:
- Tier 1: synthetic clips (fast regression, automated, agent-runnable)
- Tier 2: real clips with sparse manual annotations (final cue validation)
  - `tests/data/track_runner_real/` with 3-5 short real clips
  - Sparse GT every 10th-15th frame + seed rectangles stored in YAML
  - Same evaluator supports both synthetic and real clips

## Config schema

```yaml
track_runner: 1
settings:
  detection:
    kind: yolo
    model: yolov8n
    detect_interval: 4
    fallback: hog
  camera_compensation:
    enabled: false         # v1 ships with this off; ablation tests whether it helps
    method: affine_ransac
    exclude_tracked_region: true
  tracking:
    min_search_radius: 100
    search_radius_scale: 1.5   # radius = max(min, scale * predicted_height)
    reacquire_window: 15
    confidence_threshold: 0.3
    reacquire_threshold: 0.5
    max_missed_before_lost: 60
  scoring:
    w_detect: 0.30
    w_predict: 0.25
    w_color: 0.15
    w_size: 0.15
    w_path: 0.10
    w_motion: 0.05         # nearly decorative; 0.0 if ablation shows no benefit
    hard_gate_aspect_min: 1.5
    hard_gate_aspect_max: 4.0
    hard_gate_scale_band: 3.0
  crop:
    aspect: "1:1"
    target_fill_ratio: 0.30
    smoothing_attack: 0.15
    smoothing_release: 0.05
    max_crop_velocity: 30
    min_crop_size: 360
  jersey_color:
    hsv_low: null
    hsv_high: null
  seeding:
    interval_seconds: 10
    min_seeds: 1           # 1-2 for baseline, 3+ enables spline prior
    torso_aspect_min: 0.3
    torso_aspect_max: 0.8
  output:
    video_codec: libx264
    crf: 18
  experiment:
    enabled: false
    variant: "full"
    write_debug_video: true
    save_metrics_json: true
  io:
    cache_dir: null
    report_format: yaml
```

## Dependencies

Already in pip_requirements.txt: `opencv-python`, `numpy`, `scipy`, `pyyaml`

YOLO weights: download `yolov8n.onnx` for OpenCV DNN (no ultralytics dependency).
Tool checks for weights file at startup and falls back to HOG if missing.

## Reusable code

- `tools/stabilize_building.py`: CLI pattern, config loading, `run_process()`,
  `parse_time_seconds()`, sidecar report pattern
- `emwylib/core/utils.py`: `probe_video_stream()`, `probe_duration_seconds()`
- `source_me.sh`: environment bootstrap

## Testing

**Unit tests** (per module, no video needed):
- `kalman.py`: predict/update with synthetic trajectories, log_h scale behavior
- `scoring.py`: hard gate filtering, weighted scoring with known inputs
- `crop.py`: exponential smoother at turns vs straight, clamping, jitter suppression
- `path_prior.py`: spline fitting (>= 3 seeds), distance computation, < 3 seeds fallback
- `config.py`: parsing, validation, default round-trip
- `tracker.py`: trajectory merging (bidirectional overlap)
- `reacquisition.py`: state machine transitions
- `seeding.py`: inconsistent box normalization, color extraction from patches
- `motion_compensation.py`: affine estimation from synthetic point pairs

**Integration tests** (synthetic clips):
- Single target rectangle: verify tracker follows and output is cropped correctly
- Target + distractor crossing: verify identity is maintained (not just plumbing test)
- Handheld jitter clip: verify crop smooths out shake while following target

## Verification

1. `source source_me.sh && python -m pytest tests/test_track_runner.py -v`
2. `source source_me.sh && python -m pytest tests/test_pyflakes_code_lint.py`
3. `source source_me.sh && python tests/run_ablation.py` (headless, agent-runnable)
4. Manual test with real footage + `--write-debug-video`

## Implementation order

Evaluation harness comes early, not late. Get a testable baseline first.

1. CLI skeleton + config module + video probing (`cli.py`, `config.py`)
2. Interactive rectangle seeding UI (`seeding.py`)
3. YOLO person detector module + standalone validation test (`detection.py`)
4. Kalman filter module (`kalman.py`)
5. Minimal bidirectional tracker (`tracker.py` - detector observations + simple Kalman
   prediction + forward/backward seeded passes + basic confidence-weighted merge).
   No hard-gate scoring, reacquisition, or appearance cues yet -- those come later.
   Bidirectional tracking is core to this problem, not an optimization -- with multiple
   seed frames and operator panning, tracking outward from seeds in both directions
   is the natural approach.
6. Simple crop generation (`crop.py`)
7. **Basic debug overlay** (`report.py` - predicted box, candidate box, crop window,
   confidence)
8. **Evaluation harness** (`generate_track_clips.py`, `evaluate_tracker.py`,
   `run_ablation.py`) -- includes both static and handheld synthetic clips
9. Hard gates + candidate scoring (`scoring.py`)
10. Reacquisition logic (`reacquisition.py`)
11. Color appearance tie-breaker (add to `scoring.py` + `seeding.py`)
12. Weak path prior (`path_prior.py`) -- local regularizer only
13. Incremental seeding support (`--add-seeds`, `--suggest-seeds`)
14. Camera motion compensation stub (`motion_compensation.py`) -- interface + basic
    affine estimation, disabled by default
15. Residual motion cue (optional, depends on ablation results) -- last cue, most
    likely decorative or harmful with panning footage
16. Video encoding with crop (`encoder.py`)
17. Full debug video + sidecar report polish (`report.py`)
18. Unit tests for each module (`test_track_runner.py`)
19. Documentation (`docs/TOOLS.md`, `docs/TRACK_RUNNER_TOOL_PLAN.md`,
    `docs/TRACK_RUNNER_EXPERIMENTS.md`, `docs/FILE_STRUCTURE.md`, `docs/CHANGELOG.md`)
