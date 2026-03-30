# LDAP Authentication and User Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement admin-configured LDAP authentication and user sync in TokenLeague, with database-backed configuration, LDAP-only normal login when enabled, first-login auto-provisioning, admin-triggered sync, and a separate local-admin emergency login path.

**Architecture:** Keep LDAP configuration in `system_settings` and keep app-owned identity in `users`. Add a focused `service/ldap_auth.py` module for LDAP config parsing and directory operations, extend `service/db.py` with LDAP config and LDAP-user upsert helpers, and wire the flows through server-rendered routes and templates in `service/app.py`.

**Tech Stack:** Python, Flask, Jinja, MySQL, `ldap3`, pytest

---

## File Structure

- `service/ldap_auth.py`: LDAP config normalization, connection testing, user authentication, and user listing behind a small internal API.
- `service/db.py`: LDAP setting helpers, LDAP user upsert helpers, in-memory store support, and public user serialization updates.
- `service/app.py`: `/login` LDAP branch, `/login/local-admin`, `/admin/ldap`, and form action handling.
- `service/auth.py`: local-password verification helpers for the emergency admin flow.
- `service/templates/login.html`: add the emergency local-admin entry point.
- `service/templates/local_admin_login.html`: local-only admin recovery page.
- `service/templates/admin_ldap.html`: LDAP configuration, connection testing, sync controls, and current LDAP-backed user visibility.
- `service/templates/base.html`: add an admin navigation link to the LDAP page.
- `service/tests/test_ldap_auth.py`: focused LDAP config, sync, and route coverage.
- `service/requirements.txt`: add the LDAP client dependency.
- `scripts/migrations/001_init_schema.py`: ensure fresh installs include LDAP user columns.
- `scripts/migrations/005_add_ldap_user_fields.py`: forward migration for existing databases.
- `scripts/init_db.py`: bootstrap the default local admin with `auth_source='local'`.

### Task 1: Add schema and DB helper coverage for LDAP-backed users

**Files:**
- Create: `service/tests/test_ldap_auth.py`
- Modify: `service/db.py`
- Modify: `scripts/migrations/001_init_schema.py`
- Create: `scripts/migrations/005_add_ldap_user_fields.py`
- Modify: `scripts/init_db.py`
- Test: `service/tests/test_ldap_auth.py`

- [ ] **Step 1: Write the failing DB-layer tests**

```python
def test_get_ldap_settings_normalizes_boolean_flags():
    db.set_setting("ldap_enabled", "true")
    db.set_setting("ldap_use_ssl", "false")
    db.set_setting("ldap_start_tls", "1")

    settings = db.get_ldap_settings()

    assert settings["enabled"] is True
    assert settings["use_ssl"] is False
    assert settings["start_tls"] is True


def test_upsert_ldap_user_creates_local_user_with_hook_key():
    user = db.upsert_ldap_user(
        username="alice",
        display_name="Alice",
        ldap_dn="cn=alice,ou=people,dc=example,dc=com",
    )

    assert user["username"] == "alice"
    assert user["display_name"] == "Alice"
    assert user["auth_source"] == "ldap"
    assert user["hook_key"]


def test_upsert_ldap_user_preserves_local_admin_fallback():
    admin = db.get_user_by_username("admin")
    db.upsert_ldap_user(
        username=admin["username"],
        display_name="Directory Admin",
        ldap_dn="cn=admin,ou=people,dc=example,dc=com",
    )

    refreshed = db.get_user_by_username("admin")
    assert refreshed["auth_source"] == "local"
    assert refreshed["role"] == "admin"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest service/tests/test_ldap_auth.py::test_get_ldap_settings_normalizes_boolean_flags service/tests/test_ldap_auth.py::test_upsert_ldap_user_creates_local_user_with_hook_key service/tests/test_ldap_auth.py::test_upsert_ldap_user_preserves_local_admin_fallback -q`
