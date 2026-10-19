"""Generuje diagram schematu bazy (docs/schema.png) prosto z db/schema.sql.

Uruchom po każdej zmianie schematu:
    python -m tools.schema_diagram

Tabele, kolumny, typy, NOT NULL, klucze główne i obce są odczytywane z bazy
w pamięci (PRAGMA table_info / foreign_key_list), więc obrazek zawsze zgadza
się ze schematem. Ręcznie ustalone jest tylko rozmieszczenie tabel (LAYOUT).
"""
import pathlib
import sqlite3
import sys

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QFontMetrics, QPen, QPainterPath
from PySide6.QtWidgets import QApplication

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "schema.sql"
OUT = ROOT / "docs" / "schema.png"

SCALE = 2
TABLE_W = 300
HEAD_H = 34
ROW_H = 30
FONT = "Segoe UI"
MONO = "Consolas"

# Układ warstwowy: tabela -> (kolumna, y). Klucze obce wskazują zawsze w lewo,
# do niższej warstwy: tournament <- team <- player/match <- goal/penalty_kick/transfer.
LAYOUT = {
    "tournament":   (0, 120),
    "team":         (1, 120),
    "player":       (2, 120),
    "match":        (2, 290),
    "transfer":     (3, 120),
    "goal":         (3, 370),
    "penalty_kick": (3, 520),
}
MARGIN, GAP = 40, 150           # GAP: korytarz na linie między kolumnami
BUS_TOP = 24                    # linie przeskakujące kolumny biegną górą, nad tabelami
LANE = 11
WIDTH = 2 * MARGIN + 4 * TABLE_W + 3 * GAP
HEIGHT = 720

C = {
    "bg": "#fafafa", "head": "#316896", "head_text": "#ffffff", "card": "#f3f4f6",
    "border": "#d9dde3", "text": "#2b2f36", "type": "#6b7280", "badge": "#e5e7eb",
    "line": "#9aa3ae", "pk": "#316896",
}


def load_schema():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    tables = {}
    for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
        cols = [dict(cid=r[0], name=r[1], type=(r[2] or "").lower(), notnull=bool(r[3]),
                     pk=bool(r[5])) for r in conn.execute(f"PRAGMA table_info({name})")]
        fks = {r[3]: (r[2], r[4]) for r in conn.execute(f"PRAGMA foreign_key_list({name})")}
        for c in cols:
            c["fk"] = fks.get(c["name"])
        tables[name] = cols
    missing = set(tables) - set(LAYOUT)
    if missing:
        sys.exit(f"Dodaj nowe tabele do LAYOUT w {__file__}: {', '.join(sorted(missing))}")
    return tables


def font(px, bold=False, mono=False):
    f = QFont(MONO if mono else FONT)
    f.setPixelSize(px)
    f.setBold(bold)
    return f


def pos(table):
    col, y = LAYOUT[table]
    return MARGIN + col * (TABLE_W + GAP), y


def row_y(table, col_name, tables):
    x, y = pos(table)
    idx = next(i for i, c in enumerate(tables[table]) if c["name"] == col_name)
    return y + HEAD_H + idx * ROW_H + ROW_H / 2


def table_h(cols):
    return HEAD_H + len(cols) * ROW_H


