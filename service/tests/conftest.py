from pathlib import Path
import os
import sys

import pytest


SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

os.environ.setdefault("MY_FLASK_SECRET_KEY", "template-test-secret")
os.environ.setdefault("MY_TEMPLATE_USE_IN_MEMORY_STORE", "1")


@pytest.fixture
def app():
    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture
def client(app):
    with app.test_client() as client:
        yield client


@pytest.fixture
def auth_session(client):
    with client.session_transaction() as session:
        session["user_id"] = 1
        session["username"] = "admin"
        session["role"] = "admin"
    return client


@pytest.fixture(autouse=True)
def reset_store():
    try:
        from db import reset_in_memory_state
    except ModuleNotFoundError:
        yield
        return

    reset_in_memory_state()
    yield
