# Cookbook

This cookbook captures reusable patterns for common editing tasks.

## Trim Lecture Openings
1. Register the raw capture under `assets.video`.
2. Add a `timeline.segments` entry with `in`/`out` to trim the opening.
3. Render the project.

## Speed Up Pauses
- Split the clip into multiple segments.
- Define `assets.playback_styles` for repeated speeds (for example `normal` and `fast`).
- Apply `style` on each `source` entry, or set matching `video.speed`/`audio.speed`.

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
Picture-in-picture can be modeled as an overlay track.

Example (PiP with a slide deck overlay):

```yaml
timeline:
  segments:
    - source: {asset: lecture, in: "00:00.0", out: "10:00.0"}
  overlays:
    - id: slides
      geometry: [0.64, 0.06, 0.34, 0.34]
      opacity: 1.0
      segments:
        - source: {asset: slides, in: "00:00.0", out: "10:00.0"}
```

## Fast Forward Watermark
Use an overlay text generator on an overlay track.

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
    - source: {asset: lecture, in: "00:10.0", out: "00:20.0", style: fast}
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

## Batch Rendering
- Place multiple `.emwy.yaml` files in a directory.
- Use a shell script to loop over them: `for f in projects/*.emwy.yaml; do emwy "$f"; done`.

Feel free to copy and tweak these recipes for your own workflow.
