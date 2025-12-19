# EMWY YAML v2 Specification

Status: Draft, intended for implementation in emwy v2  
Filename suggestion: `EMWY_YAML_v2_SPEC.md`

This document defines a human-readable YAML format for producing a single, finished video from one or more raw sources using the command line. The format is designed to stay pleasant to author by hand while keeping the door open for interoperability with MLT XML.

## Goals

- Make the simple case simple: cut a lecture, speed up boring parts, normalize audio, export chapters.
- Support multiple source videos and switching between them inside one timeline.
- Support visual inserts (title cards, chapter cards) and metadata inserts (chapter markers).
- Support multiple input video tracks for compositing (picture-in-picture, slides overlay), while producing a single output video stream.
- Preserve all source streams by default (multiple audio tracks, subtitles) when cutting, unless the user remaps streams.
- Provide a structure that can be translated to and from a useful subset of MLT XML.

## Non-goals

- Full fidelity round-trip with every MLT XML feature.
- Replacing a full GUI NLE for complex motion graphics or deep color workflows.
- Multi-output builds inside one YAML file. One YAML file describes one output render.

## Format overview

EMWY YAML v2 is a single YAML document with a top-level mapping.

Top-level keys:

- `emwy`: required integer version. Must be `2`.
- `project`: optional metadata (title, author, notes).
- `profile`: required output specs (fps, resolution, audio sample rate, channel layout).
- `defaults`: optional defaults for actions, audio, video, filters.
- `assets`: optional named inputs and generated assets (video files, audio files, images, card templates).
- `tracks`: required timeline tracks (at minimum, one base video track).
- `mix`: optional compositing rules for overlay tracks.
- `output`: required output filename and encoding container defaults.
- `exports`: optional extra outputs (YouTube chapters text, MLT XML export, show notes).

## Data types

### Time values

Time values in YAML v2 are strings in one of these forms:

- `HH:MM:SS.sss`
- `MM:SS.sss`
- `SS.sss`
- Integer seconds are allowed but discouraged.

Parsing rules:

- `out` is exclusive. A segment is `[in, out)`.
- All times are interpreted as real time seconds. Internally, emwy may convert to frame counts based on `profile.fps`.

### Duration values

Duration values are seconds as a number, for example `2.0`.

### IDs

Asset IDs and track IDs are strings matching `[A-Za-z][A-Za-z0-9_]*`.

## Project metadata

`project` is optional and has no effect on rendering.

```yaml
project:
  title: "Protein Problem Set 1"
  author: "Neil Voss"
  notes: "Cut pauses, add chapter cards, export YouTube chapters."
```

## Output profile

`profile` is required. It defines the final technical specs for the rendered output.

```yaml
profile:
  fps: 60
  resolution: [1920, 1080]
  pixel_format: yuv420p
  audio:
    sample_rate: 48000
    channels: stereo        # mono | stereo | 5.1 | 7.1
```

Guidance:

- If sources differ from `profile`, emwy should resample and scale as needed.
- If `profile` is missing, emwy should fail with a clear error.

## Defaults

`defaults` sets project-wide defaults. Any event may override.

```yaml
defaults:
  action: keep
  video:
    speed: 1.1
  audio:
    normalize:
      level_db: -2
    format: mp3
    channels: stereo
```

Notes:

- `defaults.action` is commonly `keep`.
- If `defaults.action` is `keep`, the timeline normally lists only the parts to remove or modify.

## Assets

`assets` defines named reusable inputs and generated templates.

### Source assets

```yaml
assets:
  video:
    camA: {file: "lecture_cam.mkv"}
    camB: {file: "screen_capture.mkv"}
  audio:
    music: {file: "Graze.mp3"}
  image:
    watermark: {file: "vosslab.jpg"}
```

### Card templates

Cards are generated assets. Templates let you reuse styling.

```yaml
assets:
  cards:
    chapter_style:
      kind: chapter_card_style
      font_size: 96
      resolution: [1920, 1080]
      background: black
      text_color: white
      audio:
        file: "Graze.mp3"
        normalize:
          level_db: -15
```

