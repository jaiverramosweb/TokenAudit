---
name: token-usage
description: >
  Aggregate daily Claude Code token usage from local JSONL transcripts and
  keep a per-project TOKEN_USAGE.md registry that records every query.
  Shows per-day, per-project, per-model, main-thread-vs-subagent breakdown
  plus an optional JSON export for later calculations.
  Trigger: when the user wants to check token usage, measure cost, see daily tokens,
  asks "cuánto token usé", "cuánto gasté", "token usage", or types /token-usage.
license: MIT
metadata:
  author: Jaiver Ramos
  version: "1.2"
---

## When to Use

Invoke this skill when the user wants to:

- See today's, yesterday's, weekly, or monthly token usage
- Compare consumption across projects or models
- Separate main-thread cost from sub-agent cost
- Export a snapshot for billing, reporting, or historical tracking

## What It Reads

Every Claude Code session writes a JSONL transcript under
`~/.claude/projects/<project-hash>/*.jsonl`. Each line contains, among
other things:

- `timestamp` (UTC, ISO-8601)
- `message.model` (e.g. `claude-opus-4-7`, `claude-sonnet-4-6`)
- `message.usage` with `input_tokens`, `output_tokens`,
  `cache_creation_input_tokens`, `cache_read_input_tokens`
- `isSidechain` (true for sub-agent messages)
- `sessionId`, `cwd`, `gitBranch`, `uuid`, `parentUuid`

The script walks the JSONL, groups by **date x project x model x agent**,
and attributes each sub-agent message to its launching `subagent_type`
by backtracking the `parentUuid` chain to the parent Task tool_use call.

## How to Run

The user types `/token-usage` (optionally with arguments). Execute the
bundled script via `Bash`:

```bash
python "$HOME/.claude/skills/token-usage/token_usage.py" [flags]
```

Map the user's arguments directly to flags. If no arguments are given,
default to `--period today`.

### Flags

| Flag | Values | Default | What it does |
|------|--------|---------|-------------|
| `--period`, `-p` | `today`, `yesterday`, `week`, `month`, `all` | `today` | Date window (UTC) |
| `--project` | substring match | — | Filter by project directory name |
| `--export` | — | off | Writes snapshot + per-day rollups to `~/.claude/token-usage/` |
| `--json` | — | off | Prints JSON to stdout instead of the table |
| `--no-registry` | — | off | Skip the per-project `TOKEN_USAGE.md` update |

### Examples

```bash
# Today, all projects
python "$HOME/.claude/skills/token-usage/token_usage.py"

# This week + export persistent rollups
python "$HOME/.claude/skills/token-usage/token_usage.py" -p week --export

# Filter a project
python "$HOME/.claude/skills/token-usage/token_usage.py" -p month --project sensei-discovery

# Machine-readable (for pipelines or further processing)
python "$HOME/.claude/skills/token-usage/token_usage.py" -p today --json
```

## Output

### Table mode (default)

Per day, a table with columns:

| Column | Meaning |
|--------|---------|
| Project | Directory name under `~/.claude/projects/` |
| Model | Model ID reported by the API |
| Agent | `main` for main thread, otherwise the `subagent_type` (e.g. `Explore`, `general-purpose`, `Plan`) |
| Input | Pure input tokens |
| Output | Output tokens |
| CacheCr | Cache-creation input tokens (billed) |
| CacheRd | Cache-read input tokens (discounted) |
| Msgs | Messages in the bucket |

Plus global totals and a **BILLED** line (`input + output + cache_create`).

### Export mode (`--export`)

Writes to `~/.claude/token-usage/`:

- `snapshot-YYYY-MM-DD_HHMMSS.json` — full run snapshot
- `daily-YYYY-MM-DD.json` — per-day rollup (one file per calendar day,
  re-written on each export so it always reflects the latest data)

Use these files for later calculations, billing reports, or to compare
periods across sessions.

## Per-project registry (`TOKEN_USAGE.md`)

On every run (unless `--no-registry` is passed), the skill writes a
`TOKEN_USAGE.md` file inside the working directory of each project that
had data in the current query. The file contains three sections:

1. **Lifetime totals** — all-time totals across every JSONL transcript
   for that project (billed, input, output, cache_create, cache_read,
   messages).
2. **Daily breakdown** — per-day x model x agent table for the entire
   history of the project. Regenerated on each run; enclosed in
   `<!-- BEGIN:DAILY_TOTALS --> ... <!-- END:DAILY_TOTALS -->`.
3. **Sessions** — last 50 sessions sorted most-recent first. Per row:
   sessionId (8-char prefix), auto-detected title (first meaningful user
   message, cleaned of `<system-reminder>` blocks, truncated to 80
   chars), local start time, duration, message count, billed tokens,
   and a `Reinicios` (resets) column that counts in-session context
   resets. Enclosed in `<!-- BEGIN:SESSIONS --> ... <!-- END:SESSIONS -->`.
   The resets heuristic is: user-type records with `parentUuid=null`
   after the first. If `/clear` produces that signature in the
   transcript, resets are detected; otherwise the column stays `0`. The
   stronger optimization signal is many short sessions with clear
   titles rather than one giant session.
4. **Query log** — append-only history of `/token-usage` invocations.
   Each entry records timestamp, period, optional project filter, and
   the totals produced by that query. Enclosed in
   `<!-- BEGIN:QUERY_LOG --> ... <!-- END:QUERY_LOG -->` and capped at
   the last 500 entries.

Content outside those markers is preserved — feel free to add context,
links, or notes above/below the generated blocks. Content inside them is
overwritten on every run.

The path a project's registry lands in is the `cwd` recorded in the
transcripts (the actual working directory of the session), not the
hashed directory under `~/.claude/projects/`. That keeps the file close
to the code. **Add `TOKEN_USAGE.md` to `.gitignore`** if you do not want
it committed.

If the recorded `cwd` no longer exists on disk (project moved or
deleted), that project is skipped with a note in the output.

## Notes and Gotchas

- Timestamps in the transcripts are **UTC**. Daily buckets are UTC days.
- If a sub-agent message's parent chain can't be resolved to a Task call,
  the Agent column shows `unknown-subagent` rather than guessing.
- Cache-read tokens are reported separately because they are billed at a
  heavy discount; do not include them in the "billed" total.
- The script only reads files the user already has locally; no network
  calls, no external services.
