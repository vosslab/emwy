# Tools

Utility scripts live in `tools/` and are not part of the core render pipeline.

## silence_annotator.py

Detects silence in a video or audio file and writes an EMWY v2 YAML project
that fast forwards the silent sections by default.
The YAML report is always written to `<input>.emwy.yaml`.
The detector is pure Python; FFmpeg is used only to extract audio. Audio is
always downmixed to mono.
When fast-forward overlays are enabled, the YAML includes a transparent overlay
track with a master template (using `overlay_text` and `assets.overlay_text_styles`)
applied to fast-forward sections in output time.
By default, the YAML includes an intro title card named after the input file.
Generated YAML also includes `assets.playback_styles` so speed presets can be
edited in one place.

Example:

```bash
python3 tools/silence_annotator.py -i movie.mp4
python3 emwy_cli.py -y movie.emwy.yaml
```

Config file:

- The tool looks for `<input>.silence.config.yaml` by default.
- If it does not exist, a default config is written automatically.
- Use `-c, --config` to point to a different config.
- The config file starts with `silence_annotator: 1` to distinguish it from EMWY YAML.

Common flags:

- `-a, --audio` Optional wav file path to skip extraction
- `-c, --config` Config file path (default: `<input>.silence.config.yaml`)
- `-k, --keep-wav` Keep extracted wav file
- `-d, --debug` Enable verbose debug output and write `<input>.silence.debug.txt` and `.png`
- `-N, --no-fast-forward-overlay` Disable the fast-forward overlay text
- `-l, --trim-leading-silence` Trim leading silence from output
- `-L, --keep-leading-silence` Keep leading silence in output
- `-t, --trim-trailing-silence` Trim trailing silence from output
- `-T, --keep-trailing-silence` Keep trailing silence in output
- `-s, --min-silence` Override minimum silence seconds (legacy)
- `-m, --min-content` Override minimum content seconds (legacy)
- `-S, --silence-speed` Override silence speed multiplier (legacy)
- `-C, --content-speed` Override content speed multiplier (legacy)

The config file controls thresholds, speed multipliers, overlay settings, and
auto-threshold tuning. Use it to avoid a long list of CLI flags.
By default, leading and trailing silence are trimmed from the output.

Example config:

```yaml
silence_annotator: 1
settings:
  detection:
    threshold_db: -40.0
    min_silence: 3.0
    min_content: 1.5
    frame_seconds: 0.25
    hop_seconds: 0.05
    smooth_frames: 5
  trim_leading_silence: true
  trim_trailing_silence: true
  speeds:
    silence: 10.0
    content: 1.0
  overlay:
    enabled: true
    text_template: "Fast Forward {speed}X {animate}"
    geometry: [0.1, 0.4, 0.8, 0.2]
    opacity: 0.9
    font_size: 96
    text_color: "#ffffff"
    animate:
      kind: cycle
      values: [">   ", ">>  ", ">>> ", ">>>>"]
      cadence: 0.5
  title_card:
    enabled: true
    duration: 2.0
    text_template: "{name}"
    font_size: 96
    text_color: "#ffffff"
  auto_threshold:
    enabled: false
    step_db: 2.0
    max_db: -5.0
    max_tries: 20
```

Dependencies: `ffmpeg`, `ffprobe`, `numpy`. `matplotlib` is required for `--debug` plots.

`title_card.text_template` supports `{name}` (input filename without extension).

## stabilize_building.py

Stabilizes "bird on a building" footage as a standalone media-prep step (not an EMWY YAML feature).
This is global stabilization that aims to make the building static, then apply a single static crop
rectangle for the entire output range; by default it prefers crop-to-content but can optionally fall
back to a strictly budgeted border fill for rare jerk frames.

Example:

```bash
python3 tools/stabilize_building.py -i IMG_3495.mov -o IMG_3495.stabilized.mkv --start 0 --duration 30
```

Config file:

- By default, no config file is read or written (code defaults only).
- Use `-c, --config PATH` to read a config; if `PATH` does not exist, the tool writes defaults to `PATH` and then reads it.
- Use `--write-default-config` to write `<input>.stabilize_building.config.yaml` and exit 0.
- Use `--use-default-config` to read `<input>.stabilize_building.config.yaml` (error if missing).
- The config file starts with `stabilize_building: 1` to distinguish it from EMWY YAML.

Outputs:

- Stabilized video file at `--output`.
- Sidecar report written to `<output>.stabilize_building.report.yaml` (or `.json`).

Common flags:

- `--start` Optional start time (seconds or HH:MM:SS[.ms])
- `--duration` Optional duration in seconds
- `--end` Optional end time (seconds or HH:MM:SS[.ms])
- `--copy-subs` Copy subtitle streams if present (no timing or placement edits)
- `--no-copy-audio` Video-only output
- `--keep-temp` Keep intermediate motion files under the cache dir

Example config:

```yaml
stabilize_building: 1
settings:
  engine:
    kind: vidstab
    detect:
      shakiness: 5
      accuracy: 15
      stepsize: 6
      mincontrast: 0.25
      reference_frame: 1
    transform:
      optalgo: opt
      smoothing: 15
  crop:
    min_area_ratio: 0.25
    min_height_px: 0
    min_height_ratio: 0.65
    center_safe_margin: 0.10
  border:
    mode: crop_prefer_fill_fallback
    fill:
      kind: center_patch_median
      patch_fraction: 0.10
      sample_frames: 25
      max_area_ratio: 0.02
      max_frames_ratio: 0.02
      max_consecutive_frames: 15
  rejection:
    mode: budgeted
    max_missing_fraction: 0.05
    max_mad_fraction: 0.50
    max_scale_jump: 0.50
    max_abs_angle_rad: 0.60
    max_abs_zoom_percent: 35.0
    outlier_max_frames_ratio: 0.90
    outlier_max_consecutive_frames: 600
  io:
    cache_dir: null
    report_format: yaml
```

Dependencies: `ffmpeg` (with `vidstabdetect`/`vidstabtransform`), `ffprobe`, `pyyaml`.

## video_scruncher.py

Design doc for compressing silent segments while preserving visual diversity.
Currently a spec-only placeholder.
