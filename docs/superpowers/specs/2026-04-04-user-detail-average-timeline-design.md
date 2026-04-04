# User Detail Average Timeline Design

## Goal

Add a new chart to the user detail page that shows two time curves:

- average tokens per active project
- average tokens per prompt

The new chart should follow the same selected time window and filters as the existing user-detail sections.

## Current State

`service/templates/user_detail.html` currently renders one timeline chart: a stacked bar chart built from `/api/users/<id>/timeline`.

Each returned time bucket already contains the data needed for the requested averages:

- `total_token_count`
- `prompt_count`
- `project_breakdown`

The page also already refreshes the timeline, summary cards, model breakdown, project breakdown, and recent prompt events together when the user switches the detail window.

## Design

### Interaction

- Keep the existing stacked project timeline unchanged.
- Add one new chart below the existing usage timeline in the same card.
- The new chart renders two line datasets:
  - `Avg Tokens / Project`
  - `Avg Tokens / Prompt`
- The new chart does not add its own controls. It reuses the existing window selector and current URL filters.
- The new dataset labels should use the existing i18n pattern so English and Chinese user-detail pages render localized legend text.

### Metric Definitions

For each time bucket in `/api/users/<id>/timeline`:

- `avg_tokens_per_project = total_token_count / active_project_count`
- `active_project_count = len(project_breakdown)`
- `avg_tokens_per_prompt = total_token_count / prompt_count`

Zero-handling:

- if `active_project_count` is `0`, `avg_tokens_per_project` is `0`
- if `prompt_count` is `0`, `avg_tokens_per_prompt` is `0`

An "active project" means a project that appears in that bucket's `project_breakdown`, which matches the user-approved metric definition.

### Data Flow

No backend or database changes are needed.

The existing timeline API remains the source of truth. The browser derives the two average series from the fetched `timeline` array during rendering.

This keeps the metric aligned with the same windowing, granularity, and filter behavior already used by the existing timeline chart.

### Rendering

- Reuse the same x-axis labels as the usage timeline.
- Render the new chart as a non-stacked line chart.
- Use compact token formatting on y-axis ticks and tooltips, matching the existing page formatting style.
- Keep the empty-state behavior consistent with the current timeline implementation:
  - if the fetched timeline array is empty, show the existing timeline-empty message
  - if the fetched timeline contains zero-value buckets, still render the line chart with zeroes

### State Model

- The current `latestTimeline` client-side state remains the shared source for timeline-derived rendering.
- The existing project-focus state only applies to the stacked usage timeline.
- The new average chart always reflects the full fetched timeline buckets and does not participate in project legend focus behavior.

This prevents the "average per project" curve from changing when a user focuses one project in the stacked chart legend.

## Testing

Add user-detail page coverage that asserts the rendered script includes:

- a second timeline canvas for the average chart
- client-side helpers that derive average-per-project and average-per-prompt values from timeline buckets
- chart creation for a line chart with two datasets
- timeline refresh logic that redraws the new chart from the same fetched timeline payload

Run targeted user-detail page tests after the template change.
