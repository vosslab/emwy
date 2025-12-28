# EMWY YAML v2 Specification

Status: Draft, intended for emwy v2
This document defines a hand-editable YAML format for building one finished movie file from one or more inputs. The design intentionally follows MLT concepts closely so readers can use existing MLT documentation and so emwy can export and import MLT XML.

## Design goals

- Simple lecture editing stays simple: cut, speed up, normalize, add cards, export YouTube chapters.
- Multiple sources are first-class: switch between sources, and optionally composite sources (picture-in-picture).
- One YAML file produces one output file.
- The canonical compiled form is MLT XML plus an emwy metadata block.

## Core mental model

A project is one **timeline** with an ordered list of **segments**.

- Each segment is an A/V/S unit: video, audio, and subtitles (if present and not dropped).
- Segments occupy time and can be source excerpts, generated cards, or blanks.
- The authoring surface is the segment list. Playlists and track stacks are compiled details.

This matches how people think about edits and still compiles deterministically to MLT
(playlist, multitrack, tractor, transitions, filters, consumer) for export.

### Segment stream expectations

By default, a segment expects the referenced asset to include audio and video.

- If the asset is missing a required stream, emwy must fail unless the segment explicitly
  opts into fill behavior (see `fill_missing`).
- Subtitles are kept by default when present, with per-segment opt-out.

Assets in `assets.video` are assumed to be A/V by default (common camera recordings).
You should not duplicate them under `assets.audio`.

## Glossary and MLT crosswalk

Author-facing term to MLT term mapping:

- **asset**: producer definition (MLT producer)
- **segment**: a compiled A/V/S unit (maps to one or more MLT playlist entries)
- **timeline**: ordered segment list (compiles to MLT playlists and a multitrack)
- **playlist**: compiled track playlist (MLT playlist)
- **stack**: compiled multitrack inside the root timeline object (MLT multitrack inside a tractor)
- **overlay**: compositing transition between tracks (MLT transition on the tractor)
- **output**: render target (MLT consumer, commonly avformat)

In YAML, the author-facing names are primary. MLT names are referenced to guide implementation and interoperability.

## Top-level structure

Required keys:

- `emwy`: must be `2`
- `profile`: output profile (fps, resolution, audio rate)
- `assets`: named media and generated templates
- `timeline`: ordered segment list (authoring surface)
- `output`: output file and delivery encoding settings

Optional keys:

- `defaults`: default processing intent (speed, loudness, fades)
- `filters`: global filters applied after compositing
- `transitions`: explicit transitions (advanced)
- `exports`: sidecar outputs (YouTube chapters, OTIO, MLT XML)
- `compiled`: advanced/diagnostic compiled model (playlists, stack)

Notes:

- `timeline.segments` is required for all v2 authoring.
- Top-level `playlists` and `stack` are compiled-only details and must not appear
  in v2 YAML.

## Profile

`profile` defines final delivery timing and geometry. `profile.fps` must support fractional rates.

```yaml
profile:
  fps: "30000/1001"          # also allowed: 24, "24000/1001", 60, "60000/1001"
  resolution: [1920, 1080]
  pixel_format: yuv420p
  audio:
    sample_rate: 48000
    channels: stereo         # mono | stereo | 5.1 | 7.1
```

### Canonical time and frames

MLT is frame-based. YAML v2 keeps human-friendly time strings but defines a deterministic compile step to integer frames at `profile.fps`.

Rules:

- Parse time strings as exact decimal seconds, not floats.
- Convert seconds to frames at `profile.fps` using the mandatory rounding rule.
- Mandatory v2 rounding rule is `nearest_frame`.
- `in_frame` and `out_frame` may be supported as an advanced override for zero-rounding authoring.

Definition: `nearest_frame`

Let `f` be the exact rational frame index for a time `t` at the project rate (so `f = t * fps`).

