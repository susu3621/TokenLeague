# TokenLeague Postgres Migration Design

## Context

TokenLeague currently uses MySQL 5.7 through `mysql-connector-python`.
The live deployment on `homegpu1` runs only the `web` and `worker`
containers and points them at an external MySQL service through the
legacy `MY_KMM_DB_*` variables.

The live MySQL database is `tokenleague` and currently contains these
tables:

- `schema_migrations`
- `users`
- `system_settings`
- `prompt_events`
- `task_runs`
- `leaderboard_snapshots`

The target deployment must use PostgreSQL, with persistent data stored
under:

```text
/home/juns/project/TokenLeague/data/postgres
```

## Goals

- Replace MySQL with PostgreSQL as the application database.
- Run PostgreSQL as part of `docker-compose.yml`.
- Bind PostgreSQL storage to `/home/juns/project/TokenLeague/data/postgres`.
- Migrate existing MySQL data into PostgreSQL.
- Redeploy with `deploy.sh` and verify the service still works while
  connected to PostgreSQL.

## Non-Goals

- Maintain long-term dual MySQL/PostgreSQL runtime support.
- Rewrite the Flask app around an ORM.
- Change hook payload formats or public API contracts.
- Change unrelated backfill behavior.

## Architecture

TokenLeague will become a PostgreSQL-backed Flask service. The app keeps
the existing environment-variable names (`MY_APP_DB_*` and the legacy
`MY_KMM_DB_*` aliases) so scripts and deployments can switch database
engines without introducing a second public config contract.

`docker-compose.yml` will add a `postgres` service. `web` and `worker`
will depend on it and connect to the compose-internal host name
`postgres`. The Postgres container will mount the host directory
`./data/postgres` to `/var/lib/postgresql/data`, which resolves to
`/home/juns/project/TokenLeague/data/postgres` on `homegpu1`.

`deploy.sh` will protect runtime state by excluding `.env` and `data/`
from rsync deletion. The remote `.env` will be updated during migration
to point at the compose-managed PostgreSQL service.

## Database Access

The Python dependency changes from `mysql-connector-python` to
`psycopg[binary]`.

The database module keeps its public functions and in-memory test mode.
Only the database implementation changes:

- connections use `psycopg.connect`;
- row access uses dictionary rows;
- inserts that need generated IDs use `RETURNING id`;
- MySQL `ON DUPLICATE KEY UPDATE` becomes PostgreSQL
  `ON CONFLICT ... DO UPDATE`;
- JSON payloads are stored as JSONB-compatible strings;
- timestamps remain UTC-normalized before storage and parsing.

## Schema And Migrations

The migration runner remains a simple ordered Python migration runner,
but its migration table and schema DDL use PostgreSQL syntax.

The base schema uses:

- `SERIAL PRIMARY KEY` for generated IDs;
- `VARCHAR` and `TEXT` for text values;
- `JSONB` for metadata and leaderboard rows;
- `CHECK` constraints instead of MySQL `ENUM`;
- explicit `UNIQUE` constraints and indexes.

Existing migration filenames stay the same so a fresh PostgreSQL database
records the same logical migration history. Later migration files become
PostgreSQL-safe no-ops when their schema changes are already present in
the base schema.

## Data Migration

A new script migrates data from the live MySQL source to the PostgreSQL
target. It reads MySQL credentials from `MYSQL_SOURCE_*` variables and
PostgreSQL credentials from the existing `MY_APP_DB_*` / `MY_KMM_DB_*`
variables.

The script migrates tables in dependency-safe order:

1. `schema_migrations`
2. `users`
3. `system_settings`
4. `prompt_events`
5. `task_runs`
6. `leaderboard_snapshots`

For each table, it truncates the PostgreSQL target table before loading
the rows. It preserves numeric IDs and then resets PostgreSQL sequences
to the imported maximum IDs. It prints source and target row counts and
fails if any count differs.

## Deployment Flow

The live migration flow is:

1. Capture current MySQL row counts.
2. Deploy the code containing PostgreSQL support.
3. Create or update the remote `.env` so the app points at `postgres:5432`.
4. Start PostgreSQL with compose.
5. Run PostgreSQL migrations.
6. Run the MySQL-to-PostgreSQL data migration.
7. Start `web` and `worker` with `deploy.sh`.
8. Verify `/health`, container environment, row counts, and selected UI/API
   endpoints.

## Error Handling

- If PostgreSQL is not ready, compose health checks and migration commands
  fail before the app can be considered migrated.
- If any imported table count differs from MySQL, the migration script
  exits non-zero.
- If app health checks fail after deployment, `deploy.sh` prints recent
  web logs and exits non-zero.
- The old MySQL container and source data are not deleted during this
  change, so rollback remains possible by restoring the previous `.env`
  and code if needed.

## Testing

Automated checks cover:

- deploy assets include PostgreSQL and protect `.env` / `data/`;
- MySQL runtime dependencies are removed;
- migration scripts contain PostgreSQL DDL;
- application-level in-memory tests still pass;
- a PostgreSQL integration smoke test can initialize schema and exercise
  core database functions when a test PostgreSQL instance is available.

Live verification on `homegpu1` is required before completion:

- `deploy.sh` completes successfully;
- `docker compose ps` shows `postgres`, `web`, and `worker`;
- `web` environment points at `MY_APP_DB_HOST=postgres`;
- `curl http://localhost:5006/health` returns status `ok`;
- PostgreSQL row counts match the MySQL source counts captured before
  migration;
- at least one authenticated or public core endpoint can read migrated
  data.
