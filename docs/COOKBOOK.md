# Cookbook

This cookbook captures reusable patterns for common editing tasks.

## Trim Lecture Openings
1. Register the raw capture under `assets.video`.
2. Add a `timeline.segments` entry with `in`/`out` to trim the opening.
3. Render the project.

## Speed Up Pauses
- Split the clip into multiple segments.
- Add `video: {speed: 3.0}` and `audio: {speed: 3.0}` on silent sections.
- Keep `video: {speed: 1.0}` and `audio: {speed: 1.0}` on normal sections.

## Add Title Cards
- Use a `generator` segment with a fixed `duration`.
- Use `fill_missing: {audio: silence}` if the card has no audio.

## Picture-in-Picture
Picture-in-picture requires overlays, which are not yet supported in the v2 authoring surface. Use the MLT export for advanced layering until overlays are implemented.

## Batch Rendering
- Place multiple `.emwy.yaml` files in a directory.
- Use a shell script to loop over them: `for f in projects/*.emwy.yaml; do emwy "$f"; done`.

Feel free to copy and tweak these recipes for your own workflow.
