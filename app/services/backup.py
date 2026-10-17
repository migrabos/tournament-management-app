"""
Eksport i import pojedynczego turnieju do pliku JSON.

Eksport zapisuje komplet danych turnieju: drużyny, zawodników, mecze, strzelców,
serie rzutów karnych, transfery i stan. Import zawsze tworzy NOWY turniej (nic nie nadpisuje),
nadając rekordom nowe ID — dzięki temu plik da się wczytać w dowolnej bazie,
np. u znajomego.
"""
import json
import pathlib
import sqlite3
import sys
from datetime import datetime

from db.init import get_connection, with_retry

FORMAT = "tournament-manager"
VERSION = 1
IMPORT_SUFFIX = " (import)"

# Domyślny folder na eksporty: obok pliku .exe albo w katalogu głównym projektu
# (przy uruchomieniu `python main.py`). W repo jest ignorowany przez .gitignore.
if getattr(sys, "frozen", False) or "__compiled__" in globals():   # PyInstaller / Nuitka
    APP_DIR = pathlib.Path(sys.argv[0]).resolve().parent
else:
    APP_DIR = pathlib.Path(__file__).resolve().parents[2]
EXPORTS_DIR = APP_DIR / "exports"


def exports_dir() -> pathlib.Path:
    """Zwraca folder eksportów, tworząc go w razie potrzeby."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORTS_DIR


def tournaments_dir() -> pathlib.Path:
    """Folder plików eksportu/importu turniejów: exports/turnieje/ (tworzony w razie potrzeby)."""
    path = exports_dir() / "turnieje"
    path.mkdir(parents=True, exist_ok=True)
    return path


def graphics_dir(tournament_folder: str) -> pathlib.Path:
    """Folder grafik danego turnieju: exports/grafiki/<turniej>/ (tworzony w razie potrzeby)."""
    path = exports_dir() / "grafiki" / tournament_folder
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------- eksport

def export_tournament(tournament_id: int) -> dict:
    """Zwraca turniej jako słownik gotowy do zapisania w JSON."""
    with get_connection() as conn:
        t = conn.execute(
            "SELECT name, state, created_at FROM tournament WHERE id = ?", (tournament_id,)
        ).fetchone()
        if t is None:
            raise ValueError(f"Turniej {tournament_id} nie istnieje.")

        def rows(sql):
            return [dict(r) for r in conn.execute(sql, (tournament_id,)).fetchall()]

        return {
            "format": FORMAT,
            "version": VERSION,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
            "tournament": dict(t),
            "teams": rows(
                "SELECT id, name, group_name FROM team WHERE tournament_id = ? ORDER BY id"),
            "players": rows(
                """SELECT p.id, p.team_id, p.name FROM player p
                   JOIN team t ON t.id = p.team_id
                   WHERE t.tournament_id = ? ORDER BY p.id"""),
            "matches": rows(
                """SELECT id, stage, group_name, round, home_team_id, away_team_id,
                          home_score, away_score, winner_pen, played, scheduled_at
                   FROM match WHERE tournament_id = ? ORDER BY id"""),
            "goals": rows(
                """SELECT g.match_id, g.scorer_id FROM goal g
                   JOIN match m ON m.id = g.match_id
                   WHERE m.tournament_id = ? ORDER BY g.id"""),
            "penalty_kicks": rows(
                """SELECT pk.match_id, pk.kick_no, pk.player_id, pk.scored
                   FROM penalty_kick pk JOIN match m ON m.id = pk.match_id
                   WHERE m.tournament_id = ? ORDER BY pk.match_id, pk.kick_no"""),
            "transfers": rows(
                """SELECT player_id, from_team_id, to_team_id, transferred_at
                   FROM transfer WHERE tournament_id = ? ORDER BY id"""),
        }


def export_to_file(tournament_id: int, path) -> None:
    data = export_tournament(tournament_id)
    pathlib.Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- import

def import_from_file(path) -> int:
    """Wczytuje plik JSON i tworzy z niego nowy turniej. Zwraca jego id."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"Nie udało się odczytać pliku: {e}") from e
    return import_tournament(data)


def import_tournament(data: dict) -> int:
    """Tworzy nowy turniej z danych eksportu. Zwraca jego id.
    Wszystko w jednej transakcji — przy błędzie nic nie zostaje w bazie."""
    _validate(data)
    return with_retry(_do_import, data)


