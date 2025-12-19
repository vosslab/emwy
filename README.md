# emwy

**emwy** is a command-line video editor for turning long, raw recordings into clean, watchable videos using a simple YAML project file. It is designed for lecture capture, problem-solving videos, and other educational or technical recordings where speed, repeatability, and precision matter.

Internally, emwy compiles your project into **MLT XML** and renders it using **melt**, with FFmpeg handling encoding and muxing.

emwy is pronounced as one syllable, like a child trying to say "Emily" but replacing the "L" sound with a "W": *em-wee*.

## 30-second quickstart

### Install emwy

```bash
pip install emwy
```

### Install system dependencies

You need at least:

- ffmpeg
- mlt / melt
- sox
- mediainfo

See **docs/INSTALL.md** for full platform-specific instructions.

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

playlists:
  video_base:
    kind: video
    playlist:
      - source: {asset: lecture, in: "00:10.0", out: "05:00.0"}

  audio_main:
    kind: audio
    playlist:
      - source: {asset: lecture, in: "00:10.0", out: "05:00.0"}

stack:
  tracks:
    - {playlist: video_base, role: base}
    - {playlist: audio_main, role: main}

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
generated MLT XML
   ->
rendered by melt
   ->
encoded / muxed output
```

MLT XML can be saved and inspected, which makes emwy suitable for headless systems, servers, and CI pipelines.

## Documentation

Deeper documentation lives in the **docs/** directory:

- **docs/INSTALL.md**
  System dependencies, platform notes, and install verification.

- **docs/FORMAT.md**
  Project file format, time rules, and minimal and complete examples.

- **docs/COOKBOOK.md**
  Common editing recipes and reusable patterns.

- **docs/CLI.md**
  Command-line options, validation, dry runs, and logging.

- **docs/SHOTCUT.md**
  Shotcut-compatible export mode and round-tripping notes.

- **docs/DEBUGGING.md**
  Common errors, diagnostics, and media inspection tips.

- **docs/FAQ.md**
  Design decisions, limitations, and common questions.

- **docs/CHANGELOG.md**
  User-facing changes and format migration notes.

- **docs/CONTRIBUTING.md**
  Developer setup, tests, and contribution guidelines.

Optional planning and policy documents:

- **docs/ROADMAP.md**
- **docs/SECURITY.md**
- **AGENTS.md**

## Compatibility

- OS: tested primarily on Linux
- Python: 3.8+
- Render engine: MLT / melt

### Shotcut

emwy can export **Shotcut-compatible MLT XML** so Shotcut opens the project as a normal editable timeline.
See **docs/SHOTCUT.md** for details and limitations.

## Development

- Follow **docs/CONTRIBUTING.md** and **PYTHON_STYLE.md** for coding conventions.
- Use `pip install -r pip_requirements.txt` in a virtual environment to sync tooling.
- Check **AGENTS.md** to understand who maintains each subsystem.
- Review **docs/CHANGELOG.md** before shipping user-facing changes.

## Format stability

- Current format version: **emwy YAML v2**
- The format is still evolving
- Validation is strict by default, with warnings where safe

The authoritative specification is in **docs/FORMAT.md**.

## MLT Export

To export MLT XML for inspection or melt rendering:

```bash
python3 -m emwylib.exporters.mlt -y example.emwy.yaml -o example.mlt
```

## License and attribution

See **LICENSE**.

emwy builds on excellent upstream tools:

- MLT Multimedia Framework
- FFmpeg
- SoX
- MediaInfo
