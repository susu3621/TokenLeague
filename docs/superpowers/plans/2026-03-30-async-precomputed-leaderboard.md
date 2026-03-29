# Async Precomputed Leaderboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/leaderboard` load instantly after login by serving a shell page with a loading state and asynchronously fetching a default all-time leaderboard snapshot that is refreshed once per hour.

**Architecture:** Add persistent leaderboard snapshot storage plus a small snapshot refresh module that computes the default all-time board in one batch. Change the leaderboard page to a shell-first async page and add a dedicated snapshot API. Run refresh logic in a separate worker loop so the Flask request path never performs full leaderboard aggregation.

**Tech Stack:** Flask, Jinja, Python, MySQL, pytest, Docker Compose

---

### Task 1: Add failing snapshot storage and refresh tests

**Files:**
- Modify: `service/tests/test_token_league.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write failing tests for snapshot persistence and refresh**

Add focused tests for:

```python
def test_default_leaderboard_snapshot_round_trip_in_memory():
    ...

def test_refresh_default_leaderboard_snapshot_builds_ranked_rows(monkeypatch):
    ...

def test_refresh_default_leaderboard_snapshot_keeps_previous_snapshot_on_failure(monkeypatch):
    ...
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest service/tests/test_token_league.py -k "snapshot_round_trip or refresh_default_leaderboard_snapshot" -q`
Expected: FAIL because snapshot storage and refresh helpers do not exist yet.

- [ ] **Step 3: Keep fixtures minimal**

Seed only enough prompt events, task runs, and users to prove:

- total token ranking
- task counts
- last active timestamps
- snapshot overwrite only on success

- [ ] **Step 4: Re-run the focused tests to confirm failures are meaningful**

Run: `pytest service/tests/test_token_league.py -k "snapshot_round_trip or refresh_default_leaderboard_snapshot" -q`
Expected: FAIL on missing functions or missing snapshot support, not fixture setup errors.

### Task 2: Implement snapshot storage and refresh logic

**Files:**
- Modify: `service/db.py`
- Create: `scripts/migrations/006_add_leaderboard_snapshots.py`
- Create: `scripts/refresh_leaderboard_snapshot.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Implement minimal snapshot storage helpers**

Add helpers in `service/db.py` such as:

```python
DEFAULT_LEADERBOARD_SNAPSHOT_KEY = "default_all_time"

def get_leaderboard_snapshot(snapshot_key: str = DEFAULT_LEADERBOARD_SNAPSHOT_KEY) -> dict[str, Any]: ...
def save_leaderboard_snapshot(snapshot_key: str, rows: list[dict[str, Any]], generated_at: datetime) -> dict[str, Any]: ...
```

Requirements:

- support in-memory test mode
- serialize and deserialize `rows_json`
- return `generated_at` in the same normalized UTC shape used elsewhere

- [ ] **Step 2: Implement the snapshot refresh module**

Create `scripts/refresh_leaderboard_snapshot.py` with focused helpers such as:

```python
def build_default_leaderboard_rows() -> list[dict[str, Any]]: ...
def refresh_default_leaderboard_snapshot() -> dict[str, Any]: ...
```

Requirements:

- batch-load raw events, task runs, and users once
- avoid per-event `get_user_by_id()` lookups
- compute ranks and averages in the final display shape
- write the snapshot only after successful computation

- [ ] **Step 3: Add the database migration**

Create `scripts/migrations/006_add_leaderboard_snapshots.py` that creates:

```sql
CREATE TABLE leaderboard_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    snapshot_key VARCHAR(128) NOT NULL UNIQUE,
    generated_at DATETIME NULL,
    rows_json JSON NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
)
```

Also update `scripts/migrations/001_init_schema.py` so fresh database bootstraps include the table.

- [ ] **Step 4: Run the focused snapshot tests to verify they pass**

Run: `pytest service/tests/test_token_league.py -k "snapshot_round_trip or refresh_default_leaderboard_snapshot" -q`
Expected: PASS

### Task 3: Add failing async leaderboard page and API tests

**Files:**
- Modify: `service/tests/test_token_league.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Write failing tests for the new page shell and API**

Add tests for:

```python
def test_default_leaderboard_api_returns_snapshot(auth_session):
    ...

def test_default_leaderboard_api_returns_empty_payload_without_snapshot(auth_session):
    ...

