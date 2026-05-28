# Postgres Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the TokenLeague MySQL runtime with a compose-managed PostgreSQL service, migrate existing live data, and verify the deployed service works on PostgreSQL.

**Architecture:** Keep the Flask app API and environment-variable contract stable while replacing the database driver and SQL dialect. Add PostgreSQL to compose with `./data/postgres` host persistence, protect runtime data during deploy, and use a one-time migration script to copy live MySQL rows into PostgreSQL.

**Tech Stack:** Python 3.12, Flask, psycopg 3, PostgreSQL 16, Docker Compose, pytest.

---

## File Structure

- Modify `service/requirements.txt`: add PostgreSQL driver while retaining the one-time MySQL migration client.
- Modify `docker-compose.yml`: add `postgres`, configure `web` and `worker` to use it, and bind `./data/postgres`.
- Modify `deploy.sh`: preserve `.env` and `data/` during rsync and create `data/postgres` remotely.
- Modify `.env.example`, `README.md`, and `README_EN.md`: document PostgreSQL defaults.
- Modify `service/db.py`: convert runtime database access from MySQL to PostgreSQL.
- Modify `scripts/run_migrations.py` and `scripts/init_db.py`: convert migration/init flow to PostgreSQL.
- Modify `scripts/migrations/*.py`: convert DDL/introspection to PostgreSQL-safe migrations.
- Create `scripts/migrate_mysql_to_postgres.py`: one-time live data copy with row-count verification.
- Modify `service/tests/test_deploy_assets.py`: encode deployment and PostgreSQL asset expectations.
- Create `service/tests/test_postgres_assets.py`: encode PostgreSQL SQL/dependency expectations.

## Task 1: Add Failing Asset Tests

**Files:**
- Modify: `service/tests/test_deploy_assets.py`
- Create: `service/tests/test_postgres_assets.py`

- [ ] **Step 1: Write the failing tests**

Add assertions that compose includes a `postgres` service, binds `./data/postgres`, no longer exposes MySQL, deploy preserves `.env` and `data/`, app database code imports `psycopg`, and runtime database files no longer import `mysql.connector`.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_deploy_assets.py service/tests/test_postgres_assets.py
```

Expected: FAIL because the current assets still target MySQL and do not contain the new PostgreSQL compose/deploy behavior.

## Task 2: Convert Runtime Database Code

**Files:**
- Modify: `service/requirements.txt`
- Modify: `service/db.py`

- [ ] **Step 1: Replace the runtime dependency and connection**

Use `psycopg` with `dict_row`, default DB port `5432`, and keep `MY_APP_DB_*` plus `MY_KMM_DB_*` aliases.

- [ ] **Step 2: Convert generated ID and upsert SQL**

Use `RETURNING id` for `create_user`; convert `ON DUPLICATE KEY UPDATE` to PostgreSQL `ON CONFLICT`.

- [ ] **Step 3: Run focused tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_token_league.py service/tests/test_auth_flow.py service/tests/test_ldap_auth.py
```

Expected: PASS. These run through in-memory mode and verify public behavior remains unchanged.

## Task 3: Convert Migration And Init Scripts

**Files:**
- Modify: `scripts/run_migrations.py`
- Modify: `scripts/init_db.py`
- Modify: `scripts/migrations/001_init_schema.py`
- Modify: `scripts/migrations/002_add_project_name.py`
- Modify: `scripts/migrations/003_utc_timestamps.py`
- Modify: `scripts/migrations/004_add_cached_tokens.py`
- Modify: `scripts/migrations/005_add_ldap_user_fields.py`
- Modify: `scripts/migrations/006_add_leaderboard_snapshots.py`

- [ ] **Step 1: Convert connection code to psycopg**

Use PostgreSQL connection helpers and `dbname` instead of MySQL `database`.

- [ ] **Step 2: Convert DDL**

Use `SERIAL`, `TIMESTAMP`, `JSONB`, `CHECK`, `UNIQUE`, and `CREATE INDEX IF NOT EXISTS`.

- [ ] **Step 3: Keep old migration filenames**

Preserve migration names so migrated production history remains coherent; make additive migrations idempotent on PostgreSQL.

- [ ] **Step 4: Run syntax and asset tests**

Run:

```bash
python3 -m py_compile scripts/run_migrations.py scripts/init_db.py scripts/migrate_mysql_to_postgres.py scripts/migrations/*.py service/db.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_deploy_assets.py service/tests/test_postgres_assets.py
```

Expected: PASS after the implementation is complete.

## Task 4: Add One-Time Data Migration Script

