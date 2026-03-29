import importlib
import importlib.util

import db


def _load_ldap_auth_module():
    spec = importlib.util.find_spec("ldap_auth")
    assert spec is not None
    return importlib.import_module("ldap_auth")


def _build_ldap_settings(**overrides):
    settings = {
        "enabled": True,
        "host": "ldap.example.com",
        "port": 389,
        "use_ssl": False,
        "start_tls": False,
        "bind_dn": "cn=svc,dc=example,dc=com",
        "bind_password": "svc-secret",
        "base_dn": "ou=people,dc=example,dc=com",
        "user_filter": "(uid={username})",
        "username_attribute": "uid",
        "display_name_attribute": "cn",
    }
    settings.update(overrides)
    return settings


class FakeLdapClient:
    def __init__(self, *, bind_result=True, user_bind_result=None, entries=None):
        self.bind_result = bind_result
        self.user_bind_result = bind_result if user_bind_result is None else user_bind_result
        self.entries = list(entries or [])
        self.bind_calls = []
        self.search_calls = []
        self.closed = False

    def bind(self, dn, password):
        self.bind_calls.append((dn, password))
        if len(self.bind_calls) == 1:
            return self.bind_result
        return self.user_bind_result

    def search_users(self, base_dn, user_filter, attributes):
        self.search_calls.append((base_dn, user_filter, tuple(attributes)))
        return list(self.entries)

    def close(self):
        self.closed = True


def test_get_ldap_settings_normalizes_boolean_flags():
    db.set_setting("ldap_enabled", "true")
    db.set_setting("ldap_use_ssl", "false")
    db.set_setting("ldap_start_tls", "1")
    db.set_setting("ldap_port", "1389")
    db.set_setting("ldap_host", "ldap.example.com")

    get_ldap_settings = getattr(db, "get_ldap_settings", None)
    assert callable(get_ldap_settings)

    settings = get_ldap_settings()

    assert settings["enabled"] is True
    assert settings["use_ssl"] is False
    assert settings["start_tls"] is True
    assert settings["port"] == 1389
    assert settings["host"] == "ldap.example.com"


def test_upsert_ldap_user_creates_local_user_with_hook_key():
    upsert_ldap_user = getattr(db, "upsert_ldap_user", None)
    assert callable(upsert_ldap_user)

    user = upsert_ldap_user(
        username="alice",
        display_name="Alice",
        ldap_dn="cn=alice,ou=people,dc=example,dc=com",
    )

    assert user["username"] == "alice"
    assert user["display_name"] == "Alice"
    assert user["auth_source"] == "ldap"
    assert user["ldap_dn"] == "cn=alice,ou=people,dc=example,dc=com"
    assert user["hook_key"]
    assert user["last_synced_at"] is not None


def test_upsert_ldap_user_preserves_local_admin_fallback():
    admin = db.get_user_by_username("admin")
    original_hook_key = admin["hook_key"]

    upsert_ldap_user = getattr(db, "upsert_ldap_user", None)
    assert callable(upsert_ldap_user)

    upsert_ldap_user(
        username=admin["username"],
        display_name="Directory Admin",
        ldap_dn="cn=admin,ou=people,dc=example,dc=com",
    )

    refreshed = db.get_user_by_username("admin")
    assert refreshed["display_name"] == "Directory Admin"
    assert refreshed["role"] == "admin"
    assert refreshed["auth_source"] == "local"
    assert refreshed["ldap_dn"] == "cn=admin,ou=people,dc=example,dc=com"
    assert refreshed["hook_key"] == original_hook_key
    assert refreshed["last_synced_at"] is not None


def test_test_connection_returns_success_for_valid_bind():
    ldap_auth = _load_ldap_auth_module()
    fake_client = FakeLdapClient(bind_result=True)

    success, error = ldap_auth.test_connection(
        _build_ldap_settings(),
        client_factory=lambda settings: fake_client,
    )

    assert success is True
    assert error is None
    assert fake_client.bind_calls == [("cn=svc,dc=example,dc=com", "svc-secret")]
    assert fake_client.closed is True


