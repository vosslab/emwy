# Track runner specification

Status: Current implementation as of 2026-03-11

This document captures how the track_runner tool actually works today, based on
reading all 11 source files. It is intended to guide a future rewrite by
preserving the good parts and identifying the error-prone patterns.

## 1. Overview and purpose

The track_runner tool detects, tracks, and crops a single person (runner)
in handheld video footage. It produces a reframed output video where the
runner stays centered with adaptive zoom.

The workflow is: seed the runner's position interactively, run bidirectional
Kalman tracking with YOLO detection, compute smooth crop rectangles, and
encode the output via ffmpeg.

Entry point: `track_runner.py` calls `cli.main()`.

Total codebase: 4505 lines across 11 Python files.

## 2. Module map

| File | Lines | Purpose |
| --- | --- | --- |
| `cli.py` | 1191 | CLI parsing, main orchestration, seed target analysis, quality report |
| `tracker.py` | 736 | 6-phase bidirectional tracking pipeline |
| `seeding.py` | 618 | Interactive seed UI, jersey color and histogram extraction |
| `encoder.py` | 465 | Video I/O (OpenCV reader, ffmpeg writer), debug overlay |
| `config.py` | 350 | Config/seeds/diagnostics YAML loading, defaults, validation |
| `crop.py` | 334 | Adaptive crop controller with exponential smoothing |
| `detection.py` | 304 | YOLOv8n ONNX person detection, HOG fallback |
| `scoring.py` | 253 | Hard gates and weighted candidate scoring |
| `kalman.py` | 245 | 7-state Kalman filter for bbox tracking |
| `track_runner.py` | 8 | Thin wrapper: `import cli; cli.main()` |
| `__init__.py` | 1 | Docstring only |

### Dependency graph

```
track_runner.py -> cli
cli -> config, detection, encoder, seeding, tracker, tools_common, numpy
tracker -> kalman, scoring, crop, detection, cv2, concurrent.futures
seeding -> cv2, numpy
encoder -> cv2, numpy, crop
scoring -> kalman, math
crop -> numpy, math
detection -> cv2, numpy, os, urllib.request
kalman -> numpy, math
config -> yaml, os, copy
```

No circular dependencies exist. All modules communicate through plain dicts and
numpy arrays.

## 3. CLI and execution flow

### CLI arguments

| Flag | Dest | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `-i`, `--input` | `input_file` | str | required | Input video path |
| `-o`, `--output` | `output_file` | str | `{stem}_tracked{ext}` | Output path |
| `-c`, `--config` | `config_file` | str | `{input}.track_runner.config.yaml` | Config YAML path |
| `--write-default-config` | `write_default_config` | flag | False | Write defaults and exit |
| `--seed-interval` | `seed_interval` | float | None | Override `seeding.interval_seconds` |
| `--aspect` | `aspect` | str | None | Override crop aspect ratio |
| `-d`, `--debug` | `debug` | flag | False | Draw tracking overlay on output |
| `--keep-temp` | `keep_temp` | flag | False | Keep temp files |
| `--add-seeds` | `add_seeds` | flag | False | Open seed UI at problem regions |
| `-w`, `--workers` | `workers` | int | `cpu_count // 2` | Parallel detection workers |

### Main control flow

1. Parse args, resolve worker count (default: half of CPU cores, min 1).
2. Validate input file exists; check `ffprobe` and `ffmpeg` are available.
3. Resolve config/seeds/diagnostics file paths from input filename.
4. If `--write-default-config`: write defaults and return.
5. Load or create config YAML; validate required sections.
6. Apply CLI overrides (`--seed-interval`, `--aspect`) into config.
7. Probe video metadata via ffprobe (resolution, fps, duration, pix_fmt).
8. Create YOLO detector.
9. Collect seeds (three paths, see below).
10. Validate minimum visible seed count.
11. Sanitize seeds (strip numpy types) and save to seeds YAML.
12. Run `tracker.run_tracker()` -- returns crop_rects, frame_states, forward_states, backward_states.
13. Count frame sources (detected, predicted, interpolated, lost, absent).
14. Resolve output path; compute crop dimensions from first crop rect.
15. Encode cropped video via `encoder.encode_cropped_video()` to temp file.
16. Mux audio from original via `encoder.copy_audio()`.
17. Clean up temp file.
18. Analyze streaks, jerk regions; merge into combined bad_streaks.
19. Write diagnostics YAML.
20. Print quality report with letter grade.

### Three seed collection paths

