"""Grafiki z wynikami do publikacji (np. na Facebooku turnieju) — pliki PNG.

  - render_round(tid, n)   — kolejka fazy grupowej: mecze obu grup z godzinami
                             i wynikami oraz tabele grup po tej kolejce;
  - render_knockout(tid)   — faza pucharowa: trzy drabinki (miejsca 1-4, 5-8, 9-12);
  - render_scorers(tid)    — klasyfikacja strzelców (wszyscy z co najmniej jednym golem);
  - render_group_round(tid, n, g) — kolejka jednej grupy: mecze z wynikami i strzelcami.

Styl jest stały (niezależny od motywu aplikacji), żeby kolejne grafiki
wyglądały spójnie. Dłuższy bok obrazu ma zawsze 2048 px — to maksimum, do którego
Facebook zmniejsza zdjęcia; w tym rozmiarze nie skaluje ich ponownie (mniej rozmycia).
"""
from datetime import datetime

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QImage, QPainter, QColor, QFont, QFontMetrics, QLinearGradient, QPen, QPainterPath,
)

from app.dao import tournament_dao
from app.services import schedule, match_result
from app.reports import reports

LONG_SIDE_PX = 2048     # docelowy dłuższy bok PNG (limit Facebooka)
WIDTH = 1400
MARGIN = 40
GAP = 30
FONT = "Segoe UI"

C = {
    "bg": "#f1f5f2",
    "card": "#ffffff",
    "border": "#dbe5df",
    "head_from": "#0f3d24",
    "head_to": "#1f9d63",
    "band": "#1f9d63",
    "soft": "#e5f3ea",
    "zebra": "#f7faf8",
    "text": "#1f2937",
    "muted": "#6b7280",
    "accent": "#1f9d63",
    "pill_off": "#e5e7eb",
    "line": "#a7d3b9",
}

KO_SECTIONS = [
    ("MIEJSCA 1–4", "SF_TOP", ("FINAL_TOP", "FINAŁ"), ("THIRD_PLACE", "MECZ O 3. MIEJSCE")),
    ("MIEJSCA 5–8", "SF_MID", ("FINAL_MID", "MECZ O 5. MIEJSCE"), ("SEVENTH_PLACE", "MECZ O 7. MIEJSCE")),
    ("MIEJSCA 9–12", "SF_BOT", ("FINAL_BOT", "MECZ O 9. MIEJSCE"), ("ELEVENTH_PLACE", "MECZ O 11. MIEJSCE")),
]


# ---------------------------------------------------------------- pomocnicze

def _font(px: float, weight=QFont.Normal, spacing: float = 0) -> QFont:
    f = QFont(FONT)
    f.setPixelSize(int(px))
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


def _text(p: QPainter, rect: QRectF, text: str, px: float, *, weight=QFont.Normal,
          color="text", align=Qt.AlignLeft | Qt.AlignVCenter, spacing: float = 0) -> None:
    f = _font(px, weight, spacing)
    p.setFont(f)
    p.setPen(QColor(C.get(color, color)))
    p.drawText(rect, align, QFontMetrics(f).elidedText(text, Qt.ElideRight, int(rect.width())))


def _rect(p: QPainter, rect: QRectF, fill: str, radius: float = 0, border: str | None = None) -> None:
    p.setPen(QPen(QColor(C.get(border, border)), 1) if border else Qt.NoPen)
    p.setBrush(QColor(C.get(fill, fill)))
    p.drawRoundedRect(rect, radius, radius)


def _card(p: QPainter, rect: QRectF, title: str) -> QRectF:
    """Biała karta z zielonym paskiem tytułu. Zwraca obszar pod paskiem."""
    _rect(p, rect, "card", 14, "border")
    band = QRectF(rect.x(), rect.y(), rect.width(), 46)
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)        # suma kształtów, bez „dziury” na nakładce
    path.addRoundedRect(band, 14, 14)
    path.addRect(QRectF(band.x(), band.y() + 23, band.width(), 23))   # dolne rogi proste
    p.setPen(Qt.NoPen)
    p.fillPath(path.simplified(), QColor(C["band"]))
    _text(p, band, title, 17, weight=QFont.Bold, color="#ffffff",
          align=Qt.AlignCenter, spacing=1.5)
    return QRectF(rect.x(), band.bottom(), rect.width(), rect.bottom() - band.bottom())


