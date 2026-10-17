"""Jedno okno aplikacji: stały pasek (motyw + nawigacja) i przełączane strony."""
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QTableWidgetItem, QInputDialog, QMessageBox, QHeaderView, QFileDialog,
)
from PySide6.QtCore import Qt, QSettings

from app.dao import tournament_dao
from app.services import demo, backup
from app.ui.theme import stylesheet, toggle_mode, set_mode, current_mode
from app.ui.widgets import (
    primary_button, button, h1, muted, table, status_badge, center_headers, PAGE_MARGIN_X,
)
from app.ui.tournament_window import TournamentPage

UID = Qt.UserRole

# Ustawienia użytkownika (na Windows: rejestr HKCU\Software\TournamentManager).
SETTINGS_ORG, SETTINGS_APP = "TournamentManager", "TournamentManager"
THEME_KEY = "ui/theme"


def _settings() -> QSettings:
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def _theme_btn_text(mode: str) -> str:
    return "☀  Jasny" if mode == "dark" else "🌙  Ciemny"


class ListPage(QWidget):
    """Strona listy turniejów."""

    def __init__(self, on_open):
        super().__init__()
        self.setObjectName("root")
        self.on_open = on_open

        lay = QVBoxLayout(self)
        lay.setContentsMargins(PAGE_MARGIN_X, 4, PAGE_MARGIN_X, 10)
        lay.setSpacing(6)
        lay.addWidget(h1("Turnieje"))
        lay.addWidget(muted("Wybierz turniej z listy lub utwórz nowy."))
        lay.addSpacing(10)

        self.table = table(["Nazwa", "Status", "Utworzono"], stretch_col=0)
        center_headers(self.table, [1, 2])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.setColumnWidth(1, 170)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.cellDoubleClicked.connect(lambda *_: self._open())
        lay.addWidget(self.table)

        bar = QHBoxLayout()
        b_new = primary_button("Nowy turniej")
        b_new.clicked.connect(self._create)
        b_demo = button("Przykładowy turniej")
        b_demo.setToolTip("Tworzy gotowy turniej z drużynami i częścią rozegranych meczów")
        b_demo.clicked.connect(self._create_demo)
        b_import = button("Importuj")
        b_import.setToolTip("Wczytuje turniej z pliku .json jako nowy turniej")
        b_import.clicked.connect(self._import)
        b_open = button("Otwórz")
        b_open.clicked.connect(self._open)
        b_ren = button("Zmień nazwę")
        b_ren.clicked.connect(self._rename)
        b_del = button("Usuń", danger=True)
        b_del.clicked.connect(self._delete)
        b_ref = button("Odśwież")
        b_ref.clicked.connect(self.refresh)
        bar.addWidget(b_new)
        bar.addWidget(b_demo)
        bar.addWidget(b_import)
        bar.addWidget(b_open)
        bar.addWidget(b_ren)
        bar.addWidget(b_del)
        bar.addWidget(b_ref)
        bar.addStretch()
        lay.addLayout(bar)

        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        for t in tournament_dao.list_tournaments():
            r = self.table.rowCount()
            self.table.insertRow(r)
            name_item = QTableWidgetItem(t["name"])
            name_item.setData(UID, t["id"])
            self.table.setItem(r, 0, name_item)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addStretch()
            hl.addWidget(status_badge(t["state"]))
            hl.addStretch()
            self.table.setCellWidget(r, 1, holder)
            created = QTableWidgetItem(str(t["created_at"]))
            created.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(r, 2, created)

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(UID)

    def _create(self):
        name, ok = QInputDialog.getText(self, "Nowy turniej", "Nazwa turnieju:")
        name = name.strip()
        if not ok or not name:
            return
        if tournament_dao.name_taken(name):
            if QMessageBox.question(
                    self, "Nazwa zajęta",
                    f"Turniej o nazwie „{name}” już istnieje. Utworzyć drugi o tej samej nazwie?"
            ) != QMessageBox.Yes:
                return
        tournament_dao.create_tournament(name)
        self.refresh()

    def _create_demo(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            tid = demo.create_demo_tournament()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Błąd", f"Nie udało się utworzyć turnieju:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.refresh()
        self.on_open(tid)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importuj turniej", str(backup.exports_dir()),
            "Turniej (*.json);;Wszystkie pliki (*)")
        if not path:
            return
        try:
            tid = backup.import_from_file(path)
        except Exception as e:
            QMessageBox.warning(self, "Błąd importu", f"Nie udało się zaimportować turnieju:\n{e}")
            return
        self.refresh()
        self.on_open(tid)

    def _open(self):
        tid = self._selected_id()
        if tid is None:
            QMessageBox.information(self, "Info", "Wybierz turniej z listy.")
            return
        self.on_open(tid)

    def _rename(self):
        tid = self._selected_id()
        if tid is None:
            QMessageBox.information(self, "Info", "Wybierz turniej z listy.")
            return
        current = tournament_dao.get_tournament(tid)["name"]
        name, ok = QInputDialog.getText(self, "Zmień nazwę", "Nowa nazwa turnieju:", text=current)
        name = name.strip()
        if not ok or not name or name == current:
            return
        if tournament_dao.name_taken(name, exclude_id=tid):
            if QMessageBox.question(
                    self, "Nazwa zajęta",
                    f"Turniej o nazwie „{name}” już istnieje.\n"
                    "Na liście będą dwa turnieje o tej samej nazwie. Zmienić mimo to?"
            ) != QMessageBox.Yes:
                return
        tournament_dao.rename_tournament(tid, name)
        self.refresh()

    def _delete(self):
        tid = self._selected_id()
        if tid is None:
            QMessageBox.information(self, "Info", "Wybierz turniej z listy.")
            return
        if QMessageBox.question(self, "Potwierdź",
                                "Usunąć turniej i wszystkie jego dane?") == QMessageBox.Yes:
            tournament_dao.delete_tournament(tid)
            self.refresh()


