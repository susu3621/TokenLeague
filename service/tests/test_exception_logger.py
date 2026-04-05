def test_missing_route_does_not_log_http_404(client, capsys):
    response = client.get("/definitely-missing")

    captured = capsys.readouterr()

    assert response.status_code == 404
    assert "[template-error]" not in captured.err