def _header(p: QPainter, tournament: str, title: str, subtitle: str) -> float:
    h = 160
    grad = QLinearGradient(0, 0, WIDTH, h)
    grad.setColorAt(0, QColor(C["head_from"]))
    grad.setColorAt(1, QColor(C["head_to"]))
    p.fillRect(QRectF(0, 0, WIDTH, h), grad)
    _text(p, QRectF(0, 26, WIDTH, 24), tournament.upper(), 16, weight=QFont.DemiBold,
          color="#cdebd9", align=Qt.AlignCenter, spacing=3)
    _text(p, QRectF(0, 52, WIDTH, 60), title, 46, weight=QFont.Black,
          color="#ffffff", align=Qt.AlignCenter, spacing=1)
    if subtitle:
        _text(p, QRectF(0, 112, WIDTH, 30), subtitle, 20, weight=QFont.DemiBold,
              color="#e3f4ea", align=Qt.AlignCenter, spacing=1)
    return h


def _new_image(height: float) -> tuple[QImage, QPainter]:
    scale = LONG_SIDE_PX / max(WIDTH, height)       # układ w px logicznych → 2048 px
    img = QImage(round(WIDTH * scale), round(height * scale), QImage.Format_ARGB32)
    img.fill(QColor(C["bg"]))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    p.scale(scale, scale)
    return img, p


def _date(when: str | None) -> str:
    return f"{when[8:10]}.{when[5:7]}.{when[0:4]}" if when else ""


def _time(when: str | None) -> str:
    return when[11:16] if when else ""


def _dates_label(matches: list[dict]) -> str:
    days = sorted({m["scheduled_at"][:10] for m in matches if m["scheduled_at"]})
    if not days:
        return ""
    if len(days) == 1:
        return _date(days[0])
    return f"{_date(days[0])} – {_date(days[-1])}"


def _score(m: dict) -> str:
    return f"{m['home_score']}:{m['away_score']}" if m["played"] else "–:–"


def _pens(m: dict) -> str:
    if m["winner_pen"] is None:
        return ""
    if m.get("home_pens") is not None:
        return f"k. {m['home_pens']}:{m['away_pens']}"
    return "po karnych"


def _name(name: str | None) -> str:
    return name.upper() if name else "—"


# ---------------------------------------------------------------- kolejka

ROW_H = 54
TABLE_ROW_H = 40
TABLE_COLS = [("Pkt", "points", 50), ("RM", "played", 42), ("W", "wins", 42), ("R", "draws", 42),
              ("P", "losses", 42), ("BZ", "goals_for", 46), ("BS", "goals_against", 46),
              ("RB", "goal_diff", 50)]


def round_numbers(tournament_id: int) -> list[int]:
    """Numery kolejek fazy grupowej w terminarzu."""
    return sorted({m["round"] for m in schedule.get_schedule(tournament_id)
                   if m["stage"] == "GROUP"})


