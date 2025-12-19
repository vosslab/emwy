# Frequently Asked Questions

### Why YAML?
YAML keeps the project human-editable and diffable, so you can script changes or review them in Git.

### Can I mix frame rates?
Not within one project. Normalize all clips to the `profile.fps` before referencing them or expect stutter.

### How do I upgrade from v1?
Follow the migration notes in `docs/FORMAT.md` and match each `movie` block to playlists. Most users can translate segments into playlists with explicit `in`/`out` values and keep files under the `.emwy.yaml` extension.

### Does emwy support Windows?
Yes through WSL; run the CLI inside Ubuntu and keep assets on the Linux filesystem for best performance.

### How do I report issues?
Open a GitHub issue with your project YAML, logs, and tool versions (FFmpeg, melt, SoX).
