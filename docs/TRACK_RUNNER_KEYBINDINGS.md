# Track runner keybindings

Keyboard shortcuts for the track runner annotation UI.
Keys are shown in the on-screen hint overlay at the bottom of the frame view.

## Common keys (all modes)

These keys work in seed, target, and edit modes.

| Key | Action | Description |
| --- | --- | --- |
| ESC | Quit / return | Close annotation window or return to previous mode |
| Q | Quit | Same as ESC |
| P | Partial toggle | Toggle partial draw mode (visible torso only) |
| A | Approx toggle | Toggle approximate / obstruction draw mode |
| Z | Zoom cycle | Cycle zoom: fit -> 1x -> 1.5x -> 2.25x -> 3.375x -> 5x -> 8x -> 12x -> fit |
| V | Hide predictions | Temporarily suppress prediction overlays (resets on frame advance) |

## Seed mode

Draw torso bounding boxes on seed frames.

| Key | Action | Description |
| --- | --- | --- |
| Shift+LEFT | Scrub backward | Move backward by current step size |
| Shift+RIGHT | Scrub forward | Move forward by current step size |
| Shift+Alt+LEFT | Scrub backward 5x | Multiply scrub distance by 5 |
| Shift+Alt+RIGHT | Scrub forward 5x | Multiply scrub distance by 5 |
| LEFT | Pan left | Pan the view when zoomed in (no-op at fit-zoom) |
| RIGHT | Pan right | Pan the view when zoomed in (no-op at fit-zoom) |
| SPACE | Skip | Skip current frame and advance to next seed frame |
| [ | Decrease step | Halve scrub step size (floor 0.01s) |
| ] | Increase step | Double scrub step size (ceiling 10.0s) |
| ENTER | Accept suggestion | Accept the current YOLO suggestion (shown when available) |
| 1-9 | Select candidate | Select a specific YOLO candidate by number |
| N | Not in frame | Mark current position as "not in frame" |
| F | FWD/BWD average | Use forward/backward prediction consensus as seed |

### Mouse and trackpad

| Input | Action | Description |
| --- | --- | --- |
| Click and drag | Draw box | Draw a torso bounding box on the frame |
| Mouse wheel up | Zoom in | Zoom in by 1.25x, anchored to cursor position |
| Mouse wheel down | Zoom out | Zoom out by 1.25x, anchored to cursor position |
| Trackpad two-finger swipe | Pan | Pan the view when zoomed in |

## Target mode

Target mode uses the same keybindings as seed mode.
The difference is the pass number and solver mode, not the controls.

## Edit mode

Review and refine existing seed annotations.

| Key | Action | Description |
| --- | --- | --- |
| SPACE | Keep / accept polish | Keep seed and advance to next; or accept polish preview if pending |
| Shift+RIGHT | Keep / accept polish | Same as SPACE |
| Shift+LEFT | Previous | Go to previous seed |
| LEFT / RIGHT | Pan | Pan the view when zoomed in (no-op at fit-zoom) |
| D | Delete | Delete current seed from the list |
| N | Not in frame | Mark seed as "not in frame" |
| Y | YOLO polish | Run YOLO refinement and show preview box (press SPACE to accept) |
| F | Consensus polish | Run FWD/BWD consensus refinement and show preview |
| ] | Jump forward | Jump forward 10% through the filtered seed list |
| [ | Jump backward | Jump backward 10% through the filtered seed list |
| L | Low confidence | Jump to next low-confidence seed (score < 0.5) |
| U | Add seeds | Enter seed mode to add new seeds, then return to edit |

### Polish workflow

1. Press Y (YOLO) or F (consensus) to generate a refinement preview.
2. The preview box appears on the frame.
3. Press SPACE to accept the polish, or any other key to reject it.

## Zoom behavior

The Z key cycles through fixed zoom levels centered on the prediction or seed position:

```
fit -> 1x -> 1.5x -> 2.25x -> 3.375x -> 5x -> 8x -> 12x -> fit
```

Arrow keys always pan at any zoom level. Use Shift+Arrow for time navigation
(frame scrub in seed mode, seed navigation in edit mode).

The zoom controls in the status bar provide additional options:
- `-` / `+` buttons for incremental zoom
- Slider for direct zoom percentage
- Fit button to reset to fit-to-view

## Draw modes

| Mode | Key | Status bar indicator | Description |
| --- | --- | --- | --- |
| Normal | (default) | None | Draw full bounding box |
| Partial | P | PARTIAL MODE | Draw visible torso only (subject partially occluded) |
| Approximate | A | APPROX MODE | Draw approximate box (obstruction or estimation) |

Press the same key again to exit a draw mode.

## Toolbar buttons

The annotation toolbar provides clickable equivalents for common actions.
Seed mode toolbar includes Prev, Next, Skip, step size, Partial, and Approx buttons.
Edit mode toolbar includes Prev, Keep, Partial, and Approx buttons.

The overlay toolbar toggles visibility of prediction overlays: FWD, BWD, REFINED, AVG, and Legend.
