# Debugging Guide

## Common Issues
- **Validation errors**: Check line numbers in the YAML file and ensure references exist.
- **Missing media**: Confirm asset paths are relative to the project file or absolute.
- **Audio drift**: Reprobe the source with `mediainfo` and ensure `profile.fps` matches the footage.

## Useful Commands
- `emwy --dry-run project.yaml`: Run validators only.
- `emwy --dump-plan project.yaml`: Print the compiled playlists for inspection.
- `python3 -m emwylib.exporters.mlt -y project.emwy.yaml -o out.mlt`: Inspect the generated timeline.
- `melt out.mlt`: Render directly with melt to isolate FFmpeg issues (requires MLT).
- `ffmpeg -i clip.mp4 -hide_banner`: Inspect codecs and durations.

## Troubleshooting Steps
1. Re-render a small subsection by trimming `timeline.segments` to narrow the problem.
2. Use `--keep-temp` to keep intermediate audio/video for inspection.
3. Compare the timestamps in the YAML vs. MediaInfo to catch timecode typos.
4. Run `pyflakes` and unit tests to make sure helper scripts are clean.

If you find a repeatable bug, file an issue with the failing YAML, logs, and tool versions.
