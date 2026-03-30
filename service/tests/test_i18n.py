def test_resolve_locale_prefers_chinese_variants():
    from i18n import resolve_locale

    assert resolve_locale("zh-CN,zh;q=0.9,en;q=0.8") == "zh-CN"
    assert resolve_locale("zh-TW,en;q=0.8") == "zh-CN"
    assert resolve_locale("en-US,en;q=0.9") == "en"


def test_login_page_renders_chinese_copy(client):
    response = client.get("/login", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<html lang="zh-CN">' in html
    assert "登录" in html
    assert "用户名" in html
    assert "密码" in html


def test_leaderboard_page_renders_chinese_shell_copy(auth_session):
    response = auth_session.get("/leaderboard", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Token 排行榜" in html
    assert "正在加载排行榜..." in html
    assert "排行榜尚在准备中" in html


def test_unknown_browser_language_falls_back_to_english(auth_session):
    response = auth_session.get("/leaderboard", headers={"Accept-Language": "fr-FR,fr;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<html lang="en">' in html
    assert "Loading leaderboard..." in html
