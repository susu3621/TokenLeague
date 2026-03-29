import db


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
