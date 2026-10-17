from db.init import get_connection


def create_tournament(name: str) -> int:
    """Tworzy nowy turniej w stanie SETUP. Zwraca jego id."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tournament (name) VALUES (?)", (name,)
        )
        return cur.lastrowid


def rename_tournament(tournament_id: int, new_name: str) -> None:
    """Zmienia nazwę turnieju. Nazwa to tylko etykieta — powiązania idą przez id."""
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Nazwa turnieju nie może być pusta.")
    with get_connection() as conn:
        conn.execute("UPDATE tournament SET name = ? WHERE id = ?", (new_name, tournament_id))


def name_taken(name: str, exclude_id: int | None = None) -> bool:
    """Czy inny turniej ma już taką nazwę (bez względu na wielkość liter)."""
    # Porównanie w Pythonie: SQLite-owe lower() nie obsługuje polskich znaków (Ł, Ó…).
    wanted = name.strip().casefold()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM tournament WHERE id IS NOT ?", (exclude_id,)
        ).fetchall()
    return any(r["name"].strip().casefold() == wanted for r in rows)


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