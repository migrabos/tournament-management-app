import sqlite3
from db.init import get_connection, with_retry
from app.services.bracket import seed_brackets, propagate_ko_result

SF_STAGES = ("SF_TOP", "SF_MID", "SF_BOT")
# Dla każdego półfinału — mecze zależne, które wypełnia jego zwycięzca/przegrany.
SF_DEPENDENTS = {
    "SF_TOP": ("FINAL_TOP", "THIRD_PLACE"),
    "SF_MID": ("FINAL_MID", "SEVENTH_PLACE"),
    "SF_BOT": ("FINAL_BOT", "ELEVENTH_PLACE"),
}


def _validate_scorers(home_score: int, away_score: int, scorer_ids: list[int]) -> None:
    """Sprawdza, czy liczba strzelców zgadza się z wynikiem."""
    expected = home_score + away_score
    if len(scorer_ids) != expected:
        raise ValueError(
            f"Liczba strzelców ({len(scorer_ids)}) nie zgadza się "
            f"z wynikiem ({home_score} + {away_score} = {expected})."
        )


def _check_tournament_finished(tournament_id: int) -> None:
    """Jeśli wszystkie mecze turnieju zostały rozegrane — ustawia stan FINISHED."""
    with get_connection() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) AS cnt FROM match WHERE tournament_id = ? AND played = 0",
            (tournament_id,)
        ).fetchone()["cnt"]
        if remaining == 0:
            conn.execute(
                "UPDATE tournament SET state = 'FINISHED' WHERE id = ? AND state = 'KO'",
                (tournament_id,)
            )


def save_match_result(
    match_id: int,
    home_score: int,
    away_score: int,
    scorer_ids: list[int],
    winner_pen: int | None = None,
) -> None:
    """
    Atomowo zapisuje wynik meczu i listę strzelców.
    winner_pen: 0 = home wygrał karne, 1 = away wygrał karne, None = bez karnych.
    Jeśli to ostatni mecz fazy grupowej — automatycznie tworzy drabinki KO.
    Retry przy sqlite3.OperationalError (database is locked).
    """
    with_retry(_do_save_match_result, match_id, home_score, away_score,
               scorer_ids, winner_pen)


def _do_save_match_result(
    match_id: int,
    home_score: int,
    away_score: int,
    scorer_ids: list[int],
    winner_pen: int | None,
) -> None:
    _validate_scorers(home_score, away_score, scorer_ids)

    conn = get_connection()
    tournament_id = None
    stage = None
    try:
        conn.execute("BEGIN IMMEDIATE")

        match = conn.execute(
            "SELECT * FROM match WHERE id = ?", (match_id,)
        ).fetchone()

        if match is None:
            raise ValueError(f"Mecz {match_id} nie istnieje.")
        if match["played"] == 1:
            raise ValueError("Wynik tego meczu został już wpisany.")

        tournament_id = match["tournament_id"]
        stage = match["stage"]

        conn.execute(
            """UPDATE match
               SET home_score = ?, away_score = ?, winner_pen = ?, played = 1
               WHERE id = ?""",
            (home_score, away_score, winner_pen, match_id)
        )

        for scorer_id in scorer_ids:
            conn.execute(
                "INSERT INTO goal (match_id, scorer_id) VALUES (?, ?)",
                (match_id, scorer_id)
            )

        # Sprawdź czy to ostatni mecz fazy grupowej w turnieju
        if stage == "GROUP":
            remaining = conn.execute(
                """SELECT COUNT(*) as cnt FROM match
                   WHERE tournament_id = ? AND stage = 'GROUP' AND played = 0
                   AND id != ?""",
                (tournament_id, match_id)
            ).fetchone()["cnt"]

            if remaining == 0:
                seed_brackets(tournament_id, conn)

        conn.commit()

        # Propagacja po meczu SF (poza główną transakcją — bracket otwiera własną)
        if stage in SF_STAGES:
            propagate_ko_result(match_id)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Po zapisie sprawdź, czy turniej nie jest zakończony
    if tournament_id and stage != "GROUP":
        _check_tournament_finished(tournament_id)