def render_round(tournament_id: int, round_no: int) -> QImage:
    tournament = tournament_dao.get_tournament(tournament_id)["name"]
    matches = [m for m in schedule.get_schedule(tournament_id)
               if m["stage"] == "GROUP" and m["round"] == round_no]
    if not matches:
        raise ValueError(f"Brak meczów w kolejce {round_no}.")
    groups = sorted({m["group_name"] for m in matches})
    by_group = {g: sorted((m for m in matches if m["group_name"] == g),
                          key=lambda m: (m["scheduled_at"] or "9", m["match_id"]))
                for g in groups}
    tables = {g: reports.group_table_after_round(tournament_id, g, round_no) for g in groups}

    col_w = (WIDTH - 2 * MARGIN - GAP) / 2
    fixtures_h = 46 + 10 + max(len(v) for v in by_group.values()) * ROW_H + 10
    table_h = 46 + TABLE_ROW_H + max(len(v) for v in tables.values()) * TABLE_ROW_H + 8
    head_h = 160
    height = head_h + 34 + fixtures_h + 26 + 26 + table_h + 40

    img, p = _new_image(height)
    _header(p, tournament, f"{round_no}. KOLEJKA", _dates_label(matches))

    y = head_h + 34
    for i, g in enumerate(groups[:2]):
        x = MARGIN + i * (col_w + GAP)
        body = _card(p, QRectF(x, y, col_w, fixtures_h), f"GRUPA {g}")
        ry = body.y() + 10
        for k, m in enumerate(by_group[g]):
            _fixture_row(p, QRectF(x + 16, ry, col_w - 32, ROW_H), m, k > 0)
            ry += ROW_H

    y += fixtures_h + 26
    _text(p, QRectF(MARGIN, y - 4, WIDTH - 2 * MARGIN, 24), f"TABELE PO {round_no}. KOLEJCE",
          14, weight=QFont.Bold, color="muted", align=Qt.AlignCenter, spacing=2.5)
    y += 26
    for i, g in enumerate(groups[:2]):
        x = MARGIN + i * (col_w + GAP)
        body = _card(p, QRectF(x, y, col_w, table_h), f"GRUPA {g}")
        _standings(p, QRectF(x, body.y(), col_w, body.height()), tables[g])

    p.end()
    return img


def _fixture_row(p: QPainter, r: QRectF, m: dict, separator: bool) -> None:
    if separator:
        p.setPen(QPen(QColor(C["border"]), 1))
        p.drawLine(QPointF(r.x(), r.y()), QPointF(r.right(), r.y()))
    time_w, pill_w = 64, 76
    t = _time(m["scheduled_at"])
    _text(p, QRectF(r.x(), r.y(), time_w, r.height()), t or "--:--", 17,
          weight=QFont.Bold, color="text" if t else "muted")

    names = QRectF(r.x() + time_w, r.y(), r.width() - time_w - pill_w - 12, r.height())
    half = names.width() / 2
    _text(p, QRectF(names.x(), r.y(), half - 14, r.height()), _name(m["home_team_name"]), 16,
          weight=QFont.DemiBold, align=Qt.AlignRight | Qt.AlignVCenter)
    _text(p, QRectF(names.x() + half - 14, r.y(), 28, r.height()), "–", 16,
          color="muted", align=Qt.AlignCenter)
    _text(p, QRectF(names.x() + half + 14, r.y(), half - 14, r.height()), _name(m["away_team_name"]), 16,
          weight=QFont.DemiBold, align=Qt.AlignLeft | Qt.AlignVCenter)

    pill = QRectF(r.right() - pill_w, r.center().y() - 18, pill_w, 36)
    _rect(p, pill, "accent" if m["played"] else "pill_off", 9)
    _text(p, pill, _score(m), 19, weight=QFont.Bold,
          color="#ffffff" if m["played"] else "muted", align=Qt.AlignCenter)


