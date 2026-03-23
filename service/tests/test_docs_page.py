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
