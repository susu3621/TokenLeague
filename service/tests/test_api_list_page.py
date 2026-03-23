def test_build_api_list_contains_template_routes():
    from app import _build_api_list

    apis = _build_api_list()

    assert any(
        api["endpoint"] == "/api/change-password" and api["methods"] == ["POST"]
        for api in apis
    )

    change_password = next(
        api
        for api in apis
        if api["endpoint"] == "/api/change-password" and api["methods"] == ["POST"]
    )
    assert change_password["description"] == "Change current user password"


def test_api_page_renders_generated_api_items(auth_session):
    response = auth_session.get("/api")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/api/change-password" in html
    assert "Change current user password" in html