def _standings(p: QPainter, r: QRectF, rows: list[dict]) -> None:
    pad = 16
    num_w = 40
    cols_w = sum(w for _, _, w in TABLE_COLS)
    name_x = r.x() + pad + num_w
    name_w = r.width() - 2 * pad - num_w - cols_w

    def cells(y, values, *, weight=QFont.Normal, color="text", px=15):
        x = name_x + name_w
        for (_, _, w), v in zip(TABLE_COLS, values):
            bold = QFont.Bold if w == TABLE_COLS[0][2] and weight == QFont.Normal else weight
            _text(p, QRectF(x, y, w, TABLE_ROW_H), str(v), px, weight=bold,
                  color=color, align=Qt.AlignCenter)
            x += w

    y = r.y()
    _rect(p, QRectF(r.x() + 1, y, r.width() - 2, TABLE_ROW_H), "soft")
    _text(p, QRectF(name_x, y, name_w, TABLE_ROW_H), "DRUŻYNA", 13, weight=QFont.Bold,
          color="muted", spacing=1)
    cells(y, [h for h, _, _ in TABLE_COLS], weight=QFont.Bold, color="muted", px=13)
    y += TABLE_ROW_H

    for i, row in enumerate(rows):
        if i % 2:
            _rect(p, QRectF(r.x() + 1, y, r.width() - 2, TABLE_ROW_H), "zebra")
        _text(p, QRectF(r.x() + pad, y, num_w, TABLE_ROW_H), f"{i + 1}.", 15,
              weight=QFont.Bold, color="accent")
        _text(p, QRectF(name_x, y, name_w - 8, TABLE_ROW_H), _name(row["team_name"]), 15,
              weight=QFont.DemiBold)
        gd = row["goal_diff"]
        cells(y, [row["points"], row["played"], row["wins"], row["draws"], row["losses"],
                  row["goals_for"], row["goals_against"], f"+{gd}" if gd > 0 else gd])
        y += TABLE_ROW_H


# ---------------------------------------------------------------- strzelcy

SCORER_ROW_H = 44
SCORERS_PER_COLUMN = 15      # dłuższa lista dzieli się na dwie kolumny


def render_scorers(tournament_id: int) -> QImage:
    tournament = tournament_dao.get_tournament(tournament_id)["name"]
    rows = reports.top_scorers(tournament_id)
    if not rows:
        raise ValueError("Nikt jeszcze nie strzelił gola.")

    two_cols = len(rows) > SCORERS_PER_COLUMN
    per_col = (len(rows) + 1) // 2 if two_cols else len(rows)
    columns = [rows[:per_col], rows[per_col:]] if two_cols else [rows]
    col_w = (WIDTH - 2 * MARGIN - GAP) / 2 if two_cols else 820
    card_h = 46 + SCORER_ROW_H + per_col * SCORER_ROW_H + 8
    head_h = 160
    height = head_h + 34 + card_h + 40

    img, p = _new_image(height)
    _header(p, tournament, "KLASYFIKACJA STRZELCÓW", f"stan na {_standing_date(tournament_id)}")
    x0 = MARGIN if two_cols else (WIDTH - col_w) / 2
    for i, col in enumerate(columns):
        x = x0 + i * (col_w + GAP)
        body = _card(p, QRectF(x, head_h + 34, col_w, card_h),
                     "STRZELCY" if not two_cols else ("STRZELCY" if i == 0 else "STRZELCY — CD."))
        _scorers_list(p, QRectF(x, body.y(), col_w, body.height()), col)
    p.end()
    return img


def _standing_date(tournament_id: int) -> str:
    """Data, na którą aktualna jest klasyfikacja: dzień ostatniego rozegranego meczu
    z terminem; gdy żaden rozegrany mecz nie ma terminu — dzisiejsza data."""
    days = [m["scheduled_at"][:10] for m in schedule.get_schedule(tournament_id)
            if m["played"] and m["scheduled_at"]]
    return _date(max(days)) if days else f"{datetime.now():%d.%m.%Y}"


