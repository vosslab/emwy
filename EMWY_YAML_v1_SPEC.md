# EMWY YAML v1 Specification

Status: Legacy, for emwy v1.x  
Purpose: Document the original YAML format used by emwy so the v2 implementation can be understood against the older semantics.

This spec describes the format implemented by `emwy_cli.py` in this repository (not an idealized format). v1 is intentionally simple and has several sharp edges.

## High-level model

- A v1 project is a YAML **list** of dictionaries.
- Each dictionary has a required `type` key.
- Supported top-level `type` values are:
  - `global`
  - `movie`
  - `titlecard` (parsed but not used by the current v1 processing pipeline)

emwy processes each `movie` entry independently into a temporary output file, then concatenates those temporary outputs into one final output file.

## Top-level: `type: global`

The global block defines defaults for the entire run.

Common fields:

```yaml
- type: global
  quality: fast           # fast | high
  speed:
    normal: 1.1
    fast_forward: 40
  audio:
    norm_level: -2
    audio_format: MP3     # WAV | MP3 (case-insensitive)
    audio_mode: stereo    # mono | stereo
  output_file: output.mkv
```

### `quality`

`quality` selects a preset that controls default sample rate, bitrate depth, video CRF, output frame rate, and whether extra audio processing is enabled.

Observed preset behavior in v1:

- `fast` sets lower fidelity defaults and faster processing.
- `high` sets higher fidelity defaults and enables extra audio processing.

You can override specific parameters under `audio:` and `video:` (see below).

### `speed`

`speed.normal` is the default playback speed applied to segments with `type: normal`.  
`speed.fast_forward` is the speed applied to segments with `type: fastforward`.

If `speed` is omitted, emwy uses internal defaults (typically normal ~1.1 and fast_forward ~25).

### `audio` and `video` override categories

v1 supports two override categories that can appear in `global` and inside each `movie` item:

- `audio:`
- `video:`

Only certain keys are recognized by the v1 code path. Commonly used keys:

`audio:` keys:

- `norm_level` (float, dB target used by the normalize step)
- `highpass` (int, Hz)
- `lowpass` (int, Hz)
- `audio_format` (`WAV` or `MP3`)
- `audio_mode` (`mono` or `stereo`)
- `samplerate` (int, Hz)
- `bitrate` (int, used as “bit depth” in v1 conventions)
- `lame_preset` (string, MP3 preset name)

`video:` keys:

- `crf` (int, x264 CRF)
- `movframerate` (int, output frame rate used during encoding)

Note: These keys are loaded by a single internal `type_map`. If a key is not recognized, it is ignored by v1.

### `output_file`

`output_file` is the final muxed output filename. Defaults to `complete.mkv` if omitted.

## Top-level: `type: movie`

A movie block defines one input file and a set of edits. Each movie is rendered to a temporary output, then all processed movies are concatenated in order.

Common fields:

```yaml
- type: movie
  file: input.mkv
  avsync: +100ms
  audio:
    norm_level: -9
  timing:
    "00:00.0": {type: noise}
    "00:10.0": {type: skip}
    "00:11.0": {type: normal}
    "01:40.0": {type: stop}
```

### `file`

Required. Path to a media file.

### `avsync`

Optional audio offset applied to the movie audio before segment splitting.

Accepted formats:

- milliseconds: `+100ms` or `250ms`
- timecode: `H:MM:SS.s` or `MM:SS.s` (parsed as seconds)

Behavior:

- if the offset is positive, emwy prepends silence to the normalized audio track.
- negative offsets are not consistently supported by the current v1 code path.

### `timing`

Required. A mapping from **timecodes** to **segment flags**.

Timecode format accepted by v1:

- `MM:SS.sss` (minutes and seconds are required)
- `H:MM:SS.sss` (hours optional)

Seconds may be fractional.

Examples:

- `"00:18.1"`
- `"0:03:08.0"`

#### Critical v1 quirk: implicit end time

v1 does not store explicit `out` times. Instead:

- Each timing key marks the **start** of a segment.
- The **end** of that segment is the next timing key in sorted order.
- Therefore the final timing key must exist to terminate processing.

In practice, authors end the timeline by including a final marker with `type: stop`.

#### Segment flags

Each timing entry value is a dictionary. The most important key is `type`.

Supported `type` values used by the v1 pipeline:

- `normal`  
  Includes the segment and applies `speed.normal`.

- `fastforward`  
  Includes the segment and applies `speed.fast_forward`.

- `skip`  
  Excludes the segment.

- `noise`  
  Excludes the segment. Historically intended to mark a noise sample window for noise reduction, but in the current v1 code path it behaves primarily as a skipped segment.

- `stop`  
  Excludes the segment and typically serves as the final terminator marker.

Notes:

- Segments with `type` in `{skip, noise, stop}` are skipped by a `skipcodes` table.
- Any `type` not recognized by the v1 code will effectively be treated as `normal` speed unless it is skipped by `skipcodes`.

#### Title cards within timing

A timing flag may include a `titlecard` dictionary. When present, emwy inserts a generated title card **before** the processed segment for that timing marker.

Example:

```yaml
"02:28.1":
  type: normal
  titlecard:
    text: "Older Computers"
    font_size: 96
    audio_file: Graze.mp3
    norm_level: -15
```

v1 title card behavior:

- Duration is fixed in code (commonly 2.0 seconds).
- The title card inherits the movie resolution and uses the current output frame rate.
- The title card requires `audio_file` in the current v1 implementation.
- The title card audio is normalized to `norm_level` (titlecard-specific or fallback to the current normalization level).

## Top-level: `type: titlecard`

v1 YAML supports a top-level `type: titlecard` entry, for example:

```yaml
- type: titlecard
  text: "banana"
  size: 96
```

However, the current v1 processing pipeline parses these entries but does not render them into the output. Title cards that actually affect output are the `titlecard:` blocks attached to `timing` entries inside a `movie`.

## Output semantics

For each `movie`:

1. Extract and normalize audio for the entire movie.
2. For each segment `[t_i, t_{i+1})`:
   - If skipped: do nothing.
   - Else:
     - Cut video segment and apply speed (normal or fastforward).
     - If `titlecard` exists: insert a generated card before the segment.
     - Cut audio segment, apply speed, and mux with the processed video segment.
3. Concatenate all processed segments (and inserted cards) into one processed movie file.

After all movies are processed:

- Concatenate processed movie files in order into `global.output_file`.

## Known limitations of v1 (useful when reading the code)

- No explicit `out` times. End time is implicit from the next timing entry.
- No first-class track model. Everything is effectively a single program track.
- Limited transition support (hard cuts only, aside from inserted title cards).
- Several keys appear in historical YAML examples but are not used consistently by the current v1 code path (for example watermark fields and some per-segment audio replacement fields).
- Top-level `type: titlecard` entries are parsed but not emitted.

## Minimal example

```yaml
- type: global
  quality: fast
  speed: {normal: 1.1, fast_forward: 40}
  audio: {norm_level: -2, audio_format: MP3, audio_mode: stereo}
  output_file: output.mkv

- type: movie
  file: input.mp4
  timing:
    "00:00.0": {type: skip}
    "00:05.0": {type: normal}
    "00:10.0": {type: fastforward}
    "00:20.0": {type: stop}
```
