from db.init import get_connection


def create_tournament(name: str) -> int:
    """Tworzy nowy turniej w stanie SETUP. Zwraca jego id."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tournament (name) VALUES (?)", (name,)
        )
        return cur.lastrowid


def get_tournament(tournament_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM tournament WHERE id = ?", (tournament_id,)
        ).fetchone()
    return dict(row) if row else None


def list_tournaments() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tournament ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_tournament(tournament_id: int) -> None:
    """Usuwa turniej i kaskadowo wszystkie powiązane dane."""
    with get_connection() as conn:
        conn.execute("DELETE FROM tournament WHERE id = ?", (tournament_id,))


def get_state(tournament_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT state FROM tournament WHERE id = ?", (tournament_id,)
        ).fetchone()
    return row["state"] if row else None
