# Account Access and I18n Design

## Goal

Restrict normal users to the minimum safe navigation and page set, add a dedicated self-service account area for API key and password management, and make both the application UI and Docs page switch between Chinese and English based on the browser language with English fallback.

## Scope

- Limit normal-user navigation to leaderboard, docs, account access, and logout.
- Add a dedicated account page for the current user to view and rotate their own API key and change their own password.
- Restrict normal users to their own user detail page and block access to admin/system pages by direct URL.
- Keep admin capabilities available for admin users.
- Add lightweight server-side i18n for template, route, and client-rendered UI text in Chinese and English.
- Add language-aware docs loading with Chinese-first lookup and English fallback.
- Add automated tests for permissions, account flows, i18n behavior, and docs fallback behavior.

Out of scope:

- User-configurable persisted language preferences.
- URL-based language routing such as `/zh/...` and `/en/...`.
- Role model changes beyond the existing `admin` and `user` distinction.
- Full API key lifecycle history or audit logs.
- A broad frontend rewrite or SPA-style client i18n framework.

## Existing Context

TokenLeague is a server-rendered Flask + Jinja application.

Today:

- `service/templates/base.html` renders a shared top navigation for all authenticated users.
- normal users currently see links they should not access, including `/settings` and `/api`.
- `service/templates/settings.html` mixes system-level settings with a full user list and is currently reachable by any authenticated user.
- `/users/<id>` is accessible to any logged-in user.
- application copy is mostly hard-coded in templates and some page scripts, with a mix of English and Chinese already present.
- `/docs` renders Markdown files from `docs/`, but has no language selection logic.
- user API keys already exist as `hook_key` on the `users` record, and password change already exists through `POST /api/change-password`.

The requested work fits the current server-rendered architecture. It does not require a new frontend stack or a generalized authorization framework.

## Requirements Confirmed During Brainstorming

- Normal users should only see `Leaderboard`, `Docs`, a username menu for account access, and `Logout`.
- The personal area is for the user's own API key and password management, not token usage statistics.
- Normal users may access only their own user detail page; they may not access other users' detail pages.
- Restricted pages must be blocked server-side, not merely hidden in navigation.
- UI language follows browser language only; no saved user preference is required.
- Docs must also support Chinese and English.
- If a Chinese docs variant is missing, the app must automatically fall back to the English source.
- Users may view, copy, and rotate their own API key.

## Design

### Access model

Keep the existing session-based login model and add explicit route-level authorization for three access classes:

- anonymous
- authenticated user
- admin user

Within authenticated users, distinguish between:

- self-only resources
- admin-only resources

This is enough for the requested scope and avoids introducing a new policy engine.

### Navigation model

#### Normal users

Authenticated normal users should see a compact top bar:

- `Leaderboard`
- `Docs`
- username menu
- `Logout`

The username menu is the only path to the account page. This preserves a minimal top-level navigation while still giving users a stable place to manage their own API key and password.

The username menu should not expose system or admin destinations.

#### Admin users

Admin users may continue to access system pages, but the navigation should still be structured clearly:

- `Leaderboard`
- `Docs`
- username menu
- admin/system links
- `Logout`

The admin path can keep existing destinations such as `/settings`, `/api`, `/admin/users`, `/admin/ldap`, and `/admin/agents`.

### Page model

#### Account page

Add a dedicated account page for the current session user, for example:

- `GET /account`

This page replaces `/settings` as the place for self-service user actions. It should include two sections.

API key section:

- show the current `hook_key`
- show `hook_key_created_at` if available
- offer copy UI
- offer a rotate action for the current user only

Password section:

- allow the current user to submit a new password
- reuse the current password-change behavior rather than creating a second independent password path

This page should not show global system settings, other users, or admin-only data.

#### User detail page

Keep the existing user detail route:

- `GET /users/<id>`

Behavior changes:

- admins may access any user detail page
- normal users may access only `/users/<session_user_id>`
- normal users requesting another user's detail page receive an authorization failure response rather than a hidden success path

This preserves the current detail page investment without exposing peer user data.

#### System settings page

Keep `/settings` as a system-level page, but make it admin-only.

This aligns the page content with its sensitivity because it currently contains application-wide settings and user information that normal users should not see.

### Authorization behavior

Add focused authorization helpers in `service/auth.py` or a nearby module instead of repeating role checks in routes.

Needed behavior:

- authenticated-only check
- admin-only check
- self-or-admin check for user-owned resources

Route rules:

- normal user allowed:
  - `/leaderboard`
  - `/docs`
  - `/docs/<path>`
  - `/account`
  - account APIs that act on the current user
  - `/users/<self_id>`
- normal user denied:
  - `/settings`
  - `/api` docs list page
  - `/admin/*`
  - `/users/<other_id>`
- admin allowed:
  - existing admin/system routes
  - any user detail page
  - account page for self-service actions

Failure behavior should be explicit and consistent:

- unauthenticated HTML requests redirect to `/login`
- authenticated but unauthorized HTML requests return `403`
- unauthenticated JSON requests return `401`
- authenticated but unauthorized JSON requests return `403`

This matches the user's requirement that restricted URLs are truly blocked rather than merely hidden in navigation.

### Account API design

Keep account mutations scoped to the current logged-in user. Do not accept arbitrary `user_id` values from the client.

Recommended endpoints:

- keep `POST /api/change-password` as a self-service password endpoint for the current session user
- add `POST /api/account/rotate-hook-key` for rotating the current session user's API key

