from datetime import datetime

from db.init import get_connection


def _berger_rounds(team_ids: list[int]) -> list[list[tuple[int, int]]]:
    """
    Algorytm Bergera: generuje kolejki round-robin dla n drużyn.
    Zwraca listę kolejek, każda kolejka to lista par (home_id, away_id).
    """
    n = len(team_ids)
    teams = team_ids[:]
    if n % 2 == 1:
        teams.append(None)  # bye
    half = len(teams) // 2
    rounds = []

    for _ in range(len(teams) - 1):
        pairs = []
        for i in range(half):
            home = teams[i]
            away = teams[len(teams) - 1 - i]
            if home is not None and away is not None:
                pairs.append((home, away))
        rounds.append(pairs)
        # rotacja: pierwszy element stały, reszta przesuwa się w prawo
        teams = [teams[0]] + [teams[-1]] + teams[1:-1]

    return rounds


def generate_group_schedule(tournament_id: int) -> None:
    """
    Generuje terminarz fazy grupowej (round-robin) dla obu grup.
    Wymaga tournament.state='GROUP' i drużyn z przypisanymi grupami.
    Wszystko w jednej transakcji.
    """
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        state = conn.execute(
            "SELECT state FROM tournament WHERE id = ?", (tournament_id,)
        ).fetchone()

        if state is None:
            raise ValueError(f"Turniej {tournament_id} nie istnieje.")
        if state["state"] != "GROUP":
            raise ValueError("Generowanie terminarza możliwe tylko w fazie GROUP.")

        # Usuń istniejące mecze grupowe (np. ponowne generowanie)
        conn.execute(
            "DELETE FROM match WHERE tournament_id = ? AND stage = 'GROUP'",
            (tournament_id,)
        )

        for group_name in ("A", "B"):
            teams = conn.execute(
                "SELECT id FROM team WHERE tournament_id = ? AND group_name = ?",
                (tournament_id, group_name)
            ).fetchall()

            if len(teams) != 6:
                raise ValueError(f"Grupa {group_name} musi mieć 6 drużyn (jest {len(teams)}).")

            team_ids = [row["id"] for row in teams]
            rounds = _berger_rounds(team_ids)

            for round_num, pairs in enumerate(rounds, start=1):
                for home_id, away_id in pairs:
                    conn.execute(
                        """INSERT INTO match
                           (tournament_id, stage, group_name, round, home_team_id, away_team_id)
                           VALUES (?, 'GROUP', ?, ?, ?, ?)""",
                        (tournament_id, group_name, round_num, home_id, away_id)
                    )

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


DATETIME_FORMAT = "%Y-%m-%d %H:%M"


def set_match_datetime(match_id: int, when: str | None) -> None:
    """Ustawia termin meczu ('YYYY-MM-DD HH:MM') albo go usuwa (None).
    Termin nie jest nadawany przy generowaniu terminarza — ustala go administrator."""
    if when is not None:
        try:
            when = datetime.strptime(when, DATETIME_FORMAT).strftime(DATETIME_FORMAT)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Niepoprawny termin: {when!r} (oczekiwano RRRR-MM-DD GG:MM).") from e
    with get_connection() as conn:
        if conn.execute("UPDATE match SET scheduled_at = ? WHERE id = ?",
                        (when, match_id)).rowcount == 0:
            raise ValueError(f"Mecz {match_id} nie istnieje.")


def get_schedule(tournament_id: int, group_name: str | None = None) -> list[dict]:
    """Zwraca terminarz meczów (opcjonalnie filtrowany po grupie)."""
    with get_connection() as conn:
        if group_name:
            rows = conn.execute(
                "SELECT * FROM v_match_schedule "
                "WHERE tournament_id = ? AND group_name = ? "
                "ORDER BY round, group_name, match_id",
                (tournament_id, group_name)
            ).fetchall()
        else:
            # Faza grupowa wg kolejek (kolejka 1 obu grup, potem kolejka 2 itd.),
            # mecze KO (round NULL) na końcu wg match_id.
            rows = conn.execute(
                "SELECT * FROM v_match_schedule WHERE tournament_id = ? "
                "ORDER BY round IS NULL, round, group_name, match_id",
                (tournament_id,)
            ).fetchall()

    return [dict(row) for row in rows]
