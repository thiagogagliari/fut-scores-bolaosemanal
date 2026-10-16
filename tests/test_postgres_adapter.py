import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import app


class PostgresAdapterTests(unittest.TestCase):
    def test_translates_sqlite_specific_queries(self):
        translated = app.PostgresConnection._translate_sql(
            """
            SELECT * FROM payments p
            WHERE julianday(p.paid_at) < julianday(?)
            ORDER BY p.paid_at COLLATE NOCASE
            """
        )
        self.assertIn("CAST(p.paid_at AS TIMESTAMPTZ)", translated)
        self.assertIn("CAST(%s AS TIMESTAMPTZ)", translated)
        self.assertIn("ORDER BY LOWER(p.paid_at)", translated)

    def test_translates_insert_ignore_and_placeholders(self):
        translated = app.PostgresConnection._translate_sql(
            "INSERT OR IGNORE INTO teams(name, crest_url) VALUES (?, NULL)"
        )
        self.assertEqual(
            translated,
            "INSERT INTO teams(name, crest_url) VALUES (%s, NULL) ON CONFLICT DO NOTHING",
        )

    def test_postgres_rows_support_name_and_position_access(self):
        row = app.PostgresRow((("id", 42), ("name", "Time")))
        self.assertEqual(row["id"], 42)
        self.assertEqual(row[0], 42)
        self.assertEqual(row[1], "Time")

    def test_postgres_row_factory_handles_statements_without_results(self):
        make_row = app.postgres_row_factory(SimpleNamespace(description=None))
        self.assertEqual(make_row((1, 2)), (1, 2))

    def test_executemany_uses_postgres_cursor(self):
        connection = Mock()
        cursor = connection.cursor.return_value
        db = app.PostgresConnection(connection)
        parameters = [("Time",)]

        result = db.executemany(
            "INSERT OR IGNORE INTO teams(name) VALUES (?)",
            parameters,
        )

        connection.cursor.assert_called_once_with()
        cursor.executemany.assert_called_once_with(
            "INSERT INTO teams(name) VALUES (%s) ON CONFLICT DO NOTHING",
            parameters,
        )
        connection.executemany.assert_not_called()
        self.assertIs(result, cursor)


if __name__ == "__main__":
    unittest.main()
