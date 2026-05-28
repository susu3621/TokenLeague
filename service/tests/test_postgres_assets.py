from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_database_code_uses_psycopg_not_mysql_connector():
    runtime_files = [
        PROJECT_ROOT / "service" / "db.py",
        PROJECT_ROOT / "scripts" / "run_migrations.py",
        PROJECT_ROOT / "scripts" / "init_db.py",
        PROJECT_ROOT / "scripts" / "migrations" / "001_init_schema.py",
    ]

    for path in runtime_files:
        content = path.read_text(encoding="utf-8")
        assert "import psycopg" in content or "from psycopg" in content
        assert "mysql.connector" not in content


def test_postgres_schema_assets_use_postgres_dialect():
    init_schema = (PROJECT_ROOT / "scripts" / "migrations" / "001_init_schema.py").read_text(
        encoding="utf-8"
    )
    run_migrations = (PROJECT_ROOT / "scripts" / "run_migrations.py").read_text(encoding="utf-8")

    assert "SERIAL PRIMARY KEY" in init_schema
    assert "JSONB" in init_schema
    assert "CHECK (role IN" in init_schema
    assert "CREATE INDEX IF NOT EXISTS" in init_schema
    assert "AUTO_INCREMENT" not in init_schema
    assert "ENGINE=InnoDB" not in init_schema
    assert "SERIAL PRIMARY KEY" in run_migrations


def test_mysql_to_postgres_migration_script_documents_required_source_env():
    content = (PROJECT_ROOT / "scripts" / "migrate_mysql_to_postgres.py").read_text(
        encoding="utf-8"
    )

    for token in [
        "MYSQL_SOURCE_HOST",
        "MYSQL_SOURCE_PORT",
        "MYSQL_SOURCE_DB",
        "MYSQL_SOURCE_USER",
        "MYSQL_SOURCE_PWD",
    ]:
        assert token in content
    assert "TRUNCATE" in content
    assert "setval" in content
