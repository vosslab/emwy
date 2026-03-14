# Claude hook usage guide

Best practices for AI agents working in repos that use the `claude-code-permissions-hook`.
This guide covers what commands are allowed, denied, and passed through, along with
preferred alternatives for denied patterns.

This doc is Claude-specific and does not apply to Codex.

## Overview

The permissions hook intercepts every Claude Code tool call and evaluates it against
TOML config rules. Each call gets one of three outcomes:

| Outcome | Meaning |
| --- | --- |
| **Allow** | Tool call proceeds automatically |
| **Deny** | Tool call is blocked with an error message |
| **Passthrough** | Falls back to Claude Code's default permission flow (user prompt) |

### Command decomposition

The hook splits compound Bash commands (`&&`, `||`, `;`, pipes) into leaf sub-commands
and checks each leaf independently:

- **Deny**: if ANY leaf matches a deny rule, the entire command is denied
- **Allow**: ALL leaves must match an allow rule for the command to be allowed
- **Passthrough**: if any leaf has no matching rule (and none are denied)

The hook also unwraps `bash -c "..."` patterns and extracts commands inside `$(...)`.

### Max chain length

Commands with more than **5** chained sub-commands are denied automatically. Break
long chains into smaller commands or write a script file.

## Allowed commands

### Python

```bash
source source_me.sh && python3 script.py
python3 -m pytest tests/test_foo.py
pytest tests/test_foo.py -k test_name
pyflakes script.py
```

