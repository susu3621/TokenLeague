# OpenClaw Hook Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenClaw collector support that reads Gateway session artifacts, uploads TokenLeague prompt and task usage, and moves built-in hook assets into a non-auto-enabled `hooks/` template layout.

**Architecture:** Move repository-owned hook templates for Claude, Codex, Gemini, and OpenClaw into `hooks/<agent>/` so a repository checkout does not auto-enable hooks by default. Add a dedicated OpenClaw collector template under `hooks/openclaw/`; the collector reads `sessions.json` and session transcript JSONL files, maintains a local deduplication cursor, uploads `prompt-event` and `task-run` payloads through the existing API, and is installed by extending the current hook installer to copy templates into explicit local or global agent config directories.

**Tech Stack:** Python collector scripts, Bash installer, JSON session parsing, pytest

---

### Task 1: Add failing tests for the new template layout and OpenClaw collector

**Files:**
- Modify: `service/tests/test_claude_hook.py`
- Modify: `service/tests/test_codex_hook.py`
- Modify: `service/tests/test_gemini_hook.py`
- Create: `service/tests/test_openclaw_hook.py`
- Test: `service/tests/test_openclaw_hook.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_claude_hook_assets_live_under_hooks_directory():
    ...

def test_install_script_supports_openclaw_assets():
    ...

def test_collect_session_uploads_prompt_and_task_usage():
    ...

def test_collect_session_skips_previously_processed_turns():
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest service/tests/test_openclaw_hook.py -q`
Expected: FAIL because `hooks/openclaw/` assets and collector implementation do not exist yet.

- [ ] **Step 3: Write minimal test fixtures**

Create representative OpenClaw fixture payloads inline in `service/tests/test_openclaw_hook.py`:

```python
SESSIONS_FIXTURE = {
    "sessions": [
        {
            "id": "session-1",
            "agentId": "agent-1",
            "model": "claude-3-7-sonnet",
            "startedAt": "2026-03-24T09:00:00.000Z",
            "updatedAt": "2026-03-24T09:00:15.000Z",
            "usage": {"inputTokens": 120, "outputTokens": 45},
        }
    ]
}
```

and transcript JSONL records that delimit at least one user turn and one assistant completion.

- [ ] **Step 4: Run tests again to confirm the failures are meaningful**

Run: `pytest service/tests/test_openclaw_hook.py -q`
Expected: FAIL on missing module, missing functions, or missing `hooks/openclaw/` assets, not on malformed test setup.

### Task 2: Move built-in hook assets into `hooks/<agent>/`

**Files:**
- Create: `hooks/claude/tokenleague.py`
- Create: `hooks/claude/tokenleague.env.example`
- Create: `hooks/claude/settings.json`
- Create: `hooks/codex/tokenleague.py`
- Create: `hooks/codex/tokenleague.env.example`
- Create: `hooks/codex/hooks.json`
- Create: `hooks/gemini/tokenleague.py`
- Create: `hooks/gemini/tokenleague.env.example`
- Create: `hooks/gemini/settings.json`
- Test: `service/tests/test_claude_hook.py`
- Test: `service/tests/test_codex_hook.py`
- Test: `service/tests/test_gemini_hook.py`

- [ ] **Step 1: Update existing tests to load assets from `hooks/<agent>/`**

Change path expectations in the existing hook tests so they read:

```python
HOOK_PATH = ROOT / "hooks" / "claude" / "tokenleague.py"
```

and equivalent Codex and Gemini paths.

- [ ] **Step 2: Run the existing hook tests to verify they fail**

Run: `pytest service/tests/test_claude_hook.py service/tests/test_codex_hook.py service/tests/test_gemini_hook.py -q`
Expected: FAIL because the new template directories do not exist yet.

- [ ] **Step 3: Move the current hook assets into `hooks/<agent>/`**

Create the new template directories and copy the existing Claude, Codex, and Gemini hook files into them without changing runtime behavior beyond path updates.

- [ ] **Step 4: Run the existing hook tests again**

Run: `pytest service/tests/test_claude_hook.py service/tests/test_codex_hook.py service/tests/test_gemini_hook.py -q`
Expected: PASS, including the worktree project-name regression coverage.

### Task 3: Implement the OpenClaw collector

**Files:**
- Create: `hooks/openclaw/tokenleague_collect.py`
- Test: `service/tests/test_openclaw_hook.py`

- [ ] **Step 1: Implement session file discovery helpers**

Add helpers for:

```python
def _get_openclaw_root() -> Path: ...
def _load_sessions_index(root: Path) -> list[dict[str, Any]]: ...
def _load_session_transcript(root: Path, agent_id: str, session_id: str) -> list[dict[str, Any]]: ...
```

These should read `~/.openclaw/agents/<agent_id>/sessions/sessions.json` and the matching transcript JSONL file, returning empty collections on missing files.

- [ ] **Step 2: Run the focused parsing test**

Run: `pytest service/tests/test_openclaw_hook.py::test_collect_session_uploads_prompt_and_task_usage -q`
Expected: FAIL because payload construction and upload logic do not exist yet.

- [ ] **Step 3: Implement turn extraction and payload builders**

Add minimal functions for:

```python
def _extract_prompt_events(session_record: dict[str, Any], transcript_records: list[dict[str, Any]]) -> list[dict[str, Any]]: ...
def _build_task_run_payload(session_record: dict[str, Any], project_name: str) -> dict[str, Any]: ...
```

Requirements:
- map transcript boundaries into `prompt_started_at` and `prompt_finished_at`
- preserve `task_id`, `project_name`, `agent_type`, `agent_version`, and `model_name`
- use session aggregate totals only for `task-run` when per-turn token counts are unavailable

