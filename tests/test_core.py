import unittest

from stepwise_migrations.core import (
    Migration,
    MigrationError,
    load_migrations,
    parse_filename,
    plan_migrations,
    split_statements,
)


class ParseFilenameTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(parse_filename("0007_add_index.sql"), (7, "add_index"))

    def test_version_width_is_not_fixed(self):
        self.assertEqual(parse_filename("12_x.sql"), (12, "x"))

    def test_leading_zeros_parse_as_same_version(self):
        self.assertEqual(parse_filename("0001_a.sql")[0], parse_filename("1_a.sql")[0])

    def test_rejects_malformed_names(self):
        bad = [
            "create_users.sql",
            "0001.sql",
            "0001_.sql",
            "0001_users.txt",
            "0001_users.sql.bak",
            "_0001_users.sql",
            "0001_bad-slug.sql",
            "0001_has space.sql",
            "",
        ]
        for name in bad:
            with self.subTest(name=name):
                with self.assertRaises(MigrationError):
                    parse_filename(name)


class LoadMigrationsTests(unittest.TestCase):
    def test_sorts_by_numeric_version(self):
        files = {
            "10_c.sql": "c",
            "0002_b.sql": "b",
            "0001_a.sql": "a",
        }
        migrations = load_migrations(files)
        self.assertEqual([m.version for m in migrations], [1, 2, 10])
        self.assertEqual([m.sql for m in migrations], ["a", "b", "c"])

    def test_fields_are_populated(self):
        (m,) = load_migrations({"0003_orders.sql": "SELECT 1;"})
        self.assertEqual(m.version, 3)
        self.assertEqual(m.slug, "orders")
        self.assertEqual(m.filename, "0003_orders.sql")
        self.assertEqual(m.sql, "SELECT 1;")

    def test_empty_input(self):
        self.assertEqual(load_migrations({}), [])

    def test_duplicate_versions_rejected(self):
        files = {"0001_a.sql": "a", "1_b.sql": "b"}
        with self.assertRaises(MigrationError) as ctx:
            load_migrations(files)
        self.assertIn("duplicate", str(ctx.exception))

    def test_bad_filename_propagates(self):
        with self.assertRaises(MigrationError):
            load_migrations({"nope.sql": "x"})

    def test_checksum_depends_on_content(self):
        a = Migration(1, "a", "0001_a.sql", "SELECT 1;")
        b = Migration(1, "a", "0001_a.sql", "SELECT 2;")
        same = Migration(1, "a", "0001_a.sql", "SELECT 1;")
        self.assertNotEqual(a.checksum, b.checksum)
        self.assertEqual(a.checksum, same.checksum)
        self.assertEqual(len(a.checksum), 64)


class PlanMigrationsTests(unittest.TestCase):
    def setUp(self):
        self.migrations = load_migrations(
            {
                "0001_a.sql": "a",
                "0002_b.sql": "b",
                "0003_c.sql": "c",
            }
        )

    def test_everything_pending_when_nothing_applied(self):
        plan = plan_migrations(self.migrations, {})
        self.assertEqual(plan.to_apply, tuple(self.migrations))
        self.assertEqual(plan.mismatched, ())

    def test_applied_are_skipped(self):
        applied = {1: self.migrations[0].checksum, 2: self.migrations[1].checksum}
        plan = plan_migrations(self.migrations, applied)
        self.assertEqual([m.version for m in plan.to_apply], [3])
        self.assertEqual(plan.mismatched, ())

    def test_up_to_date(self):
        applied = {m.version: m.checksum for m in self.migrations}
        plan = plan_migrations(self.migrations, applied)
        self.assertEqual(plan.to_apply, ())
        self.assertEqual(plan.mismatched, ())

    def test_changed_file_is_mismatch_not_pending(self):
        applied = {1: "stale-checksum"}
        plan = plan_migrations(self.migrations, applied)
        self.assertEqual(plan.mismatched, ((self.migrations[0], "stale-checksum"),))
        self.assertEqual([m.version for m in plan.to_apply], [2, 3])

    def test_applied_versions_without_a_file_are_ignored(self):
        applied = {99: "whatever"}
        plan = plan_migrations(self.migrations, applied)
        self.assertEqual(len(plan.to_apply), 3)
        self.assertEqual(plan.mismatched, ())

    def test_gap_in_applied_history_still_plans_the_gap(self):
        applied = {1: self.migrations[0].checksum, 3: self.migrations[2].checksum}
        plan = plan_migrations(self.migrations, applied)
        self.assertEqual([m.version for m in plan.to_apply], [2])


class SplitStatementsTests(unittest.TestCase):
    def test_basic_split(self):
        self.assertEqual(
            split_statements("CREATE TABLE a (id INT); CREATE TABLE b (id INT);"),
            ["CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)"],
        )

    def test_trailing_statement_without_semicolon(self):
        self.assertEqual(split_statements("SELECT 1; SELECT 2"), ["SELECT 1", "SELECT 2"])

    def test_empty_and_whitespace_only(self):
        self.assertEqual(split_statements(""), [])
        self.assertEqual(split_statements("  \n ; ;\n"), [])

    def test_semicolon_inside_single_quotes(self):
        sql = "INSERT INTO t VALUES ('a;b'); SELECT 1;"
        self.assertEqual(
            split_statements(sql), ["INSERT INTO t VALUES ('a;b')", "SELECT 1"]
        )

    def test_semicolon_inside_double_quotes(self):
        sql = 'CREATE TABLE "a;b" (id INT); SELECT 1;'
        self.assertEqual(
            split_statements(sql), ['CREATE TABLE "a;b" (id INT)', "SELECT 1"]
        )

    def test_doubled_quote_escape_stays_in_one_statement(self):
        sql = "INSERT INTO t VALUES ('it''s; fine'); SELECT 1;"
        self.assertEqual(
            split_statements(sql), ["INSERT INTO t VALUES ('it''s; fine')", "SELECT 1"]
        )

    def test_other_quote_type_inside_a_literal_is_plain_text(self):
        sql = "INSERT INTO t VALUES ('say \"hi;\"'); SELECT 1;"
        self.assertEqual(
            split_statements(sql), ["INSERT INTO t VALUES ('say \"hi;\"')", "SELECT 1"]
        )

    def test_multiline_statement_is_preserved(self):
        sql = "CREATE TABLE a (\n  id INT,\n  name TEXT\n);\n"
        self.assertEqual(
            split_statements(sql), ["CREATE TABLE a (\n  id INT,\n  name TEXT\n)"]
        )


if __name__ == "__main__":
    unittest.main()
