# Installation Guide

## System Requirements
- Linux, macOS, or Windows Subsystem for Linux with FFmpeg, MLT/melt, SoX, and MediaInfo available in the `PATH`.
- Python 3.12 recommended, Python 3.8 minimum.
- At least 8 GB RAM for rendering hour-long lessons plus temporary disk space equal to your source footage size.

## Python Environment
1. Create or activate a virtual environment (`python3 -m venv .venv && source .venv/bin/activate`).
2. Install emwy and helper tools:
   ```bash
   pip install -r pip_requirements.txt
   pip install -e .
   ```
3. Verify dependencies with `pyflakes` and `python -m emwy --help`.

## Media Tooling
- **FFmpeg**: Required for extracting, transcoding, and muxing. Package managers usually provide an up-to-date build.
- **MLT / melt**: Provide the timeline engine. On macOS use Homebrew (`brew install mlt`).
- **SoX**: Handles normalization and noise sampling. Install via your package manager.
- **MediaInfo**: Used for probing assets and validating codecs.

## Post-Install Checks
1. Run `tests/run_samples.sh` to ensure the CLI renders bundled sample projects.
2. Confirm `emwy --save-mlt sample.emwy.yaml sample.mlt` writes MLT XML.
3. Inspect generated artifacts under `samples/output/` for AV-sync, resolution, and card placement.

If any tool is missing, re-run installation for that component and ensure its binary is accessible.