**Path 1: `--add-seeds`** (requires existing seeds and diagnostics):
- Loads saved diagnostics from previous run.
- Computes seed targets from six sources (see section 10).
- Deduplicates targets within `2 * fps` frames.
- Opens seed UI at target frames with prediction overlays.
- Merges new seeds with existing (new overwrites same frame_index).

**Path 2: saved seeds exist** (no `--add-seeds`):
- Calls `collect_seeds()` with `pre_provided_seeds=saved_seeds`.
- Returns them directly without opening the UI.

**Path 3: no saved seeds**:
- Opens interactive UI at regular intervals (`interval_seconds`, default 10s).
- User draws torso rectangles on each displayed frame.

## 4. Configuration system

### Three-file layout

All paths are derived from the input filename:

- Config: `{input}.track_runner.config.yaml` -- settings and parameters
- Seeds: `{input}.track_runner.seeds.yaml` -- seed points with appearance data
- Diagnostics: `{input}.track_runner.diagnostics.yaml` -- tracking results for `--add-seeds`

### Real-world file sizes

Measured from two test videos (~2-4 min of 30fps footage):

| File | Lines | Bytes | Format concern |
| --- | --- | --- | --- |
| Config | 56-67 | 1.2-1.5 KB | Fine as YAML |
| Seeds (303 seeds) | 4707 | 51 KB | Verbose but tolerable |
| Diagnostics (4115 frames) | 53187 | 974 KB | Too large for YAML |
| Diagnostics (longer video) | 80804 | 1.5 MB | Too large for YAML |

The diagnostics file is the bottleneck. Its bulk comes from three per-frame
arrays serialized as YAML lists-of-lists:

- `predictions` (lines 132-28947): ~1695 entries, each with forward/backward
  bbox (4 floats), source string, and confidence float. ~28800 lines.
- `bbox_positions` (lines 28954-32611): `[frame_idx, cx, cy]` for detected
  frames only (~1219 entries). ~3600 lines.
- `bbox_all_frames` (lines 32612-end): `[frame_idx, cx, cy, w, h]` for all
  frames with a bbox (~4115 entries). ~20500 lines.

The scalar fields (bad_streaks, jerk_regions, max_streak, detect_pct, etc.)
are small. The per-frame numeric arrays are pure tabular data that YAML
serializes at 3-5 lines per entry (one line per list element). JSON or a
binary format would reduce these by 3-5x.

The seeds file is moderately verbose: 303 seeds at ~15 lines each. Each seed
has 3-4 small integer lists (torso_box, full_person_box, jersey_hsv) that
YAML writes as one element per line. JSON flow-style or compact format would
cut this roughly in half.

### Header and version scheme

Each file type has a header key that must be present and match:

- Config: `track_runner: 1`
- Seeds: `track_runner_seeds: 1`
- Diagnostics: `track_runner_diagnostics: 1`

### Full default config tree

```yaml
track_runner: 1
settings:
  detection:
    kind: yolo
    model: yolov8n
    detect_interval: 1
    confidence_threshold: 0.25
    nms_threshold: 0.45
    fallback: hog
  camera_compensation:
    enabled: false
    method: affine_ransac
    exclude_tracked_region: true
  tracking:
    min_search_radius: 100
    search_radius_scale: 1.5
    reacquire_window: 15
    confidence_threshold: 0.3
    reacquire_threshold: 0.5
    max_missed_before_lost: 60
    max_vy_fraction: 0.03
    max_v_log_h: 0.05
    velocity_freeze_streak: 3
    jerk_threshold: 0.3
  scoring:
    w_detect: 0.30
    w_predict: 0.25
    w_color: 0.15
    w_size: 0.15
    w_path: 0.10
    w_motion: 0.05
    hard_gate_aspect_min: 1.5
    hard_gate_aspect_max: 4.0
    hard_gate_scale_band: 2.0
    max_bbox_area_fraction: 0.15
    vertical_limit_scale: 0.5
    max_displacement_per_frame: 80
  crop:
    aspect: "1:1"
    target_fill_ratio: 0.30
    far_fill_ratio: 0.50
    far_threshold_px: 120
    very_far_fill_ratio: 0.65
    very_far_threshold_px: 60
    smoothing_attack: 0.15
    smoothing_release: 0.05
    max_crop_velocity: 30
    min_crop_size: 200
  jersey_color:
    hsv_low: null
    hsv_high: null
  seeding:
    interval_seconds: 10
    min_seeds: 1
    torso_aspect_min: 0.3
    torso_aspect_max: 0.8
  output:
    video_codec: libx264
    crf: 18
  experiment:
    enabled: false
    variant: full
    write_debug_video: true
    save_metrics_json: true
  io:
    cache_dir: null
    report_format: yaml
```

