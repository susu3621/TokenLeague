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


def test_build_api_list_localizes_descriptions_for_chinese_locale():
    from app import _build_api_list

    apis = _build_api_list(locale="zh-CN")

    change_password = next(
        api
        for api in apis
        if api["endpoint"] == "/api/change-password" and api["methods"] == ["POST"]
    )
    assert change_password["description"] == "修改当前用户密码"

    user_stats = next(
        api
        for api in apis
        if api["endpoint"] == "/api/users/<int:user_id>/stats" and api["methods"] == ["GET"]
    )
    assert user_stats["description"] == "获取单个用户 Token 统计"


def test_build_api_list_contains_account_rotation_endpoint():
    from app import _build_api_list

    apis = _build_api_list()

    assert any(
        api["endpoint"] == "/api/account/rotate-hook-key" and api["methods"] == ["POST"]
        for api in apis
    )


def test_api_page_renders_generated_api_items(auth_session):
    response = auth_session.get("/api")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/api/change-password" in html
    assert "Change current user password" in html


def test_api_page_renders_localized_descriptions_for_chinese_locale(auth_session):
    response = auth_session.get("/api", headers={"Accept-Language": "zh-CN,zh;q=0.9"})

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/api/change-password" in html
    assert "修改当前用户密码" in html
    assert "获取单个用户 Token 统计" in html
