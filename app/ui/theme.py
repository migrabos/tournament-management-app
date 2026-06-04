"""Motyw aplikacji — palety jasna/ciemna i arkusz stylów (QSS)."""

LIGHT = {
    "bg": "#f4f6f8",
    "surface": "#ffffff",
    "border": "#e6e8ec",
    "text": "#1f2937",
    "muted": "#6b7280",
    "accent": "#1f9d63",
    "accent_hover": "#18814f",
    "accent_pressed": "#136b40",
    "accent_soft": "#e7f5ee",
    "accent_text": "#15803d",
    "accent_dis_bg": "#b8d8c7",
    "accent_dis_text": "#eef6f1",
    "danger": "#dc2626",
    "danger_soft": "#fdecec",
    "danger_border": "#f0c2c2",
    "header_bg": "#f9fafb",
    "row_alt": "#fafbfc",
    "grid": "#f0f1f3",
    "input_border": "#d7dbe0",
    "btn_hover": "#f3f4f6",
    "btn_pressed": "#e9ebee",
    "disabled_bg": "#f5f6f8",
    "disabled_text": "#aab0b8",
    "scroll": "#cdd2d8",
    "scroll_hover": "#b3b9c1",
    "empty_title": "#9aa1aa",
}

DARK = {
    "bg": "#1b1d23",
    "surface": "#23262e",
    "border": "#343842",
    "text": "#e6e8ec",
    "muted": "#9aa0ab",
    "accent": "#29b173",
    "accent_hover": "#34c081",
    "accent_pressed": "#1f9560",
    "accent_soft": "#1e3a2c",
    "accent_text": "#5fd39b",
    "accent_dis_bg": "#2c4738",
    "accent_dis_text": "#7fa893",
    "danger": "#f06b6b",
    "danger_soft": "#3a2526",
    "danger_border": "#5a3636",
    "header_bg": "#2a2e37",
    "row_alt": "#262932",
    "grid": "#2f333d",
    "input_border": "#3a3f4a",
    "btn_hover": "#2c303a",
    "btn_pressed": "#333845",
    "disabled_bg": "#24262d",
    "disabled_text": "#5f6672",
    "scroll": "#3c4150",
    "scroll_hover": "#4a505f",
    "empty_title": "#6b7280",
}

STATE_BADGE_LIGHT = {
    "SETUP":    ("#eef2ff", "#4f46e5"),
    "GROUP":    ("#e7f5ee", "#15803d"),
    "KO":       ("#fef3e2", "#b45309"),
    "FINISHED": ("#f1f5f9", "#475569"),
}
STATE_BADGE_DARK = {
    "SETUP":    ("#2a2c44", "#a5b4fc"),
    "GROUP":    ("#1e3a2c", "#5fd39b"),
    "KO":       ("#3a2f1c", "#e0a96d"),
    "FINISHED": ("#2a2e37", "#9aa0ab"),
}

STATE_LABELS = {
    "SETUP": "Konfiguracja",
    "GROUP": "Faza grupowa",
    "KO": "Faza pucharowa",
    "FINISHED": "Zakończony",
}

STAGE_LABELS = {
    "SF_TOP": "Półfinał (1-4)", "FINAL_TOP": "Finał (1. miejsce)", "THIRD_PLACE": "Mecz o 3. miejsce",
    "SF_MID": "Półfinał (5-8)", "FINAL_MID": "Finał (5. miejsce)", "SEVENTH_PLACE": "Mecz o 7. miejsce",
    "SF_BOT": "Półfinał (9-12)", "FINAL_BOT": "Finał (9. miejsce)", "ELEVENTH_PLACE": "Mecz o 11. miejsce",
}
BRACKETS = [
    ("Drabinka o miejsca 1-4", ["SF_TOP", "FINAL_TOP", "THIRD_PLACE"]),
    ("Drabinka o miejsca 5-8", ["SF_MID", "FINAL_MID", "SEVENTH_PLACE"]),
    ("Drabinka o miejsca 9-12", ["SF_BOT", "FINAL_BOT", "ELEVENTH_PLACE"]),
]

# ----- aktualny tryb -----
_MODE = "light"


def current_mode() -> str:
    return _MODE


def set_mode(mode: str) -> None:
    global _MODE
    _MODE = "dark" if mode == "dark" else "light"


def toggle_mode() -> str:
    set_mode("light" if _MODE == "dark" else "dark")
    return _MODE


def _colors() -> dict:
    return DARK if _MODE == "dark" else LIGHT


def badge_colors(state: str) -> tuple[str, str]:
    table = STATE_BADGE_DARK if _MODE == "dark" else STATE_BADGE_LIGHT
    return table.get(state, ("#f1f5f9", "#475569"))


