"""
AnalyticsWidget — the Editor's Analytics mode (Editor-only). Loads outcome logs exported
from the Player and shows how a flow is doing: how often it resolves the problem, where
techs give up, which fixes get rejected, what they search for, and the trend over time.
The numbers come from analytics.py; this file only draws them.

Colours: the status colours are fixed per state and never reused for anything else. Red
and green are not told apart by colour alone: "didn't solve it" is hatched, every state
has a glyph and a label with its count, and bars carry hover tooltips.
"""

from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QTabWidget, QToolTip, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen

import analytics as A
import theme
from engine import Tree

STATUS_STYLE = {   # status -> (glyph + label, colour, hatched)
    A.RESOLVED: ("✓ Solved it", theme.GREEN, False),
    A.NOT_RESOLVED: ("✗ Didn't solve it", theme.RED, True),
    A.FINISHED: ("● Finished, not rated", theme.GOLD, False),
    A.ABANDONED: ("↩ Left part-way", theme.TEXT_DIM, False),
    A.RESET: ("⟲ Started over", theme.ORANGE, False),
    A.ERROR: ("⚠ Flow error", "#8A7FB5", True),
    A.OPEN: ("… Still open", "#5A4E3A", False),
}


def clip(text: str, n: int = 64) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


class Names:
    """Readable names for step ids and ending keys, taken from the open flow when it is the flow
    being looked at (same client and title); otherwise the raw ids."""

    def __init__(self, tree: Tree | None, flow: A.FlowAnalytics):
        self.tree = tree if tree is not None and (tree.client or "") == flow.client and tree.title == flow.title else None

    @property
    def known(self) -> bool:
        return self.tree is not None

    def step(self, step_id: str) -> str:
        if self.tree and step_id in self.tree.steps:
            return clip(self.tree.steps[step_id].question, 60) or step_id
        return step_id

    def ending(self, key: str) -> str:
        t = self.tree
        if not t:
            return key
        if key in t.resolutions:
            return clip(t.resolutions[key].text, 70) or key
        sid, _, idx = key.rpartition("#")
        if sid in t.steps and idx.isdigit() and int(idx) < len(t.steps[sid].options):
            o = t.steps[sid].options[int(idx)]
            text = clip(o.resolution or "", 56)
            return f"“{clip(o.label, 28)}” → {text}" if text else f"“{clip(o.label, 28)}” (on {clip(self.step(sid), 34)})"
        return key