Expected: FAIL because `db.get_ldap_settings` and `db.upsert_ldap_user` do not exist and the in-memory user shape does not yet include LDAP metadata.

- [ ] **Step 3: Implement the minimal DB helpers and in-memory support**

Add helpers in `service/db.py` with shapes like:

```python
def get_ldap_settings() -> dict[str, Any]:
    return {
        "enabled": _is_truthy(get_setting("ldap_enabled")),
        "host": (get_setting("ldap_host") or "").strip(),
        "port": int((get_setting("ldap_port") or "389").strip() or "389"),
        "use_ssl": _is_truthy(get_setting("ldap_use_ssl")),
        "start_tls": _is_truthy(get_setting("ldap_start_tls")),
        "bind_dn": (get_setting("ldap_bind_dn") or "").strip(),
        "bind_password": get_setting("ldap_bind_password") or "",
        "base_dn": (get_setting("ldap_base_dn") or "").strip(),
        "user_filter": (get_setting("ldap_user_filter") or "").strip(),
        "username_attribute": (get_setting("ldap_username_attribute") or "uid").strip(),
        "display_name_attribute": (get_setting("ldap_display_name_attribute") or "cn").strip(),
    }


def upsert_ldap_user(*, username: str, display_name: str, ldap_dn: str) -> dict[str, Any]:
    ...
```

Update the in-memory store and user serializers so `auth_source`, `ldap_dn`, and `last_synced_at` are available in tests and templates.

- [ ] **Step 4: Add the schema and bootstrap changes**

Implement the forward migration and fresh-install schema updates:

```python
ALTER TABLE users
ADD COLUMN auth_source ENUM('local', 'ldap') NOT NULL DEFAULT 'local',
ADD COLUMN ldap_dn VARCHAR(255) NULL,
ADD COLUMN last_synced_at DATETIME NULL;
```

Also update `scripts/init_db.py` so the bootstrap admin insert explicitly sets `auth_source='local'`.

- [ ] **Step 5: Run the focused DB tests again**

Run: `pytest service/tests/test_ldap_auth.py::test_get_ldap_settings_normalizes_boolean_flags service/tests/test_ldap_auth.py::test_upsert_ldap_user_creates_local_user_with_hook_key service/tests/test_ldap_auth.py::test_upsert_ldap_user_preserves_local_admin_fallback -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add service/tests/test_ldap_auth.py service/db.py scripts/migrations/001_init_schema.py scripts/migrations/005_add_ldap_user_fields.py scripts/init_db.py
git commit -m "feat: add LDAP user schema and db helpers"
```

### Task 2: Add the LDAP service module and dependency

**Files:**
- Modify: `service/requirements.txt`
- Create: `service/ldap_auth.py`
- Modify: `service/tests/test_ldap_auth.py`
- Test: `service/tests/test_ldap_auth.py`

- [ ] **Step 1: Write the failing LDAP service tests**

Add tests that isolate LDAP behavior with fakes instead of a real directory server:

```python
def test_test_connection_returns_success_for_valid_bind(monkeypatch):
    fake_client = FakeLdapClient(bind_result=True)

    result = ldap_auth.test_connection(
        settings,
        client_factory=lambda **_: fake_client,
    )

    assert result == (True, None)


def test_authenticate_user_returns_normalized_profile(monkeypatch):
    fake_client = FakeLdapClient(
        bind_result=True,
        entries=[
            {
                "dn": "cn=alice,ou=people,dc=example,dc=com",
                "uid": "alice",
                "cn": "Alice",
            }
        ],
    )

    profile = ldap_auth.authenticate_user(
        settings,
        "alice",
        "secret123",
        client_factory=lambda **_: fake_client,
    )

    assert profile == {
        "username": "alice",
        "display_name": "Alice",
        "ldap_dn": "cn=alice,ou=people,dc=example,dc=com",
    }
```

