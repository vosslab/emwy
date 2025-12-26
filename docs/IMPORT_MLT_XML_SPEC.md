# Import MLT XML spec (draft)

This document captures ideas for an MLT XML import pipeline. Import is not
implemented yet.

## Goals

- Best-effort import of common MLT timelines into EMWY YAML v2.
- Preserve timing, clips, and speed changes.
- Surface unsupported features as warnings.

## Scope

Initial import should target:

- `avformat` producers
- `timewarp` producers
- playlists with `entry` and `blank`
- tractors with a `multitrack` that includes one base video track and one main
  audio track

## Mapping ideas

- Producers -> `assets` entries
- Playlists -> compiled `playlists` in memory
- Tractor tracks -> `stack.tracks`
- Overlay transitions -> `timeline.overlays` (future)

## Proposed import flow

1. Parse MLT XML.
2. Build a producer table keyed by id.
3. Resolve playlists into ordered entries.
4. Build a stack with base video + main audio.
5. Convert to `timeline.segments` by merging paired audio/video entries.

## Handling speed changes

- `timewarp` producers map to `video.speed` or `audio.speed` in EMWY.
- Preserve the speed in the segment rather than baking it into in/out frames.

## Unsupported features

If present, warn and skip:

- Filters not representable as EMWY filters.
- Complex transitions or multi-track mixing beyond overlays.
- MLT services not recognized by the importer.

## Round-trip expectations

- MLT -> EMWY -> MLT should preserve timing for core cases.
- EMWY -> MLT -> EMWY will be lossy until import exists.
