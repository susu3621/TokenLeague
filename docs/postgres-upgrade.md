# PostgreSQL 16 to 18.4

Run `./deploy.sh --upgrade-postgres` from the local checkout. The deployment uses
`postgres:18.4-alpine3.23` and `/var/lib/postgresql/18/docker`. It requires Python
3.10+ and Docker Compose on the deployment host. Ingestion is unavailable while
Web and worker are stopped. Collectors should submit again after service resumes.

The migration retains the source directory and private logical backups under
`data/`. It compares all non-template databases before and after restore and
again after promotion, before application writers resume. Backups include role
credentials and application data. Keep their directory private. Do not commit
them or print their contents.

CHECK definitions that differ across versions are parsed again on PostgreSQL 18
using temporary tables. Every other field must match exactly. The original
source inventory is retained beside the canonical PostgreSQL 18 inventory.

The official image changed its volume mount to `/var/lib/postgresql` for version
18. A version tag change alone cannot upgrade a PostgreSQL 16 cluster. See the
[official image documentation](https://hub.docker.com/_/postgres) and the
[PostgreSQL upgrade documentation](https://www.postgresql.org/docs/18/upgrading.html).

## If migration stops

Read `data/postgres18-migration.json` and inspect the named containers. Do not
rerun a restore, move a directory, or remove a receipt until their actual state
is known. The state is saved before and after promotion so a disconnect can be
reconciled without repeating a write.

- Before `promoting`, `data/postgres` still contains the source. Web and worker
  may be stopped, and the source may be read-only. The candidate and backup are
  separate. Preserve them while diagnosing the failure.
- At `promoting` or `promoted`, compare both directory paths with `PG_VERSION`
  and inspect the actual container mounts. `promoting` is written before either
  directory rename. Do not infer which rename completed from the receipt alone.
- At `complete`, PostgreSQL 18.4 has passed the deployed inventory comparison.
  The deployment then starts Web and worker. Confirm application reads,
  ingestion, and the snapshot worker separately.

To return to the retained source **before PostgreSQL 18 accepts new application
writes**, stop all three services. Preserve the candidate directory. Restore the
old directory at `data/postgres` and the PostgreSQL 16 image and volume mapping
from the prior Git revision. Start only PostgreSQL. The source was deliberately
left read-only; use a local administrative `psql` session to run these commands
as separate statements:

```sql
SET default_transaction_read_only = off;
ALTER SYSTEM RESET default_transaction_read_only;
SELECT pg_reload_conf();
```

Verify that a new connection reports `default_transaction_read_only=off` before
starting Web and worker. Archive the receipt with the reconciled recovery record
before a new attempt. After PostgreSQL 18 has accepted writes, returning to the
old directory would lose those writes. Reconcile them or restore from a fresh
logical backup instead. Retained clusters are not automatically deleted.

## Validation

Run unit and isolated Docker checks. The Docker checks use separate Compose
projects and exercise successful migration, container recreation, role grants,
sequence continuation, and a failed inventory comparison that blocks promotion.
They also run application migrations, all three ingestion routes, idempotent
prompt submission, snapshot generation, and authenticated statistics reads on 18.
They require cached `postgres:16-alpine` and `postgres:18.4-alpine3.23` images.

```bash
TOKENLEAGUE_RUN_POSTGRES_UPGRADE_TEST=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  python3 -m pytest -q service/tests/test_postgres_upgrade.py
```

## Production record: 2026-11-14

`homegpu1` migrated PostgreSQL 16.14 to `postgres:18.4-alpine3.23` (Alpine 3.23.5).
All 7 application tables and 84,179 rows matched before writers resumed. Sequence
values, indexes, column definitions, role credentials and memberships matched.
Five CHECK definitions were equivalent after parsing on PostgreSQL 18. The
original source inventory remains unchanged.

The receipt is `data/postgres18-migration.json`. Backups and comparison files are
in `data/postgres-upgrades/20261114T083027Z/`. The retained PostgreSQL 16 cluster is
`data/postgres16-retained-20261114T083027Z/`. Backup SHA-256 checks passed after
promotion. These paths are relative to `/home/juns/project/TokenLeague`.

The first candidate startup stopped before initdb because its parent directory
belonged to the host user with mode 700. The migration now assigns that directory
to the image's postgres user. Recovery verified the uninitialized candidate, the
backup hashes and the frozen source inventory before continuing. A later CHECK
text comparison stopped before promotion; recovery parsed the source expressions
on PostgreSQL 18 and continued without repeating the restore.

The final regression run passed 260 tests, including isolated Docker migration,
failed verification, container recreation and application ingestion. Production
acceptance also exposed per-event user lookups in the live leaderboard. The
application now loads users once per leaderboard request.
