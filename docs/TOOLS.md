# Tools

Utility scripts live in `tools/` and are not part of the core render pipeline.

## silence_annotator.py

Detects silence in a video or audio file and writes an EMWY v2 YAML project
that fast forwards the silent sections by default.
The YAML report is always written to `<input>.emwy.yaml`.
The detector is pure Python; FFmpeg is used only to extract audio. Audio is
always downmixed to mono.
When fast-forward overlays are enabled, the YAML includes a transparent overlay
track that labels accelerated sections in output time.

Example:

```bash
python3 tools/silence_annotator.py -i movie.mp4
python3 emwy.py -y movie.emwy.yaml
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

The config file controls thresholds, speed multipliers, overlay settings, and
auto-threshold tuning. Use it to avoid a long list of CLI flags.

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
  speeds:
    silence: 10.0
    content: 1.0
  overlay:
    enabled: true
    text_template: "Fast Forward {speed}X >>>"
    geometry: [0.1, 0.4, 0.8, 0.2]
    opacity: 0.9
    font_size: 96
    text_color: "#ffffff"
  auto_threshold:
    enabled: false
    step_db: 2.0
    max_db: -5.0
    max_tries: 20
```

Dependencies: `ffmpeg`, `ffprobe`, `numpy`. `matplotlib` is required for `--debug` plots.

## video_scruncher.py

Design doc for compressing silent segments while preserving visual diversity.
Currently a spec-only placeholder.
