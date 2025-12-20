# Roadmap

This roadmap prioritizes reliability and interchange over UI features.

## Near Term
- Finalize [EMWY_YAML_v2_SPEC.md](../EMWY_YAML_v2_SPEC.md) and parser.
- Add MLT import path to complement the exporter.
- Implement playlist transitions (crossfades, dips).
- Support entry `enabled` flags to skip sections without affecting timeline timing.
- Export MKV chapters from entry `title` fields (honoring `chapter: false`).
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
