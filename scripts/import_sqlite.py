from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app


TABLES = (
    "users",
    "rounds",
    "teams",
    "app_settings",
    "matches",
    "picks",
    "payments",
    "winner_verifications",
    "prize_payouts",
)
IDENTITY_TABLES = ("users", "rounds", "matches", "teams")
EMPTY_CHECK_TABLES = (*TABLES, "sessions")


def is_pristine_app_bootstrap(
    existing: dict[str, int],
    users: Sequence[Mapping[str, object]],
    settings: Sequence[Mapping[str, object]],
    teams: Sequence[Mapping[str, object]],
) -> bool:
    expected_counts = {table: 0 for table in EMPTY_CHECK_TABLES}
    expected_counts.update(
        users=1,
        teams=len(app.TEAMS),
        app_settings=1,
    )
    if existing != expected_counts:
        return False

    expected_admin_email = os.environ.get(
        "FUTSCORES_ADMIN_EMAIL", "admin@futscores.com"
    ).strip().lower()
    if len(users) != 1:
        return False
    admin = users[0]
    if (
        admin["name"] != "Administrador"
        or admin["email"] != expected_admin_email
        or admin["team"] != "Brasil"
        or admin["role"] != "admin"
        or admin["is_blocked"] != 0
    ):
        return False

    if (
        len(settings) != 1
        or settings[0]["key"] != "teams_seeded"
        or settings[0]["value"] != "1"
    ):
        return False

    return [(team["name"], team["crest_url"]) for team in teams] == [
        (name, None) for name in app.TEAMS
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importa o SQLite local para um PostgreSQL vazio."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Confirma a importação; sem esta opção, apenas exibe contagens locais.",
    )
    args = parser.parse_args()

    if args.apply and not app.DATABASE_URL:
        parser.error("Configure DATABASE_URL para o PostgreSQL de destino.")
    if not app.DB_PATH.is_file():
        parser.error(f"Banco SQLite local não encontrado: {app.DB_PATH}")

    with sqlite3.connect(app.DB_PATH) as source:
        source.row_factory = sqlite3.Row
        counts = {
            table: source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in EMPTY_CHECK_TABLES
        }
        print("Registros no SQLite local:")
        for table, count in counts.items():
            suffix = " (não serão importadas)" if table == "sessions" else ""
            print(f"  {table}: {count}{suffix}")

        if not args.apply:
            print("Nenhum dado foi escrito. Revise as contagens e use --apply.")
            return 0

        with app.connect_db() as destination:
            app.create_postgres_schema(destination)
            existing = {
                table: destination.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                for table in EMPTY_CHECK_TABLES
            }
            nonempty = [table for table, count in existing.items() if count]
            if nonempty:
                bootstrap = is_pristine_app_bootstrap(
                    existing,
                    destination.execute(
                        "SELECT name, email, team, role, is_blocked FROM users ORDER BY id"
                    ).fetchall(),
                    destination.execute(
                        "SELECT key, value FROM app_settings ORDER BY key"
                    ).fetchall(),
                    destination.execute(
                        "SELECT name, crest_url FROM teams ORDER BY id"
                    ).fetchall(),
                )
                if not bootstrap:
                    raise RuntimeError(
                        "O banco de destino não está vazio; importação cancelada "
                        f"para evitar sobrescrever dados: {', '.join(nonempty)}"
                    )
                print(
                    "Estado inicial intacto do app detectado; removendo apenas "
                    "a conta admin e os times de bootstrap."
                )
                for table in ("users", "teams", "app_settings"):
                    destination.execute(f"DELETE FROM {table}")

            for table in TABLES:
                columns = [
                    column["name"]
                    for column in source.execute(f"PRAGMA table_info({table})")
                ]
                rows = source.execute(f"SELECT * FROM {table}").fetchall()
                if not rows:
                    continue
                column_list = ", ".join(columns)
                placeholders = ", ".join("%s" for _ in columns)
                statement = (
                    f"INSERT INTO {table} ({column_list}) "
                    f"VALUES ({placeholders})"
                )
                destination.executemany(
                    statement,
                    [tuple(row[column] for column in columns) for row in rows],
                )

            for table in IDENTITY_TABLES:
                destination.execute(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table}', 'id'),
                        COALESCE(MAX(id), 1),
                        COUNT(*) > 0
                    ) FROM {table}
                    """
                )

    print("Importação concluída. O arquivo SQLite local foi mantido intacto.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
