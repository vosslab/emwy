# Install

Install emwy to run the CLI from this repo and access the Python modules that
power renders and exporters.

## Requirements

- Python 3.8+ (3.12 recommended).
- ffmpeg, sox, mkvmerge, and mediainfo available on PATH.
- MLT/melt only if you plan to use MLT XML output with external tools.

## Install steps

- Create and activate a virtual environment:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```
- Install Python dependencies:
  ```bash
  pip install -r pip_requirements.txt
  ```
- Install the package in editable mode if you want the `emwy` console script:
  ```bash
  pip install -e .
  ```

## Verify install

```bash
python3 emwy_cli.py -h
```

## Known gaps

- TODO: Confirm the `emwy` console script works as packaged and document its
  preferred invocation.
- TODO: Document supported operating systems and any platform-specific setup.