- [ ] **Step 4: Implement upload orchestration**

Add a single entry point such as:

```python
def collect_and_upload() -> int: ...
```

This should iterate sessions, upload new prompt events first, then upload the latest task-run aggregate.

- [ ] **Step 5: Run collector tests to verify they pass**

Run: `pytest service/tests/test_openclaw_hook.py -q`
Expected: PASS for parsing, payload building, and basic upload behavior.

### Task 4: Add deduplication and version handling

**Files:**
- Modify: `hooks/openclaw/tokenleague_collect.py`
- Test: `service/tests/test_openclaw_hook.py`

- [ ] **Step 1: Write the failing deduplication and version tests**

Cover:

```python
def test_collect_session_skips_previously_processed_turns():
    ...

def test_collect_session_prefers_openclaw_version_env_override():
    ...
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest service/tests/test_openclaw_hook.py::test_collect_session_skips_previously_processed_turns service/tests/test_openclaw_hook.py::test_collect_session_prefers_openclaw_version_env_override -q`
Expected: FAIL because cursor state and version override logic are not implemented yet.

- [ ] **Step 3: Implement local cursor state**

Add state helpers for:

```python
def _load_cursor_state() -> dict[str, Any]: ...
def _save_cursor_state(state: dict[str, Any]) -> None: ...
```

Track per-session turn offsets or stable turn identifiers and the last uploaded aggregate timestamp so repeated collector runs remain idempotent.

- [ ] **Step 4: Implement OpenClaw version detection**

Support:
- `TOKENLEAGUE_OPENCLAW_VERSION` environment override
- local installation metadata detection when available
- fallback to `"unknown"`

- [ ] **Step 5: Run the full OpenClaw test file again**

Run: `pytest service/tests/test_openclaw_hook.py -q`
Expected: PASS with deduplication and version logic included.

### Task 5: Extend the installer for the new hook template layout

**Files:**
- Modify: `scripts/install_hooks.sh`
- Create: `hooks/openclaw/tokenleague.env.example`
- Test: `service/tests/test_openclaw_hook.py`

- [ ] **Step 1: Add failing installer assertions**

Use assertions like:

```python
def test_install_script_supports_openclaw_assets():
    content = INSTALL_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "--openclaw" in content
    assert "install_openclaw_hooks" in content
    assert "uninstall_openclaw_hooks" in content
    assert "hooks/openclaw/tokenleague_collect.py" in content
```

- [ ] **Step 2: Run the targeted installer test**

Run: `pytest service/tests/test_openclaw_hook.py::test_install_script_supports_openclaw_assets -q`
Expected: FAIL because the installer does not know about OpenClaw yet.

- [ ] **Step 3: Implement minimal installer changes**

Add `--openclaw` support, source all built-in hook assets from `hooks/<agent>/`, copy them into repository-local target directories only when `--local` is used, support uninstall cleanup for those target directories, and print next-step guidance that recommends `~/.openclaw/.env`.

- [ ] **Step 4: Create the environment example**

Write `hooks/openclaw/tokenleague.env.example` containing:

```bash
TOKENLEAGUE_HOOK_KEY=your-hook-key-here
TOKENLEAGUE_API_URL=http://localhost:5006
TOKENLEAGUE_OPENCLAW_VERSION=
```

with comments explaining that the real file should be `~/.openclaw/.env` for service-based deployments.

- [ ] **Step 5: Run the targeted installer test again**

Run: `pytest service/tests/test_openclaw_hook.py::test_install_script_supports_openclaw_assets -q`
Expected: PASS

### Task 5: Update OpenClaw documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/HOOKS.md`

- [ ] **Step 1: Update README installation and environment guidance**

Document:
- `--openclaw` installation examples
- that repository-owned hook templates now live under `hooks/` and are not auto-enabled by checkout alone
- that OpenClaw uses a collector, not terminal hook events
- why `~/.openclaw/.env` is the recommended configuration path for service startups

- [ ] **Step 2: Update hook documentation**

Add OpenClaw to the supported agents, explain the collector data flow, list `TOKENLEAGUE_OPENCLAW_VERSION`, and document `env.shellEnv.enabled` only in troubleshooting.

- [ ] **Step 3: Verify doc coverage**

Run: `rg -n "OpenClaw|openclaw|TOKENLEAGUE_OPENCLAW_VERSION|\\.openclaw/\\.env|shellEnv" README.md docs/HOOKS.md scripts/install_hooks.sh`
Expected: OpenClaw install, env, and troubleshooting references appear consistently.

### Task 6: Run final verification

**Files:**
- Test: `service/tests/test_openclaw_hook.py`
- Test: `service/tests/test_claude_hook.py`
- Test: `service/tests/test_codex_hook.py`
- Test: `service/tests/test_gemini_hook.py`
- Test: `scripts/install_hooks.sh`

- [ ] **Step 1: Run the OpenClaw tests**

Run: `pytest service/tests/test_openclaw_hook.py -q`
Expected: PASS

- [ ] **Step 2: Run the neighboring hook test suite**

Run: `pytest service/tests/test_claude_hook.py service/tests/test_codex_hook.py service/tests/test_gemini_hook.py -q`
Expected: PASS to confirm OpenClaw changes did not regress existing integrations.

- [ ] **Step 3: Validate the installer syntax**

Run: `bash -n scripts/install_hooks.sh`
Expected: PASS with no shell syntax errors.

- [ ] **Step 4: Review diff for scope control**

Run: `git diff -- . ':!docs/superpowers'`
Expected: Only `hooks/` assets, installer changes, hook docs, and hook tests are included.
