# emwy

emwy is a command-line video editor for turning long recordings into clean outputs from a YAML project file. It targets lecture capture, demos, and other repeatable technical edits, and keeps projects compatible with MLT XML for import/export.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md): System dependencies and install steps.
- [docs/USAGE.md](docs/USAGE.md): CLI workflows and example commands.
- [docs/EMWY_YAML_v2_SPEC.md](docs/EMWY_YAML_v2_SPEC.md): YAML project file specification.
- [docs/TOOLS.md](docs/TOOLS.md): Helper scripts in `emwy_tools/` and how to use them.
- [docs/CODE_ARCHITECTURE.md](docs/CODE_ARCHITECTURE.md): Core pipeline layout and data flow.
- [docs/FILE_STRUCTURE.md](docs/FILE_STRUCTURE.md): Repository layout and where to find things.

Additional docs live in `docs/`.

## Quick start

Validate a sample project:

```bash
source source_me.sh && python emwy_cli.py -n -y samples/gangnam.emwy.yaml
```

Install the system dependencies listed in [docs/INSTALL.md](docs/INSTALL.md) before running a real render.

## Testing

```bash
source source_me.sh && python -m pytest tests/
```
