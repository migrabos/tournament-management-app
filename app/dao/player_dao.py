from db.init import get_connection


def add_player(team_id: int, name: str) -> int:
    """Dodaje zawodnika do drużyny. Zwraca jego id.
    Trigger trg_player_squad_limit pilnuje limitu 10 zawodników."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO player (team_id, name) VALUES (?, ?)",
            (team_id, name)
        )
        return cur.lastrowid


def delete_player(player_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM player WHERE id = ?", (player_id,))


def get_player(player_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM player WHERE id = ?", (player_id,)
        ).fetchone()
    return dict(row) if row else None


def list_players(team_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM player WHERE team_id = ? ORDER BY name", (team_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def count_players(team_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM player WHERE team_id = ?", (team_id,)
        ).fetchone()
    return row["cnt"]


def list_players_in_tournament(tournament_id: int) -> list[dict]:
    """Zwraca wszystkich zawodników turnieju z informacją o drużynie."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT p.id, p.name AS pname, t.id AS tid, t.name AS tname
               FROM player p JOIN team t ON t.id = p.team_id
               WHERE t.tournament_id = ? ORDER BY t.name, p.name""",
            (tournament_id,)
        ).fetchall()
    return [dict(r) for r in rows]