Always use `source source_me.sh && python3` for running Python. Direct `python3`
invocations also work. Command substitution (`` ` `` or `$(...)`) is blocked in
Python commands.

### Git

Allowed git subcommands:

`add`, `branch`, `check-ignore`, `checkout`, `diff`, `ls-files`, `ls-tree`,
`log`, `mv`, `pull`, `remote`, `restore`, `rev-parse`, `show`, `status`, `worktree`

The `-C <path>` flag is supported before the subcommand.

```bash
git status
git diff --staged
git log --oneline -10
git -C /path/to/repo status
git mv old_name.py new_name.py
```

### Cargo

All cargo subcommands are allowed except: `publish`, `yank`, `login`, `logout`,
`owner`, `install`. Command substitution is blocked.

```bash
cargo build
cargo test
cargo clippy -- -D warnings
cargo fmt --check
```

### Shell scripts

```bash
bash script.sh
bash -n script.sh        # syntax check only
./script.sh
./script.py
./subdir/script.py
```

### Safe utilities

These commands are allowed as single commands. Command substitution is blocked.

**File and text processing:**
`awk`, `cat`, `colordiff`, `comm`, `cut`, `diff`, `expand`, `file`, `fmt`, `fold`,
`grep`, `head`, `jq`, `mediainfo`, `nl`, `od`, `paste`, `rg`, `sed`, `seq`, `shuf`,
`sort`, `tac`, `tail`, `tee`, `tr`, `unexpand`, `uniq`, `wc`, `xargs`

**Filesystem navigation:**
`basename`, `cd`, `chmod`, `cp`, `dirname`, `du`, `df`, `find`, `ls`, `lsof`,
`mkdir`, `mktemp`, `readlink`, `realpath`, `stat`, `tar`, `touch`, `tree`, `unzip`

**Process and system info:**
`curl`, `date`, `echo`, `env`, `export`, `expr`, `false`, `id`, `ln`, `md5`,
`nproc`, `numfmt`, `pgrep`, `pkill`, `printenv`, `printf`, `ps`, `pwd`,
`screencapture`, `sleep`, `source`, `test`, `timeout`, `true`, `tty`, `uname`,
`unlink`, `wc`, `which`, `whoami`, `xcrun`, `xxd`

Note: Some of these (like `cat`, `grep`, `find`, `head`, `tail`) have deny rules
that block them when used with file path arguments. See the denied commands section.
Use the dedicated tools (Read, Grep, Glob) instead.

### Env-prefixed commands

One or more `VAR=value` prefixes before a safe command are allowed:

```bash
LC_ALL=C sort file.txt
REPO_ROOT=/path PYTHONPATH=lib python3 -m pytest
```

### File deletion (safe patterns)

The `rm` command is denied by default, but these specific patterns are allowed:

| Pattern | Example |
| --- | --- |
| Underscore-prefixed files | `rm _temp.py`, `rm -f _scratch.sh` |
| `/tmp/` paths | `rm /tmp/test_output.json` |
| Cache directories | `rm -rf __pycache__`, `rm -r ~/Library/Caches/foo` |
| `git rm` with relative paths | `git rm old_file.py` |

### Package managers (read-only)

```bash
pip show numpy
pip list
pip freeze
pip check
brew list
brew info python
brew search qt
brew --prefix
```

### File access zones

| Tool | Allowed paths |
| --- | --- |
| Read | `~/` and below, Homebrew site-packages, `/tmp/`, `/var/folders/` |
| Write | `~/nsh/`, `~/.claude/`, `/tmp/` |
| Edit | `~/nsh/`, `~/.claude/`, `/tmp/` |
| Glob | `~/nsh/`, `~/.claude/`, `/tmp/` |
| Grep | `~/nsh/`, `~/.claude/`, `/tmp/` |

All file tools block path traversal (`..`). Reading `.env` and `.secret` files is denied.

### Web tools

`WebFetch` and `WebSearch` are allowed without restrictions.

### Agent types

Allowed subagent types for the Agent tool:

`Explore`, `general-purpose`, `Plan`, `Bash`, `haiku`, `sonnet`, `opus`,
`statusline-setup`, `claude-code-guide`, `superpowers:code-reviewer`,
`coder`, `reviewer`, `tester`, `maintainer`, `planner`, `orchestrator`,
`integrator`, `architect`, `scheduler`, `monitor`, `parallelizer`

### Orchestration tools

These tools are auto-allowed: `TaskOutput`, `TaskCreate`, `TaskList`, `TaskGet`,
`TaskUpdate`, `TaskStop`, `Skill`, `SendMessage`, `TeamCreate`, `TeamDelete`,
`NotebookEdit`.

Playwright MCP browser tools (`mcp__plugin_playwright_playwright__browser_*`)
are also allowed.

## Denied commands

### `rm` (file deletion)

**Blocked:** `rm file.txt`, `rm -rf dir/`

**Why:** Prevents accidental deletion of important files.

**Instead:** Use underscore-prefixed filenames for scratch files (`_temp.py`),
write to `/tmp/`, or use `git rm` for tracked files.

### `git commit`, `git stash`, `git clean`

**Blocked:** All variations including flag insertion (`git -C /tmp commit`).

**Why:** Humans make commits. `git clean` is destructive and removes untracked files.

**Instead:** Stage changes with `git add` and update `docs/CHANGELOG.md`. The user
commits manually.

### `cat`/`head`/`tail` with file paths

**Blocked:** `cat /path/to/file`, `head -20 /abs/path/file.txt`

**Why:** The Read tool provides a better experience with line numbers and offset/limit.

**Instead:** Use the Read tool with optional `offset` and `limit` parameters.
Pipeline usage without file paths (e.g., consuming stdin) is still allowed.

### `grep`/`rg` with file paths

**Blocked:** `grep pattern /path/to/file`, `rg pattern /abs/search/dir`

**Why:** The Grep tool provides structured output modes and context lines.

**Instead:** Use the Grep tool with `pattern`, `path`, `glob`, `-A`/`-B`/`-C`,
`output_mode`, and `head_limit` parameters. Pipeline filtering (no file path)
is still allowed.

### `find`

**Blocked:** `find . -name "*.py"`

**Why:** The Glob tool is faster and supports recursive patterns.

**Instead:** Use `Glob(pattern='**/*.py', path='/search/dir')`.

### `sed -n`

**Blocked:** `sed -n '10,20p' file.txt`

**Why:** The Read tool with offset and limit does this better.

**Instead:** Use `Read(file_path='file.txt', offset=10, limit=11)`.
Other sed operations (substitution, etc.) are allowed.

### Heredocs (`<<EOF`)

**Blocked:** `python3 - <<EOF`, `bash <<'SCRIPT'`

**Why:** Heredocs are hard to read, lint, and test.

**Instead:** Write code to a `_temp.py` or `_temp.sh` file using the Write tool,
then run it with `source source_me.sh && python3 _temp.py` or `bash _temp.sh`.
Underscore-prefixed files can be removed freely.

### `for` and `while` loops

**Blocked:** `for f in *.py; do ...`, `while read line; do ...`

**Why:** Loop logic belongs in script files, not inline Bash.

**Instead:** Write the logic in a `_temp.py` or `_temp.sh` file and execute it.

### `bash -c` / `bash -lc`

**Blocked:** `bash -c "command"`, `bash -lc "source && python3 ..."`

**Why:** The Bash tool already runs bash. `bash -c` is redundant bash-in-bash.

**Instead:** Run the command directly: `source source_me.sh && python3 script.py`.
Running script files (`bash script.sh`, `bash -n script.sh`) is still allowed.

### `mv`

**Blocked:** `mv old.py new.py`

**Why:** Use `git mv` for tracked files to preserve history.

**Instead:** `git mv old.py new.py`. For untracked files, use `cp` + `rm` or ask
the user.

### `VAR=$(...)` assignments

**Blocked:** `PROJECT=$(basename $PWD)`, `OUTPUT=$(python3 script.py)`

**Why:** Command substitution in assignments creates hidden side effects.

**Instead:** Use `source source_me.sh` for environment setup or inline the command
directly.

### `$PYTHON` variable

**Blocked:** `$PYTHON script.py`, `${PYTHON} -m pytest`

**Why:** Use the actual interpreter name for clarity.

**Instead:** `python3 script.py`

### `PYTHONDONTWRITEBYTECODE` / `PYTHONUNBUFFERED`

**Blocked:** Setting these environment variables manually.

**Why:** `source_me.sh` already exports these.

**Instead:** `source source_me.sh && python3 ...`

### Bare variable assignments

**Blocked:** `REPO_ROOT=/path/to/repo` (with no command following)

**Why:** The decomposer splits `A=x && cmd` into leaves; a bare `A=x` leaf is
useless.

**Instead:** Use space-separated env prefixes on one line: `REPO_ROOT=/path python3 script.py`

### `gh` CLI

**Blocked:** All `gh` commands.

**Why:** `gh` is not installed on this system.

**Instead:** N/A. GitHub operations are not available via CLI.

### Homebrew python `-c`

**Blocked:** `/opt/homebrew/bin/python3 -c "print('hello')"`

**Why:** Inline code is hard to lint and debug.

**Instead:** Write a `_temp.py` file and run it with
`source source_me.sh && python3 _temp.py`.

## Passthrough (interactive tools)

These tools intentionally passthrough to Claude Code's default permission flow
so the user sees interactive dialogs:

| Tool | Reason |
| --- | --- |
| `AskUserQuestion` | User must see and answer the question dialog |
| `EnterPlanMode` | User must consent to entering plan mode |
| `ExitPlanMode` | User must review and approve the plan |
| `EnterWorktree` | User must consent to worktree creation |
| `ExitWorktree` | User must consent to keep/remove decision |
| `CronCreate` | User should approve scheduled recurring jobs |
| `CronDelete` | User should approve canceling scheduled jobs |
| `CronList` | Kept consistent with other Cron tools |

Do NOT add these tools to any allow rule. Auto-approving them bypasses Claude Code's
interactive UI dialogs, causing blank answers or skipped consent screens.

## Best practices

- Always use `source source_me.sh && python3` for Python execution
- Use dedicated tools (Read, Grep, Glob) instead of their Bash equivalents
- Write scratch code to `_temp.py` or `_temp.sh` (underscore prefix = safe to delete)
- Keep compound commands under 5 chained sub-commands
- No command substitution (`` ` `` or `$(...)`) in variable assignments
- Use relative paths for project files where possible
- For loops or conditionals, write a script file instead of inline Bash
- Stage changes and update `docs/CHANGELOG.md`; let the user commit

