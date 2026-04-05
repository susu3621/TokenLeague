# Project Timeline And README Refresh Design

## Goal

Implement two related improvements:

- let a user inspect average tokens per prompt and prompt-count trends for one selected project from the existing user detail page
- rewrite the project documentation so `README.md` becomes a complete English guide and `README_CN.md` becomes a complete Chinese guide, covering features, installation, hook setup, and deployment

## Current State

### User detail timeline

`service/templates/user_detail.html` already renders three timeline-driven views:

- stacked usage timeline by project
- average tokens per active project
- prompt count timeline

The page already supports a legend-driven project focus state for the stacked usage chart, but the other two charts always show user-wide aggregates derived from the full bucket totals. The project table is currently read-only and does not participate in timeline selection.

The backing API, `/api/users/<int:user_id>/timeline`, returns one bucket per time slice with:

- total token counts
- prompt count
- `project_breakdown` entries containing `project_name` and `total_token_count`

That payload is enough to focus the stacked usage chart, but not enough to derive project-specific averages or project-specific prompt counts.

### Project documentation

`README.md` is a mixed Chinese/English overview with partial setup instructions. It does not clearly separate local Python setup from Docker Compose setup, does not describe the authenticated pages and ingestion flow in a structured way, and there is no dedicated `README_CN.md`.

## Design

### User detail interaction

- Keep `/users/<int:user_id>` as the only entry point. No new project page is introduced.
- The project table becomes the control for timeline focus.
- Default state remains "all projects".
- Clicking a project row selects that project and updates:
  - the stacked usage timeline
  - the average timeline
  - the prompt count timeline
- Clicking the already-selected row clears the selection and restores the full user-wide view.
- The selected project is client-side state only. It is not encoded in the URL and is reset when a new time window is fetched.

### Timeline data contract

Extend each `project_breakdown` item in `/api/users/<int:user_id>/timeline` to include:

- `project_name`
- `total_token_count`
- `prompt_count`

The bucket-level `prompt_count` remains the user-wide total for that bucket. The per-project `prompt_count` enables the browser to compute:

- selected-project average tokens per prompt
- selected-project prompt count per time bucket

No new endpoint is needed. The existing timeline API remains the source of truth for all three charts.

### Frontend state model

Add one shared selection state in `service/templates/user_detail.html`:

- `selectedTimelineProject = null | project_name`

Behavior:

- stacked usage timeline keeps the existing focused-project rendering behavior
- average timeline derives its values from the selected project when a project is selected; otherwise it keeps the existing user-wide values
- prompt count timeline renders the selected project's prompt counts when a project is selected; otherwise it keeps the existing bucket prompt counts
- project table row styling reflects the current selection so the active filter is visible without reading the chart legend

### Metric definitions

For a selected project within one time bucket:

- `selected_project_total_tokens = matching project_breakdown.total_token_count or 0`
- `selected_project_prompt_count = matching project_breakdown.prompt_count or 0`
- `selected_project_avg_tokens_per_prompt = selected_project_total_tokens / selected_project_prompt_count` when prompt count is non-zero, else `0`

When no project is selected:

- average tokens per project stays `bucket.total_token_count / len(bucket.project_breakdown)`
- average tokens per prompt stays `bucket.total_token_count / bucket.prompt_count`
- prompt count timeline stays `bucket.prompt_count`

No separate "average tokens per project" metric is introduced for the selected-project state. The existing chart keeps two lines and simply changes its data source based on the active project filter:

- full view: `Avg Tokens / Project` and `Avg Tokens / Prompt`
- selected-project view: `Avg Tokens / Prompt` for that project, while the project-average line becomes that selected project's token total for the bucket because there is exactly one active project in focus

This preserves the current chart structure without adding a fourth chart or a second filter model.

### Documentation refresh

Create two top-level guides:

- `README.md` in English
- `README_CN.md` in Simplified Chinese

Both guides should cover the same product surface:

- what TokenLeague does
- supported agent collectors and ingestion sources
- core UI surfaces and metrics
- local Python setup
- Docker Compose setup, clearly marked as the recommended deployment path
- environment variables
- hook installation and uninstall flow
- backfill workflow
- testing and development notes

The English and Chinese guides should be parallel documents, not line-by-line bilingual mixing inside one file.

## Error Handling

### Timeline selection

- If a selected project does not exist in the newly fetched window, the page falls back to the all-project view.
- Empty timeline buckets still render as zeroes.
- Empty project tables do not leave a stale selection behind.

### Documentation

- Avoid version-specific claims not supported by the repository.
- Prefer commands that match the checked-in project structure, including `service/tests` verification and current Docker Compose assets.

## Testing

Add or update tests to cover:

- timeline API buckets include per-project `prompt_count`
- filters and windows continue to work with the expanded bucket schema
- user-detail template script includes project-table click handling and selection-aware average/prompt-count calculations
- English and Chinese rendering still expose the expected timeline labels
- README and `README_CN.md` both exist and describe local and Docker Compose installation paths
