# Usage

Use emwy to render video projects defined in `.emwy.yaml` files.

## Quick start

Validate a sample project without rendering:

```bash
python3 emwy_cli.py -n -y samples/gangnam.emwy.yaml
```

## CLI

Primary entry points:

```bash
python3 emwy_cli.py -y project.emwy.yaml
python3 emwy_tui.py -y project.emwy.yaml
```

Common flags (CLI):

- `-y, --yaml`: Path to the project YAML (required).
- `-o, --output`: Override `output.file` from the YAML.
- `-n, --dry-run`: Validate only, do not render.
- `-c, --cache-dir`: Directory for temporary render files.
- `-k, --keep-temp`: Preserve temporary render files.
- `-K, --no-keep-temp`: Remove temporary render files (default).
- `-p, --dump-plan`: Print compiled playlists/stack after planning.

The TUI supports the same flags and adds `-d, --debug` to write `emwy_tui.log`.

## Examples

Render a sample project:

```bash
python3 emwy_cli.py -y samples/gangnam.emwy.yaml
```

Export MLT XML for inspection:

```bash
python3 -m emwylib.exporters.mlt -y samples/gangnam.emwy.yaml -o samples/gangnam.mlt
```

Run the Textual TUI with a dry run:

```bash
python3 emwy_tui.py -n -y samples/gangnam.emwy.yaml
```

## Inputs and outputs

- Inputs: `.emwy.yaml` project files plus any referenced media assets.
- Outputs: rendered media at the path specified by `output.file` in the YAML.
- Optional outputs: MLT XML (`.mlt`) when running the exporter module.
- TUI debug log: `emwy_tui.log` when `-d, --debug` is enabled.

## Known gaps

- TODO: Confirm whether the `emwy` console script is supported and document it.