### Validation rules

- Header key `track_runner` must be present with value `1`.
- `settings` must be a dict.
- Required sub-sections: `detection`, `tracking`, `scoring`, `crop`.

## 5. Detection pipeline

### YoloDetector (detection.py:110-216)

**Preprocessing (letterbox)**:
1. `cv2.dnn.blobFromImage()` with `scalefactor=1/255.0`, `size=(640,640)`, `swapRB=True`, `crop=False`.
2. This creates a letterboxed 640x640 input preserving aspect ratio.

**Inference**:
1. Forward pass produces output shape `[1, 84, 8400]`.
2. Transpose to `[8400, 84]` for row-wise parsing.
3. Each row: 4 bbox values (cx, cy, w, h in 640-space) + 80 class scores.
4. Filter to person class (COCO class 0) above `confidence_threshold`.

**Coordinate reversal**:
1. Compute scale = `min(640/frame_h, 640/frame_w)`.
2. Compute letterbox offsets: `offset_x = (640 - frame_w * scale) / 2`.
3. Reverse: `x_real = (x_640 - offset_x) / scale`.
4. Clamp to frame boundaries; skip degenerate boxes (w < 1 or h < 1).

**NMS**:
`cv2.dnn.NMSBoxes(boxes, scores, confidence_threshold, nms_threshold)`.
Handles version inconsistency: `int(idx) if ndim==0 else int(idx[0])`.

**Output**: list of dicts with `bbox` as `[x, y, w, h]` top-left corner format,
`confidence` float, `class_id` 0.

### HogDetector (detection.py:220-263)

Fallback detector using `cv2.HOGDescriptor` with the default people detector SVM.
Same output format as YoloDetector.

### Model caching

Weights cached to `~/.cache/track_runner/`. Downloads `yolov8n.pt` from GitHub
releases, then exports to ONNX via `ultralytics.YOLO.export()`. Validates file
size between 5MB and 20MB. Falls back to HOG if weights unavailable.

### Factory (detection.py:267-304)

`create_detector(config)` builds detector from config, stores `_config` on the
detector instance for parallel worker recreation (since detector objects cannot
be pickled).

## 6. Kalman filter

### State and measurement vectors

7-dimensional state: `[cx, cy, log_h, aspect, vx, vy, v_log_h]`

- `cx, cy`: bounding box center in pixels
- `log_h`: natural log of bbox height (handles multiplicative scale change)
- `aspect`: width / height ratio
- `vx, vy`: velocity in pixels/frame
- `v_log_h`: rate of height change in log-space

4-dimensional measurement: `[cx, cy, log_h, aspect]`

### Transition model

Constant-velocity model via transition matrix F:
```
F = I(7) with F[0,4]=1, F[1,5]=1, F[2,6]=1
```
Position += velocity each step. Aspect ratio has no velocity term.

### Noise covariances

**Initial state covariance P (diagonal)**:
`[10, 10, 0.01, 0.01, 100, 100, 100]`

High uncertainty on velocities (100), low on position (10) and shape (0.01).

**Process noise Q (diagonal)**:
`[1, 1, 0.01, 0.01, 0.1, 0.1, 0.1]`

**Measurement noise R (diagonal)**:
`[4, 4, 0.04, 0.04]`

### Key functions

- `create_kalman(bbox)`: Initialize from `(cx, cy, w, h)`. Computes `log(h)` and `w/h`.
- `predict(state)`: `x_pred = F @ x`, `P_pred = F @ P @ F.T + Q`. Returns new state dict (immutable).
- `update(state, measurement)`: Standard Kalman update with `K = P @ H.T @ inv(S)`.
- `get_bbox(state)`: Extracts `(cx, cy, w, h)` where `h = exp(x[2])`, `w = aspect * h`.
- `measurement_from_bbox(bbox)`: Converts `(cx, cy, w, h)` to `(cx, cy, log(h), w/h)`.
- `get_innovation_distance(state, measurement)`: Mahalanobis distance via `sqrt(y.T @ inv(S) @ y)`.

## 7. Scoring and hard gates

### Hard gates (scoring.py:32-128)

Five gates applied in order (candidate rejected if any fails):

