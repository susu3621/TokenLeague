# Gemini CLI Hook Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add installable Gemini CLI hooks that report TokenLeague prompt and task usage with automated test coverage and updated documentation.

**Architecture:** Add a dedicated `.gemini` hook implementation that follows Gemini CLI’s official hook lifecycle instead of forcing it into the Claude or Codex model. Persist minimal per-session state in `TMPDIR`, upload turn data on `AfterAgent`, and extend the existing installer to manage `.gemini/settings.json` alongside the current agent families.

**Tech Stack:** Python hook scripts, Bash installer, JSON settings files, pytest

---

### Task 1: Add failing Gemini hook tests

**Files:**
- Create: `service/tests/test_gemini_hook.py`
- Test: `service/tests/test_gemini_hook.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_gemini_settings_register_expected_hooks():
    ...

def test_after_agent_uploads_prompt_and_task_usage():
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest service/tests/test_gemini_hook.py -q`
Expected: FAIL because `.gemini` hook assets and implementation do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `.gemini/settings.json`, `.gemini/hooks/tokenleague.py`, and `.gemini/hooks/tokenleague.env.example` with only the logic needed to satisfy the tests.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest service/tests/test_gemini_hook.py -q`
Expected: PASS

### Task 2: Extend installer for Gemini

**Files:**
- Modify: `scripts/install_hooks.sh`
- Test: `service/tests/test_gemini_hook.py`

- [ ] **Step 1: Write the failing installer assertions**

```python
def test_install_script_supports_gemini_settings():
    ...
```

- [ ] **Step 2: Run targeted test to verify it fails**

Run: `pytest service/tests/test_gemini_hook.py::test_install_script_supports_gemini_settings -q`
Expected: FAIL because `--gemini` and `.gemini/settings.json` support is missing.

- [ ] **Step 3: Write minimal installer changes**

Add `--gemini`, include Gemini in the default install target set, copy `.gemini/hooks/*`, merge/remove `.gemini/settings.json` hook config, and print Gemini verification guidance.

- [ ] **Step 4: Run targeted test to verify it passes**

Run: `pytest service/tests/test_gemini_hook.py::test_install_script_supports_gemini_settings -q`
Expected: PASS

### Task 3: Update docs

**Files:**
- Modify: `README.md`
- Modify: `docs/HOOKS.md`

- [ ] **Step 1: Write doc assertions in your head and update docs after behavior is stable**

Document install, uninstall, config paths, and supported agents including Gemini CLI.

- [ ] **Step 2: Verify docs reference Gemini consistently**

Run: `rg -n "Gemini|gemini" README.md docs/HOOKS.md scripts/install_hooks.sh`
Expected: Gemini install and usage instructions appear in all three files.

### Task 4: Run final verification

**Files:**
- Test: `service/tests/test_gemini_hook.py`
- Test: `service/tests/test_claude_hook.py`
- Test: `service/tests/test_codex_hook.py`

- [ ] **Step 1: Run Gemini tests**

Run: `pytest service/tests/test_gemini_hook.py -q`
Expected: PASS

- [ ] **Step 2: Run neighboring hook tests**

Run: `pytest service/tests/test_claude_hook.py service/tests/test_codex_hook.py -q`
Expected: PASS

- [ ] **Step 3: Review diff for scope control**

Run: `git diff -- . ':!docs/superpowers'`
Expected: Only Gemini hook support, installer, tests, and docs changes.
