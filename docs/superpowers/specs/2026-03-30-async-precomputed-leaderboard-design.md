# Async Precomputed Leaderboard Design

## Goal

Make login feel instant by removing synchronous leaderboard computation from the post-login request path. The `/leaderboard` page should render immediately with a loading state, then asynchronously load a precomputed default leaderboard snapshot that is refreshed once per hour.

## Current State

Normal non-LDAP login already does a small amount of work: local password verification and session creation. The slow part happens after the redirect to `/leaderboard`.

`/leaderboard` currently calls `db.get_leaderboard(window=..., filters=...)` during server-side rendering. That path loads the full `prompt_events` and `task_runs` tables into Python, then walks all prompt events and calls `get_user_by_id()` per event. On larger datasets this makes the first authenticated page load expensive enough that users perceive login itself as slow.

The repository already has one precedent for async page refresh behavior: the user detail page renders a lightweight shell and then refreshes sections from browser-side JavaScript. The repository also already has a precedent for background periodic work via a separate timer-driven collector path.

## Requirements

1. Login should remain synchronous only for authentication and session creation.
2. `/leaderboard` should render fast even when the historical event tables are large.
3. The page should visibly show `Loading leaderboard...` before data arrives.
4. The default leaderboard may be stale by up to one hour.
5. The initial scope only needs the default all-time leaderboard. Existing realtime filter behavior does not need to be preserved on the landing page.

## Design

### Route Model

Keep the existing login redirect target:

- `POST /login` -> `302 /leaderboard`

Change `/leaderboard` from a server-rendered data page into a shell-first page:

- render the page chrome, title, description, and empty table container on the server
- render a visible loading message immediately
- do not calculate leaderboard rows during the request
- fetch leaderboard data from a dedicated snapshot API after the page loads

Add a dedicated snapshot API:

- `GET /api/leaderboard/default`

This API returns the most recent successful default leaderboard snapshot and its generation time.

### Data Model

Add a new database table for precomputed leaderboard snapshots:

- `leaderboard_snapshots`

Fields:

- `snapshot_key` unique identifier, initially only `default_all_time`
- `generated_at` UTC timestamp for the data represented by the snapshot
- `rows_json` serialized leaderboard rows in display-ready shape
- `created_at`
- `updated_at`

The initial scope stores one snapshot row only. This keeps the schema simple and leaves room to add future variants like filtered or windowed snapshots without redesigning the API contract.

For in-memory test mode, add an equivalent in-memory snapshot store so tests do not need a live database.

### Snapshot Contents

`rows_json` should store the fields already used by the leaderboard UI:

- `rank`
- `user_id`
- `username`
- `display_name`
- `total_token_count`
- `prompt_count`
- `task_count`
- `total_duration_ms`
- `last_active_at`
- `avg_token_per_prompt`

The snapshot should be the final display model, not an intermediate aggregation format. That keeps the API read path very cheap and avoids repeating sorting or ranking logic on page requests.

### Snapshot Refresh Flow

Add a dedicated refresh script, for example:

- `scripts/refresh_leaderboard_snapshot.py`

Responsibilities:

1. load the current raw leaderboard source data
2. compute the default all-time leaderboard in one batch
3. write the resulting rows as the new `default_all_time` snapshot
4. only replace the stored snapshot after a full successful computation

Failure handling:

- if refresh fails, leave the previous snapshot untouched
- log the error and exit non-zero
- the UI continues serving the last successful snapshot

The computation itself should not reuse the current N+1 user lookup pattern. It should load users once, aggregate in memory once, and then write the finished snapshot.

### Background Execution

Run snapshot refresh outside the request-serving Flask process.

Recommended deployment shape:

- add a separate `worker` service in `docker-compose.yml`
- worker command runs migrations, performs one immediate refresh at startup, then refreshes every hour

This keeps the web process simple and makes refresh behavior independent from traffic volume. It also avoids the fragile behavior of process-local caches in multi-container or restarted deployments.

For local development, the refresh script should still be runnable manually.

### Frontend Behavior

`service/templates/leaderboard.html` should adopt the same broad pattern already used by `user_detail.html`:

- render static shell content on the server
- include a loading region such as `Loading leaderboard...`
- include browser-side JavaScript that fetches `/api/leaderboard/default`
- replace the loading region with table rows after the response arrives
- render the snapshot generation time, for example `Last updated: 2026-03-30 12:00 UTC`

States:

- loading: show loading text and placeholder body
- success with rows: render rows
- success with no snapshot yet: show `Leaderboard is being prepared`
- request failure: show `Failed to load leaderboard`

The initial scope keeps the existing filter controls out of the async landing path. The page may keep simple copy that this is the default leaderboard snapshot.

### API Contract

`GET /api/leaderboard/default`

Success shape:

```json
{
  "success": true,
  "snapshot_key": "default_all_time",
  "generated_at": "2026-03-30T12:00:00+00:00",
  "rows": [
    {
      "rank": 1,
      "user_id": 2,
      "username": "alice",
      "display_name": "Alice",
      "total_token_count": 190,
      "prompt_count": 2,
      "task_count": 1,
      "total_duration_ms": 24000,
      "last_active_at": "2026-03-30T11:40:00+00:00",
      "avg_token_per_prompt": 95.0
    }
  ]
}
```

No snapshot yet:

```json
{
  "success": true,
  "snapshot_key": "default_all_time",
  "generated_at": null,
  "rows": []
}
```

This endpoint is read-only and authenticated like the current leaderboard APIs.

## Testing

Add coverage for:

- `/leaderboard` rendering a loading container and async refresh script instead of server-rendered rows
- `/api/leaderboard/default` returning the latest stored snapshot
- `/api/leaderboard/default` returning an empty success payload when no snapshot exists
- snapshot refresh logic generating correct order, rank, totals, and timestamps
- snapshot refresh preserving the previous stored snapshot when recomputation fails
- in-memory store support for snapshot reads and writes

## Non-Goals

- realtime leaderboard recomputation on page load
- filtered snapshot variants
- windowed snapshot variants
- replacing existing `/api/leaderboard` realtime behavior for non-landing-page use cases
