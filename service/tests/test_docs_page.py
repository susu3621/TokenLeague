def test_docs_page_requires_login(client):
    response = client.get("/docs")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_docs_page_renders_template_markdown_source(auth_session):
    response = auth_session.get("/docs")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Template Project Docs" in html
    assert "Use this directory as the base" in html