def _scorers_list(p: QPainter, r: QRectF, rows: list[dict]) -> None:
    pad, num_w, goals_w = 16, 48, 64
    team_w = (r.width() - 2 * pad - num_w - goals_w) * 0.45
    name_w = r.width() - 2 * pad - num_w - goals_w - team_w
    name_x = r.x() + pad + num_w
    team_x = name_x + name_w

    y = r.y()
    _rect(p, QRectF(r.x() + 1, y, r.width() - 2, SCORER_ROW_H), "soft")
    for text, x, w, align in (("ZAWODNIK", name_x, name_w, Qt.AlignLeft),
                              ("DRUŻYNA", team_x, team_w, Qt.AlignLeft),
                              ("GOLE", r.right() - pad - goals_w, goals_w, Qt.AlignCenter)):
        _text(p, QRectF(x, y, w, SCORER_ROW_H), text, 13, weight=QFont.Bold, color="muted",
              align=align | Qt.AlignVCenter, spacing=1)
    y += SCORER_ROW_H

    prev_rank = None
    for i, row in enumerate(rows):
        if i % 2:
            _rect(p, QRectF(r.x() + 1, y, r.width() - 2, SCORER_ROW_H), "zebra")
        podium = row["rank"] <= 3
        rank = f"{row['rank']}." if row["rank"] != prev_rank else ""   # ex aequo: miejsce raz
        prev_rank = row["rank"]
        _text(p, QRectF(r.x() + pad, y, num_w, SCORER_ROW_H), rank, 16,
              weight=QFont.Bold, color="accent")
        _text(p, QRectF(name_x, y, name_w - 10, SCORER_ROW_H), row["player_name"], 16,
              weight=QFont.Bold if podium else QFont.DemiBold)
        _text(p, QRectF(team_x, y, team_w - 10, SCORER_ROW_H), _name(row["team_name"]), 14,
              weight=QFont.DemiBold, color="muted")
        pill = QRectF(r.right() - pad - goals_w + 10, y + 7, goals_w - 20, SCORER_ROW_H - 14)
        _rect(p, pill, "accent" if podium else "soft", 8)
        _text(p, pill, str(row["goals"]), 17, weight=QFont.Bold,
              color="#ffffff" if podium else "text", align=Qt.AlignCenter)
        y += SCORER_ROW_H


# ---------------------------------------------------------------- kolejka jednej grupy

SCORER_LINE_H = 34


def render_group_round(tournament_id: int, round_no: int, group_name: str) -> QImage:
    tournament = tournament_dao.get_tournament(tournament_id)["name"]
    matches = sorted((m for m in schedule.get_schedule(tournament_id, group_name)
                      if m["round"] == round_no),
                     key=lambda m: (m["scheduled_at"] or "9", m["match_id"]))
    if not matches:
        raise ValueError(f"Brak meczów grupy {group_name} w kolejce {round_no}.")
    details = [match_result.get_match_details(m["match_id"]) for m in matches]

    def card_h(d):
        n = max(len(d["home_scorers"]), len(d["away_scorers"])) if d["played"] else 0
        return 36 + 110 + (n * SCORER_LINE_H + 24 if n else 0)

    head_h = 160
    height = head_h + 34 + sum(card_h(d) + 22 for d in details) - 22 + 40
    img, p = _new_image(height)
    _header(p, tournament, f"{round_no}. KOLEJKA · GRUPA {group_name}", _dates_label(matches))

    y = head_h + 34
    for d in details:
        h = card_h(d)
        _match_card(p, QRectF(MARGIN, y, WIDTH - 2 * MARGIN, h), d)
        y += h + 22
    p.end()
    return img


