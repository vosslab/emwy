# Command-Line Interface

The `emwy` executable loads a YAML project, validates it, and renders video via MLT and FFmpeg.

## Usage
```bash
emwy [options] project.emwy.yaml
```

## Common Flags
- `-o, --output FILE`: Override `output.file` from the YAML.
- `-n, --dry-run`: Validate and exit without rendering.
- `-c, --cache-dir PATH`: Directory for temporary render files.
- `-k, --keep-temp`: Preserve intermediate files for inspection.
- `-K, --no-keep-temp`: Remove intermediate files after rendering (default).

## MLT Export
Use the exporter module to write MLT XML for inspection or melt rendering:

```bash
python3 -m emwylib.exporters.mlt -y project.emwy.yaml -o project.mlt
```

## Exit Codes
- `0`: Success.
- `1`: Validation error.
- `2`: External tool failure (FFmpeg/MLT/SoX).

Run `emwy --help` for the full flag list including experimental developer toggles.