1. **Search radius**: Euclidean distance from predicted center must be within
   `max(min_search_radius, search_radius_scale * pred_h)`. Default:
   `max(100, 1.5 * pred_h)`. Widens by 5% per missed frame after streak > 5,
   up to 3x base radius.

2. **Displacement cap**: Distance must be within `max_displacement_per_frame`
   (default 80px). Applied after search radius -- an absolute ceiling that
   prevents wild jumps even when search radius is widened.

3. **Vertical limit**: `|dy| <= pred_h * vertical_limit_scale`. Default:
   `pred_h * 0.5`. Runners move mostly horizontally.

4. **Aspect ratio**: `cand_h / cand_w` must be in `[1.5, 4.0]`.

5. **Area fraction**: `cand_w * cand_h` must not exceed
   `frame_w * frame_h * max_bbox_area_fraction` (default 15%).

6. **Scale band**: candidate area must be within factor `hard_gate_scale_band`
   (default 2.0) of predicted area in both directions.

### Weighted scoring (scoring.py:132-217)

Six terms, all normalized 0-1:

| Term | Weight | Computation |
| --- | --- | --- |
| detect | 0.30 | `clamp(candidate.confidence, 0, 1)` |
| predict | 0.25 | `1 - dist / max_search_radius` |
| color | 0.15 | **Placeholder: always returns 0.5** |
| size | 0.15 | `1 - abs(log_h_diff) / 1.0` (tolerance = 1.0 in log-space) |
| path | 0.10 | **Placeholder: always returns 0.5** |
| motion | 0.05 | **Placeholder: always returns 0.5** |

`select_best()` returns the candidate with the highest total score.

## 8. Tracker pipeline

### 6-phase pipeline (tracker.py:622-736)

**Phase 1: Detection pass** (`_run_detection_pass`):
- Reads entire video once and caches per-frame detections.
- When `num_workers > 1`: splits frame range across `ProcessPoolExecutor` workers.
  Each worker creates its own VideoCapture and detector instance.
- When `num_workers == 1`: sequential single-process path.
- Detection runs every `detect_interval` frames (default 1); other frames get empty lists.

**Phase 2+3: Forward and backward Kalman passes** (`_run_kalman_pass`):
- When `num_workers > 1`: both passes run in parallel via `ThreadPoolExecutor(max_workers=2)`.
- Forward: iterates frames 0 to N-1, initializes from first visible seed.
- Backward: iterates frames N-1 to 0, initializes from last visible seed.

Each pass, per frame:
1. Check for seed at current frame. Handle by status:
   - `visible`: reinitialize Kalman, reset confidence to 1.0 and streak to 0.
   - `not_in_frame`: set confidence to floor (0.1), bump streak past freeze threshold, emit "absent" source.
   - `obstructed`: bump `missed_streak` to at least 2, continue predicting.
2. Run `kalman.predict()`.
3. Clamp vertical velocity: `|vy| <= max(1.0, pred_h * 0.03)`.
4. Clamp size velocity: `|v_log_h| <= 0.05`.
5. Freeze velocity if `missed_streak > velocity_freeze_streak` (default 3): zero vx, vy, v_log_h.
6. Match against cached detections: `apply_hard_gates` -> `score_candidates` -> `select_best`.
7. If match found: convert detection bbox to center format, update Kalman, set source="detected".
8. If no match: increment missed_streak, decay confidence by 0.95 with floor 0.1.

**Phase 4: Merge** (`_merge_passes`):
- Per frame, pick the result with higher confidence.
- Tags winning result with `pass="forward"` or `pass="backward"`.

**Phase 5: Interpolation** (`_interpolate_predicted_gaps`):
- Finds predicted-only gaps of length >= 3 frames.
- Skips gaps containing any "absent" frames.
- Searches backward for anchor A (last detected frame before gap).
- Searches forward for anchor B (first detected frame after gap).
- Linearly interpolates bbox `(cx, cy, w, h)` through the gap.
- Interpolated confidence: `conf_a * (1-t) + conf_b * t`.
- Sets source to "interpolated".

**Phase 6: Crop** (inline in `run_tracker`):
- Creates `CropController` from config.
- Feeds each merged state's bbox and confidence through `crop_ctrl.update()`.
- Produces per-frame crop rectangles `(x, y, w, h)` in top-left pixel coords.

### Confidence decay

- Factor: 0.95 per frame without detection match.
- Floor: 0.1 (prevents crop from going haywire).

### Velocity clamping and freezing

