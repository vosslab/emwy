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

### Fractional-first fps and internal time

Real projects frequently use fractional frame rates such as 23.976 (24000/1001), 29.97 (30000/1001), and 59.94 (60000/1001). YAML v2 therefore allows `profile.fps` as:

- an integer, for example `60`
- a rational string, for example `"60000/1001"`

Implementation rule:

- emwy must convert `profile.fps` into a rational value (numerator, denominator) and use that consistently throughout the build.

Event times in YAML remain human-friendly strings like `HH:MM:SS.sss`. Internally, emwy should represent time as a rational duration in seconds (not a float) to avoid drift on long timelines and fractional frame rates.

Conversion rule from a time string to internal rational seconds:

- Parse the string into whole seconds plus a fractional decimal part.
- Convert the fractional decimal part into a rational fraction exactly based on the digits provided.
- Store the result as a rational number of seconds.

When emwy must convert a rational time to frames, it must define and document a rounding mode. Recommended default is `nearest_frame`, with `floor` as an optional strict mode.

```yaml
profile:
  fps: "60000/1001"         # examples: 24, "24000/1001", 30, "30000/1001", 60, "60000/1001"
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
```

Notes:

- `defaults.action` is commonly `keep`.
- If `defaults.action` is `keep`, the timeline normally lists only the parts to remove or modify.

Processing vs encoding guidance:

- `defaults` should describe editorial and signal-processing intent (speed, fades, loudness normalization).
- Container and codec choices belong under `output` (and `exports`), not under `defaults`.

## Assets

`assets` defines named reusable inputs and generated templates.

### Source assets

```yaml
assets:
  video:
    lecture: {file: "lecture_camera.mkv"}
    screen:  {file: "screen_capture.mkv"}
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

### Event ids

Any event may include an optional `id`. If present, it must be unique within the file.

Event ids exist primarily so you can attach markers relative to structure without needing to precompute final output time.

Example:

```yaml
- range:
    id: p1_setup
    src: lecture
    in:  "06:10.0"
    out: "18:40.0"
    action: keep
```

### Range events

Range event schema:

- `id`: optional unique string
- `src`: required asset ID (typically from `assets.video.*`)
- `in`: required time
- `out`: required time
- `action`: optional, default from `defaults.action`
- `video`: optional video modifiers
- `audio`: optional audio modifiers
- `streams`: optional stream selection and mapping
- `filters`: optional list of filters
- `chapter`, `subchapter`, `subsubchapter`: optional headings that become markers at the start of the event
- `markers`: optional list of markers relative to the start of the event
- `note`: optional free text

Example:

```yaml
- range:
    id: p1_setup
    src: lecture
    in:  "06:10.0"
    out: "18:40.0"
    action: keep
    video: {speed: 1.15}
    chapter: "Problem 1"
    subchapter: "Setup"
    markers:
      - {title: "Key idea", level: 2, offset: "03:10.0"}
```

### Insert events

Insert event schema:

- `id`: optional unique string
- `insert`: required object describing what to insert
- `chapter`, `subchapter`, `subsubchapter`: optional headings for a marker at the start of the insert
- `markers`: optional list of markers relative to the start of the insert (rare)
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
    id: card_p2
    chapter_card:
      title: "Problem 2"
      duration: 2.0
      style: chapter_style
  chapter: "Problem 2"
```

### Marker events

Marker events add metadata only. They insert no frames.

Two placement modes exist:

- structural placement (preferred): headings and `markers` attached to `range` or `insert` events
- absolute placement (optional): a marker at an output-time `at` position

Structural markers round-trip better and are deterministic without having to render first.

Marker schema:

- `title`: required
- `level`: optional integer, default `1`
- `offset`: time string relative to the start of the referenced event (structural mode)
- `ref`: `{event: <event_id>}` (structural mode)
- `at`: required only for absolute placement, time in output timeline time (absolute mode)

Examples:

Structural marker relative to an event:

```yaml
- marker:
    title: "Important definition"
    level: 2
    ref: {event: p1_setup}
    offset: "03:10.0"
```

Absolute marker in output time (discouraged for hand-authoring):

```yaml
- marker:
    title: "Office hours"
    level: 1
    at: "12:34.0"
```

## Actions for a range## Actions for a range

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
    src: lecture
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
    src: lecture
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
### Compatibility when switching sources

When `keep_all: true` and the timeline switches `src` between assets, emwy must decide whether streams are compatible.

Required compatibility (default):

- same number of video streams (usually 1)
- same number of audio streams selected into the output
- same number of subtitle streams if `subtitles: keep`
- audio channel layouts must match per stream, or be explicitly remapped

If compatibility fails and no explicit mapping is provided, emwy must fail with a clear error describing the mismatch.

Optional explicit mapping:

- Users may name output streams and map each source stream index into those names per asset.


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
      - range: {src: lecture, in: "00:00.0", out: "02:00.0", action: keep}
      - range: {src: screen,  in: "00:00.0", out: "02:00.0", action: keep}
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
      - range: {src: screen, in: "00:00.0", out: "30:00.0", action: keep}

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
Encoding and container decisions belong here. YAML v2 treats these as delivery choices, separate from editorial decisions and signal processing.


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
## OTIO interoperability

OpenTimelineIO (OTIO) is a modern interchange format for editorial timelines. YAML v2 is designed to map to OTIO concepts cleanly (timeline, tracks, clips, transitions, markers), even if the initial implementation supports only a subset.

Suggested subset export:

- base video track and any overlay tracks as OTIO tracks
- `range` events as OTIO clips referencing media
- `insert` cards as OTIO generator clips
- headings and structural markers as OTIO markers

Suggested subset import:

- clips and cuts into `range` events
- markers into headings or `marker` events
- ignore or warn on unsupported OTIO effects and transitions

Configuration:

```yaml
exports:
  otio:
    file: "edit.otio"
```


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
    lecture: {file: "lecture_camera.mkv"}
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
          src: lecture
          in:  "00:00.0"
          out: "00:30.0"
          action: skip
          note: "Noise and settling in"

      - insert:
          chapter_card: {title: "Intro", duration: 2.0, style: chapter_style}
        chapter: "Intro"

      - range:
          src: lecture
          in:  "00:30.0"
          out: "06:10.0"
          chapter: "Intro"
          subchapter: "Goals"

      - insert:
          chapter_card: {title: "Problem 1", duration: 2.0, style: chapter_style}
        chapter: "Problem 1"

      - range:
          src: lecture
          in:  "06:10.0"
          out: "18:40.0"
          chapter: "Problem 1"
          subchapter: "Setup"
          video: {speed: 1.15}

      - range:
          src: lecture
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

