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


def test_docs_page_prefers_cookie_locale_over_accept_language(auth_session):
    auth_session.set_cookie("tokenleague_locale", "zh-CN")

    response = auth_session.get("/docs", headers={"Accept-Language": "en-US,en;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague 文档" in html
    assert "Token 使用排行榜应用" in html


def test_docs_page_can_force_english_with_cookie(auth_session):
    auth_session.set_cookie("tokenleague_locale", "en")

    response = auth_session.get("/docs", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague Documentation" in html
    assert "token usage leaderboard application" in html


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


def test_docs_page_handles_localized_only_docs_without_english_counterpart(
    auth_session, monkeypatch, tmp_path
):
    import app as app_module

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "GUIDE.zh-CN.md").write_text("# 仅中文指南\n\n内容", encoding="utf-8")
    monkeypatch.setattr(app_module, "DOCS_DIR", docs_dir)

    doc_list = app_module._get_doc_list("en")

    assert doc_list == [{"path": "GUIDE.md", "title": "仅中文指南"}]

    response = auth_session.get("/docs")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "仅中文指南" in html


def test_docs_page_resolves_logical_path_to_localized_only_doc_for_english_requests(
    auth_session, monkeypatch, tmp_path
):
    import app as app_module

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "GUIDE.zh-CN.md").write_text("# 仅中文指南\n\n仅本地化内容", encoding="utf-8")
    monkeypatch.setattr(app_module, "DOCS_DIR", docs_dir)

    response = auth_session.get("/docs/GUIDE.md")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "仅中文指南" in html
    assert "仅本地化内容" in html
    assert "Missing document: GUIDE.md" not in html