def can_edit_match(match_id: int) -> tuple[bool, str]:
    """Czy wynik rozegranego meczu można jeszcze edytować.
    Zwraca (True, "") albo (False, powód).

    Reguły:
      - mecz grupowy: edytowalny dopóki turniej jest w fazie GROUP
        (po wpisaniu ostatniego wyniku drabinki są rozstawione i wyniki grup się blokują);
      - półfinał KO: edytowalny dopóki zależny finał i mecz o miejsce NIE są rozegrane
        (inaczej zmiana zwycięzcy podmieniłaby uczestnika już rozstrzygniętego meczu);
      - finał / mecz o miejsce: edytowalny zawsze (brak meczów zależnych).
    """
    with get_connection() as conn:
        m = conn.execute("SELECT * FROM match WHERE id = ?", (match_id,)).fetchone()
        if m is None:
            return False, "Mecz nie istnieje."
        if not m["played"]:
            return False, "Mecz nie został jeszcze rozegrany."

        if m["stage"] == "GROUP":
            state = conn.execute(
                "SELECT state FROM tournament WHERE id = ?", (m["tournament_id"],)
            ).fetchone()["state"]
            if state != "GROUP":
                return False, "Wyniki grupowe są zablokowane po rozstawieniu drabinek."
            return True, ""

        if m["stage"] in SF_STAGES:
            final_stage, place_stage = SF_DEPENDENTS[m["stage"]]
            dependents = conn.execute(
                """SELECT played FROM match
                   WHERE tournament_id = ? AND stage IN (?, ?)""",
                (m["tournament_id"], final_stage, place_stage)
            ).fetchall()
            if any(d["played"] for d in dependents):
                return False, ("Najpierw zmień/usuń wynik kolejnego meczu "
                               "(finał lub mecz o miejsce), który wynika z tego półfinału.")
            return True, ""

        # finał / mecz o miejsce — brak meczów zależnych
        return True, ""


def edit_match_result(
    match_id: int,
    home_score: int,
    away_score: int,
    scorer_ids: list[int],
    winner_pen: int | None = None,
) -> None:
    """Edytuje wynik już rozegranego meczu (transakcja).
    Usuwa poprzednich strzelców, zapisuje nowy wynik i nowych strzelców.
    Dla półfinału KO ponownie propaguje zwycięzcę/przegranego do meczów zależnych.
    Retry przy sqlite3.OperationalError (database is locked).
    """
    with_retry(_do_edit_match_result, match_id, home_score, away_score,
               scorer_ids, winner_pen)


def _do_edit_match_result(
    match_id: int,
    home_score: int,
    away_score: int,
    scorer_ids: list[int],
    winner_pen: int | None,
) -> None:
    _validate_scorers(home_score, away_score, scorer_ids)

    editable, reason = can_edit_match(match_id)
    if not editable:
        raise ValueError(reason)

    conn = get_connection()
    tournament_id = None
    stage = None
    try:
        conn.execute("BEGIN IMMEDIATE")

        match = conn.execute(
            "SELECT * FROM match WHERE id = ?", (match_id,)
        ).fetchone()

        tournament_id = match["tournament_id"]
        stage = match["stage"]

        conn.execute("DELETE FROM goal WHERE match_id = ?", (match_id,))
        conn.execute(
            """UPDATE match
               SET home_score = ?, away_score = ?, winner_pen = ?, played = 1
               WHERE id = ?""",
            (home_score, away_score, winner_pen, match_id)
        )
        for scorer_id in scorer_ids:
            conn.execute(
                "INSERT INTO goal (match_id, scorer_id) VALUES (?, ?)",
                (match_id, scorer_id)
            )

        conn.commit()

        # Ponowna propagacja po edycji półfinału (mecze zależne nie są rozegrane — sprawdzone wyżej)
        if stage in SF_STAGES:
            propagate_ko_result(match_id)

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Po edycji sprawdź, czy turniej nie jest zakończony
    if tournament_id and stage != "GROUP":
        _check_tournament_finished(tournament_id)


def get_match(match_id: int) -> dict | None:
    """Zwraca dane meczu lub None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM match WHERE id = ?", (match_id,)
        ).fetchone()
    return dict(row) if row else None


def get_match_goals(match_id: int) -> list[dict]:
    """Zwraca listę strzelców dla danego meczu."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT g.id, p.name as scorer_name, t.name as team_name
               FROM goal g
               JOIN player p ON p.id = g.scorer_id
               JOIN team   t ON t.id = p.team_id
               WHERE g.match_id = ?""",
            (match_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def get_match_scorer_counts(match_id: int) -> dict[int, int]:
    """Zwraca słownik {scorer_id: liczba_bramek} dla danego meczu."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT scorer_id, COUNT(*) AS n FROM goal WHERE match_id = ? GROUP BY scorer_id",
            (match_id,)
        ).fetchall()
    return {row["scorer_id"]: row["n"] for row in rows}
