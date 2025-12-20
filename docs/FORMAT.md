# EMWY YAML Format

This document summarizes the v2 source format consumed by `emwy`. It is a usage-oriented summary; the v2 spec is authoritative. The complete specification lives in [EMWY_YAML_v2_SPEC.md](../EMWY_YAML_v2_SPEC.md), while this guide highlights how to author everyday projects. The recommended filename extension is `.emwy.yaml`.

## Version Header
Every project starts with `emwy: 2` to declare the schema version. Future releases may add `emwy: 3`; the CLI validates and refuses unknown versions.

## Sections
1. **profile**: Declares fps, resolution, color space hints, and audio defaults (sample rate, channel layout).
2. **assets**: A typed registry of media items (`video`, `audio`, `image`, `cards`). Each asset object lists a `file` path plus optional metadata.
3. **timeline**: Ordered list of segments. Each segment is an A/V/S unit with `source`, `blank`, or `generator` entries and optional per-segment `video`/`audio` processing.
4. **output**: Specifies the muxed file, container hints, preview settings, and export toggles (`save_mlt`, `dry_run`).
5. **compiled** (advanced): Optional compiled playlists/stack for export/debugging.

Notes:
- `timeline.segments` is required for all v2 authoring.
- Top-level `playlists` and `stack` are compiled-only details and must not appear in v2 YAML.

## Current v2 Support Notes
- `source`, `blank`, and basic `generator` segments are supported.
- Frame override suffixes (`@frame`) are defined in the v2 spec but not yet implemented.
- Overlays, transitions, and advanced stream mapping are defined in the v2 spec but not yet implemented.

## Assets
- Assets under `assets.video` are assumed to be A/V by default (common camera recordings).
- Do not duplicate A/V files under `assets.audio`.
- For audio-only or video-only assets, use `fill_missing` on the segment.

Example (A/V source):

```yaml
assets:
  video:
    source: {file: "lecture_camera.mkv"}
timeline:
  segments:
    - source: {asset: source, in: "00:00.0", out: "00:30.0"}
```

Example (audio-only):

```yaml
assets:
  audio:
    music: {file: "intro.mp3"}
timeline:
  segments:
    - source:
        asset: music
        in: "00:00.0"
        out: "00:12.0"
        fill_missing: {video: black}
```

Example (chapter card with image background):

```yaml
assets:
  image:
    chapter_bg: {file: "chapter_bg.png"}
  cards:
    chapter_style:
      kind: chapter_card_style
      font_size: 96
      font_file: "fonts/Inter-Bold.ttf"
      text_color: "#ffffff"
      background: {kind: image, asset: chapter_bg}
timeline:
  segments:
    - generator:
        kind: chapter_card
        title: "Problem 1"
        duration: "00:02.0"
        style: chapter_style
        fill_missing: {audio: silence}
```

Example (chapter card with gradient background):

```yaml
assets:
  cards:
    chapter_style:
      kind: chapter_card_style
      font_size: 96
      font_file: "fonts/Inter-Bold.ttf"
      text_color: "#ffffff"
      background:
        kind: gradient
        from: "#101820"
        to: "#2b5876"
        direction: vertical
timeline:
  segments:
    - generator:
        kind: chapter_card
        title: "Problem 2"
        duration: "00:02.0"
        style: chapter_style
        fill_missing: {audio: silence}
```

Tip: set `font_file` for consistent sizing across machines.

## Timecodes
- Accept `HH:MM:SS.sss`, `MM:SS.sss`, or frame counts with `@frame` suffix.
- All times must include leading zeros to avoid ambiguity (`00:03.0`).

## Validation Rules
- Assets must be referenced by at least one segment or `emwy` warns.
- Missing required streams in a segment are errors unless `fill_missing` is set.
- Output file extension determines the container unless overridden.

For migration tips from v1, see [COOKBOOK.md](COOKBOOK.md). When in doubt, export MLT XML to verify structure before running a full render.
