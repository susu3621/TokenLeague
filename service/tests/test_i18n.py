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
    assert "跟踪各类 Agent 运行中的 Token 用量，并按天、周和全时段比较用户排名。" in html
    assert "需要恢复访问？" in html
    assert "本地管理员登录" in html


def test_local_admin_login_page_renders_chinese_copy(client):
    response = client.get("/login/local-admin", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "本地管理员恢复登录" in html
    assert "仅当 LDAP 登录不可用且你需要修复 LDAP 配置时，才使用此页面。" in html
    assert "用户名" in html
    assert "密码" in html


def test_leaderboard_page_renders_chinese_shell_copy(auth_session):
    response = auth_session.get("/leaderboard", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Token 排行榜" in html
    assert "此页面展示最新的预计算默认排行榜快照。" in html
    assert "排名可能比最新的用量事件最多滞后一小时。" in html
    assert "更新时间：" in html
    assert "正在加载排行榜..." in html
    assert "排行榜尚在准备中" in html
    assert "排名" in html
    assert "用户" in html
    assert "总 Token" in html
    assert "最近活跃时间" in html


def test_unknown_browser_language_falls_back_to_english(auth_session):
    response = auth_session.get("/leaderboard", headers={"Accept-Language": "fr-FR,fr;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<html lang="en">' in html
    assert "This page loads the latest precomputed default leaderboard snapshot." in html
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
    assert "所选过去7天时间范围内的 admin 用户详情。" in html
    assert "加载中..." in html
    assert "当前时间范围内没有数据。" in html
    assert "No project data." not in html
    assert "No model data." not in html
    assert "No prompt events recorded." not in html
    assert "No timeline data available." not in html
    assert "总 Token" in html
    assert "Prompt 数" in html
    assert "任务数" in html
    assert "每次 Prompt 平均 Token" in html
    assert "用量时间线" in html
    assert "项目分布" in html
    assert "模型分布" in html
    assert "Agent 分布" in html
    assert "最近 Prompt 事件" in html
    assert "项目" in html
    assert "事件" in html
    assert "完成时间" in html
    assert "今天" in html
    assert "过去7天" in html
    assert "过去30天" in html
    assert "过去90天" in html
    assert "<span hidden>今天 过去7天 过去30天 过去90天</span>" not in html
    assert 'aria-label="时间范围选择器"' in html


def test_admin_pages_render_chinese_shell_copy(auth_session):
    pages = {
        "/settings": ["配置已登录页面中显示的 TokenLeague 标题和副标题。", "当前用户"],
        "/api": ["此页面根据 Flask 路由表自动生成。"],
        "/admin/users": ["创建排行榜用户，并轮换他们专用的上报 Hook Key。"],
        "/admin/ldap": [
            "配置 LDAP 认证、测试连接，并将目录用户同步到本地用户表。",
            "目录操作",
            "当前本地用户",
        ],
        "/admin/agents": ["这里展示用量上报中观察到的 Agent 类型、版本和模型组合。"],
    }

    for path, snippets in pages.items():
        response = auth_session.get(path, headers={"Accept-Language": "zh-CN,zh;q=0.9"})

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        for snippet in snippets:
            assert snippet in html
