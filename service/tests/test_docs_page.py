import json
import re


def markdown(response):
    match = re.search(r'<script id="raw-markdown" type="application/json">(.*?)</script>', response.get_data(as_text=True), re.S)
    return json.loads(match.group(1))


def test_docs_page_requires_login(client):
    response = client.get("/docs")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_docs_page_renders_current_project_markdown_source(auth_session):
    response = auth_session.get("/docs")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague Documentation" in html
    assert "record AI assistant token usage and prompt efficiency" in html


def test_docs_page_prefers_chinese_variant_when_available(auth_session):
    response = auth_session.get("/docs", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague 文档" in html
    assert "记录 AI 助手的 Token 用量与使用效率" in markdown(response)


def test_docs_page_prefers_cookie_locale_over_accept_language(auth_session):
    auth_session.set_cookie("tokenleague_locale", "zh-CN")

    response = auth_session.get("/docs", headers={"Accept-Language": "en-US,en;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague 文档" in html
    assert "记录 AI 助手的 Token 用量与使用效率" in markdown(response)


def test_docs_page_can_force_english_with_cookie(auth_session):
    auth_session.set_cookie("tokenleague_locale", "en")

    response = auth_session.get("/docs", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague Documentation" in html
    assert "record AI assistant token usage and prompt efficiency" in html


def test_docs_page_falls_back_to_english_when_localized_file_is_missing(auth_session):
    response = auth_session.get("/docs/HOOKS.md", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "TokenLeague Hooks" in html
    assert "collects token usage statistics" in html


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
    assert "仅本地化内容" in markdown(response)
    assert "Missing document: GUIDE.md" not in html


def test_project_guide_renders_only_allowed_root_documents(auth_session, monkeypatch, tmp_path):
    import app as app_module

    (tmp_path / 'service').mkdir()
    (tmp_path / 'README.md').write_text('# 项目说明\n\n部署步骤', encoding='utf-8')
    monkeypatch.setattr(app_module, 'BASE_DIR', tmp_path / 'service')
    response = auth_session.get('/docs/project/README.md')
    assert response.status_code == 200
    assert '部署步骤' in markdown(response)
    assert auth_session.get('/docs/project/.env').status_code == 404
    assert auth_session.get('/docs/project/service/app.py').status_code == 404


def test_document_assets_are_authenticated_and_sent_as_images(client, auth_session, monkeypatch, tmp_path):
    import app as app_module

    assets = tmp_path / 'assets'
    assets.mkdir()
    content = b'\x89PNG\r\n\x1a\nimage-content'
    (assets / 'sample.png').write_bytes(content)
    monkeypatch.setattr(app_module, 'DOCS_DIR', tmp_path)
    # auth_session and client share the same test client; explicitly clear it first.
    with client.session_transaction() as session:
        session.clear()
    assert client.get('/docs/assets/sample.png').status_code == 302
    with client.session_transaction() as session:
        session['user_id'] = 1
    response = client.get('/docs/assets/sample.png')
    assert response.status_code == 200
    assert response.content_type == 'image/png'
    assert response.data == content
    assert client.get('/docs/assets/../README.md').status_code == 404