- Vertical velocity capped at `max(1.0, pred_h * max_vy_fraction)` (default 3% of height).
- Log-height velocity capped at `max_v_log_h` (default 0.05).
- After `velocity_freeze_streak` (default 3) consecutive misses: all velocities zeroed.
- Note: freeze uses `>` not `>=`, so freezing starts at streak 4, not 3.

### Jerk detection (tracker.py:544-618)

`find_jerk_regions()` scans consecutive detected frames and computes:
```
relative_jerk = displacement / (person_height * frame_gap)
```
Frames exceeding `jerk_threshold` (default 0.3) are flagged. Nearby flagged
frames (within `min_streak=3` of each other) are grouped into regions.
Returns list of `(start_frame, length)` sorted by length descending.

## 9. Crop controller

### Three-tier adaptive fill ratio

The crop zooms tighter when the runner is farther away (smaller bbox):

| Tier | Bbox height threshold | Fill ratio | Effect |
| --- | --- | --- | --- |
| Very far | <= 60px | 0.65 | Tightest crop |
| Far | <= 120px | 0.50 | Moderate crop |
| Baseline | >= 360px | 0.30 | Loosest crop |

Linear interpolation between tiers. Desired crop height = `bbox_h / fill_ratio`.

### Exponential smoothing with attack/release

- **Attack alpha** (0.15): applied when error exceeds `4 * deadband` (large corrections).
- **Release alpha** (0.05): applied for small corrections.
- Both multiplied by confidence: low confidence = slower response.
- Applied independently to cx, cy, and crop size.

### Deadband

Errors below `deadband_fraction * smooth_size` (default 2%) are ignored entirely.
Suppresses micro-jitter without adding lag.

### Velocity capping

Per-frame crop center movement capped at `max_crop_velocity` (default 30 pixels).
Applied independently to x and y using `math.copysign`.

### Frame boundary clamping

Crop rectangle clamped so it stays within `[0, frame_w]` and `[0, frame_h]`.

### Crop application (crop.py:240-279)

`apply_crop()` handles out-of-bounds crops by zero-padding (black fill) via
numpy array slicing.

## 10. Seeding system

### Seed data structure

Visible seed:
```python
{
    "frame_index": int,
    "time_seconds": float,
    "torso_box": [x, y, w, h],         # top-left, user-drawn normalized
    "full_person_box": [cx, cy, w, h],  # center format
    "jersey_hsv": [h, s, v],            # median HSV from torso
    "color_histogram": ndarray,         # 30x32 H-S histogram (stripped before YAML save)
}
```

Absence marker:
```python
{
    "frame_index": int,
    "time_seconds": float,
    "status": "not_in_frame" | "obstructed",
}
```

### Interactive UI

Window title: "Track Runner - Seed Selection".

Controls:
- Mouse drag: draw torso rectangle (green preview).
- Spacebar: skip to next seed frame.
- Left/right arrow: scrub by 0.2 seconds.
- `n`: mark runner as not in frame.
- `o`: mark runner as obstructed.
- ESC or `q`: finish collecting seeds.

When `--add-seeds`, prediction overlays are drawn:
- Forward prediction: blue rectangle labeled "FWD".
- Backward prediction: magenta rectangle labeled "BWD".

### Torso normalization (seeding.py:69-98)

- Minimum dimensions: 10px.
- Aspect ratio (w/h) clamped to `[torso_aspect_min, torso_aspect_max]` (default [0.3, 0.8]).
- If too wide: shrink width. If too narrow: shrink height.

### Full person estimation

Two paths:
1. If detector available: run detection on seed frame, find detection with best IoU overlap
   (threshold > 0.1). Convert detection bbox to center format.
2. Fallback: estimate from torso geometry:
   - `full_h = torso_h * 2.5`
   - `full_cy = torso_cy + torso_h * 0.5` (shifted down)
   - `full_w = full_h * 0.4`
   - `full_cx = torso_cx`

### Jersey color extraction

- Median HSV: crop torso ROI, convert BGR to HSV, compute `numpy.median` per channel.
- Color histogram: 2D histogram on H (30 bins, 0-180) and S (32 bins, 0-256) channels,
  normalized to sum to 1 via `cv2.normalize` with `NORM_L1`.

### Six seed target sources for --add-seeds

1. **Bad streaks**: from saved diagnostics `bad_streaks`. Places seeds every ~5 seconds
   within each streak. Minimum streak length: 30 frames.

2. **Seedless gaps**: gaps between existing visible seeds exceeding 15 seconds.
   Places seeds every ~5 seconds within gaps.

