# LDAP Authentication and User Sync Design

## Goal

Add LDAP configuration to TokenLeague, store the configuration in the database, require LDAP authentication for normal logins when LDAP is enabled, and support both admin-triggered sync and first-login auto-provisioning of LDAP users into the local `users` table.

## Scope

- Add an admin-only LDAP configuration page in the web UI.
- Store LDAP configuration in `system_settings`.
- Add LDAP-backed authentication for `/login` when LDAP is enabled.
- Preserve a separate local-admin emergency login path for configuration recovery.
- Add admin-triggered LDAP user sync into the local `users` table.
- Add first-login auto-provisioning for LDAP users who do not yet exist locally.
- Extend the local `users` schema with the minimum LDAP metadata needed to track source and sync state.
- Add automated tests for LDAP config, login behavior, emergency login, and user sync behavior.

Out of scope:

- LDAP group-to-role mapping.
- Automatic disable or deletion of users removed from LDAP.
- Multiple LDAP providers or per-tenant LDAP settings.
- Replacing the local `users` table as the application's source of business identity.
- Migrating existing admin roles from local state to LDAP-derived authorization.

## Existing Context

TokenLeague is a small Flask + Jinja application with session authentication, a MySQL persistence layer in `service/db.py`, and server-rendered admin pages in `service/app.py`.

Today:

- `/login` uses `service/auth.py::verify_password`, which only checks the local `users.password_hash`.
- `/settings` is a normal authenticated page, not admin-only.
- `/admin/users` is the existing admin user management page.
- application settings are already stored as key/value pairs in `system_settings`.
- the local `users` table already owns app-specific state such as `role`, `status`, and `hook_key`.

That means LDAP should be added as a new authentication capability, while the local `users` table remains the application record used by rankings, hook ingestion, and authorization.

## Design

### Integration model

Keep the current architectural pattern:

- configuration stays in `system_settings`
- app-owned user state stays in `users`
- Flask routes in `service/app.py` orchestrate form handling and login
- a new LDAP service module encapsulates LDAP-specific operations

Avoid introducing a dedicated LDAP configuration table or a generalized auth-provider abstraction in the first version. The current codebase is small enough that the added abstraction would cost more complexity than it saves.

### Configuration storage

Store LDAP configuration as individual settings in `system_settings`:

- `ldap_enabled`
- `ldap_host`
- `ldap_port`
- `ldap_use_ssl`
- `ldap_start_tls`
- `ldap_bind_dn`
- `ldap_bind_password`
- `ldap_base_dn`
- `ldap_user_filter`
- `ldap_username_attribute`
- `ldap_display_name_attribute`

Storage rules:

- `ldap_enabled`, `ldap_use_ssl`, and `ldap_start_tls` are stored as string booleans and parsed through a shared helper.
- `ldap_bind_password` is stored in the database so the app can reconnect without re-entry.
- the admin form never re-renders the stored bind password in plaintext.
- posting an empty bind password means "keep the existing password".

The existing `db.get_setting` and `db.set_setting` API remains the write path. Add LDAP-specific read helpers in `service/db.py` so route code does not manually assemble or normalize every setting.

### User schema changes

Extend `users` with the minimum fields needed for LDAP-backed identity tracking:

- `auth_source` with values `local` or `ldap`
- `ldap_dn`
- `last_synced_at`

Rules:

- keep `password_hash` because the local emergency admin path still uses it
- keep `role`, `status`, and `hook_key` as local application-owned fields
- keep `username` as the unique join key between LDAP and the local user table in the first version

Behavioral meaning:

- `auth_source='ldap'` indicates the user's normal authentication source is LDAP
- `auth_source='local'` indicates a purely local account, primarily the emergency admin account
- `ldap_dn` stores the last known distinguished name returned by LDAP
- `last_synced_at` records when LDAP identity data was last refreshed by sync or successful login

Do not add a separate external-id column in the first version. The requested scope does not require rename-safe identity migration, and using `username` keeps the implementation aligned with the current table design.

### LDAP service boundary

Add a dedicated module, for example `service/ldap_auth.py`, to contain LDAP operations and normalization. The rest of the app should not call LDAP libraries directly.

The module should expose focused operations:

- load and validate effective LDAP config
- test connectivity and bind behavior
- authenticate a single user by username and password
- fetch a single LDAP user by username
- list LDAP users for admin sync

Returned LDAP user objects should be normalized into a small internal shape:

- `username`
- `display_name`
- `ldap_dn`

This keeps Flask routes and DB upsert logic independent from raw LDAP response structures.

### Login flow

#### Normal login

`/login` keeps the same route and form, but changes behavior when LDAP is enabled.

When `ldap_enabled=false`:

- preserve the current local password authentication behavior

When `ldap_enabled=true`:

- ignore local password authentication for normal login
- authenticate the submitted username/password against LDAP
- on LDAP success, upsert the local user record by username
- if the local user already exists, refresh `display_name`, `ldap_dn`, `auth_source`, and `last_synced_at`
- if the local user does not exist, create it with:
  - `display_name` from LDAP, falling back to username
  - `role='user'`
  - `status='active'`
  - generated `hook_key`
  - `auth_source='ldap'`
- reject login if the resulting local user has `status='disabled'`
- establish the usual Flask session from the local user record

