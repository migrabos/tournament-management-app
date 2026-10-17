"""Dialogi: wpisywanie/edycja wyniku meczu, termin meczu oraz transfer zawodnika."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QRadioButton, QButtonGroup, QMessageBox, QComboBox, QCheckBox, QWidget,
    QCalendarWidget, QTimeEdit,
)
from PySide6.QtCore import Qt, QDateTime

from app.dao import team_dao, player_dao
from app.services import match_result, transfer, schedule
from app.ui.widgets import primary_button, button, h2, muted, card, Stepper


class ResultDialog(QDialog):
    """Wpisanie lub edycja wyniku meczu wraz ze strzelcami."""

    def __init__(self, parent, match_id: int, edit: bool = False):
        super().__init__(parent)
        self.match_id = match_id
        self.edit = edit
        self.setWindowTitle("Edycja wyniku meczu" if edit else "Wynik meczu")
        self.setMinimumWidth(520)

        self.match = match_result.get_match(match_id)
        self.home = team_dao.get_team(self.match["home_team_id"])
        self.away = team_dao.get_team(self.match["away_team_id"])
        self.home_players = player_dao.list_players(self.match["home_team_id"])
        self.away_players = player_dao.list_players(self.match["away_team_id"])
        self.existing = match_result.get_match_scorer_counts(match_id) if edit else {}
        self.is_ko = self.match["stage"] != "GROUP"
        self.existing_shootout = match_result.get_match_shootout(match_id) if edit else []

        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(16)

        title = h2(f"{self.home['name']}  –  {self.away['name']}")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        root.addWidget(muted("Ustaw liczbę bramek dla każdego zawodnika."), alignment=Qt.AlignCenter)

        cols = QHBoxLayout()
        cols.setSpacing(14)
        self.home_spins = self._team_card(cols, self.home, self.home_players)
        self.away_spins = self._team_card(cols, self.away, self.away_players)
        root.addLayout(cols)

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = button("Anuluj")
        cancel.clicked.connect(self.reject)
        save = primary_button("Zapisz")
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        root.addLayout(btns)

    def _team_card(self, parent_layout, team, players) -> dict:
        frame, lay = card(padding=14)
        lbl = QLabel(team["name"])
        lbl.setObjectName("groupTitle")
        lay.addWidget(lbl)
        spins = {}
        if not players:
            lay.addWidget(muted("(brak zawodników)"))
        for p in players:
            row = QHBoxLayout()
            name = QLabel(p["name"])
            row.addWidget(name)
            row.addStretch()
            spin = Stepper(value=self.existing.get(p["id"], 0), minimum=0, maximum=20)
            row.addWidget(spin)
            spins[p["id"]] = spin
            lay.addLayout(row)
        parent_layout.addWidget(frame)
        return spins

    def _save(self):
        home_goals = {pid: s.value() for pid, s in self.home_spins.items()}
        away_goals = {pid: s.value() for pid, s in self.away_spins.items()}
        home_score = sum(home_goals.values())
        away_score = sum(away_goals.values())

        winner_pen = None
        shootout = []
        if self.is_ko and home_score == away_score:
            # remis w KO — rozstrzygają rzuty karne
            dlg = ShootoutDialog(self, self.home, self.away, self.home_players,
                                 self.away_players, self.existing_shootout,
                                 self.match["winner_pen"] if self.edit else None)
            if dlg.exec() != QDialog.Accepted:
                return
            shootout, winner_pen = dlg.shootout, dlg.winner_pen

        scorers = []
        for pid, n in {**home_goals, **away_goals}.items():
            scorers.extend([pid] * n)

        try:
            if self.edit:
                match_result.edit_match_result(self.match_id, home_score, away_score, scorers,
                                               winner_pen, shootout)
            else:
                match_result.save_match_result(self.match_id, home_score, away_score, scorers,
                                               winner_pen, shootout)
        except Exception as e:
            QMessageBox.critical(self, "Błąd zapisu", str(e))
            return
        self.accept()


class ShootoutDialog(QDialog):
    """Rzuty karne po remisie w meczu pucharowym — otwierane z ResultDialog.
    Kolejki: w każdej strzela po jednym zawodniku z obu drużyn (gospodarze pierwsi).
    Po zatwierdzeniu: self.shootout = [(player_id, scored), ...] (pusta, gdy wybrano
    samego zwycięzcę) oraz self.winner_pen (0/1)."""

    NO_KICK = None      # „— nie strzelał” (seria rozstrzygnięta przed końcem kolejki)

    def __init__(self, parent, home, away, home_players, away_players,
                 existing=(), winner_pen: int | None = None):
        super().__init__(parent)
        self.setWindowTitle("Rzuty karne")
        self.setMinimumWidth(560)
        self.home, self.away = home, away
        self.home_players, self.away_players = home_players, away_players
        self.home_ids = {p["id"] for p in home_players}
        self.shootout, self.winner_pen = [], None
        self.rounds = []        # [(home_cb, home_chk, away_cb, away_chk, QWidget wiersza)]
        self._build(list(existing), winner_pen)

    def _build(self, existing, winner_pen):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)

        title = h2(f"{self.home['name']}  –  {self.away['name']}")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        root.addWidget(muted("Remis — mecz rozstrzygają rzuty karne. "
                             "Nie liczą się do klasyfikacji strzelców."),
                       alignment=Qt.AlignCenter)
        self.score_lbl = QLabel()
        self.score_lbl.setObjectName("h1")
        self.score_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.score_lbl)

        # tryb: pełna seria albo tylko zwycięzca
        self.mode = QButtonGroup(self)
        self.rb_full = QRadioButton("Wpisz przebieg serii")
        self.rb_winner = QRadioButton("Tylko zwycięzca (bez szczegółów)")
        mode_row = QHBoxLayout()
        for rb in (self.rb_full, self.rb_winner):
            self.mode.addButton(rb)
            mode_row.addWidget(rb)
        mode_row.addStretch()
        root.addLayout(mode_row)

        # przebieg serii
        self.full_box, full_lay = card(padding=14)
        head = QHBoxLayout()
        for name in (self.home["name"], self.away["name"]):
            lbl = QLabel(name)
            lbl.setObjectName("groupTitle")
            head.addWidget(lbl, 1)
        full_lay.addLayout(head)
        self.rounds_lay = QVBoxLayout()
        self.rounds_lay.setSpacing(6)
        full_lay.addLayout(self.rounds_lay)
        round_btns = QHBoxLayout()
        add = button("+ Kolejka")
        add.clicked.connect(lambda: self._add_round())
        rem = button("− Usuń ostatnią")
        rem.clicked.connect(self._remove_round)
        round_btns.addWidget(add)
        round_btns.addWidget(rem)
        round_btns.addStretch()
        full_lay.addLayout(round_btns)
        root.addWidget(self.full_box)

        # tylko zwycięzca
        self.winner_box, win_lay = card(padding=14)
        self.win_group = QButtonGroup(self)
        self.rb_home = QRadioButton(self.home["name"])
        self.rb_away = QRadioButton(self.away["name"])
        for rb in (self.rb_home, self.rb_away):
            self.win_group.addButton(rb)
            win_lay.addWidget(rb)
        root.addWidget(self.winner_box)

        btns = QHBoxLayout()
        btns.addStretch()
        back = button("Wróć")
        back.clicked.connect(self.reject)
        ok = primary_button("Zatwierdź")
        ok.clicked.connect(self._accept)
        btns.addWidget(back)
        btns.addWidget(ok)
        root.addLayout(btns)

        # stan początkowy: zapisana seria (edycja) albo 5 kolejek
        if existing:
            home_k = [k for k in existing if k[0] in self.home_ids]
            away_k = [k for k in existing if k[0] not in self.home_ids]
            missing = (self.NO_KICK, False)
            for i in range(max(len(home_k), len(away_k))):
                self._add_round(home_k[i] if i < len(home_k) else missing,
                                away_k[i] if i < len(away_k) else missing)
        else:
            for _ in range(5):
                self._add_round()
        if winner_pen is not None and not existing:
            self.rb_winner.setChecked(True)
            (self.rb_home if winner_pen == 0 else self.rb_away).setChecked(True)
        else:
            self.rb_full.setChecked(True)
        self.mode.buttonToggled.connect(self._refresh)
        self._refresh()

    def _kicker(self, players, kick, idx):
        cb = QComboBox()
        cb.addItem("— nie strzelał", self.NO_KICK)
        for p in players:
            cb.addItem(p["name"], p["id"])
        if kick is None:            # nowa kolejka: kolejny zawodnik ze składu
            cb.setCurrentIndex(1 + idx % len(players) if players else 0)
        else:
            cb.setCurrentIndex(max(cb.findData(kick[0]), 0))
        chk = QCheckBox("gol")
        chk.setChecked(True if kick is None else bool(kick[1]))
        cb.currentIndexChanged.connect(self._refresh)
        chk.toggled.connect(self._refresh)
        return cb, chk

    def _add_round(self, home_kick=None, away_kick=None):
        idx = len(self.rounds)
        row_w = QWidget()
        row = QHBoxLayout(row_w)
        row.setContentsMargins(0, 0, 0, 0)
        hcb, hchk = self._kicker(self.home_players, home_kick, idx)
        acb, achk = self._kicker(self.away_players, away_kick, idx)
        num = QLabel(f"{idx + 1}.")
        num.setAlignment(Qt.AlignCenter)
        num.setMinimumWidth(28)
        row.addWidget(hcb, 1)
        row.addWidget(hchk)
        row.addWidget(num)
        row.addWidget(acb, 1)
        row.addWidget(achk)
        self.rounds_lay.addWidget(row_w)
        self.rounds.append((hcb, hchk, acb, achk, row_w))
        self._refresh()

    def _remove_round(self):
        if self.rounds:
            self.rounds.pop()[-1].deleteLater()
            self._refresh()

    def _kicks(self) -> list[tuple[int, bool]]:
        """Strzały w kolejności: w każdej kolejce najpierw gospodarze, potem goście."""
        kicks = []
        for hcb, hchk, acb, achk, _ in self.rounds:
            for cb, chk in ((hcb, hchk), (acb, achk)):
                if cb.currentData() is not self.NO_KICK:
                    kicks.append((cb.currentData(), chk.isChecked()))
        return kicks

    def _score(self) -> tuple[int, int]:
        kicks = self._kicks()
        home = sum(s for pid, s in kicks if pid in self.home_ids)
        return home, sum(s for _, s in kicks) - home

    def _refresh(self, *_):
        if not hasattr(self, "rb_full"):
            return
        full = self.rb_full.isChecked()
        self.full_box.setVisible(full)
        self.winner_box.setVisible(not full)
        self.score_lbl.setVisible(full)
        for hcb, hchk, acb, achk, _ in self.rounds:
            hchk.setEnabled(hcb.currentData() is not self.NO_KICK)
            achk.setEnabled(acb.currentData() is not self.NO_KICK)
        self.score_lbl.setText("{} : {}".format(*self._score()))
        self.adjustSize()

    def _accept(self):
        if self.rb_winner.isChecked():
            if not self.win_group.checkedButton():
                QMessageBox.warning(self, "Rzuty karne", "Wskaż zwycięzcę.")
                return
            self.shootout, self.winner_pen = [], 0 if self.rb_home.isChecked() else 1
        else:
            h, a = self._score()
            if h == a:
                QMessageBox.warning(self, "Rzuty karne",
                    f"Seria jest nierozstrzygnięta ({h}:{a}). Dodaj kolejkę lub popraw strzały.")
                return
            self.shootout, self.winner_pen = self._kicks(), 0 if h > a else 1
        self.accept()


QT_DATETIME_FORMAT = "yyyy-MM-dd HH:mm"      # odpowiednik schedule.DATETIME_FORMAT


class MatchDateDialog(QDialog):
    """Ustawienie lub usunięcie terminu (data i godzina) meczu."""

    def __init__(self, parent, match_id: int, subtitle: str = ""):
        super().__init__(parent)
        self.match_id = match_id
        self.setWindowTitle("Termin meczu")
        self.setMinimumWidth(380)
        m = match_result.get_match_details(match_id)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)
        title = h2(f"{m['home_team_name'] or '?'}  –  {m['away_team_name'] or '?'}")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        if subtitle:
            root.addWidget(muted(subtitle), alignment=Qt.AlignCenter)

        current = (QDateTime.fromString(m["scheduled_at"], QT_DATETIME_FORMAT)
                   if m["scheduled_at"] else QDateTime.currentDateTime())
        if not m["scheduled_at"]:      # domyślnie najbliższa pełna godzina
            t = current.time()
            current = current.addSecs(3600 - t.minute() * 60 - t.second())

        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.calendar.setSelectedDate(current.date())
        root.addWidget(self.calendar)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Godzina:"))
        self.time = QTimeEdit(current.time())
        self.time.setDisplayFormat("HH:mm")
        self.time.setButtonSymbols(QTimeEdit.NoButtons)   # wpisywanie / strzałki / kółko myszy
        time_row.addWidget(self.time)
        time_row.addStretch()
        root.addLayout(time_row)

        btns = QHBoxLayout()
        if m["scheduled_at"]:
            clear = button("Usuń termin", danger=True)
            clear.clicked.connect(lambda: self._save(None))
            btns.addWidget(clear)
        btns.addStretch()
        cancel = button("Anuluj")
        cancel.clicked.connect(self.reject)
        ok = primary_button("Zapisz")
        ok.clicked.connect(lambda: self._save(
            QDateTime(self.calendar.selectedDate(), self.time.time()).toString(QT_DATETIME_FORMAT)))
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def _save(self, when):
        try:
            schedule.set_match_datetime(self.match_id, when)
        except Exception as e:
            QMessageBox.critical(self, "Błąd", str(e))
            return
        self.accept()


def format_kickoff(when: str | None) -> str:
    """'2026-10-18 18:30' → '18.10.2026  18:30'; brak terminu → '—'."""
    if not when:
        return "—"
    return QDateTime.fromString(when, QT_DATETIME_FORMAT).toString("dd.MM.yyyy  HH:mm")


class TransferDialog(QDialog):
    """Transfer zawodnika do innej drużyny w tym samym turnieju."""

    def __init__(self, parent, tournament_id: int):
        super().__init__(parent)
        self.tournament_id = tournament_id
        self.setWindowTitle("Transfer zawodnika")
        self.setMinimumWidth(440)

        self.teams = team_dao.list_teams(tournament_id)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)
        root.addWidget(h2("Transfer zawodnika"))

        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        grid.setHorizontalSpacing(12)

        grid.addWidget(QLabel("Zawodnik:"), 0, 0)
        self.player_cb = QComboBox()
        self.player_map = {}
        for t in self.teams:
            for p in player_dao.list_players(t["id"]):
                label = f"{p['name']}  ·  {t['name']}"
                self.player_map[label] = p["id"]
                self.player_cb.addItem(label)
        grid.addWidget(self.player_cb, 0, 1)

        grid.addWidget(QLabel("Do drużyny:"), 1, 0)
        self.team_cb = QComboBox()
        self.team_map = {t["name"]: t["id"] for t in self.teams}
        for name in self.team_map:
            self.team_cb.addItem(name)
        grid.addWidget(self.team_cb, 1, 1)
        root.addLayout(grid)

        root.addWidget(muted("Limit składu: 5–10 zawodników. Transfery zablokowane w fazie pucharowej."))

        btns = QHBoxLayout()
        btns.addStretch()
        cancel = button("Anuluj")
        cancel.clicked.connect(self.reject)
        ok = primary_button("Wykonaj")
        ok.clicked.connect(self._do)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def _do(self):
        if not self.player_cb.currentText() or not self.team_cb.currentText():
            QMessageBox.information(self, "Info", "Wybierz zawodnika i drużynę.")
            return
        player_id = self.player_map[self.player_cb.currentText()]
        team_id = self.team_map[self.team_cb.currentText()]
        try:
            transfer.transfer_player(player_id, team_id)
        except Exception as e:
            QMessageBox.critical(self, "Błąd transferu", str(e))
            return
        self.accept()


class MatchDetailsDialog(QDialog):
    """Podgląd rozegranego meczu: wynik, karne i strzelcy obu drużyn.
    Przycisk „Edytuj wynik” zamyka okno z want_edit=True — edycję otwiera wywołujący."""

    def __init__(self, parent, match_id: int, subtitle: str = ""):
        super().__init__(parent)
        self.want_edit = False
        self.d = match_result.get_match_details(match_id)
        self.setWindowTitle("Szczegóły meczu")
        self.setMinimumWidth(560)
        self._build(subtitle)

    def _build(self, subtitle):
        d = self.d
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        if d["scheduled_at"]:
            subtitle = " · ".join(filter(None, [subtitle, format_kickoff(d["scheduled_at"])]))
        if subtitle:
            root.addWidget(muted(subtitle), alignment=Qt.AlignCenter)

        # wynik: Gospodarze  2 : 1  Goście
        score_row = QHBoxLayout()
        home = h2(d["home_team_name"] or "?")
        home.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        away = h2(d["away_team_name"] or "?")
        away.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        score = QLabel(f"{d['home_score']} : {d['away_score']}" if d["played"] else "–  :  –")
        score.setObjectName("h1")
        score.setAlignment(Qt.AlignCenter)
        score.setMinimumWidth(110)
        score_row.addWidget(home, 1)
        score_row.addWidget(score)
        score_row.addWidget(away, 1)
        root.addLayout(score_row)

        if d["winner_pen"] is not None:
            winner = d["home_team_name"] if d["winner_pen"] == 0 else d["away_team_name"]
            pens = f" {d['home_pens']}:{d['away_pens']}" if d["shootout"] else ""
            root.addWidget(muted(f"Po rzutach karnych{pens} wygrywa {winner}"),
                           alignment=Qt.AlignCenter)

        if not d["played"]:
            root.addWidget(muted("Mecz nie został jeszcze rozegrany."), alignment=Qt.AlignCenter)
        else:
            cols = QHBoxLayout()
            cols.setSpacing(14)
            for scorers, align, home_side in (
                    (d["home_scorers"], Qt.AlignRight, True),
                    (d["away_scorers"], Qt.AlignLeft, False)):
                frame, lay = card(padding=14)
                if not scorers:
                    lay.addWidget(muted("brak bramek"), alignment=align)
                for s in scorers:
                    name = s["name"] + (f"  ×{s['goals']}" if s["goals"] > 1 else "")
                    text = f"{name}  ⚽" if home_side else f"⚽  {name}"   # lustrzanie
                    lbl = QLabel(text)
                    lbl.setAlignment(align)
                    lay.addWidget(lbl)
                lay.addStretch()
                cols.addWidget(frame, 1)
            root.addLayout(cols)

        if d["shootout"]:
            frame, lay = card(padding=14)
            lay.addWidget(muted("Seria rzutów karnych"), alignment=Qt.AlignCenter)
            grid = QGridLayout()
            grid.setHorizontalSpacing(12)
            for i, k in enumerate(d["shootout"]):
                mark = "✓" if k["scored"] else "✗"
                text = f"{k['name']}  {mark}" if k["home"] else f"{mark}  {k['name']}"
                lbl = QLabel(text)
                lbl.setAlignment(Qt.AlignRight if k["home"] else Qt.AlignLeft)
                grid.addWidget(QLabel(f"{k['kick_no']}."), i, 1, alignment=Qt.AlignCenter)
                grid.addWidget(lbl, i, 0 if k["home"] else 2)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(2, 1)
            lay.addLayout(grid)
            root.addWidget(frame)

        btns = QHBoxLayout()
        btns.addStretch()
        close = button("Zamknij")
        close.clicked.connect(self.reject)
        btns.addWidget(close)
        if d["home_team_id"] is not None and d["away_team_id"] is not None:
            edit = primary_button("Edytuj wynik" if d["played"] else "Wpisz wynik")
            edit.clicked.connect(self._edit)
            btns.addWidget(edit)
        root.addLayout(btns)

    def _edit(self):
        self.want_edit = True
        self.accept()