def stylesheet() -> str:
    c = _colors()
    return f"""
    * {{
        font-family: "Segoe UI", "Inter", sans-serif;
        font-size: 10pt;
        color: {c['text']};
    }}
    QMainWindow, QDialog, QWidget#root {{ background: {c['bg']}; }}
    QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; }}

    QLabel#h1 {{ font-size: 19pt; font-weight: 600; }}
    QLabel#h2 {{ font-size: 13pt; font-weight: 600; }}
    QLabel#muted {{ color: {c['muted']}; }}

    QFrame#card {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 12px;
    }}

    /* Przyciski */
    QPushButton {{
        background: {c['surface']};
        border: 1px solid {c['input_border']};
        border-radius: 8px;
        padding: 8px 16px;
        color: {c['text']};
    }}
    QPushButton:hover {{ background: {c['btn_hover']}; }}
    QPushButton:pressed {{ background: {c['btn_pressed']}; }}
    QPushButton:disabled {{ color: {c['disabled_text']}; background: {c['disabled_bg']}; border-color: {c['border']}; }}

    QPushButton[accent="true"] {{
        background: {c['accent']}; border: none; color: #ffffff; font-weight: 600;
    }}
    QPushButton[accent="true"]:hover {{ background: {c['accent_hover']}; }}
    QPushButton[accent="true"]:pressed {{ background: {c['accent_pressed']}; }}
    QPushButton[accent="true"]:disabled {{ background: {c['accent_dis_bg']}; color: {c['accent_dis_text']}; }}

    QPushButton[danger="true"] {{ color: {c['danger']}; border-color: {c['danger_border']}; }}
    QPushButton[danger="true"]:hover {{ background: {c['danger_soft']}; }}

    /* Pola wejściowe */
    QLineEdit, QComboBox, QSpinBox {{
        background: {c['surface']};
        border: 1px solid {c['input_border']};
        border-radius: 8px;
        padding: 6px 10px;
        min-height: 18px;
        selection-background-color: {c['accent_soft']};
        selection-color: {c['text']};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {c['surface']}; border: 1px solid {c['border']};
        border-radius: 8px; selection-background-color: {c['accent_soft']};
        selection-color: {c['text']}; outline: none; padding: 4px;
    }}

    /* Stepper [ − n + ] — jedna pigułka z obramowaniem */
    QFrame#stepper {{
        border: 1px solid {c['input_border']};
        border-radius: 8px;
        background: {c['surface']};
    }}
    QFrame#stepper QPushButton {{
        background: {c['header_bg']};
        border: none;
        font-size: 15pt; font-weight: 600; color: {c['muted']};
        padding: 0;
    }}
    QFrame#stepper QPushButton#stepMinus {{
        border-right: 1px solid {c['border']};
        border-top-left-radius: 7px; border-bottom-left-radius: 7px;
    }}
    QFrame#stepper QPushButton#stepPlus {{
        border-left: 1px solid {c['border']};
        border-top-right-radius: 7px; border-bottom-right-radius: 7px;
    }}
    QFrame#stepper QPushButton:hover {{ background: {c['btn_hover']}; color: {c['text']}; }}
    QFrame#stepper QPushButton:pressed {{ background: {c['btn_pressed']}; }}
    QLabel#stepValue {{
        background: transparent; font-weight: 600; font-size: 11pt; color: {c['text']};
    }}

    /* Tabele i drzewa */
    QTableWidget, QTreeWidget {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        gridline-color: {c['grid']};
        selection-background-color: {c['accent_soft']};
        selection-color: {c['text']};
        outline: none;
        alternate-background-color: {c['row_alt']};
    }}
    QTableWidget::item, QTreeWidget::item {{ padding: 7px 6px; border: none; }}
    QTableWidget::item:selected, QTreeWidget::item:selected {{
        background: {c['accent_soft']}; color: {c['text']};
    }}
    QHeaderView::section {{
        background: {c['header_bg']};
        border: none;
        border-bottom: 1px solid {c['border']};
        padding: 9px 6px;
        font-weight: 600;
        color: {c['muted']};
    }}
    QTableCornerButton::section {{ background: {c['header_bg']}; border: none; }}

    /* Zakładki */
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: 10px;
        background: {c['surface']};
        top: -1px;
    }}
    QTabBar::tab {{
        background: transparent;
        padding: 9px 18px;
        margin-right: 2px;
        color: {c['muted']};
        border: none;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:selected {{ color: {c['accent_text']}; border-bottom: 2px solid {c['accent']}; font-weight: 600; }}
    QTabBar::tab:hover:!selected {{ color: {c['text']}; }}

    QLabel#groupTitle {{ font-size: 11pt; font-weight: 600; color: {c['text']}; }}
    QLabel#emptyTitle {{ font-size: 13pt; font-weight: 600; color: {c['empty_title']}; }}
    QFrame#sep {{ background: {c['border']}; max-height: 1px; min-height: 1px; }}

    /* Splitter — subtelny uchwyt */
    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:horizontal {{ width: 16px; }}
    QSplitter::handle:vertical {{ height: 16px; }}

    /* Paski przewijania */
    QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 5px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['scroll_hover']}; }}
    QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 5px; min-width: 28px; }}
    QScrollBar::handle:horizontal:hover {{ background: {c['scroll_hover']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    """