- If `f` is not halfway between two integers, round to the nearest integer frame.
- If `f` is exactly halfway (fractional part is exactly 1/2), round **up** to the next frame (half-up tie-break).

This tie-break rule is mandatory to keep compilation deterministic across machines and languages.

All compiled MLT XML must use integer frame positions.

## Defaults

`defaults` sets project-wide processing intent. It must not include delivery codec choices.

```yaml
defaults:
  video:
    speed: 1.1
  audio:
    normalize:
      level_db: -2
```

## Assets

Assets are named inputs and named generators. Assets compile to MLT producers.

Optional style registries may also appear under `assets`:

- `assets.playback_styles`: speed presets applied to `source` entries.
- `assets.cards`: appearance presets for `chapter_card`/`title_card`.
- `assets.overlay_text_styles`: appearance presets for `overlay_text`.

Per-entry producer instances

Assets define reusable producer definitions. During compilation, emwy may create distinct per-entry producer instances (producer chains) as needed to apply entry-scoped filters, speed changes, stream remaps, or other per-entry properties without mutating the base asset.

Author-facing impact:

- Assets stay reusable and stable.
- Entry-scoped processing stays local to the segment.

```yaml
assets:
  video:
    lecture: {file: "lecture_camera.mkv"}
    screen:  {file: "screen_capture.mkv"}
  audio:
    music:   {file: "Graze.mp3"}
  image:
    watermark: {file: "vosslab.jpg"}
    chapter_bg: {file: "chapter_bg.png"}
  cards:
    chapter_style:
      kind: chapter_card_style
      font_size: 96
      resolution: [1920, 1080]
      background: {kind: image, asset: chapter_bg}
```

## Timeline and segments

`timeline` is the authoring surface. It is an ordered list of segments that always
represent audio, video, and subtitles (when present and not dropped).

```yaml
timeline:
  segments:
    - source: {asset: lecture, in: "00:30.0", out: "06:10.0", title: "Intro"}
```

### Segment entry types

A segment entry is a mapping with exactly one of these keys:

- `source`: excerpt from an asset
- `blank`: time advances with no media (black video + silence audio)
- `generator`: generated media (chapter cards, title cards, overlay text, black, silence, still)
- `nested`: a nested timeline treated as one entry (advanced)

#### Source entry

```yaml
- source:
    id: intro
    enabled: true
    title: "Intro"
    note: "Opening section"
    asset: lecture
    in:  "00:30.0"
    out: "06:10.0"
    video: {speed: 1.1}
    audio: {normalize: {level_db: -2}}
    subtitles: keep
    fill_missing: {video: black, audio: silence}
    markers:
      - {title: "Goals", level: 2, offset: "00:10.0"}
```

Fields:

- `id`: optional unique id for anchoring markers and transitions
- `enabled`: optional boolean, default `true`. If `false`, the entry is ignored for rendering and does not affect output timing.
- `title`: optional string. If present and the entry is enabled, it becomes an MKV chapter title at the start of the entry in output time (see Chapters).
- `chapter`: optional boolean, default `true` when `title` is present. Set to `false` to prevent chapter creation from a title.
- `note`: optional string. Internal annotation for humans and tooling. Notes never create chapters and are not exported unless a future debug/export feature is added.
- `asset`: required asset id
- `in`, `out`: required time strings
- `style`: optional playback style id from `assets.playback_styles`
- `video`, `audio`: optional processing intent. If speeds are provided, they must match.
- `subtitles`: optional selector, `keep` (default) or `drop`
- `fill_missing`: optional fill behavior for missing streams. If `true`, it implies
  `{video: black, audio: silence}`. If a mapping, allowed keys are `video` and
  `audio` with values `black` or `silence` respectively.
- `streams`: optional stream mapping (see Streams)
- `filters`: optional per-entry filters
- `markers`: optional marker list relative to the start of this entry

