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
        match_result.confirm_group_stage(tid)


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
        """Demo z rozegraną całą grupą da się zatwierdzić jak zwykły turniej."""
        from app.services import demo
        tid = demo.create_demo_tournament(rounds_played=5, seed=3)
        self.assertEqual(tournament_dao.get_state(tid), "GROUP")
        match_result.confirm_group_stage(tid)
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


class TestConfirmGroupStage(DBTestCase):
    def _all_group_results(self, tid):
        """Wpisuje wszystkie wyniki grupowe (1:0), BEZ zatwierdzania."""
        for fx in schedule.get_schedule(tid):
            if fx["stage"] == "GROUP":
                scorer = self._first_player(fx["home_team_id"])
                match_result.save_match_result(fx["match_id"], 1, 0, [scorer])

    def _setup(self):
        tid, _ = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        return tid

    def test_last_result_does_not_start_knockout(self):
        tid = self._setup()
        self._all_group_results(tid)
        self.assertEqual(tournament_dao.get_state(tid), "GROUP")
        self.assertEqual(match_result.group_stage_status(tid), (30, 30))

    def test_results_editable_until_confirmed(self):
        tid = self._setup()
        self._all_group_results(tid)
        fx = next(f for f in schedule.get_schedule(tid) if f["stage"] == "GROUP")
        away = self._first_player(fx["away_team_id"])

        # przed zatwierdzeniem: poprawka ostatniego wyniku jest możliwa
        match_result.edit_match_result(fx["match_id"], 0, 1, [away])

        match_result.confirm_group_stage(tid)
        self.assertEqual(tournament_dao.get_state(tid), "KO")
        editable, _ = match_result.can_edit_match(fx["match_id"])
        self.assertFalse(editable)
        home = self._first_player(fx["home_team_id"])
        with self.assertRaisesRegex(ValueError, "zatwierdzona"):
            match_result.edit_match_result(fx["match_id"], 1, 0, [home])

    def test_confirm_requires_all_results(self):
        tid = self._setup()
        fx = next(f for f in schedule.get_schedule(tid) if f["stage"] == "GROUP")
        match_result.save_match_result(fx["match_id"], 0, 0, [])
        with self.assertRaises(ValueError):
            match_result.confirm_group_stage(tid)
        self.assertEqual(tournament_dao.get_state(tid), "GROUP")

    def test_confirm_twice_is_rejected(self):
        tid = self._setup()
        self._all_group_results(tid)
        match_result.confirm_group_stage(tid)
        with self.assertRaises(ValueError):
            match_result.confirm_group_stage(tid)


