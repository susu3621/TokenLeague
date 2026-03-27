# Agent Transcript Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two manual backfill scripts for Codex and Claude Code that default-scan local historical artifacts, support `--dry-run`, and replay valid usage into the existing TokenLeague ingestion API.

**Architecture:** Add a shared `scripts/backfill_common.py` module for command-line parsing, summary accounting, sample printing, and per-session upload orchestration. Implement `scripts/backfill_codex.py` and `scripts/backfill_claude.py` as thin adapters over the existing hook parsing logic so the backfill path reuses the same payload rules as the live hooks.

**Tech Stack:** Python scripts, existing hook helper modules, JSON/JSONL transcript parsing, pytest

---

### Task 1: Add failing backfill script tests

**Files:**
- Create: `service/tests/test_backfill_scripts.py`
- Test: `service/tests/test_backfill_scripts.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_codex_dry_run_scans_default_root_and_counts_payloads():
    ...

def test_claude_backfill_skips_subagent_transcripts():
    ...

def test_backfill_uploads_prompt_events_before_task_run():
    ...
```

- [ ] **Step 2: Run the focused test file to verify it fails**

Run: `pytest service/tests/test_backfill_scripts.py -q`
Expected: FAIL because the backfill scripts and shared helpers do not exist yet.

- [ ] **Step 3: Add representative fixtures inline in the test file**

Create minimal artifacts for:

```python
CODEX_TRANSCRIPT = [
    {"type": "session_meta", "payload": {"id": "session-1", "cwd": "/tmp/TokenLeague", "cli_version": "0.116.0"}},
    {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1"}},
    {"type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 10, "output_tokens": 5, "cached_input_tokens": 2}}}},
    {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-1"}},
]
```

plus Claude transcript JSONL with one assistant usage record.

- [ ] **Step 4: Re-run the focused test file to confirm failures are meaningful**

Run: `pytest service/tests/test_backfill_scripts.py -q`
Expected: FAIL on missing modules or missing functions, not on broken test fixture setup.

### Task 2: Implement shared backfill runtime and Codex replay

**Files:**
- Create: `scripts/backfill_common.py`
- Create: `scripts/backfill_codex.py`
- Test: `service/tests/test_backfill_scripts.py`

- [ ] **Step 1: Write the first targeted failing Codex assertions**

Focus on:

```python
def test_codex_dry_run_scans_default_root_and_counts_payloads():
    ...

def test_backfill_uploads_prompt_events_before_task_run():
    ...
```

- [ ] **Step 2: Run only the Codex-focused tests to verify they fail**

Run: `pytest service/tests/test_backfill_scripts.py -k "codex or uploads_prompt_events_before_task_run" -q`
Expected: FAIL because there is no shared CLI runtime or Codex replay script.

- [ ] **Step 3: Implement the shared runtime**

Create `scripts/backfill_common.py` with focused helpers such as:

```python
def build_parser(default_root: Path, description: str) -> argparse.ArgumentParser: ...
def print_summary(summary: dict[str, Any], *, dry_run: bool) -> None: ...
def upload_session(send_request, prompt_events: list[dict[str, Any]], task_run: dict[str, Any]) -> tuple[int, int, bool]: ...
```

Requirements:
- support `--dry-run`, `--limit`, `--verbose`, and `--root`
- count scanned files, discovered sessions, generated prompt events, generated task runs, skips, and failures
- print a small sample of generated records in dry-run mode

- [ ] **Step 4: Implement the Codex backfill script with minimal adapters**

Create `scripts/backfill_codex.py` that:
- defaults to `~/.codex/sessions`
- scans `**/*.jsonl`
- reuses `hooks/codex/tokenleague.py` parsing helpers for completed turns and payload building
- treats every discovered session transcript as a full replay source
- uses the shared runtime for dry-run and upload behavior

Use a same-directory import bootstrap like:

```python
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import backfill_common
```

- [ ] **Step 5: Run the Codex-focused tests to verify they pass**

Run: `pytest service/tests/test_backfill_scripts.py -k "codex or uploads_prompt_events_before_task_run" -q`
Expected: PASS

- [ ] **Step 6: Commit the Codex backfill slice**

```bash
git add service/tests/test_backfill_scripts.py scripts/backfill_common.py scripts/backfill_codex.py
git commit -m "feat: add codex transcript backfill"
```

### Task 3: Implement Claude Code replay

**Files:**
- Create: `scripts/backfill_claude.py`
- Test: `service/tests/test_backfill_scripts.py`

- [ ] **Step 1: Write the Claude-specific failing test**

```python
def test_claude_backfill_skips_subagent_transcripts():
    ...
```

- [ ] **Step 2: Run the Claude-focused test to verify it fails**

Run: `pytest service/tests/test_backfill_scripts.py -k "claude" -q`
Expected: FAIL because the Claude backfill script does not exist yet.

- [ ] **Step 3: Implement the Claude backfill script**

Create `scripts/backfill_claude.py` that:
- defaults to `~/.claude/projects`
- scans `**/*.jsonl`
- ignores any path containing `/subagents/`
- reuses `hooks/claude/tokenleague.py` transcript-to-payload builder
- feeds payloads into the shared runtime for dry-run and upload

Keep the session/file boundary explicit so one malformed transcript only affects one session.

- [ ] **Step 4: Run the Claude-focused test to verify it passes**

Run: `pytest service/tests/test_backfill_scripts.py -k "claude" -q`
Expected: PASS

- [ ] **Step 5: Commit the Claude backfill slice**

```bash
git add service/tests/test_backfill_scripts.py scripts/backfill_claude.py
git commit -m "feat: add claude transcript backfill"
```

### Task 4: Document the scripts and run final verification

**Files:**
- Modify: `README.md`
- Modify: `docs/HOOKS.md`
- Test: `service/tests/test_backfill_scripts.py`
- Test: `service/tests/test_claude_hook.py`
- Test: `service/tests/test_codex_hook.py`
- Test: `service/tests/test_cursor_hook.py`

- [ ] **Step 1: Update user-facing docs**

Document:
- the two script names
- default scan behavior
- `--dry-run`
- `--limit`
- required environment variables for actual upload

- [ ] **Step 2: Run the new backfill test file**

Run: `pytest service/tests/test_backfill_scripts.py -q`
Expected: PASS

- [ ] **Step 3: Run neighboring hook regression tests**

Run: `pytest service/tests/test_claude_hook.py service/tests/test_codex_hook.py service/tests/test_cursor_hook.py -q`
Expected: PASS

- [ ] **Step 4: Review the diff for scope control**

Run: `git diff -- . ':!docs/superpowers'`
Expected: Only the new backfill scripts, tests, and docs changes appear.

- [ ] **Step 5: Commit the docs and verification slice**

```bash
git add README.md docs/HOOKS.md service/tests/test_backfill_scripts.py scripts/backfill_common.py scripts/backfill_codex.py scripts/backfill_claude.py
git commit -m "feat: add manual transcript backfill scripts"
```