Missing streams on a source asset are errors unless `fill_missing` is provided.
Speed sync: if `video.speed` or `audio.speed` is set, emwy applies the same
value to both streams. If both are set and differ, it is an error.
Playback styles (`assets.playback_styles`) provide a shared speed preset. When
`style` is set on a source entry, its `speed` is applied to both streams unless
overridden with matching per-entry speeds.
Playback styles may also include `overlay_text_style`. When an overlay template
uses `apply.kind: playback_style` and the template omits `style`, emwy uses the
matched playback style's `overlay_text_style`.

Examples:

Single A/V asset (no duplicate audio asset):

```yaml
assets:
  video:
    lecture: {file: "lecture_camera.mkv"}

timeline:
  segments:
    - source: {asset: lecture, in: "00:00.0", out: "00:30.0"}
```

Audio-only asset with explicit video fill:

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

Video-only asset with explicit audio fill:

```yaml
assets:
  video:
    broll: {file: "broll_no_audio.mp4"}

timeline:
  segments:
    - source:
        asset: broll
        in: "00:00.0"
        out: "00:08.0"
        fill_missing: {audio: silence}
```

#### Blank entry

Blank segments advance time with no media.

```yaml
- blank: {duration: "00:02.0"}                 # black video + silence audio
- blank: {duration: "00:02.0", fill: black}    # explicit black fill
- blank: {duration: "00:02.0", fill: transparent}  # for advanced overlays
```

#### Generator entry

A generator entry inserts media that emwy creates.

Common generator kinds:

- `chapter_card`
- `title_card`
- `overlay_text` (overlay tracks only)
- `black`
- `silence`
- `still`

Notes:

- Generator entries may also include `note` for internal annotation.
- `still` requires `asset` referencing `assets.image`.

```yaml
- generator:
    id: card_p1
    enabled: true
    kind: chapter_card
    title: "Problem 1"
    note: "Start of the first worked problem"
    duration: "00:02.0"
    style: chapter_style
    markers:
      - {title: "Problem 1", level: 1, offset: "00:00.0"}
```

Still image generator example:

```yaml
- generator:
    kind: still
    asset: watermark
    duration: "00:03.0"
```

Generator kinds produce their natural streams (video for cards/black/still, audio
for silence). Use `fill_missing` to explicitly fill the missing stream when needed.

Card styles (`assets.cards`) can define default appearance for `chapter_card` and
`title_card` generators. Supported fields:

- `font_size`: integer font size
- `font_file`: path to a TTF/OTF font file
- `text_color`: color string like `#ffffff` or `rgb(255,255,255)`
- `background`: mapping that selects a background kind

Supported `background` mappings:

- `kind: image` with `asset` id under `assets.image`
- `kind: color` with `color` (default `#000000`)
- `kind: gradient` with `from`, `to`, and `direction` (`vertical` or `horizontal`)
- `kind: transparent` for overlay text

Note: `transparent` backgrounds are intended for overlay tracks.

Overlay text styles (`assets.overlay_text_styles`) define the default appearance
for `overlay_text` generators. They accept the same fields as card styles, but
default to a transparent background when none is provided.

`overlay_text` generators require `text` (or `title`) and may include `style`
referencing `assets.overlay_text_styles`.

Planned extensions for `background.kind` include `video` and `source_blur` (not yet implemented).

Notes:

- For consistent typography across machines, set `font_file`. If omitted, emwy
  falls back to a bundled system font when available and otherwise uses Pillow's
  default bitmap font (which renders small).

### Overlay tracks (authoring surface)

`timeline.overlays` is a list of overlay tracks. Each overlay track is video-only
and compiles into the stack as a role `overlay` track plus an overlay transition.

Overlay track fields:

- `id`: optional id used to name the overlay playlist.
- `geometry`: `[x, y, w, h]` normalized values between 0 and 1.
- `opacity`: `0.0` to `1.0`.
- `segments`: list of `source`, `blank`, or `generator` entries (video-only).
- `template`: generator entry used when `apply` matches (omit duration).
- `apply`: overlay template selector (currently `kind: speed` with `stream`,
  `min_speed`, and optional `max_speed`, or `kind: playback_style` with `style`).