def test_authenticate_user_returns_normalized_profile():
    ldap_auth = _load_ldap_auth_module()
    fake_client = FakeLdapClient(
        bind_result=True,
        user_bind_result=True,
        entries=[
            {
                "dn": "cn=alice,ou=people,dc=example,dc=com",
                "uid": "alice",
                "cn": "Alice",
            }
        ],
    )

    profile = ldap_auth.authenticate_user(
        _build_ldap_settings(),
        "alice",
        "secret123",
        client_factory=lambda settings: fake_client,
    )

    assert profile == {
        "username": "alice",
        "display_name": "Alice",
        "ldap_dn": "cn=alice,ou=people,dc=example,dc=com",
    }
    assert fake_client.bind_calls == [
        ("cn=svc,dc=example,dc=com", "svc-secret"),
        ("cn=alice,ou=people,dc=example,dc=com", "secret123"),
    ]
    assert fake_client.search_calls == [
        (
            "ou=people,dc=example,dc=com",
            "(uid=alice)",
            ("uid", "cn"),
        )
    ]


def test_login_uses_ldap_when_enabled(client, monkeypatch):
    ldap_auth = _load_ldap_auth_module()
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

    response = client.post(
        "/login",
        data={"username": "alice", "password": "secret123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/leaderboard")
    user = db.get_user_by_username("alice")
    assert user["auth_source"] == "ldap"
    assert user["ldap_dn"] == "cn=alice,ou=people,dc=example,dc=com"


def test_login_local_password_is_rejected_when_ldap_is_enabled(client):
    db.set_setting("ldap_enabled", "true")

    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=True,
    )

    assert response.status_code == 200
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
    ldap_auth = _load_ldap_auth_module()
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

    response = client.post(
        "/login",
        data={"username": "alice", "password": "secret123"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Invalid username or password" in response.get_data(as_text=True)


def test_local_admin_login_rejects_ldap_managed_account(client):
    db.set_setting("ldap_enabled", "true")
    db.create_user(
        "ops-admin",
        "secret123",
        display_name="Ops Admin",
        role="admin",
        auth_source=db.AUTH_SOURCE_LDAP,
    )

    response = client.post(
        "/login/local-admin",
        data={"username": "ops-admin", "password": "secret123"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Invalid username or password" in response.get_data(as_text=True)


def test_admin_ldap_page_requires_admin(client):
    response = client.get("/admin/ldap", follow_redirects=False)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_can_save_ldap_config_without_overwriting_blank_password(auth_session):
    auth_session.post(
        "/admin/ldap",
        data={
            "action": "save_config",
            "ldap_host": "ldap.example.com",
            "ldap_bind_password": "first-secret",
        },
        follow_redirects=True,
    )

    auth_session.post(
        "/admin/ldap",
        data={
            "action": "save_config",
            "ldap_host": "ldap.internal",
            "ldap_bind_password": "",
        },
        follow_redirects=True,
    )

    assert db.get_setting("ldap_bind_password") == "first-secret"
    assert db.get_setting("ldap_host") == "ldap.internal"


def test_admin_can_test_ldap_connection(auth_session, monkeypatch):
    ldap_auth = _load_ldap_auth_module()
    monkeypatch.setattr(
        ldap_auth,
        "test_connection",
        lambda settings, **_: (True, None),
    )

    response = auth_session.post(
        "/admin/ldap",
        data={"action": "test_connection"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "LDAP connection successful" in response.get_data(as_text=True)


def test_admin_sync_users_uses_ldap_results(auth_session, monkeypatch):
    ldap_auth = _load_ldap_auth_module()
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

    response = auth_session.post(
        "/admin/ldap",
        data={"action": "sync_users"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "Created 1 users" in response.get_data(as_text=True)
    assert db.get_user_by_username("alice")["auth_source"] == "ldap"
