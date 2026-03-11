# Tools

Utility scripts live here and are not part of the core render pipeline.
Each tool is a sub-package with a shebang-runnable entry point script.

Run `run_tool.py` to list available tools or dispatch to one:
```bash
source source_me.sh && python emwy_tools/run_tool.py
source source_me.sh && python emwy_tools/run_tool.py silence_annotator -- --help
```

Quick index:
- `silence_annotator/silence_annotator.py` detect silence and emit an EMWY v2 timeline YAML
- `stabilize_building/stabilize_building.py` global stabilize and emit a derived stabilized video + sidecar report
- `track_runner/track_runner.py` track a runner in handheld footage and produce a cropped/reframed output
- `video_scruncher/video_scruncher.py` design stub (not implemented)

Shared modules:
- `tools_common.py` shared utilities (file checks, video probing, time parsing)
- `emwy_yaml_writer.py` helper for generating EMWY YAML programmatically

Tests:
- `tests/` tool-specific pytest tests with shared `conftest.py`

Related docs:
- [docs/TOOLS.md](../docs/TOOLS.md) full tool documentation
- [docs/FORMAT.md](../docs/FORMAT.md) v2 YAML format
- [docs/CLI.md](../docs/CLI.md) CLI usage and flags
- [docs/DEBUGGING.md](../docs/DEBUGGING.md) troubleshooting and dump-plan
