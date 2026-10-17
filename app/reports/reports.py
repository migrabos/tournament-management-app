"""
Raporty agregujące — złożone zapytania pobierające dane z wielu tabel.
Każdy raport to jedno zapytanie SQL z JOIN/GROUP BY (logika w bazie, nie w Pythonie).
"""
from db.init import get_connection


def group_table(tournament_id: int, group_name: str) -> list[dict]:
    """Tabela jednej grupy, posortowana wg regulaminu:
    punkty → różnica bramek → bramki strzelone."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT team_name, played, wins, draws, losses,
                      goals_for, goals_against, goal_diff, points
               FROM v_group_table
               WHERE tournament_id = ? AND group_name = ?
               ORDER BY points DESC, goal_diff DESC, goals_for DESC, team_name""",
            (tournament_id, group_name)
        ).fetchall()
    return [dict(r) for r in rows]


def group_table_after_round(tournament_id: int, group_name: str, round_no: int) -> list[dict]:
    """Tabela grupy uwzględniająca tylko mecze rozegrane do kolejki round_no włącznie
    (np. do grafiki kolejki). Kolumny i sortowanie jak w group_table."""
    with get_connection() as conn:
        rows = conn.execute(
            """WITH per_team AS (
                   SELECT t.id AS team_id, t.name AS team_name, m.id AS match_id,
                          CASE WHEN m.home_team_id = t.id THEN m.home_score ELSE m.away_score END AS gf,
                          CASE WHEN m.home_team_id = t.id THEN m.away_score ELSE m.home_score END AS ga
                     FROM team t
                     LEFT JOIN match m ON m.tournament_id = t.tournament_id
                                 AND m.stage = 'GROUP' AND m.played = 1 AND m.round <= ?
                                 AND (m.home_team_id = t.id OR m.away_team_id = t.id)
                    WHERE t.tournament_id = ? AND t.group_name = ?
               )
               SELECT team_name,
                      COUNT(match_id)                                         AS played,
                      SUM(CASE WHEN gf > ga THEN 1 ELSE 0 END)                AS wins,
                      SUM(CASE WHEN gf = ga AND match_id IS NOT NULL THEN 1 ELSE 0 END) AS draws,
                      SUM(CASE WHEN gf < ga THEN 1 ELSE 0 END)                AS losses,
                      COALESCE(SUM(gf), 0)                                    AS goals_for,
                      COALESCE(SUM(ga), 0)                                    AS goals_against,
                      COALESCE(SUM(gf - ga), 0)                               AS goal_diff,
                      SUM(CASE WHEN gf > ga THEN 3
                               WHEN gf = ga AND match_id IS NOT NULL THEN 1
                               ELSE 0 END)                                    AS points
                 FROM per_team
                GROUP BY team_id, team_name
                ORDER BY points DESC, goal_diff DESC, goals_for DESC, team_name""",
            (round_no, tournament_id, group_name)
        ).fetchall()
    return [dict(r) for r in rows]


def top_scorers(tournament_id: int, limit: int = 20) -> list[dict]:
    """Klasyfikacja królów strzelców w turnieju."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT player_name, team_name, goals
               FROM v_scorers
               WHERE tournament_id = ?
               ORDER BY goals DESC, player_name
               LIMIT ?""",
            (tournament_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def transfer_history(tournament_id: int) -> list[dict]:
    """Historia transferów w turnieju (najnowsze pierwsze)."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT player_name, from_team_name, to_team_name, transferred_at
               FROM v_transfer_history
               WHERE tournament_id = ?
               ORDER BY transferred_at DESC, transfer_id DESC""",
            (tournament_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def team_stats(tournament_id: int) -> list[dict]:
    """Statystyki drużyn: liczba meczów, bramki, śr. bramek/mecz, % wygranych.
    Łączy match (jako home i away), goal i team — agregacja wieloencyjna."""
    with get_connection() as conn:
        rows = conn.execute(
            """WITH games AS (
                   SELECT t.id AS team_id, t.name AS team_name,
                          CASE WHEN m.home_team_id = t.id THEN m.home_score
                               ELSE m.away_score END AS gf,
                          CASE WHEN m.home_team_id = t.id THEN m.away_score
                               ELSE m.home_score END AS ga
                   FROM team t
                   JOIN match m ON m.played = 1
                               AND (m.home_team_id = t.id OR m.away_team_id = t.id)
                   WHERE t.tournament_id = ?
               )
               SELECT team_name,
                      COUNT(*) AS matches,
                      COALESCE(SUM(gf), 0) AS goals_for,
                      COALESCE(SUM(ga), 0) AS goals_against,
                      ROUND(AVG(gf), 2) AS avg_goals_for,
                      ROUND(100.0 * SUM(CASE WHEN gf > ga THEN 1 ELSE 0 END) / COUNT(*), 1)
                          AS win_pct
               FROM games
               GROUP BY team_id, team_name
               ORDER BY goals_for DESC, team_name""",
            (tournament_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def squad(team_id: int) -> list[dict]:
    """Skład drużyny z liczbą strzelonych bramek dla każdego zawodnika."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT p.name AS player_name,
                      COUNT(g.id) AS goals
               FROM player p
               LEFT JOIN goal g ON g.scorer_id = p.id
               WHERE p.team_id = ?
               GROUP BY p.id, p.name
               ORDER BY goals DESC, p.name""",
            (team_id,)
        ).fetchall()
    return [dict(r) for r in rows]
