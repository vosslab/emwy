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
- For image backgrounds, define a `cards` style with `background: {kind: image, asset: ...}`.
- For solid backgrounds, use `background: {kind: color, color: "#101820"}`.
- For gradients, use `background: {kind: gradient, from: "#101820", to: "#2b5876", direction: vertical}`.
- Use `font_file` in the card style for consistent sizing across machines.

Example:

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

## Picture-in-Picture
Picture-in-picture requires overlays, which are not yet supported in the v2 authoring surface. Use the MLT export for advanced layering until overlays are implemented.

## Batch Rendering
- Place multiple `.emwy.yaml` files in a directory.
- Use a shell script to loop over them: `for f in projects/*.emwy.yaml; do emwy "$f"; done`.

Feel free to copy and tweak these recipes for your own workflow.
