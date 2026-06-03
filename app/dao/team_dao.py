from db.init import get_connection


def add_team(tournament_id: int, name: str) -> int:
    """Dodaje drużynę do turnieju. Zwraca jej id."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO team (tournament_id, name) VALUES (?, ?)",
            (tournament_id, name)
        )
        return cur.lastrowid


def rename_team(team_id: int, new_name: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE team SET name = ? WHERE id = ?", (new_name, team_id))


def delete_team(team_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM team WHERE id = ?", (team_id,))


def get_team(team_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM team WHERE id = ?", (team_id,)).fetchone()
    return dict(row) if row else None


def list_teams(tournament_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM team WHERE tournament_id = ? ORDER BY group_name, name",
            (tournament_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def count_teams(tournament_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM team WHERE tournament_id = ?",
            (tournament_id,)
        ).fetchone()
    return row["cnt"]