## Tracks

A project must have at least one base video track. The final output has a single video stream after compositing.

```yaml
tracks:
  video_base:
    kind: video
    timeline: [ ... ]
```

Optional additional tracks:

- `video_overlay_*`: overlay video tracks composited onto `video_base`
- `audio_*`: additional audio tracks or derived mixes

### Track kind

Supported `kind` values:

- `video`
- `audio`

## Timeline events

A timeline is an ordered list of events. Events are processed in list order.

There are three event families:

- `range`: take a time range from a source asset and do something with it.
- `insert`: insert generated content or external content into the output timeline.
- `marker`: metadata-only marker such as a chapter marker (no frames inserted).

### Range events

Range event schema:

- `src`: required asset ID (typically from `assets.video.*`)
- `in`: required time
- `out`: required time
- `action`: optional, default from `defaults.action`
- `video`: optional video modifiers
- `audio`: optional audio modifiers
- `streams`: optional stream selection and mapping
- `filters`: optional list of filters
- `chapter`, `subchapter`, `subsubchapter`: optional headings that become markers
- `note`: optional free text

Example:

```yaml
- range:
    src: camA
    in:  "00:25.5"
    out: "00:27.7"
    action: keep
    video: {speed: 1.15}
    chapter: "Problem 1"
    subchapter: "Setup"
```

### Insert events

Insert event schema:

- `insert`: required object describing what to insert
- `chapter`, `subchapter`, `subsubchapter`: optional headings for a marker at the start of the insert
- `note`: optional free text

Supported insert types:

- `title_card`: a visual card with text and optional audio
- `chapter_card`: a visual divider card intended to be a chapter boundary
- `clip`: insert an external media asset (video or audio)
- `silence`: insert silence for a duration
- `black`: insert black frames for a duration

Example chapter card:

```yaml
- insert:
    chapter_card:
      title: "Problem 2"
      duration: 2.0
      style: chapter_style
```

### Marker events

Marker events add metadata only. They insert no frames.

Marker schema:

- `marker`: required
- `title`: required
- `level`: optional integer, default `1`
- `at`: required time in output timeline time

Example:

```yaml
- marker:
    title: "Office hours"
    level: 1
    at: "00:00.0"
```

Guidance:

- Prefer headings on `range` and `insert` events over explicit `marker` events.
- Use `marker` when you need a marker inside a long kept range.

## Actions for a range

`action` controls the basic fate of the source range. Effects are modifiers.

Supported actions:

- `keep`: include the range in the output.
- `skip`: exclude the range from the output.
- `replace`: replace the range with something else.
- `stop`: terminate processing at this point.

Optional advanced actions:

- `audio_only`: include only audio from the range, with black video inserted for the same duration.
- `video_only`: include only video from the range, with silence for the same duration.

### Replace action

`replace` requires a `replacement` block:

```yaml
- range:
    src: camA
    in: "10:05.0"
    out: "10:07.0"
    action: replace
    replacement:
      kind: beep            # beep | silence | blur | card | clip
      beep_hz: 1000
```

Notes:

- `blur` implies video replacement only, audio is handled via `audio` modifiers.
- `card` is a short title card insert that matches the replaced duration unless explicitly set.

## Video modifiers

`video` is a mapping. Supported keys are intended to be composable.

Common keys:

- `speed`: number or named preset (for example `fast_forward`)
- `crop`: `[x, y, w, h]`
- `scale`: `[w, h]`
- `pad`: `[w, h, x, y]`
- `rotate`: degrees
- `fade_in`: seconds
- `fade_out`: seconds
- `watermark`: asset ID from `assets.image.*`
- `overlay_text`: text overlay definition

Example:

```yaml
video:
  speed: 40
  watermark: watermark
  fade_in: 0.2
```

### Speed and audio coupling

Speed changes affect both video and audio duration unless audio is explicitly replaced or muted. A speed of `2.0` means double speed, half duration.

## Audio modifiers

`audio` is a mapping. Supported keys are intended to be composable.

