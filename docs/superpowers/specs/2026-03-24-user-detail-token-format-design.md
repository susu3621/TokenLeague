# User Detail Token Format Design

## Goal

Make token counts on the user detail page easier to scan by rendering them in compact human-readable form such as `K`, `M`, and `B`.

## Scope

This change is limited to the user detail page in `service/templates/user_detail.html`.

Apply compact token formatting to:

- summary cards for token values
- project breakdown token columns
- model breakdown token columns
- model chart axes and tooltips
- usage timeline axes and tooltips
- agent breakdown token column
- recent prompt event token column

Prompt counts and task counts stay as normal integers.

## Formatting Rules

- values below `1000` stay unscaled
- values at or above `1000` use `K`, `M`, or `B`
- keep at most one decimal place
- trim trailing `.0`

Examples:

- `950`
- `1.3K`
- `15K`
- `2.3M`
- `1B`

## Implementation

Use the same compact-formatting rules on both the server-rendered template values and the browser-rendered table/chart values so the page remains visually consistent.

## Testing

Add coverage for:

- compact formatter suffix behavior
- user detail page rendering compact token values
- user detail script exposing a shared client formatter for token fields