Rules:

- endpoint requires login
- endpoint never rotates another user's key
- successful rotation returns the newly generated key and timestamp needed to refresh the page

Do not add a generic admin key-rotation API in this change. Admin management for other users already exists under `/admin/users`.

### Leaderboard behavior for normal users

The leaderboard remains visible to all authenticated users, but links from the leaderboard must respect self-only detail access.

Safe options:

- render a link only for the current user's own row and plain text for others
- or keep all links but rely on the server-side 403 path

Preferred behavior:

- avoid presenting links that normal users are not allowed to use
- still enforce the restriction server-side in case a URL is guessed or typed directly

This reduces confusing clicks while preserving the security boundary.

### Language detection

Use browser language detection on every request, based on `Accept-Language`.

Supported UI languages:

- `en`
- `zh-CN`

Normalization rules:

- any Chinese locale such as `zh`, `zh-CN`, or `zh-TW` resolves to the Chinese UI bucket in the first version
- all other locales fall back to English

Expose the resolved language through shared request/template context so templates, route handlers, and page scripts can use one consistent decision.

Also set the `<html lang>` attribute dynamically from this resolved language.

### UI translation strategy

Implement lightweight server-side translations rather than introducing a separate i18n framework.

Recommended structure:

- a translation dictionary keyed by stable message IDs
- a helper such as `t("nav.docs")`
- shared context injection so Jinja templates can call the helper directly

Coverage should include:

- shared shell navigation labels
- page titles and subtitles
- form labels, buttons, and status messages
- table headers and empty states
- route-level flash or inline messages
- client-rendered strings used by page scripts, especially in leaderboard and user-detail templates

For templates that render follow-up UI in JavaScript, pass only the small set of translated strings needed on that page as serialized JSON rather than duplicating translation logic in client code.

This keeps the implementation consistent with the existing Flask + Jinja pattern.

### Docs language resolution

Keep the current docs route shape:

- `/docs`
- `/docs/<path:filepath>`

Add language-aware file resolution without changing the public URL.

Given a requested logical document such as `README.md`:

- if the resolved UI language is Chinese, first look for `README.zh-CN.md`
- if that file exists, render it
- otherwise render `README.md`

The same rule applies to nested doc paths if they are added later:

- `guide/setup.md` -> try `guide/setup.zh-CN.md` first, then `guide/setup.md`

Sidebar behavior:

- sidebar entries should represent logical documents, not every physical language variant
- localized variants should not appear as duplicate entries
- title extraction should come from the actually rendered file so Chinese users see Chinese headings when a localized variant exists

Current root-level docs such as `README.md` and `HOOKS.md` should therefore support optional companion files:

- `README.zh-CN.md`
- `HOOKS.zh-CN.md`

### Docs listing strategy

Adjust docs listing so it groups localized variants under one logical document.

For example:

- treat `README.md` and `README.zh-CN.md` as one doc entry with logical path `README.md`
- ignore localized variants as separate sidebar items

Preferred rule:

- English base file remains the canonical logical path
- localized variants are implementation details chosen during render

This keeps existing links stable and makes fallback straightforward.

### Copy and messaging consistency

Because the current codebase has mixed English and Chinese strings, this change should normalize all user-facing copy within touched pages.

At minimum, cover:

- `base.html`
- `leaderboard.html`
- `docs.html`
- `user_detail.html`
- `login.html`
- `local_admin_login.html`
- `settings.html`
- new account page template
- admin pages touched by the new navigation or message helpers

The first version does not need to translate every historical Markdown document immediately; it only needs the selection and fallback mechanism. English originals remain valid when no Chinese file exists.

### Data model impact

No schema change is required for language support or self-service account access.

Existing fields are sufficient:

- `users.hook_key`
- `users.hook_key_created_at`
- `users.password_hash`
- `users.role`

This keeps the change small and focused on authorization, routing, and presentation.

## Testing

Add coverage for the following behaviors.

### Navigation and permissions

- normal user navigation omits admin/system links
- normal user navigation includes docs, leaderboard, username menu, and logout
- admin navigation still exposes admin/system links
- normal user cannot access `/settings`
- normal user cannot access `/api`
- normal user cannot access `/admin/*`
- normal user can access `/users/<self_id>`
- normal user cannot access `/users/<other_id>`

### Account page and APIs

- authenticated user can load the account page
- account page renders current API key information
- user can rotate their own API key and receives the new value
- API key changes after rotation
- user can change their password and log in with the new password

### Language behavior

- Chinese `Accept-Language` renders Chinese UI labels on core pages
- non-Chinese `Accept-Language` renders English UI labels
- pages with client-side updates use translated status and empty-state messages

### Docs behavior

- docs sidebar does not duplicate localized variants
- Chinese request renders `*.zh-CN.md` when present
- Chinese request falls back to the English base file when localized docs are absent
- English request renders the English base file

### Regression coverage

- admin-only flows continue to work
- leaderboard still loads its default snapshot
- existing user detail page behavior still works for authorized viewers

## Rollout Notes

Implement in this order:

1. add language resolution and translation helpers
2. add authorization helper for self-or-admin access
3. add the new account page and account key-rotation endpoint
4. move `/settings` to admin-only access
5. update navigation and leaderboard link behavior
6. add docs logical-path grouping and localized file resolution
7. update and expand tests

This order keeps the app functional while progressively tightening access and adding the new account workflow.
