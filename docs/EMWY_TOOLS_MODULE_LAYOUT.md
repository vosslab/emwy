# EMWY tools module layout

This document describes the organization philosophy for the `emwy_tools/` directory.
The rules guide where to place new code as tools are written and refactored.

## Shared modules in common_tools/

Shared modules live in `emwy_tools/common_tools/` when they serve 2 or more tools.

Current contents:

- `common_tools/tools_common.py`: shared utility functions used by multiple tools
- `common_tools/emwy_yaml_writer.py`: shared YAML generation
- `common_tools/frame_reader.py`: shared video frame reading
- `common_tools/frame_filters.py`: display-only image filters for annotation UIs

Until a module has at least 2 real consumers, it stays inside the consuming tool's
folder. This keeps the shared layer clean and avoids premature generalization.

## Per-tool code goes in tool subfolders

Each tool gets its own subfolder under `emwy_tools/`. Tool-specific code lives there.

Examples:

- `emwy_tools/silence_annotator/`: silence detection tool
- `emwy_tools/stabilize_building/`: video stabilization tool
- `emwy_tools/video_scruncher/`: video compression tool
- `emwy_tools/track_runner/`: track running and annotation tool

Tool subfolders may have subfolders for logical grouping. The most common is `ui/`
for Qt-based UI code.

## Promotion rule

A module earns promotion from a tool subfolder to `emwy_tools/` level when:

- It has 2 or more real consumers across different tools.
- Moving it unblocks code sharing and reduces duplication.

Example (hypothetical): If `track_runner` and `video_scruncher` both need custom
Qt widgets, the widgets are initially created inside `track_runner/ui/`. Once
`video_scruncher` needs them, the widgets are promoted to `emwy_tools/qt_layer/`
and both tools import from there.

Do not create shared folders (`qt_common`, `common`, `media`) preemptively. Wait
for the second real consumer.

## track_runner/ui/ structure

The `track_runner/ui/` subfolder splits into two kinds of files.

### Qt plumbing (generic widgets and styling)

These files provide generic Qt infrastructure with no track_runner-specific concepts.
They can be promoted to a shared layer when needed.

- `frame_view.py`: Qt widget for frame display
- `overlay_items.py`: Qt graphics items for overlay visualization
- `theme.py`: color schemes and styling
- `app_shell.py`: main application window shell
- `actions.py`: reusable action definitions

### Controllers and workspace (track_runner semantics)

These files implement track_runner-specific business logic and state management.
They use the generic Qt plumbing but are tightly coupled to track_runner concepts.

- `workspace.py`: workspace state and management
- `seed_controller.py`: seed annotation and editing state
- `target_controller.py`: target management state
- `edit_controller.py`: editing operations
- `status_presenter.py`: status display logic

Tight coupling to track_runner is acceptable here. The generic Qt plumbing in
the first group is what gets promoted when a second tool needs it.

## Naming conventions

### Filenames

- Use lowercase `snake_case` for all filenames.
- Use `_view.py` for Qt view classes.
- Use `_controller.py` for controller classes.
- Use `_presenter.py` for presenter/viewmodel classes.

Examples:

- `frame_view.py`
- `seed_controller.py`
- `status_presenter.py`

### Class names

- Use `CamelCase` for all class names.
- Suffix view classes with `View` (e.g., `FrameView`, `OverlayView`).
- Suffix controller classes with `Controller` (e.g., `SeedController`, `EditController`).
- Suffix presenter classes with `Presenter` (e.g., `StatusPresenter`).

Examples:

```python
class FrameView(QWidget):
	pass

class SeedController:
	pass

class StatusPresenter:
	pass
```

## Non-goals

Do not create these directories unless a second tool actually needs the code:

- `emwy_tools/qt_common/`
- `emwy_tools/qt_layer/`
- `emwy_tools/common/` (use `common_tools/` instead)
- `emwy_tools/media/`
- `emwy_tools/ui/`

Wait for the real consumer before creating a shared layer. Preemptive generalization
often leads to over-designed code that does not match actual use cases.

## Directory tree (current state)

```
emwy_tools/
  run_tool.py               # shared: tool runner
  common_tools/             # shared modules
    __init__.py
    emwy_yaml_writer.py     # shared: YAML generation
    frame_filters.py        # shared: display-only image filters
    frame_reader.py         # shared: video input
    tools_common.py         # shared: utilities
  silence_annotator/        # tool
    config.py
    detection.py
    silence_annotator.py
    __init__.py
  stabilize_building/       # tool
    config.py
    crop.py
    stabilize.py
    stabilize_building.py
    __init__.py
  track_runner/             # tool
    cli.py
    config.py
    crop.py
    detection.py
    encoder.py
    hypothesis.py
    interval_solver.py
    propagator.py
    review.py
    scoring.py
    seed_editor.py
    seeding.py
    state_io.py
    track_runner.py
    __init__.py
    ui/                     # ui subfolder
      frame_view.py         # qt plumbing
      overlay_items.py      # qt plumbing
      theme.py              # qt plumbing
      app_shell.py          # qt plumbing
      actions.py            # qt plumbing
      workspace.py            # annotation workspace
      seed_controller.py      # seed annotation controller
      target_controller.py    # target management controller
      edit_controller.py      # edit operations controller
      status_presenter.py     # status display presenter
      __init__.py
  video_scruncher/          # tool
    video_scruncher.py
    __init__.py
  tests/                    # test suite
    conftest.py
    test_tools_common.py
    test_track_runner.py
    __init__.py
```
