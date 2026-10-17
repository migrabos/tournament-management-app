"""Okno pojedynczego turnieju — zakładki z całą funkcjonalnością."""
# pyrefly: ignore [missing-import]
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QHeaderView,
    QInputDialog, QMessageBox, QSplitter, QFileDialog, QMenu,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

from app.dao import tournament_dao, team_dao, player_dao
from app.services import draw, schedule, match_result, reset, backup
from app.reports import reports
from app.ui.theme import STAGE_LABELS, BRACKETS
from app.ui import graphics
from app.ui.widgets import (
    primary_button, button, h1, h2, muted, status_badge, table, center_headers, empty_state,
)
from app.ui.dialogs import (
    ResultDialog, TransferDialog, MatchDetailsDialog, MatchDateDialog, format_kickoff,
)

UID = Qt.UserRole


class TournamentPage(QWidget):
    """Widok pojedynczego turnieju — strona w QStackedWidget (jedno okno aplikacji)."""

    def __init__(self, tournament_id: int):
        super().__init__()
        self.setObjectName("root")
        self.tournament_id = tournament_id
        t = tournament_dao.get_tournament(tournament_id)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 8, 22, 18)
        outer.setSpacing(14)

        # Nagłówek
        head = QHBoxLayout()
        head.addWidget(h1(t["name"]))
        head.addSpacing(12)
        self.badge_holder = QHBoxLayout()
        head.addLayout(self.badge_holder)
        head.addStretch()
        self.btn_export = button("Eksportuj")
        self.btn_export.setToolTip("Zapisuje cały turniej do pliku .json (kopia zapasowa / do wysłania).")
        self.btn_export.clicked.connect(self._do_export)
        head.addWidget(self.btn_export)
        self.btn_reset = button("Resetuj turniej", danger=True)
        self.btn_reset.setToolTip("Usuwa wyniki i grupy, wraca do losowania. Drużyny i składy zostają.")
        self.btn_reset.clicked.connect(self._do_reset)
        head.addWidget(self.btn_reset)
        outer.addLayout(head)
        self._badge = None

        # Zakładki
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)
        self._build_setup_tab()
        self._build_draw_tab()
        self._build_groups_tab()
        self._build_ko_tab()
        self._build_scorers_tab()
        self._build_transfers_tab()
        self.tabs.currentChanged.connect(lambda _: self.refresh_all())

        self.refresh_all()

    # ---------- helpers ----------
    def _state(self) -> str:
        return tournament_dao.get_state(self.tournament_id)

    def refresh_all(self):
        if self._badge is not None:
            self.badge_holder.removeWidget(self._badge)
            self._badge.deleteLater()
        self._badge = status_badge(self._state())
        self.badge_holder.addWidget(self._badge)
        self.btn_reset.setVisible(self._state() != "SETUP")
        self._refresh_teams()
        self._refresh_players()
        self._refresh_draw()
        self._refresh_groups()
        self._refresh_ko()
        self._refresh_scorers()
        self._refresh_transfers()

    @staticmethod
    def _fit_height(tbl):
        """Ustaw wysokość tabeli dokładnie na nagłówek + wszystkie wiersze (bez scrolla)."""
        h = tbl.horizontalHeader().height()
        for r in range(tbl.rowCount()):
            h += tbl.rowHeight(r)
        h += 2 * tbl.frameWidth() + 2
        tbl.setFixedHeight(h)

    @staticmethod
    def _item(text, *, center=False, align=None, uid=None) -> QTableWidgetItem:
        it = QTableWidgetItem(str(text))
        if align is not None:
            it.setTextAlignment(align)
        elif center:
            it.setTextAlignment(Qt.AlignCenter)
        if uid is not None:
            it.setData(UID, uid)
        return it

    # ---------- TAB 1: drużyny i zawodnicy ----------
    def _build_setup_tab(self):
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(14)
        split = QSplitter(Qt.Horizontal)

        # lewa: drużyny
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.teams_info = h2("Drużyny")
        ll.addWidget(self.teams_info)
        self.teams_table = table(["Drużyna", "Grupa"], stretch_col=0)
        center_headers(self.teams_table, [1])
        self.teams_table.itemSelectionChanged.connect(self._refresh_players)
        ll.addWidget(self.teams_table)
        tb = QHBoxLayout()
        b_add = primary_button("Dodaj")
        b_add.clicked.connect(self._add_team)
        b_ren = button("Zmień nazwę")
        b_ren.clicked.connect(self._rename_team)
        b_del = button("Usuń", danger=True)
        b_del.clicked.connect(self._delete_team)
        for b in (b_add, b_ren, b_del):
            tb.addWidget(b)
        tb.addStretch()
        ll.addLayout(tb)

        # prawa: zawodnicy
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(h2("Zawodnicy"))
        self.players_table = table(["Zawodnik"], stretch_col=0)
        rl.addWidget(self.players_table)
        pb = QHBoxLayout()
        p_add = primary_button("Dodaj zawodnika")
        p_add.clicked.connect(self._add_player)
        p_del = button("Usuń", danger=True)
        p_del.clicked.connect(self._delete_player)
        pb.addWidget(p_add)
        pb.addWidget(p_del)
        pb.addStretch()
        rl.addLayout(pb)

        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([520, 480])
        lay.addWidget(split)
        self.tabs.addTab(page, "Drużyny i zawodnicy")

    def _selected_team_id(self):
        row = self.teams_table.currentRow()
        if row < 0:
            return None
        return self.teams_table.item(row, 0).data(UID)

    def _refresh_teams(self):
        teams = team_dao.list_teams(self.tournament_id)
        self.teams_table.setRowCount(0)
        for t in teams:
            r = self.teams_table.rowCount()
            self.teams_table.insertRow(r)
            self.teams_table.setItem(r, 0, self._item(t["name"], uid=t["id"]))
            self.teams_table.setItem(r, 1, self._item(t["group_name"] or "—", center=True))
        self.teams_info.setText(f"Drużyny · {len(teams)}/12")

    def _refresh_players(self):
        self.players_table.setRowCount(0)
        tid = self._selected_team_id()
        if tid is None:
            return
        for p in player_dao.list_players(tid):
            r = self.players_table.rowCount()
            self.players_table.insertRow(r)
            self.players_table.setItem(r, 0, self._item(p["name"], uid=p["id"]))

    def _add_team(self):
        if self._state() != "SETUP":
            QMessageBox.information(self, "Info", "Drużyny dodajesz tylko w fazie konfiguracji.")
            return
        if team_dao.count_teams(self.tournament_id) >= 12:
            QMessageBox.information(self, "Info", "Turniej ma już 12 drużyn.")
            return
        name, ok = QInputDialog.getText(self, "Nowa drużyna", "Nazwa drużyny:")
        if ok and name.strip():
            try:
                team_dao.add_team(self.tournament_id, name.strip())
            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))
            self.refresh_all()

    def _rename_team(self):
        tid = self._selected_team_id()
        if tid is None:
            return
        name, ok = QInputDialog.getText(self, "Zmień nazwę", "Nowa nazwa:")
        if ok and name.strip():
            team_dao.rename_team(tid, name.strip())
            self.refresh_all()

    def _delete_team(self):
        tid = self._selected_team_id()
        if tid is None:
            return
        if self._state() != "SETUP":
            QMessageBox.information(self, "Info", "Drużyny usuwasz tylko w fazie konfiguracji.")
            return
        if QMessageBox.question(self, "Potwierdź", "Usunąć drużynę i jej zawodników?") == QMessageBox.Yes:
            team_dao.delete_team(tid)
            self.refresh_all()

    def _add_player(self):
        tid = self._selected_team_id()
        if tid is None:
            QMessageBox.information(self, "Info", "Wybierz najpierw drużynę.")
            return
        name, ok = QInputDialog.getText(self, "Nowy zawodnik", "Imię i nazwisko:")
        if ok and name.strip():
            try:
                player_dao.add_player(tid, name.strip())
            except Exception as e:
                QMessageBox.critical(self, "Błąd", str(e))
            self._refresh_players()

    def _delete_player(self):
        row = self.players_table.currentRow()
        if row < 0:
            return
        pid = self.players_table.item(row, 0).data(UID)
        player_dao.delete_player(pid)
        self._refresh_players()

    def _safe_name(self) -> str:
        name = tournament_dao.get_tournament(self.tournament_id)["name"]
        safe = "".join(c if c.isalnum() or c in " -_()" else "_" for c in name).strip()
        return safe or "turniej"

    def _do_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Eksportuj turniej",
            str(backup.exports_dir() / f"{self._safe_name()}.json"), "Turniej (*.json)")
        if not path:
            return
        try:
            backup.export_to_file(self.tournament_id, path)
        except Exception as e:
            QMessageBox.critical(self, "Błąd eksportu", str(e))
            return
        QMessageBox.information(self, "Eksport", f"Zapisano turniej do pliku:\n{path}")

    def _do_reset(self):
        answer = QMessageBox.warning(
            self, "Resetuj turniej",
            "Usunąć wszystkie wyniki, strzelców, grupy i historię transferów\n"
            "i wrócić do losowania?\n\n"
            "Drużyny i zawodnicy zostaną. Tej operacji nie da się cofnąć.",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            reset.reset_to_setup(self.tournament_id)
        except Exception as e:
            QMessageBox.critical(self, "Błąd", str(e))
            return
        self.refresh_all()
        self.tabs.setCurrentIndex(1)  # zakładka „Losowanie”

    # ---------- TAB 2: losowanie ----------
    def _build_draw_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(14)

        bar = QHBoxLayout()
        self.btn_draw = primary_button("Losuj grupy")
        self.btn_draw.clicked.connect(self._do_draw)
        self.btn_sched = button("Generuj terminarz")
        self.btn_sched.clicked.connect(self._do_schedule)
        bar.addWidget(self.btn_draw)
        bar.addWidget(self.btn_sched)
        bar.addStretch()
        lay.addLayout(bar)

        self.groups_box = QHBoxLayout()
        self.groups_box.setSpacing(14)
        lay.addLayout(self.groups_box)
        lay.addStretch()
        self.tabs.addTab(page, "Losowanie")

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _refresh_draw(self):
        self._clear_layout(self.groups_box)
        groups = draw.get_groups(self.tournament_id)
        for gname in ("A", "B"):
            from app.ui.widgets import card
            frame, cl = card()
            title = QLabel(f"Grupa {gname}")
            title.setObjectName("groupTitle")
            cl.addWidget(title)
            names = groups[gname]
            if not names:
                cl.addWidget(muted("(przed losowaniem)"))
            for n in names:
                cl.addWidget(QLabel(n))
            cl.addStretch()
            self.groups_box.addWidget(frame)

    def _do_draw(self):
        try:
            draw.draw_groups(self.tournament_id)
        except Exception as e:
            QMessageBox.critical(self, "Błąd losowania", str(e))
            return
        self.refresh_all()

    def _do_schedule(self):
        try:
            schedule.generate_group_schedule(self.tournament_id)
        except Exception as e:
            QMessageBox.critical(self, "Błąd", str(e))
            return
        QMessageBox.information(self, "Sukces", "Wygenerowano terminarz fazy grupowej.")
        self.refresh_all()

    # ---------- TAB 3: grupy ----------
    def _build_groups_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        # placeholder przed losowaniem
        self.groups_empty = empty_state(
            "Grupy nie zostały jeszcze wylosowane",
            "Przejdź do zakładki 'Losowanie', aby wylosować grupy i wygenerować terminarz.")
        lay.addWidget(self.groups_empty)

        # właściwa zawartość — dwie kolumny: Grupa A | Grupa B
        self.groups_content = QWidget()
        cl = QVBoxLayout(self.groups_content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(muted("Dwuklik meczu: wpisanie wyniku lub szczegóły z listą strzelców. Prawy przycisk: ustawienie terminu."))
        top.addStretch()
        self.group_progress = muted("")
        top.addWidget(self.group_progress)
        btn_round_img = button("Grafika kolejki")
        btn_round_img.setToolTip("Eksport PNG z wynikami kolejki i tabelami grup (np. na Facebooka).")
        btn_round_img.clicked.connect(self._export_round_graphic)
        top.addWidget(btn_round_img)
        btn_group_img = button("Grafika kolejki grupy")
        btn_group_img.setToolTip("Eksport PNG: mecze jednej grupy w kolejce z wynikami i strzelcami.")
        btn_group_img.clicked.connect(self._export_group_round_graphic)
        top.addWidget(btn_group_img)
        self.btn_confirm_groups = primary_button("Zatwierdź fazę grupową")
        self.btn_confirm_groups.setToolTip(
            "Tworzy drabinki KO. Po zatwierdzeniu wyniki grup są zablokowane.")
        self.btn_confirm_groups.clicked.connect(self._confirm_groups)
        top.addWidget(self.btn_confirm_groups)
        cl.addLayout(top)

        cols_row = QHBoxLayout()
        cols_row.setSpacing(16)
        self.group_tables = {}
        self.group_fixtures = {}
        std_cols = ["Drużyna", "M", "W", "R", "P", "BZ", "BS", "+/-", "Pkt"]
        for gname in ("A", "B"):
            box = QVBoxLayout()
            box.setSpacing(8)
            title = QLabel(f"Grupa {gname}")
            title.setObjectName("groupTitle")
            box.addWidget(title)

            tv = table(std_cols, stretch_col=0)
            center_headers(tv, range(1, 9))
            tv.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.group_tables[gname] = tv
            box.addWidget(tv)

            box.addWidget(muted("Terminarz"))
            fx = table(["Kolejka", "Gospodarze", "Wynik", "Goście", "Termin"], stretch_col=1)
            fx.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
            center_headers(fx, [0, 2, 4])
            fx.horizontalHeaderItem(1).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            fx.horizontalHeaderItem(3).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            fx.cellDoubleClicked.connect(
                lambda r, _c, t=fx: self._open_match(t.item(r, 0).data(UID)))
            fx.setContextMenuPolicy(Qt.CustomContextMenu)
            fx.customContextMenuRequested.connect(
                lambda pos, t=fx: self._match_menu(
                    t, pos, t.item(t.rowAt(pos.y()), 0).data(UID) if t.rowAt(pos.y()) >= 0 else None))
            self.group_fixtures[gname] = fx
            box.addWidget(fx)

            wrap = QWidget()
            wrap.setLayout(box)
            cols_row.addWidget(wrap)
        cl.addLayout(cols_row)

        lay.addWidget(self.groups_content)
        self.tabs.addTab(page, "Grupy")

    def _refresh_groups(self):
        drawn = self._state() != "SETUP"
        self.groups_empty.setVisible(not drawn)
        self.groups_content.setVisible(drawn)
        if not drawn:
            return

        state = self._state()
        played, total = match_result.group_stage_status(self.tournament_id)
        in_group = state == "GROUP"
        self.btn_confirm_groups.setVisible(in_group)
        self.btn_confirm_groups.setEnabled(in_group and total > 0 and played == total)
        if not in_group:
            self.group_progress.setText("Faza grupowa zatwierdzona ✓")
        elif total == 0:
            self.group_progress.setText("Wygeneruj terminarz w zakładce „Losowanie”")
        else:
            self.group_progress.setText(f"Rozegrano {played} z {total} meczów")

        for gname, tv in self.group_tables.items():
            tv.setRowCount(0)
            for row in reports.group_table(self.tournament_id, gname):
                r = tv.rowCount()
                tv.insertRow(r)
                vals = [row["team_name"], row["played"], row["wins"], row["draws"],
                        row["losses"], row["goals_for"], row["goals_against"],
                        row["goal_diff"], row["points"]]
                tv.setItem(r, 0, self._item(vals[0]))
                for i in range(1, 9):
                    tv.setItem(r, i, self._item(vals[i], center=True))
            self._fit_height(tv)

        for tbl in self.group_fixtures.values():
            tbl.setRowCount(0)
        for fx in schedule.get_schedule(self.tournament_id):
            if fx["stage"] != "GROUP":
                continue
            tbl = self.group_fixtures[fx["group_name"]]
            score = f"{fx['home_score']} : {fx['away_score']}" if fx["played"] else "–  :  –"
            r = tbl.rowCount()
            tbl.insertRow(r)
            tbl.setItem(r, 0, self._item(fx["round"], center=True, uid=fx["match_id"]))
            tbl.setItem(r, 1, self._item(fx["home_team_name"], align=Qt.AlignRight | Qt.AlignVCenter))
            tbl.setItem(r, 2, self._item(score, center=True))
            tbl.setItem(r, 3, self._item(fx["away_team_name"], align=Qt.AlignLeft | Qt.AlignVCenter))
            tbl.setItem(r, 4, self._item(format_kickoff(fx["scheduled_at"]), center=True))

    def _confirm_groups(self):
        answer = QMessageBox.question(
            self, "Zatwierdź fazę grupową",
            "Zatwierdzić wyniki fazy grupowej i utworzyć drabinki pucharowe?\n\n"
            "Po zatwierdzeniu wyników grup nie da się już edytować "
            "(można jedynie zresetować cały turniej).",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            match_result.confirm_group_stage(self.tournament_id)
        except Exception as e:
            QMessageBox.critical(self, "Błąd", str(e))
            return
        self.refresh_all()
        self.tabs.setCurrentIndex(3)  # zakładka „Drabinki KO”

    # ---------- TAB 4: drabinki KO ----------
    def _build_ko_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        ko_top = QHBoxLayout()
        ko_top.addWidget(muted("Dwuklik meczu z obiema drużynami: wpisanie wyniku lub szczegóły z listą strzelców. "
                               "Prawy przycisk: ustawienie terminu."))
        ko_top.addStretch()
        btn_ko_img = button("Grafika fazy pucharowej")
        btn_ko_img.setToolTip("Eksport PNG z drabinkami, godzinami i wynikami (np. na Facebooka).")
        btn_ko_img.clicked.connect(self._export_knockout_graphic)
        ko_top.addWidget(btn_ko_img)
        lay.addLayout(ko_top)
        self.ko_tree = QTreeWidget()
        self.ko_tree.setColumnCount(5)
        self.ko_tree.setHeaderLabels(["Faza", "Gospodarze", "Wynik", "Goście", "Termin"])
        self.ko_tree.setRootIsDecorated(True)
        self.ko_tree.setAlternatingRowColors(False)
        self.ko_tree.setFocusPolicy(Qt.NoFocus)
        self.ko_tree.header().setSectionsMovable(False)
        self.ko_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.ko_tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.ko_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.ko_tree.header().setSectionResizeMode(3, QHeaderView.Stretch)
        self.ko_tree.header().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hi = self.ko_tree.headerItem()
        hi.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        hi.setTextAlignment(2, Qt.AlignCenter)
        hi.setTextAlignment(3, Qt.AlignLeft | Qt.AlignVCenter)
        hi.setTextAlignment(4, Qt.AlignCenter)
        self.ko_tree.itemDoubleClicked.connect(self._ko_double)
        self.ko_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ko_tree.customContextMenuRequested.connect(
            lambda pos: self._match_menu(
                self.ko_tree, pos,
                it.data(0, UID) if (it := self.ko_tree.itemAt(pos)) else None))
        lay.addWidget(self.ko_tree)
        self.tabs.addTab(page, "Drabinki KO")

    def _ko_double(self, item, _col):
        mid = item.data(0, UID)
        if mid is not None:
            self._open_match(mid)

    def _refresh_ko(self):
        self.ko_tree.clear()
        by_stage = {}
        for fx in schedule.get_schedule(self.tournament_id):
            if fx["stage"] != "GROUP":
                by_stage.setdefault(fx["stage"], []).append(fx)

        for bracket_name, stages in BRACKETS:
            top = QTreeWidgetItem([bracket_name, "", "", ""])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            self.ko_tree.addTopLevelItem(top)
            top.setExpanded(True)
            for stage in stages:
                for fx in by_stage.get(stage, []):
                    home = fx["home_team_name"] or "?"
                    away = fx["away_team_name"] or "?"
                    if fx["played"]:
                        score = f"{fx['home_score']} : {fx['away_score']}"
                        if fx["winner_pen"] is not None:
                            score += (f" (k. {fx['home_pens']}:{fx['away_pens']})"
                                      if fx["home_pens"] is not None else " k.")
                            if fx["winner_pen"] == 0:
                                home += "  ✓"
                            else:
                                away += "  ✓"
                    else:
                        score = "–  :  –"
                    child = QTreeWidgetItem([STAGE_LABELS.get(stage, stage), home, score, away,
                                             format_kickoff(fx["scheduled_at"])])
                    child.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                    child.setTextAlignment(2, Qt.AlignCenter)
                    child.setTextAlignment(3, Qt.AlignLeft | Qt.AlignVCenter)
                    child.setTextAlignment(4, Qt.AlignCenter)
                    child.setData(0, UID, fx["match_id"])
                    top.addChild(child)

    # ---------- TAB 5: królowie strzelców ----------
    def _build_scorers_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        sc_top = QHBoxLayout()
        sc_top.addWidget(muted("Wszyscy zawodnicy, którzy strzelili gola (bez rzutów karnych w serii)."))
        sc_top.addStretch()
        btn_sc_img = button("Grafika strzelców")
        btn_sc_img.setToolTip("Eksport PNG z klasyfikacją strzelców (np. na Facebooka).")
        btn_sc_img.clicked.connect(self._export_scorers_graphic)
        sc_top.addWidget(btn_sc_img)
        lay.addLayout(sc_top)
        self.scorers = table(["#", "Zawodnik", "Drużyna", "Gole"], stretch_col=1)
        # Zawodnik i Drużyna dzielą szerokość po równo (bez wielkiej przerwy w środku)
        self.scorers.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        center_headers(self.scorers, [0, 3])
        lay.addWidget(self.scorers)
        self.tabs.addTab(page, "Klasyfikacja strzelców")

    def _refresh_scorers(self):
        self.scorers.setRowCount(0)
        for row in reports.top_scorers(self.tournament_id):
            r = self.scorers.rowCount()
            self.scorers.insertRow(r)
            self.scorers.setItem(r, 0, self._item(row["rank"], center=True))
            self.scorers.setItem(r, 1, self._item(row["player_name"]))
            self.scorers.setItem(r, 2, self._item(row["team_name"]))
            self.scorers.setItem(r, 3, self._item(row["goals"], center=True))

    # ---------- TAB 6: transfery ----------
    def _build_transfers_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)
        bar = QHBoxLayout()
        b = primary_button("Wykonaj transfer")
        b.clicked.connect(self._do_transfer)
        bar.addWidget(b)
        bar.addWidget(muted("Transfery zablokowane po starcie fazy pucharowej."))
        bar.addStretch()
        lay.addLayout(bar)
        self.transfers = table(["Zawodnik", "Z drużyny", "Do drużyny", "Kiedy"], stretch_col=0)
        center_headers(self.transfers, [3])
        lay.addWidget(self.transfers)
        self.tabs.addTab(page, "Transfery")

    def _refresh_transfers(self):
        self.transfers.setRowCount(0)
        for row in reports.transfer_history(self.tournament_id):
            r = self.transfers.rowCount()
            self.transfers.insertRow(r)
            self.transfers.setItem(r, 0, self._item(row["player_name"]))
            self.transfers.setItem(r, 1, self._item(row["from_team_name"]))
            self.transfers.setItem(r, 2, self._item(row["to_team_name"]))
            self.transfers.setItem(r, 3, self._item(row["transferred_at"], center=True))

    def _do_transfer(self):
        if self._state() in ("KO", "FINISHED"):
            QMessageBox.information(self, "Info", "Transfery są zablokowane w fazie pucharowej.")
            return
        dlg = TransferDialog(self, self.tournament_id)
        if dlg.exec():
            self.refresh_all()

    # ---------- grafiki do publikacji ----------
    def _pick_round(self, title: str, groups: bool = False):
        """Wybór kolejki (opcjonalnie z grupą). Domyślnie ostatnia kolejka z rozegranym meczem.
        Zwraca n, (n, grupa) albo None."""
        fixtures = [f for f in schedule.get_schedule(self.tournament_id) if f["stage"] == "GROUP"]
        if not fixtures:
            QMessageBox.information(self, title, "Najpierw wygeneruj terminarz fazy grupowej.")
            return None
        options = sorted({(f["round"], f["group_name"]) if groups else f["round"] for f in fixtures})
        played = [((f["round"], f["group_name"]) if groups else f["round"])
                  for f in fixtures if f["played"]]
        default = options.index(max(played)) if played else 0
        labels = [f"{o[0]}. kolejka · grupa {o[1]}" if groups else f"{o}. kolejka" for o in options]
        choice, ok = QInputDialog.getItem(self, title, "Kolejka:", labels, default, False)
        return options[labels.index(choice)] if ok else None

    def _export_round_graphic(self):
        n = self._pick_round("Grafika kolejki")
        if n is not None:
            self._save_graphic(lambda: graphics.render_round(self.tournament_id, n),
                               f"{self._safe_name()} - kolejka {n}.png")

    def _export_knockout_graphic(self):
        self._save_graphic(lambda: graphics.render_knockout(self.tournament_id),
                           f"{self._safe_name()} - faza pucharowa.png")

    def _export_scorers_graphic(self):
        self._save_graphic(lambda: graphics.render_scorers(self.tournament_id),
                           f"{self._safe_name()} - strzelcy.png")

    def _export_group_round_graphic(self):
        picked = self._pick_round("Grafika kolejki grupy", groups=True)
        if picked is None:
            return
        n, g = picked
        self._save_graphic(lambda: graphics.render_group_round(self.tournament_id, n, g),
                           f"{self._safe_name()} - kolejka {n} grupa {g}.png")

    def _save_graphic(self, render, filename: str):
        try:
            img = render()
        except ValueError as e:
            QMessageBox.information(self, "Grafika", str(e))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Zapisz grafikę", str(backup.exports_dir() / filename), "Obraz PNG (*.png)")
        if not path:
            return
        if not img.save(path, "PNG"):
            QMessageBox.critical(self, "Błąd", f"Nie udało się zapisać pliku:\n{path}")
            return
        if QMessageBox.question(self, "Grafika zapisana",
                                f"Zapisano grafikę:\n{path}\n\nOtworzyć ją teraz?") == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ---------- wspólne: wynik ----------
    def _match_subtitle(self, m) -> str:
        if m["stage"] == "GROUP":
            return f"Grupa {m['group_name']} · kolejka {m['round']}"
        return STAGE_LABELS.get(m["stage"], m["stage"])

    def _match_menu(self, widget, pos, match_id):
        """Menu kontekstowe meczu (prawy przycisk): ustawienie terminu."""
        if match_id is None:
            return
        menu = QMenu(self)
        menu.addAction("Ustaw termin meczu…", lambda: self._set_match_date(match_id))
        menu.exec(widget.viewport().mapToGlobal(pos))

    def _set_match_date(self, match_id):
        m = match_result.get_match(match_id)
        if m and MatchDateDialog(self, match_id, self._match_subtitle(m)).exec():
            self.refresh_all()

    def _open_match(self, match_id):
        """Dwuklik meczu: rozegrany → szczegóły, nierozegrany → wpisanie wyniku."""
        if match_id is None:
            return
        m = match_result.get_match(match_id)
        if m is None:
            return
        if not m["played"]:
            self._enter_result(match_id)
            return
        dlg = MatchDetailsDialog(self, match_id, self._match_subtitle(m))
        dlg.exec()
        if dlg.want_edit:
            self._enter_result(match_id, ask=False)

    def _enter_result(self, match_id, ask: bool = True):
        if match_id is None:
            return
        m = match_result.get_match(match_id)
        if m is None:
            return
        if m["home_team_id"] is None or m["away_team_id"] is None:
            QMessageBox.information(self, "Info", "Ten mecz nie ma jeszcze obu drużyn.")
            return
        if m["played"]:
            editable, reason = match_result.can_edit_match(match_id)
            if not editable:
                QMessageBox.information(self, "Wynik zablokowany", reason)
                return
            if ask and QMessageBox.question(self, "Edycja wyniku",
                                            "Wynik jest już wpisany. Edytować?") != QMessageBox.Yes:
                return
            dlg = ResultDialog(self, match_id, edit=True)
        else:
            dlg = ResultDialog(self, match_id, edit=False)
        if dlg.exec():
            self.refresh_all()