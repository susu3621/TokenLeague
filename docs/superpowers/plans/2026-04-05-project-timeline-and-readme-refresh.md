# Project Timeline And README Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add project-selectable timeline averages and prompt counts on the user detail page, then replace the mixed README with complete English and Chinese guides.

**Architecture:** Reuse the existing `/api/users/<id>/timeline` endpoint by expanding each bucket's `project_breakdown` rows with per-project prompt counts. Keep the project selection entirely client-side in `service/templates/user_detail.html`, driven from the project breakdown table. Rewrite the top-level documentation as two parallel guides, one English and one Chinese.

**Tech Stack:** Flask, Jinja, in-memory/test DB helpers, Chart.js, pytest

---

### Task 1: Extend timeline buckets with per-project prompt counts

**Files:**
- Modify: `service/db.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write the failing API tests**

```python
def test_user_detail_timeline_includes_project_prompt_counts(auth_session, monkeypatch):
    _seed_user_detail_filter_data(monkeypatch)

    response = auth_session.get("/api/users/1/timeline?window=month&granularity=day")

    assert response.status_code == 200
    buckets = {
        bucket["time_bucket"]: bucket
        for bucket in response.get_json()["timeline"]
        if bucket["total_token_count"] > 0
    }
    assert buckets["2026-03-24"]["project_breakdown"] == [
        {"project_name": "TokenLeague", "total_token_count": 30, "prompt_count": 1},
    ]
```

- [ ] **Step 2: Run the targeted test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py -k "project_prompt_counts"`

Expected: FAIL because `project_breakdown` items do not yet include `prompt_count`.

- [ ] **Step 3: Implement the minimal bucket aggregation change**

```python
project_totals = group["_project_totals"]
project_state = project_totals.setdefault(
    project_name,
    {"total_token_count": 0, "prompt_count": 0},
)
project_state["total_token_count"] += event["total_token_count"]
project_state["prompt_count"] += 1
```

and later:

```python
item["project_breakdown"] = [
    {
        "project_name": project_name,
        "total_token_count": project_state["total_token_count"],
        "prompt_count": project_state["prompt_count"],
    }
    for project_name, project_state in ...
]
```

- [ ] **Step 4: Run the targeted API tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py -k "timeline and project"`

Expected: PASS for the new bucket-shape assertions and the existing filter/window timeline tests.

- [ ] **Step 5: Commit**

```bash
git add service/db.py service/tests/test_token_league.py
git commit -m "feat: add project prompt counts to timeline buckets"
```

### Task 2: Make project table clicks drive all timeline charts

**Files:**
- Modify: `service/templates/user_detail.html`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write the failing template tests**

```python
def test_user_detail_page_script_updates_all_timelines_from_project_table_click(auth_session):
    response = auth_session.get("/users/1")

    html = response.get_data(as_text=True)
    assert "function averageTokensPerPrompt(bucket, projectName = null)" in html
    assert "function promptCountForProject(bucket, projectName)" in html
    assert "tbody.querySelectorAll('tr[data-project-name]')" in html
    assert "renderAverageTimeline(data.timeline || [], windowValue, selectedTimelineProject);" in html
    assert "renderPromptCountTimeline(data.timeline || [], windowValue, selectedTimelineProject);" in html
```

- [ ] **Step 2: Run the targeted template tests to verify they fail**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py -k "project_table_click or prompt_count_timeline"`

Expected: FAIL because the current script does not bind project-table clicks to the average/prompt-count charts.

- [ ] **Step 3: Implement minimal client-side selection logic**

```javascript
function promptCountForProject(bucket, projectName) {
  const row = (bucket.project_breakdown || []).find(project => project.project_name === projectName);
  return row ? Number(row.prompt_count || 0) : 0;
}

function averageTokensPerPrompt(bucket, projectName = null) {
  if (!projectName) {
    const totalTokenCount = Number(bucket.total_token_count || 0);
    const promptCount = Number(bucket.prompt_count || 0);
    return promptCount ? totalTokenCount / promptCount : 0;
  }
  const totalTokenCount = tokenCountForProject(bucket, projectName);
  const promptCount = promptCountForProject(bucket, projectName);
  return promptCount ? totalTokenCount / promptCount : 0;
}
```

and bind clickable rows:

```javascript
<tr data-project-name="${escapeHtml(project.project_name)}" class="${rowClass}">
```

```javascript
tbody.querySelectorAll('tr[data-project-name]').forEach(row => {
  row.addEventListener('click', () => updateTimelineProjectFocus(row.dataset.projectName));
});
```

- [ ] **Step 4: Run the targeted template tests to verify they pass**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py -k "average_timeline or prompt_count_timeline or project_table_click"`

Expected: PASS for the new script assertions and the existing user-detail chart assertions.

- [ ] **Step 5: Commit**

```bash
git add service/templates/user_detail.html service/tests/test_token_league.py
git commit -m "feat: add project-selected user detail timelines"
```

### Task 3: Replace the mixed README with English and Chinese guides

**Files:**
- Modify: `README.md`
- Create: `README_CN.md`
- Test: `service/tests/test_deploy_assets.py`

- [ ] **Step 1: Write the failing documentation test**

```python
def test_top_level_readmes_cover_local_and_docker_installation():
    readme_en = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_cn = (PROJECT_ROOT / "README_CN.md").read_text(encoding="utf-8")

    assert "Docker Compose" in readme_en
    assert "Local Python Setup" in readme_en
    assert "Docker Compose 部署" in readme_cn
    assert "本地 Python 运行" in readme_cn
```

- [ ] **Step 2: Run the targeted docs test to verify it fails**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_deploy_assets.py -k "readme"`

Expected: FAIL because `README_CN.md` does not exist and the current README is incomplete.

- [ ] **Step 3: Rewrite the guides**

```text
README.md
- Overview
- Features
- Architecture / ingestion flow
- Quick start with Docker Compose (recommended)
- Local Python setup
- Environment variables
- Hook install / uninstall
- Backfill
- Tests and development

README_CN.md
- 与 README.md 对齐的中文版本
```

- [ ] **Step 4: Run the targeted docs test to verify it passes**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_deploy_assets.py -k "readme"`

Expected: PASS with both README files present and containing both setup paths.

- [ ] **Step 5: Commit**

```bash
git add README.md README_CN.md service/tests/test_deploy_assets.py
git commit -m "docs: refresh setup guides in English and Chinese"
```

### Task 4: Final regression verification

**Files:**
- Verify only

- [ ] **Step 1: Run focused user-detail regression coverage**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py`

Expected: PASS with the expanded timeline payload and selection-aware chart script.

- [ ] **Step 2: Run the full service test suite**

Run: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests`

Expected: PASS with zero failures.

- [ ] **Step 3: Inspect git status**

Run: `git status --short`

Expected: clean working tree before push.

- [ ] **Step 4: Push and prepare GitHub merge**

```bash
git push -u origin feature/project-timeline-docs
gh pr create --base main --head feature/project-timeline-docs --title "feat: add project timeline filters and refresh docs"
```
