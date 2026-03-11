# Usage

Use emwy to render video projects defined in `.emwy.yaml` files.

## Quick start

Validate a sample project without rendering:

```bash
source source_me.sh && python emwy_cli.py -n -y samples/gangnam.emwy.yaml
```

Render a sample project:

```bash
source source_me.sh && python emwy_cli.py -y samples/gangnam.emwy.yaml
```

## CLI

Primary entry points:

```bash
source source_me.sh && python emwy_cli.py -y project.emwy.yaml
source source_me.sh && python emwy_tui.py -y project.emwy.yaml
```

Common flags (CLI):

- `-y, --yaml`: Path to the project YAML (required).
- `-o, --output`: Override `output.file` from the YAML.
- `-n, --dry-run`: Validate only, do not render.
- `-c, --cache-dir`: Directory for temporary render files.
- `-k, --keep-temp`: Preserve temporary render files.
- `-K, --no-keep-temp`: Remove temporary render files (default).
- `-p, --dump-plan`: Print compiled playlists/stack after planning.
- `-d, --debug`: Write debug log to `emwy_cli.log`.

The TUI supports the same flags and adds `-d, --debug` to write `emwy_tui.log`.

## Tools

Helper scripts for media preparation live in `emwy_tools/`. See [docs/TOOLS.md](docs/TOOLS.md) for details.

## Inputs and outputs

- Inputs: `.emwy.yaml` project files plus any referenced media assets.
- Outputs: rendered media at the path specified by `output.file` in the YAML.
- Optional outputs: MLT XML (`.mlt`) when running the exporter module.
- TUI debug log: `emwy_tui.log` when `-d, --debug` is enabled.

## Known gaps

- The `emwy` console script has not been confirmed as a packaged entry point.
