# Gemini CLI Hook Support Design

## Goal

Add TokenLeague statistics hook support for Gemini CLI so Gemini sessions can upload per-prompt and per-session token usage to the existing leaderboard without changing the server ingestion API.

## Scope

- Add project templates for Gemini hook configuration and hook script under `.gemini/`.
- Extend `scripts/install_hooks.sh` to install and uninstall Gemini hooks in project and global locations.
- Add automated tests for Gemini hook behavior and install script wiring.
- Update user-facing hook installation documentation.

Out of scope:

- Antigravity support.
- Refactoring Claude/Codex hooks into a shared framework.
- Server-side schema changes.

## Existing Context

The repository already supports two agent families:

- Claude Code: transcript parsing on `Stop` / `SessionEnd`.
- Codex CLI: local session state captured on `UserPromptSubmit`, then aggregated on `Stop`.

Gemini CLI has a different hook model. Official docs describe hooks in `.gemini/settings.json` or `~/.gemini/settings.json`, with JSON-over-stdin input and JSON-over-stdout output. Relevant lifecycle points are `SessionStart`, `BeforeAgent`, `AfterModel`, `AfterAgent`, and `SessionEnd`.

## Design

### Hook configuration

Use `.gemini/settings.json` with TokenLeague hooks registered for:

- `SessionStart` with matcher `startup`
- `BeforeAgent` with matcher `*`
- `AfterModel` with matcher `*`
- `AfterAgent` with matcher `*`
- `SessionEnd` with matcher `exit`

Each hook invokes the same Python script: `.gemini/hooks/tokenleague.py`.

### Data collection strategy

Gemini `SessionEnd` is best-effort, so prompt usage must be uploaded before shutdown. The hook script will therefore:

- `SessionStart`: emit a startup message describing `TOKENLEAGUE_API_URL` and hook key presence.
- `BeforeAgent`: initialize or update local session state, create a new pending turn with prompt start time, cwd, project name, and model fallback.
- `AfterModel`: capture the most recent model response metadata for the pending turn.
- `AfterAgent`: convert the pending turn into a prompt-event payload and update accumulated task-run totals, then upload both payloads immediately.
- `SessionEnd`: clean up local session state only.

### Session state

Persist Gemini hook state under `TMPDIR` similarly to Codex, keyed by `GEMINI_SESSION_ID` when present, otherwise a session id from hook payload.

State shape:

- `session_id`
- `project_name`
- `cwd`
- `model_name`
- `task_run` aggregate
- `pending_turn`

`pending_turn` contains:

- `started_at`
- `prompt`
- `latest_usage`
- `latest_response_id`
- `latest_model_name`
- `latest_model_version`

### Token extraction

Gemini hook docs guarantee stable `llm_request` and `llm_response` envelopes but do not fully guarantee every usage field. The implementation will:

1. Prefer `llm_response.usageMetadata.promptTokenCount` for input tokens.
2. Prefer `llm_response.usageMetadata.candidatesTokenCount` for output tokens.
3. Fall back to `llm_response.usageMetadata.totalTokenCount` when detailed fields are absent, assigning the total to input tokens and `0` to output tokens.

This fallback preserves usable accounting even if Gemini CLI omits fine-grained counts in some builds.

### Model metadata

- `model_name`: prefer `llm_request.model`, then any model value embedded in `llm_response`, then prior state.
- `agent_version`: prefer explicit Gemini CLI version fields or environment overrides, then auto-detect from the installed `gemini` binary path; if unavailable, use `"unknown"`.
- `agent_type`: constant `"gemini-cli"`.

### Error handling

- Missing hook key: skip upload and write structured log entry.
- Missing usage metadata: skip upload for that turn and keep logs explicit.
- Invalid JSON or unreadable state: recover with empty state.
- All logs go to a temp file and never to stdout.

## Testing

Add focused tests for:

- `.gemini/settings.json` hook registration.
- Install script references to `.gemini/settings.json` and `--gemini`.
- `SessionStart` message formatting.
- `BeforeAgent` state initialization.
- `AfterModel` usage capture.
- `AfterAgent` prompt-event and task-run upload behavior.
- Fallback token extraction from `totalTokenCount`.

## Files

Create:

- `.gemini/settings.json`
- `.gemini/hooks/tokenleague.py`
- `.gemini/hooks/tokenleague.env.example`
- `service/tests/test_gemini_hook.py`

Modify:

- `scripts/install_hooks.sh`
- `README.md`
- `docs/HOOKS.md`
