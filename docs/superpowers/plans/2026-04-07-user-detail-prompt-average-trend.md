# User Detail Prompt Average Trend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show only the per-prompt average token trend on the user detail page and rename the section to directly reflect that meaning.

**Architecture:** Keep the existing user detail page structure and timeline data source intact. Limit the change to i18n copy, the user detail template heading, and the frontend chart helpers so the chart renders one prompt-average dataset while preserving project-specific filtering.

**Tech Stack:** Flask, Jinja2 templates, Chart.js, pytest

---

### Task 1: Update tests for the new prompt-average-only chart

**Files:**
- Modify: `service/tests/test_token_league.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write the failing test**

```python
def test_user_detail_page_renders_prompt_average_trend_chart_section(auth_session):
    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    messages = _user_detail_messages(html)
    assert "Avg Tokens / Prompt Trend" in html
    assert 'canvas id="average-timeline-chart"' in html
    assert messages["avg_tokens_per_prompt"] == "Avg Tokens / Prompt"
    assert "avg_tokens_per_project" not in messages
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py -k "prompt_average_trend or average_timeline"`
Expected: FAIL because the page still renders the old heading and still exposes the per-project average message.

- [ ] **Step 3: Write minimal implementation**

```html
<h3>{{ t('user_detail.prompt_average_timeline_heading') }}</h3>
```

```javascript
function renderPromptAverageTimeline(timeline, windowValue, projectName = null) {
    // single-series prompt average chart
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py -k "prompt_average_trend or average_timeline"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/tests/test_token_league.py service/templates/user_detail.html service/i18n.py
git commit -m "fix: simplify user prompt average trend chart"
```

### Task 2: Implement the prompt-average-only chart

**Files:**
- Modify: `service/templates/user_detail.html`
- Modify: `service/i18n.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write the failing test**

```python
def test_user_detail_page_script_renders_prompt_average_timeline_from_timeline_buckets(auth_session):
    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "function renderPromptAverageTimeline(timeline, windowValue, projectName = null)" in html
    assert "function averageTokensPerProject" not in html
    assert "label: userDetailMessages.avg_tokens_per_prompt" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py -k "prompt_average_timeline_from_timeline_buckets or updates_average_and_prompt_count"`
Expected: FAIL because the script still renders the old generic average timeline and includes the per-project average helper.

- [ ] **Step 3: Write minimal implementation**

```javascript
function averageTokensPerPrompt(bucket, projectName = null) {
    const totalTokenCount = projectName ? tokenCountForProject(bucket, projectName) : Number(bucket.total_token_count || 0);
    const promptCount = projectName ? promptCountForProject(bucket, projectName) : Number(bucket.prompt_count || 0);
    return promptCount ? totalTokenCount / promptCount : 0;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py -k "prompt_average_timeline_from_timeline_buckets or updates_average_and_prompt_count"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/tests/test_token_league.py service/templates/user_detail.html service/i18n.py
git commit -m "fix: render prompt average trend only"
```
