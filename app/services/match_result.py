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


def _resolve_shootout(conn, match, home_score: int, away_score: int,
                      winner_pen: int | None, shootout: list) -> int | None:
    """Sprawdza serię karnych i zwraca winner_pen.
    shootout: [(player_id, scored), ...] w kolejności strzałów; pusta lista = bez serii
    (wtedy liczy się samo winner_pen). Seria musi wyłonić zwycięzcę — jeśli
    podano też winner_pen, musi się z nim zgadzać."""
    if not shootout:
        return winner_pen
    if match["stage"] == "GROUP" or home_score != away_score:
        raise ValueError("Rzuty karne tylko po remisie w meczu pucharowym.")
    team_of = {r["id"]: r["team_id"] for r in conn.execute(
        "SELECT id, team_id FROM player WHERE team_id IN (?, ?)",
        (match["home_team_id"], match["away_team_id"]))}
    home_pens = away_pens = 0
    for player_id, scored in shootout:
        if player_id not in team_of:
            raise ValueError("Wykonawca karnego nie należy do żadnej z drużyn tego meczu.")
        if team_of[player_id] == match["home_team_id"]:
            home_pens += bool(scored)
        else:
            away_pens += bool(scored)
    if home_pens == away_pens:
        raise ValueError(f"Seria karnych nierozstrzygnięta ({home_pens}:{away_pens}).")
    derived = 0 if home_pens > away_pens else 1
    if winner_pen is not None and winner_pen != derived:
        raise ValueError("Zwycięzca po karnych nie zgadza się z przebiegiem serii.")
    return derived


def _insert_shootout(conn, match_id: int, shootout: list) -> None:
    conn.executemany(
        "INSERT INTO penalty_kick (match_id, kick_no, player_id, scored) VALUES (?, ?, ?, ?)",
        [(match_id, i, pid, int(bool(scored))) for i, (pid, scored) in enumerate(shootout, 1)]
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
    shootout: list[tuple[int, bool]] | None = None,
) -> None:
    """
    Atomowo zapisuje wynik meczu i listę strzelców.
    winner_pen: 0 = home wygrał karne, 1 = away wygrał karne, None = bez karnych.
    shootout: opcjonalny przebieg serii [(player_id, scored), ...] — nie liczy się
    do klasyfikacji strzelców; jeśli podany, z niego wynika winner_pen.
    Faza grupowa NIE kończy się sama — drabinki KO tworzy dopiero
    confirm_group_stage() (przycisk „Zatwierdź fazę grupową”).
    Retry przy sqlite3.OperationalError (database is locked).
    """
    with_retry(_do_save_match_result, match_id, home_score, away_score,
               scorer_ids, winner_pen, shootout or [])


def _do_save_match_result(
    match_id: int,
    home_score: int,
    away_score: int,
    scorer_ids: list[int],
    winner_pen: int | None,
    shootout: list,
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
        winner_pen = _resolve_shootout(conn, match, home_score, away_score,
                                       winner_pen, shootout)

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
        _insert_shootout(conn, match_id, shootout)

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


def group_stage_status(tournament_id: int) -> tuple[int, int]:
    """Zwraca (rozegrane, wszystkie) mecze fazy grupowej turnieju."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(played), 0) AS played, COUNT(*) AS total
               FROM match WHERE tournament_id = ? AND stage = 'GROUP'""",
            (tournament_id,)
        ).fetchone()
    return row["played"], row["total"]


def confirm_group_stage(tournament_id: int) -> None:
    """
    Zatwierdza fazę grupową: tworzy drabinki KO i przestawia turniej na KO.
    Od tej chwili wyniki grupowe są zablokowane (patrz can_edit_match).
    Wymaga stanu GROUP i kompletu rozegranych meczów grupowych.
    Retry przy sqlite3.OperationalError (database is locked).
    """
    with_retry(_do_confirm_group_stage, tournament_id)


