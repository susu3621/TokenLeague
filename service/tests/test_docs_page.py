def test_docs_page_requires_login(client):
    response = client.get("/docs")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_docs_page_renders_current_project_markdown_source(auth_session):
    response = auth_session.get("/docs")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague Documentation" in html
    assert "token usage leaderboard application" in html


def test_docs_page_prefers_chinese_variant_when_available(auth_session):
    response = auth_session.get("/docs", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague 文档" in html
    assert "Token 使用排行榜应用" in html


def test_docs_page_falls_back_to_english_when_localized_file_is_missing(auth_session):
    response = auth_session.get("/docs/HOOKS.md", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague Hooks" in html
    assert "automatically track token usage" in html


def test_docs_sidebar_does_not_duplicate_localized_variants(auth_session):
    response = auth_session.get("/docs", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "README.zh-CN.md" not in html
    assert html.count('href="/docs/README.md"') == 1
