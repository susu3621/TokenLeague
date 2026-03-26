# User Detail Unified Window Design

## Goal

Make the `today`, `week`, and `month` window selector on the user detail page apply to all detail sections, not just the usage timeline.

## Current State

The user detail page in `service/templates/user_detail.html` renders summary cards, `Agent Breakdown`, and `Recent Prompt Events` from the server-rendered `/users/<id>` response. It separately fetches `/api/users/<id>/projects`, `/api/users/<id>/models`, and `/api/users/<id>/timeline` from the browser.

The existing `today / 过去7天 / 过去30天` buttons only control the timeline chart. `Project Breakdown` and `Model Breakdown` still use the page-level `window` query parameter. `Agent Breakdown`, `Recent Prompt Events`, and the summary cards do not react to the timeline buttons at all.

## Design

### Window Model

The user detail page gets a single detail window value shared by all sections on the page.

Supported values:

- `today`
- `week`
- `month`
- `all`

The page should default to `week` when no explicit window is provided. The selector continues to expose `today`, `week`, and `month`. `all` remains supported as a valid deep-link or API window, even if it is not exposed by the selector.

For compatibility with existing leaderboard links, user detail requests that arrive with `window=day` should be treated as `today`.

This unified window only applies to the user detail page. It does not change leaderboard or other page window behavior.

### Backend Behavior

The user detail page and supporting APIs should all filter data with the same window semantics:

- `today`: records whose event time falls between UTC midnight and now
- `week`: records in the trailing 7-day window, inclusive of today
- `month`: records in the trailing 30-day window, inclusive of today
- `all`: current unbounded behavior

Endpoint contract:

| Route | Accepted windows | Default | Legacy alias |
|-------|------------------|---------|--------------|
| `/users/<id>` | `today`, `week`, `month`, `all` | `week` | `day` -> `today` |
| `/api/users/<id>/stats` | `today`, `week`, `month`, `all` | `week` | `day` -> `today` |
| `/api/users/<id>/projects` | `today`, `week`, `month`, `all` | `week` | `day` -> `today` |
| `/api/users/<id>/models` | `today`, `week`, `month`, `all` | `week` | `day` -> `today` |
| `/api/users/<id>/timeline` | `today`, `week`, `month`, `all` | `week` | `day` -> `today` |

The following user-detail data sources should honor the same window:

- `/users/<id>` server-rendered stats payload
- `/api/users/<id>/stats`
- `/api/users/<id>/projects`
- `/api/users/<id>/models`
- `/api/users/<id>/timeline`

`timeline` keeps its current granularity rules:

- `today` uses hourly buckets
- `week` and `month` use daily buckets
- `all` can keep the existing fallback behavior if requested directly

### Frontend Behavior

The selector becomes the page-level detail window control.

On initial load, the page should render the active selector state from the current detail window. When the user clicks a selector button, the page should refresh all user-detail sections against the same window:

- summary cards
- `Usage Timeline`
- `Project Breakdown`
- `Model Breakdown`
- `Agent Breakdown`
- `Recent Prompt Events`

The page should reuse the existing section structure and empty-state text. This change should not require a full page navigation; the current page should update in place by requesting refreshed data from the existing APIs.

For first paint, `/users/<id>` should continue rendering the current window's summary cards, agent breakdown, and recent prompt events on the server. Frontend refresh logic augments that initial render instead of replacing the page with a shell-first hydration flow.

If the page is loaded with `window=all`, no selector button is active and all sections should render unbounded data until the user picks one of the visible selector windows.

When the user changes the selector, the browser URL should be updated in place with the selected `window` query parameter so the current state remains shareable without triggering a full reload.

### Rendering Updates

`Project Breakdown` and `Model Breakdown` should stop reading from the initial page-level `window` variable and instead use the current detail window.

`Agent Breakdown`, `Recent Prompt Events`, and the summary cards should move from static server-rendered values to DOM regions that can be refreshed from the window-aware stats payload. The model chart should also re-render when the window changes.

### Error Handling

If a section returns no data for the selected window, it should show the existing empty-state copy for that section. A single empty section should not block other sections from rendering refreshed data.

## Testing

Add coverage for:

- user stats, project breakdown, and model breakdown honoring `today`, `week`, and `month`
- the user detail page rendering a unified window selector state
- the user detail page script requesting refreshed stats, projects, models, and timeline data for the selected window
- the user detail page rendering refreshable containers for `Agent Breakdown` and `Recent Prompt Events`