def _match_card(p: QPainter, r: QRectF, d: dict) -> None:
    _rect(p, r, "card", 14, "border")
    t = _time(d["scheduled_at"])
    _text(p, QRectF(r.x(), r.y() + 14, r.width(), 22), f"godz. {t}" if t else "", 15,
          weight=QFont.Bold, color="accent", align=Qt.AlignCenter, spacing=1)

    row = QRectF(r.x(), r.y() + 36, r.width(), 110)
    third = r.width() / 3
    winner = None
    if d["played"] and d["home_score"] != d["away_score"]:
        winner = "home" if d["home_score"] > d["away_score"] else "away"
    for side, x in (("home", r.x()), ("away", r.x() + 2 * third)):
        f = _font(26, QFont.Black if winner == side else QFont.Bold, 1)
        p.setFont(f)
        p.setPen(QColor(C["text"]))
        p.drawText(QRectF(x + 24, row.y(), third - 48, row.height()),
                   Qt.AlignCenter | Qt.TextWordWrap, _name(d[f"{side}_team_name"]))
    _text(p, QRectF(r.x() + third, row.y(), third, row.height()),
          f"{d['home_score']} : {d['away_score']}" if d["played"] else "–  :  –", 64,
          weight=QFont.Black, color="accent" if d["played"] else "muted", align=Qt.AlignCenter)

    if not d["played"] or not (d["home_scorers"] or d["away_scorers"]):
        return
    half = r.width() / 2
    top = row.bottom() + 4
    n = max(len(d["home_scorers"]), len(d["away_scorers"]))
    p.setPen(QPen(QColor(C["border"]), 1))
    p.drawLine(QPointF(r.x() + 24, top - 4), QPointF(r.right() - 24, top - 4))
    p.drawLine(QPointF(r.x() + half, top + 6), QPointF(r.x() + half, top + n * SCORER_LINE_H + 6))
    for side, align in (("home_scorers", Qt.AlignRight), ("away_scorers", Qt.AlignLeft)):
        ly = top + 8
        x = r.x() + 30 if align == Qt.AlignRight else r.x() + half + 30
        w = half - 60
        for s in d[side]:
            text = s["name"] + (f"  ×{s['goals']}" if s["goals"] > 1 else "")
            _ball(p, QPointF(x + w - 6 if align == Qt.AlignRight else x + 6, ly + SCORER_LINE_H / 2))
            tr = QRectF(x, ly, w - 22, SCORER_LINE_H) if align == Qt.AlignRight \
                else QRectF(x + 22, ly, w - 22, SCORER_LINE_H)
            _text(p, tr, text, 16, weight=QFont.DemiBold, align=align | Qt.AlignVCenter)
            ly += SCORER_LINE_H


def _ball(p: QPainter, c: QPointF) -> None:
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C["accent"]))
    p.drawEllipse(c, 6, 6)


# ---------------------------------------------------------------- faza pucharowa

SIDE_W = 360
CENTER_W = 400
MATCH_ROW_H = 40
BLOCK_H = 22 + 22 + 2 * MATCH_ROW_H + 24       # etykieta, godzina, karta, karne
SECTION_H = 46 + 22 + 2 * BLOCK_H + 18 + 10


def render_knockout(tournament_id: int) -> QImage:
    tournament = tournament_dao.get_tournament(tournament_id)["name"]
    ko = [m for m in schedule.get_schedule(tournament_id) if m["stage"] != "GROUP"]
    if not ko:
        raise ValueError("Faza pucharowa jeszcze się nie zaczęła (brak drabinek).")
    by_stage: dict[str, list[dict]] = {}
    for m in sorted(ko, key=lambda m: m["match_id"]):
        by_stage.setdefault(m["stage"], []).append(m)

    head_h = 160
    height = head_h + 34 + len(KO_SECTIONS) * (SECTION_H + 26) - 26 + 40
    img, p = _new_image(height)
    _header(p, tournament, "FAZA PUCHAROWA", _dates_label(ko))

    y = head_h + 34
    for title, sf_stage, final, place in KO_SECTIONS:
        rect = QRectF(MARGIN, y, WIDTH - 2 * MARGIN, SECTION_H)
        body = _card(p, rect, title)
        _ko_section(p, body, by_stage.get(sf_stage, []),
                    (final[1], (by_stage.get(final[0]) or [None])[0]),
                    (place[1], (by_stage.get(place[0]) or [None])[0]))
        y += SECTION_H + 26

    p.end()
    return img