3. **Stall regions**: stretches where bbox center displacement stays below 2% of
   frame width for >= 3 seconds. Skips first/last 5 seconds. Returns midpoints.

4. **Big movement regions**: per-frame displacement / person_height / frame_gap
   exceeding 0.15. Groups nearby flagged frames (within 1 second). Minimum
   3 flagged frames per region.

5. **Area change regions**: per-frame `|area_change| / area / frame_gap >= 0.50`.
   Same grouping logic as movement regions.

6. **Interval targets**: regular spacing at `--seed-interval` seconds, skipping
   targets within `2 * fps` frames of an existing seed.

All six sources are merged, deduplicated (within `2 * fps` frames), and sorted
chronologically.

## 11. Encoder pipeline

### VideoReader (encoder.py:21-110)

OpenCV `VideoCapture` wrapper with:
- Context manager support (`with` statement).
- `__iter__` yielding `(frame_index, frame)` tuples from start.
- `read_frame(index)` for random access via seek.
- `get_info()` returning metadata dict.

### VideoWriter (encoder.py:113-219)

Pipes raw BGR frames to ffmpeg via `subprocess.Popen`:
```
ffmpeg -y -f rawvideo -vcodec rawvideo -s WxH -pix_fmt bgr24 -r FPS
  -i - -an -vcodec CODEC -crf CRF -pix_fmt yuv420p OUTPUT
```

### encode_cropped_video (encoder.py:295-345)

For each frame:
1. Read frame from VideoReader.
2. Apply crop via `crop.apply_crop()`.
3. Resize to exact output dimensions via `cv2.resize()`.
4. If debug: draw tracking overlay via `draw_debug_overlay_cropped()`.
5. Write frame to VideoWriter.

### Audio muxing (encoder.py:249-291)

Separate ffmpeg pass:
```
ffmpeg -y -i VIDEO -i ORIGINAL -c:v copy -c:a aac -map 0:v:0 -map 1:a:0
  -shortest OUTPUT
```
Checks for audio stream presence via ffprobe first. If no audio, copies video directly.

### Debug overlay colors

| Source | Color | BGR |
| --- | --- | --- |
| detected | green | (0, 255, 0) |
| predicted | yellow | (0, 255, 255) |
| interpolated | orange | (0, 165, 255) |
| lost | red | (0, 0, 255) |

Overlay includes: frame info label, tracked bbox with crosshair, confidence bar
(green-to-red gradient in top-right corner), box coordinates.

## 12. Bounding box format reference

| Location | Format | Notes |
| --- | --- | --- |
| Detection output | `[x, y, w, h]` top-left | From both YoloDetector and HogDetector |
| Seed torso_box | `[x, y, w, h]` top-left | User-drawn, normalized |
| Seed full_person_box | `[cx, cy, w, h]` center | From detection or estimation |
| Kalman state | `[cx, cy, log_h, aspect, ...]` | log-height and aspect, not w/h |
| kalman.get_bbox() | `(cx, cy, w, h)` center | h = exp(log_h), w = aspect * h |
| Tracker frame_state bbox | `(cx, cy, w, h)` center | From Kalman state |
| Crop rect | `(x, y, w, h)` top-left | Integer pixel coordinates |
| Scoring input | `[x, y, w, h]` top-left | Detection format, converted inside |

**Conversion points**:
- `tracker._bbox_topleft_to_center()`: detection `[x,y,w,h]` to `(cx,cy,w,h)` for Kalman update.
- `seeding._bbox_to_center()`: detection `[x,y,w,h]` to `[cx,cy,w,h]` for seed full_person_box.
- `scoring._bbox_center()`: same conversion inside scoring.
- `kalman.measurement_from_bbox()`: `(cx,cy,w,h)` to `(cx,cy,log(h),w/h)`.
- `kalman.get_bbox()`: state `[cx,cy,log_h,aspect]` to `(cx,cy,w,h)`.

## 13. Data flow diagrams

### Seed collection flow

```
User draws torso box
    |
    v
normalize_seed_box() -- clamp aspect, enforce min size
    |
    v
extract_jersey_color() -- median HSV from torso ROI
extract_color_histogram() -- 30x32 H-S histogram
    |
    v
_resolve_full_person_box()
    |-- detector available? --> detect(frame) --> find_overlapping_person()
    |                                               |-- IoU > 0.1? --> bbox_to_center(det)
    |                                               |-- no overlap --> estimate_full_person_from_torso()
    |-- no detector ---------> estimate_full_person_from_torso()
    |
    v
seed dict {frame_index, torso_box, full_person_box, jersey_hsv, color_histogram}
```