- [ ] **Step 2: Run the focused LDAP service tests to verify they fail**

Run: `pytest service/tests/test_ldap_auth.py::test_test_connection_returns_success_for_valid_bind service/tests/test_ldap_auth.py::test_authenticate_user_returns_normalized_profile -q`
Expected: FAIL because `service/ldap_auth.py` does not exist and `ldap3` is not yet available.

- [ ] **Step 3: Add the dependency and implement the minimal service**

Update `service/requirements.txt`:

```text
flask
mysql-connector-python
werkzeug
ldap3
```

Create `service/ldap_auth.py` with a small surface area:

```python
def validate_settings(settings: dict[str, Any], *, require_bind: bool) -> list[str]:
    ...


def test_connection(settings: dict[str, Any], *, client_factory=None) -> tuple[bool, str | None]:
    ...


def authenticate_user(settings: dict[str, Any], username: str, password: str, *, client_factory=None) -> dict[str, str] | None:
    ...


def list_users(settings: dict[str, Any], *, client_factory=None) -> list[dict[str, str]]:
    ...
```

Normalize all LDAP results into `username`, `display_name`, and `ldap_dn`. Keep connection details inside this module.

- [ ] **Step 4: Run the focused LDAP service tests again**

Run: `pytest service/tests/test_ldap_auth.py::test_test_connection_returns_success_for_valid_bind service/tests/test_ldap_auth.py::test_authenticate_user_returns_normalized_profile -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/requirements.txt service/ldap_auth.py service/tests/test_ldap_auth.py
git commit -m "feat: add LDAP service module"
```

### Task 3: Implement LDAP-aware login and local-admin emergency login

**Files:**
- Modify: `service/auth.py`
- Modify: `service/app.py`
- Modify: `service/templates/login.html`
- Create: `service/templates/local_admin_login.html`
- Modify: `service/tests/test_ldap_auth.py`
- Test: `service/tests/test_ldap_auth.py`

- [ ] **Step 1: Write the failing login-flow tests**

Cover both the LDAP-enabled and emergency-local paths:

```python
def test_login_uses_ldap_when_enabled(client, monkeypatch):
    db.set_setting("ldap_enabled", "true")
    monkeypatch.setattr(
        ldap_auth,
        "authenticate_user",
        lambda settings, username, password, **_: {
            "username": username,
            "display_name": "Alice",
            "ldap_dn": "cn=alice,ou=people,dc=example,dc=com",
        },
    )

    response = client.post("/login", data={"username": "alice", "password": "secret123"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/leaderboard")


def test_login_local_password_is_rejected_when_ldap_is_enabled(client):
    db.set_setting("ldap_enabled", "true")

    response = client.post("/login", data={"username": "admin", "password": "admin123"})

    assert "Invalid username or password" in response.get_data(as_text=True)


def test_local_admin_login_allows_local_admin_when_ldap_is_enabled(client):
    db.set_setting("ldap_enabled", "true")

    response = client.post(
        "/login/local-admin",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/leaderboard")


def test_login_rejects_disabled_local_user_even_after_ldap_success(client, monkeypatch):
    db.set_setting("ldap_enabled", "true")
    db.create_user("alice", "placeholder123", display_name="Alice", status=db.USER_DISABLED)
    monkeypatch.setattr(
        ldap_auth,
        "authenticate_user",
        lambda settings, username, password, **_: {
            "username": username,
            "display_name": "Alice",
            "ldap_dn": "cn=alice,ou=people,dc=example,dc=com",
        },
    )

    response = client.post("/login", data={"username": "alice", "password": "secret123"})

    assert "Invalid username or password" in response.get_data(as_text=True)


def test_local_admin_login_rejects_ldap_managed_account(client):
    db.set_setting("ldap_enabled", "true")
    db.upsert_ldap_user(
        username="ops-admin",
        display_name="Ops Admin",
        ldap_dn="cn=ops-admin,ou=people,dc=example,dc=com",
    )

    response = client.post(
        "/login/local-admin",
        data={"username": "ops-admin", "password": "whatever"},
    )

    assert "Invalid username or password" in response.get_data(as_text=True)
```