class TestExportImport(DBTestCase):
    def _snapshot(self, tid):
        """Wszystko, co widzi użytkownik — do porównania przed i po imporcie."""
        return {
            "state": tournament_dao.get_state(tid),
            "groups": {g: reports.group_table(tid, g) for g in ("A", "B")},
            "scorers": reports.top_scorers(tid, limit=200),
            "transfers": [(r["player_name"], r["from_team_name"], r["to_team_name"])
                          for r in reports.transfer_history(tid)],
            "matches": [(f["stage"], f["group_name"], f["round"], f["home_team_name"],
                         f["away_team_name"], f["home_score"], f["away_score"],
                         f["winner_pen"], f["played"])
                        for f in schedule.get_schedule(tid)],
        }

    def test_round_trip_with_transfer_after_goal(self):
        """Zawodnik strzela gola, potem przechodzi do innej drużyny.
        Po eksporcie i imporcie turniej musi wyglądać identycznie."""
        from app.services import backup
        tid, teams = self._make_tournament(name="Liga")
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        fixtures = [f for f in schedule.get_schedule(tid) if f["stage"] == "GROUP"]

        first = fixtures[0]
        scorer = self._first_player(first["home_team_id"])
        match_result.save_match_result(first["match_id"], 1, 0, [scorer])
        other_team = next(t for t in teams
                          if t not in (first["home_team_id"], first["away_team_id"]))
        transfer.transfer_player(scorer, other_team)       # gol strzelony dla starej drużyny

        for fx in fixtures[1:]:
            match_result.save_match_result(
                fx["match_id"], 1, 0, [self._first_player(fx["home_team_id"])])
        match_result.confirm_group_stage(tid)
        ko = next(f for f in schedule.get_schedule(tid) if f["stage"] == "SF_TOP")
        match_result.save_match_result(ko["match_id"], 0, 0, [], winner_pen=1)  # karne

        before = self._snapshot(tid)
        path = pathlib.Path(self._tmpdir) / "liga.json"
        backup.export_to_file(tid, path)
        new_tid = backup.import_from_file(path)

        self.assertNotEqual(new_tid, tid)
        self.assertEqual(tournament_dao.get_tournament(new_tid)["name"], "Liga (import)")
        self.assertEqual(self._snapshot(new_tid), before)

        # trigger walidujący gole działa dalej po imporcie
        with get_connection() as c:
            n = c.execute("SELECT COUNT(*) AS n FROM sqlite_master "
                          "WHERE type = 'trigger' AND name = 'trg_goal_scorer_valid'"
                          ).fetchone()["n"]
        self.assertEqual(n, 1)

    def test_imported_tournament_can_be_continued(self):
        from app.services import backup, demo
        tid = demo.create_demo_tournament(seed=5)
        new_tid = backup.import_tournament(backup.export_tournament(tid))
        for fx in schedule.get_schedule(new_tid):
            if fx["stage"] == "GROUP" and not fx["played"]:
                match_result.save_match_result(fx["match_id"], 0, 0, [])
        match_result.confirm_group_stage(new_tid)
        self.assertEqual(tournament_dao.get_state(new_tid), "KO")

    def test_repeated_import_gets_unique_names(self):
        from app.services import backup
        tid, _ = self._make_tournament(name="Cup", n_teams=2, players_per_team=1)
        data = backup.export_tournament(tid)
        names = {tournament_dao.get_tournament(backup.import_tournament(data))["name"]
                 for _ in range(3)}
        self.assertEqual(names, {"Cup (import)", "Cup (import 2)", "Cup (import 3)"})

    def test_invalid_files_are_rejected_without_side_effects(self):
        from app.services import backup
        tid = self._make_tournament(name="Cup")[0]
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        self._play_all_group_matches(tid)
        good = backup.export_tournament(tid)
        count_before = len(tournament_dao.list_tournaments())

        import copy
        bad_cases = []
        b = copy.deepcopy(good); b["format"] = "cos-innego"; bad_cases.append(b)
        b = copy.deepcopy(good); b["version"] = 99; bad_cases.append(b)
        b = copy.deepcopy(good); del b["teams"]; bad_cases.append(b)
        b = copy.deepcopy(good); b["goals"].pop(); bad_cases.append(b)       # zły wynik
        b = copy.deepcopy(good); b["players"][0]["team_id"] = 999999; bad_cases.append(b)
        for bad in bad_cases:
            with self.assertRaises(ValueError):
                backup.import_tournament(bad)

        broken = pathlib.Path(self._tmpdir) / "broken.json"
        broken.write_text("{ to nie json", encoding="utf-8")
        with self.assertRaises(ValueError):
            backup.import_from_file(broken)

        self.assertEqual(len(tournament_dao.list_tournaments()), count_before)


class TestRenameTournament(DBTestCase):
    def test_rename_keeps_all_data(self):
        tid, teams = self._make_tournament(name="Stara nazwa")
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        self._play_all_group_matches(tid)
        before = (reports.group_table(tid, "A"), reports.top_scorers(tid))

        tournament_dao.rename_tournament(tid, "  Nowa nazwa  ")

        self.assertEqual(tournament_dao.get_tournament(tid)["name"], "Nowa nazwa")
        self.assertEqual((reports.group_table(tid, "A"), reports.top_scorers(tid)), before)
        self.assertEqual(tournament_dao.get_state(tid), "KO")

    def test_empty_name_rejected(self):
        tid = tournament_dao.create_tournament("Cup")
        with self.assertRaises(ValueError):
            tournament_dao.rename_tournament(tid, "   ")
        self.assertEqual(tournament_dao.get_tournament(tid)["name"], "Cup")

    def test_name_taken(self):
        a = tournament_dao.create_tournament("Liga")
        b = tournament_dao.create_tournament("Puchar")
        self.assertTrue(tournament_dao.name_taken("liga"))            # wielkość liter bez znaczenia
        self.assertFalse(tournament_dao.name_taken("Liga", exclude_id=a))  # własna nazwa się nie liczy
        self.assertTrue(tournament_dao.name_taken("Liga", exclude_id=b))
        self.assertFalse(tournament_dao.name_taken("Turniej"))
        tournament_dao.create_tournament("Puchar Łodzi")
        self.assertTrue(tournament_dao.name_taken("PUCHAR ŁODZI"))

