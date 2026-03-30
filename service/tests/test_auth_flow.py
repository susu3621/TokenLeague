def test_login_page_is_public(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert "TokenLeague" in response.get_data(as_text=True)


def test_settings_requires_login(client):
    response = client.get("/settings")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_account_page_requires_login(client):
    response = client.get("/account")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_settings_page_returns_403_for_normal_user(user_session):
    response = user_session.get("/settings")

    assert response.status_code == 403
    assert response.get_data(as_text=True) == "Forbidden"


def test_settings_page_returns_localized_403_for_normal_user(user_session):
    response = user_session.get(
        "/settings",
        headers={"Accept-Language": "zh-CN,zh;q=0.9"},
    )

    assert response.status_code == 403
    assert response.get_data(as_text=True) == "禁止访问"


def test_account_page_renders_current_user_hook_key(user_session):
    import db

    user = db.get_user_by_username("alice")

    response = user_session.get("/account")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert user["hook_key"] in html
    assert "/api/account/rotate-hook-key" in html
    assert "/api/change-password" in html


def test_account_page_hides_password_form_for_ldap_user(client):
    import db

    user = db.create_user(
        "ldap-alice",
        "secret123",
        display_name="LDAP Alice",
        auth_source=db.AUTH_SOURCE_LDAP,
    )
    with client.session_transaction() as session:
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]

    response = client.get("/account")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "API Key" in html
    assert "New Password" not in html
    assert "Save Password" not in html
    assert "/api/change-password" not in html


def test_rotate_hook_key_api_rotates_only_the_current_user_key(user_session):
    import db

    current_user = db.get_user_by_username("alice")
    other_user = db.create_user("bob", "secret123", display_name="Bob")
    original_current_hook_key = current_user["hook_key"]
    original_other_hook_key = other_user["hook_key"]

    response = user_session.post("/api/account/rotate-hook-key")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["hook_key"] != original_current_hook_key
    assert payload["hook_key_created_at"]

    refreshed_current_user = db.get_user_by_username("alice")
    refreshed_other_user = db.get_user_by_username("bob")
    assert refreshed_current_user["hook_key"] != original_current_hook_key
    assert refreshed_current_user["hook_key"] == payload["hook_key"]
    assert refreshed_other_user["hook_key"] == original_other_hook_key


def test_change_password_api_rejects_ldap_users(client):
    import db

    user = db.create_user(
        "ldap-alice",
        "secret123",
        display_name="LDAP Alice",
        auth_source=db.AUTH_SOURCE_LDAP,
    )
    original_password_hash = user["password_hash"]
    with client.session_transaction() as session:
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]

    response = client.post("/api/change-password", json={"new_password": "changed123"})

    assert response.status_code == 403
    assert response.get_json() == {
        "success": False,
        "error": "Password changes are not available for LDAP users",
    }
    assert db.get_user_by_username("ldap-alice")["password_hash"] == original_password_hash


def test_change_password_api_rejects_ldap_users_in_chinese(client):
    import db

    user = db.create_user(
        "ldap-alice",
        "secret123",
        display_name="LDAP Alice",
        auth_source=db.AUTH_SOURCE_LDAP,
    )
    with client.session_transaction() as session:
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["role"] = user["role"]

    response = client.post(
        "/api/change-password",
        json={"new_password": "changed123"},
        headers={"Accept-Language": "zh-CN,zh;q=0.9"},
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "success": False,
        "error": "LDAP 用户无法修改密码",
    }


def test_api_list_page_returns_403_for_normal_user(user_session):
    response = user_session.get("/api")

    assert response.status_code == 403
    assert response.get_data(as_text=True) == "Forbidden"


def test_disabled_admin_loses_settings_access(auth_session):
    import db

    db.set_user_status(1, db.USER_DISABLED)

    response = auth_session.get("/settings")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    with auth_session.session_transaction() as session:
        assert "user_id" not in session
        assert "role" not in session


def test_login_post_redirects_to_settings(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/leaderboard")


def test_login_rejects_local_password_after_user_becomes_ldap(client):
    import db

    db.create_user("alice", "alice123", display_name="Alice")
    db.upsert_ldap_user(
        username="alice",
        display_name="Alice LDAP",
        ldap_dn="cn=alice,dc=example,dc=com",
    )

    response = client.post(
        "/login",
        data={"username": "alice", "password": "alice123"},
        follow_redirects=False,
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Invalid username or password" in html
    assert "/leaderboard" not in response.headers.get("Location", "")


def test_change_password_api_requires_login(client):
    response = client.post("/api/change-password", json={"new_password": "changed123"})

    assert response.status_code == 401


def test_change_password_api_requires_new_password_in_chinese(auth_session):
    response = auth_session.post(
        "/api/change-password",
        json={},
        headers={"Accept-Language": "zh-CN,zh;q=0.9"},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": "必须提供 new_password",
    }


def test_rotate_hook_key_api_requires_login(client):
    response = client.post("/api/account/rotate-hook-key")

    assert response.status_code == 401


def test_rotate_hook_key_api_requires_login_in_chinese(client):
    response = client.post(
        "/api/account/rotate-hook-key",
        headers={"Accept-Language": "zh-CN,zh;q=0.9"},
    )

    assert response.status_code == 401
    assert response.get_json() == {
        "success": False,
        "error": "需要先登录",
    }


def test_change_password_api_rejects_invalid_origin_in_chinese(auth_session):
    response = auth_session.post(
        "/api/change-password",
        json={"new_password": "changed123"},
        headers={
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "https://evil.example.com",
        },
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "success": False,
        "error": "来源校验失败",
    }


def test_change_password_api_updates_password(auth_session):
    response = auth_session.post("/api/change-password", json={"new_password": "changed123"})

    assert response.status_code == 200
    assert response.get_json()["success"] is True

    auth_session.post("/logout")
    relogin = auth_session.post(
        "/login",
        data={"username": "admin", "password": "changed123"},
        follow_redirects=False,
    )
    assert relogin.status_code == 302
    assert relogin.headers["Location"].endswith("/leaderboard")
