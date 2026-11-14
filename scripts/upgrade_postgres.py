#!/usr/bin/env python3
"""Offline PostgreSQL 16 -> 18 migration. Run through deploy.sh --upgrade-postgres.

Uses only the host Python standard library and Docker. Private backups and the
old cluster stay under data/. An interrupted operation must be reconciled before
another deployment; this script never repeats an unfinished restore or cutover.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone


IMAGE = "postgres:18.4-alpine3.23"
PGDATA = "/var/lib/postgresql/18/docker"
ROOT = Path(__file__).resolve().parents[1]
INVENTORY_SQL = Path(__file__).with_name("postgres_inventory.sql").read_text()


def run(args, *, input=None, output=None, env=None):
    result = subprocess.run(args, input=input, stdout=output or subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    if result.returncode:
        # SQL errors can contain source data. Do not print them in deploy logs.
        raise RuntimeError(f"{args[0]} operation failed (exit {result.returncode}); inspect the containers privately")
    return result.stdout


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def quote_identifier(value):
    return '"' + value.replace('"', '""') + '"'


def restore_globals(content, bootstrap_user):
    """initdb already created the source superuser; retain its ALTER ROLE."""
    alternatives = (quote_identifier(bootstrap_user), bootstrap_user)
    return "\n".join(line for line in content.splitlines()
                     if line not in {f"CREATE ROLE {name};" for name in alternatives}) + "\n"


class Upgrade:
    def __init__(self, root=ROOT, compose="docker compose"):
        self.root = Path(root).resolve()
        self.data = self.root / "data"
        self.cluster = self.data / "postgres"
        self.receipt = self.data / "postgres18-migration.json"
        self.compose = shlex.split(compose)

    def dc(self, *args):
        return run([*self.compose, "--project-directory", str(self.root), *args])

    def layout(self):
        self.cluster.mkdir(parents=True, exist_ok=True)
        return run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "sh",
                    "--mount", f"type=bind,src={self.cluster},dst=/cluster,readonly", IMAGE, "-ec",
                    'if [ -f /cluster/PG_VERSION ]; then printf "legacy-"; cat /cluster/PG_VERSION; '
                    'elif [ -f /cluster/18/docker/PG_VERSION ]; then cat /cluster/18/docker/PG_VERSION; '
                    'elif [ -n "$(ls -A /cluster)" ]; then echo unknown; else echo empty; fi']).decode().strip()

    def check(self):
        if self.receipt.exists():
            state = json.loads(self.receipt.read_text())["state"]
            if state != "complete":
                raise RuntimeError(f"Unfinished migration ({state}). Reconcile {self.receipt} before deployment")
        layout = self.layout()
        if self.receipt.exists() and layout != "18":
            raise RuntimeError("A completed migration must retain the PostgreSQL 18 cluster; refusing initialization")
        if layout not in {"18", "empty"}:
            raise RuntimeError(f"PostgreSQL data layout is {layout}; run ./deploy.sh --upgrade-postgres for version 16")
        print(f"PostgreSQL 18 preflight passed ({layout})", flush=True)

    def sql(self, container, user, database, sql):
        return run(["docker", "exec", "-i", container, "psql", "-XqAt", "-v", "ON_ERROR_STOP=1",
                    "-U", user, "-d", database], input=sql.encode()).decode().strip()

    def inventory(self, container, user, databases):
        result = {database: json.loads(self.sql(container, user, database, INVENTORY_SQL))
                  for database in databases}
        result["_roles"] = json.loads(self.sql(container, user, "postgres", """
            SELECT json_agg(json_build_array(r.rolname, r.rolsuper, r.rolinherit, r.rolcreaterole,
                   r.rolcreatedb, r.rolcanlogin, r.rolreplication, r.rolbypassrls, r.rolconnlimit,
                   r.rolvaliduntil, r.rolconfig, md5(a.rolpassword)) ORDER BY r.rolname)
            FROM pg_roles r JOIN pg_authid a USING (oid) WHERE r.rolname NOT LIKE 'pg_%';
        """))
        result["_role_members"] = json.loads(self.sql(container, user, "postgres", """
            SELECT coalesce(json_agg(json_build_array(pg_get_userbyid(roleid), pg_get_userbyid(member),
                   pg_get_userbyid(grantor), admin_option, inherit_option, set_option)
                   ORDER BY pg_get_userbyid(roleid), pg_get_userbyid(member), pg_get_userbyid(grantor)), '[]')
            FROM pg_auth_members;
        """))
        return result

    def verify_inventory(self, before, restored, container, user):
        """Reparse differing CHECK definitions with the target SQL parser.

        PostgreSQL 18 can push an array cast into individual elements. Compare
        its parsed definition, while retaining the original source inventory.
        Every other field, including row hashes, must still match exactly.
        """
        canonical = json.loads(json.dumps(before))
        for database, entries in before.items():
            if database.startswith("_"):
                continue
            for key, source in entries.items():
                target = restored.get(database, {}).get(key)
                if source == target or not key.startswith("constraint:") or target is None:
                    continue
                if not source["definition"].startswith("CHECK "):
                    continue
                schema, table, _ = key[len("constraint:"):].split(".", 2)
                definition = self.sql(container, user, database, f"""
                    CREATE TEMP TABLE upgrade_source_check (LIKE {quote_identifier(schema)}.{quote_identifier(table)});
                    ALTER TABLE upgrade_source_check ADD CONSTRAINT source_check {source['definition']};
                    SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conrelid = 'pg_temp.upgrade_source_check'::regclass AND conname = 'source_check';
                """)
                canonical[database][key]["definition"] = definition
        if canonical != restored:
            raise RuntimeError("Restored inventory differs; preserve both clusters and inspect the private inventories")
        return canonical

    def wait(self, container, user):
        for _ in range(120):
            probe = subprocess.run(["docker", "exec", container, "pg_isready", "-U", user, "-d", "postgres"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if probe.returncode == 0:
                # initdb's temporary server is socket-only. Wait for final TCP startup.
                if subprocess.run(["docker", "exec", container, "pg_isready", "-h", "127.0.0.1",
                                   "-U", user, "-d", "postgres"], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0:
                    return
            status = run(["docker", "inspect", "--format", "{{.State.Status}}", container]).decode().strip()
            if status != "running":
                raise RuntimeError(f"Database container is {status}: {container}. Inspect before retrying")
            time.sleep(1)
        raise RuntimeError(f"Database startup timed out: {container}. Inspect before retrying")

    def migrate(self):
        if self.receipt.exists():
            self.check()
            return
        if self.layout() != "legacy-16":
            self.check()
            return
        source = self.dc("ps", "-q", "postgres").decode().strip()
        if not source:
            raise RuntimeError("The PostgreSQL 16 source container must be running")
        details = json.loads(run(["docker", "inspect", source]))[0]
        mounts = [m for m in details["Mounts"] if m["Destination"] == "/var/lib/postgresql/data"]
        if len(mounts) != 1 or Path(mounts[0]["Source"]).resolve() != self.cluster:
            raise RuntimeError("Source mount differs from data/postgres; manual review required")
        source_env = dict(value.split("=", 1) for value in details["Config"]["Env"])
        user = source_env.get("POSTGRES_USER", "postgres")
        if self.sql(source, user, "postgres", "SHOW server_version_num;")[:2] != "16":
            raise RuntimeError("Source server is not PostgreSQL 16")
        if self.sql(source, user, "postgres", "SHOW default_transaction_read_only;") != "off":
            raise RuntimeError("Source is already read-only; reconcile its existing maintenance state")
        if self.sql(source, user, "postgres", "SELECT count(*) FROM pg_tablespace WHERE spcname NOT IN ('pg_default','pg_global');") != "0":
            raise RuntimeError("Custom tablespaces require a separate migration plan")
        databases = json.loads(self.sql(source, user, "postgres", """
            SELECT json_agg(datname ORDER BY datname) FROM pg_database WHERE NOT datistemplate;
        """))
        size = int(self.sql(source, user, "postgres", "SELECT sum(pg_database_size(oid)) FROM pg_database;"))
        if shutil.disk_usage(self.data).free < size * 4 + 256 * 1024 * 1024:
            raise RuntimeError("Insufficient disk space for backup, restore and retained source")
        version = run(["docker", "run", "--rm", "--network", "none", IMAGE, "postgres", "--version"]).decode().strip()
        if version != "postgres (PostgreSQL) 18.4":
            raise RuntimeError(f"Unexpected target image version: {version}")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.data / "postgres-upgrades" / stamp
        backup.mkdir(parents=True, mode=0o700)
        backup.chmod(0o700)
        stage = self.data / f"postgres18-stage-{stamp}"
        stage.mkdir(mode=0o700)
        retained = self.data / f"postgres16-retained-{stamp}"
        candidate = f"tokenleague-pg18-{stamp.lower()}"
        record = {"state": "prepared", "backup": str(backup), "stage": str(stage),
                  "retained_source": str(retained), "source_container": source,
                  "source_image": details["Image"], "target_image": IMAGE, "candidate": candidate,
                  "databases": databases, "started_at": stamp}

        def state(value):
            record["state"] = value
            save(self.receipt, record)
            print(f"PostgreSQL migration: {value}", flush=True)

        state("prepared")
        # A failure deliberately leaves a receipt and preserves both clusters.
        # Never restart writers automatically after an uncertain cutover.
        self.dc("stop", "-t", "60", "web", "worker")
        state("writers_stopped")
        self.sql(source, user, "postgres", "ALTER SYSTEM SET default_transaction_read_only = 'on';")
        self.sql(source, user, "postgres", "SELECT pg_reload_conf();")
        self.sql(source, user, "postgres", """
            SELECT pg_terminate_backend(pid) FROM pg_stat_activity
            WHERE backend_type = 'client backend' AND pid <> pg_backend_pid();
        """)
        if self.sql(source, user, "postgres", "SHOW default_transaction_read_only;") != "on":
            raise RuntimeError("Source write freeze failed")
        state("source_frozen")
        before = self.inventory(source, user, databases)
        save(backup / "source-inventory.json", before)
        client_env = {**os.environ, "PGPASSWORD": source_env.get("POSTGRES_PASSWORD", "")}
        client = ["docker", "run", "--rm", "--network", f"container:{source}",
                  "-e", "PGPASSWORD", IMAGE]
        with (backup / "globals.sql").open("wb") as output:
            run([*client, "pg_dumpall", "-h", "127.0.0.1", "-U", user, "--globals-only"],
                output=output, env=client_env)
        for number, database in enumerate(databases):
            with (backup / f"database-{number}.dump").open("wb") as output:
                run([*client, "pg_dump", "-h", "127.0.0.1", "-U", user, "-d", database,
                     "--format=custom", "--create"], output=output, env=client_env)
        after = self.inventory(source, user, databases)
        if before != after:
            raise RuntimeError("Source changed during backup; migration halted")
        for path in backup.iterdir():
            path.chmod(0o600)
        record["backup_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in backup.iterdir()}
        state("backed_up")
        # On Linux, initdb switches to the postgres user. It must be able to
        # traverse the parent of PGDATA as well as PGDATA itself.
        run(["docker", "run", "--rm", "--network", "none", "--user", "0", "--entrypoint", "sh",
             "--mount", f"type=bind,src={stage},dst=/cluster", IMAGE, "-ec",
             "chown postgres:postgres /cluster; chmod 700 /cluster"])
        target_env = {**os.environ, "POSTGRES_PASSWORD": source_env["POSTGRES_PASSWORD"]}
        run(["docker", "run", "-d", "--name", candidate, "--network", "none",
             "-e", f"POSTGRES_USER={user}", "-e", "POSTGRES_DB=postgres", "-e", "POSTGRES_PASSWORD",
             "--mount", f"type=bind,src={stage},dst=/var/lib/postgresql", IMAGE], env=target_env)
        self.wait(candidate, user)
        self.sql(candidate, user, "postgres", restore_globals((backup / "globals.sql").read_text(), user))
        for number, database in enumerate(databases):
            args = ["docker", "exec", "-i", candidate, "pg_restore", "--exit-on-error", "-U", user, "-d", "postgres"]
            if database != "postgres":
                args.append("--create")
            run(args, input=(backup / f"database-{number}.dump").read_bytes())
        restored = self.inventory(candidate, user, databases)
        save(backup / "restored-inventory.json", restored)
        canonical = self.verify_inventory(before, restored, candidate, user)
        save(backup / "source-inventory-pg18.json", canonical)
        for database in databases:
            self.sql(candidate, user, database, "ANALYZE;")
        state("restore_verified")
        run(["docker", "stop", "-t", "60", candidate])
        self.dc("stop", "-t", "60", "postgres")
        state("promoting")
        self.cluster.rename(retained)
        stage.rename(self.cluster)
        state("promoted")
        self.dc("up", "-d", "--no-deps", "postgres")
        deployed = self.dc("ps", "-q", "postgres").decode().strip()
        self.wait(deployed, user)
        if self.sql(deployed, user, "postgres", "SHOW server_version_num;") != "180004":
            raise RuntimeError("Deployed database is not PostgreSQL 18.4")
        if self.sql(deployed, user, "postgres", "SHOW data_directory;") != PGDATA:
            raise RuntimeError("Deployed PGDATA differs from the PostgreSQL 18 layout")
        final = self.inventory(deployed, user, databases)
        save(backup / "deployed-inventory.json", final)
        if final != canonical:
            raise RuntimeError("Deployed inventory differs; writers remain stopped")
        record["verified_tables"] = sum(key.startswith("relation:") and "rows" in value
                                        for database in databases for key, value in before[database].items())
        record["verified_rows"] = sum(value.get("rows", 0) for database in databases
                                      for key, value in before[database].items() if key.startswith("relation:"))
        run(["docker", "rm", candidate])
        state("complete")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--compose", default="docker compose")
    args = parser.parse_args()
    os.umask(0o077)
    upgrade = Upgrade(compose=args.compose)
    upgrade.data.mkdir(exist_ok=True)
    with (upgrade.data / "postgres-upgrade.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.migrate:
            upgrade.migrate()
        else:
            upgrade.check()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"PostgreSQL upgrade stopped: {exc}", file=sys.stderr)
        sys.exit(1)
