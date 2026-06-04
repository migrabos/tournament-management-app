"""Dialogi: wpisywanie/edycja wyniku meczu oraz transfer zawodnika."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QRadioButton, QButtonGroup, QMessageBox, QComboBox,
)
from PySide6.QtCore import Qt

from app.dao import team_dao, player_dao
from app.services import match_result, transfer
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

        self.pen_group = None
        if self.is_ko:
            pen_card, pen_lay = card(padding=14)
            pen_lay.addWidget(muted("Jeśli remis — zwycięzca po karnych:"))
            self.pen_group = QButtonGroup(self)
            self.rb_none = QRadioButton("(brak / nie remis)")
            self.rb_home = QRadioButton(self.home["name"])
            self.rb_away = QRadioButton(self.away["name"])
            for rb in (self.rb_none, self.rb_home, self.rb_away):
                self.pen_group.addButton(rb)
                pen_lay.addWidget(rb)
            self.rb_none.setChecked(True)
            if self.edit and self.match["winner_pen"] is not None:
                (self.rb_home if self.match["winner_pen"] == 0 else self.rb_away).setChecked(True)
            root.addWidget(pen_card)

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
        if self.is_ko:
            if home_score == away_score:
                if self.rb_home.isChecked():
                    winner_pen = 0
                elif self.rb_away.isChecked():
                    winner_pen = 1
                else:
                    QMessageBox.warning(self, "Remis w fazie pucharowej",
                        "Mecz pucharowy nie może zakończyć się remisem.\n"
                        "Zmień wynik lub wskaż zwycięzcę po karnych.")
                    return
            elif not self.rb_none.isChecked():
                QMessageBox.warning(self, "Błąd", "Karne tylko przy remisie.")
                return

        scorers = []
        for pid, n in {**home_goals, **away_goals}.items():
            scorers.extend([pid] * n)

        try:
            if self.edit:
                match_result.edit_match_result(self.match_id, home_score, away_score, scorers, winner_pen)
            else:
                match_result.save_match_result(self.match_id, home_score, away_score, scorers, winner_pen)
        except Exception as e:
            QMessageBox.critical(self, "Błąd zapisu", str(e))
            return
        self.accept()


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
