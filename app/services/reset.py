from db.init import get_connection, with_retry


def reset_to_setup(tournament_id: int) -> None:
    """
    Cofa turniej do stanu sprzed losowania (SETUP).

    Usuwa wszystkie mecze (gole kasują się kaskadowo), zdejmuje drużyny z grup
    i czyści historię transferów. Drużyny i zawodnicy zostają w obecnych
    składach — reset dotyczy wyników, nie składów.
    Wszystko w jednej transakcji. Retry przy sqlite3.OperationalError (database is locked).
    """
    with_retry(_do_reset, tournament_id)


def _do_reset(tournament_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        state = conn.execute(
            "SELECT state FROM tournament WHERE id = ?", (tournament_id,)
        ).fetchone()

        if state is None:
            raise ValueError(f"Turniej {tournament_id} nie istnieje.")
        if state["state"] == "SETUP":
            raise ValueError("Turniej jest już przed losowaniem.")

        conn.execute("DELETE FROM match WHERE tournament_id = ?", (tournament_id,))
        conn.execute("DELETE FROM transfer WHERE tournament_id = ?", (tournament_id,))
        conn.execute(
            "UPDATE team SET group_name = NULL WHERE tournament_id = ?", (tournament_id,)
        )
        conn.execute(
            "UPDATE tournament SET state = 'SETUP' WHERE id = ?", (tournament_id,)
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()