# Install

Install emwy to run the CLI from this repo and access the Python modules that
power renders and exporters.

## Requirements

- Python 3.12.
- System tools: `ffmpeg`, `sox`, `mkvtoolnix` (provides `mkvmerge`), `mediainfo`, and `mlt` (provides `melt`).
- macOS with Homebrew is the primary development platform.

## Install steps

Clone the repo and install system dependencies with Homebrew:

```bash
brew bundle
```

Install Python dependencies:

```bash
pip install -r pip_requirements.txt
```

Optionally install the package in editable mode for the `emwy` console script:

```bash
pip install -e .
```

## Verify install

```bash
source source_me.sh && python emwy_cli.py -h
```

## Known gaps

- The `emwy` console script has not been confirmed as a packaged entry point.
- Only macOS with Homebrew has been tested; other platforms may need manual dependency setup.
