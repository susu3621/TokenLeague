# User Timeline Range Design

## Goal

Change the user detail usage timeline from an hourly smoothed chart into a daily stacked bar chart with two explicit ranges: the past 7 days and the past 30 days.

## Current State

The user detail page in `service/templates/user_detail.html` always fetches `/api/users/<id>/timeline` with `window=<page window>` and `granularity=hour`. The chart is rendered with `tension: 0.3`, so the line is curved. The page-level `window` query parameter only supports `day`, `week`, and `all`.

## Design

### UI

The timeline card gets its own selector with two buttons:

- `过去7天`
- `过去30天`

The selector only affects the timeline card. Other summary cards on the page continue using the existing page `window`.

### API

The timeline endpoint accepts a timeline-specific window value and defaults to `week`. It should support:

- `week` for the past 7 days
- `month` for the past 30 days

The timeline chart will request `granularity=day`.

### Data Shape

The backend should continue returning the existing timeline totals, but daily timeline responses for `week` and `month` should also include `project_breakdown` per bucket and zero-filled buckets for missing dates so the chart reflects the full selected range.

### Rendering

The timeline chart becomes a Chart.js stacked `bar` chart:

- one bar per day
- one dataset per project
- deterministic colors derived from project name
- stacked `x` and `y` axes so each day shows the total split by project

## Testing

Add coverage for:

- `month` timeline API requests returning 30 daily buckets with per-project breakdown
- the user detail page rendering the 7-day / 30-day selector and stacked bar chart config
