# OpenClaw Hook Support Design

## Goal

Add TokenLeague statistics support for OpenClaw without changing the server ingestion API, using OpenClaw Gateway session storage as the source of truth instead of terminal hook events.

## Scope

- Move built-in hook assets out of repository-root auto-discovery directories and into `hooks/<agent>/` template directories.
- Add OpenClaw collector assets under `hooks/openclaw/`.
- Extend `scripts/install_hooks.sh` to install and uninstall OpenClaw collector assets in project and global locations.
- Add automated tests for OpenClaw session parsing, aggregation, and deduplication behavior.
- Update user-facing hook installation documentation, including service-safe environment setup guidance.

Out of scope:

- TokenLeague server schema changes.
- Refactoring Claude, Codex, Gemini, and OpenClaw into a shared abstraction.
- Rewriting OpenClaw Gateway configuration.
- Realtime streaming or webhook-based ingestion for OpenClaw.

## Existing Context

The repository already supports hook-driven integrations for Claude Code, Codex CLI, and Gemini CLI. Those agents expose local hook lifecycles that can upload usage at prompt or session boundaries.

OpenClaw differs in two important ways:

- It commonly runs through a long-lived service process, so shell profile environment variables are not a reliable configuration path.
- Official documentation treats the Gateway session store as the canonical source for session state, token totals, and transcript history.

Because of that, OpenClaw should be integrated as a collector that reads Gateway session artifacts and converts them into the same TokenLeague ingestion payloads already used by other agents.

## Design

### Integration model

Add a dedicated OpenClaw collector script instead of trying to reuse the existing local command-hook model.

Repository-owned hook assets should live under `hooks/<agent>/` rather than `.claude/`, `.codex/`, `.gemini/`, or `.openclaw/` at the repository root. This prevents the repository checkout itself from auto-enabling hooks when a user already has global agent configuration.

The collector will read:

- `~/.openclaw/agents/<agent_id>/sessions/sessions.json`
- `~/.openclaw/agents/<agent_id>/sessions/<session_id>.jsonl`

It will transform OpenClaw session data into:

- `/api/ingest/prompt-event`
- `/api/ingest/task-run`

`agent_type` is fixed to `"openclaw"`.

### Environment strategy

The recommended configuration path for service deployments is `~/.openclaw/.env`.

Required and optional variables:

- `TOKENLEAGUE_HOOK_KEY`
- `TOKENLEAGUE_API_URL`
- `TOKENLEAGUE_OPENCLAW_VERSION` (optional override)

This is the primary recommendation because OpenClaw services do not reliably inherit interactive shell configuration such as `~/.zshrc` or `~/.bashrc`.

Document `env.shellEnv.enabled` only as a fallback troubleshooting path, not as the default setup.

### Data collection flow

The collector will:

1. Load `sessions.json` to discover sessions, token totals, update timestamps, and model/session metadata.
2. Read the matching session transcript JSONL file for each target session.
3. Identify prompt/assistant completion boundaries from transcript entries.
4. Emit prompt-level `prompt-event` payloads for newly observed turns.
5. Emit session-level `task-run` payloads reflecting the latest known aggregate totals.

This design keeps OpenClaw ingestion aligned with the existing leaderboard schema while respecting OpenClaw's storage model.

### Session and turn mapping

Session-level data comes from `sessions.json`:

- `session_id`
- `started_at`
- `finished_at` or last updated time
- aggregate input/output token totals
- prompt count
- model name when available

Turn-level data comes from transcript JSONL:

- prompt start time
- assistant completion time
- prompt index within the session
- per-turn model metadata when present

When transcript entries do not contain per-turn token usage, the collector should still emit prompt events by deriving timing and sequence boundaries from transcript history and using the latest session aggregate totals only for `task-run`.

### Idempotency and local state

The collector must avoid double-uploading previously processed data.

Persist local state under a temp or local state file keyed by OpenClaw agent and session identifiers. Track:

- processed session ids
- latest uploaded transcript offset or turn identifier per session
- last uploaded aggregate timestamp per session

If state is missing or unreadable, recover by rebuilding from current OpenClaw files and only uploading what appears new relative to the stored cursor.

### Model and version metadata

- `model_name`: prefer session store metadata, then transcript metadata, then `"unknown"`.
- `agent_version`: prefer `TOKENLEAGUE_OPENCLAW_VERSION`, then any explicit OpenClaw version metadata discoverable from local installation, otherwise `"unknown"`.

OpenClaw model metadata and OpenClaw binary version must remain separate fields.

### Install behavior

Extend `scripts/install_hooks.sh` with `--openclaw`.

The installer should treat `hooks/<agent>/` as the source of truth for all built-in hook templates:

- `hooks/claude/`
- `hooks/codex/`
- `hooks/gemini/`
- `hooks/openclaw/`

Global or explicit local installs copy from those directories into agent-specific config locations such as `~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.openclaw/`, or repository-local target directories when `--local` is requested.

Global install:

- copy `hooks/openclaw/tokenleague_collect.py`
- copy `hooks/openclaw/tokenleague.env.example`
- target `~/.openclaw/`

Local install:

- copy the same assets into repository-local `.openclaw/` only when the user explicitly runs `install_hooks.sh --local`

The install script should not rewrite the user's main OpenClaw Gateway configuration. It should only place collector assets and print next-step guidance for configuring `~/.openclaw/.env` and restarting the OpenClaw service.

### Error handling

- Missing `TOKENLEAGUE_HOOK_KEY`: skip upload and log a clear error.
- Missing OpenClaw session files: exit cleanly without failing the user's OpenClaw workflow.
- Malformed session or transcript records: skip the bad record, continue processing the rest, and log the parse issue.
- Network or upload failures: preserve cursor state only for successfully uploaded records so retries remain safe.
- All logs go to a local temp log file and never to stdout unless explicitly requested by the caller.

## Testing

Add focused tests for:

- install script wiring for `--openclaw`
- parsing `sessions.json`
- mapping transcript JSONL into prompt-event payloads
- aggregating session totals into task-run payloads
- deduplication cursor behavior
- version detection and environment override behavior
- safe handling of missing or malformed OpenClaw files

## Files

Create:

- `hooks/openclaw/tokenleague_collect.py`
- `hooks/openclaw/tokenleague.env.example`
- `service/tests/test_openclaw_hook.py`
- `docs/superpowers/specs/2026-03-24-openclaw-hook-design.md`

Modify:

- `hooks/claude/*`
- `hooks/codex/*`
- `hooks/gemini/*`
- `scripts/install_hooks.sh`
- `README.md`
- `docs/HOOKS.md`
