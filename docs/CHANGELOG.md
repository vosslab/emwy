# Changelog

## Unreleased
- Added overlay template apply rules so fast-forward title cards can be authored once.
- Added overlay tracks with transparent blanks and overlay rendering support.
- Added `still` generator support and transparent card backgrounds for overlays.
- Documented overlay authoring and updated Shotcut export limitations.
- Updated silence annotator YAML to include fast-forward overlays.
- Fixed pyflakes runner to avoid null-separated sort errors.
- Documented MLT interop mapping and added export test coverage.
- Added silence annotator config file support and simplified CLI flags.
- Polished silence annotator config validation and defaults handling.
- Added MLT import/export specification docs.
- Added `pyproject.toml` and `MANIFEST.in` for packaging metadata.
- Added centralized version file and release history doc.
- Expanded pyflakes runner output with categorized error counts.
- Expanded pyflakes error categorization patterns.
- Expanded pyflakes syntax error matching.
- Added output for unclassified pyflakes errors.
- Filtered pyflakes summaries to true error lines and added warning category.
- Filtered first/random/last pyflakes output to error lines only.
- Implemented MKV chapter export from segment titles.
- Reshaped README introduction to lead with the EMWY acronym and MLT compatibility.
- Clarified the EMWY acronym in the README.
- Resolved AGENTS documentation links to use `docs/` paths.
- Added `.DS_Store` to `.gitignore`.
- Fixed documentation links to `docs/PYTHON_STYLE.md`.
- Moved contributor guidance to `docs/DEVELOPMENT.md`.
- Renamed `docs/ARCHITECTURE.md` to `docs/CODE_ARCHITECTURE.md`.
- Added documentation scaffolding and agent descriptions.
- Introduced pip requirements file for development tooling.
- Documented installation, CLI usage, cookbook recipes, and troubleshooting tips.
- Added v2 sample project with `.emwy.yaml` extension and run script.
- Added MLT exporter module for v2 YAML projects.
- Split media wrappers into `emwylib/media` for ffmpeg and sox helpers.
- Added `paired_audio` expansion for generator entries when playlists are aligned.
- Made `timeline.segments` the required authoring surface; playlists/stack are compiled-only.
- Removed `take` support from v2 loader and timeline.
- Updated rendering to process and mux A/V per segment before concatenation.
- Added CLI flags for temp retention and cache directory (`--keep-temp`, `--cache-dir`).
- Added title/chapter card backgrounds (image, color, gradient) with font overrides.

## v1.0.0
- Initial public release of emwy with YAML v2 parser and CLI.