class TestMatchDetails(DBTestCase):
    def test_scorers_split_by_side_with_counts(self):
        tid, teams = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        fx = next(f for f in schedule.get_schedule(tid) if f["stage"] == "GROUP")
        home_players = [p["id"] for p in player_dao.list_players(fx["home_team_id"])]
        away_players = [p["id"] for p in player_dao.list_players(fx["away_team_id"])]
        match_result.save_match_result(
            fx["match_id"], 3, 1, [home_players[0], home_players[1], home_players[0], away_players[0]])

        d = match_result.get_match_details(fx["match_id"])
        self.assertEqual((d["home_score"], d["away_score"]), (3, 1))
        self.assertEqual([s["goals"] for s in d["home_scorers"]], [2, 1])   # najpierw dublet
        self.assertEqual(len(d["away_scorers"]), 1)
        self.assertEqual(d["home_team_name"], fx["home_team_name"])

    def test_scorer_stays_on_original_side_after_transfer(self):
        tid, teams = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        fx = next(f for f in schedule.get_schedule(tid) if f["stage"] == "GROUP")
        scorer = self._first_player(fx["home_team_id"])
        match_result.save_match_result(fx["match_id"], 1, 0, [scorer])
        elsewhere = next(t for t in teams if t not in (fx["home_team_id"], fx["away_team_id"]))
        transfer.transfer_player(scorer, elsewhere)

        d = match_result.get_match_details(fx["match_id"])
        self.assertEqual(len(d["home_scorers"]), 1)
        self.assertEqual(d["away_scorers"], [])

    def test_unplayed_and_missing(self):
        tid, _ = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        fx = next(f for f in schedule.get_schedule(tid) if f["stage"] == "GROUP")
        d = match_result.get_match_details(fx["match_id"])
        self.assertFalse(d["played"])
        self.assertEqual((d["home_scorers"], d["away_scorers"]), ([], []))
        self.assertIsNone(match_result.get_match_details(999999))

class TestPenaltyShootout(DBTestCase):
    def _ko_match(self):
        """Turniej po fazie grupowej; zwraca (tid, półfinał SF_TOP, gracze gosp., gracze gości)."""
        tid, _ = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        self._play_all_group_matches(tid)
        ko = next(f for f in schedule.get_schedule(tid) if f["stage"] == "SF_TOP")
        home = [p["id"] for p in player_dao.list_players(ko["home_team_id"])]
        away = [p["id"] for p in player_dao.list_players(ko["away_team_id"])]
        return tid, ko, home, away

    def test_shootout_not_counted_as_goals_and_decides_winner(self):
        tid, ko, home, away = self._ko_match()
        scorers_before = reports.top_scorers(tid, limit=200)
        # 1:1 i karne 1:2 dla gości (winner_pen wynika z serii)
        shootout = [(home[0], True), (away[0], True), (home[1], False),
                    (away[1], True), (home[2], False), (away[2], False)]
        match_result.save_match_result(ko["match_id"], 1, 1, [home[0], away[0]],
                                       shootout=shootout)

        self.assertEqual(match_result.get_match(ko["match_id"])["winner_pen"], 1)
        fx = next(f for f in schedule.get_schedule(tid) if f["match_id"] == ko["match_id"])
        self.assertEqual((fx["home_pens"], fx["away_pens"]), (1, 2))
        # w klasyfikacji strzelców doszły tylko 2 bramki z gry, nie karne
        total = lambda rows: sum(r["goals"] for r in rows)
        self.assertEqual(total(reports.top_scorers(tid, limit=200)),
                         total(scorers_before) + 2)

        d = match_result.get_match_details(ko["match_id"])
        self.assertEqual(len(d["shootout"]), 6)
        self.assertEqual([k["home"] for k in d["shootout"]], [True, False] * 3)
        self.assertEqual(match_result.get_match_shootout(ko["match_id"]), shootout)

    def test_invalid_shootouts_rejected(self):
        tid, ko, home, away = self._ko_match()
        mid = ko["match_id"]
        cases = [
            (0, 0, None, [(home[0], True), (away[0], True)]),   # nierozstrzygnięta
            (0, 0, 0, [(home[0], False), (away[0], True)]),     # sprzeczna z winner_pen
            (1, 0, None, [(home[0], True)]),                    # bez remisu
        ]
        outsider = next(p["id"] for t in team_dao.list_teams(tid)
                        if t["id"] not in (ko["home_team_id"], ko["away_team_id"])
                        for p in player_dao.list_players(t["id"]))
        cases.append((0, 0, None, [(outsider, True)]))          # obcy zawodnik
        for hs, as_, wp, so in cases:
            scorers = [home[0]] * hs + [away[0]] * as_
            with self.assertRaises(ValueError):
                match_result.save_match_result(mid, hs, as_, scorers, wp, so)
        self.assertFalse(match_result.get_match(mid)["played"])

    def test_trigger_blocks_kick_without_shootout(self):
        tid, ko, home, _ = self._ko_match()
        match_result.save_match_result(ko["match_id"], 1, 0, [home[0]])
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            with get_connection() as c:
                c.execute("INSERT INTO penalty_kick (match_id, kick_no, player_id, scored) "
                          "VALUES (?, 1, ?, 1)", (ko["match_id"], home[0]))

    def test_edit_replaces_shootout(self):
        tid, ko, home, away = self._ko_match()
        mid = ko["match_id"]
        match_result.save_match_result(mid, 0, 0, [], shootout=[(home[0], True), (away[0], False)])
        match_result.edit_match_result(mid, 2, 0, [home[0], home[1]])
        self.assertEqual(match_result.get_match_shootout(mid), [])
        self.assertIsNone(match_result.get_match(mid)["winner_pen"])

    def test_export_import_keeps_shootout(self):
        from app.services import backup
        tid, ko, home, away = self._ko_match()
        shootout = [(home[0], True), (away[0], False)]
        match_result.save_match_result(ko["match_id"], 0, 0, [], shootout=shootout)

        data = backup.export_tournament(tid)
        new_tid = backup.import_tournament(data)
        new_ko = next(f for f in schedule.get_schedule(new_tid) if f["stage"] == "SF_TOP")
        d = match_result.get_match_details(new_ko["match_id"])
        self.assertEqual([(k["home"], k["scored"]) for k in d["shootout"]],
                         [(True, True), (False, False)])

        # plik sprzed wprowadzenia serii karnych (bez sekcji) też się wczytuje
        del data["penalty_kicks"]
        backup.import_tournament(data)


