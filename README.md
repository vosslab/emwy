# emwy

**emwy** is a command-line video editor for turning long, raw recordings into clean, watchable videos using a simple YAML project file. It is designed for lecture capture, problem-solving videos, and other educational or technical recordings where speed, repeatability, and precision matter.

Internally, emwy compiles timeline segments into a render plan, renders A/V segments with FFmpeg/SoX, and concatenates them with mkvmerge. MLT export is optional for interoperability.

emwy is pronounced as one syllable, like a child trying to say "Emily" but replacing the "L" sound with a "W": *em-wee*.

## 30-second quickstart

### Install emwy

```bash
pip install emwy
```

### Install system dependencies

You need at least:

- ffmpeg
- sox
- mkvmerge (mkvtoolnix)
- mediainfo
- mlt / melt (optional, for MLT export)

See **[docs/INSTALL.md](docs/INSTALL.md)** for full platform-specific instructions.

Install Python dependencies with:

```bash
pip install -r pip_requirements.txt
```

### Create a minimal project

Save as `example.emwy.yaml` (recommended extension for v2):

```yaml
emwy: 2

profile:
  fps: "30000/1001"
  resolution: [1920, 1080]
  audio: {sample_rate: 48000, channels: stereo}

assets:
  video:
    lecture: {file: lecture.mp4}

timeline:
  segments:
    - source: {asset: lecture, in: "00:10.0", out: "05:00.0"}

output:
  file: lecture_trimmed.mkv
```

### Run emwy

```bash
emwy example.emwy.yaml
```

### Output

```
lecture_trimmed.mkv
```

## What emwy is for

- Trimming lectures and screen recordings
- Speeding up silent or repetitive sections
- Adding chapter cards and YouTube chapters
- Simple overlays like picture-in-picture or slides
- Audio cleanup such as normalization and noise reduction
- Fully scriptable, reproducible edits

## What emwy is not for

- Complex motion graphics
- Color grading
- Visual effects or animation-heavy edits
- Replacing full GUI NLEs for cinematic workflows

## How it works

The pipeline is intentionally simple:

```
.emwy.yaml
   ->
validated project graph
   ->
compiled render plan
   ->
per-segment A/V renders
   ->
concatenated output
```

MLT XML can be exported and inspected, which makes emwy suitable for headless systems, servers, and CI pipelines.

## Documentation

Deeper documentation lives in the **docs/** directory:

- **[docs/INSTALL.md](docs/INSTALL.md)**
  System dependencies, platform notes, and install verification.

- **[docs/FORMAT.md](docs/FORMAT.md)**
  Project file format, time rules, and minimal and complete examples.

- **[docs/COOKBOOK.md](docs/COOKBOOK.md)**
  Common editing recipes and reusable patterns.

- **[docs/CLI.md](docs/CLI.md)**
  Command-line options, validation, dry runs, and logging.

- **[docs/TOOLS.md](docs/TOOLS.md)**
  Helper scripts in `tools/` and how to use them.

- **[docs/SHOTCUT.md](docs/SHOTCUT.md)**
  Shotcut-compatible export mode and round-tripping notes.

- **[docs/DEBUGGING.md](docs/DEBUGGING.md)**
  Common errors, diagnostics, and media inspection tips.

- **[docs/FAQ.md](docs/FAQ.md)**
  Design decisions, limitations, and common questions.

- **[docs/CHANGELOG.md](docs/CHANGELOG.md)**
  User-facing changes and format migration notes.

- **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)**
  Developer setup, tests, and contribution guidelines.

- **[docs/CODE_ARCHITECTURE.md](docs/CODE_ARCHITECTURE.md)**
  High-level code structure and module responsibilities.

Optional planning and policy documents:

- **[docs/ROADMAP.md](docs/ROADMAP.md)**
- **[docs/SECURITY.md](docs/SECURITY.md)**
- **[AGENTS.md](AGENTS.md)**

## Compatibility

- OS: tested primarily on Linux
- Python: 3.8+
- Render engine: FFmpeg/SoX + mkvmerge (MLT optional for export)

### Shotcut

emwy can export **Shotcut-compatible MLT XML** so Shotcut opens the project as a normal editable timeline.
See **[docs/SHOTCUT.md](docs/SHOTCUT.md)** for details and limitations.

## Development

- Follow **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** and **[docs/PYTHON_STYLE.md](docs/PYTHON_STYLE.md)** for coding conventions.
- Use `pip install -r pip_requirements.txt` in a virtual environment to sync tooling.
- Check **[AGENTS.md](AGENTS.md)** to understand who maintains each subsystem.
- Review **[docs/CHANGELOG.md](docs/CHANGELOG.md)** before shipping user-facing changes.

## Format stability

- Current format version: **emwy YAML v2**
- The format is still evolving
- Validation is strict by default, with warnings where safe

The authoritative specification is in **[docs/FORMAT.md](docs/FORMAT.md)**.

## MLT Export

To export MLT XML for inspection or melt rendering:

```bash
python3 -m emwylib.exporters.mlt -y example.emwy.yaml -o example.mlt
```

## License and attribution

See **LICENSE**.

emwy builds on excellent upstream tools:

- FFmpeg
- SoX
- MediaInfo
- mkvmerge (mkvtoolnix)
- MLT Multimedia Framework (export)