Common keys:

- `normalize`: `{level_db: -2}` or `{lufs: -16, true_peak_db: -1.5}`
- `gain_db`: number
- `mute`: boolean
- `replace_with`: asset ID from `assets.audio.*`
- `duck`: ducking config for background tracks
- `highpass_hz`: number
- `lowpass_hz`: number
- `fade_in`: seconds
- `fade_out`: seconds
- `denoise`: `{profile: "room_tone", amount: 0.5}`

Example fast-forward with muted lecture audio and replacement music:

```yaml
- range:
    src: camA
    in: "04:38.7"
    out: "06:00.1"
    action: keep
    video: {speed: 40}
    audio:
      mute: true
      replace_with: music
      normalize: {level_db: -15}
```

## Filters

`filters` is a list of named filters with parameters. Filters may be applied at:

- clip scope: `range.filters`
- track scope: `tracks.<id>.filters`
- global scope: `defaults.filters` or `output.filters`

Filter schema:

```yaml
filters:
  - name: "denoise"
    params: {amount: 0.4}
```

### Keyframes

Any numeric parameter may accept keyframes:

```yaml
params:
  amount:
    - {t: "00:00.0", v: 0.0}
    - {t: "00:05.0", v: 0.6}
```

`t` in keyframes is relative to the start of the event.

## Streams and subtitles

By default, emwy should keep all streams present in the selected source asset, including:

- primary audio
- commentary audio tracks
- subtitle tracks

This makes classroom edits of movies sane.

Stream selection is controlled via `streams`:

```yaml
streams:
  keep_all: true
  audio:
    - {src_index: 0, name: "main"}
    - {src_index: 1, name: "commentary"}
  subtitles: keep
```

If the user switches sources mid-timeline, stream selection should be validated for compatibility. If incompatible, emwy should fail unless explicit remapping is provided.

## Multiple sources and interlacing

Switching between sources is done by changing `src` per `range` event on the base video track.

```yaml
tracks:
  video_base:
    kind: video
    timeline:
      - range: {src: camA, in: "00:00.0", out: "02:00.0", action: keep}
      - range: {src: camB, in: "00:00.0", out: "02:00.0", action: keep}
```

This produces a single output timeline that alternates between sources.

## Overlays and picture-in-picture

Overlay tracks are separate video tracks. They are composited onto the base track in `mix`.

```yaml
tracks:
  video_base:
    kind: video
    timeline: [ ... ]

  video_overlay_slides:
    kind: video
    timeline:
      - range: {src: camB, in: "00:00.0", out: "30:00.0", action: keep}

mix:
  compositor: over
  layers:
    - track: video_overlay_slides
      mode: pip
      rect: [0.65, 0.05, 0.33, 0.33]   # normalized x, y, w, h
      opacity: 1.0
```

Notes:

- `rect` is normalized to the output resolution.
- `pip` is a convenience mode for an `over` compositor with a rect.

## Chapters and educational outlines

Headings are attached to events:

- `chapter`: level 1
- `subchapter`: level 2
- `subsubchapter`: level 3

A heading on an event creates a marker at the start of that event in output timeline time.

Example:

```yaml
- insert:
    chapter_card:
      title: "Problem 2"
      duration: 2.0
      style: chapter_style
  chapter: "Problem 2"
```

### Exporting YouTube chapters

YouTube chapters are flat. Export rules:

- Use only `chapter` (level 1).
- Output format is lines like `MM:SS Title`.
- First chapter should be at `00:00`.
- Enforce YouTube constraints in exporter when possible (minimum chapter length, increasing order).

Export configuration:

```yaml
exports:
  youtube_chapters:
    file: "chapters.txt"
```

## Output

`output` defines the main render output.

```yaml
output:
  file: "Unordered_Tetrad-2021-Nov.mkv"
  container: mkv
  video_codec: libx264
  audio_codec: aac
```

Guidance:

- One YAML file should produce one output file.
- If you want multiple outputs, create multiple YAML files, optionally sharing common config via `include`.

## Include and reuse

