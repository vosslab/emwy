# Tools

Utility scripts live in `tools/` and are not part of the core render pipeline.

## silence_annotator.py

Detects silence in a video or audio file and writes an EMWY v2 YAML project
that fast forwards the silent sections by default.
The YAML report is always written to `<input>.emwy.yaml`.
The detector is pure Python; FFmpeg is used only to extract audio. Audio is
always downmixed to mono.

Example:

```bash
python3 tools/silence_annotator.py -i movie.mp4
python3 emwy.py -y movie.emwy.yaml
```

Common flags:

- `-a, --audio` Optional wav file path to skip extraction
- `-t, --threshold` Silence threshold in dBFS (default: -40)
- `-s, --min-silence` Minimum silence duration in seconds (default: 3.0)
- `-m, --min-content` Minimum content duration in seconds (default: 1.5)
- `-S, --silence-speed` Playback speed for silence segments (default: 10.0)
- `-C, --content-speed` Playback speed for content segments (default: 1.0)
- `-w, --frame` Frame window size in seconds (default: 0.25)
- `-p, --hop` Hop size in seconds (default: 0.05)
- `-q, --smooth` Smoothing window in frames (default: 5)
- `-d, --debug` Enable verbose debug output and write `<input>.silence.debug.txt` and `.png`
- `-u, --auto-threshold` Auto-raise threshold until silence is detected

Dependencies: `ffmpeg`, `ffprobe`, `numpy`. `matplotlib` is required for `--debug` plots.

## video_scruncher.py

Design doc for compressing silent segments while preserving visual diversity.
Currently a spec-only placeholder.