def _nice_max(n: int) -> int:
    for step in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000):
        if n <= step * 4 or step == 5000:
            return max(step * ((n + step - 1) // step), 1)
    return n


class StatusBar(QWidget):
    """One horizontal stacked bar of how sessions ended, a 2px gap between segments, with a legend row
    underneath that always names every state and its count (colour is never the only cue)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.counts: dict = {}
        self.setMinimumHeight(64)
        self.setMouseTracking(True)

    def set_counts(self, counts):
        self.counts = {s: counts.get(s, 0) for s in A.STATUS_ORDER if counts.get(s, 0)}
        self.update()

    def _segments(self, width: float):
        total = sum(self.counts.values())
        if not total:
            return []
        usable = width - 2 * (len(self.counts) - 1)
        x, out = 0.0, []
        for s, n in self.counts.items():
            w = max(usable * n / total, 3.0)
            out.append((s, n, QRectF(x, 0, w, 22)))
            x += w + 2
        return out

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        segs = self._segments(self.width())
        for s, _n, r in segs:
            _label, colour, hatched = STATUS_STYLE[s]
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(colour))
            p.drawRoundedRect(r, 4, 4)
            if hatched:
                p.setBrush(QBrush(QColor(theme.BG), Qt.BDiagPattern))
                p.drawRoundedRect(r, 4, 4)
        font = QFont(self.font())
        font.setPointSize(9)
        p.setFont(font)
        p.setPen(QColor(theme.TEXT_DIM))
        x, y = 0, 40
        for s, n in self.counts.items():
            label, colour, _h = STATUS_STYLE[s]
            text = f"{label}  {n}"
            w = p.fontMetrics().horizontalAdvance(text) + 26
            if x + w > self.width() and x:
                x, y = 0, y + 18
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(colour))
            p.drawRoundedRect(QRectF(x, y - 9, 10, 10), 2, 2)
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(int(x + 16), y, text)
            x += w
        self.setMinimumHeight(y + 12)
        p.end()

    def mouseMoveEvent(self, ev):
        for s, n, r in self._segments(self.width()):
            if r.contains(ev.position()):
                total = sum(self.counts.values())
                QToolTip.showText(ev.globalPosition().toPoint(), f"{STATUS_STYLE[s][0]}: {n} of {total} ({round(100 * n / total)}%)", self)
                return
        QToolTip.hideText()


class TrendChart(QWidget):
    """Sessions per day, stacked by how they ended (weeks when the data spans months). One axis."""

    MAX_BARS = 70

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars: list = []     # (label, Counter)
        self.setMinimumHeight(190)
        self.setMouseTracking(True)

    def set_data(self, daily: dict, first: date | None, last: date | None):
        self.bars = []
        if daily and first and last:
            span = (last - first).days + 1
            step = 1 if span <= self.MAX_BARS else 7
            d = first
            while d <= last:
                from collections import Counter
                c = Counter()
                for k in range(step):
                    c.update(daily.get(d + timedelta(days=k), {}))
                label = d.isoformat() if step == 1 else f"week of {d.isoformat()}"
                self.bars.append((label, c))
                d += timedelta(days=step)
        self.update()

    def _geometry(self):
        left, right, top, bottom = 34, 8, 8, 22
        return QRectF(left, top, max(self.width() - left - right, 10), max(self.height() - top - bottom, 10))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        area = self._geometry()
        font = QFont(self.font())
        font.setPointSize(8)
        p.setFont(font)
        if not self.bars:
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(self.rect(), Qt.AlignCenter, "No sessions in this period")
            p.end()
            return
        top = _nice_max(max(sum(c.values()) for _l, c in self.bars))
        for frac in (0.0, 0.5, 1.0):                       # recessive grid, three lines
            y = area.bottom() - area.height() * frac
            p.setPen(QPen(QColor(theme.BORDER), 1))
            p.drawLine(int(area.left()), int(y), int(area.right()), int(y))
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(0, int(y) - 7, 30, 14, Qt.AlignRight | Qt.AlignVCenter, str(round(top * frac)))
        n = len(self.bars)
        slot = area.width() / n
        w = max(min(slot - 2, 22), 2)
        for i, (_label, c) in enumerate(self.bars):
            x = area.left() + i * slot + (slot - w) / 2
            y = area.bottom()
            for s in A.STATUS_ORDER:
                if not c.get(s):
                    continue
                h = max(area.height() * c[s] / top - 2, 1.5)    # 2px surface gap between stacked segments
                r = QRectF(x, y - h, w, h)
                _l, colour, hatched = STATUS_STYLE[s]
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(colour))
                p.drawRoundedRect(r, 2, 2)
                if hatched:
                    p.setBrush(QBrush(QColor(theme.BG), Qt.BDiagPattern))
                    p.drawRoundedRect(r, 2, 2)
                y -= h + 2
        p.setPen(QColor(theme.TEXT_DIM))
        for i in sorted({0, n // 2, n - 1}):
            label = self.bars[i][0].replace("week of ", "")[5:]
            x = area.left() + i * slot + slot / 2
            p.drawText(int(x - 24), int(area.bottom()) + 4, 48, 16, Qt.AlignCenter, label)
        p.end()

    def mouseMoveEvent(self, ev):
        area = self._geometry()
        if self.bars and area.contains(ev.position()):
            i = min(int((ev.position().x() - area.left()) / (area.width() / len(self.bars))), len(self.bars) - 1)
            label, c = self.bars[i]
            lines = [label] + [f"{STATUS_STYLE[s][0]}: {c[s]}" for s in A.STATUS_ORDER if c.get(s)]
            QToolTip.showText(ev.globalPosition().toPoint(), "\n".join(lines) if len(lines) > 1 else f"{label}: no sessions", self)
        else:
            QToolTip.hideText()


class Tile(QFrame):
    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(2)
        self.value = QLabel("—")
        self.value.setStyleSheet("font-size: 26px; font-weight: 700; background: transparent;")
        self.caption = QLabel(caption)
        self.caption.setProperty("role", "subheading")
        self.caption.setStyleSheet("background: transparent;")
        self.note = QLabel("")
        self.note.setProperty("role", "note")
        self.note.setStyleSheet("background: transparent;")
        self.note.setWordWrap(True)
        lay.addWidget(self.caption)
        lay.addWidget(self.value)
        lay.addWidget(self.note)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, value: str, note: str = "", colour: str | None = None):
        self.value.setText(value)
        self.value.setStyleSheet("font-size: 26px; font-weight: 700; background: transparent;" + (f" color: {colour};" if colour else ""))
        self.note.setText(note)


def make_table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setAlternatingRowColors(False)
    t.setShowGrid(False)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
    for i in range(1, len(headers)):
        t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
    return t


class _NumItem(QTableWidgetItem):
    """Sorts by its number, not its text."""

    def __init__(self, text: str, number: float):
        super().__init__(text)
        self.number = number
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.number < getattr(other, "number", 0)


class AnalyticsWidget(QWidget):
    step_selected = Signal(str)     # a card was double-clicked: jump to it in the flow editor

    def __init__(self, parent=None):
        super().__init__(parent)
        self.analytics: A.Analytics | None = None
        self.tree: Tree | None = None
        self.paths: list[str] = []
        self._build_ui()
        self._refresh()

    # ---------- public ----------

    def set_tree(self, tree: Tree | None):
        """The flow open in the Editor, used only to give cards and endings readable names."""
        self.tree = tree
        self._refresh()

    def load_files(self, paths: list[str]) -> int:
        """Add outcome-log files (exact repeats are ignored). Returns how many events were new."""
        events, problems = A.load_logs([*self.paths, *paths])
        before = self.analytics.events if self.analytics else 0
        if events:
            self.paths = [*self.paths, *paths]
            self.analytics = A.analyze(events)
        if problems:
            QMessageBox.warning(self, "Outcome logs", "Some files couldn't be used:\n\n" + "\n".join(problems))
        self._fill_flow_combo()
        self._refresh()
        return (self.analytics.events if self.analytics else 0) - before

    def select_flow(self, key) -> bool:
        """Show one flow (by its (client, title) key). False if it isn't in the loaded logs."""
        for i in range(self.flow_combo.count()):
            if self.flow_combo.itemData(i) == key:
                self.flow_combo.setCurrentIndex(i)
                return True
        return False

    def clear(self):
        self.analytics, self.paths = None, []
        self._fill_flow_combo()
        self._refresh()

    def current_flow(self) -> A.FlowAnalytics | None:
        if not self.analytics or not self.analytics.flows:
            return None
        key = self.flow_combo.currentData()
        return self.analytics.combined() if key is None else self.analytics.flows.get(key) or self.analytics.combined()

    # ---------- UI ----------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        bar = QHBoxLayout()
        title = QLabel("Analytics")
        title.setProperty("role", "heading")
        bar.addWidget(title)
        bar.addSpacing(12)
        self.flow_combo = QComboBox()
        self.flow_combo.setMinimumWidth(260)
        self.flow_combo.currentIndexChanged.connect(lambda _i: self._refresh())
        bar.addWidget(self.flow_combo)
        bar.addStretch()
        self.open_btn = QPushButton("Open outcome logs…")
        self.open_btn.setProperty("role", "primary")
        self.open_btn.clicked.connect(self._open_dialog)
        bar.addWidget(self.open_btn)
        self.export_btn = QPushButton("Export summary…")
        self.export_btn.clicked.connect(self._export_dialog)
        bar.addWidget(self.export_btn)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        bar.addWidget(self.clear_btn)
        root.addLayout(bar)

        self.empty = QLabel(
            "Open one or more outcome logs to see how a flow is doing.\n\n"
            "The Player writes them: File → Export Outcome Log… sends a client's log back as a .jsonl file.\n"
            "You can open several at once (different machines, different weeks); repeated events are ignored.")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.empty.setProperty("role", "note")
        root.addWidget(self.empty, 1)

        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        self.names_note = QLabel("")
        self.names_note.setProperty("role", "note")
        body.addWidget(self.names_note)
        self.tabs = QTabWidget()
        body.addWidget(self.tabs, 1)

        # Overview
        ov = QWidget()
        ovl = QVBoxLayout(ov)
        tiles = QHBoxLayout()
        self.t_sessions, self.t_resolved, self.t_done, self.t_left = (Tile("Sessions"), Tile("Solved it"),
                                                                       Tile("Reached an ending"), Tile("Left or started over"))
        for t in (self.t_sessions, self.t_resolved, self.t_done, self.t_left):
            tiles.addWidget(t)
        ovl.addLayout(tiles)
        self.status_bar = StatusBar()
        ovl.addWidget(self._section("How sessions ended"))
        ovl.addWidget(self.status_bar)
        ovl.addWidget(self._section("Sessions per day"))
        self.trend = TrendChart()
        ovl.addWidget(self.trend)
        ovl.addWidget(self._section("Flows, busiest first"))
        self.flows_table = make_table(["Flow", "Sessions", "Solved it", "Reached an ending", "Left / started over"])
        self.flows_table.cellClicked.connect(self._flow_row_clicked)
        ovl.addWidget(self.flows_table)
        ovl.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(ov)
        scroll.setFrameShape(QFrame.NoFrame)
        self.tabs.addTab(scroll, "Overview")

        # Cards
        self.cards_table = make_table(["Card", "Visits", "Left here", "Left %", "Most chosen answer"])
        self.cards_table.cellDoubleClicked.connect(self._card_double_clicked)
        self.cards_table.setToolTip("Double-click a card to open it in the flow editor")
        self.tabs.addTab(self._with_hint(self.cards_table, "Where techs go and where they give up. Amber = at least 30% of visits ended with the tech leaving or starting over."), "Cards")

        # Endings
        self.endings_table = make_table(["Ending", "Reached", "Finished here", "Solved it", "Rejected", "Rejected %"])
        self.tabs.addTab(self._with_hint(self.endings_table, "Orange = rejected in at least half of 3+ sightings. Red = found unhelpful by most who rated it."), "Endings")

        # Searches
        sw = QWidget()
        sl = QVBoxLayout(sw)
        sl.addWidget(self._section("Searches that found nothing — add tags for these"))
        self.nores_table = make_table(["Search", "Times"])
        sl.addWidget(self.nores_table)
        sl.addWidget(self._section("What techs search for"))
        self.search_table = make_table(["Search", "Times"])
        sl.addWidget(self.search_table)
        self.tabs.addTab(sw, "Searches")
        root.addWidget(self.body, 1)

    @staticmethod
    def _section(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setProperty("role", "subheading")
        return lab

    @staticmethod
    def _with_hint(table: QTableWidget, hint: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        h = QLabel(hint)
        h.setProperty("role", "note")
        h.setWordWrap(True)
        lay.addWidget(h)
        lay.addWidget(table, 1)
        return w

    # ---------- dialogs ----------

    def _open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open outcome logs", "", "Outcome log (*.jsonl);;All files (*)")
        if paths:
            self.load_files(paths)

    def _export_dialog(self):
        flow = self.current_flow()
        if not flow:
            return
        slug = "".join(c if c.isalnum() else "-" for c in flow.name).strip("-").lower() or "flows"
        path, _ = QFileDialog.getSaveFileName(self, "Export summary", f"flow-review-{slug}.md", "Markdown (*.md)")
        if path:
            self.export_summary(path)

    def export_summary(self, path: str):
        flow = self.current_flow()
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(A.to_markdown(flow, Names(self.tree, flow)))
        except OSError as e:
            QMessageBox.critical(self, "Couldn't save the summary", str(e))

    # ---------- filling the view ----------

    def _fill_flow_combo(self):
        keep = self.flow_combo.currentData()
        self.flow_combo.blockSignals(True)
        self.flow_combo.clear()
        if self.analytics and self.analytics.flows:
            if len(self.analytics.flows) > 1:
                self.flow_combo.addItem(f"All flows ({self.analytics.sessions} sessions)", userData=None)
            for f in self.analytics.ranked():
                self.flow_combo.addItem(f"{f.name} ({f.sessions})", userData=f.key)
            for i in range(self.flow_combo.count()):          # keep showing the same flow after more logs are loaded
                if self.flow_combo.itemData(i) == keep:
                    self.flow_combo.setCurrentIndex(i)
                    break
        self.flow_combo.blockSignals(False)

    def _refresh(self):
        flow = self.current_flow()
        has = flow is not None
        self.empty.setVisible(not has)
        self.body.setVisible(has)
        self.flow_combo.setVisible(has)
        self.export_btn.setEnabled(has)
        self.clear_btn.setEnabled(has)
        if not has:
            return
        single = self.flow_combo.currentData() is not None or len(self.analytics.flows) == 1
        names = Names(self.tree, flow)
        self.names_note.setText(
            "" if not single else "Card names are from the flow open in the Editor." if names.known
            else "Open this flow in the Editor to see card names instead of ids.")
        c = flow.statuses
        self.t_sessions.set(str(flow.sessions), f"{flow.first_day} to {flow.last_day}" if flow.first_day else "")
        trend = flow.trend()
        delta = ""
        if trend:
            d = round((trend[0] - trend[1]) * 100)
            delta = f"{'▲' if d > 0 else '▼' if d < 0 else '■'} {abs(d)} points vs the week before"
        self.t_resolved.set(A.pct(flow.resolution_rate), f"{c[A.RESOLVED]} of {flow.rated} rated" + (f"\n{delta}" if delta else ""))
        self.t_done.set(A.pct(flow.completion_rate), f"{flow.statuses[A.RESOLVED] + flow.statuses[A.NOT_RESOLVED] + flow.statuses[A.FINISHED]} sessions")
        self.t_left.set(A.pct(flow.abandon_rate), f"{c[A.ABANDONED]} left · {c[A.RESET]} started over"
                        + (f" · most on one call: {flow.max_restarts}" if flow.max_restarts else ""))
        self.status_bar.set_counts(c)
        self.trend.set_data(flow.daily, flow.first_day, flow.last_day)
        self._fill_flows_table()
        self.tabs.setTabEnabled(1, single)
        self.tabs.setTabEnabled(2, single)
        self._fill_cards(flow, names)
        self._fill_endings(flow, names)
        self._fill_searches(flow)

    def _fill_flows_table(self):
        t = self.flows_table
        t.setSortingEnabled(False)
        flows = self.analytics.ranked()
        t.setRowCount(len(flows))
        for r, f in enumerate(flows):
            first = QTableWidgetItem(f.name)
            first.setData(Qt.UserRole, f.key)
            t.setItem(r, 0, first)
            t.setItem(r, 1, _NumItem(str(f.sessions), f.sessions))
            t.setItem(r, 2, _NumItem(A.pct(f.resolution_rate), f.resolution_rate or -1))
            t.setItem(r, 3, _NumItem(A.pct(f.completion_rate), f.completion_rate or -1))
            t.setItem(r, 4, _NumItem(A.pct(f.abandon_rate), f.abandon_rate or -1))
        t.setSortingEnabled(True)
        t.setMaximumHeight(60 + 30 * len(flows))

    def _flow_row_clicked(self, row: int, _col: int):
        self.select_flow(self.flows_table.item(row, 0).data(Qt.UserRole))

    def _fill_cards(self, flow: A.FlowAnalytics, names: Names):
        t = self.cards_table
        t.setSortingEnabled(False)
        rows = sorted(flow.steps.values(), key=lambda s: (-s.left_here, -s.visits, s.step_id))
        t.setRowCount(len(rows))
        amber = QColor(theme.GOLD_BRIGHT)
        for r, s in enumerate(rows):
            top = max(((i, n) for (sid, i), n in flow.answers.items() if sid == s.step_id), key=lambda x: x[1], default=None)
            label = ""
            if top and names.tree and s.step_id in names.tree.steps and top[0] < len(names.tree.steps[s.step_id].options):
                label = f"“{clip(names.tree.steps[s.step_id].options[top[0]].label, 28)}” ×{top[1]}"
            elif top:
                label = f"answer {top[0] + 1} ×{top[1]}"
            item = QTableWidgetItem(names.step(s.step_id))
            item.setData(Qt.UserRole, s.step_id)
            item.setToolTip(s.step_id)
            t.setItem(r, 0, item)
            t.setItem(r, 1, _NumItem(str(s.visits), s.visits))
            t.setItem(r, 2, _NumItem(str(s.left_here), s.left_here))
            t.setItem(r, 3, _NumItem(A.pct(s.drop_off_rate), s.drop_off_rate or 0))
            t.setItem(r, 4, QTableWidgetItem(label))
            if s.high_drop_off:
                for c in range(5):
                    t.item(r, c).setForeground(amber)
                t.item(r, 3).setText(A.pct(s.drop_off_rate) + "  ⚠")
        t.setSortingEnabled(True)

    def _fill_endings(self, flow: A.FlowAnalytics, names: Names):
        t = self.endings_table
        t.setSortingEnabled(False)
        rows = sorted(flow.endings.values(), key=lambda e: (-e.reached, e.key))
        t.setRowCount(len(rows))
        for r, e in enumerate(rows):
            item = QTableWidgetItem(names.ending(e.key))
            item.setToolTip(e.key)
            t.setItem(r, 0, item)
            t.setItem(r, 1, _NumItem(str(e.reached), e.reached))
            t.setItem(r, 2, _NumItem(str(e.finished), e.finished))
            t.setItem(r, 3, _NumItem(A.pct(e.helpful_rate) + (f" of {e.rated}" if e.rated else ""), e.helpful_rate if e.helpful_rate is not None else -1))
            t.setItem(r, 4, _NumItem(str(e.rejected), e.rejected))
            t.setItem(r, 5, _NumItem(A.pct(e.rejection_rate) + ("  ⚠" if e.high_rejection else ""), e.rejection_rate or 0))
            colour = QColor(theme.ORANGE) if e.high_rejection else QColor(theme.RED) if (e.rated and e.helpful_rate < 0.5) else None
            if colour:
                for c in range(6):
                    t.item(r, c).setForeground(colour)
        t.setSortingEnabled(True)

    def _fill_searches(self, flow: A.FlowAnalytics):
        for table, counter in ((self.nores_table, flow.no_results), (self.search_table, flow.searches)):
            table.setSortingEnabled(False)
            rows = counter.most_common(30)
            table.setRowCount(len(rows))
            for r, (q, n) in enumerate(rows):
                table.setItem(r, 0, QTableWidgetItem(q))
                table.setItem(r, 1, _NumItem(str(n), n))
            table.setSortingEnabled(True)

    def _card_double_clicked(self, row: int, _col: int):
        sid = self.cards_table.item(row, 0).data(Qt.UserRole)
        if self.tree and sid in self.tree.steps:
            self.step_selected.emit(sid)
