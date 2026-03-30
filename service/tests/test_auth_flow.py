def test_login_page_is_public(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert "TokenLeague" in response.get_data(as_text=True)


def test_settings_requires_login(client):
    response = client.get("/settings")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_settings_page_returns_403_for_normal_user(user_session):
    response = user_session.get("/settings")

    assert response.status_code == 403
    assert response.get_data(as_text=True) == "Forbidden"


def test_api_list_page_returns_403_for_normal_user(user_session):
    response = user_session.get("/api")

    assert response.status_code == 403
    assert response.get_data(as_text=True) == "Forbidden"


def test_login_post_redirects_to_settings(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/leaderboard")


def test_change_password_api_requires_login(client):
    response = client.post("/api/change-password", json={"new_password": "changed123"})

    assert response.status_code == 401


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