def _do_confirm_group_stage(tournament_id: int) -> None:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        state = conn.execute(
            "SELECT state FROM tournament WHERE id = ?", (tournament_id,)
        ).fetchone()
        if state is None:
            raise ValueError(f"Turniej {tournament_id} nie istnieje.")
        if state["state"] != "GROUP":
            raise ValueError("Zatwierdzić można tylko turniej w fazie grupowej.")

        row = conn.execute(
            """SELECT COUNT(*) AS total, COALESCE(SUM(played), 0) AS played
               FROM match WHERE tournament_id = ? AND stage = 'GROUP'""",
            (tournament_id,)
        ).fetchone()
        if row["total"] == 0:
            raise ValueError("Najpierw wygeneruj terminarz fazy grupowej.")
        if row["played"] < row["total"]:
            raise ValueError(
                f"Wpisz wszystkie wyniki fazy grupowej "
                f"(rozegrano {row['played']} z {row['total']} meczów).")

        seed_brackets(tournament_id, conn)
        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def can_edit_match(match_id: int) -> tuple[bool, str]:
    """Czy wynik rozegranego meczu można jeszcze edytować.
    Zwraca (True, "") albo (False, powód).

    Reguły:
      - mecz grupowy: edytowalny dopóki turniej jest w fazie GROUP
        (po zatwierdzeniu fazy grupowej drabinki są rozstawione i wyniki grup się blokują);
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
                return False, ("Faza grupowa została zatwierdzona — wyniki grup są zablokowane. "
                               "Aby je zmienić, zresetuj turniej.")
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
    shootout: list[tuple[int, bool]] | None = None,
) -> None:
    """Edytuje wynik już rozegranego meczu (transakcja).
    Usuwa poprzednich strzelców i serię karnych, zapisuje nowy wynik i nowych strzelców.
    Dla półfinału KO ponownie propaguje zwycięzcę/przegranego do meczów zależnych.
    Retry przy sqlite3.OperationalError (database is locked).
    """
    with_retry(_do_edit_match_result, match_id, home_score, away_score,
               scorer_ids, winner_pen, shootout or [])


def _do_edit_match_result(
    match_id: int,
    home_score: int,
    away_score: int,
    scorer_ids: list[int],
    winner_pen: int | None,
    shootout: list,
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

        winner_pen = _resolve_shootout(conn, match, home_score, away_score,
                                       winner_pen, shootout)

        conn.execute("DELETE FROM goal WHERE match_id = ?", (match_id,))
        conn.execute("DELETE FROM penalty_kick WHERE match_id = ?", (match_id,))
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
        _insert_shootout(conn, match_id, shootout)

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

def get_match_details(match_id: int) -> dict | None:
    """
    Szczegóły meczu do wyświetlenia: drużyny, wynik, karne i strzelcy
    rozdzieleni na gospodarzy i gości ({"name", "goals"}, posortowani malejąco),
    oraz seria karnych ("shootout", "home_pens", "away_pens").

    Strona strzelca: jego obecna drużyna, a jeśli od tamtej pory przeszedł
    transferem gdzie indziej — drużyna meczu, z której odszedł.
    """
    with get_connection() as conn:
        m = conn.execute(
            """SELECT m.*, ht.name AS home_team_name, at.name AS away_team_name
               FROM match m
               LEFT JOIN team ht ON ht.id = m.home_team_id
               LEFT JOIN team at ON at.id = m.away_team_id
               WHERE m.id = ?""",
            (match_id,)
        ).fetchone()
        if m is None:
            return None
        rows = conn.execute(
            """SELECT p.id, p.name, p.team_id, COUNT(*) AS goals,
                      (SELECT tr.from_team_id FROM transfer tr
                        WHERE tr.player_id = p.id AND tr.from_team_id IN (?, ?)
                        ORDER BY tr.id LIMIT 1) AS former_team_id
               FROM goal g JOIN player p ON p.id = g.scorer_id
               WHERE g.match_id = ?
               GROUP BY p.id
               ORDER BY goals DESC, p.name""",
            (m["home_team_id"], m["away_team_id"], match_id)
        ).fetchall()
        kicks = conn.execute(
            """SELECT pk.kick_no, pk.scored, p.name, p.team_id
               FROM penalty_kick pk JOIN player p ON p.id = pk.player_id
               WHERE pk.match_id = ? ORDER BY pk.kick_no""",
            (match_id,)
        ).fetchall()

    details = dict(m)
    details["home_scorers"], details["away_scorers"] = [], []
    for r in rows:
        team = r["team_id"] if r["team_id"] in (m["home_team_id"], m["away_team_id"]) \
            else r["former_team_id"]
        side = "home_scorers" if team == m["home_team_id"] else "away_scorers"
        details[side].append({"name": r["name"], "goals": r["goals"]})

    # Seria karnych: transfery są zablokowane od startu KO, więc obecna
    # drużyna wykonawcy to drużyna z meczu.
    details["shootout"] = [
        {"kick_no": k["kick_no"], "name": k["name"], "scored": bool(k["scored"]),
         "home": k["team_id"] == m["home_team_id"]}
        for k in kicks]
    details["home_pens"] = sum(k["scored"] for k in details["shootout"] if k["home"])
    details["away_pens"] = sum(k["scored"] for k in details["shootout"] if not k["home"])
    return details


def get_match_shootout(match_id: int) -> list[tuple[int, bool]]:
    """Przebieg serii karnych [(player_id, scored), ...] w kolejności strzałów."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT player_id, scored FROM penalty_kick WHERE match_id = ? ORDER BY kick_no",
            (match_id,)
        ).fetchall()
    return [(r["player_id"], bool(r["scored"])) for r in rows]