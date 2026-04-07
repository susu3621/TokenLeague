# User Detail Prompt Average Trend Design

## Context

The user detail page currently renders an "Average Trends" section with two lines:

- average tokens per project
- average tokens per prompt

The requested behavior narrows this section to only the prompt average trend and replaces the vague section heading with wording that directly describes the chart's meaning.

## Approved Behavior

- Remove the "average tokens per project" line from the user detail average chart.
- Keep only the "average tokens per prompt" line.
- Rename the chart section heading to describe the remaining line directly.
- Update English and Chinese copy consistently.
- Keep existing timeline window switching and project-focus behavior so the remaining prompt-average line still updates from the selected project when applicable.

## Design

### UI copy

- English heading: `Avg Tokens / Prompt Trend`
- Chinese heading: `每次 Prompt 平均 Token 趋势`

The dataset label remains the existing prompt-average wording because it is already direct and specific.

### Frontend behavior

- Replace the multi-series average chart implementation with a single-series prompt-average trend renderer.
- Remove the per-project average helper from the page script.
- Preserve project-scoped prompt-average calculation by reusing the selected project's total token count and prompt count in each bucket.

### Testing

- Update page-render tests to assert the new heading text.
- Update script-render tests to assert the prompt-average-only renderer and removal of per-project-average references.
