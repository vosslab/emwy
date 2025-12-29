# Roadmap

This roadmap prioritizes reliability and interchange over UI features.

## Near Term
- Finalize [EMWY_YAML_v2_SPEC.md](../EMWY_YAML_v2_SPEC.md) and parser.
- Add MLT import path to complement the exporter.
- Implement playlist transitions (crossfades, dips).
- Support entry `enabled` flags to skip sections without affecting timeline timing.
- Export MKV chapters from entry `title` fields (honoring `chapter: false`).
- Pre-render overlay generators (especially `overlay_text`) so MLT export can emit overlay playlists + transitions.
- Add animated overlay text cycles for fast-forward labels (plan):
  - Spec: define `overlay_text.animate` (`kind: cycle`, `values`, `fps` or `cadence`)
    and document `{animate}` placeholder handling.
  - Silence annotator: default overlay text template uses `{animate}` and ships a
    default `animate` block with validation.
  - YAML writer: emit `animate` under overlay text generators when provided.
  - Renderer: render a short loop clip from per-value frames, then loop it to the
    overlay duration.
  - Tests: cover YAML output, loader preservation, and animated overlay command flow.
  - Docs: update [docs/FORMAT.md](FORMAT.md) and [docs/CHANGELOG.md](CHANGELOG.md).
- Expand card backgrounds beyond current `image`/`color`/`gradient` (`video`, `source_blur`).
- Add regression tests that re-render sample lectures nightly.

## Mid Term
- Multi-track audio bussing with independent normalization passes.
- GPU-accelerated rendering path for FFmpeg/MLT.
- Configurable template library for title cards (themes, typography, layout).

## Long Term
- Headless cloud rendering pipeline with automatic upload.
- Formal v3 spec with per-track effects graphs.

## Explicit Non-Goals
- No color grading UI.
- No node-based compositing.
- No real-time preview engine.
