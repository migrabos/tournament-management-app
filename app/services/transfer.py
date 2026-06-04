import sqlite3
from db.init import get_connection, with_retry

MAX_SQUAD = 10
MIN_SQUAD = 5


def transfer_player(player_id: int, to_team_id: int) -> None:
    """
    Atomowo przenosi zawodnika do nowej drużyny.
    Kontrola współbieżności: BEGIN IMMEDIATE + warunek WHERE team_id=current
    gwarantuje, że tylko jedna transakcja wygrywa wyścig o tego samego zawodnika.
    Retry przy sqlite3.OperationalError (database is locked).
    """
    with_retry(_do_transfer, player_id, to_team_id)


def _do_transfer(player_id: int, to_team_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        player = conn.execute(
            "SELECT p.*, t.tournament_id FROM player p JOIN team t ON t.id = p.team_id WHERE p.id = ?",
            (player_id,)
        ).fetchone()

        if player is None:
            raise ValueError(f"Zawodnik {player_id} nie istnieje.")

        from_team_id = player["team_id"]
        tournament_id = player["tournament_id"]

        if from_team_id == to_team_id:
            raise ValueError("Zawodnik już należy do tej drużyny.")

        # Sprawdź czy drużyna docelowa jest w tym samym turnieju
        to_team = conn.execute(
            "SELECT tournament_id FROM team WHERE id = ?", (to_team_id,)
        ).fetchone()

        if to_team is None:
            raise ValueError(f"Drużyna {to_team_id} nie istnieje.")
        if to_team["tournament_id"] != tournament_id:
            raise ValueError("Drużyny muszą być w tym samym turnieju.")

        # Sprawdź limit składu drużyny docelowej
        squad_size = conn.execute(
            "SELECT COUNT(*) as cnt FROM player WHERE team_id = ?", (to_team_id,)
        ).fetchone()["cnt"]

        if squad_size >= MAX_SQUAD:
            raise ValueError(f"Drużyna docelowa ma już {MAX_SQUAD} zawodników (limit składu).")

        # Sprawdź minimum składu drużyny źródłowej
        from_squad_size = conn.execute(
            "SELECT COUNT(*) as cnt FROM player WHERE team_id = ?", (from_team_id,)
        ).fetchone()["cnt"]

        if from_squad_size <= MIN_SQUAD:
            raise ValueError(
                f"Drużyna źródłowa musi mieć min. {MIN_SQUAD} zawodników "
                f"(ma {from_squad_size}) — nie można jej dalej osłabiać.")

        # Kluczowy warunek: WHERE team_id=from_team_id zabezpiecza przed wyścigiem.
        # Jeśli inny wątek zdążył przenieść zawodnika wcześniej, UPDATE zmieni 0 wierszy.
        rows_updated = conn.execute(
            "UPDATE player SET team_id = ? WHERE id = ? AND team_id = ?",
            (to_team_id, player_id, from_team_id)
        ).rowcount

        if rows_updated == 0:
            raise ValueError("Zawodnik został właśnie przeniesiony przez inną operację — spróbuj ponownie.")

        # Trigger trg_transfer_audit automatycznie wstawia rekord do tabeli transfer.

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
