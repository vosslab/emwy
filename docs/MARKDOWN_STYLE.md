# Markdown Style

Keep documentation concise, scannable, and consistent.

## Content
- use ASCII and ISO-8859-1 character encoding
- escape UTF-8 symbols such as &alpha;, &beta;, etc.

## Headings
- Use sentence case.
- Start at `#` for the document title, then `##`, `###` as needed.
- Keep headings short (3-6 words).

## Lists
- Prefer `-` for bullets.
- One idea per bullet.
- Keep bullet lines short; wrap at ~100 chars.

## Code
- Use fenced code blocks with language where practical.
- Use inline backticks for file paths, CLI flags, and identifiers.

## Links
- Use relative links inside the repo.
- Prefer descriptive link text, not raw URLs.
- When referencing another doc, always link it (avoid bare filenames).
- Example: [docs/FORMAT.md](docs/FORMAT.md), [docs/CLI.md](docs/CLI.md)

## Recommended common docs
- `AGENTS.md`: agent instructions, tool constraints, and repo-specific workflow guardrails.
- `README.md`: project purpose, quick start, and links to deeper documentation.
- `LICENSE`: legal terms for using and redistributing the project; keep exact license text.
- `docs/CHANGELOG.md`: chronological, user-facing changes by date/version; canonical release history.
- `docs/CODE_ARCHITECTURE.md`: high-level system design, major components, and data flow.
- `docs/FILE_STRUCTURE.md`: directory map with what belongs where, including generated assets.
- `docs/INSTALL.md`: setup steps, dependencies, and environment requirements.
- `docs/MARKDOWN_STYLE.md`: Markdown writing rules and formatting conventions for this repo.
- `docs/NEWS.md`: curated release highlights and announcements, not a full changelog.
- `docs/PYTHON_STYLE.md`: Python formatting, linting, and project-specific conventions.
- `docs/RELATED_PROJECTS.md`: sibling repos, shared libraries, and integration touchpoints.
- `docs/ROADMAP.md`: planned work, priorities, and what is intentionally not started.
- `docs/TODO.md`: backlog scratchpad for small tasks without timelines.
- `docs/TROUBLESHOOTING.md`: known issues, fixes, and debugging steps with symptoms.
- `docs/USAGE.md`: how to run the tool, CLI flags, and practical examples.

### Less common but acceptable
- `docs/AUTHORS.md`: primary maintainers and notable contributors; keep short.
- `docs/COOKBOOK.md`: extended, real-world scenarios that build on usage docs.
- `docs/DEVELOPMENT.md`: local dev workflows, build steps, and release process.
- `docs/FAQ.md`: short answers to common questions and misconceptions.

### File I/O
Possible examples:
- `docs/INPUT_FORMATS.md`: supported input formats, required fields, and validation rules.
- `docs/OUTPUT_FORMATS.md`: generated outputs, schemas, naming rules, and destinations.
- `docs/FILE_FORMATS.md`: combined reference for input and output formats when one doc is clearer.
- `docs/YAML_FILE_FORMAT.md`: YAML schema, examples, and validation requirements.

### Docs not to use
- `CODE_OF_CONDUCT.md`: avoid adding unless project scope changes and it will be maintained.
- `COMMUNITY.md`: avoid adding; this repo does not run a community program.
- `ISSUE_TEMPLATE.md`: avoid adding; we are not using GitHub issue templates here.
- `PULL_REQUEST_TEMPLATE.md`: avoid adding; we are not using GitHub PR templates here.
- `SECURITY.md`: avoid adding unless security reporting is formally supported.

### Repo-specific docs are always encouraged
- `docs/CONTAINER.md`: container image details, build steps, and run commands.
- `docs/ENGINES.md`: supported external engines/services and how to select them.
- `docs/EMWY_YAML_v2_SPEC.md`: specification for the EMWY YAML v2 format with examples.
- `docs/MACOS_PODMAN.md`: macOS-specific Podman setup steps and known issues.
- `docs/QUESTION_TYPES.md`: catalog of question types with expected fields and behavior.

## Examples
- Show a minimal example before a complex one.
- Label sample output explicitly if needed.

## Tone
- Write in the present tense.
- Prefer active voice.
- Avoid filler and speculation.
