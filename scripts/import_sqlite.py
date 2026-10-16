from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

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
                raise RuntimeError(
                    "O banco de destino não está vazio; importação cancelada "
                    f"para evitar sobrescrever dados: {', '.join(nonempty)}"
                )

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