def _validate(data) -> None:
    """Sprawdza strukturę pliku i spójność odwołań, zanim cokolwiek trafi do bazy."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("To nie jest plik eksportu turnieju.")
    if data.get("version") != VERSION:
        raise ValueError(
            f"Nieobsługiwana wersja pliku ({data.get('version')}). "
            f"Ta wersja aplikacji obsługuje wersję {VERSION}.")
    try:
        name = data["tournament"]["name"]
        state = data["tournament"]["state"]
        teams = {t["id"] for t in data["teams"]}
        players = {p["id"]: p["team_id"] for p in data["players"]}
        matches = {m["id"]: m for m in data["matches"]}
        goals = [(g["match_id"], g["scorer_id"]) for g in data["goals"]]
        # Brak sekcji = plik sprzed dodania serii karnych.
        kicks = [(k["match_id"], k["player_id"]) for k in data.get("penalty_kicks", [])]
        transfers = [(t["player_id"], t["from_team_id"], t["to_team_id"])
                     for t in data["transfers"]]
    except (KeyError, TypeError) as e:
        raise ValueError(f"Plik jest uszkodzony lub niekompletny (brak pola {e}).") from e

    if not isinstance(name, str) or not name.strip():
        raise ValueError("Plik nie zawiera nazwy turnieju.")
    if state not in ("SETUP", "GROUP", "KO", "FINISHED"):
        raise ValueError(f"Nieznany stan turnieju: {state}.")
    if any(team_id not in teams for team_id in players.values()):
        raise ValueError("Zawodnik należy do drużyny, której nie ma w pliku.")
    for m in matches.values():
        for side in ("home_team_id", "away_team_id"):
            if m[side] is not None and m[side] not in teams:
                raise ValueError("Mecz odwołuje się do drużyny, której nie ma w pliku.")

    # Gole: weryfikujemy sami (zamiast triggera trg_goal_scorer_valid — patrz _do_import).
    per_match: dict[int, int] = {}
    for match_id, scorer_id in goals:
        m = matches.get(match_id)
        if m is None or scorer_id not in players:
            raise ValueError("Gol odwołuje się do nieistniejącego meczu lub zawodnika.")
        if not m["played"]:
            raise ValueError("Gol przypisany do nierozegranego meczu.")
        per_match[match_id] = per_match.get(match_id, 0) + 1
    for m in matches.values():
        if m["played"] and per_match.get(m["id"], 0) != m["home_score"] + m["away_score"]:
            raise ValueError("Liczba strzelców nie zgadza się z wynikiem meczu.")

    for match_id, player_id in kicks:
        m = matches.get(match_id)
        if m is None or player_id not in players:
            raise ValueError("Rzut karny odwołuje się do nieistniejącego meczu lub zawodnika.")
        if m["winner_pen"] is None:
            raise ValueError("Rzut karny przypisany do meczu bez serii karnych.")

    for player_id, from_team, to_team in transfers:
        if player_id not in players or from_team not in teams or to_team not in teams:
            raise ValueError("Transfer odwołuje się do nieistniejącego zawodnika lub drużyny.")


def _unique_name(conn, base: str) -> str:
    existing = {r["name"] for r in conn.execute("SELECT name FROM tournament")}
    name = base + IMPORT_SUFFIX
    n = 2
    while name in existing:
        name = f"{base}{IMPORT_SUFFIX[:-1]} {n})"
        n += 1
    return name


def _do_import(data: dict) -> int:
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")

        name = _unique_name(conn, data["tournament"]["name"].strip())
        tid = conn.execute(
            "INSERT INTO tournament (name, state) VALUES (?, ?)",
            (name, data["tournament"]["state"])
        ).lastrowid

        team_map = {}
        for t in data["teams"]:
            team_map[t["id"]] = conn.execute(
                "INSERT INTO team (tournament_id, name, group_name) VALUES (?, ?, ?)",
                (tid, t["name"], t["group_name"])
            ).lastrowid

        player_map = {}
        for p in data["players"]:
            player_map[p["id"]] = conn.execute(
                "INSERT INTO player (team_id, name) VALUES (?, ?)",
                (team_map[p["team_id"]], p["name"])
            ).lastrowid

        match_map = {}
        for m in data["matches"]:
            match_map[m["id"]] = conn.execute(
                """INSERT INTO match (tournament_id, stage, group_name, round,
                       home_team_id, away_team_id, home_score, away_score,
                       winner_pen, played, scheduled_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, m["stage"], m["group_name"], m["round"],
                 team_map.get(m["home_team_id"]), team_map.get(m["away_team_id"]),
                 m["home_score"], m["away_score"], m["winner_pen"], m["played"],
                 m.get("scheduled_at"))   # brak w plikach sprzed wprowadzenia terminów
            ).lastrowid

        # Trigger trg_goal_scorer_valid sprawdza, czy strzelec gra TERAZ w jednej
        # z drużyn meczu. Zawodnik przeniesiony po strzeleniu gola miałby więc
        # odrzucony poprawny, historyczny gol. Na czas wstawiania goli trigger jest
        # zdejmowany i od razu przywracany — w tej samej transakcji (DDL w SQLite jest
        # transakcyjny), a spójność goli sprawdza wcześniej _validate().
        trigger_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'trg_goal_scorer_valid'"
        ).fetchone()
        if trigger_sql:
            conn.execute("DROP TRIGGER trg_goal_scorer_valid")
        conn.executemany(
            "INSERT INTO goal (match_id, scorer_id) VALUES (?, ?)",
            [(match_map[g["match_id"]], player_map[g["scorer_id"]]) for g in data["goals"]]
        )
        if trigger_sql:
            conn.execute(trigger_sql["sql"])

        # Transfery są zablokowane od startu KO, więc wykonawcy karnych wciąż grają
        # w drużynach meczu — trigger trg_penalty_kick_valid może zostać.
        conn.executemany(
            "INSERT INTO penalty_kick (match_id, kick_no, player_id, scored) VALUES (?, ?, ?, ?)",
            [(match_map[k["match_id"]], k["kick_no"], player_map[k["player_id"]], k["scored"])
             for k in data.get("penalty_kicks", [])]
        )

        conn.executemany(
            """INSERT INTO transfer (tournament_id, player_id, from_team_id, to_team_id,
                                     transferred_at)
               VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))""",
            [(tid, player_map[t["player_id"]], team_map[t["from_team_id"]],
              team_map[t["to_team_id"]], t["transferred_at"]) for t in data["transfers"]]
        )

        conn.commit()
        return tid

    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise ValueError(f"Dane w pliku są niespójne: {e}") from e
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()