## Common patterns

| Task | Wrong | Right |
| --- | --- | --- |
| Run Python | `python3 script.py` | `source source_me.sh && python3 script.py` |
| Read a file | `cat /path/to/file.py` | Read tool: `file_path="/path/to/file.py"` |
| Search files | `grep -r "pattern" src/` | Grep tool: `pattern="pattern"`, `path="src/"` |
| Find files | `find . -name "*.py"` | Glob tool: `pattern="**/*.py"` |
| Read lines 10-20 | `sed -n '10,20p' file.txt` | Read tool: `offset=10`, `limit=11` |
| Delete temp file | `rm temp.py` | Name it `_temp.py`, then `rm _temp.py` |
| Rename file | `mv old.py new.py` | `git mv old.py new.py` |
| Loop over files | `for f in *.py; do ...` | Write `_temp.sh` with the loop, run `bash _temp.sh` |
| Inline Python | `python3 -c "print(1)"` | Write `_temp.py`, run with source_me.sh |
| Set env + run | `REPO_ROOT=/x && python3 s.py` | `REPO_ROOT=/x python3 s.py` (one line) |
| Run heredoc | `python3 - <<EOF ...` | Write `_temp.py`, run with source_me.sh |
| GitHub CLI | `gh pr list` | Not available (`gh` not installed) |
