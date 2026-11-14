from pathlib import Path
import re
import runpy
import subprocess

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("debug_value,expected", [(None, False), ("1", True)])
def test_application_startup_requires_explicit_debug_opt_in(monkeypatch, debug_value, expected):
    from flask import Flask

    if debug_value is None:
        monkeypatch.delenv("FLASK_DEBUG", raising=False)
    else:
        monkeypatch.setenv("FLASK_DEBUG", debug_value)
    called = {}
    monkeypatch.setattr(Flask, "run", lambda self, **options: called.update(options))
    runpy.run_path(str(PROJECT_ROOT / "service" / "app.py"), run_name="__main__")
    assert called["debug"] is expected


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
    assert "postgres:18.4-alpine3.23" in compose
    assert "./data/postgres:/var/lib/postgresql\n" in compose
    assert "PGDATA: /var/lib/postgresql/18/docker" in compose
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


@pytest.mark.parametrize("git_is_file", [True, False])
def test_deploy_excludes_preserve_git_files_and_directories(tmp_path, git_is_file):
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    marker = target / ".git"
    if git_is_file:
        marker.write_text("gitdir: /private/worktree/git-metadata\n")
    else:
        marker.mkdir()
        (marker / "config").write_text("existing metadata\n")
    (source / "application.py").write_text("deployed code\n")
    (target / ".env").write_text("PRESERVE_ME=1\n")
    (target / "data").mkdir()
    (target / "data" / "preserve").write_text("existing data\n")
    script = (PROJECT_ROOT / "deploy.sh").read_text(encoding="utf-8")
    excludes = [f"--exclude={value}" for value in re.findall(r"--exclude='([^']+)'", script)]
    subprocess.run(["rsync", "-rlt", "--delete", *excludes, f"{source}/", f"{target}/"], check=True, capture_output=True)
    assert marker.exists()
    assert (marker.read_text() if git_is_file else (marker / "config").read_text()).strip()
    assert (target / ".env").read_text() == "PRESERVE_ME=1\n"
    assert (target / "data" / "preserve").read_text() == "existing data\n"
    assert (target / "application.py").read_text() == "deployed code\n"


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
