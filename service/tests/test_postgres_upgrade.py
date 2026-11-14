"""Guard tests plus an opt-in, isolated Docker migration and failure exercise."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("upgrade_postgres", PROJECT_ROOT / "scripts/upgrade_postgres.py")
upgrade_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade_module)


@pytest.mark.parametrize("layout", ["legacy-16", "legacy-18", "unknown", "17"])
def test_regular_deploy_rejects_incompatible_or_misplaced_clusters(tmp_path, monkeypatch, layout):
    upgrade = upgrade_module.Upgrade(tmp_path)
    monkeypatch.setattr(upgrade, "layout", lambda: layout)
    with pytest.raises(RuntimeError, match="data layout"):
        upgrade.check()


@pytest.mark.parametrize("layout", ["18", "empty"])
def test_regular_deploy_accepts_new_or_migrated_layout(tmp_path, monkeypatch, layout):
    upgrade = upgrade_module.Upgrade(tmp_path)
    monkeypatch.setattr(upgrade, "layout", lambda: layout)
    upgrade.check()


def test_unfinished_migration_blocks_replay_before_docker_access(tmp_path):
    upgrade = upgrade_module.Upgrade(tmp_path)
    upgrade.data.mkdir()
    upgrade_module.save(upgrade.receipt, {"state": "promoting"})
    with pytest.raises(RuntimeError, match="Unfinished migration"):
        upgrade.migrate()


def test_completed_migration_cannot_silently_initialize_an_empty_cluster(tmp_path, monkeypatch):
    upgrade = upgrade_module.Upgrade(tmp_path)
    upgrade.data.mkdir()
    upgrade_module.save(upgrade.receipt, {"state": "complete"})
    monkeypatch.setattr(upgrade, "layout", lambda: "empty")
    with pytest.raises(RuntimeError, match="refusing initialization"):
        upgrade.check()


@pytest.mark.parametrize("username", ["tokenleague_user", 'name with "quotes"'])
def test_globals_restore_preserves_password_and_other_roles(username):
    quoted = upgrade_module.quote_identifier(username)
    content = f"CREATE ROLE {quoted};\nALTER ROLE {quoted} WITH LOGIN PASSWORD 'test-only';\nCREATE ROLE reader;\n"
    restored = upgrade_module.restore_globals(content, username)
    assert f"CREATE ROLE {quoted};" not in restored
    assert f"ALTER ROLE {quoted} WITH LOGIN PASSWORD 'test-only';" in restored
    assert "CREATE ROLE reader;" in restored


@pytest.mark.skipif(os.getenv("TOKENLEAGUE_RUN_POSTGRES_UPGRADE_TEST") != "1",
                    reason="Set TOKENLEAGUE_RUN_POSTGRES_UPGRADE_TEST=1 for isolated Docker checks")
@pytest.mark.parametrize("mismatch", [False, True], ids=["migration", "verification-failure"])
def test_docker_upgrade_preserves_contents_and_blocks_bad_cutover(tmp_path, mismatch, monkeypatch):
    name = f"tokenleague-upgrade-test-{uuid.uuid4().hex[:10]}"
    user = "upgrade_test_user"
    source_password = uuid.uuid4().hex
    upgrade = upgrade_module.Upgrade(tmp_path)
    upgrade.cluster.mkdir(parents=True)
    compose = {"name": name, "services": {
        "postgres": {"image": "postgres:16-alpine", "environment": {
            "POSTGRES_USER": user, "POSTGRES_DB": "tokenleague", "POSTGRES_PASSWORD": source_password},
            "volumes": [f"{upgrade.cluster}:/var/lib/postgresql/data"], "ports": ["127.0.0.1::5432"]},
        "web": {"image": "postgres:16-alpine", "entrypoint": ["sleep", "infinity"], "stop_signal": "SIGKILL"},
        "worker": {"image": "postgres:16-alpine", "entrypoint": ["sleep", "infinity"], "stop_signal": "SIGKILL"},
    }}
    config = tmp_path / "docker-compose.yml"
    upgrade_module.save(config, compose)
    candidate = None
    try:
        upgrade.dc("up", "-d", "--pull", "never")
        source = upgrade.dc("ps", "-q", "postgres").decode().strip()
        upgrade.wait(source, user)
        upgrade.sql(source, user, "tokenleague", """
            CREATE TABLE samples (id bigserial PRIMARY KEY, payload jsonb, tags text[],
                                  recorded_at timestamptz, amount numeric(20,4), parent bigint REFERENCES samples);
            INSERT INTO samples(payload, tags, recorded_at, amount) VALUES
                ('{"name":"测试","nested":[1,null,true]}', ARRAY['a','b'], '2026-01-01T03:04:05Z', 123.4567),
                (NULL, ARRAY[]::text[], NULL, NULL);
            SELECT setval('samples_id_seq', 99, false);
            CREATE ROLE reader;
            GRANT SELECT ON samples TO reader;
        """)
        compose["services"]["postgres"]["image"] = upgrade_module.IMAGE
        compose["services"]["postgres"]["environment"]["PGDATA"] = upgrade_module.PGDATA
        compose["services"]["postgres"]["volumes"] = [f"{upgrade.cluster}:/var/lib/postgresql"]
        upgrade_module.save(config, compose)
        if mismatch:
            inventory = upgrade.inventory

            def incorrect_inventory(container, *args):
                result = inventory(container, *args)
                if container.startswith("tokenleague-pg18-"):
                    result["tokenleague"]["relation:public.samples"]["rows"] += 1
                return result

            upgrade.inventory = incorrect_inventory
            with pytest.raises(RuntimeError, match="Restored inventory differs"):
                upgrade.migrate()
            receipt = json.loads(upgrade.receipt.read_text())
            assert receipt["state"] == "backed_up"
            assert upgrade.layout() == "legacy-16"
            assert not Path(receipt["retained_source"]).exists()
            assert upgrade.sql(source, user, "postgres", "SHOW default_transaction_read_only;") == "on"
            with pytest.raises(RuntimeError, match="Unfinished migration"):
                upgrade.check()
        else:
            upgrade.migrate()
            receipt = json.loads(upgrade.receipt.read_text())
            assert receipt["state"] == "complete"
            assert receipt["verified_rows"] == 2
            assert Path(receipt["retained_source"]).exists()
            upgrade.check()
            deployed = upgrade.dc("ps", "-q", "postgres").decode().strip()
            assert upgrade.sql(deployed, user, "tokenleague", "SELECT nextval('samples_id_seq');") == "99"
            assert upgrade.sql(deployed, user, "tokenleague", "SELECT has_table_privilege('reader','samples','SELECT');") == "t"
            # A subsequent ordinary deployment must reuse the persisted cluster.
            upgrade.dc("up", "-d", "--no-deps", "--force-recreate", "postgres")
            deployed = upgrade.dc("ps", "-q", "postgres").decode().strip()
            upgrade.wait(deployed, user)
            assert upgrade.sql(deployed, user, "tokenleague", "SELECT count(*) FROM samples;") == "2"
            verify_application(upgrade, deployed, user, source_password, monkeypatch)
        for service in ("web", "worker"):
            assert not upgrade.dc("ps", "--status", "running", "-q", service).strip()
    finally:
        if upgrade.receipt.exists():
            candidate = json.loads(upgrade.receipt.read_text())["candidate"]
        if candidate:
            subprocess.run(["docker", "rm", "-f", candidate], capture_output=True)
        upgrade.dc("down", "--volumes", "--remove-orphans")


def verify_application(upgrade, container, db_user, password, monkeypatch):
    """Exercise actual schema migrations, driver writes and authenticated reads."""
    details = json.loads(upgrade_module.run(["docker", "inspect", container]))[0]
    port = details["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
    for key, value in {"MY_TEMPLATE_USE_IN_MEMORY_STORE": "0", "MY_APP_DB_HOST": "127.0.0.1",
                       "MY_APP_DB_PORT": port, "MY_APP_DB_NAME": "tokenleague",
                       "MY_APP_DB_USER": db_user, "MY_APP_DB_PWD": password}.items():
        monkeypatch.setenv(key, value)
    subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/run_migrations.py")],
                   env=os.environ.copy(), check=True, capture_output=True)
    import db
    from app import app

    user = db.create_user("upgrade_acceptance", "isolated-test-only")
    started = datetime.now(timezone.utc) - timedelta(minutes=1)
    finished = started + timedelta(seconds=5)
    common = {"project_name": "upgrade-test", "agent_type": "codex", "agent_version": "test",
              "model_name": "test", "input_token_count": 10, "output_token_count": 5}
    app.config.update(TESTING=True)
    with app.test_client() as client:
        headers = {"X-Hook-Key": user["hook_key"]}
        event = {**common, "external_event_id": "event-1", "task_id": "task-1",
                 "prompt_started_at": started.isoformat(), "prompt_finished_at": finished.isoformat()}
        for _ in range(2):
            assert client.post("/api/ingest/prompt-event", json=event, headers=headers).status_code == 200
        task = {**common, "external_task_id": "task-1", "prompt_count": 1,
                "started_at": started.isoformat(), "finished_at": finished.isoformat()}
        assert client.post("/api/ingest/task-run", json=task, headers=headers).status_code == 200
        turn = {**common, "session_id": "task-1", "turn_id": "turn-1", "started_at": started.isoformat(),
                "finished_at": finished.isoformat(), "duration_ms": 5000,
                "timing_source": "timestamps", "tool_status": "unavailable"}
        assert client.post("/api/ingest/turn-timing", json=turn, headers=headers).status_code == 200
        subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/refresh_leaderboard_snapshot.py")],
                       env=os.environ.copy(), check=True, capture_output=True)
        with client.session_transaction() as session:
            session["user_id"] = user["id"]
        snapshot = client.get("/api/leaderboard/default").get_json()
        row = next(row for row in snapshot["rows"] if row["user_id"] == user["id"])
        assert (row["total_token_count"], row["prompt_count"], row["task_count"]) == (15, 1, 1)
        for path in ("/leaderboard", f"/users/{user['id']}", "/api/leaderboard",
                     f"/api/users/{user['id']}/stats", "/api/timing"):
            assert client.get(path).status_code == 200
