# User Detail Average Timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second user-detail timeline chart that shows average tokens per active project and average tokens per prompt for the selected window and filters.

**Architecture:** Reuse the existing `/api/users/<id>/timeline` payload and derive both average series in `service/templates/user_detail.html` without changing backend APIs or database queries. Localize the new chart heading and legend labels through `service/i18n.py`, and keep the existing stacked project timeline plus focused-project legend behavior unchanged.

**Tech Stack:** Flask, Jinja templates, inline JavaScript, Chart.js, pytest

---

## File Map

- Modify: `service/templates/user_detail.html`
  - Add the second chart canvas and localized heading.
  - Add client-side state for the new Chart.js instance.
  - Derive average-per-project and average-per-prompt series from fetched timeline buckets.
  - Render the new line chart from the same refreshed timeline payload.
  - Refactor empty-chart handling so it can safely support two different timeline canvases.
- Modify: `service/i18n.py`
  - Add localized strings for the new chart heading and the new "average per project" dataset label.
- Modify: `service/tests/test_token_league.py`
  - Add regression coverage for the new localized chart section and script behavior.

### Task 1: Add localized chart shell coverage

**Files:**
- Modify: `service/tests/test_token_league.py`
- Modify: `service/i18n.py`
- Modify: `service/templates/user_detail.html`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_user_detail_page_renders_average_timeline_chart_section(auth_session):
    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Average Trends" in html
    assert 'canvas id="average-timeline-chart"' in html
    assert '"avg_tokens_per_project": t("user_detail.avg_tokens_per_project")' in html
    assert '"avg_tokens_per_prompt": t("user_detail.avg_tokens_per_prompt")' in html