**Files:**
- Create: `scripts/migrate_mysql_to_postgres.py`

- [ ] **Step 1: Implement source and target connections**

Read MySQL from `MYSQL_SOURCE_HOST`, `MYSQL_SOURCE_PORT`, `MYSQL_SOURCE_DB`, `MYSQL_SOURCE_USER`, and `MYSQL_SOURCE_PWD`. Read PostgreSQL target from `MY_APP_DB_*` / `MY_KMM_DB_*`.

- [ ] **Step 2: Implement deterministic table copy**

Truncate target tables, copy rows in dependency-safe order, preserve IDs, reset sequences, and compare source/target row counts.

- [ ] **Step 3: Run syntax check**

Run:

```bash
python3 -m py_compile scripts/migrate_mysql_to_postgres.py
```

Expected: PASS.

## Task 5: Update Compose, Deploy, And Docs

**Files:**
- Modify: `docker-compose.yml`
- Modify: `deploy.sh`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `README_EN.md`

- [ ] **Step 1: Add PostgreSQL compose service**

Add `postgres:16-alpine`, a healthcheck, env-driven DB/user/password, and `./data/postgres:/var/lib/postgresql/data`.

- [ ] **Step 2: Point web and worker at postgres**

Set `MY_APP_DB_HOST=postgres`, `MY_APP_DB_PORT=5432`, and pass DB name/user/password from `.env`.

- [ ] **Step 3: Protect runtime state in deploy**

Exclude `.env` and `data/` from rsync deletion and ensure `data/postgres` exists on the remote host.

- [ ] **Step 4: Update user docs**

Replace MySQL/MariaDB wording with PostgreSQL deployment instructions and defaults.

- [ ] **Step 5: Run deploy asset tests**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests/test_deploy_assets.py service/tests/test_template_assets.py service/tests/test_postgres_assets.py
```

Expected: PASS.

## Task 6: Local Verification

**Files:**
- No additional file changes.

- [ ] **Step 1: Run full local test suite**

Run:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q service/tests
```

Expected: PASS.

- [ ] **Step 2: Run shell and diff checks**

Run:

```bash
bash -n deploy.sh service/run.sh
python3 -m py_compile service/db.py scripts/*.py scripts/migrations/*.py
git diff --check
```

Expected: all commands exit 0.

## Task 7: Live Migration On homegpu1

**Files:**
- Remote runtime files only: `/home/juns/project/TokenLeague/.env`, `/home/juns/project/TokenLeague/.env.mysql-source`, and `/home/juns/project/TokenLeague/data/postgres`.

- [ ] **Step 1: Backup remote runtime env**

On `homegpu1`, copy `.env` to `.env.mysql-backup-<timestamp>` and create `.env.mysql-source` from the old MySQL values.

- [ ] **Step 2: Switch remote `.env` to PostgreSQL**

Set `MY_APP_DB_HOST=postgres`, `MY_APP_DB_PORT=5432`, `MY_APP_DB_NAME=tokenleague`, `MY_APP_DB_USER=tokenleague_user`, and `MY_APP_DB_PWD`/`POSTGRES_PASSWORD` to the preserved runtime password.

- [ ] **Step 3: Deploy PostgreSQL version**

Run:

```bash
./deploy.sh -n 80
```

Expected: compose starts `postgres`, `web`, and `worker`, and `/health` passes.

- [ ] **Step 4: Stop web and worker for deterministic import**

Run remotely:

```bash
docker compose stop web worker
```

Expected: `postgres` remains running.

- [ ] **Step 5: Import MySQL data into PostgreSQL**

Run remotely:

```bash
docker compose run --rm web python3 /app/scripts/migrate_mysql_to_postgres.py
```

Expected: all table source and target row counts match.

- [ ] **Step 6: Redeploy for final verification**

Run:

```bash
./deploy.sh -n 120
```

Expected: health check passes while connected to PostgreSQL.

- [ ] **Step 7: Verify live state**

Confirm `docker compose ps`, `web` container environment, PostgreSQL row counts, `/health`, and at least one data-reading endpoint.

## Task 8: Bring Migration Commit Back To Main Workspace

**Files:**
- All migration-related files from the feature worktree.

- [ ] **Step 1: Commit implementation in the feature worktree**

Run:

```bash
git add .
git commit -m "feat: migrate TokenLeague to postgres"
```

Expected: commit contains only migration-related changes.

- [ ] **Step 2: Cherry-pick into the original detached workspace**

Run from `/Users/juns/project/TokenLeague`:

```bash
git cherry-pick <implementation-commit>
```

Expected: existing unrelated local edits remain intact.
