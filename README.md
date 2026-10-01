# stepwise-migrations

A small SQL migration library for Python, with a thin CLI on top. No
third-party dependencies — everything runs on the standard library.

## Why

Most migration tools end up mixing three concerns in one place: reading
files off disk, talking to a database, and deciding what actually needs
to run. That last part — the planning logic — is the part worth getting
right, and it shouldn't need a database or a temp directory to test.

So the split here is deliberate: `stepwise_migrations.core` has no I/O
at all. Every function takes plain data (filenames, SQL text, a
version-to-checksum map) and returns plain data. `stepwise_migrations.cli`
is the only place that opens a file or a database connection.

## Migration files

Migrations live in a directory as `NNNN_slug.sql` files:

```
migrations/
  0001_create_users.sql
  0002_add_users_email_index.sql
  0003_create_orders.sql
```

Each file is applied once, in version order, and its checksum is
recorded so a file edited after the fact is caught instead of silently
skipped.

## CLI usage

```
$ python -m stepwise_migrations.cli status --directory migrations --database app.db
PENDING   0001_create_users.sql
PENDING   0002_add_users_email_index.sql
PENDING   0003_create_orders.sql

$ python -m stepwise_migrations.cli apply --directory migrations --database app.db
applied   0001_create_users.sql
applied   0002_add_users_email_index.sql
applied   0003_create_orders.sql

$ python -m stepwise_migrations.cli status --directory migrations --database app.db
up to date
```

If a previously-applied file changes on disk, `status` and `apply` will
report a `MISMATCH` line instead of quietly re-running or ignoring it.

## Library usage

The planning logic is usable on its own, independent of the CLI or any
particular database driver:

```python
from stepwise_migrations.core import load_migrations, plan_migrations

files = {
    "0001_create_users.sql": "CREATE TABLE users (id INTEGER PRIMARY KEY);",
    "0002_add_email.sql": "ALTER TABLE users ADD COLUMN email TEXT;",
}
migrations = load_migrations(files)

# what the migrations table already has recorded, as version -> checksum
applied = {1: migrations[0].checksum}

plan = plan_migrations(migrations, applied)
[m.filename for m in plan.to_apply]   # ['0002_add_email.sql']
plan.mismatched                       # ()
```

Because `load_migrations` and `plan_migrations` take dicts and lists
instead of paths and connections, tests can exercise every branch (bad
filenames, duplicate versions, checksum drift) without touching a disk
or a database.

## Status

Early skeleton. The CLI only supports sqlite for now; the core planning
functions are database-agnostic and the CLI's storage backend is meant
to become swappable later.

## Tests

```
python -m unittest discover -s tests -t .
```

## License

MIT, see LICENSE.