def _ko_section(p: QPainter, body: QRectF, semis: list[dict], final, place) -> None:
    top = body.y() + 22
    center_x = body.center().x() - CENTER_W / 2
    final_r = QRectF(center_x, top, CENTER_W, BLOCK_H)
    place_r = QRectF(center_x, top + BLOCK_H + 18, CENTER_W, BLOCK_H)
    semi_y = body.y() + (body.height() - BLOCK_H) / 2
    semi_rects = [QRectF(body.x() + 30, semi_y, SIDE_W, BLOCK_H),
                  QRectF(body.right() - 30 - SIDE_W, semi_y, SIDE_W, BLOCK_H)]

    # linie: półfinał → finał (ciągła), półfinał → mecz o miejsce (przerywana)
    for sr, left in zip(semi_rects, (True, False)):
        card_mid = sr.y() + 44 + MATCH_ROW_H
        sx = sr.right() if left else sr.left()
        for target, style in ((final_r, Qt.SolidLine), (place_r, Qt.DashLine)):
            tx = target.left() if left else target.right()
            ty = target.y() + 44 + MATCH_ROW_H
            mid_x = (sx + tx) / 2
            p.setPen(QPen(QColor(C["line"]), 2, style))
            p.setBrush(Qt.NoBrush)
            path = QPainterPath(QPointF(sx, card_mid))
            path.lineTo(mid_x, card_mid)
            path.lineTo(mid_x, ty)
            path.lineTo(tx, ty)
            p.drawPath(path)

    for i, sr in enumerate(semi_rects):
        _ko_block(p, sr, f"PÓŁFINAŁ {i + 1}", semis[i] if i < len(semis) else None)
    _ko_block(p, final_r, *final, highlight=True)
    _ko_block(p, place_r, *place)


def _ko_block(p: QPainter, r: QRectF, label: str, m: dict | None, highlight: bool = False) -> None:
    _text(p, QRectF(r.x(), r.y(), r.width(), 22), label, 14, weight=QFont.Bold,
          color="accent" if highlight else "muted", align=Qt.AlignCenter, spacing=1.5)
    t = _time(m["scheduled_at"]) if m else ""
    _text(p, QRectF(r.x(), r.y() + 22, r.width(), 22), f"godz. {t}" if t else "", 14,
          weight=QFont.DemiBold, align=Qt.AlignCenter)

    card = QRectF(r.x(), r.y() + 44, r.width(), 2 * MATCH_ROW_H)
    _rect(p, card, "card", 10, "accent" if highlight else "border")
    p.setPen(QPen(QColor(C["border"]), 1))
    p.drawLine(QPointF(card.x() + 1, card.y() + MATCH_ROW_H), QPointF(card.right() - 1, card.y() + MATCH_ROW_H))

    winner = None
    if m and m["played"]:
        if m["winner_pen"] is not None:
            winner = "home" if m["winner_pen"] == 0 else "away"
        else:
            winner = "home" if m["home_score"] > m["away_score"] else "away"
    for i, side in enumerate(("home", "away")):
        row = QRectF(card.x(), card.y() + i * MATCH_ROW_H, card.width(), MATCH_ROW_H)
        won = winner == side
        if won:
            _rect(p, QRectF(row.x() + 1, row.y() + 6, 4, row.height() - 12), "accent", 2)
        name = _name(m[f"{side}_team_name"]) if m else "—"
        _text(p, QRectF(row.x() + 16, row.y(), row.width() - 76, row.height()), name, 16,
              weight=QFont.Bold if won else QFont.DemiBold,
              color="text" if (m and m[f"{side}_team_name"]) else "muted")
        score_box = QRectF(row.right() - 52, row.y() + 6, 44, row.height() - 12)
        played = bool(m and m["played"])
        _rect(p, score_box, ("accent" if won else "soft") if played else "pill_off", 7)
        _text(p, score_box, str(m[f"{side}_score"]) if played else "–", 17, weight=QFont.Bold,
              color="#ffffff" if won else ("text" if played else "muted"), align=Qt.AlignCenter)

    pens = _pens(m) if m and m["played"] else ""
    if pens:
        _text(p, QRectF(r.x(), card.bottom() + 2, r.width(), 22), pens, 13,
              weight=QFont.DemiBold, color="muted", align=Qt.AlignCenter)
