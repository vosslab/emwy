# emwy

emwy is a command-line video editor for turning long recordings into clean outputs from a YAML project file. It targets lecture capture, demos, and other repeatable technical edits, and keeps projects compatible with MLT XML for import/export.

## Documentation
- [docs/INSTALL.md](docs/INSTALL.md): System dependencies and install verification.
- [docs/USAGE.md](docs/USAGE.md): Primary workflows and example commands.
- [docs/CLI.md](docs/CLI.md): CLI usage, flags, and exit codes.
- [docs/FORMAT.md](docs/FORMAT.md): Project file overview and examples.
- [docs/TOOLS.md](docs/TOOLS.md): Helper scripts in tools/ and how to use them.
- [docs/DEBUGGING.md](docs/DEBUGGING.md): Common errors and diagnostics.
- [docs/CODE_ARCHITECTURE.md](docs/CODE_ARCHITECTURE.md): Core pipeline layout and data flow.
- [docs/FILE_STRUCTURE.md](docs/FILE_STRUCTURE.md): Repository layout and where to find things.

## Quick start
Validate a sample project from this repo:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r pip_requirements.txt
python3 emwy_cli.py -n -y samples/gangnam.emwy.yaml
```

Install the system dependencies listed in [docs/INSTALL.md](docs/INSTALL.md) before running a real render. Remove `-n` to render and set the output path in your YAML file.
