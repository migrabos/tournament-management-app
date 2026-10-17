import sqlite3
import pathlib
import sys
import time

if getattr(sys, "frozen", False):
    # Uruchomione jako .exe (PyInstaller)
    BUNDLE_DIR = pathlib.Path(sys._MEIPASS) / "db"       # schema.sql spakowany w exe
    DATA_DIR = pathlib.Path(sys.executable).parent       # baza obok pliku .exe
else:
    # Zwykłe uruchomienie: python main.py
    BUNDLE_DIR = DATA_DIR = pathlib.Path(__file__).parent

DB_PATH = DATA_DIR / "tournament.db"
SCHEMA_PATH = BUNDLE_DIR / "schema.sql"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def with_retry(fn, *args, max_retries=3, **kwargs):
    """Wykonuje fn z retry przy sqlite3.OperationalError (database is locked)."""
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
            else:
                raise


def init_db() -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn:
        conn.executescript(schema)
    print(f"Baza zainicjalizowana: {DB_PATH}")


if __name__ == "__main__":
    init_db()