"""Thin CLI wrapper around stepwise_migrations.core.

All filesystem and database access lives here. This module's job is to
gather raw data (file contents, applied-migrations rows), hand it to the
pure functions in core.py, and act on the result.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from .core import Migration, load_migrations, plan_migrations, split_statements

_TRACKING_TABLE = "schema_migrations"


def _ensure_tracking_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TRACKING_TABLE} (
            version INTEGER PRIMARY KEY,
            checksum TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _read_applied(conn: sqlite3.Connection) -> dict[int, str]:
    rows = conn.execute(f"SELECT version, checksum FROM {_TRACKING_TABLE}").fetchall()
    return {version: checksum for version, checksum in rows}


def _read_migration_files(directory: Path) -> dict[str, str]:
    files = {}
    for path in sorted(directory.glob("*.sql")):
        files[path.name] = path.read_text(encoding="utf-8")
    return files


def _apply(conn: sqlite3.Connection, migration: Migration) -> None:
    for statement in split_statements(migration.sql):
        conn.execute(statement)
    conn.execute(
        f"INSERT INTO {_TRACKING_TABLE} (version, checksum) VALUES (?, ?)",
        (migration.version, migration.checksum),
    )
    conn.commit()


def cmd_status(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    migrations = load_migrations(_read_migration_files(directory))

    conn = sqlite3.connect(args.database)
    try:
        _ensure_tracking_table(conn)
        applied = _read_applied(conn)
    finally:
        conn.close()

    plan = plan_migrations(migrations, applied)

    for migration, recorded_checksum in plan.mismatched:
        print(
            f"MISMATCH  {migration.filename} "
            f"(recorded {recorded_checksum[:8]}, file is {migration.checksum[:8]})"
        )
    for migration in plan.to_apply:
        print(f"PENDING   {migration.filename}")
    if not plan.to_apply and not plan.mismatched:
        print("up to date")

    return 1 if plan.mismatched else 0


def cmd_apply(args: argparse.Namespace) -> int:
    directory = Path(args.directory)
    migrations = load_migrations(_read_migration_files(directory))

    conn = sqlite3.connect(args.database)
    try:
        _ensure_tracking_table(conn)
        applied = _read_applied(conn)
        plan = plan_migrations(migrations, applied)

        if plan.mismatched:
            for migration, recorded_checksum in plan.mismatched:
                print(
                    f"MISMATCH  {migration.filename} "
                    f"(recorded {recorded_checksum[:8]}, file is {migration.checksum[:8]})",
                    file=sys.stderr,
                )
            print("refusing to apply: checksum mismatch on an already-applied migration", file=sys.stderr)
            return 1

        for migration in plan.to_apply:
            _apply(conn, migration)
            print(f"applied   {migration.filename}")
    finally:
        conn.close()

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stepwise-migrations")
    parser.add_argument(
        "-d", "--directory", default="migrations", help="directory holding NNNN_slug.sql files"
    )
    parser.add_argument(
        "--database", default="app.db", help="path to the sqlite database file"
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="show pending and mismatched migrations")
    status_parser.set_defaults(func=cmd_status)

    apply_parser = subparsers.add_parser("apply", help="apply all pending migrations")
    apply_parser.set_defaults(func=cmd_apply)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