- [ ] **Step 2: Run the targeted login tests to verify they fail**

Run: `pytest service/tests/test_ldap_auth.py::test_login_uses_ldap_when_enabled service/tests/test_ldap_auth.py::test_login_local_password_is_rejected_when_ldap_is_enabled service/tests/test_ldap_auth.py::test_local_admin_login_allows_local_admin_when_ldap_is_enabled service/tests/test_ldap_auth.py::test_login_rejects_disabled_local_user_even_after_ldap_success service/tests/test_ldap_auth.py::test_local_admin_login_rejects_ldap_managed_account -q`
Expected: FAIL because `/login` still only uses local password verification and `/login/local-admin` does not exist.

- [ ] **Step 3: Implement the minimal route and auth changes**

Refactor `service/auth.py` to make the local-password path explicit:

```python
def verify_local_password(username: str, password: str):
    ...


def verify_local_admin_password(username: str, password: str):
    user = verify_local_password(username, password)
    if not user or user["role"] != "admin" or user.get("auth_source") != "local":
        return None
    return user
```

Then update `service/app.py`:

- branch `/login` on `db.get_ldap_settings()["enabled"]`
- call `ldap_auth.authenticate_user(...)` when LDAP is enabled
- upsert the local LDAP-backed user before creating the session
- add `GET` and `POST` for `/login/local-admin`

Create `service/templates/local_admin_login.html` and add a small recovery link from `service/templates/login.html`.

- [ ] **Step 4: Run the targeted login tests again**

Run: `pytest service/tests/test_ldap_auth.py::test_login_uses_ldap_when_enabled service/tests/test_ldap_auth.py::test_login_local_password_is_rejected_when_ldap_is_enabled service/tests/test_ldap_auth.py::test_local_admin_login_allows_local_admin_when_ldap_is_enabled service/tests/test_ldap_auth.py::test_login_rejects_disabled_local_user_even_after_ldap_success service/tests/test_ldap_auth.py::test_local_admin_login_rejects_ldap_managed_account -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/auth.py service/app.py service/templates/login.html service/templates/local_admin_login.html service/tests/test_ldap_auth.py
git commit -m "feat: add LDAP login and local admin fallback"
```

### Task 4: Add the admin LDAP configuration page and sync flow

**Files:**
- Modify: `service/app.py`
- Modify: `service/db.py`
- Modify: `service/templates/base.html`
- Create: `service/templates/admin_ldap.html`
- Modify: `service/tests/test_ldap_auth.py`
- Test: `service/tests/test_ldap_auth.py`

- [ ] **Step 1: Write the failing admin-page tests**

Add route and action coverage using the same `action`-field pattern as `/admin/users`:

```python
def test_admin_ldap_page_requires_admin(client):
    response = client.get("/admin/ldap")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_can_save_ldap_config_without_overwriting_blank_password(auth_session):
    auth_session.post(
        "/admin/ldap",
        data={"action": "save_config", "ldap_bind_password": "first-secret", "ldap_host": "ldap.example.com"},
    )

    auth_session.post(
        "/admin/ldap",
        data={"action": "save_config", "ldap_bind_password": "", "ldap_host": "ldap.internal"},
    )

    assert db.get_setting("ldap_bind_password") == "first-secret"
    assert db.get_setting("ldap_host") == "ldap.internal"


def test_admin_sync_users_uses_ldap_results(auth_session, monkeypatch):
    monkeypatch.setattr(
        ldap_auth,
        "list_users",
        lambda settings, **_: [
            {
                "username": "alice",
                "display_name": "Alice",
                "ldap_dn": "cn=alice,ou=people,dc=example,dc=com",
            }
        ],
    )

    response = auth_session.post("/admin/ldap", data={"action": "sync_users"}, follow_redirects=True)

    assert response.status_code == 200
    assert "Created 1 users" in response.get_data(as_text=True)
    assert db.get_user_by_username("alice")["auth_source"] == "ldap"


def test_admin_can_test_ldap_connection(auth_session, monkeypatch):
    monkeypatch.setattr(
        ldap_auth,
        "test_connection",
        lambda settings, **_: (True, None),
    )

    response = auth_session.post("/admin/ldap", data={"action": "test_connection"}, follow_redirects=True)

    assert response.status_code == 200
    assert "LDAP connection successful" in response.get_data(as_text=True)
```