### Tracking pipeline flow

```
Phase 1: Detection pass
    VideoCapture --> detect(frame) every N frames --> all_detections[frame_idx]
    (parallel: split across ProcessPoolExecutor workers)

Phase 2+3: Bidirectional Kalman
    For each direction (forward / backward):
        Initialize Kalman from edge seed
        For each frame:
            Check seed reinit (visible/absent/obstructed)
            kalman.predict()
            Clamp velocities (vy, v_log_h)
            Freeze velocities if streak > threshold
            apply_hard_gates(detections) --> score_candidates() --> select_best()
            If match: kalman.update(), source="detected"
            If no match: decay confidence, source="predicted"

Phase 4: Merge
    Per frame: pick higher confidence from forward vs backward

Phase 5: Interpolation
    Find predicted-only gaps >= 3 frames (no absent frames)
    Linear interpolation between detected anchors

Phase 6: Crop
    CropController.update(bbox, confidence) per frame
    Output: crop_rects list
```

### Encoding pipeline flow

```
VideoReader --> iterate frames
    |
    v
crop.apply_crop(frame, crop_rect) --> numpy slice with zero-padding
    |
    v
cv2.resize(cropped, (out_w, out_h))
    |
    v
[optional] draw_debug_overlay_cropped() -- bbox, crosshair, confidence bar
    |
    v
VideoWriter.write_frame() --> ffmpeg stdin pipe
    |
    v
copy_audio(original, temp_video, output) --> ffmpeg -c:v copy -c:a aac
```

## 14. Known issues and error-prone patterns

### Numpy type contamination in seeds YAML

Seeds from the interactive UI contain `numpy.integer`, `numpy.floating`, and
`numpy.ndarray` values. `_sanitize_seeds_for_yaml()` in cli.py strips these
before saving, but `color_histogram` arrays are dropped entirely (not saved to
YAML). Seeds loaded from YAML lack histogram data, which means the color scoring
path (if implemented) would have no histogram to compare against on reload.

### Placeholder scoring terms

Three of six scoring terms always return 0.5:
- `color_score`: `_compute_color_score()` ignores the appearance dict entirely.
- `path_score`: hardcoded 0.5 in `score_candidates()`.
- `motion_score`: hardcoded 0.5 in `score_candidates()`.

These contribute `0.15 * 0.5 + 0.10 * 0.5 + 0.05 * 0.5 = 0.15` constant bias
to every candidate's score. The effective scoring uses only 3 of 6 terms
(detect, predict, size) with total effective weight of 0.70.

### Inconsistent streak logic

`_find_worst_streaks()` in cli.py counts "predicted", "interpolated", and "absent"
frames as missed-detection frames for streak computation.
The `max_streak` counter in `main()` counts only "predicted" frames,
excluding interpolated frames. This means `_find_worst_streaks()` reports
longer streaks than `max_streak` for the same data.

### Resolution-independent displacement cap

`max_displacement_per_frame` defaults to 80 pixels regardless of video resolution.
At 4K this is very tight (80/3840 = 2% of frame width); at 480p it is very loose
(80/640 = 12.5%). The vertical limit uses `pred_h * 0.5` which scales with the
runner, but the displacement cap does not.

### Missing diagnostics on first --add-seeds run

If `--add-seeds` is run but no diagnostics file exists from a previous render,
`load_diagnostics()` returns an empty dict. The code loads `diag.get("bad_streaks", [])`,
`diag.get("bbox_positions", [])`, etc., which all return empty lists. All six
target sources produce empty results, and the tool prints "no problem regions found"
and returns. This is technically correct but gives no guidance to the user.
As of current code, `--add-seeds` now raises `RuntimeError` if no saved seeds exist,
which prevents the empty-diagnostics case for the seeds path but not for diagnostics.

### Velocity freeze boundary

`tracker.py:344`: `if missed_streak > velocity_freeze_streak` uses `>` (strict),
so with default `velocity_freeze_streak=3`, freezing starts at streak 4.
The variable name and config name suggest freezing at streak 3. This is an
off-by-one that may be intentional but is undocumented.

### O(N^2) interpolation anchor search

`_interpolate_predicted_gaps()` scans backward from each gap start to find anchor A
and forward from each gap end to find anchor B, using linear scans through the
full frame list. For a video with many gaps, this is O(gaps * frames). Could be
improved with a precomputed index of detected frame positions.

### NMS return type inconsistency