To avoid duplication across variants, YAML v2 may support `include`.

```yaml
include:
  - "common_defaults.yml"

output:
  file: "Lecture_short.mkv"
```

Merge rules:

- Included files load first.
- The main file overrides included values.
- Lists replace by default. If you want list concatenation, define it explicitly in v2 later.

## MLT XML interoperability

MLT XML import and export is an interoperability feature, not the core representation.

### Export to MLT XML (subset)

A YAML v2 project can export to MLT XML using this mapping:

- `assets.video.*` -> MLT producers
- `tracks.*.timeline` -> MLT playlists
- `mix.layers` -> MLT multitrack compositing and transitions
- `filters` -> MLT filters where a known name mapping exists
- `profile` -> MLT profile

Limitations:

- Only supported filters and transitions will map.
- Unknown ops should either be dropped with warnings or cause export failure depending on a strictness flag.

### Import from MLT XML (subset)

MLT XML import should create:

- `profile` from the MLT profile
- `assets` from producers
- `tracks` from playlists
- `mix` from multitrack structure when present

Import should be best-effort and should record unmapped MLT features in `project.notes` or an `imports.warnings` block.

## Validation

An emwy v2 validator should check:

- Required keys exist: `emwy`, `profile`, `tracks`, `output`
- `in` and `out` exist for every `range`
- `in < out` for every `range`
- Timeline order is non-decreasing in output time construction
- Overlaps on the base track are not allowed unless explicitly supported in a future version
- Asset IDs exist and files are readable
- Stream remapping is consistent across source switches when `keep_all` is true
- Chapter exports are consistent and do not land inside skipped content

## Complete example: lecture with chapters, speed, cards, and PiP

```yaml
emwy: 2

profile:
  fps: 60
  resolution: [1920, 1080]
  audio: {sample_rate: 48000, channels: stereo}

defaults:
  action: keep
  video: {speed: 1.1}
  audio:
    normalize: {level_db: -2}

assets:
  video:
    camA: {file: "lecture_cam.mkv"}
    slides: {file: "screen_capture.mkv"}
  audio:
    music: {file: "Graze.mp3"}
  image:
    watermark: {file: "vosslab.jpg"}
  cards:
    chapter_style:
      kind: chapter_card_style
      font_size: 96
      resolution: [1920, 1080]
      audio: {file: "Graze.mp3", normalize: {level_db: -15}}

tracks:
  video_base:
    kind: video
    timeline:
      - range:
          src: camA
          in:  "00:00.0"
          out: "00:30.0"
          action: skip
          note: "Noise and settling in"

      - insert:
          chapter_card: {title: "Intro", duration: 2.0, style: chapter_style}
        chapter: "Intro"

      - range:
          src: camA
          in:  "00:30.0"
          out: "06:10.0"
          chapter: "Intro"
          subchapter: "Goals"

      - insert:
          chapter_card: {title: "Problem 1", duration: 2.0, style: chapter_style}
        chapter: "Problem 1"

      - range:
          src: camA
          in:  "06:10.0"
          out: "18:40.0"
          chapter: "Problem 1"
          subchapter: "Setup"
          video: {speed: 1.15}

      - range:
          src: camA
          in:  "18:40.0"
          out: "19:20.0"
          action: keep
          video: {speed: 40}
          audio:
            mute: true
            replace_with: music
            normalize: {level_db: -15}
          note: "Fast forward silent work"

  video_overlay_slides:
    kind: video
    timeline:
      - range: {src: slides, in: "00:30.0", out: "19:20.0", action: keep}

mix:
  compositor: over
  layers:
    - track: video_overlay_slides
      mode: pip
      rect: [0.64, 0.06, 0.34, 0.34]
      opacity: 1.0

output:
  file: "Lecture_ProblemSet1.mkv"
  container: mkv

exports:
  youtube_chapters: {file: "chapters.txt"}
```

## Versioning and forward compatibility

- A file must declare `emwy: 2`.
- Minor extensions should be additive.
- Unknown keys should cause a warning by default and may be fatal in strict mode.

