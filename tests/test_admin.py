import json
import re
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import app


class AdminApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = app.DB_PATH
        app.DB_PATH = Path(cls.temp_dir.name) / "test.sqlite3"
        app.init_database()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.FutScoresHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.admin_cookie = cls.login("admin@futscores.com", "admin123")
        cls.player_cookie = cls.login("torcedor@futscores.com", "torcida123")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()
        app.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    @classmethod
    def request_json(cls, path, method="GET", payload=None, cookie=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            cls.base_url + path,
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                **({"Cookie": cookie} if cookie else {}),
            },
        )
        try:
            with urlopen(request) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            finally:
                error.close()

    @classmethod
    def login(cls, email, password):
        request = Request(
            cls.base_url + "/api/login",
            data=json.dumps({"email": email, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request) as response:
            json.loads(response.read())
            return response.headers["Set-Cookie"].split(";", 1)[0]

    def test_admin_login_and_player_access_are_role_protected(self):
        status, payload = self.request_json("/api/state", cookie=self.admin_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["role"], "admin")

        status, payload = self.request_json("/api/admin", cookie=self.player_cookie)
        self.assertEqual(status, 403)
        self.assertIn("administradores", payload["error"])

    def test_admin_can_create_round_add_match_publish_result_and_record_payment(self):
        status, created = self.request_json(
            "/api/admin/rounds",
            "POST",
            {"name": "Semana de teste", "dateRange": "24/10 a 25/10", "prizeCents": 750},
            self.admin_cookie,
        )
        self.assertEqual(status, 201)
        round_id = created["id"]

        status, match_created = self.request_json(
            f"/api/admin/rounds/{round_id}/matches",
            "POST",
            {
                "home": "Palmeiras",
                "away": "Santos",
                "startsAt": "2026-10-24T18:00:00-03:00",
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 201)
        match_id = match_created["id"]

        status, _ = self.request_json(
            "/api/picks",
            "PUT",
            {"picks": [{"matchId": match_id, "home": 2, "away": 1}]},
            self.player_cookie,
        )
        self.assertEqual(status, 200)

        status, _ = self.request_json(
            f"/api/admin/matches/{match_id}",
            "PUT",
            {
                "home": "Palmeiras",
                "away": "Santos",
                "startsAt": "2026-10-24T18:00:00-03:00",
                "homeResult": 2,
                "awayResult": 1,
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 200)

        _, admin_state = self.request_json("/api/admin", cookie=self.admin_cookie)
        member = next(
            item for item in admin_state["members"]
            if item["email"] == "torcedor@futscores.com"
        )
        status, _ = self.request_json(
            f"/api/admin/payments/{round_id}/{member['id']}",
            "PUT",
            {"paid": True},
            self.admin_cookie,
        )
        self.assertEqual(status, 200)

        _, updated_admin_state = self.request_json("/api/admin", cookie=self.admin_cookie)
        saved_round = next(
            item for item in updated_admin_state["rounds"] if item["id"] == round_id
        )
        self.assertEqual(saved_round["matches"][0]["homeResult"], 2)
        self.assertIn(member["id"], saved_round["paidUserIds"])

        _, player_state = self.request_json("/api/state", cookie=self.player_cookie)
        self.assertTrue(player_state["round"]["paymentPaid"])

        status, _ = self.request_json(
            f"/api/admin/rounds/{round_id}",
            "PUT",
            {
                "name": "Semana de teste",
                "dateRange": "24/10 a 25/10",
                "prizeCents": 750,
                "status": "finished",
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        _, player_state = self.request_json("/api/state", cookie=self.player_cookie)
        self.assertEqual(player_state["round"]["status"], "finished")
        self.assertEqual(player_state["history"][0]["points"], 10)
        status, error = self.request_json(
            "/api/picks",
            "PUT",
            {"picks": []},
            self.player_cookie,
        )
        self.assertEqual(status, 409)
        self.assertIn("rodada aberta", error["error"])

    def test_admin_manages_teams_and_player_accounts(self):
        status, created_team = self.request_json(
            "/api/admin/teams",
            "POST",
            {"name": "Time de teste", "crestUrl": "https://example.com/crest.png"},
            self.admin_cookie,
        )
        self.assertEqual(status, 201)
        team_id = created_team["id"]
        _, teams = self.request_json("/api/teams")
        created_catalog_team = next(team for team in teams["teams"] if team["id"] == team_id)
        self.assertEqual(created_catalog_team["crestUrl"], "https://example.com/crest.png")

        status, _ = self.request_json(
            f"/api/admin/teams/{team_id}",
            "PUT",
            {"name": "Time renomeado", "crestUrl": ""},
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        _, teams = self.request_json("/api/teams")
        renamed_team = next(team for team in teams["teams"] if team["id"] == team_id)
        self.assertEqual(renamed_team["name"], "Time renomeado")
        self.assertIsNone(renamed_team["crestUrl"])

        status, _ = self.request_json(
            f"/api/admin/teams/{team_id}",
            "PUT",
            {"name": "Inválido", "crestUrl": "javascript:alert(1)"},
            self.admin_cookie,
        )
        self.assertEqual(status, 400)
        status, _ = self.request_json(
            f"/api/admin/teams/{team_id}",
            "DELETE",
            cookie=self.admin_cookie,
        )
        self.assertEqual(status, 200)

        member = next(
            item for item in self.request_json("/api/admin", cookie=self.admin_cookie)[1]["members"]
            if item["email"] == "torcedor@futscores.com"
        )
        status, _ = self.request_json(
            f"/api/admin/members/{member['id']}",
            "PUT",
            {"blocked": True},
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        status, _ = self.request_json("/api/state", cookie=self.player_cookie)
        self.assertEqual(status, 401)
        status, _ = self.request_json(
            "/api/login",
            "POST",
            {"email": "torcedor@futscores.com", "password": "torcida123"},
        )
        self.assertEqual(status, 403)

        status, _ = self.request_json(
            f"/api/admin/members/{member['id']}",
            "PUT",
            {"blocked": False},
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        status, created_member = self.request_json(
            "/api/register",
            "POST",
            {
                "name": "Conta para excluir",
                "email": "excluir@example.com",
                "password": "senhaSegura123",
                "team": "Palmeiras",
            },
        )
        self.assertEqual(status, 200)
        deleted_cookie = self.login("excluir@example.com", "senhaSegura123")
        status, _ = self.request_json(
            f"/api/admin/members/{created_member['user']['id']}",
            "DELETE",
            cookie=self.admin_cookie,
        )
        self.assertEqual(status, 200)
        status, _ = self.request_json("/api/state", cookie=deleted_cookie)
        self.assertEqual(status, 401)

    def test_competitor_picks_are_hidden_until_kickoff_and_match_points_are_returned(self):
        status, created_round = self.request_json(
            "/api/admin/rounds",
            "POST",
            {"name": "Rodada de comparação", "dateRange": "Teste", "prizeCents": 500},
            self.admin_cookie,
        )
        self.assertEqual(status, 201)
        kickoff = datetime.now(timezone.utc) + timedelta(days=1)
        status, created_match = self.request_json(
            f"/api/admin/rounds/{created_round['id']}/matches",
            "POST",
            {
                "home": "Palmeiras",
                "away": "Santos",
                "startsAt": kickoff.isoformat(),
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 201)
        match_id = created_match["id"]

        status, created_user = self.request_json(
            "/api/register",
            "POST",
            {
                "name": "Outro jogador",
                "email": "outro-jogador@example.com",
                "password": "senhaSegura123",
                "team": "Santos",
            },
        )
        self.assertEqual(status, 200)
        other_cookie = self.login("outro-jogador@example.com", "senhaSegura123")
        _, admin_state = self.request_json("/api/admin", cookie=self.admin_cookie)
        existing_player_id = next(
            member["id"] for member in admin_state["members"]
            if member["email"] == "torcedor@futscores.com"
        )
        for user_id in (existing_player_id, created_user["user"]["id"]):
            status, _ = self.request_json(
                f"/api/admin/payments/{created_round['id']}/{user_id}",
                "PUT",
                {"paid": True},
                self.admin_cookie,
            )
            self.assertEqual(status, 200)

        for cookie, score in ((self.player_cookie, (0, 0)), (other_cookie, (0, 0))):
            status, _ = self.request_json(
                "/api/picks",
                "PUT",
                {"picks": [{"matchId": match_id, "home": score[0], "away": score[1]}]},
                cookie,
            )
            self.assertEqual(status, 200)

        status, _ = self.request_json(
            "/api/picks",
            "PUT",
            {"picks": [{"matchId": match_id, "home": 1, "away": 0}]},
            self.player_cookie,
        )
        self.assertEqual(status, 200)
        _, edited_before_kickoff = self.request_json(
            "/api/state", cookie=self.player_cookie
        )
        self.assertEqual(edited_before_kickoff["round"]["matches"][0]["pick"], [1, 0])

        status, _ = self.request_json(
            f"/api/admin/matches/{match_id}",
            "PUT",
            {
                "home": "Palmeiras",
                "away": "Santos",
                "startsAt": kickoff.isoformat(),
                "homeResult": None,
                "awayResult": None,
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        _, before_kickoff = self.request_json("/api/state", cookie=self.player_cookie)
        hidden_match = before_kickoff["round"]["matches"][0]
        self.assertEqual(hidden_match["otherPicks"], [])
        self.assertIsNone(hidden_match["homeResult"])
        self.assertIsNone(hidden_match["pickPoints"])

        started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        with app.connect_db() as db:
            # Keep the test participant eligible after the fixture moves kickoff back.
            db.execute(
                "UPDATE payments SET paid_at = ? WHERE user_id IN (?, ?) AND round_id = ?",
                (
                    (started_at - timedelta(minutes=1)).isoformat(),
                    existing_player_id,
                    created_user["user"]["id"],
                    created_round["id"],
                ),
            )
        _, before_result = self.request_json("/api/state", cookie=self.player_cookie)
        before_result_points = {
            item["id"]: item["points"] for item in before_result["standings"]
        }
        status, _ = self.request_json(
            f"/api/admin/matches/{match_id}",
            "PUT",
            {
                "home": "Palmeiras",
                "away": "Santos",
                "startsAt": started_at.isoformat(),
                "homeResult": 1,
                "awayResult": 0,
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        _, after_kickoff = self.request_json("/api/state", cookie=self.player_cookie)
        started_match = after_kickoff["round"]["matches"][0]
        self.assertEqual(started_match["otherPicks"][0]["userId"], created_user["user"]["id"])
        self.assertEqual(started_match["otherPicks"][0]["pick"], [0, 0])
        self.assertEqual(started_match["pickPoints"], 10)
        self.assertEqual(started_match["otherPicks"][0]["points"], 1)
        updated_points = {
            item["id"]: item["points"] for item in after_kickoff["standings"]
        }
        self.assertEqual(
            updated_points[existing_player_id] - before_result_points.get(existing_player_id, 0),
            10,
        )
        self.assertEqual(
            updated_points[created_user["user"]["id"]]
            - before_result_points.get(created_user["user"]["id"], 0),
            1,
        )
        status, error = self.request_json(
            "/api/picks",
            "PUT",
            {"picks": [{"matchId": match_id, "home": 2, "away": 0}]},
            self.player_cookie,
        )
        self.assertEqual(status, 409)
        self.assertIn("partida já começou", error["error"])
        _, after_locked_edit = self.request_json(
            "/api/state", cookie=self.player_cookie
        )
        self.assertEqual(after_locked_edit["round"]["matches"][0]["pick"], [1, 0])

    def test_player_payment_summary_counts_round_contributions(self):
        _, admin_state = self.request_json("/api/admin", cookie=self.admin_cookie)
        active_round = next(round_item for round_item in admin_state["rounds"] if round_item["status"] == "active")
        player = next(
            item for item in admin_state["members"]
            if item["email"] == "torcedor@futscores.com"
        )
        _, unpaid_state = self.request_json("/api/state", cookie=self.player_cookie)
        self.assertEqual(unpaid_state["round"]["userPaidCents"], 0)
        self.assertEqual(unpaid_state["round"]["totalCollectedCents"], 0)

        _, second_user = self.request_json(
            "/api/register",
            "POST",
            {
                "name": "Contribuinte",
                "email": "contribuinte@example.com",
                "password": "senhaSegura123",
                "team": "Santos",
            },
        )
        for user_id in (player["id"], second_user["user"]["id"]):
            status, _ = self.request_json(
                f"/api/admin/payments/{active_round['id']}/{user_id}",
                "PUT",
                {"paid": True},
                self.admin_cookie,
            )
            self.assertEqual(status, 200)

        _, paid_state = self.request_json("/api/state", cookie=self.player_cookie)
        self.assertTrue(paid_state["round"]["paymentPaid"])
        self.assertEqual(
            paid_state["round"]["userPaidCents"],
            active_round["prizeCents"],
        )
        self.assertEqual(paid_state["round"]["paidCount"], 2)
        self.assertEqual(
            paid_state["round"]["totalCollectedCents"],
            active_round["prizeCents"] * 2,
        )

    def test_unpaid_picks_are_excluded_and_payment_closes_at_first_kickoff(self):
        status, created_round = self.request_json(
            "/api/admin/rounds",
            "POST",
            {"name": "Prazo de pagamento", "dateRange": "Teste", "prizeCents": 600},
            self.admin_cookie,
        )
        self.assertEqual(status, 201)
        round_id = created_round["id"]
        kickoff = datetime.now(timezone.utc) + timedelta(days=1)
        self.assertTrue(
            app.payment_is_eligible(
                True,
                (kickoff - timedelta(microseconds=1)).isoformat(),
                kickoff.isoformat(),
            )
        )
        self.assertFalse(
            app.payment_is_eligible(
                True,
                kickoff.isoformat(),
                kickoff.isoformat(),
            )
        )
        status, created_match = self.request_json(
            f"/api/admin/rounds/{round_id}/matches",
            "POST",
            {
                "home": "Palmeiras",
                "away": "Santos",
                "startsAt": kickoff.isoformat(),
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 201)
        match_id = created_match["id"]

        registered = []
        for name, email in (
            ("Participante pago", "pagamento-em-dia@example.com"),
            ("Participante pendente", "pagamento-pendente@example.com"),
        ):
            status, result = self.request_json(
                "/api/register",
                "POST",
                {
                    "name": name,
                    "email": email,
                    "password": "senhaSegura123",
                    "team": "Santos",
                },
            )
            self.assertEqual(status, 200)
            registered.append(
                (result["user"]["id"], self.login(email, "senhaSegura123"))
            )

        for cookie, prediction in zip((item[1] for item in registered), ((1, 0), (0, 0))):
            status, _ = self.request_json(
                "/api/picks",
                "PUT",
                {
                    "picks": [
                        {
                            "matchId": match_id,
                            "home": prediction[0],
                            "away": prediction[1],
                        }
                    ]
                },
                cookie,
            )
            self.assertEqual(status, 200)

        paid_user_id, paid_cookie = registered[0]
        unpaid_user_id, _ = registered[1]
        status, _ = self.request_json(
            f"/api/admin/payments/{round_id}/{paid_user_id}",
            "PUT",
            {"paid": True},
            self.admin_cookie,
        )
        self.assertEqual(status, 200)

        _, admin_state = self.request_json("/api/admin", cookie=self.admin_cookie)
        saved_round = next(item for item in admin_state["rounds"] if item["id"] == round_id)
        unpaid_member = next(
            item for item in saved_round["participants"] if item["id"] == unpaid_user_id
        )
        self.assertTrue(unpaid_member["hasPicks"])
        self.assertEqual(unpaid_member["pickCount"], 1)
        self.assertFalse(unpaid_member["paid"])
        self.assertTrue(saved_round["paymentOpen"])

        started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        status, _ = self.request_json(
            f"/api/admin/matches/{match_id}",
            "PUT",
            {
                "home": "Palmeiras",
                "away": "Santos",
                "startsAt": started_at.isoformat(),
                "homeResult": 1,
                "awayResult": 0,
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        with app.connect_db() as db:
            db.execute(
                "UPDATE payments SET paid_at = ? WHERE round_id = ? AND user_id = ?",
                (
                    (started_at - timedelta(minutes=1)).isoformat(),
                    round_id,
                    paid_user_id,
                ),
            )

        _, player_state = self.request_json("/api/state", cookie=paid_cookie)
        public_unpaid = next(
            item for item in player_state["round"]["participants"]
            if item["id"] == unpaid_user_id
        )
        self.assertTrue(public_unpaid["hasPicks"])
        self.assertFalse(public_unpaid["paid"])
        self.assertEqual(player_state["round"]["matches"][0]["otherPicks"], [])

        status, error = self.request_json(
            f"/api/admin/payments/{round_id}/{unpaid_user_id}",
            "PUT",
            {"paid": True},
            self.admin_cookie,
        )
        self.assertEqual(status, 409)
        self.assertIn("prazo", error["error"])
        _, admin_after_deadline = self.request_json("/api/admin", cookie=self.admin_cookie)
        closed_round = next(
            item for item in admin_after_deadline["rounds"] if item["id"] == round_id
        )
        self.assertFalse(closed_round["paymentOpen"])

        status, _ = self.request_json(
            f"/api/admin/rounds/{round_id}",
            "PUT",
            {
                "name": "Prazo de pagamento",
                "dateRange": "Teste",
                "prizeCents": 600,
                "status": "finished",
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        _, finished_state = self.request_json("/api/state", cookie=paid_cookie)
        self.assertIn(paid_user_id, [entry["id"] for entry in finished_state["standings"]])
        self.assertNotIn(unpaid_user_id, [entry["id"] for entry in finished_state["standings"]])
        self.assertEqual(
            [winner["id"] for winner in finished_state["finishedRound"]["winners"]],
            [paid_user_id],
        )
        self.assertEqual(finished_state["finishedRound"]["poolCents"], 600)

    def test_finished_round_announces_tied_champions_and_compares_picks(self):
        status, created_round = self.request_json(
            "/api/admin/rounds",
            "POST",
            {"name": "Final da rodada", "dateRange": "16/10", "prizeCents": 501},
            self.admin_cookie,
        )
        self.assertEqual(status, 201)
        round_id = created_round["id"]
        kickoff = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        matches = []
        for home, away in (("Palmeiras", "Santos"), ("Flamengo", "Ceará")):
            status, created_match = self.request_json(
                f"/api/admin/rounds/{round_id}/matches",
                "POST",
                {"home": home, "away": away, "startsAt": kickoff},
                self.admin_cookie,
            )
            self.assertEqual(status, 201)
            matches.append(created_match["id"])

        status, _ = self.request_json(
            "/api/picks",
            "PUT",
            {"picks": [{"matchId": matches[0], "home": 1, "away": 0}]},
            self.player_cookie,
        )
        self.assertEqual(status, 200)
        _, partial_pick_state = self.request_json(
            "/api/state", cookie=self.player_cookie
        )
        self.assertEqual(
            next(
                match["pick"]
                for match in partial_pick_state["round"]["matches"]
                if match["id"] == matches[0]
            ),
            [1, 0],
        )
        self.assertIsNone(
            next(
                match["pick"]
                for match in partial_pick_state["round"]["matches"]
                if match["id"] == matches[1]
            )
        )

        registered = []
        for name, email in (
            ("Campeã Alice", "alice-campea@example.com"),
            ("Campeão Bruno", "bruno-campeao@example.com"),
        ):
            status, result = self.request_json(
                "/api/register",
                "POST",
                {
                    "name": name,
                    "email": email,
                    "password": "senhaSegura123",
                    "team": "Santos",
                },
            )
            self.assertEqual(status, 200)
            registered.append(
                (result["user"]["id"], self.login(email, "senhaSegura123"))
            )

        picks_by_user = [
            (self.player_cookie, [(2, 0), (0, 1)]),
            (registered[0][1], [(2, 1), (0, 1)]),
            (registered[1][1], [(2, 1), (2, 2)]),
        ]
        for cookie, scores in picks_by_user:
            status, _ = self.request_json(
                "/api/picks",
                "PUT",
                {
                    "picks": [
                        {"matchId": match_id, "home": score[0], "away": score[1]}
                        for match_id, score in zip(matches, scores)
                    ]
                },
                cookie,
            )
            self.assertEqual(status, 200)

        for match_id, home_result, away_result in (
            (matches[0], 2, 1),
            (matches[1], None, None),
        ):
            status, _ = self.request_json(
                f"/api/admin/matches/{match_id}",
                "PUT",
                {
                    "home": "Palmeiras" if match_id == matches[0] else "Flamengo",
                    "away": "Santos" if match_id == matches[0] else "Ceará",
                    "startsAt": kickoff,
                    "homeResult": home_result,
                    "awayResult": away_result,
                },
                self.admin_cookie,
            )
            self.assertEqual(status, 200)

        player_id = self.request_json("/api/state", cookie=self.player_cookie)[1]["user"]["id"]
        for user_id in (player_id, *(user_id for user_id, _ in registered)):
            status, _ = self.request_json(
                f"/api/admin/payments/{round_id}/{user_id}",
                "PUT",
                {"paid": True},
                self.admin_cookie,
            )
            self.assertEqual(status, 200)

        _, admin_state = self.request_json("/api/admin", cookie=self.admin_cookie)
        round_data = next(item for item in admin_state["rounds"] if item["id"] == round_id)
        status, _ = self.request_json(
            f"/api/admin/rounds/{round_id}",
            "PUT",
            {
                "name": round_data["name"],
                "dateRange": round_data["dateRange"],
                "prizeCents": round_data["prizeCents"],
                "status": "finished",
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        _, incomplete_state = self.request_json("/api/state", cookie=self.player_cookie)
        self.assertIsNone(incomplete_state["finishedRound"])
        status, _ = self.request_json(
            f"/api/admin/payouts/{round_id}/{registered[0][0]}",
            "PUT",
            {"paid": True},
            self.admin_cookie,
        )
        self.assertEqual(status, 409)

        status, _ = self.request_json(
            f"/api/admin/matches/{matches[1]}",
            "PUT",
            {
                "home": "Flamengo",
                "away": "Ceará",
                "startsAt": kickoff,
                "homeResult": 1,
                "awayResult": 0,
            },
            self.admin_cookie,
        )
        self.assertEqual(status, 200)

        _, player_state = self.request_json("/api/state", cookie=self.player_cookie)
        final_round = player_state["finishedRound"]
        self.assertFalse(final_round["isWinner"])
        self.assertEqual(final_round["userPoints"], 4)
        self.assertEqual(final_round["userExact"], 0)
        self.assertEqual(final_round["poolCents"], 1503)
        self.assertEqual(
            [winner["name"] for winner in final_round["winners"]],
            ["Campeã Alice", "Campeão Bruno"],
        )
        self.assertEqual(
            [winner["payoutCents"] for winner in final_round["winners"]],
            [752, 751],
        )
        self.assertIsNone(final_round["userVerificationCode"])
        _, admin_state = self.request_json("/api/admin", cookie=self.admin_cookie)
        admin_round = next(
            item for item in admin_state["rounds"] if item["id"] == round_id
        )
        self.assertEqual(
            [item["name"] for item in admin_round["championCodes"]],
            ["Campeã Alice", "Campeão Bruno"],
        )
        self.assertTrue(
            all(
                re.fullmatch(r"(?:[0-9A-F]{4}-){2}[0-9A-F]{4}", item["code"])
                for item in admin_round["championCodes"]
            )
        )
        self.assertEqual(final_round["matches"][0]["homeResult"], 2)
        self.assertEqual(final_round["matches"][0]["winnerPicks"][0]["pick"], [2, 1])
        self.assertTrue(final_round["matches"][0]["winnerPicks"][0]["exact"])
        self.assertEqual(final_round["matches"][1]["userPick"], [0, 1])

        for (user_id, cookie), expected_payout in zip(registered, (752, 751)):
            _, winner_state = self.request_json("/api/state", cookie=cookie)
            winner_summary = winner_state["finishedRound"]
            self.assertTrue(winner_summary["isWinner"])
            winner_code = winner_summary["userVerificationCode"]
            self.assertRegex(winner_code, r"^(?:[0-9A-F]{4}-){2}[0-9A-F]{4}$")
            admin_code = next(
                item["code"] for item in admin_round["championCodes"]
                if item["userId"] == user_id
            )
            self.assertEqual(winner_code, admin_code)
            self.assertEqual(winner_summary["userPayoutCents"], expected_payout)
            self.assertEqual(winner_summary["userExact"], 1)
            self.assertEqual(winner_summary["matches"][0]["userPoints"], 10)
            self.assertEqual(winner_summary["matches"][1]["userPoints"], 0)

        status, error = self.request_json(
            f"/api/admin/payouts/{round_id}/{player_id}",
            "PUT",
            {"paid": True},
            self.admin_cookie,
        )
        self.assertEqual(status, 409)
        self.assertIn("campeão", error["error"])

        winner_id, _ = registered[0]
        status, _ = self.request_json(
            f"/api/admin/payouts/{round_id}/{winner_id}",
            "PUT",
            {"paid": True},
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        _, updated_admin_state = self.request_json("/api/admin", cookie=self.admin_cookie)
        updated_admin_round = next(
            item for item in updated_admin_state["rounds"] if item["id"] == round_id
        )
        self.assertEqual(updated_admin_round["paidOutCents"], 752)
        self.assertEqual(updated_admin_state["totalPaidOutCents"], 752)
        paid_champion = next(
            item for item in updated_admin_round["payoutWinners"]
            if item["userId"] == winner_id
        )
        self.assertEqual(paid_champion["paidCents"], 752)
        self.assertIsNotNone(paid_champion["paidAt"])

        _, public_history = self.request_json("/api/state", cookie=self.player_cookie)
        public_round = next(
            item for item in public_history["history"] if item["id"] == round_id
        )
        self.assertEqual(public_round["paidOutCents"], 752)
        self.assertEqual(
            public_round["payouts"],
            [{"name": "Campeã Alice", "amountCents": 752}],
        )
        self.assertEqual(public_history["summary"]["totalPayoutCents"], 752)

        status, _ = self.request_json(
            f"/api/admin/payouts/{round_id}/{winner_id}",
            "PUT",
            {"paid": False},
            self.admin_cookie,
        )
        self.assertEqual(status, 200)
        _, unpaid_admin_state = self.request_json("/api/admin", cookie=self.admin_cookie)
        unpaid_round = next(
            item for item in unpaid_admin_state["rounds"] if item["id"] == round_id
        )
        self.assertEqual(unpaid_round["paidOutCents"], 0)
        self.assertEqual(unpaid_admin_state["totalPaidOutCents"], 0)

        status, next_round = self.request_json(
            "/api/admin/rounds",
            "POST",
            {"name": "Próxima rodada", "dateRange": "17/10", "prizeCents": 500},
            self.admin_cookie,
        )
        self.assertEqual(status, 201)
        _, state_after_new_round = self.request_json(
            "/api/state", cookie=self.player_cookie
        )
        self.assertEqual(state_after_new_round["round"]["id"], next_round["id"])
        self.assertFalse(state_after_new_round["round"]["paymentPaid"])
        self.assertIsNone(state_after_new_round["finishedRound"])

    def test_admin_can_delete_round_and_cascade_its_matches_and_picks(self):
        _, round_data = self.request_json(
            "/api/admin/rounds",
            "POST",
            {"name": "Rodada para excluir", "dateRange": "Teste", "prizeCents": 500},
            self.admin_cookie,
        )
        _, match_data = self.request_json(
            f"/api/admin/rounds/{round_data['id']}/matches",
            "POST",
            {
                "home": "Palmeiras",
                "away": "Santos",
                "startsAt": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(),
            },
            self.admin_cookie,
        )
        _, _ = self.request_json(
            "/api/picks",
            "PUT",
            {"picks": [{"matchId": match_data["id"], "home": 1, "away": 0}]},
            self.player_cookie,
        )
        status, _ = self.request_json(
            f"/api/admin/rounds/{round_data['id']}",
            "DELETE",
            cookie=self.admin_cookie,
        )
        self.assertEqual(status, 200)
        with app.connect_db() as db:
            self.assertIsNone(db.execute("SELECT id FROM matches WHERE id = ?", (match_data["id"],)).fetchone())
            self.assertIsNone(db.execute("SELECT match_id FROM picks WHERE match_id = ?", (match_data["id"],)).fetchone())
        self.assertTrue(self.request_json("/api/state", cookie=self.player_cookie)[1]["round"]["id"])
        for round_item in self.request_json("/api/admin", cookie=self.admin_cookie)[1]["rounds"]:
            status, _ = self.request_json(
                f"/api/admin/rounds/{round_item['id']}",
                "DELETE",
                cookie=self.admin_cookie,
            )
            self.assertEqual(status, 200)
        _, empty_state = self.request_json("/api/state", cookie=self.player_cookie)
        self.assertIsNone(empty_state["round"]["id"])
        self.assertEqual(empty_state["round"]["matches"], [])
        app.init_database()
        _, after_restart = self.request_json("/api/admin", cookie=self.admin_cookie)
        self.assertEqual(after_restart["rounds"], [])


if __name__ == "__main__":
    unittest.main()