Use either `segments` or `template`/`apply`, not both.

Example:

```yaml
assets:
  playback_styles:
    fast: {speed: 40, overlay_text_style: fast_forward_style}
  overlay_text_styles:
    fast_forward_style:
      kind: overlay_text_style
      font_size: 96
      text_color: "#ffffff"
      background: {kind: transparent}
timeline:
  segments:
    - source: {asset: lecture, in: "00:00.0", out: "00:20.0"}
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

Template overlays expand across the base timeline, inserting the template for
matching segments and transparent blanks elsewhere. `{speed}` is replaced with
the matched speed for each segment.

## Compiled model (advanced)

`playlists` and `stack` are internal compiled details that emwy may emit for export
targets like MLT. They are not part of the authoring surface for v2.

```yaml
compiled:
  playlists:
    video_base:
      kind: video
      playlist:
        - source: {asset: lecture, in: "00:30.0", out: "06:10.0"}
  stack:
    tracks:
      - {playlist: video_base, role: base}
      - {playlist: audio_main, role: main}
```

Common roles:

- video: `base`, `overlay`
- audio: `main`, `commentary`, `music`

## Streams and subtitles

Default behavior is to preserve all streams from a source asset when possible,
including multiple audio tracks and subtitles. Subtitles are kept by default; a
segment may opt out with `subtitles: drop` or `streams: {subtitles: drop}`.

When switching source assets within the same timeline, stream compatibility must
be defined.

Compatibility requirements (default):

- same number of selected audio streams
- compatible channel layouts per selected stream, or explicit remap
- subtitle handling consistent with the output container

Explicit mapping is provided via `streams` on a source entry.

```yaml
- source:
    asset: lecture
    in: "10:00.0"
    out: "10:20.0"
    streams:
      audio:
        - {src_index: 0, name: "main"}
        - {src_index: 1, name: "commentary"}
      subtitles: keep
```

If compatibility fails and no mapping is provided, emwy must fail with a clear error.

## Transitions

Transitions fall into two families.

### Adjacent transitions inside a playlist

These are transitions between neighboring playlist entries on the same playlist, such as cross-dissolve or dip-to-black.

Authoring form (recommended): attach a transition to the outgoing edge of an entry.

```yaml
- source:
    id: a
    asset: lecture
    in: "00:30.0"
    out: "01:00.0"
    transition_to_next:
      kind: dissolve
      duration: "00:00.5"
```

Semantics (mandatory for v2):

- The transition duration is expressed in frames after compilation.
- A transition does **not** extend the overall timeline duration.
- The transition is centered on the cut: it steals frames from the tail of A and the head of B.

Let the compiled transition duration be `d` frames.

- `tailA = floor(d/2)`
- `headB = d - tailA` (the incoming clip B receives the extra frame when `d` is odd)

During the overlap window, A and B are blended according to the transition kind (dissolve, wipe, etc).

Validation:

- A must have at least `tailA` frames available at its end.
- B must have at least `headB` frames available at its start.
- If not, compilation must fail with a clear error unless a future version introduces an explicit policy.

Implementation:

- Compile to an MLT-style overlap and playlist-level transition using compiled frame counts.

### Stack compositing transitions between tracks (advanced)

These are transitions that define how an overlay track is composited onto a base track,
including picture-in-picture. They are layered on top of the primary segment list and
live in the compiled model.

```yaml
compiled:
  stack:
    tracks:
      - {playlist: video_base, role: base}
      - {playlist: video_slides, role: overlay}
    overlays:
      - a: video_base
        b: video_slides
        kind: over
        in:  "00:30.0"
        out: "19:20.0"
        geometry: [0.64, 0.06, 0.34, 0.34]   # normalized x, y, w, h
        opacity: 1.0
