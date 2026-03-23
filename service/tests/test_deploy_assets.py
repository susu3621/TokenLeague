from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_deploy_script_targets_tokenleague_defaults():
    content = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert "REMOTE_PATH=\"~/project/TokenLeague\"" in content
    assert "HEALTH_PORT=5006" in content
    assert "--exclude='.env'" not in content
    assert "personal-information-flow" not in content
    assert "MY_API_KEY_ZHIPU" not in content


def test_runtime_assets_use_port_5006():
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert 'PORT: 5006' in compose
    assert '"5006:5006"' in compose
    assert '"3306:3306"' not in compose
    assert "\n  mysql:\n" not in compose
    assert "env_file:" in compose
    assert "MY_APP_DB_HOST: mysql" not in compose
    assert "EXPOSE 5006" in dockerfile
    assert "PORT=5006" in env_example


def test_db_scripts_support_kmm_env_aliases():
    expected_tokens = [
        "MY_KMM_DB_HOST",
        "MY_KMM_DB_NAME",
        "MY_KMM_DB_USER",
        "MY_KMM_DB_PWD",
    ]
    files = [
        PROJECT_ROOT / "service" / "db.py",
        PROJECT_ROOT / "scripts" / "init_db.py",
        PROJECT_ROOT / "scripts" / "run_migrations.py",
        PROJECT_ROOT / "scripts" / "migrations" / "001_init_schema.py",
    ]

    for path in files:
        content = path.read_text(encoding="utf-8")
        for token in expected_tokens:
            assert token in content, f"{token} missing in {path.name}"