class AppWindow(QMainWindow):
    """Główne (jedyne) okno aplikacji."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Menedżer Turnieju Piłkarskiego")
        self.resize(1080, 700)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 12, 0, 12)
        outer.setSpacing(8)

        # stały górny pasek — wcięty jak treść stron, żeby przyciski były w jednej linii
        bar = QHBoxLayout()
        bar.setContentsMargins(PAGE_MARGIN_X, 0, PAGE_MARGIN_X, 0)
        self.back_btn = button("←  Lista turniejów")
        self.back_btn.clicked.connect(self._back)
        self.back_btn.setVisible(False)
        bar.addWidget(self.back_btn)
        bar.addStretch()
        self.theme_btn = button(_theme_btn_text(current_mode()))
        self.theme_btn.clicked.connect(self._toggle_theme)
        bar.addWidget(self.theme_btn)
        outer.addLayout(bar)

        # przełączane strony
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        self.list_page = ListPage(on_open=self._open_tournament)
        self.stack.addWidget(self.list_page)
        self.tournament_page = None

    def _open_tournament(self, tid):
        if self.tournament_page is not None:
            self.stack.removeWidget(self.tournament_page)
            self.tournament_page.deleteLater()
        self.tournament_page = TournamentPage(tid)
        self.stack.addWidget(self.tournament_page)
        self.stack.setCurrentWidget(self.tournament_page)
        self.back_btn.setVisible(True)

    def _back(self):
        self.stack.setCurrentWidget(self.list_page)
        self.back_btn.setVisible(False)
        self.list_page.refresh()
        if self.tournament_page is not None:
            self.stack.removeWidget(self.tournament_page)
            self.tournament_page.deleteLater()
            self.tournament_page = None

    def _toggle_theme(self):
        mode = toggle_mode()
        _settings().setValue(THEME_KEY, mode)       # zapamiętaj wybór na kolejne uruchomienia
        QApplication.instance().setStyleSheet(stylesheet())
        self.theme_btn.setText(_theme_btn_text(mode))
        self.list_page.refresh()
        if self.tournament_page is not None:
            self.tournament_page.refresh_all()


def run():
    app = QApplication.instance() or QApplication(sys.argv)
    set_mode(_settings().value(THEME_KEY, "light"))  # motyw z poprzedniej sesji
    app.setStyleSheet(stylesheet())
    win = AppWindow()
    win.showMaximized()   # start zmaksymalizowany; resize() to rozmiar po przywróceniu
    app.exec()