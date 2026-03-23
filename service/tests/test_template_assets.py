from pathlib import Path


TEMPLATE_DIR = Path(__file__).resolve().parents[2]


def test_template_bootstrap_files_exist():
    expected_files = [
        "README.md",
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


def test_template_readme_documents_reusable_foundation():
    content = (TEMPLATE_DIR / "README.md").read_text(encoding="utf-8")

    assert "reusable foundation" in content.lower()
    assert "what is intentionally excluded" in content.lower()
    assert "how to start" in content.lower()