Normal login errors should stay generic, such as "Invalid username or password", even when the real cause is LDAP connection, bind, or search failure. Admin-facing diagnostics belong only on the LDAP config page.

#### Emergency local-admin login

Add a separate route pair:

- `GET /login/local-admin`
- `POST /login/local-admin`

This route remains local-password based even when LDAP is enabled, but is deliberately restricted:

- only users with `role='admin'`
- only users with `auth_source='local'`
- still subject to `status='active'`

This path exists solely to recover from broken LDAP configuration without locking administrators out of the application.

Keep the entry point explicit rather than silently falling back from `/login`, so normal authentication remains deterministic and administrators can reason about which backend is in use.

### LDAP user sync

Add an admin-triggered sync action on the LDAP admin page.

The sync flow:

1. Load effective LDAP config.
2. Bind using the configured bind DN and password.
3. Query LDAP users under the configured base DN and filter.
4. Normalize each result into `username`, `display_name`, and `ldap_dn`.
5. Upsert each user into the local `users` table by username.

Upsert rules:

- if the local user exists, update:
  - `display_name`
  - `ldap_dn`
  - `auth_source='ldap'`
  - `last_synced_at`
- if the local user does not exist, create it with:
  - default `role='user'`
  - default `status='active'`
  - generated `hook_key`
  - `auth_source='ldap'`
  - LDAP-derived `display_name`
  - `ldap_dn`
  - `last_synced_at`
- never overwrite:
  - `role`
  - `status`
  - `hook_key`
  - `password_hash`

Return a sync summary to the admin UI:

- created count
- updated count
- skipped count

The first version should not attempt destructive reconciliation. If an LDAP user disappears from the directory, the corresponding local account remains untouched until an admin explicitly disables it.

### First-login auto-provisioning

Successful LDAP login reuses the same upsert path as manual sync.

This ensures:

- admins may pre-sync users before rollout
- unsynced LDAP users can still access the app on first login
- LDAP display-name changes propagate during normal use

Implement this shared behavior as a single DB-layer helper or tightly scoped service helper so admin sync and login do not drift apart.

### Admin UI

Do not place LDAP configuration in `/settings`, because `/settings` is currently available to any authenticated user. LDAP configuration contains privileged credentials and admin-only operations.

Add a dedicated admin-only route and template:

- `GET /admin/ldap`
- `POST /admin/ldap`

The page should contain three sections.

#### Configuration form

Fields:

- enabled toggle
- host
- port
- use SSL toggle
- StartTLS toggle
- bind DN
- bind password
- base DN
- user filter
- username attribute
- display-name attribute

Actions:

- save configuration
- test connection

Use traditional form posts, matching the existing server-rendered admin pages. This keeps the first version consistent with `admin_users` and avoids introducing frontend-only complexity.

#### Sync action

Add a dedicated submit action to trigger LDAP sync and render the result summary on the same page.

The first version does not need a preview-only mode or client-side progress UI.

#### LDAP-backed user visibility

Render a table of local users with LDAP metadata that helps administrators understand the current state:

- username
- display name
- role
- status
- auth source
- ldap DN
- last synced at

This view should use the local `users` table rather than direct LDAP queries so the page always reflects application state.

### Error handling

Ordinary login:

- always return a generic authentication failure message
- do not leak LDAP hostnames, DNs, filters, or transport details

Admin LDAP page:

- surface actionable messages for invalid config, connection failure, bind failure, and sync failure
- keep the messages scoped to admin users only

Config validation:

- require host, port, base DN, username attribute, and user filter when enabling LDAP
- require bind DN and bind password for admin sync and connection test
- disallow enabling both `ldap_use_ssl` and `ldap_start_tls` simultaneously if the implementation treats them as mutually exclusive transport modes

### Testing

Add focused automated tests for:

- local login remains unchanged when LDAP is disabled
- normal login uses LDAP when LDAP is enabled
- local password no longer works on `/login` when LDAP is enabled
- emergency local-admin login works when LDAP is enabled
- non-admin or non-local accounts cannot use the emergency login path
- LDAP login auto-provisions a missing local user
- LDAP login refreshes an existing local user's display name and DN
- disabled local users cannot log in even after successful LDAP authentication
- admin-only access to the LDAP page
- LDAP config persistence to `system_settings`
- blank bind-password submissions preserve the existing stored password
- LDAP test-connection success and failure rendering
- admin sync creates new users and updates existing users
- admin sync does not overwrite `role`, `status`, `hook_key`, or `password_hash`

Mock LDAP service calls in tests rather than requiring a real directory server.

## Files

Create:

- `service/ldap_auth.py`
- `service/templates/admin_ldap.html`
- `service/templates/local_admin_login.html`
- `docs/superpowers/specs/2026-03-29-ldap-auth-and-sync-design.md`

Modify:

- `service/app.py`
- `service/auth.py`
- `service/db.py`
- `service/templates/base.html`
- `service/templates/login.html`
- `service/tests/test_auth_flow.py`
- `service/tests/test_token_league.py`
- `scripts/migrations/001_init_schema.py`
- add a new numbered migration for the LDAP user columns if the repository migration policy prefers forward-only schema updates over editing only the bootstrap schema
