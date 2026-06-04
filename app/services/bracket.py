import sqlite3
from db.init import get_connection


def seed_brackets(tournament_id: int, conn: sqlite3.Connection) -> None:
    """
    Tworzy mecze 3 drabinek KO na podstawie wyników fazy grupowej.
    Wywoływana wewnątrz istniejącej transakcji z match_result.py.

    Kolejność po grupie: punkty → bilans → bramki strzelone.
    Drabinki:
      TOP  (miejsca 1-4):  A1 vs B2, B1 vs A2 → Final, 3rd place
      MID  (miejsca 5-8):  A3 vs B4, B3 vs A4 → Final, 7th place
      BOT  (miejsca 9-12): A5 vs B6, B5 vs A6 → Final, 11th place
    """
    standings = _get_standings(tournament_id, conn)

    group_a = standings["A"]  # posortowane 1..6
    group_b = standings["B"]

    # Pary półfinałów dla każdej drabinki (home, away)
    brackets = {
        "TOP": [
            (group_a[0], group_b[1]),  # A1 vs B2
            (group_b[0], group_a[1]),  # B1 vs A2
        ],
        "MID": [
            (group_a[2], group_b[3]),  # A3 vs B4
            (group_b[2], group_a[3]),  # B3 vs A4
        ],
        "BOT": [
            (group_a[4], group_b[5]),  # A5 vs B6
            (group_b[4], group_a[5]),  # B5 vs A6
        ],
    }

    stage_map = {
        "TOP": ("SF_TOP", "FINAL_TOP", "THIRD_PLACE"),
        "MID": ("SF_MID", "FINAL_MID", "SEVENTH_PLACE"),
        "BOT": ("SF_BOT", "FINAL_BOT", "ELEVENTH_PLACE"),
    }

    for bracket, pairs in brackets.items():
        sf_stage, final_stage, third_stage = stage_map[bracket]

        sf_ids = []
        for home_team, away_team in pairs:
            cur = conn.execute(
                """INSERT INTO match (tournament_id, stage, home_team_id, away_team_id)
                   VALUES (?, ?, ?, ?)""",
                (tournament_id, sf_stage, home_team, away_team)
            )
            sf_ids.append(cur.lastrowid)

        # Mecz finałowy i o 3. miejsce — bez drużyn, wypełniane po SF
        conn.execute(
            "INSERT INTO match (tournament_id, stage) VALUES (?, ?)",
            (tournament_id, final_stage)
        )
        conn.execute(
            "INSERT INTO match (tournament_id, stage) VALUES (?, ?)",
            (tournament_id, third_stage)
        )

    conn.execute(
        "UPDATE tournament SET state = 'KO' WHERE id = ?", (tournament_id,)
    )


def propagate_ko_result(match_id: int) -> None:
    """
    Po wpisaniu wyniku meczu SF — wstawia zwycięzcę do finału, przegranego do meczu o 3. miejsce.
    Wywoływana przez match_result po zapisaniu wyniku meczu KO.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        match = conn.execute(
            "SELECT * FROM match WHERE id = ?", (match_id,)
        ).fetchone()

        stage = match["stage"]
        if stage not in ("SF_TOP", "SF_MID", "SF_BOT"):
            conn.rollback()
            return

        stage_map = {
            "SF_TOP": ("FINAL_TOP", "THIRD_PLACE"),
            "SF_MID": ("FINAL_MID", "SEVENTH_PLACE"),
            "SF_BOT": ("FINAL_BOT", "ELEVENTH_PLACE"),
        }
        final_stage, third_stage = stage_map[stage]
        tournament_id = match["tournament_id"]

        winner = _get_winner(match)
        loser = _get_loser(match)

        # Sprawdź czy drugi SF tej drabinki już rozegrany
        other_sf = conn.execute(
            """SELECT * FROM match
               WHERE tournament_id = ? AND stage = ? AND played = 1 AND id != ?""",
            (tournament_id, stage, match_id)
        ).fetchone()

        final = conn.execute(
            "SELECT id FROM match WHERE tournament_id = ? AND stage = ?",
            (tournament_id, final_stage)
        ).fetchone()

        third = conn.execute(
            "SELECT id FROM match WHERE tournament_id = ? AND stage = ?",
            (tournament_id, third_stage)
        ).fetchone()

        if other_sf:
            # Drugi SF też rozegrany — wypełnij finał i mecz o 3. miejsce
            other_winner = _get_winner(other_sf)
            other_loser  = _get_loser(other_sf)

            conn.execute(
                "UPDATE match SET home_team_id = ?, away_team_id = ? WHERE id = ?",
                (winner, other_winner, final["id"])
            )
            conn.execute(
                "UPDATE match SET home_team_id = ?, away_team_id = ? WHERE id = ?",
                (loser, other_loser, third["id"])
            )
        # Jeśli drugi SF jeszcze nierozegrany — poczekaj, wypełni go tamten wynik

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _get_winner(match_row) -> int:
    if match_row["winner_pen"] is not None:
        return match_row["home_team_id"] if match_row["winner_pen"] == 0 else match_row["away_team_id"]
    if match_row["home_score"] > match_row["away_score"]:
        return match_row["home_team_id"]
    return match_row["away_team_id"]


def _get_loser(match_row) -> int:
    if match_row["winner_pen"] is not None:
        return match_row["away_team_id"] if match_row["winner_pen"] == 0 else match_row["home_team_id"]
    if match_row["home_score"] > match_row["away_score"]:
        return match_row["away_team_id"]
    return match_row["home_team_id"]


def _get_standings(tournament_id: int, conn: sqlite3.Connection) -> dict:
    """Zwraca słownik {'A': [id1, id2, ...], 'B': [...]} posortowany wg tabeli grupy."""
    rows = conn.execute(
        """SELECT team_id, group_name, points, goal_diff, goals_for
           FROM v_group_table
           WHERE tournament_id = ?
           ORDER BY group_name, points DESC, goal_diff DESC, goals_for DESC""",
        (tournament_id,)
    ).fetchall()

    standings: dict[str, list[int]] = {"A": [], "B": []}
    for row in rows:
        standings[row["group_name"]].append(row["team_id"])
    return standings
