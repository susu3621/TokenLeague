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


def test_account_page_renders_chinese_copy(auth_session):
    response = auth_session.get("/account", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "个人设置" in html
    assert "在一个页面中管理你的 API Key 和密码。" in html
    assert "API Key" in html
    assert "使用这个 Hook Key 为你自己的账号上报用量事件。" in html
    assert "当前 API Key" in html
    assert "密码" in html
    assert "为当前登录账号设置新密码。" in html
    assert "新密码" in html
    assert "Could not copy API key" not in html
    assert "Rotating API key..." not in html
    assert "Failed to rotate API key" not in html
    assert "New password is required" not in html
    assert "Saving password..." not in html
    assert "Failed to save password" not in html


def test_user_detail_page_renders_chinese_copy(auth_session):
    response = auth_session.get("/users/1", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<title>用户详情 |" in html
    assert "用户详情 for admin within the selected week window." in html
    assert "加载中..." in html
    assert "当前时间范围内没有数据。" in html
    assert "No project data." not in html
    assert "No model data." not in html
    assert "No prompt events recorded." not in html
    assert "No timeline data available." not in html
    assert "今天" in html
    assert "过去7天" in html
    assert "过去30天" in html
    assert "过去90天" in html
    assert "<span hidden>今天 过去7天 过去30天 过去90天</span>" not in html