`detection.py:207-209`: `cv2.dnn.NMSBoxes()` returns a flat array in some OpenCV
versions and a nested array in others. The code handles this:
`i = int(idx) if numpy.ndim(idx) == 0 else int(idx[0])`. This is correct but
fragile -- if OpenCV changes the return type again, it would break silently.

### Log-height zero edge case

`kalman.measurement_from_bbox()` computes `math.log(h)` with no guard against
`h <= 0`. A degenerate detection with zero height would cause a math domain error.
The hard gates reject `cand_h <= 0` in the aspect ratio check, but if a seed
has zero height, `create_kalman()` would also crash.

### Covariance inversion stability

`kalman.update()` uses `numpy.linalg.inv(S)` to invert the innovation covariance.
If S becomes singular or near-singular (which can happen with very low process
noise and repeated predictions without updates), this will raise `LinAlgError`
or produce numerically unstable results. A pseudoinverse or Cholesky
decomposition would be more robust.

### YAML is wrong format for large per-frame data

The diagnostics file reaches 53K-81K lines (1-1.5 MB) for short videos because
YAML serializes each `[frame_idx, cx, cy, w, h]` entry across 5 indented lines.
`bbox_all_frames` alone is ~20K lines for a 4115-frame video. The seeds file
(~4700 lines for 303 seeds) is also verbose. These files are pure numeric
tabular data with no human editing need. JSON would reduce file sizes by
3-5x and load/save significantly faster. YAML is appropriate for the config
file (56-67 lines, human-editable) but not for the per-frame arrays.

### bbox_positions diagnostic offset bug

`cli.py:1154-1155`: The bbox_positions diagnostic computes center as
`s["bbox"][0] + s["bbox"][2] / 2` where bbox is already in center format
`(cx, cy, w, h)`. This computes `cx + w/2`, which is the right edge, not the
center. The comment on line 1141-1143 acknowledges this bug but notes that
`_find_stall_regions` uses relative displacement, so the constant offset cancels
out. Still, any future consumer of `bbox_positions` expecting true centers would
get wrong values.

## 15. Differences from original plan

The original plan is documented in [docs/TRACK_RUNNER_TOOL_PLAN.md](docs/TRACK_RUNNER_TOOL_PLAN.md).

### Planned but not implemented

| Planned module | Status |
| --- | --- |
| `path_prior.py` | Not implemented. Scoring weight `w_path=0.10` contributes constant 0.5. |
| `reacquisition.py` | Not implemented as a separate module. Partial logic exists inline: search radius widens after 5 missed frames; velocity freezes after 3 misses. No dedicated state machine. |
| `motion_compensation.py` | Not implemented. Config section exists (`camera_compensation`) but no code reads it. |
| `report.py` | Not implemented as a module. Quality reporting is inline in `cli.py`. Debug overlay is in `encoder.py`. No sidecar YAML report. |
| Evaluation harness | Not implemented: no `generate_track_clips.py`, `evaluate_tracker.py`, or `run_ablation.py`. |
| `--draw-roi` flag | Not implemented. No ROI polygon support. |
| `--suggest-seeds` flag | Not implemented. `--add-seeds` serves a similar purpose with six automated target sources. |

### Parameter values that drifted from plan

| Parameter | Plan default | Current default |
| --- | --- | --- |
| `detect_interval` | 4 | 1 |
| `hard_gate_scale_band` | 3.0 | 2.0 |
| `min_crop_size` | 360 | 200 |
| `confidence_threshold` (detection) | not specified | 0.25 |
| `nms_threshold` | not specified | 0.45 |

### Structural changes from plan

- Plan placed files under `tools/track_runner/`. Implementation uses `emwy_tools/track_runner/`.
- Plan specified `cli.py` as entry point via `python -m tools.track_runner`. Implementation uses
  `track_runner.py` as a thin wrapper that imports `cli.main()`.
- Plan described `seeding.py` handling `--draw-roi`. Implementation handles
  absence markers (`not_in_frame`, `obstructed`) instead.
- Plan described confidence-weighted averaging for merge. Implementation uses
  simple pick-higher-confidence.
- Plan described reacquisition state machine with explicit window and snap-back.
  Implementation uses inline search radius widening and velocity freezing.
- Plan described tracker running detection every N frames with Kalman bridging gaps.
  Implementation separates detection pass (phase 1) from Kalman passes (phases 2-3),
  which is architecturally cleaner.
- Plan described jersey color as a tie-breaker identity check.
  Implementation extracts jersey color but never uses it for scoring.
