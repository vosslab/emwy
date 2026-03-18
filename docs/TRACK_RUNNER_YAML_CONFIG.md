# Track runner YAML config reference

The track runner config file controls detection, crop behavior, and encoding
for the crop-and-follow pipeline. It is auto-created at
`tr_config/{video}.track_runner.config.yaml` on first run.

## Minimal example

```yaml
track_runner: 2
detection:
  model: yolov8n
  confidence_threshold: 0.25
processing:
  crop_aspect: '16:9'
  crop_fill_ratio: 0.1
  video_codec: libx264
  crf: 18
  encode_filters:
  - bilateral
  - auto_levels
  - hqdn3d
```

## Top-level keys

| Key | Required | Description |
| --- | --- | --- |
| `track_runner` | yes | Schema version, must be `2` |
| `detection` | yes | Object detection model settings |
| `processing` | yes | Crop, codec, and filter settings |

## Detection section

| Key | Default | Description |
| --- | --- | --- |
| `model` | `yolov8n` | YOLO model name for person detection |
| `confidence_threshold` | `0.25` | Minimum detection confidence (0.0-1.0) |

## Processing section

### Required keys

| Key | Default | Description |
| --- | --- | --- |
| `crop_aspect` | `16:9` | Output aspect ratio as `W:H` string |
| `crop_fill_ratio` | `0.1` | Target fraction of crop height the subject fills |
| `video_codec` | `libx264` | FFmpeg video codec name |
| `crf` | `18` | Constant rate factor (lower = higher quality) |
| `encode_filters` | `[bilateral, auto_levels, hqdn3d]` | Ordered filter pipeline for encode |

### Crop mode

| Key | Default | Description |
| --- | --- | --- |
| `crop_mode` | `smooth` | Crop algorithm: `smooth`, `direct_center`, or `smart` |

**`smooth`** (default): Online controller that tracks the subject with exponential
smoothing, deadband, and velocity capping. Reacts to the trajectory frame by frame.
Good general-purpose choice but assumes reasonably stable input. Can be combined
with offline post-smoothing for better results on shaky footage.

**`direct_center`**: Offline algorithm that centers the crop directly on the solved
trajectory, then applies forward-backward EMA smoothing. Sees the full trajectory
(past and future) before deciding crop positions, so it handles sudden jumps
better than `smooth` mode. Recommended for handheld or shaky camera footage.

**`smart`**: Experimental regime-switching crop controller. Classifies trajectory
spans into regimes (clear, uncertain, distance) and applies different crop targets
per regime. Uses `direct_center`-style offline processing with per-frame fill_ratio
and zoom rate from the regime policy. Includes vertical asymmetry and torso
protection composition rules. Thresholds are provisional.

### Smooth mode tuning

These keys only apply when `crop_mode: smooth`.

| Key | Default | Description |
| --- | --- | --- |
| `crop_smoothing_attack` | `0.15` | EMA alpha for large corrections (higher = faster response) |
| `crop_smoothing_release` | `0.05` | EMA alpha for small drift (higher = faster drift) |
| `crop_max_velocity` | `30.0` | Hard cap on crop center movement per frame (pixels) |
| `crop_velocity_scale` | `2.0` | Adaptive velocity multiplier based on subject speed |
| `crop_displacement_alpha` | `0.1` | EMA alpha for tracking subject displacement |
| `crop_min_size` | `200` | Minimum crop height in pixels |

#### Post-smoothing (optional, applied after smooth mode)

These apply an offline forward-backward EMA pass on top of the smooth controller
output. This sees future frames and produces much more stable results.

| Key | Default | Description |
| --- | --- | --- |
| `crop_post_smooth_strength` | `0.0` | Position smoothing alpha (0 = off, try 0.05-0.15) |
| `crop_post_smooth_size_strength` | `0.0` | Size smoothing alpha (0 = defaults to half of position) |
| `crop_post_smooth_max_velocity` | `0.0` | Velocity cap after post-smoothing (0 = no cap) |

### Direct center mode tuning

These keys only apply when `crop_mode: direct_center`. The direct center
algorithm reuses `crop_post_smooth_*` keys for its smoothing pass.

| Key | Default | Description |
| --- | --- | --- |
| `crop_post_smooth_strength` | `0.0` | Position smoothing alpha (0 = no smoothing) |
| `crop_post_smooth_size_strength` | `0.0` | Size smoothing alpha (0 = defaults to half of position) |
| `crop_post_smooth_max_velocity` | `0.0` | Velocity cap on center per frame (0 = no cap) |
| `crop_min_size` | `200` | Minimum crop height in pixels |

### Encode filters

`encode_filters` is an ordered list of filter names applied during encoding.
Filters run in two stages: OpenCV filters run per-frame in Python before writing,
FFmpeg filters run as `-vf` flags in the encode command.

**OpenCV filters** (per-frame, Python):

| Name | Description |
| --- | --- |
| `bilateral` | Edge-preserving noise reduction |
| `clahe` | Adaptive contrast enhancement (good for low light) |
| `sharpen` | Unsharp mask sharpening |
| `denoise` | Non-local means denoising (strong, slow) |
| `auto_levels` | Per-channel percentile histogram stretch |

**FFmpeg filters** (in encode command):

| Name | Description |
| --- | --- |
| `hqdn3d` | High-quality 3D denoising (spatial + temporal) |
| `nlmeans` | Non-local means denoising |

When both types are present, OpenCV filters run first per-frame, then FFmpeg
filters are applied during the final encode pass. When any encode filters are
active, the resizing interpolation upgrades from bilinear to Lanczos.

### Output resolution

| Key | Default | Description |
| --- | --- | --- |
| `output_resolution` | auto | Explicit `[width, height]` for output. If omitted, uses the median of all crop rectangles. |

## CLI flags that override config

| Flag | Overrides |
| --- | --- |
| `-c CONFIG` | Config file path (default: `tr_config/{video}.track_runner.config.yaml`) |
| `-o OUTPUT` | Output video path (default: next to input with `_tracked` suffix) |
| `--aspect W:H` | `crop_aspect` for this encode only |
| `-F filters` | `encode_filters` as comma-separated list for this encode only |

## Recommended presets

### Handheld/shaky camera (e.g. filming from stands)

```yaml
processing:
  crop_mode: direct_center
  crop_aspect: '16:9'
  crop_fill_ratio: 0.1
  crop_post_smooth_strength: 0.03
  crop_post_smooth_max_velocity: 15.0
  video_codec: libx264
  crf: 18
  encode_filters:
  - bilateral
  - auto_levels
  - hqdn3d
```

### Stable tripod footage

```yaml
processing:
  crop_mode: smooth
  crop_aspect: '16:9'
  crop_fill_ratio: 0.1
  video_codec: libx264
  crf: 18
  encode_filters:
  - auto_levels
  - hqdn3d
```

### Maximum smoothness (slow camera movement feel)

```yaml
processing:
  crop_mode: direct_center
  crop_aspect: '16:9'
  crop_fill_ratio: 0.1
  crop_post_smooth_strength: 0.02
  crop_post_smooth_max_velocity: 10.0
  video_codec: libx264
  crf: 18
  encode_filters:
  - bilateral
  - auto_levels
  - hqdn3d
```