```

Validation:

- overlays must reference playlists that are present in `compiled.stack.tracks`.

Implementation:

- Compile overlays to MLT transitions attached to the root timeline object, with track indices and keyframe-capable properties.
- Wipes should compile to an MLT luma-style transition where available, with a luma resource.

Overlay timing semantics (mandatory for v2):

- Overlay `in` and `out` are interpreted in **stack time** (the time that results after playlist entries and blanks advance time).
- An overlay transition only has an effect where both referenced video playlists produce frames.

Clipping rule:

- The effective overlay active range is the intersection of:
  - the overlay's declared `[in, out)` range, and
  - the time span where the overlay playlist produces non-transparent video.

By default, overlay playlists should use `blank.fill: transparent` for gaps so that gaps in the overlay do not cover the base.

If an overlay playlist uses `fill: black`, that black is treated as real pixels and will cover the base inside the overlay region.

## Filters

### v1 parity notes

v1 included several audio processing steps and conveniences (normalize, highpass/lowpass,
avsync-style delay, optional noise reduction). In v2 these should be expressed as named
filters at segment, timeline, or compiled stack scope.

Filters may be attached at:

- segment scope: filters on a segment apply only to that segment
- timeline scope: filters on the timeline apply to every segment
- compiled stack scope: filters applied after compositing

Filter schema:

```yaml
filters:
  - name: "denoise"
    params: {amount: 0.4}
```

Keyframes:

Any numeric parameter may accept keyframes. Keyframe time `t` is relative to the start
of the segment unless otherwise specified.

```yaml
params:
  amount:
    - {t: "00:00.0", v: 0.0}
    - {t: "00:05.0", v: 0.6}
```

## Markers, chapters, and educational outlines

### MKV chapters from titles

Segment `title` values are treated as chapters by default.

Rules:

- If a segment has `title` and `enabled: true`, emwy creates a chapter at the start of that entry in output timeline time.
- If `enabled: false`, the entry is ignored for rendering and does not create a chapter.
- Chapters are emitted into MKV output when the output container supports it. If the muxing tool requires it, emwy may generate an intermediate chapters file, but authors do not need to configure an export section for this behavior.
- To label an entry without creating a chapter, set `chapter: false` on that entry.

Example:

```yaml
- source:
    asset: lecture
    in:  "00:30.0"
    out: "06:10.0"
    title: "Intro"
```

```yaml
- source:
    enabled: false
    title: "Optional segment to revisit later"
    note: "Internal label only, flip enabled to include later"
    asset: lecture
    in:  "06:10.0"
    out: "07:20.0"
```


Markers are metadata. They should be anchored to structure, not to output absolute time.

Preferred authoring:

- Attach `markers` to playlist entries, using `offset` relative to entry start.
- Use a heading path for educational outlines.

Recommended marker levels:

- level 1: chapter
- level 2: subchapter
- level 3: subsubchapter

Example:

```yaml
- generator:
    kind: chapter_card
    title: "Problem 2"
    duration: "00:02.0"
    style: chapter_style
    markers:
      - {title: "Problem 2", level: 1, offset: "00:00.0"}
```

### YouTube chapters export

YouTube chapters are flat. Export rules:

- emit level 1 markers only
- format lines as `MM:SS Title`
- ensure the first is `00:00` and marker times are increasing

## Output

`output` contains delivery choices, separate from editorial and processing intent.

```yaml
output:
  file: "Lecture_ProblemSet1.mkv"
  container: mkv
  video_codec: libx264
  audio_codec: aac
  crf: 18
  merge_batch_threshold: 24
  merge_batch_size: 8
