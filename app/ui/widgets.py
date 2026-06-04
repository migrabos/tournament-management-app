"""Pomocnicze widżety i fabryki — spójny wygląd w całej aplikacji."""
from PySide6.QtWidgets import (
    QPushButton, QLabel, QFrame, QTableWidget, QHeaderView,
    QAbstractItemView, QVBoxLayout, QHBoxLayout,
)
from PySide6.QtCore import Qt

from app.ui.theme import STATE_LABELS, badge_colors


class Stepper(QFrame):
    """Kompaktowy licznik [ − n + ] — zamiennik QSpinBox z czystym wyglądem."""

    def __init__(self, value: int = 0, minimum: int = 0, maximum: int = 20):
        super().__init__()
        self.setObjectName("stepper")
        self._min = minimum
        self._max = maximum
        self._value = max(minimum, min(maximum, value))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._minus = QPushButton("−")
        self._minus.setObjectName("stepMinus")
        self._plus = QPushButton("+")
        self._plus.setObjectName("stepPlus")
        for b, d in ((self._minus, -1), (self._plus, +1)):
            b.setFixedSize(30, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, delta=d: self._step(delta))

        self._label = QLabel(str(self._value))
        self._label.setObjectName("stepValue")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setFixedSize(36, 30)

        lay.addWidget(self._minus)
        lay.addWidget(self._label)
        lay.addWidget(self._plus)

    def _step(self, delta: int):
        self.setValue(self._value + delta)

    def setValue(self, v: int):
        self._value = max(self._min, min(self._max, v))
        self._label.setText(str(self._value))

    def value(self) -> int:
        return self._value


def primary_button(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setProperty("accent", "true")
    b.setCursor(Qt.PointingHandCursor)
    return b


def button(text: str, danger: bool = False) -> QPushButton:
    b = QPushButton(text)
    if danger:
        b.setProperty("danger", "true")
    b.setCursor(Qt.PointingHandCursor)
    return b


def h1(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("h1")
    return lbl


def h2(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("h2")
    return lbl


def muted(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    return lbl


def status_badge(state: str) -> QLabel:
    bg, fg = badge_colors(state)
    lbl = QLabel(STATE_LABELS.get(state, state))
    lbl.setStyleSheet(
        f"background: {bg}; color: {fg}; padding: 4px 14px;"
        f"border-radius: 11px; font-weight: 600;"
    )
    return lbl


def card(*, padding: int = 16) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(padding, padding, padding, padding)
    lay.setSpacing(10)
    return frame, lay


def empty_state(title: str, hint: str = "") -> QFrame:
    """Ładny placeholder na pusty widok (np. przed losowaniem grup)."""
    frame, lay = card(padding=44)
    lay.addStretch()
    t = QLabel(title)
    t.setObjectName("emptyTitle")
    t.setAlignment(Qt.AlignCenter)
    lay.addWidget(t)
    if hint:
        h = muted(hint)
        h.setAlignment(Qt.AlignCenter)
        lay.addWidget(h)
    lay.addStretch()
    return frame


def table(headers: list[str], stretch_col: int | None = None) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setFocusPolicy(Qt.NoFocus)
    hh = t.horizontalHeader()
    hh.setHighlightSections(False)
    hh.setSectionsMovable(False)   # użytkownik nie może przestawiać kolumn
    for i in range(len(headers)):
        mode = QHeaderView.Stretch if i == stretch_col else QHeaderView.ResizeToContents
        hh.setSectionResizeMode(i, mode)
        # domyślnie nagłówki do lewej — pasują do tekstowej treści
        t.horizontalHeaderItem(i).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    if stretch_col is None:
        hh.setStretchLastSection(True)
    return t


def center_headers(tbl, cols):
    """Wyśrodkuj nagłówki wskazanych kolumn (liczbowych)."""
    for ci in cols:
        tbl.horizontalHeaderItem(ci).setTextAlignment(Qt.AlignCenter)
