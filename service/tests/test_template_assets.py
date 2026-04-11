from pathlib import Path


TEMPLATE_DIR = Path(__file__).resolve().parents[2]


def test_template_bootstrap_files_exist():
    expected_files = [
        "README.md",
        "README_EN.md",
        ".env.example",
        "Dockerfile",
        "docker-compose.yml",
        "service/requirements.txt",
        "service/run.sh",
        "service/static/pwa/README.md",
        "scripts/init_db.py",
        "scripts/run_migrations.py",
        "scripts/migrations/001_init_schema.py",
    ]

    for relative_path in expected_files:
        assert (TEMPLATE_DIR / relative_path).is_file(), relative_path


def test_init_schema_covers_base_tables():
    content = (TEMPLATE_DIR / "scripts" / "migrations" / "001_init_schema.py").read_text(
        encoding="utf-8"
    )

    assert "users" in content
    assert "system_settings" in content
    assert "prompt_events" in content
    assert "task_runs" in content
    assert "schema_migrations" not in content
    assert "ADD COLUMN IF NOT EXISTS" not in content
    assert "FOREIGN KEY" not in content


def test_template_readme_documents_tokenleague_product_setup():
    content_zh = (TEMPLATE_DIR / "README.md").read_text(encoding="utf-8")
    content_en = (TEMPLATE_DIR / "README_EN.md").read_text(encoding="utf-8")

    assert "团队级 ai token 观测" in content_zh.lower()
    assert "docker compose 部署（推荐）" in content_zh.lower()
    assert "本地 python 运行" in content_zh.lower()
    assert "team-level ai token analytics" in content_en.lower()
    assert "docker compose (recommended)" in content_en.lower()
    assert "local python setup" in content_en.lower()