- [ ] **Step 2: Run the targeted admin tests to verify they fail**

Run: `pytest service/tests/test_ldap_auth.py::test_admin_can_save_ldap_config_without_overwriting_blank_password service/tests/test_ldap_auth.py::test_admin_sync_users_uses_ldap_results service/tests/test_ldap_auth.py::test_admin_can_test_ldap_connection -q`
Expected: FAIL because `/admin/ldap` does not exist and there is no config-saving or sync handling yet.

- [ ] **Step 3: Implement the minimal admin route and template**

Add `/admin/ldap` to `service/app.py` using `action` dispatch:

```python
if action == "save_config":
    ...
elif action == "test_connection":
    ok, error = ldap_auth.test_connection(settings)
elif action == "sync_users":
    users = ldap_auth.list_users(settings)
    ...
```

Create `service/templates/admin_ldap.html` with:

- configuration form
- save and test buttons
- sync button
- current-user table showing `auth_source`, `ldap_dn`, and `last_synced_at`

Add an admin navigation link in `service/templates/base.html`.

- [ ] **Step 4: Run the targeted admin tests again**

Run: `pytest service/tests/test_ldap_auth.py::test_admin_can_save_ldap_config_without_overwriting_blank_password service/tests/test_ldap_auth.py::test_admin_sync_users_uses_ldap_results service/tests/test_ldap_auth.py::test_admin_can_test_ldap_connection -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/app.py service/db.py service/templates/base.html service/templates/admin_ldap.html service/tests/test_ldap_auth.py
git commit -m "feat: add LDAP admin configuration and sync"
```

### Task 5: Run verification and close the loop

**Files:**
- Modify: `service/tests/test_ldap_auth.py` (only if fixes are needed from verification)
- Modify: `service/app.py` (only if fixes are needed from verification)
- Modify: `service/db.py` (only if fixes are needed from verification)
- Test: `service/tests/test_ldap_auth.py`
- Test: `service/tests/test_auth_flow.py`
- Test: `service/tests/test_token_league.py`

- [ ] **Step 1: Run the LDAP-focused test set**

Run: `pytest service/tests/test_ldap_auth.py service/tests/test_auth_flow.py service/tests/test_token_league.py -q`
Expected: PASS

- [ ] **Step 2: Run the full service test suite**

Run: `pytest service/tests -q`
Expected: PASS

- [ ] **Step 3: Fix any final regressions with the smallest possible patch**

If a regression appears, keep the fix inside the affected boundary instead of reopening architecture decisions. Typical examples:

```python
if request.method == "POST" and action == "save_config" and not bind_password:
    bind_password = current_settings["bind_password"]
```

- [ ] **Step 4: Re-run the failing verification command until green**

Run the specific command that failed in Step 1 or Step 2.
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add service/app.py service/db.py service/tests/test_ldap_auth.py service/ldap_auth.py service/templates/admin_ldap.html service/templates/local_admin_login.html service/templates/login.html service/templates/base.html service/requirements.txt scripts/migrations/001_init_schema.py scripts/migrations/005_add_ldap_user_fields.py scripts/init_db.py
git commit -m "feat: add LDAP authentication and user sync"
```
