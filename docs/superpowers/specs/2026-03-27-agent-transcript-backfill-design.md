# Agent Transcript Backfill Design

## Goal

Add two manual backfill scripts for TokenLeague so users can replay previously unrecorded historical usage from local agent artifacts into the existing ingestion API.

The scripts must cover:

- Codex
- Claude Code

Each script must support a `--dry-run` mode.

## Scope

- Add one manual backfill script per supported agent.
- Reuse existing transcript parsing and TokenLeague ingestion behavior where practical.
- Default each script to scanning the agent's standard local history location without requiring manual path input.
- Add `--dry-run` support so users can inspect what would be uploaded before sending any data.
- Add automated tests for scanning, dry-run behavior, and error handling.
- Document how to run the backfill scripts.

Out of scope:

- Changing the server ingestion API or database schema.
- Adding persistent checkpoint state for incremental backfill.
- Turning backfill into an always-on background collector.
- Inventing or estimating missing token counts when the source artifacts do not contain them.

## Existing Context

TokenLeague already ingests usage through per-agent hooks or collectors and stores data through the existing idempotent endpoints:

- `/api/ingest/prompt-event`
- `/api/ingest/task-run`

Those endpoints already upsert records by external identifiers, so a manual backfill can safely reuse the same payload format without introducing a separate import API.

Current agent support differs by source format:

- Codex stores structured session JSONL files under `~/.codex/sessions/...`.
- Claude Code stores structured transcript JSONL files under `~/.claude/projects/...`.

Because of that, the backfill design covers Codex and Claude Code only.

## Design

### Script layout

Add two user-facing scripts:

- `scripts/backfill_codex.py`
- `scripts/backfill_claude.py`

Also add one internal shared module to avoid duplicating upload, summary, and command-line wiring:

- `scripts/backfill_common.py`

The user-facing scripts stay separate because the requested operating model is independent manual commands rather than one multiplexed command with an agent selector.

### Manual execution model

Both scripts are one-shot tools that the user runs manually.

They do not persist local checkpoint or cursor state. Repeated execution is safe because the server already uses upsert semantics for:

- `external_event_id`
- `external_task_id`

This keeps the implementation simple and aligned with the intended "manual one-time backfill" workflow.

### Default scan roots

Each script must work with no path argument.

Default roots:

- Codex: `~/.codex/sessions`
- Claude Code: `~/.claude/projects`

Each script may additionally accept an optional `--root PATH` override for troubleshooting or constrained replay, but default execution must require no path knowledge from the user.

### Agent-specific scanning behavior

#### Codex

The Codex backfill scans `~/.codex/sessions/**/*.jsonl`.

For each session transcript:

1. Read the transcript entries.
2. Extract session metadata from `session_meta`.
3. Extract every completed turn from `task_started` + `token_count` + `task_complete`.
4. Build one `prompt-event` per completed turn.
5. Build one aggregated `task-run` per session.

Unlike the live Codex hook, the backfill script must not use live session state such as `baseline_completed_turn_count` or `processed_turn_ids`. It should treat each historical session file as a full replay source.

#### Claude Code

The Claude Code backfill scans `~/.claude/projects/**/*.jsonl`.

It must exclude transcript files under `/subagents/` by default so subagent conversations do not get replayed as top-level usage records.

For each transcript:

1. Reuse the existing Claude transcript grouping logic for primary user and assistant turns.
2. Build one `prompt-event` per grouped assistant message that carries usage.
3. Build one aggregated `task-run` per session.

If a transcript contains no prompt events after parsing, it should be skipped and counted in the summary.

### Dry-run behavior

Each script must support `--dry-run`.

In dry-run mode:

- Scan files normally.
- Parse and build payloads normally.
- Do not send any HTTP requests.
- Do not write any local state.

Dry-run output must include a summary with:

- scanned file count
- discovered session count
- generated prompt-event count
- generated task-run count
- skipped item count
- failed item count
- skip reasons grouped by category

Dry-run should also print a small sample of generated records so the user can validate the replay shape before performing a real upload. Sample fields should include:

- session id
- external event id
- project name
- agent type
- agent version
- model name

### Upload behavior

Non-dry-run execution reuses the existing ingestion API and authentication flow through:

- `TOKENLEAGUE_API_URL`
- `TOKENLEAGUE_HOOK_KEY`

Upload ordering is per session:

1. Upload every `prompt-event` for the session.
2. Only if all prompt uploads succeed, upload the session `task-run`.

If a session fails, the script continues processing later sessions and reports the failures at the end.

### Command-line interface

Both scripts must share the same flags:

- `--dry-run`
- `--limit N`
- `--verbose`
- `--root PATH`

Behavior:

- `--dry-run`: parse only, no uploads
- `--limit N`: process at most `N` sessions after discovery
- `--verbose`: print per-file or per-session handling details
- `--root PATH`: override the default scan root

### Error handling

- Missing scan root: exit cleanly with an explanatory summary.
- Invalid JSON or unreadable transcript file: skip that file and record a parse failure.
- Missing required token or timing data: skip that session and record the reason.
- Missing `TOKENLEAGUE_HOOK_KEY` in non-dry-run mode: fail fast before upload begins.
- Network or API failure for one session: record the failure and continue with later sessions.

The scripts should return:

- exit code `0` when the run completed without upload or parse failures, including the case where nothing was backfillable
- exit code `1` when at least one parse or upload failure occurred

### Testing

Add focused tests for:

- Codex default-root scanning and full session replay
- Claude default-root scanning and exclusion of `/subagents/`
- dry-run producing payload counts without calling upload helpers
- per-session upload ordering
- failure accounting for malformed files
- `--limit` behavior

## Files

Create:

- `scripts/backfill_common.py`
- `scripts/backfill_codex.py`
- `scripts/backfill_claude.py`
- `service/tests/test_backfill_scripts.py`
- `docs/superpowers/specs/2026-03-27-agent-transcript-backfill-design.md`

Modify:

- `README.md`
- `docs/HOOKS.md`
