# Cookbook

This cookbook captures reusable patterns for common editing tasks.

## Trim Lecture Openings
1. Register the raw capture under `assets.video`.
2. Create a `video_base` playlist with a first clip starting at the desired intro time.
3. Mirror the same time range in `audio_main`.
4. Reference the playlists in `stack.tracks` and render.

## Speed Up Pauses
- Split the clip into multiple playlist items.
- Attach `speed: 3.0` on the silent section and `speed: 1.1` on the rest.
- Use `ease: linear` for deterministic timing.

## Add Title Cards
- Create an `assets.image` entry (PNG) and optional `assets.audio` cue.
- Build a `titlecard` playlist referencing the assets and specifying a fixed duration via `out`.
- Place the playlist in the stack before the main track with `role: overlay`.

## Picture-in-Picture
1. Duplicate the base video asset with a different playlist name.
2. Add `position` and `scale` filters in the overlay playlist.
3. Insert the overlay playlist into the stack with `role: overlay` and a higher z-order.

## Batch Rendering
- Place multiple `stack` definitions under different YAML files.
- Use a shell script to loop over them: `for f in projects/*.emwy.yaml; do emwy "$f"; done`.

Feel free to copy and tweak these recipes for your own workflow.
