import unittest

import app
from scripts import import_sqlite


class SQLiteImportTests(unittest.TestCase):
    def setUp(self):
        self.counts = {
            table: 0 for table in import_sqlite.EMPTY_CHECK_TABLES
        }
        self.counts.update(
            users=1,
            teams=len(app.TEAMS),
            app_settings=1,
        )
        self.users = [
            {
                "name": "Administrador",
                "email": "admin@futscores.com",
                "team": "Brasil",
                "role": "admin",
                "is_blocked": 0,
            }
        ]
        self.settings = [{"key": "teams_seeded", "value": "1"}]
        self.teams = [
            {"name": name, "crest_url": None} for name in app.TEAMS
        ]

    def test_accepts_untouched_application_bootstrap(self):
        self.assertTrue(
            import_sqlite.is_pristine_app_bootstrap(
                self.counts,
                self.users,
                self.settings,
                self.teams,
            )
        )

    def test_rejects_any_additional_database_records(self):
        self.counts["rounds"] = 1

        self.assertFalse(
            import_sqlite.is_pristine_app_bootstrap(
                self.counts,
                self.users,
                self.settings,
                self.teams,
            )
        )

    def test_rejects_changed_bootstrap_admin(self):
        self.users[0]["email"] = "someone-else@example.com"

        self.assertFalse(
            import_sqlite.is_pristine_app_bootstrap(
                self.counts,
                self.users,
                self.settings,
                self.teams,
            )
        )

    def test_rejects_modified_seeded_teams(self):
        self.teams[0]["crest_url"] = "https://example.com/crest.png"

        self.assertFalse(
            import_sqlite.is_pristine_app_bootstrap(
                self.counts,
                self.users,
                self.settings,
                self.teams,
            )
        )


if __name__ == "__main__":
    unittest.main()
