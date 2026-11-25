from db.init import get_connection


def add_player(team_id: int, name: str) -> int:
    """Dodaje zawodnika do drużyny (w dowolnej fazie turnieju, bez limitu składu).
    Zwraca jego id."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO player (team_id, name) VALUES (?, ?)",
            (team_id, name)
        )
        return cur.lastrowid


def delete_player(player_id: int) -> None:
    """Usuwa zawodnika — tylko w fazie konfiguracji (SETUP).
    Później usunięcie skasowałoby jego gole (kaskada), a wyniki meczów zostałyby,
    przez co strzelcy przestaliby się zgadzać z wynikami."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT t.state FROM player p
               JOIN team tm ON tm.id = p.team_id
               JOIN tournament t ON t.id = tm.tournament_id
               WHERE p.id = ?""",
            (player_id,)
        ).fetchone()
        if row is None:
            return
        if row["state"] != "SETUP":
            raise ValueError("Zawodników usuwasz tylko w fazie konfiguracji "
                             "(przed losowaniem grup).")
        conn.execute("DELETE FROM player WHERE id = ?", (player_id,))


def get_player(player_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM player WHERE id = ?", (player_id,)
        ).fetchone()
    return dict(row) if row else None


def list_players(team_id: int, only_active: bool = False) -> list[dict]:
    """Skład drużyny; only_active=True pomija zawodników wyłączonych z gry."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM player WHERE team_id = ?" + (" AND active = 1" if only_active else "")
            + " ORDER BY name", (team_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def set_active(player_id: int, active: bool) -> None:
    """Włącza/wyłącza zawodnika w grze — w każdej fazie turnieju. Nic nie kasuje:
    gole, karne i historia wyłączonego zawodnika zostają."""
    with get_connection() as conn:
        conn.execute("UPDATE player SET active = ? WHERE id = ?", (int(bool(active)), player_id))


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