def test_leaderboard_page_renders_loading_shell(auth_session):
    ...
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest service/tests/test_token_league.py -k "default_leaderboard_api or leaderboard_page_renders_loading_shell" -q`
Expected: FAIL because the new API and async page behavior do not exist yet.

- [ ] **Step 3: Make the assertions explicit**

Check for:

- `Loading leaderboard...`
- a container marker for async rows
- JavaScript fetch of `/api/leaderboard/default`
- empty-success API payload when no snapshot exists

- [ ] **Step 4: Re-run the focused tests to confirm the failure mode**

Run: `pytest service/tests/test_token_league.py -k "default_leaderboard_api or leaderboard_page_renders_loading_shell" -q`
Expected: FAIL on missing endpoint or missing page shell markup.

### Task 4: Implement async page and snapshot API

**Files:**
- Modify: `service/app.py`
- Modify: `service/templates/leaderboard.html`
- Modify: `service/tests/test_token_league.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Add the snapshot API route**

Add `GET /api/leaderboard/default` that:

- requires login
- loads the stored snapshot
- returns `{success, snapshot_key, generated_at, rows}`

- [ ] **Step 2: Convert `/leaderboard` into a shell-first page**

Render:

- page title and description
- loading message
- last-updated placeholder
- tbody marker for client-rendered rows

Do not pass computed `rows` from the route.

- [ ] **Step 3: Add minimal browser-side rendering**

Implement script behavior in `service/templates/leaderboard.html` to:

- fetch `/api/leaderboard/default`
- render rows into the table body
- render empty-state and error-state text
- render `Last updated`
- escape dynamic text before `innerHTML`

- [ ] **Step 4: Run the focused API/page tests to verify they pass**

Run: `pytest service/tests/test_token_league.py -k "default_leaderboard_api or leaderboard_page_renders_loading_shell" -q`
Expected: PASS

### Task 5: Add failing worker-loop tests and implement hourly refresh runner

**Files:**
- Modify: `service/tests/test_token_league.py`
- Create: `scripts/run_leaderboard_snapshot_worker.py`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Add one focused worker-loop test**

Add a test for a small loop helper, for example:

```python
def test_worker_loop_runs_immediate_refresh_before_sleep(monkeypatch):
    ...
```

- [ ] **Step 2: Run the worker-focused test to verify it fails**

Run: `pytest service/tests/test_token_league.py -k "worker_loop_runs_immediate_refresh_before_sleep" -q`
Expected: FAIL because the worker runner does not exist yet.

- [ ] **Step 3: Implement the worker runner**

Create `scripts/run_leaderboard_snapshot_worker.py` with:

```python
def run_forever(refresh_func=refresh_default_leaderboard_snapshot, sleep_func=time.sleep, interval_seconds=3600): ...
```

Requirements:

- perform one refresh immediately on startup
- sleep for 3600 seconds between subsequent refreshes
- print simple success/failure logs
- keep the loop isolated so tests can inject fake sleep and refresh functions

- [ ] **Step 4: Wire the worker into deployment**

Update `docker-compose.yml` with a `worker` service that:

- uses the same image/build as `web`
- loads the same `.env`
- runs migrations then starts the worker loop

Document the new worker behavior in `README.md`.

- [ ] **Step 5: Run the worker-focused test to verify it passes**

Run: `pytest service/tests/test_token_league.py -k "worker_loop_runs_immediate_refresh_before_sleep" -q`
Expected: PASS

### Task 6: Run end-to-end verification and review scope

**Files:**
- Modify: `service/tests/test_token_league.py`
- Modify: `service/tests/test_auth_flow.py`
- Test: `service/tests/test_token_league.py`
- Test: `service/tests/test_auth_flow.py`

- [ ] **Step 1: Add one auth regression assertion if needed**

Ensure login still redirects to `/leaderboard` and the page stays accessible immediately after login.

- [ ] **Step 2: Run the full focused test set**

Run: `pytest service/tests/test_token_league.py service/tests/test_auth_flow.py -q`
Expected: PASS

- [ ] **Step 3: Review the diff for scope control**

Run: `git diff -- . ':!docs/superpowers'`
Expected: Only snapshot storage, refresh scripts, async leaderboard UI, tests, deployment wiring, and matching docs changes appear.

- [ ] **Step 4: Run a manual snapshot refresh once**

Run: `python3 scripts/refresh_leaderboard_snapshot.py`
Expected: success log indicating the default snapshot was refreshed.
