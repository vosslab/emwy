# EMWY YAML Format

This document summarizes the v2 source format consumed by `emwy`. The complete specification lives in `EMWY_YAML_v2_SPEC.md`, while this guide highlights how to author everyday projects. The recommended filename extension is `.emwy.yaml`.

## Version Header
Every project starts with `emwy: 2` to declare the schema version. Future releases may add `emwy: 3`; the CLI validates and refuses unknown versions.

## Sections
1. **profile**: Declares fps, resolution, color space hints, and audio defaults (sample rate, channel layout).
2. **assets**: A typed registry of media items (`video`, `audio`, `image`). Each asset object lists a `file` path plus optional metadata such as `speed_map` or `color_space`.
3. **playlists**: Named playlists referencing assets. Each entry describes `kind`, `playlist` items with `source.asset`, optional `in`/`out`, and optional filters (speed, gain, overlays).
4. **stack**: Orders playlists onto virtual tracks. A track entry contains `{playlist: name, role: base|main|overlay, transitions: []}`.
5. **output**: Specifies the muxed file, container hints, preview settings, and export toggles (`save_mlt`, `dry_run`).

## Current v2 Support Notes
- Base video + main audio stack rendering is supported.
- `source`, `blank`, and basic `generator` entries are supported.
- Frame override suffixes (`@frame`) are reserved but not yet implemented.
- Overlays, transitions, stream mapping, and paired audio are planned but not yet implemented.

## Timecodes
- Accept `HH:MM:SS.sss`, `MM:SS.sss`, or frame counts with `@frame` suffix.
- All times must include leading zeros to avoid ambiguity (`00:03.0`).
- For loops or jumps, playlists may specify `repeat: n` or `markers: []`.

## Validation Rules
- Assets must be referenced by at least one playlist or `emwy` warns.
- Track roles must include one `base` video and one `main` audio.
- Output file extension determines the container unless overridden.

For migration tips from v1, see `docs/COOKBOOK.md`. When in doubt, open the generated MLT XML to verify structure before running a full render.
