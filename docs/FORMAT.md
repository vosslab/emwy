# EMWY YAML Format

This document summarizes the v2 source format consumed by `emwy`. It is a usage-oriented summary; the v2 spec is authoritative. The complete specification lives in [EMWY_YAML_v2_SPEC.md](../EMWY_YAML_v2_SPEC.md), while this guide highlights how to author everyday projects. The recommended filename extension is `.emwy.yaml`.

## Version Header
Every project starts with `emwy: 2` to declare the schema version. Future releases may add `emwy: 3`; the CLI validates and refuses unknown versions.

## Sections
1. **profile**: Declares fps, resolution, color space hints, and audio defaults (sample rate, channel layout).
2. **assets**: A typed registry of media items (`video`, `audio`, `image`, `cards`, `overlay_text_styles`, `playback_styles`). Each asset object lists a `file` path plus optional metadata.
3. **timeline**: Ordered list of segments plus optional overlay tracks. Each segment is an A/V/S unit with `source`, `blank`, or `generator` entries and optional per-segment `video`/`audio` processing.
4. **output**: Specifies the muxed file, container hints, and batch merge settings for large timelines.
5. **compiled** (advanced): Optional compiled playlists/stack for export/debugging.

Notes:
- `timeline.segments` is required for all v2 authoring.
- Top-level `playlists` and `stack` are compiled-only details and must not appear in v2 YAML.

## Current v2 Support Notes
- `source`, `blank`, and `generator` segments are supported (including `still`).
- Frame override suffixes (`@frame`) are defined in the v2 spec but not yet implemented.
- Overlays are supported in the authoring surface for native rendering.
- MLT export currently ignores overlay tracks.
- Transitions and advanced stream mapping are defined in the v2 spec but not yet implemented.
- MKV chapters are emitted from segment `title` fields (unless `chapter: false`).

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

Playback style example (shared speed presets):

```yaml
assets:
  playback_styles:
    normal: {speed: 1.1}
    fast: {speed: 40, overlay_text_style: fast_forward_style}
timeline:
  segments:
    - source: {asset: lecture, in: "00:00.0", out: "00:10.0", style: normal}
    - source: {asset: lecture, in: "00:10.0", out: "00:12.0", style: fast}
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

Example (still image generator):

```yaml
assets:
  image:
    watermark: {file: "watermark.png"}
timeline:
  segments:
    - generator:
        kind: still
        asset: watermark
        duration: "00:02.0"
        fill_missing: {audio: silence}
```

## Overlays
`timeline.overlays` is a list of overlay tracks. Each overlay track has its own
`segments` list (video-only) and optional geometry/opacity settings. Overlays
compile into a compositing stack over the base timeline.

Fields:
- `id`: optional overlay id (used to name the overlay playlist).
- `geometry`: `[x, y, w, h]` normalized values between 0 and 1.
- `opacity`: `0.0` to `1.0`.
- `segments`: list of `source`, `blank`, or `generator` entries (video-only).
- `template`: overlay entry template (currently generator-only) used with `apply`.
- `apply`: selection rule for `template` overlays (`kind: speed` or `playback_style`).

Blank segments on overlay tracks default to `fill: transparent`.
Transparent card backgrounds are intended for overlays.
Template overlays expand across timeline segments, inserting the template when
`apply` matches and transparent blanks elsewhere. `{speed}` in template titles
or text is replaced with the matched speed.
Use either `segments` or `template`/`apply`, not both.
Overlay text templates use `kind: overlay_text` with `text` (or `title`) and an
optional `style` from `assets.overlay_text_styles`.
When `apply.kind: playback_style` is used, the matched playback style may supply
`overlay_text_style` to fill in a missing template style.

Example (fast forward overlay template):

```yaml
assets:
  playback_styles:
    fast: {speed: 40}
  overlay_text_styles:
    fast_forward_style:
      kind: overlay_text_style
      font_size: 96
      text_color: "#ffffff"
      background: {kind: transparent}
timeline:
  segments:
    - source: {asset: lecture, in: "00:00.0", out: "00:10.0"}
    - source: {asset: lecture, in: "00:10.0", out: "00:15.0", style: fast}
  overlays:
    - id: fast_forward
      geometry: [0.1, 0.4, 0.8, 0.2]
      opacity: 0.9
      apply:
        kind: playback_style
        style: fast
      template:
        generator:
          kind: overlay_text
          text: "Fast Forward {speed}X >>>"
          style: fast_forward_style
```

## Timecodes
- Accept `HH:MM:SS.sss`, `MM:SS.sss`, or frame counts with `@frame` suffix.
- All times must include leading zeros to avoid ambiguity (`00:03.0`).

## Validation Rules
- Assets must be referenced by at least one segment or `emwy` warns.
- Missing required streams in a segment are errors unless `fill_missing` is set.
- `video.speed` and `audio.speed` are kept in sync; mismatches raise an error.
- Output file extension determines the container unless overridden.

For migration tips from v1, see [COOKBOOK.md](COOKBOOK.md). When in doubt, export MLT XML to verify structure before running a full render.
