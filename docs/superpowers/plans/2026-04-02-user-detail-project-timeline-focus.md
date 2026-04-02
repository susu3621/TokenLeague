# User Detail Project Timeline Focus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make legend clicks on the user-detail usage timeline focus a single project and let a second click restore all projects.

**Architecture:** Keep the change entirely inside the existing user-detail template script. Store a `selectedTimelineProject` client-side state value, filter timeline datasets from that state during chart rendering, and replace Chart.js default legend toggling with a custom click handler.

**Tech Stack:** Flask templates, inline browser JavaScript, Chart.js, pytest

---

### Task 1: Add regression coverage for focused legend behavior

**Files:**
- Modify: `service/tests/test_token_league.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write the failing test**

```python
def test_user_detail_page_script_supports_single_project_timeline_focus(auth_session):
    response = auth_session.get("/users/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "let selectedTimelineProject = null;" in html
    assert "function getVisibleProjectNames(timeline)" in html
    assert "return selectedTimelineProject ? [selectedTimelineProject] : getProjectNames(timeline);" in html
    assert "const clickedProject = legendItem.text;" in html
    assert "selectedTimelineProject = selectedTimelineProject === clickedProject ? null : clickedProject;" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest service/tests/test_token_league.py::test_user_detail_page_script_supports_single_project_timeline_focus -v`
Expected: FAIL because the current template does not define focused-project timeline state or a custom legend click handler.

- [ ] **Step 3: Write minimal implementation**

```javascript
let selectedTimelineProject = null;

function getVisibleProjectNames(timeline) {
    const allProjects = getProjectNames(timeline);
    return selectedTimelineProject ? [selectedTimelineProject] : allProjects;
}

function buildTimelineDatasets(timeline) {
    return getVisibleProjectNames(timeline).map(projectName => {
        // existing dataset building
    });
}

legend: {
    position: 'bottom',
    onClick: (_event, legendItem) => {
        const clickedProject = legendItem.text;
        selectedTimelineProject = selectedTimelineProject === clickedProject ? null : clickedProject;
        renderTimeline(latestTimeline, currentWindow);
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest service/tests/test_token_league.py::test_user_detail_page_script_supports_single_project_timeline_focus -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/tests/test_token_league.py service/templates/user_detail.html
git commit -m "feat: focus user detail timeline by project"
```

### Task 2: Implement focused timeline rendering safely

**Files:**
- Modify: `service/templates/user_detail.html`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Extend timeline state with the latest fetched data**

```javascript
let latestTimeline = [];
let selectedTimelineProject = null;
```

- [ ] **Step 2: Reset focused project state when fresh timeline data arrives**

```javascript
function renderTimeline(timeline, windowValue) {
    latestTimeline = timeline || [];
    selectedTimelineProject = null;
    const datasets = buildTimelineDatasets(latestTimeline);
}
```

- [ ] **Step 3: Preserve focused rendering during legend-triggered rerenders**

```javascript
function updateTimelineProjectFocus(projectName) {
    selectedTimelineProject = selectedTimelineProject === projectName ? null : projectName;
    drawTimeline(latestTimeline, currentWindow);
}
```

- [ ] **Step 4: Use custom legend click behavior instead of default dataset hiding**

```javascript
legend: {
    position: 'bottom',
    onClick: (_event, legendItem) => {
        updateTimelineProjectFocus(legendItem.text);
    }
}
```

- [ ] **Step 5: Run focused tests**

Run: `pytest service/tests/test_token_league.py::test_user_detail_page_script_supports_single_project_timeline_focus -v`
Expected: PASS

- [ ] **Step 6: Run broader user-detail regression coverage**

Run: `pytest service/tests/test_token_league.py -k "user_detail_page" -v`
Expected: PASS for user detail page script and rendering tests

- [ ] **Step 7: Commit**

```bash
git add service/tests/test_token_league.py service/templates/user_detail.html
git commit -m "fix: focus user detail timeline on selected project"
```
