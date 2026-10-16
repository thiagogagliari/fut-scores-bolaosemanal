from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Generator
from urllib.parse import urlparse, urlsplit


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "futscores.sqlite3"
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SESSION_SECONDS = 60 * 60 * 24 * 14
PASSWORD_ITERATIONS = 240_000
DB_INTEGRITY_ERRORS: tuple[type[Exception], ...] = (sqlite3.IntegrityError,)

TEAMS = [
    "Alemanha", "América/MG", "Arsenal", "Atalanta", "Athletic Club",
    "Athletico/PR", "Atlético Mineiro", "Atlético/GO", "Auxerre", "Avaí",
    "Bahia", "Barcelona", "Botafogo", "Botafogo/PB", "Botafogo/SP", "Brasil",
    "Brusque", "Bétis", "CRB", "Cagliari", "Ceará", "Chapecoense", "Chelsea",
    "Chéquia", "Como", "Corinthians", "Coritiba", "Criciúma", "Cruzeiro",
    "Crystal Palace", "Cuiabá", "Dinamarca", "Escócia", "Eslovênia",
    "Espanha", "Ferroviária/SP", "Flamengo", "Fluminense", "Fortaleza",
    "Goiás", "Grécia", "Grêmio", "Holanda", "Internacional", "Juventude/RS",
    "Juventus", "Liverpool", "Londrina", "Manchester City", "Manchester Utd",
    "Marseille", "Milan", "Mirassol", "Monaco", "Náutico/PE", "Noruega",
    "Nottingham Forest", "Palmeiras", "Paysandu/PA", "Portugal", "PSG",
    "RB Bragantino", "Real Madrid", "Santos", "Sevilla", "Sport/PE",
    "São Paulo/SP", "Vasco da Gama", "Vila Nova/GO", "Vitória/BA",
]

DEMO_MEMBERS = [
    ("Antonio", "Flamengo"),
    ("Bruno Silva", "Ceará"),
    ("Carlos Eduardo", "Corinthians"),
    ("Diego Sales", "Flamengo"),
    ("Ednei", "Ceará"),
    ("GUILHERME", "Flamengo"),
    ("Helber Marques", "Fluminense"),
    ("Kayki wendel", "Ceará"),
    ("Lelê", "Ceará"),
    ("Marcelo", "Flamengo"),
    ("Paulo eduardo", "Ceará"),
    ("Rafa Torcedor", "Palmeiras"),
    ("Samuel Santos", "Fortaleza"),
    ("Thiago Gagliari", "Ceará"),
]

WEEK_TWO_MATCHES = [
    ("2026-10-17T11:00:00-03:00", "Ceará", "Corinthians"),
    ("2026-10-17T16:00:00-03:00", "Flamengo", "Palmeiras"),
    ("2026-10-17T18:30:00-03:00", "Bahia", "Internacional"),
    ("2026-10-17T21:00:00-03:00", "Santos", "Fluminense"),
    ("2026-10-18T11:00:00-03:00", "Botafogo", "Vasco da Gama"),
    ("2026-10-18T16:00:00-03:00", "São Paulo/SP", "Fortaleza"),
    ("2026-10-18T16:00:00-03:00", "Grêmio", "Cruzeiro"),
    ("2026-10-18T16:00:00-03:00", "Vitória/BA", "Mirassol"),
    ("2026-10-18T18:30:00-03:00", "Atlético Mineiro", "RB Bragantino"),
    ("2026-10-18T18:30:00-03:00", "Juventude/RS", "Ceará"),
    ("2026-10-18T20:00:00-03:00", "Arsenal", "Liverpool"),
    ("2026-10-18T20:00:00-03:00", "Barcelona", "Real Madrid"),
    ("2026-10-18T20:00:00-03:00", "Milan", "Juventus"),
    ("2026-10-18T20:00:00-03:00", "Manchester City", "Chelsea"),
]

WEEK_ONE_MATCHES = [
    ("2026-10-10T11:00:00-03:00", "Palmeiras", "Ceará", 2, 0),
    ("2026-10-10T16:00:00-03:00", "Corinthians", "Santos", 1, 1),
    ("2026-10-10T18:30:00-03:00", "Flamengo", "Bahia", 3, 1),
    ("2026-10-10T21:00:00-03:00", "Fluminense", "Botafogo", 0, 1),
    ("2026-10-11T11:00:00-03:00", "Internacional", "Grêmio", 1, 0),
    ("2026-10-11T16:00:00-03:00", "Cruzeiro", "Vasco da Gama", 2, 2),
    ("2026-10-11T16:00:00-03:00", "Fortaleza", "São Paulo/SP", 0, 2),
    ("2026-10-11T18:30:00-03:00", "Atlético Mineiro", "Vitória/BA", 2, 1),
    ("2026-10-11T18:30:00-03:00", "RB Bragantino", "Juventude/RS", 1, 0),
    ("2026-10-11T20:00:00-03:00", "Liverpool", "Arsenal", 1, 1),
    ("2026-10-11T20:00:00-03:00", "Real Madrid", "Barcelona", 2, 1),
    ("2026-10-11T20:00:00-03:00", "Juventus", "Milan", 0, 0),
    ("2026-10-11T20:00:00-03:00", "Chelsea", "Manchester City", 1, 2),
    ("2026-10-11T20:00:00-03:00", "Mirassol", "Botafogo", 1, 1),
]


class PostgresRow(dict[str, object]):
    def __getitem__(self, key: str | int) -> object:
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def postgres_row_factory(cursor: Any) -> Any:
    columns = [column.name for column in cursor.description]
    return lambda values: PostgresRow(zip(columns, values))


class PostgresConnection:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @staticmethod
    def _translate_sql(sql: str) -> str:
        ignore_conflicts = bool(re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\b", sql, re.I))
        sql = re.sub(
            r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
            "INSERT INTO",
            sql,
            flags=re.I,
        )
        sql = re.sub(
            r"\b([A-Za-z_][\w.]*)\s+COLLATE\s+NOCASE\b",
            r"LOWER(\1)",
            sql,
            flags=re.I,
        )
        sql = re.sub(
            r"julianday\(([^()]*)\)",
            r"CAST(\1 AS TIMESTAMPTZ)",
            sql,
            flags=re.I,
        )
        sql = sql.replace("?", "%s")
        if ignore_conflicts:
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return sql

    def execute(self, sql: str, parameters: object = ()) -> Any:
        return self.connection.execute(self._translate_sql(sql), parameters)

    def executemany(self, sql: str, parameters: object) -> Any:
        return self.connection.executemany(self._translate_sql(sql), parameters)


@contextmanager
def connect_db() -> Generator[Any, None, None]:
    if os.environ.get("VERCEL") == "1" and not DATABASE_URL:
        raise RuntimeError("Configure DATABASE_URL para usar PostgreSQL na Vercel.")
    if DATABASE_URL:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "Instale as dependências de requirements.txt para usar PostgreSQL."
            ) from exc

        global DB_INTEGRITY_ERRORS
        DB_INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)
        with psycopg.connect(DATABASE_URL, row_factory=postgres_row_factory) as connection:
            yield PostgresConnection(connection)
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"{salt.hex()}:{digest.hex()}"


def password_matches(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, expected = stored_hash.split(":", 1)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex),
            PASSWORD_ITERATIONS,
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def outcome(home: int, away: int) -> int:
    return (home > away) - (home < away)


def score_points(
    prediction: tuple[int, int], result: tuple[int, int]
) -> int:
    predicted_home, predicted_away = prediction
    actual_home, actual_away = result
    if (predicted_home, predicted_away) == (actual_home, actual_away):
        return 10

    points = 0
    if outcome(predicted_home, predicted_away) == outcome(actual_home, actual_away):
        points += 3
    if predicted_home == actual_home:
        points += 1
    if predicted_away == actual_away:
        points += 1
    if predicted_home - predicted_away == actual_home - actual_away:
        points += 1
    return points


