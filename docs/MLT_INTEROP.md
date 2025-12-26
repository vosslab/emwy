# MLT interop guide

This guide explains how EMWY YAML maps to MLT XML today and what round-tripping
looks like in practice. See [docs/EXPORT_MLT_XML_SPEC.md](docs/EXPORT_MLT_XML_SPEC.md)
for exact export behavior and [docs/IMPORT_MLT_XML_SPEC.md](docs/IMPORT_MLT_XML_SPEC.md)
for import ideas.

## Current status

- Export to MLT XML is supported via `python3 -m emwylib.exporters.mlt`.
- Import from MLT XML is not implemented yet.
- Shotcut export uses the same MLT XML format with extra annotations; see
  [docs/SHOTCUT.md](docs/SHOTCUT.md).

## Mapping overview

EMWY YAML uses a timeline-first authoring surface that compiles into playlists
and a stack. The MLT export maps those compiled structures as follows:

- `assets.*` -> MLT producers
- `playlists.*` -> MLT `<playlist>` elements
- `stack.tracks` -> MLT `<multitrack>` tracks on a `<tractor>`
- `stack.overlays` -> MLT transitions (not emitted yet)
- `output` -> MLT consumer (not emitted; export is project-only)

## Timeline to playlists

`timeline.segments` is compiled into:

- `video_base` playlist for video entries
- `audio_main` playlist for audio entries

Each playlist entry is emitted as:

- `source` -> playlist entry referencing an `avformat` producer
- `blank` -> playlist `<blank>`
- `generator` -> playlist entry referencing a `color` producer (cards are
  pre-rendered, not editable text)

## Overlays

Overlay tracks are authored in `timeline.overlays` and compile into overlay
playlists plus `stack.overlays`. The current MLT exporter does not emit overlay
tracks or transitions, so overlays are ignored in MLT XML output. Native emwy
rendering does support overlays.

## Round-trip workflow

Because MLT import is not implemented yet, the recommended round-trip is:

1. Author EMWY YAML.
2. Export MLT XML.
3. Edit in Shotcut or other MLT editors.
4. Render from Shotcut or the MLT toolchain.

If you need to return to EMWY YAML, keep the YAML as the source of truth and
repeat the export when changes are required.