def draw_table(p, name, cols):
    x, y = pos(name)
    rect = QRectF(x, y, TABLE_W, table_h(cols))
    p.setPen(QPen(QColor(C["border"]), 1))
    p.setBrush(QColor(C["card"]))
    p.drawRoundedRect(rect, 4, 4)
    head = QRectF(x, y, TABLE_W, HEAD_H)
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    path.addRoundedRect(head, 4, 4)
    path.addRect(QRectF(x, y + HEAD_H / 2, TABLE_W, HEAD_H / 2))
    p.fillPath(path.simplified(), QColor(C["head"]))
    p.setFont(font(14, bold=True))
    p.setPen(QColor(C["head_text"]))
    p.drawText(head.adjusted(12, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, name)

    for i, c in enumerate(cols):
        ry = y + HEAD_H + i * ROW_H
        r = QRectF(x, ry, TABLE_W, ROW_H)
        if i:
            p.setPen(QPen(QColor(C["border"]), 0.6))
            p.drawLine(QPointF(x + 8, ry), QPointF(x + TABLE_W - 8, ry))
        # nazwa + znaczniki PK/FK
        label = c["name"]
        p.setFont(font(13, bold=c["pk"]))
        p.setPen(QColor(C["text"]))
        p.drawText(r.adjusted(12, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, label)
        tag_x = x + 12 + QFontMetrics(font(13, bold=c["pk"])).horizontalAdvance(label) + 6
        for tag, show in (("PK", c["pk"]), ("FK", c["fk"])):
            if show:
                p.setFont(font(9, bold=True))
                p.setPen(QColor(C["pk"]))
                p.drawText(QRectF(tag_x, ry, 22, ROW_H), Qt.AlignVCenter | Qt.AlignLeft, tag)
                tag_x += 22
        # typ + NN
        right = x + TABLE_W - 10
        if c["notnull"] and not c["pk"]:
            badge = QRectF(right - 26, ry + 7, 26, ROW_H - 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(C["badge"]))
            p.drawRoundedRect(badge, 3, 3)
            p.setFont(font(10, mono=True))
            p.setPen(QColor(C["type"]))
            p.drawText(badge, Qt.AlignCenter, "NN")
            right -= 32
        p.setFont(font(12, mono=True))
        p.setPen(QColor(C["type"]))
        p.drawText(QRectF(x, ry, right - x, ROW_H), Qt.AlignVCenter | Qt.AlignRight, c["type"])


def draw_relations(p, tables):
    rels = [(t, c["name"], *c["fk"]) for t, cols in tables.items() for c in cols if c["fk"]]
    lanes = {}                                  # korytarz (indeks kolumny po lewej) -> zajęte tory
    bus = 0

    def lane_x(gap_col):
        n = lanes.get(gap_col, 0)
        lanes[gap_col] = n + 1
        center = MARGIN + (gap_col + 1) * TABLE_W + gap_col * GAP + GAP / 2
        return center + (n - 2) * LANE

    for src, col, dst, dst_col in sorted(rels, key=lambda r: (LAYOUT[r[0]][0] - LAYOUT[r[2]][0])):
        cs, cd = LAYOUT[src][0], LAYOUT[dst][0]
        assert cs > cd, f"FK {src}.{col} musi wskazywać tabelę w kolumnie po lewej"
        sx, sy = pos(src)[0], row_y(src, col, tables)
        dx, dy = pos(dst)[0] + TABLE_W, row_y(dst, dst_col, tables)
        path = QPainterPath(QPointF(sx, sy))
        if cs - cd == 1:                        # sąsiednie kolumny: jedno załamanie w korytarzu
            x = lane_x(cd)
            path.lineTo(x, sy)
            path.lineTo(x, dy)
        else:                                   # przeskok: w górę, nad tabelami, w dół
            x1, x2 = lane_x(cs - 1), lane_x(cd)
            yb = BUS_TOP + bus * LANE
            bus += 1
            for pt in ((x1, sy), (x1, yb), (x2, yb), (x2, dy)):
                path.lineTo(*pt)
        path.lineTo(dx, dy)
        p.setPen(QPen(QColor(C["line"]), 1.3))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        # strona „wiele” (FK): kurza łapka; strona „jeden” (PK): kreska
        for k in (-5, 0, 5):
            p.drawLine(QPointF(sx - 9, sy), QPointF(sx, sy + k))
        p.drawLine(QPointF(dx + 7, dy - 5), QPointF(dx + 7, dy + 5))


def main():
    tables = load_schema()
    app = QApplication.instance() or QApplication(sys.argv)  # noqa: F841 — potrzebne dla czcionek
    img = QImage(int(WIDTH * SCALE), int(HEIGHT * SCALE), QImage.Format_RGB32)
    img.fill(QColor(C["bg"]))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    p.scale(SCALE, SCALE)
    draw_relations(p, tables)
    for name, cols in tables.items():
        draw_table(p, name, cols)
    p.end()
    img.save(str(OUT))
    print(f"Zapisano {OUT.relative_to(ROOT)} ({img.width()}x{img.height()})")


if __name__ == "__main__":
    main()