```

Optional batching controls:

- `merge_batch_threshold`: if segment or overlay track entries exceed this count,
  emwy merges in batches to avoid huge mkvmerge commands. Default `24`.
- `merge_batch_size`: number of files to merge per batch when batching is active.
  Default `8`.

## Canonical compiled form

For v2, the canonical compiled form is:

- MLT XML that melt can render directly, plus
- an emwy metadata block stored as properties on the root timeline object

The metadata block preserves information MLT does not represent natively, such as structured marker paths. Exporters may also emit sidecar files (for example YouTube chapters).

## Interoperability

### MLT XML export and import

Export mapping:

- assets compile to producers
- playlists compile to MLT playlists
- stack compiles to multitrack inside a tractor
- overlays compile to transitions
- output compiles to a consumer

Import should be best-effort and must warn about unsupported features.

### Shotcut MLT export

Shotcut uses MLT XML plus additional annotations and a couple of structural conventions so it can map the project into its Timeline, track UI, and bin.

When exporting in Shotcut mode, the emitted MLT XML must additionally include:

- `<property name="shotcut">1</property>` on the main timeline tractor
- a playlist with id `main bin` before the last tractor
- a playlist with id `background` containing a black color producer, and make it the first child track of the last tractor
- for `mlt_service=avformat` sources, use `chain` where applicable and apply the same Shotcut properties to it

Nice-to-have annotations:

- `shotcut:name` on playlists (track labels)
- `shotcut:audio` and `shotcut:video` flags
- `shotcut:filter` and `shotcut:transition` to bind Shotcut UI panels
- `shotcut:markers` if chapters should appear as Shotcut markers

Suggested YAML switch:

```yaml
exports:
  mlt_xml: {file: "edit.mlt"}
  shotcut_mlt: {file: "edit_shotcut.mlt"}
```


### OTIO export and import

OTIO is a useful interchange target for editorial tooling.

Suggested subset export:

- playlists and stack export to OTIO tracks and stacks
- playlist entries export to OTIO clips and gaps
- markers export to OTIO markers

Suggested subset import:

- OTIO clips and gaps import as playlist entries
- OTIO markers import as segment markers

## Validation

An emwy v2 validator should check:

- required keys exist and `emwy: 2`
- every source entry has `in < out` after frame compilation
- referenced assets exist
- overlay transitions reference valid playlists and have valid time ranges
- stream mappings are compatible across asset switches when preserving streams
- marker offsets do not exceed entry duration

## Conformance tests

A recommended conformance test is to render the same project two ways:

1. Render with emwy native rendering.
2. Export MLT XML, render with melt, and compare outputs.

Comparison should include:

- frame count equality (ffprobe)
- duration equality
- checksum or perceptual comparison on decoded frames (sample every N frames or all frames)
- audio duration and sample count equality (or a tolerant audio hash)

This test should use fractional fps such as 30000/1001 and include transitions and overlays.

## Complete example: lecture with chapters, speed, and cards

```yaml
emwy: 2

profile:
  fps: "60000/1001"
  resolution: [1920, 1080]
  audio: {sample_rate: 48000, channels: stereo}

defaults:
  video: {speed: 1.1}
  audio: {normalize: {level_db: -2}}

assets:
  video:
    lecture: {file: "lecture_camera.mkv"}
  cards:
    chapter_style:
      kind: chapter_card_style
      font_size: 96
      resolution: [1920, 1080]

timeline:
  segments:
    - source: {asset: lecture, in: "00:30.0", out: "06:10.0", title: "Intro"}
    - generator:
        kind: chapter_card
        title: "Problem 1"
        duration: "00:02.0"
        style: chapter_style
        fill_missing: {audio: silence}
        markers:
          - {title: "Problem 1", level: 1, offset: "00:00.0"}
    - source:
        asset: lecture
        in:  "06:10.0"
        out: "18:40.0"
        video: {speed: 1.15}
    - source:
        asset: lecture
        in:  "18:40.0"
        out: "19:20.0"
        video: {speed: 40}

output:
  file: "Lecture_ProblemSet1.mkv"
  container: mkv
```