def test_user_detail_page_renders_average_timeline_chart_section_in_chinese(auth_session):
    response = auth_session.get("/users/1", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "平均值曲线" in html
    assert "每项目平均 Token" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest service/tests/test_token_league.py::test_user_detail_page_renders_average_timeline_chart_section service/tests/test_token_league.py::test_user_detail_page_renders_average_timeline_chart_section_in_chinese -v`
Expected: FAIL because the page does not yet render the new chart section or localized strings.

- [ ] **Step 3: Write the minimal implementation**

```python
# service/i18n.py
"user_detail.average_timeline_heading": "Average Trends",
"user_detail.avg_tokens_per_project": "Avg Tokens / Project",
...
"user_detail.average_timeline_heading": "平均值曲线",
"user_detail.avg_tokens_per_project": "每项目平均 Token",
```

```html
<!-- service/templates/user_detail.html -->
<div class="chart-container">
    <canvas id="timeline-chart"></canvas>
</div>
<h3 style="margin: 24px 0 12px;">{{ t('user_detail.average_timeline_heading') }}</h3>
<div class="chart-container">
    <canvas id="average-timeline-chart"></canvas>
</div>
```

```javascript
// service/templates/user_detail.html
const userDetailMessages = {{ {
    "avg_tokens_per_project": t("user_detail.avg_tokens_per_project"),
    "avg_tokens_per_prompt": t("user_detail.avg_tokens_per_prompt"),
} | tojson }};
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest service/tests/test_token_league.py::test_user_detail_page_renders_average_timeline_chart_section service/tests/test_token_league.py::test_user_detail_page_renders_average_timeline_chart_section_in_chinese -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/tests/test_token_league.py service/i18n.py service/templates/user_detail.html
git commit -m "feat: add user detail average timeline shell"
```

### Task 2: Add regression coverage for average-series rendering

**Files:**
- Modify: `service/tests/test_token_league.py`
- Modify: `service/templates/user_detail.html`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write the failing test**

```python
def test_user_detail_page_script_renders_average_timeline_from_timeline_buckets(auth_session):
    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "let averageTimelineChart = null;" in html
    assert "function averageTokensPerProject(bucket)" in html
    assert "const projectCount = (bucket.project_breakdown || []).length;" in html
    assert "return projectCount ? totalTokenCount / projectCount : 0;" in html
    assert "function averageTokensPerPrompt(bucket)" in html
    assert "return promptCount ? totalTokenCount / promptCount : 0;" in html
    assert "function renderAverageTimeline(timeline, windowValue)" in html
    assert "const averageCtx = document.getElementById('average-timeline-chart').getContext('2d');" in html
    assert "type: 'line'" in html
    assert "label: userDetailMessages.avg_tokens_per_project" in html
    assert "label: userDetailMessages.avg_tokens_per_prompt" in html
    assert "data: timeline.map(bucket => averageTokensPerProject(bucket))" in html
    assert "data: timeline.map(bucket => averageTokensPerPrompt(bucket))" in html
    assert "renderAverageTimeline(data.timeline || [], windowValue);" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest service/tests/test_token_league.py::test_user_detail_page_script_renders_average_timeline_from_timeline_buckets -v`
Expected: FAIL because the template does not yet define average-series helpers or render the second chart.

- [ ] **Step 3: Write the minimal implementation**

```javascript
let averageTimelineChart = null;

function averageTokensPerProject(bucket) {
    const totalTokenCount = Number(bucket.total_token_count || 0);
    const projectCount = (bucket.project_breakdown || []).length;
    return projectCount ? totalTokenCount / projectCount : 0;
}

function averageTokensPerPrompt(bucket) {
    const totalTokenCount = Number(bucket.total_token_count || 0);
    const promptCount = Number(bucket.prompt_count || 0);
    return promptCount ? totalTokenCount / promptCount : 0;
}
```

```javascript
function clearChart(chart) {
    if (chart) {
        chart.destroy();
    }
    return null;
}

function renderEmptyChart(ctx, chart) {
    const nextChart = clearChart(chart);
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.font = '14px DM Sans';
    ctx.fillStyle = '#6b7280';
    ctx.textAlign = 'center';
    ctx.fillText(userDetailMessages.timeline_empty, ctx.canvas.width / 2, ctx.canvas.height / 2);
    return nextChart;
}
```

```javascript
function renderAverageTimeline(timeline, windowValue) {
    const averageCtx = document.getElementById('average-timeline-chart').getContext('2d');
    averageTimelineChart = clearChart(averageTimelineChart);

    if (!timeline || timeline.length === 0) {
        averageTimelineChart = renderEmptyChart(averageCtx, averageTimelineChart);
        return;
    }

    const isToday = windowValue === 'today';
    const labels = timeline.map(bucket => formatTimelineLabel(bucket.time_bucket, isToday));
    averageTimelineChart = new Chart(averageCtx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: userDetailMessages.avg_tokens_per_project,
                    data: timeline.map(bucket => averageTokensPerProject(bucket)),
                    borderColor: '#0f766e',
                    backgroundColor: 'rgba(15, 118, 110, 0.18)',
                },
                {
                    label: userDetailMessages.avg_tokens_per_prompt,
                    data: timeline.map(bucket => averageTokensPerPrompt(bucket)),
                    borderColor: '#b45309',
                    backgroundColor: 'rgba(180, 83, 9, 0.18)',
                },
            ],
        },
    });
}
```

```javascript
function refreshUserDetail(windowValue) {
    ...
    fetch(buildRefreshUrl(`/api/users/${userId}/timeline`, windowValue, { granularity }))
        .then(r => r.json())
        .then(data => {
            if (requestId !== refreshRequestId) {
                return;
            }
            renderTimeline(data.timeline || [], windowValue);
            renderAverageTimeline(data.timeline || [], windowValue);
        });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest service/tests/test_token_league.py::test_user_detail_page_script_renders_average_timeline_from_timeline_buckets -v`
Expected: PASS

- [ ] **Step 5: Run broader user-detail regression coverage**

Run: `pytest service/tests/test_token_league.py -k "user_detail_page or user_timeline_api" -v`
Expected: PASS with the new average-timeline coverage plus existing user-detail timeline regressions still green.

- [ ] **Step 6: Commit**

```bash
git add service/tests/test_token_league.py service/templates/user_detail.html
git commit -m "feat: add user detail average timeline chart"
```
