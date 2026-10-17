"""
Testy operacji w bazie danych, które pokrywają:
  - poprawność operacji CRUD i kaskad,
  - integralność wymuszaną w bazie (triggery),
  - poprawność operacji transakcyjnych (faza grupowa -> drabinki),
  - KONTROLĘ RÓWNOCZESNEGO DOSTĘPU (transfer jako "limitowany zasób"),
  - poprawność operacji raportujących (agregacje).

Każdy test działa na osobnej, tymczasowej bazie (nie rusza tournament.db).

Uruchom:  python -m unittest discover -s tests
"""
import contextlib
import io
import pathlib
import shutil
import tempfile
import threading
import unittest

import db.init as dbinit
from db.init import get_connection
from app.dao import tournament_dao, team_dao, player_dao
from app.services import draw, schedule, match_result, transfer
from app.reports import reports


class DBTestCase(unittest.TestCase):
    """Baza testowa: świeży, tymczasowy plik bazy na każdy test."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig_path = dbinit.DB_PATH
        dbinit.DB_PATH = pathlib.Path(self._tmpdir) / "test.db"
        with contextlib.redirect_stdout(io.StringIO()):  # wycisz "Baza zainicjalizowana"
            dbinit.init_db()

    def tearDown(self):
        dbinit.DB_PATH = self._orig_path
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    # ---- pomocnicze ----
    def _make_tournament(self, name="Test", n_teams=12, players_per_team=6):
        tid = tournament_dao.create_tournament(name)
        teams = []
        for i in range(n_teams):
            team_id = team_dao.add_team(tid, f"Team {i}")
            teams.append(team_id)
            for j in range(players_per_team):
                player_dao.add_player(team_id, f"T{i} Player {j}")
        return tid, teams

    def _first_player(self, team_id):
        with get_connection() as c:
            return c.execute(
                "SELECT id FROM player WHERE team_id = ? LIMIT 1", (team_id,)
            ).fetchone()["id"]

    def _play_all_group_matches(self, tid):
        """Każdy mecz grupowy: 1:0 dla gospodarzy (1 strzelec z gospodarzy)."""
        for fx in schedule.get_schedule(tid):
            if fx["stage"] != "GROUP":
                continue
            scorer = self._first_player(fx["home_team_id"])
            match_result.save_match_result(fx["match_id"], 1, 0, [scorer])


class TestCrudAndCascade(DBTestCase):
    def test_create_and_cascade_delete(self):
        tid, teams = self._make_tournament(n_teams=2, players_per_team=3)
        self.assertEqual(team_dao.count_teams(tid), 2)
        self.assertEqual(player_dao.count_players(teams[0]), 3)

        # usunięcie turnieju kasuje kaskadowo drużyny i zawodników
        tournament_dao.delete_tournament(tid)
        self.assertIsNone(tournament_dao.get_tournament(tid))
        with get_connection() as c:
            teams_left = c.execute(
                "SELECT COUNT(*) AS n FROM team WHERE tournament_id = ?", (tid,)
            ).fetchone()["n"]
            players_left = c.execute(
                "SELECT COUNT(*) AS n FROM player WHERE team_id = ?", (teams[0],)
            ).fetchone()["n"]
        self.assertEqual(teams_left, 0)
        self.assertEqual(players_left, 0)


class TestIntegrityTriggers(DBTestCase):
    def test_squad_limit_max_10(self):
        tid = tournament_dao.create_tournament("Cup")
        team_id = team_dao.add_team(tid, "Drużyna")
        for i in range(10):
            player_dao.add_player(team_id, f"Zawodnik {i}")
        # 11. zawodnik — trigger trg_player_squad_limit musi zablokować
        with self.assertRaises(Exception):
            player_dao.add_player(team_id, "Zawodnik 11")

    def test_transfer_blocked_after_knockout(self):
        tid, teams = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        self._play_all_group_matches(tid)
        self.assertEqual(tournament_dao.get_state(tid), "KO")

        # transfer w fazie pucharowej — trigger trg_transfer_window musi zablokować
        player_id = self._first_player(teams[0])
        with self.assertRaises(Exception):
            transfer.transfer_player(player_id, teams[1])


class TestTransactionalFlow(DBTestCase):
    def test_group_phase_seeds_knockout(self):
        tid, _ = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)

        fixtures = [f for f in schedule.get_schedule(tid) if f["stage"] == "GROUP"]
        self.assertEqual(len(fixtures), 30, "round-robin 2x6 drużyn = 30 meczów")

        self._play_all_group_matches(tid)

        # po ostatnim wyniku: stan KO i 12 meczów pucharowych (3 drabinki x 4)
        self.assertEqual(tournament_dao.get_state(tid), "KO")
        with get_connection() as c:
            ko = c.execute(
                "SELECT COUNT(*) AS n FROM match WHERE tournament_id = ? AND stage != 'GROUP'",
                (tid,)
            ).fetchone()["n"]
        self.assertEqual(ko, 12)


class TestConcurrency(DBTestCase):
    def test_two_users_compete_for_last_squad_slot(self):
        """Flagowy test: dwóch użytkowników jednocześnie transferuje zawodnika
        do drużyny, w której został JEDEN wolny slot (limit składu = 10).
        Dokładnie jeden transfer może się udać."""
        tid = tournament_dao.create_tournament("Concurrency")
        target = team_dao.add_team(tid, "Docelowa")
        src_a = team_dao.add_team(tid, "Źródło A")
        src_b = team_dao.add_team(tid, "Źródło B")

        # drużyna docelowa: 9 zawodników -> 1 wolny slot
        for i in range(9):
            player_dao.add_player(target, f"D {i}")
        # źródła: po 6 (mogą oddać jednego, zostają z 5 = minimum)
        for i in range(6):
            player_dao.add_player(src_a, f"A {i}")
            player_dao.add_player(src_b, f"B {i}")

        player_a = self._first_player(src_a)
        player_b = self._first_player(src_b)

        results = {}

        def worker(name, player_id):
            try:
                transfer.transfer_player(player_id, target)
                results[name] = "ok"
            except Exception as e:
                results[name] = ("err", str(e))

        t1 = threading.Thread(target=worker, args=("A", player_a))
        t2 = threading.Thread(target=worker, args=("B", player_b))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # dokładnie jeden się udał, jeden odrzucony
        ok = [k for k, v in results.items() if v == "ok"]
        self.assertEqual(len(ok), 1, f"Powinien wygrać dokładnie jeden: {results}")
        # drużyna docelowa ma dokładnie 10 (slot zajęty raz)
        self.assertEqual(player_dao.count_players(target), 10)
        # zalogowano dokładnie jeden transfer
        self.assertEqual(len(reports.transfer_history(tid)), 1)


class TestReports(DBTestCase):
    def test_group_table_and_top_scorers(self):
        tid, _ = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        self._play_all_group_matches(tid)

        table_a = reports.group_table(tid, "A")
        self.assertEqual(len(table_a), 6, "Tabela grupy zawiera wszystkie 6 drużyn")
        # suma rozegranych meczów w grupie = 6 drużyn * 5 kolejek = 30 (liczone dwustronnie)
        self.assertEqual(sum(r["played"] for r in table_a), 30)

        scorers = reports.top_scorers(tid)
        self.assertTrue(len(scorers) > 0)
        # każdy mecz grupowy dał 1 gola -> 30 goli łącznie w klasyfikacji
        self.assertEqual(sum(s["goals"] for s in scorers), 30)


if __name__ == "__main__":
    unittest.main()


class TestDemoTournament(DBTestCase):
    def test_demo_tournament_is_mid_group_stage(self):
        from app.services import demo
        tid = demo.create_demo_tournament(seed=1)

        self.assertEqual(tournament_dao.get_state(tid), "GROUP")
        self.assertEqual(team_dao.count_teams(tid), 12)
        fixtures = [f for f in schedule.get_schedule(tid) if f["stage"] == "GROUP"]
        played = [f for f in fixtures if f["played"]]
        self.assertEqual(len(fixtures), 30)
        self.assertEqual(len(played), 18, "3 kolejki x 6 meczów")

        # liczba bramek w bazie zgadza się z wynikami
        with get_connection() as c:
            goals = c.execute(
                "SELECT COUNT(*) AS n FROM goal g JOIN match m ON m.id = g.match_id "
                "WHERE m.tournament_id = ?", (tid,)
            ).fetchone()["n"]
        self.assertEqual(goals, sum(f["home_score"] + f["away_score"] for f in played))

    def test_demo_names_do_not_clash(self):
        from app.services import demo
        t1 = demo.create_demo_tournament(seed=1)
        t2 = demo.create_demo_tournament(seed=2)
        self.assertNotEqual(tournament_dao.get_tournament(t1)["name"],
                            tournament_dao.get_tournament(t2)["name"])

    def test_demo_can_be_played_to_the_end(self):
        """Demo z rozegraną całą grupą przechodzi w fazę KO jak zwykły turniej."""
        from app.services import demo
        tid = demo.create_demo_tournament(rounds_played=5, seed=3)
        self.assertEqual(tournament_dao.get_state(tid), "KO")


class TestReset(DBTestCase):
    def test_reset_returns_to_setup_and_keeps_squads(self):
        from app.services import reset
        tid, teams = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        transfer.transfer_player(self._first_player(teams[0]), teams[1])
        self._play_all_group_matches(tid)          # -> faza KO
        squads_before = {t: player_dao.count_players(t) for t in teams}

        reset.reset_to_setup(tid)

        self.assertEqual(tournament_dao.get_state(tid), "SETUP")
        with get_connection() as c:
            for table in ("match", "transfer"):
                n = c.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE tournament_id = ?",
                              (tid,)).fetchone()["n"]
                self.assertEqual(n, 0, table)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM goal").fetchone()["n"], 0)
        self.assertTrue(all(t["group_name"] is None for t in team_dao.list_teams(tid)))
        # składy (łącznie z transferem) bez zmian
        self.assertEqual({t: player_dao.count_players(t) for t in teams}, squads_before)

        # turniej da się rozegrać od nowa
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        self._play_all_group_matches(tid)
        self.assertEqual(tournament_dao.get_state(tid), "KO")

    def test_reset_in_setup_is_rejected(self):
        from app.services import reset
        tid, _ = self._make_tournament()
        with self.assertRaises(ValueError):
            reset.reset_to_setup(tid)