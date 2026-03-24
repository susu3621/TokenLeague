# User Timeline Range Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the user detail usage timeline to a daily stacked bar chart grouped by project, with dedicated 7-day and 30-day range controls.

**Architecture:** Keep the change scoped to the existing user detail page and timeline API. The frontend owns the new selector and always requests daily buckets, while the backend adds `month` window support, returns per-project totals inside each daily bucket, and zero-fills missing daily dates for stable stacked-bar rendering.

**Tech Stack:** Flask, Jinja templates, Chart.js, pytest

---

### Task 1: Add failing coverage for the new timeline behavior

**Files:**
- Modify: `service/tests/test_token_league.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_user_detail_page_renders_timeline_range_selector(auth_session):
    ...


def test_user_timeline_api_supports_month_daily_range(auth_session):
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest service/tests/test_token_league.py -k "timeline_range_selector or month_daily_range" -q`
Expected: FAIL because the selector markup and `month` timeline support do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Update the timeline endpoint response shape and the user detail template.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest service/tests/test_token_league.py -k "timeline_range_selector or month_daily_range" -q`
Expected: PASS

### Task 2: Implement the timeline selector and stacked project bar chart

**Files:**
- Modify: `service/templates/user_detail.html`
- Modify: `service/app.py`
- Modify: `service/db.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Update timeline window parsing**

Accept `week` and `month` in `/api/users/<id>/timeline`, defaulting to `week`.

- [ ] **Step 2: Add daily zero-fill support and project breakdowns**

Return a full sequence of daily buckets for selected `week` and `month` ranges, plus per-project totals inside each bucket.

- [ ] **Step 3: Update the timeline card UI**

Render the selector and wire it to fetch timeline data for the chosen range.

- [ ] **Step 4: Render a stacked bar chart**

Render one stacked bar per day, with colors derived from project name.

- [ ] **Step 5: Run focused verification**

Run: `pytest service/tests/test_token_league.py -q`
Expected: PASS
