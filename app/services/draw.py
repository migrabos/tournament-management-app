import random
from db.init import get_connection


def draw_groups(tournament_id: int) -> None:
    """
    Losuje grupy dla turnieju: 12 drużyn dzielonych losowo na grupę A (6) i B (6).
    Wymaga dokładnie 12 drużyn z group_name=NULL.
    Ustawia tournament.state='GROUP' po pomyślnym losowaniu.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        state = conn.execute(
            "SELECT state FROM tournament WHERE id = ?", (tournament_id,)
        ).fetchone()

        if state is None:
            raise ValueError(f"Turniej {tournament_id} nie istnieje.")
        if state["state"] != "SETUP":
            raise ValueError("Losowanie możliwe tylko w fazie SETUP.")

        teams = conn.execute(
            "SELECT id FROM team WHERE tournament_id = ?", (tournament_id,)
        ).fetchall()

        if len(teams) != 12:
            raise ValueError(f"Turniej musi mieć dokładnie 12 drużyn (jest {len(teams)}).")

        ids = [row["id"] for row in teams]
        random.shuffle(ids)

        group_a = ids[:6]
        group_b = ids[6:]

        conn.execute(
            "UPDATE team SET group_name = NULL WHERE tournament_id = ?",
            (tournament_id,)
        )

        for team_id in group_a:
            conn.execute(
                "UPDATE team SET group_name = 'A' WHERE id = ?", (team_id,)
            )
        for team_id in group_b:
            conn.execute(
                "UPDATE team SET group_name = 'B' WHERE id = ?", (team_id,)
            )

        conn.execute(
            "UPDATE tournament SET state = 'GROUP' WHERE id = ?", (tournament_id,)
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_groups(tournament_id: int) -> dict:
    """Zwraca słownik {'A': [...], 'B': [...]} z nazwami drużyn po losowaniu."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name, group_name FROM team "
            "WHERE tournament_id = ? AND group_name IS NOT NULL "
            "ORDER BY group_name, name",
            (tournament_id,)
        ).fetchall()

    result = {"A": [], "B": []}
    for row in rows:
        result[row["group_name"]].append(row["name"])
    return result
