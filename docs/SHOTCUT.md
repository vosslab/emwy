# Shotcut Export Mode

emwy can emit Shotcut-compatible MLT XML so you can open the project inside Shotcut for manual tweaking.

## Enabling Export
- Run `emwy project.emwy.yaml --save-mlt shotcut.mlt`.
- Copy the MLT file plus referenced media into a Shotcut-accessible folder.

## Limitations
- Only one video track and one audio track are exported today.
- Filters that Shotcut does not understand are skipped with warnings.
- Title cards render as pre-composited clips rather than editable text.

## Workflow Tips
1. Use emwy for deterministic rough cuts.
2. Open `shotcut.mlt` to add manual adjustments (transitions, text, color).
3. Export from Shotcut if advanced effects are required.