class TestMatchDateTime(DBTestCase):
    def _fixture(self):
        tid, _ = self._make_tournament()
        draw.draw_groups(tid)
        schedule.generate_group_schedule(tid)
        return tid, next(f for f in schedule.get_schedule(tid) if f["stage"] == "GROUP")

    def test_schedule_generation_leaves_date_empty(self):
        tid, _ = self._fixture()
        self.assertTrue(all(f["scheduled_at"] is None for f in schedule.get_schedule(tid)))

    def test_set_change_and_clear(self):
        tid, fx = self._fixture()
        schedule.set_match_datetime(fx["match_id"], "2026-10-18 18:30")
        self.assertEqual(match_result.get_match(fx["match_id"])["scheduled_at"], "2026-10-18 18:30")
        schedule.set_match_datetime(fx["match_id"], "2026-10-19 9:05")      # normalizacja
        self.assertEqual(match_result.get_match(fx["match_id"])["scheduled_at"], "2026-10-19 09:05")
        schedule.set_match_datetime(fx["match_id"], None)
        self.assertIsNone(match_result.get_match(fx["match_id"])["scheduled_at"])

    def test_invalid_rejected(self):
        tid, fx = self._fixture()
        for bad in ("jutro", "2026-13-01 10:00", "2026-10-18"):
            with self.assertRaises(ValueError):
                schedule.set_match_datetime(fx["match_id"], bad)
        with self.assertRaises(ValueError):
            schedule.set_match_datetime(999999, "2026-10-18 18:30")

    def test_date_survives_result_and_export_import(self):
        from app.services import backup
        tid, fx = self._fixture()
        schedule.set_match_datetime(fx["match_id"], "2026-10-18 18:30")
        match_result.save_match_result(fx["match_id"], 1, 0, [self._first_player(fx["home_team_id"])])
        self.assertEqual(match_result.get_match(fx["match_id"])["scheduled_at"], "2026-10-18 18:30")

        data = backup.export_tournament(tid)
        new_tid = backup.import_tournament(data)
        dates = [f["scheduled_at"] for f in schedule.get_schedule(new_tid) if f["scheduled_at"]]
        self.assertEqual(dates, ["2026-10-18 18:30"])
        for m in data["matches"]:          # plik sprzed wprowadzenia terminów
            del m["scheduled_at"]
        backup.import_tournament(data)
