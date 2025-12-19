# Roadmap

This roadmap prioritizes reliability and interchange over UI features.

## Near Term
- Finalize EMWY YAML v2 spec and parser.
- Add MLT import path to complement the exporter.
- Implement playlist transitions (crossfades, dips).
- Add regression tests that re-render sample lectures nightly.

## Mid Term
- Multi-track audio bussing with independent normalization passes.
- GPU-accelerated rendering path for FFmpeg/MLT.
- Configurable template library for title cards.

## Long Term
- Headless cloud rendering pipeline with automatic upload.
- Formal v3 spec with per-track effects graphs.

## Explicit Non-Goals
- No color grading UI.
- No node-based compositing.
- No real-time preview engine.
