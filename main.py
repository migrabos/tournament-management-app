"""
Punkt wejścia aplikacji.
Uruchom: python main.py
"""
from db.init import DB_PATH, init_db
from app.ui.main_window import run


def main():
    if not DB_PATH.exists():
        init_db()
    run()


if __name__ == "__main__":
    main()
