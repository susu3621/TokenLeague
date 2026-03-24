# User Detail Token Format Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render all token values on the user detail page in compact human-readable form such as `K`, `M`, and `B`.

**Architecture:** Add one server-side compact token formatter to support Jinja-rendered values and one matching browser formatter for async tables and Chart.js callbacks. Keep prompt/task counts unchanged so only token-bearing values get the new display treatment.

**Tech Stack:** Flask, Jinja templates, Chart.js, pytest

---

### Task 1: Add failing coverage for compact token formatting

**Files:**
- Modify: `service/tests/test_token_league.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_compact_token_count_formats_human_readable_suffixes():
    ...


def test_user_detail_page_renders_compact_token_counts(auth_session):
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest service/tests/test_token_league.py -k "compact_token_count or compact_token_counts" -q`
Expected: FAIL because no compact formatter exists yet.

- [ ] **Step 3: Write minimal implementation**

Add server and browser compact formatter helpers and route token fields through them.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest service/tests/test_token_league.py -k "compact_token_count or compact_token_counts" -q`
Expected: PASS

### Task 2: Apply compact formatting across the user detail page

**Files:**
- Modify: `service/app.py`
- Modify: `service/templates/user_detail.html`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Format server-rendered token values**

Use the compact formatter for summary cards, agent breakdown, and recent prompt events.

- [ ] **Step 2: Format async table token values**

Use the browser formatter for project and model token columns.

- [ ] **Step 3: Format chart ticks and tooltips**

Apply compact token formatting to model and timeline chart numeric labels.

- [ ] **Step 4: Run focused verification**

Run: `pytest service/tests/test_token_league.py -q`
Expected: PASS
