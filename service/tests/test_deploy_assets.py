from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_deploy_script_targets_tokenleague_defaults():
    content = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert "REMOTE_PATH=\"~/project/TokenLeague\"" in content
    assert "HEALTH_PORT=5006" in content
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
    assert "\n  postgres:\n" in compose
    assert "postgres:16" in compose
    assert "./data/postgres:/var/lib/postgresql/data" in compose
    assert "env_file:" in compose
    assert "MY_APP_DB_HOST: mysql" not in compose
    assert "MY_APP_DB_HOST: postgres" in compose
    assert "EXPOSE 5006" in dockerfile
    assert "PORT=5006" in env_example
    assert "MY_APP_DB_PORT=5432" in env_example


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


def test_deploy_preserves_runtime_env_and_postgres_data():
    content = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")

    assert "--exclude='.env'" in content
    assert "--exclude='.env.*'" in content
    assert "--exclude='data/'" in content
    assert "mkdir -p data/postgres" in content


def test_project_name_schema_assets_exist():
    db_content = (PROJECT_ROOT / "service" / "db.py").read_text(encoding="utf-8")
    init_schema = (PROJECT_ROOT / "scripts" / "migrations" / "001_init_schema.py").read_text(encoding="utf-8")
    add_project_name = PROJECT_ROOT / "scripts" / "migrations" / "002_add_project_name.py"

    assert "project_name" in db_content
    assert "project_name" in init_schema
    assert add_project_name.exists()
    assert "project_name" in add_project_name.read_text(encoding="utf-8")


def test_top_level_readmes_cover_local_and_docker_installation():
    readme_zh = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = (PROJECT_ROOT / "README_EN.md").read_text(encoding="utf-8")

    assert "Docker Compose (Recommended)" in readme_en
    assert "Local Python Setup" in readme_en
    assert "Hook Installation" in readme_en
    assert "Docker Compose 部署（推荐）" in readme_zh
    assert "本地 Python 运行" in readme_zh
    assert "Hook 安装" in readme_zh


def test_deploy_assets_document_restart_requirements():
    deploy_script = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    readme_zh = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = (PROJECT_ROOT / "README_EN.md").read_text(encoding="utf-8")

    assert compose.count("restart: unless-stopped") >= 2
    assert "systemctl is-enabled docker" in deploy_script
    assert "restart: unless-stopped" in readme_en
    assert "systemctl enable --now docker" in readme_en
    assert "restart: unless-stopped" in readme_zh
    assert "systemctl enable --now docker" in readme_zh
