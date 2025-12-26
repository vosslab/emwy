# Export MLT XML spec

This document records the current MLT XML export behavior implemented by
`emwylib/exporters/mlt.py`.

## Status

- Export is implemented.
- Overlays are not emitted yet.
- Output is project-only; no consumer is emitted.

## Entry point

Export with:

```bash
python3 -m emwylib.exporters.mlt -y project.emwy.yaml -o project.mlt
```

## Required inputs

- `timeline.segments` is required (compiled into playlists/stack).
- `stack.tracks` must include a base video playlist and main audio playlist.

## Profile mapping

`profile` fields map to the MLT `<profile>` element:

- `fps` -> `frame_rate_num`, `frame_rate_den`
- `resolution` -> `width`, `height`
- Display aspect is derived from width/height

## Playlist mapping

Each playlist becomes a `<playlist id="...">` element.

### Entry types

- `source` -> `<entry producer="...">` referencing an `avformat` or `timewarp`
  producer
- `blank` -> `<blank length="...">`
- `generator` -> `<entry producer="...">` referencing a `color` producer

### Generator kinds

Supported generator kinds:

- `black`
- `chapter_card`
- `title_card`
- `still`

Cards and stills are exported as pre-rendered clips, not editable MLT text
filters. The export uses a `color` producer placeholder.

## Producer mapping

`source` entries emit a producer:

- `mlt_service=avformat` for speed 1.0
- `mlt_service=timewarp` for other speeds
- `resource` is either the source file path or `speed:filepath` when timewarp

## Tracks and tractor

`stack.tracks` becomes:

- a `<tractor id="tractor0">`
- a `<multitrack>` with `<track producer="playlist_id">` entries

Only the base video track and the main audio track are emitted. Overlay tracks
are ignored.

## Known gaps

- Overlay transitions are not emitted.
- No consumer is emitted.
- Shotcut annotations are only added by `docs/SHOTCUT.md` guidance; no dedicated
  export mode exists yet.
