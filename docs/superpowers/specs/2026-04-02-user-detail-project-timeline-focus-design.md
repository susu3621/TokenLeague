# User Detail Project Timeline Focus Design

## Goal

Change the user detail usage timeline so clicking a project in the chart legend focuses the timeline on that single project instead of hiding it.

## Current State

The usage timeline on `service/templates/user_detail.html` renders one stacked bar dataset per project with Chart.js. The chart uses the default legend click behavior, which toggles visibility for the clicked dataset. That means clicking a project hides that project and leaves the other projects visible.

## Design

### Interaction

- When no project is selected, the timeline shows all project datasets.
- Clicking a legend item selects that project and re-renders the chart so only the clicked project remains visible.
- Clicking the same legend item again clears the selection and restores all projects.
- Clicking a different legend item switches focus to the newly clicked project.

### State Model

The selected project is a client-side view state for the timeline only. It is not sent to the backend and it is not encoded into the page URL.

When the detail window changes and the page fetches new timeline data, the selected project resets so the refreshed chart starts in the default "show all projects" state.

### Backend

No API or database changes are needed. `/api/users/<id>/timeline` continues returning the existing full project breakdown for each time bucket.

### Rendering

The timeline rendering code should derive the visible datasets from two inputs:

- the fetched timeline buckets
- the optional selected project name

Legend click handling should use a custom Chart.js legend `onClick` handler instead of the default hide/show behavior.

## Testing

Add user-detail page coverage that asserts the rendered script includes:

- timeline state for the selected project
- dataset filtering based on the selected project
- custom legend click handling that toggles between focused and full-timeline views