POSTGRES_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS users (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        team TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'player' CHECK(role IN ('player', 'admin')),
        is_blocked INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP::text)
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at BIGINT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS rounds (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,
        date_range TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('active', 'finished')),
        prize_cents BIGINT NOT NULL DEFAULT 500
    )""",
    """CREATE TABLE IF NOT EXISTS matches (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        round_id BIGINT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
        starts_at TEXT NOT NULL,
        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,
        home_result INTEGER,
        away_result INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS picks (
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        match_id BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
        home_score INTEGER NOT NULL CHECK(home_score BETWEEN 0 AND 20),
        away_score INTEGER NOT NULL CHECK(away_score BETWEEN 0 AND 20),
        PRIMARY KEY (user_id, match_id)
    )""",
    """CREATE TABLE IF NOT EXISTS payments (
        round_id BIGINT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        paid INTEGER NOT NULL DEFAULT 0 CHECK(paid IN (0, 1)),
        paid_at TEXT,
        PRIMARY KEY (round_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS winner_verifications (
        round_id BIGINT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        code TEXT NOT NULL UNIQUE,
        PRIMARY KEY (round_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS prize_payouts (
        round_id BIGINT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        amount_cents BIGINT NOT NULL CHECK(amount_cents >= 0),
        paid_at TEXT NOT NULL,
        PRIMARY KEY (round_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS teams (
        id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
        name TEXT NOT NULL,
        crest_url TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS users_email_lower_unique ON users (LOWER(email))",
    "CREATE UNIQUE INDEX IF NOT EXISTS teams_name_lower_unique ON teams (LOWER(name))",
)


def create_postgres_schema(db: PostgresConnection) -> None:
    db.execute("SELECT pg_advisory_xact_lock(?)", (894_271_630,))
    for statement in POSTGRES_SCHEMA:
        db.execute(statement)


def create_sqlite_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            team TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'player' CHECK(role IN ('player', 'admin')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rounds (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            date_range TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'finished')),
            prize_cents INTEGER NOT NULL DEFAULT 500
        );
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY,
            round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
            starts_at TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_result INTEGER,
            away_result INTEGER
        );
        CREATE TABLE IF NOT EXISTS picks (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            match_id INTEGER NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
            home_score INTEGER NOT NULL CHECK(home_score BETWEEN 0 AND 20),
            away_score INTEGER NOT NULL CHECK(away_score BETWEEN 0 AND 20),
            PRIMARY KEY (user_id, match_id)
        );
        CREATE TABLE IF NOT EXISTS payments (
            round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paid INTEGER NOT NULL DEFAULT 0 CHECK(paid IN (0, 1)),
            paid_at TEXT,
            PRIMARY KEY (round_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS winner_verifications (
            round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code TEXT NOT NULL UNIQUE,
            PRIMARY KEY (round_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS prize_payouts (
            round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount_cents INTEGER NOT NULL CHECK(amount_cents >= 0),
            paid_at TEXT NOT NULL,
            PRIMARY KEY (round_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            crest_url TEXT
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    if "role" not in columns:
        db.execute(
            "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'player'"
        )
    if "is_blocked" not in columns:
        db.execute(
            "ALTER TABLE users ADD COLUMN is_blocked INTEGER NOT NULL DEFAULT 0"
        )
    payment_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(payments)")
    }
    if "paid_at" not in payment_columns:
        db.execute("ALTER TABLE payments ADD COLUMN paid_at TEXT")


def init_database() -> None:
    with connect_db() as db:
        if DATABASE_URL:
            create_postgres_schema(db)
        else:
            create_sqlite_schema(db)

        if not db.execute(
            "SELECT 1 FROM app_settings WHERE key = 'teams_seeded'"
        ).fetchone():
            db.executemany(
                "INSERT OR IGNORE INTO teams(name, crest_url) VALUES (?, NULL)",
                [(team,) for team in TEAMS],
            )
            db.execute(
                """
                INSERT INTO app_settings(key, value) VALUES ('teams_seeded', '1')
                ON CONFLICT(key) DO NOTHING
                """
            )

        if (
            not DATABASE_URL
            and not db.execute("SELECT COUNT(*) FROM rounds").fetchone()[0]
            and not db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        ):
            db.execute(
                "INSERT INTO rounds(id, name, date_range, status) VALUES"
                "(1, 'Semana 1', '10/10 a 11/10', 'finished'),"
                "(2, 'Semana 2', '17/10 a 18/10', 'active')"
            )
            db.executemany(
                """
                INSERT INTO matches(round_id, starts_at, home_team, away_team,
                                   home_result, away_result)
                VALUES (1, ?, ?, ?, ?, ?)
                """,
                WEEK_ONE_MATCHES,
            )
            db.executemany(
                """
                INSERT INTO matches(round_id, starts_at, home_team, away_team)
                VALUES (2, ?, ?, ?)
                """,
                WEEK_TWO_MATCHES,
            )
            demo_hash = hash_password("torcida123")
            db.execute(
                "INSERT INTO users(name, email, password_hash, team) VALUES"
                "('Rafa Torcedor', 'torcedor@futscores.com', ?, 'Palmeiras')",
                (demo_hash,),
            )
            member_hash = hash_password(secrets.token_urlsafe(32))
            db.executemany(
                """
                INSERT INTO users(name, email, password_hash, team)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        name,
                        f"participante{index}@futscores.local",
                        member_hash,
                        team,
                    )
                    for index, (name, team) in enumerate(DEMO_MEMBERS, start=1)
                    if name != "Rafa Torcedor"
                ],
            )

        if DATABASE_URL and not os.environ.get("FUTSCORES_ADMIN_PASSWORD"):
            raise RuntimeError(
                "Configure FUTSCORES_ADMIN_PASSWORD nas variáveis de ambiente."
            )
        admin_email = os.environ.get("FUTSCORES_ADMIN_EMAIL", "admin@futscores.com").strip().lower()
        admin_password = os.environ.get("FUTSCORES_ADMIN_PASSWORD", "admin123")
        if len(admin_password) < 8:
            raise ValueError("FUTSCORES_ADMIN_PASSWORD precisa ter ao menos 8 caracteres.")
        existing_admin = db.execute(
            "SELECT id, email, password_hash FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()
        if existing_admin is None:
            db.execute(
                """
                INSERT INTO users(name, email, password_hash, team, role)
                VALUES ('Administrador', ?, ?, 'Brasil', 'admin')
                """,
                (admin_email, hash_password(admin_password)),
            )
        elif "FUTSCORES_ADMIN_EMAIL" in os.environ or "FUTSCORES_ADMIN_PASSWORD" in os.environ:
            configured_email = os.environ.get("FUTSCORES_ADMIN_EMAIL", existing_admin["email"]).strip().lower()
            configured_hash = (
                hash_password(admin_password)
                if "FUTSCORES_ADMIN_PASSWORD" in os.environ
                else existing_admin["password_hash"]
            )
            db.execute(
                "UPDATE users SET email = ?, password_hash = ? WHERE id = ?",
                (configured_email, configured_hash, existing_admin["id"]),
            )
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))


def public_user(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "team": row["team"],
        "role": row["role"],
    }


def make_teams_state() -> list[dict[str, object]]:
    with connect_db() as db:
        return [
            {"id": row["id"], "name": row["name"], "crestUrl": row["crest_url"]}
            for row in db.execute("SELECT * FROM teams ORDER BY name COLLATE NOCASE")
        ]


def normalized_crest_url(value: object) -> tuple[bool, str | None]:
    if value is None or value == "":
        return True, None
    if not isinstance(value, str) or len(value) > 2048:
        return False, None
    url = value.strip()
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        valid = False
    return (True, url) if valid else (False, None)


def match_has_started(starts_at: str, now: datetime | None = None) -> bool:
    kickoff = datetime.fromisoformat(starts_at)
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    return kickoff.astimezone(timezone.utc) <= (now or datetime.now(timezone.utc))


def round_payment_deadline(
    db: sqlite3.Connection,
    round_id: int,
) -> str | None:
    starts = [
        row["starts_at"]
        for row in db.execute(
            "SELECT starts_at FROM matches WHERE round_id = ?",
            (round_id,),
        )
    ]
    if not starts:
        return None
    return min(
        starts,
        key=lambda starts_at: datetime.fromisoformat(starts_at).astimezone(timezone.utc),
    )


def payment_is_eligible(
    paid: bool,
    paid_at: str | None,
    deadline: str | None,
) -> bool:
    if not paid:
        return False
    if paid_at is None or deadline is None:
        return True
    payment_time = datetime.fromisoformat(paid_at)
    cutoff = datetime.fromisoformat(deadline)
    if payment_time.tzinfo is None:
        payment_time = payment_time.replace(tzinfo=timezone.utc)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    return payment_time.astimezone(timezone.utc) < cutoff.astimezone(timezone.utc)


def ensure_winner_verification_codes(
    db: sqlite3.Connection,
    round_id: int,
    winners: list[dict[str, object]],
) -> dict[int, str]:
    codes: dict[int, str] = {}
    for winner in winners:
        user_id = int(winner["id"])
        existing = db.execute(
            "SELECT code FROM winner_verifications WHERE round_id = ? AND user_id = ?",
            (round_id, user_id),
        ).fetchone()
        while existing is None:
            code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
            db.execute(
                """
                INSERT OR IGNORE INTO winner_verifications(round_id, user_id, code)
                VALUES (?, ?, ?)
                """,
                (round_id, user_id, code),
            )
            existing = db.execute(
                "SELECT code FROM winner_verifications WHERE round_id = ? AND user_id = ?",
                (round_id, user_id),
            ).fetchone()
        codes[user_id] = existing["code"]
    return codes


def make_finished_round_summary(
    db: sqlite3.Connection,
    round_row: sqlite3.Row | None,
    user_id: int,
) -> dict[str, object] | None:
    if round_row is None:
        return None

    matches = db.execute(
        "SELECT * FROM matches WHERE round_id = ? ORDER BY starts_at, id",
        (round_row["id"],),
    ).fetchall()
    if not matches or any(
        match["home_result"] is None or match["away_result"] is None
        for match in matches
    ):
        return None

    deadline = round_payment_deadline(db, round_row["id"])
    players = [
        player
        for player in db.execute(
            """
            SELECT u.id, u.name, p.paid, p.paid_at FROM users u
            JOIN payments p ON p.user_id = u.id AND p.round_id = ?
            WHERE u.role = 'player' AND u.is_blocked = 0
            ORDER BY u.name COLLATE NOCASE, u.id
            """,
            (round_row["id"],),
        )
        if payment_is_eligible(bool(player["paid"]), player["paid_at"], deadline)
    ]
    picks_by_user: dict[int, dict[int, tuple[int, int]]] = {
        player["id"]: {} for player in players
    }
    for row in db.execute(
        """
        SELECT p.user_id, p.match_id, p.home_score, p.away_score
        FROM picks p
        JOIN matches m ON m.id = p.match_id
        JOIN users u ON u.id = p.user_id
        WHERE m.round_id = ? AND u.role = 'player' AND u.is_blocked = 0
        """,
        (round_row["id"],),
    ):
        if row["user_id"] not in picks_by_user:
            continue
        picks_by_user[row["user_id"]][row["match_id"]] = (
            row["home_score"],
            row["away_score"],
        )

    player_scores = []
    for player in players:
        player_picks = picks_by_user[player["id"]]
        if not player_picks:
            continue
        points = 0
        exact = 0
        for match in matches:
            prediction = player_picks.get(match["id"])
            if prediction is None:
                continue
            result = (match["home_result"], match["away_result"])
            points += score_points(prediction, result)
            exact += prediction == result
        player_scores.append(
            {
                "id": player["id"],
                "name": player["name"],
                "points": points,
                "exact": exact,
            }
        )

    winners: list[dict[str, object]] = []
    paid_rows = db.execute(
        """
        SELECT p.paid_at
        FROM payments p JOIN users u ON u.id = p.user_id
        WHERE p.round_id = ? AND p.paid = 1 AND u.role = 'player'
        """,
        (round_row["id"],),
    ).fetchall()
    pool_cents = round_row["prize_cents"] * sum(
        payment_is_eligible(True, payment["paid_at"], deadline)
        for payment in paid_rows
    )
    if player_scores:
        highest_points = max(player["points"] for player in player_scores)
        winners = sorted(
            (player for player in player_scores if player["points"] == highest_points),
            key=lambda player: (player["name"].casefold(), player["id"]),
        )
        if winners:
            share, remainder = divmod(pool_cents, len(winners))
            for index, winner in enumerate(winners):
                winner["payoutCents"] = share + int(index < remainder)
    verification_codes = ensure_winner_verification_codes(
        db, round_row["id"], winners
    )
    payout_rows = {
        row["user_id"]: row
        for row in db.execute(
            "SELECT user_id, amount_cents, paid_at FROM prize_payouts WHERE round_id = ?",
            (round_row["id"],),
        )
    }
    for winner in winners:
        payout = payout_rows.get(winner["id"])
        winner["paidCents"] = payout["amount_cents"] if payout else 0
        winner["paidAt"] = payout["paid_at"] if payout else None

    winner_picks = {
        winner["id"]: picks_by_user[winner["id"]]
        for winner in winners
    }
    comparison = []
    user_picks = picks_by_user.get(user_id, {})
    for match in matches:
        result = (match["home_result"], match["away_result"])
        user_pick = user_picks.get(match["id"])
        comparison.append(
            {
                "id": match["id"],
                "home": match["home_team"],
                "away": match["away_team"],
                "homeResult": result[0],
                "awayResult": result[1],
                "userPick": list(user_pick) if user_pick else None,
                "userPoints": score_points(user_pick, result) if user_pick else 0,
                "userExact": user_pick == result,
                "winnerPicks": [
                    {
                        "userId": winner["id"],
                        "name": winner["name"],
                        "pick": (
                            list(winner_picks[winner["id"]][match["id"]])
                            if match["id"] in winner_picks[winner["id"]]
                            else None
                        ),
                        "points": (
                            score_points(
                                winner_picks[winner["id"]][match["id"]], result
                            )
                            if match["id"] in winner_picks[winner["id"]]
                            else 0
                        ),
                        "exact": winner_picks[winner["id"]].get(match["id"]) == result,
                    }
                    for winner in winners
                ],
            }
        )

    user_winner = next(
        (winner for winner in winners if winner["id"] == user_id),
        None,
    )
    return {
        "id": round_row["id"],
        "name": round_row["name"],
        "dateRange": round_row["date_range"],
        "poolCents": pool_cents,
        "isWinner": user_winner is not None,
        "userPoints": next(
            (player["points"] for player in player_scores if player["id"] == user_id),
            0,
        ),
        "userExact": next(
            (player["exact"] for player in player_scores if player["id"] == user_id),
            0,
        ),
        "userPayoutCents": user_winner["payoutCents"] if user_winner else 0,
        "userVerificationCode": (
            verification_codes[user_id] if user_winner else None
        ),
        "winners": winners,
        "matches": comparison,
    }


def make_state(user_id: int) -> dict[str, object]:
    with connect_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        teams = [
            {"id": row["id"], "name": row["name"], "crestUrl": row["crest_url"]}
            for row in db.execute("SELECT * FROM teams ORDER BY name COLLATE NOCASE")
        ]
        latest_round = db.execute(
            "SELECT * FROM rounds ORDER BY id DESC LIMIT 1"
        ).fetchone()
        finished_round_summary = (
            make_finished_round_summary(db, latest_round, user_id)
            if latest_round and latest_round["status"] == "finished"
            else None
        )
        active_round = db.execute(
            "SELECT * FROM rounds WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if active_round is None:
            active_round = db.execute(
                "SELECT * FROM rounds ORDER BY id DESC LIMIT 1"
            ).fetchone()
        payment_deadline = (
            round_payment_deadline(db, active_round["id"])
            if active_round
            else None
        )
        user_payment = (
            db.execute(
                "SELECT paid, paid_at FROM payments WHERE round_id = ? AND user_id = ?",
                (active_round["id"], user_id),
            ).fetchone()
            if active_round
            else None
        )
        user_eligible = bool(
            user_payment
            and payment_is_eligible(
                bool(user_payment["paid"]),
                user_payment["paid_at"],
                payment_deadline,
            )
        )
        paid_count = (
            db.execute(
                """
                SELECT COUNT(*)
                FROM payments p JOIN users u ON u.id = p.user_id
                WHERE p.round_id = ? AND p.paid = 1 AND u.role = 'player'
                  AND (
                    p.paid_at IS NULL OR ? IS NULL
                    OR julianday(p.paid_at) < julianday(?)
                  )
                """,
                (active_round["id"], payment_deadline, payment_deadline),
            ).fetchone()[0]
            if active_round
            else 0
        )
        matches = (
            db.execute(
                "SELECT * FROM matches WHERE round_id = ? ORDER BY starts_at, id",
                (active_round["id"],),
            ).fetchall()
            if active_round
            else []
        )
        picks = db.execute(
            """
            SELECT match_id, home_score, away_score FROM picks WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
        picks_by_match = {
            row["match_id"]: [row["home_score"], row["away_score"]]
            for row in picks
        }

        standings = []
        members = db.execute(
            "SELECT * FROM users WHERE role = 'player' AND is_blocked = 0"
        ).fetchall()
        round_deadlines: dict[int, str | None] = {}
        for member in members:
            member_picks = db.execute(
                """
                SELECT p.home_score, p.away_score, m.home_result, m.away_result,
                       r.id AS round_id, pay.paid_at
                FROM picks p JOIN matches m ON m.id = p.match_id
                JOIN rounds r ON r.id = m.round_id
                JOIN payments pay ON pay.user_id = p.user_id
                                  AND pay.round_id = r.id AND pay.paid = 1
                WHERE p.user_id = ? AND r.status IN ('finished', 'active')
                  AND m.home_result IS NOT NULL AND m.away_result IS NOT NULL
                """,
                (member["id"],),
            ).fetchall()
            eligible_picks = []
            for pick in member_picks:
                round_id = pick["round_id"]
                if round_id not in round_deadlines:
                    round_deadlines[round_id] = round_payment_deadline(db, round_id)
                if payment_is_eligible(
                    True,
                    pick["paid_at"],
                    round_deadlines[round_id],
                ):
                    eligible_picks.append(pick)
            member_picks = eligible_picks
            if not member_picks:
                continue
            points = sum(
                score_points(
                    (pick["home_score"], pick["away_score"]),
                    (pick["home_result"], pick["away_result"]),
                )
                for pick in member_picks
            )
            exact = sum(
                pick["home_score"] == pick["home_result"]
                and pick["away_score"] == pick["away_result"]
                for pick in member_picks
            )
            standings.append(
                {
                    **public_user(member),
                    "points": points,
                    "exact": exact,
                    "picks": len(member_picks),
                }
            )
        standings.sort(key=lambda entry: (-entry["points"], -entry["exact"], entry["name"].casefold()))

        history_rows = db.execute(
            "SELECT * FROM rounds WHERE status = 'finished' ORDER BY id DESC"
        ).fetchall()
        history = []
        for old_round in history_rows:
            old_points, old_exact = 0, 0
            history_deadline = round_payment_deadline(db, old_round["id"])
            round_payment = db.execute(
                "SELECT paid, paid_at FROM payments WHERE round_id = ? AND user_id = ?",
                (old_round["id"], user_id),
            ).fetchone()
            eligible = bool(
                round_payment
                and payment_is_eligible(
                    bool(round_payment["paid"]),
                    round_payment["paid_at"],
                    history_deadline,
                )
            )
            old_matches = db.execute(
                """
                SELECT * FROM matches
                WHERE round_id = ? AND home_result IS NOT NULL AND away_result IS NOT NULL
                ORDER BY starts_at, id
                """,
                (old_round["id"],),
            ).fetchall()
            for match in old_matches:
                pick = db.execute(
                    "SELECT home_score, away_score FROM picks "
                    "WHERE user_id = ? AND match_id = ?",
                    (user_id, match["id"]),
                ).fetchone()
                if pick is None:
                    continue
                result = (match["home_result"], match["away_result"])
                prediction = (pick["home_score"], pick["away_score"])
                old_points += score_points(prediction, result)
                old_exact += prediction == result
            history.append(
                {
                    "id": old_round["id"],
                    "name": old_round["name"],
                    "dateRange": old_round["date_range"],
                    "points": old_points if eligible else 0,
                    "exact": old_exact if eligible else 0,
                    "eligible": eligible,
                    "rank": None,
                    "paidOutCents": db.execute(
                        "SELECT COALESCE(SUM(amount_cents), 0) FROM prize_payouts WHERE round_id = ?",
                        (old_round["id"],),
                    ).fetchone()[0],
                    "payouts": [
                        {
                            "name": payout["name"],
                            "amountCents": payout["amount_cents"],
                        }
                        for payout in db.execute(
                            """
                            SELECT u.name, p.amount_cents
                            FROM prize_payouts p JOIN users u ON u.id = p.user_id
                            WHERE p.round_id = ?
                            ORDER BY u.name COLLATE NOCASE, u.id
                            """,
                            (old_round["id"],),
                        )
                    ],
                    "matches": [
                        {
                            "id": match["id"],
                            "home": match["home_team"],
                            "away": match["away_team"],
                            "homeResult": match["home_result"],
                            "awayResult": match["away_result"],
                        }
                        for match in old_matches
                    ],
                }
            )

        user_rank = next(
            (index for index, entry in enumerate(standings, start=1) if entry["id"] == user_id),
            None,
        )
        total_points = sum(item["points"] for item in history)
        now = datetime.now(timezone.utc)
        round_matches = []
        for match in matches:
            started = match_has_started(match["starts_at"], now)
            result_available = match["home_result"] is not None and (
                started or active_round["status"] == "finished"
            )
            pick = picks_by_match.get(match["id"])
            other_picks = []
            if started:
                other_picks = [
                    {
                        "userId": row["user_id"],
                        "name": row["name"],
                        "pick": [row["home_score"], row["away_score"]],
                        "points": (
                            score_points(
                                (row["home_score"], row["away_score"]),
                                (match["home_result"], match["away_result"]),
                            )
                            if result_available
                            else None
                        ),
                    }
                    for row in db.execute(
                        """
                        SELECT p.user_id, u.name, p.home_score, p.away_score
                        FROM picks p JOIN users u ON u.id = p.user_id
                        JOIN payments pay ON pay.user_id = p.user_id
                                          AND pay.round_id = ? AND pay.paid = 1
                        WHERE p.match_id = ? AND p.user_id != ?
                          AND u.role = 'player' AND u.is_blocked = 0
                          AND (
                            pay.paid_at IS NULL OR ? IS NULL
                            OR julianday(pay.paid_at) < julianday(?)
                          )
                        ORDER BY u.name COLLATE NOCASE
                        """,
                        (
                            active_round["id"],
                            match["id"],
                            user_id,
                            payment_deadline,
                            payment_deadline,
                        ),
                    )
                ]
            round_matches.append(
                {
                    "id": match["id"],
                    "startsAt": match["starts_at"],
                    "home": match["home_team"],
                    "away": match["away_team"],
                    "started": started,
                    "homeResult": match["home_result"] if result_available else None,
                    "awayResult": match["away_result"] if result_available else None,
                    "pick": pick,
                    "pickPoints": (
                        score_points(
                            (pick[0], pick[1]),
                            (match["home_result"], match["away_result"]),
                        )
                        if pick and result_available and user_eligible
                        else None
                    ),
                    "otherPicks": other_picks,
                }
            )
        return {
            "user": public_user(user),
            "teams": teams,
            "finishedRound": finished_round_summary,
            "round": {
                "id": active_round["id"] if active_round else None,
                "name": active_round["name"] if active_round else "Sem rodada",
                "dateRange": active_round["date_range"] if active_round else "",
                "status": active_round["status"] if active_round else "finished",
                "matchCount": len(matches),
                "prizeCents": active_round["prize_cents"] if active_round else 0,
                "paymentPaid": user_eligible,
                "eligible": user_eligible,
                "paymentDeadline": payment_deadline,
                "paymentOpen": bool(
                    active_round
                    and active_round["status"] == "active"
                    and (
                        payment_deadline is None
                        or not match_has_started(payment_deadline)
                    )
                ),
                "userPaidCents": (
                    active_round["prize_cents"]
                    if active_round and user_eligible
                    else 0
                ),
                "paidCount": paid_count,
                "participants": (
                    [
                        {
                            "id": member["id"],
                            "name": member["name"],
                            "team": member["team"],
                            "paid": payment_is_eligible(
                                bool(member["paid"]),
                                member["paid_at"],
                                payment_deadline,
                            ),
                            "hasPicks": bool(member["has_picks"]),
                        }
                        for member in db.execute(
                            """
                            SELECT u.id, u.name, u.team,
                                   COALESCE(p.paid, 0) AS paid,
                                   p.paid_at,
                                   EXISTS(
                                       SELECT 1 FROM picks pk
                                       JOIN matches mt ON mt.id = pk.match_id
                                       WHERE pk.user_id = u.id AND mt.round_id = ?
                                   ) AS has_picks
                            FROM users u
                            LEFT JOIN payments p ON p.user_id = u.id AND p.round_id = ?
                            WHERE u.role = 'player' AND u.is_blocked = 0
                            ORDER BY u.name COLLATE NOCASE, u.id
                            """,
                            (active_round["id"], active_round["id"]),
                        )
                    ]
                    if active_round
                    else []
                ),
                "totalCollectedCents": (
                    active_round["prize_cents"] * paid_count if active_round else 0
                ),
                "matches": round_matches,
            },
            "standings": standings,
            "history": history,
            "summary": {
                "rounds": len(history),
                "wins": 0,
                "points": total_points,
                "rank": user_rank,
                "totalPayoutCents": db.execute(
                    "SELECT COALESCE(SUM(amount_cents), 0) FROM prize_payouts"
                ).fetchone()[0],
            },
        }


def make_admin_state() -> dict[str, object]:
    with connect_db() as db:
        rounds = db.execute("SELECT * FROM rounds ORDER BY id DESC").fetchall()
        members = db.execute(
            """
            SELECT id, name, email, team, is_blocked
            FROM users WHERE role = 'player'
            ORDER BY name COLLATE NOCASE
            """
        ).fetchall()
        rounds_data = []
        admin_id = db.execute(
            "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
        ).fetchone()
        for round_row in rounds:
            deadline = round_payment_deadline(db, round_row["id"])
            matches = db.execute(
                "SELECT * FROM matches WHERE round_id = ? ORDER BY starts_at, id",
                (round_row["id"],),
            ).fetchall()
            finished_summary = (
                make_finished_round_summary(
                    db, round_row, admin_id["id"] if admin_id else 0
                )
                if round_row["status"] == "finished"
                else None
            )
            champion_codes = [
                {
                    "userId": winner["id"],
                    "name": winner["name"],
                    "code": db.execute(
                        """
                        SELECT code FROM winner_verifications
                        WHERE round_id = ? AND user_id = ?
                        """,
                        (round_row["id"], winner["id"]),
                    ).fetchone()["code"],
                }
                for winner in (
                    finished_summary["winners"] if finished_summary else []
                )
            ]
            paid_user_ids = {
                row["user_id"]
                for row in db.execute(
                    """
                    SELECT user_id, paid_at FROM payments
                    WHERE round_id = ? AND paid = 1
                    """,
                    (round_row["id"],),
                )
                if payment_is_eligible(True, row["paid_at"], deadline)
            }
            round_participants = []
            for member in members:
                payment = db.execute(
                    """
                    SELECT paid, paid_at FROM payments
                    WHERE round_id = ? AND user_id = ?
                    """,
                    (round_row["id"], member["id"]),
                ).fetchone()
                eligible = bool(
                    payment
                    and payment_is_eligible(
                        bool(payment["paid"]),
                        payment["paid_at"],
                        deadline,
                    )
                )
                pick_count = db.execute(
                    """
                    SELECT COUNT(*)
                    FROM picks p JOIN matches m ON m.id = p.match_id
                    WHERE p.user_id = ? AND m.round_id = ?
                    """,
                    (member["id"], round_row["id"]),
                ).fetchone()[0]
                round_participants.append(
                    {
                        "id": member["id"],
                        "name": member["name"],
                        "team": member["team"],
                        "paid": eligible,
                        "pickCount": pick_count,
                        "hasPicks": pick_count > 0,
                        "blocked": bool(member["is_blocked"]),
                    }
                )
            payouts_by_user = {
                payout["user_id"]: payout
                for payout in db.execute(
                    """
                    SELECT user_id, amount_cents, paid_at
                    FROM prize_payouts WHERE round_id = ?
                    """,
                    (round_row["id"],),
                )
            }
            payout_winners = [
                {
                    "userId": winner["id"],
                    "name": winner["name"],
                    "dueCents": winner["payoutCents"],
                    "paidCents": (
                        payouts_by_user[winner["id"]]["amount_cents"]
                        if winner["id"] in payouts_by_user
                        else 0
                    ),
                    "paidAt": (
                        payouts_by_user[winner["id"]]["paid_at"]
                        if winner["id"] in payouts_by_user
                        else None
                    ),
                }
                for winner in (
                    finished_summary["winners"] if finished_summary else []
                )
            ]
            rounds_data.append(
                {
                    "id": round_row["id"],
                    "name": round_row["name"],
                    "dateRange": round_row["date_range"],
                    "status": round_row["status"],
                    "prizeCents": round_row["prize_cents"],
                    "paymentDeadline": deadline,
                    "paymentOpen": bool(
                        round_row["status"] == "active"
                        and (deadline is None or not match_has_started(deadline))
                    ),
                    "championCodes": champion_codes,
                    "totalCollectedCents": (
                        round_row["prize_cents"] * len(paid_user_ids)
                    ),
                    "calculatedPrizeCents": (
                        finished_summary["poolCents"] if finished_summary else 0
                    ),
                    "paidOutCents": sum(
                        payout["amount_cents"] for payout in payouts_by_user.values()
                    ),
                    "payoutWinners": payout_winners,
                    "paidUserIds": sorted(paid_user_ids),
                    "participants": round_participants,
                    "matches": [
                        {
                            "id": match["id"],
                            "startsAt": match["starts_at"],
                            "home": match["home_team"],
                            "away": match["away_team"],
                            "homeResult": match["home_result"],
                            "awayResult": match["away_result"],
                            "pickCount": db.execute(
                                "SELECT COUNT(*) FROM picks WHERE match_id = ?",
                                (match["id"],),
                            ).fetchone()[0],
                        }
                        for match in matches
                    ],
                }
            )
        return {
            "rounds": rounds_data,
            "members": [dict(member) for member in members],
            "totalCollectedCents": sum(
                round_data["totalCollectedCents"] for round_data in rounds_data
            ),
            "totalPaidOutCents": db.execute(
                "SELECT COALESCE(SUM(amount_cents), 0) FROM prize_payouts"
            ).fetchone()[0],
        }


def valid_score(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 20


def normalize_datetime(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


class FutScoresHandler(BaseHTTPRequestHandler):
    server_version = "FutScores/1.0"

    def _secure_cookie_suffix(self) -> str:
        forwarded_proto = self.headers.get("x-forwarded-proto", "").split(",", 1)[0]
        return "; Secure" if os.environ.get("VERCEL") == "1" or forwarded_proto == "https" else ""

    def _send(
        self,
        status: HTTPStatus,
        payload: object,
        content_type: str = "application/json; charset=utf-8",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if isinstance(payload, bytes):
            body = payload
        elif content_type.startswith("application/json"):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        else:
            body = str(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: http: https:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        if content_type.startswith("application/json"):
            self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for name, value in extra_headers.items():
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 64_000:
                raise ValueError
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("Envie dados válidos no formato JSON.") from exc
        if not isinstance(body, dict):
            raise ValueError("O corpo da requisição deve ser um objeto.")
        return body

    def _cookie(self, name: str) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = cookie.get(name)
        return morsel.value if morsel else None

    def _current_user(self) -> sqlite3.Row | None:
        token = self._cookie("futscores_session")
        if not token:
            return None
        now = int(time.time())
        with connect_db() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            return db.execute(
                """
                SELECT users.* FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ? AND sessions.expires_at > ?
                  AND users.is_blocked = 0
                """,
                (token, now),
            ).fetchone()

    def _require_user(self) -> sqlite3.Row | None:
        user = self._current_user()
        if user is None:
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "Entre na sua conta para continuar."})
        return user

    def _require_admin(self) -> sqlite3.Row | None:
        user = self._require_user()
        if user is not None and user["role"] != "admin":
            self._send(HTTPStatus.FORBIDDEN, {"error": "Acesso exclusivo para administradores."})
            return None
        return user

    def _admin_post(self, path: str, body: dict[str, object]) -> None:
        if path == "/api/admin/teams":
            name = body.get("name")
            name = name.strip() if isinstance(name, str) else ""
            valid_url, crest_url = normalized_crest_url(body.get("crestUrl"))
            if not 2 <= len(name) <= 60 or not valid_url:
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "Informe um nome de time válido e um link HTTP ou HTTPS para o escudo."},
                )
                return
            try:
                with connect_db() as db:
                    cursor = db.execute(
                        "INSERT INTO teams(name, crest_url) VALUES (?, ?) RETURNING id",
                        (name, crest_url),
                    )
                    team_id = cursor.fetchone()[0]
            except DB_INTEGRITY_ERRORS:
                self._send(HTTPStatus.CONFLICT, {"error": "Já existe um time com esse nome."})
                return
            self._send(HTTPStatus.CREATED, {"id": team_id})
            return

        if path == "/api/admin/rounds":
            name = str(body.get("name", "")).strip()
            date_range = str(body.get("dateRange", "")).strip()
            prize_cents = body.get("prizeCents", 500)
            if not name or len(name) > 50 or not date_range or len(date_range) > 50:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "Informe o nome e o período da rodada."})
                return
            if not isinstance(prize_cents, int) or isinstance(prize_cents, bool) or not 0 <= prize_cents <= 100_000_000:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "O valor do bolão é inválido."})
                return
            with connect_db() as db:
                db.execute("UPDATE rounds SET status = 'finished' WHERE status = 'active'")
                cursor = db.execute(
                    """
                    INSERT INTO rounds(name, date_range, status, prize_cents)
                    VALUES (?, ?, 'active', ?) RETURNING id
                    """,
                    (name, date_range, prize_cents),
                )
                round_id = cursor.fetchone()[0]
            self._send(HTTPStatus.CREATED, {"id": round_id})
            return

        match = re.fullmatch(r"/api/admin/rounds/(\d+)/matches", path)
        if match:
            round_id = int(match.group(1))
            starts_at = normalize_datetime(body.get("startsAt"))
            home = body.get("home")
            away = body.get("away")
            if not starts_at or not isinstance(home, str) or not isinstance(away, str) or home == away:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "Confira os times e a data da partida."})
                return
            with connect_db() as db:
                active_teams = {
                    row["name"]
                    for row in db.execute("SELECT name FROM teams")
                }
                if home not in active_teams or away not in active_teams:
                    self._send(HTTPStatus.BAD_REQUEST, {"error": "Escolha times cadastrados no bolão."})
                    return
                if not db.execute("SELECT 1 FROM rounds WHERE id = ?", (round_id,)).fetchone():
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Rodada não encontrada."})
                    return
                cursor = db.execute(
                    """
                    INSERT INTO matches(round_id, starts_at, home_team, away_team)
                    VALUES (?, ?, ?, ?) RETURNING id
                    """,
                    (round_id, starts_at, home, away),
                )
                match_id = cursor.fetchone()[0]
            self._send(HTTPStatus.CREATED, {"id": match_id})
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "Ação administrativa não encontrada."})

    def _admin_put(self, path: str, body: dict[str, object]) -> None:
        team_update = re.fullmatch(r"/api/admin/teams/(\d+)", path)
        if team_update:
            team_id = int(team_update.group(1))
            name = body.get("name")
            name = name.strip() if isinstance(name, str) else ""
            valid_url, crest_url = normalized_crest_url(body.get("crestUrl"))
            if not 2 <= len(name) <= 60 or not valid_url:
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "Informe um nome de time válido e um link HTTP ou HTTPS para o escudo."},
                )
                return
            try:
                with connect_db() as db:
                    old_team = db.execute(
                        "SELECT name FROM teams WHERE id = ?", (team_id,)
                    ).fetchone()
                    if old_team is None:
                        self._send(HTTPStatus.NOT_FOUND, {"error": "Time não encontrado."})
                        return
                    db.execute(
                        "UPDATE teams SET name = ?, crest_url = ? WHERE id = ?",
                        (name, crest_url, team_id),
                    )
                    if old_team["name"] != name:
                        db.execute(
                            "UPDATE users SET team = ? WHERE team = ?",
                            (name, old_team["name"]),
                        )
                        db.execute(
                            """
                            UPDATE matches SET home_team = ? WHERE home_team = ?
                            """,
                            (name, old_team["name"]),
                        )
                        db.execute(
                            """
                            UPDATE matches SET away_team = ? WHERE away_team = ?
                            """,
                            (name, old_team["name"]),
                        )
            except DB_INTEGRITY_ERRORS:
                self._send(HTTPStatus.CONFLICT, {"error": "Já existe um time com esse nome."})
                return
            self._send(HTTPStatus.OK, {"ok": True})
            return

        member_update = re.fullmatch(r"/api/admin/members/(\d+)", path)
        if member_update:
            user_id = int(member_update.group(1))
            blocked = body.get("blocked")
            if not isinstance(blocked, bool):
                self._send(HTTPStatus.BAD_REQUEST, {"error": "O status de bloqueio é inválido."})
                return
            with connect_db() as db:
                cursor = db.execute(
                    """
                    UPDATE users SET is_blocked = ?
                    WHERE id = ? AND role = 'player'
                    """,
                    (int(blocked), user_id),
                )
                if cursor.rowcount == 0:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Participante não encontrado."})
                    return
            self._send(HTTPStatus.OK, {"ok": True})
            return

        payout_update = re.fullmatch(r"/api/admin/payouts/(\d+)/(\d+)", path)
        if payout_update:
            round_id, user_id = map(int, payout_update.groups())
            paid = body.get("paid")
            if not isinstance(paid, bool):
                self._send(HTTPStatus.BAD_REQUEST, {"error": "O status do prêmio é inválido."})
                return
            with connect_db() as db:
                round_row = db.execute(
                    "SELECT * FROM rounds WHERE id = ?", (round_id,)
                ).fetchone()
                user = db.execute(
                    "SELECT id FROM users WHERE id = ? AND role = 'player'",
                    (user_id,),
                ).fetchone()
                if round_row is None:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Rodada não encontrada."})
                    return
                if user is None:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Participante não encontrado."})
                    return
                existing = db.execute(
                    "SELECT 1 FROM prize_payouts WHERE round_id = ? AND user_id = ?",
                    (round_id, user_id),
                ).fetchone()
                if not paid:
                    db.execute(
                        "DELETE FROM prize_payouts WHERE round_id = ? AND user_id = ?",
                        (round_id, user_id),
                    )
                    self._send(HTTPStatus.OK, {"ok": True})
                    return
                if existing:
                    self._send(HTTPStatus.OK, {"ok": True})
                    return
                if round_row["status"] != "finished":
                    self._send(
                        HTTPStatus.CONFLICT,
                        {"error": "Só é possível registrar prêmios de rodadas encerradas."},
                    )
                    return
                summary = make_finished_round_summary(
                    db, round_row, user_id
                )
                winner = next(
                    (
                        item for item in summary["winners"]
                        if item["id"] == user_id
                    ),
                    None,
                ) if summary else None
                if winner is None:
                    self._send(
                        HTTPStatus.CONFLICT,
                        {"error": "Este participante não é campeão elegível desta rodada."},
                    )
                    return
                db.execute(
                    """
                    INSERT INTO prize_payouts(round_id, user_id, amount_cents, paid_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        round_id,
                        user_id,
                        winner["payoutCents"],
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            self._send(HTTPStatus.OK, {"ok": True})
            return

        round_match = re.fullmatch(r"/api/admin/rounds/(\d+)", path)
        if round_match:
            round_id = int(round_match.group(1))
            name = str(body.get("name", "")).strip()
            date_range = str(body.get("dateRange", "")).strip()
            prize_cents = body.get("prizeCents")
            status = body.get("status")
            if not name or len(name) > 50 or not date_range or len(date_range) > 50:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "Informe o nome e o período da rodada."})
                return
            if not isinstance(prize_cents, int) or isinstance(prize_cents, bool) or not 0 <= prize_cents <= 100_000_000:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "O valor do bolão é inválido."})
                return
            if status not in ("active", "finished"):
                self._send(HTTPStatus.BAD_REQUEST, {"error": "O status da rodada é inválido."})
                return
            with connect_db() as db:
                if not db.execute("SELECT 1 FROM rounds WHERE id = ?", (round_id,)).fetchone():
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Rodada não encontrada."})
                    return
                if status == "active":
                    db.execute(
                        "UPDATE rounds SET status = 'finished' WHERE status = 'active' AND id != ?",
                        (round_id,),
                    )
                db.execute(
                    """
                    UPDATE rounds SET name = ?, date_range = ?, prize_cents = ?, status = ?
                    WHERE id = ?
                    """,
                    (name, date_range, prize_cents, status, round_id),
                )
            self._send(HTTPStatus.OK, {"ok": True})
            return

        match_update = re.fullmatch(r"/api/admin/matches/(\d+)", path)
        if match_update:
            match_id = int(match_update.group(1))
            starts_at = normalize_datetime(body.get("startsAt"))
            home = body.get("home")
            away = body.get("away")
            home_result, away_result = body.get("homeResult"), body.get("awayResult")
            if (home_result is None) != (away_result is None):
                self._send(HTTPStatus.BAD_REQUEST, {"error": "Informe os dois placares do resultado ou deixe ambos vazios."})
                return
            if home_result is not None and (not valid_score(home_result) or not valid_score(away_result)):
                self._send(HTTPStatus.BAD_REQUEST, {"error": "Os resultados devem ser números inteiros de 0 a 20."})
                return
            if not starts_at or not isinstance(home, str) or not isinstance(away, str) or home == away:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "Confira os times e a data da partida."})
                return
            with connect_db() as db:
                existing = db.execute(
                    "SELECT home_team, away_team FROM matches WHERE id = ?",
                    (match_id,),
                ).fetchone()
                if existing is None:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Partida não encontrada."})
                    return
                active_teams = {
                    row["name"]
                    for row in db.execute("SELECT name FROM teams")
                }
                legacy_teams = {existing["home_team"], existing["away_team"]}
                if (
                    home not in active_teams | legacy_teams
                    or away not in active_teams | legacy_teams
                ):
                    self._send(HTTPStatus.BAD_REQUEST, {"error": "Escolha times cadastrados no bolão."})
                    return
                cursor = db.execute(
                    """
                    UPDATE matches
                    SET starts_at = ?, home_team = ?, away_team = ?,
                        home_result = ?, away_result = ?
                    WHERE id = ?
                    """,
                    (starts_at, home, away, home_result, away_result, match_id),
                )
                if cursor.rowcount == 0:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Partida não encontrada."})
                    return
            self._send(HTTPStatus.OK, {"ok": True})
            return

        payment_update = re.fullmatch(r"/api/admin/payments/(\d+)/(\d+)", path)
        if payment_update:
            round_id, user_id = map(int, payment_update.groups())
            paid = body.get("paid")
            if not isinstance(paid, bool):
                self._send(HTTPStatus.BAD_REQUEST, {"error": "O status de pagamento é inválido."})
                return
            with connect_db() as db:
                round_row = db.execute(
                    "SELECT id, status FROM rounds WHERE id = ?", (round_id,)
                ).fetchone()
                if round_row is None:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Rodada não encontrada."})
                    return
                if not db.execute(
                    "SELECT 1 FROM users WHERE id = ? AND role = 'player'", (user_id,)
                ).fetchone():
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Participante não encontrado."})
                    return
                existing_payment = db.execute(
                    """
                    SELECT paid, paid_at FROM payments
                    WHERE round_id = ? AND user_id = ?
                    """,
                    (round_id, user_id),
                ).fetchone()
                deadline = round_payment_deadline(db, round_id)
                already_eligible = bool(
                    existing_payment
                    and payment_is_eligible(
                        bool(existing_payment["paid"]),
                        existing_payment["paid_at"],
                        deadline,
                    )
                )
                if paid and not already_eligible and (
                    round_row["status"] != "active"
                    or (deadline is not None and match_has_started(deadline))
                ):
                    self._send(
                        HTTPStatus.CONFLICT,
                        {"error": "O prazo para confirmar pagamentos terminou no início do primeiro jogo."},
                    )
                    return
                paid_at = (
                    existing_payment["paid_at"]
                    if paid and existing_payment and existing_payment["paid"]
                    else datetime.now(timezone.utc).isoformat() if paid else None
                )
                db.execute(
                    """
                    INSERT INTO payments(round_id, user_id, paid, paid_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(round_id, user_id) DO UPDATE SET
                        paid = excluded.paid, paid_at = excluded.paid_at
                    """,
                    (round_id, user_id, int(paid), paid_at),
                )
            self._send(HTTPStatus.OK, {"ok": True})
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "Ação administrativa não encontrada."})

    def _admin_delete(self, path: str) -> None:
        round_match = re.fullmatch(r"/api/admin/rounds/(\d+)", path)
        if round_match:
            with connect_db() as db:
                cursor = db.execute(
                    "DELETE FROM rounds WHERE id = ?", (int(round_match.group(1)),)
                )
                if cursor.rowcount == 0:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Rodada não encontrada."})
                    return
            self._send(HTTPStatus.OK, {"ok": True})
            return

        team_match = re.fullmatch(r"/api/admin/teams/(\d+)", path)
        if team_match:
            with connect_db() as db:
                cursor = db.execute(
                    "DELETE FROM teams WHERE id = ?", (int(team_match.group(1)),)
                )
                if cursor.rowcount == 0:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Time não encontrado."})
                    return
            self._send(HTTPStatus.OK, {"ok": True})
            return

        member_match = re.fullmatch(r"/api/admin/members/(\d+)", path)
        if member_match:
            with connect_db() as db:
                cursor = db.execute(
                    "DELETE FROM users WHERE id = ? AND role = 'player'",
                    (int(member_match.group(1)),),
                )
                if cursor.rowcount == 0:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "Participante não encontrado."})
                    return
            self._send(HTTPStatus.OK, {"ok": True})
            return

        match = re.fullmatch(r"/api/admin/matches/(\d+)", path)
        if not match:
            self._send(HTTPStatus.NOT_FOUND, {"error": "Ação administrativa não encontrada."})
            return
        with connect_db() as db:
            cursor = db.execute("DELETE FROM matches WHERE id = ?", (int(match.group(1)),))
            if cursor.rowcount == 0:
                self._send(HTTPStatus.NOT_FOUND, {"error": "Partida não encontrada."})
                return
        self._send(HTTPStatus.OK, {"ok": True})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            user = self._require_user()
            if user:
                self._send(HTTPStatus.OK, make_state(user["id"]))
            return
        if path == "/api/admin":
            if self._require_admin():
                self._send(HTTPStatus.OK, make_admin_state())
            return
        if path == "/api/teams":
            self._send(HTTPStatus.OK, {"teams": make_teams_state()})
            return
        if path == "/":
            file_path = ROOT / "templates" / "index.html"
            content_type = "text/html; charset=utf-8"
        elif path in ("/static/style.css", "/static/app.js"):
            filename = Path(path).name
            file_path = ROOT / "static" / filename
            content_type = "text/css; charset=utf-8" if filename.endswith(".css") else "text/javascript; charset=utf-8"
        else:
            self._send(HTTPStatus.NOT_FOUND, {"error": "Página não encontrada."})
            return
        try:
            content = file_path.read_bytes()
        except OSError:
            self._send(HTTPStatus.NOT_FOUND, {"error": "Arquivo não encontrado."})
            return
        self._send(HTTPStatus.OK, content, content_type)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/admin/"):
            if self._require_admin() is None:
                return
            try:
                body = self._json_body()
            except ValueError as exc:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._admin_post(path, body)
            return
        if path not in ("/api/login", "/api/register", "/api/logout"):
            self._send(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
            return
        try:
            body = self._json_body()
        except ValueError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return

        if path == "/api/logout":
            token = self._cookie("futscores_session")
            if token:
                with connect_db() as db:
                    db.execute("DELETE FROM sessions WHERE token = ?", (token,))
            self._send(
                HTTPStatus.OK,
                {"ok": True},
                extra_headers={
                    "Set-Cookie": (
                        "futscores_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
                        f"{self._secure_cookie_suffix()}"
                    )
                },
            )
            return

        email = str(body.get("email", "")).strip().lower()
        password = body.get("password", "")
        if not email or not isinstance(password, str) or len(password) < 8:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "Informe e-mail e senha com ao menos 8 caracteres."})
            return

        if path == "/api/register":
            name = str(body.get("name", "")).strip()
            team = str(body.get("team", "")).strip()
            if len(name) < 2 or len(name) > 60:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "Seu nome deve ter entre 2 e 60 caracteres."})
                return
            if "@" not in email or len(email) > 254:
                self._send(HTTPStatus.BAD_REQUEST, {"error": "Informe um e-mail válido."})
                return
            try:
                with connect_db() as db:
                    if not db.execute(
                        "SELECT 1 FROM teams WHERE name = ?", (team,)
                    ).fetchone():
                        self._send(HTTPStatus.BAD_REQUEST, {"error": "Escolha um time da lista."})
                        return
                    cursor = db.execute(
                        "INSERT INTO users(name, email, password_hash, team) VALUES (?, ?, ?, ?) RETURNING id",
                        (name, email, hash_password(password), team),
                    )
                    user_id = cursor.fetchone()[0]
            except DB_INTEGRITY_ERRORS:
                self._send(HTTPStatus.CONFLICT, {"error": "Este e-mail já está cadastrado."})
                return
        else:
            with connect_db() as db:
                user = db.execute(
                    "SELECT * FROM users WHERE email = ?", (email,)
                ).fetchone()
                if user is None or not password_matches(password, user["password_hash"]):
                    self._send(HTTPStatus.UNAUTHORIZED, {"error": "E-mail ou senha incorretos."})
                    return
                if user["is_blocked"]:
                    self._send(HTTPStatus.FORBIDDEN, {"error": "Esta conta foi bloqueada pelo administrador."})
                    return
                user_id = user["id"]

        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + SESSION_SECONDS
        with connect_db() as db:
            db.execute("INSERT INTO sessions(token, user_id, expires_at) VALUES (?, ?, ?)", (token, user_id, expires_at))
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        self._send(
            HTTPStatus.OK,
            {"user": public_user(user)},
            extra_headers={
                "Set-Cookie": (
                    f"futscores_session={token}; Path=/; HttpOnly; SameSite=Lax; "
                    f"Max-Age={SESSION_SECONDS}{self._secure_cookie_suffix()}"
                )
            },
        )

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/admin/"):
            if self._require_admin() is None:
                return
            try:
                body = self._json_body()
            except ValueError as exc:
                self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._admin_put(path, body)
            return
        if path != "/api/picks":
            self._send(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
            return
        user = self._require_user()
        if user is None:
            return
        try:
            body = self._json_body()
        except ValueError as exc:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        picks = body.get("picks")
        if not isinstance(picks, list):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "A lista de palpites é inválida."})
            return
        with connect_db() as db:
            round_row = db.execute(
                "SELECT id FROM rounds WHERE status = 'active' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if round_row is None:
                self._send(HTTPStatus.CONFLICT, {"error": "Não há uma rodada aberta para palpites."})
                return
            match_rows = db.execute(
                "SELECT id, starts_at FROM matches WHERE round_id = ?", (round_row["id"],)
            ).fetchall()
            matches = {match["id"]: match["starts_at"] for match in match_rows}
            now = datetime.now(timezone.utc)
            open_match_ids = {
                match_id
                for match_id, starts_at in matches.items()
                if datetime.fromisoformat(starts_at).astimezone(timezone.utc) > now
            }
            submitted = set()
            to_save = []
            for pick in picks:
                if not isinstance(pick, dict):
                    self._send(HTTPStatus.BAD_REQUEST, {"error": "Um dos palpites é inválido."})
                    return
                match_id, home_score, away_score = (
                    pick.get("matchId"), pick.get("home"), pick.get("away")
                )
                if (
                    not isinstance(match_id, int)
                    or isinstance(match_id, bool)
                    or match_id not in matches
                    or match_id in submitted
                ):
                    self._send(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "Um dos palpites não corresponde a um jogo aberto da rodada."},
                    )
                    return
                if match_id not in open_match_ids:
                    self._send(
                        HTTPStatus.CONFLICT,
                        {"error": "O prazo para palpitar neste jogo terminou porque a partida já começou."},
                    )
                    return
                if (
                    not isinstance(home_score, int)
                    or isinstance(home_score, bool)
                    or not isinstance(away_score, int)
                    or isinstance(away_score, bool)
                    or not 0 <= home_score <= 20
                    or not 0 <= away_score <= 20
                ):
                    self._send(HTTPStatus.BAD_REQUEST, {"error": "Confira os placares: use números de 0 a 20."})
                    return
                submitted.add(match_id)
                to_save.append((user["id"], match_id, home_score, away_score))
            db.executemany(
                """
                INSERT INTO picks(user_id, match_id, home_score, away_score)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, match_id) DO UPDATE SET
                    home_score = excluded.home_score, away_score = excluded.away_score
                """,
                to_save,
            )
        self._send(HTTPStatus.OK, {"ok": True})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/admin/"):
            self._send(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
            return
        if self._require_admin() is None:
            return
        self._admin_delete(path)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.log_date_time_string()} {format % args}")


def main() -> None:
    host = os.environ.get("FUTSCORES_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    if host not in ("127.0.0.1", "localhost", "::1") and not os.environ.get("FUTSCORES_ADMIN_PASSWORD"):
        raise RuntimeError(
            "Defina FUTSCORES_ADMIN_PASSWORD antes de disponibilizar o servidor na rede."
        )
    init_database()
    server = ThreadingHTTPServer((host, port), FutScoresHandler)
    print(f"Fut Scores disponível em http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
