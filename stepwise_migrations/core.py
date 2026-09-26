"""Pure planning logic for SQL migrations.

Nothing in this module touches a filesystem or a database connection.
Every function takes plain data in and returns plain data out, so the
whole planning story (parsing, ordering, diffing, checksum validation)
can be tested without a database or temp files.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Mapping, Sequence

_FILENAME_RE = re.compile(r"^(\d+)_([a-zA-Z0-9][a-zA-Z0-9_]*)\.sql$")


class MigrationError(ValueError):
    """Raised when migration input data is malformed or inconsistent."""


@dataclass(frozen=True)
class Migration:
    version: int
    slug: str
    filename: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Plan:
    """Result of comparing available migrations against applied state."""

    to_apply: tuple[Migration, ...]
    mismatched: tuple[tuple[Migration, str], ...]


def parse_filename(filename: str) -> tuple[int, str]:
    """Split a migration filename into (version, slug).

    Expected shape: "0007_add_index_to_orders.sql". Raises MigrationError
    for anything else, so callers don't have to guess at malformed input.
    """
    match = _FILENAME_RE.match(filename)
    if not match:
        raise MigrationError(
            f"{filename!r} does not match the expected NNNN_slug.sql pattern"
        )
    version_str, slug = match.groups()
    return int(version_str), slug


def load_migrations(files: Mapping[str, str]) -> list[Migration]:
    """Build a sorted, validated migration list from filename -> sql text.

    Rejects duplicate version numbers up front, since applying two
    migrations under the same version is never something a caller wants
    silently resolved by file order.
    """
    migrations: list[Migration] = []
    seen_versions: dict[int, str] = {}

    for filename, sql in files.items():
        version, slug = parse_filename(filename)
        if version in seen_versions:
            raise MigrationError(
                f"duplicate migration version {version}: "
                f"{seen_versions[version]!r} and {filename!r}"
            )
        seen_versions[version] = filename
        migrations.append(Migration(version, slug, filename, sql))

    migrations.sort(key=lambda m: m.version)
    return migrations


def plan_migrations(
    migrations: Sequence[Migration],
    applied: Mapping[int, str],
) -> Plan:
    """Diff available migrations against a version->checksum applied map.

    `applied` describes what a migrations table already recorded. Versions
    missing from `migrations` but present in `applied` are not reported
    here; that is a separate concern (a migration file someone deleted),
    left to the caller since this function only knows about the plan to
    move forward, not repository hygiene.
    """
    to_apply: list[Migration] = []
    mismatched: list[tuple[Migration, str]] = []

    for migration in migrations:
        recorded_checksum = applied.get(migration.version)
        if recorded_checksum is None:
            to_apply.append(migration)
        elif recorded_checksum != migration.checksum:
            mismatched.append((migration, recorded_checksum))

    return Plan(to_apply=tuple(to_apply), mismatched=tuple(mismatched))


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into individual statements on top-level ';'.

    Tracks single- and double-quoted string state so a semicolon inside
    a literal (e.g. an INSERT with 'a;b' as a value) doesn't end up
    splitting the statement in the wrong place.
    """
    statements: list[str] = []
    current: list[str] = []
    quote_char: str | None = None

    for char in sql:
        if quote_char is not None:
            current.append(char)
            if char == quote_char:
                quote_char = None
            continue

        if char in ("'", '"'):
            quote_char = char
            current.append(char)
            continue

        if char == ";":
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            continue

        current.append(char)

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)

    return statements
