"""
GraphPanel / GraphView — a read-only, auto-laid-out picture of a flow for
the Editor. Editor-only.

Steps are boxes; each answer is an arrow labelled with the answer text.
Answers that end the flow lead to small green "ending" pills, and an
answer pointing at a step that doesn't exist leads to a red dashed
"missing" pill. The picture also shows:

  * the start step (★), unreachable steps (dashed, dimmed)
  * validation: steps with errors are outlined red, with warnings amber
  * the live Test pane: the current step is filled, the path taken so far
    is drawn in the accent colour
  * the step selected in the outline
  * imported feedback (see feedback.py): arrows thicker where more sessions
    went, never-taken answers dimmed, visit counts on steps, helpful-rate
    on endings, and a numbered badge on steps that have comments

Click a step to select it in the outline. Ctrl+wheel zooms, drag pans.
Export writes the whole graph as PNG or SVG (for client sign-off).
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsPathItem, QGraphicsSimpleTextItem, QGraphicsPolygonItem, QPushButton, QLabel,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QSizeF
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPolygonF,
)

import theme
from engine import Tree, SEVERITY_ERROR
from feedback import FlowFeedback, ending_key
from graph_layout import layout

NODE_W, NODE_H = 190, 64
END_W, END_H = 150, 46
X_GAP, Y_GAP = 110, 26
LABEL_W = X_GAP - 14
AMBER = "#D8A23A"
EXPORT_MARGIN = 24

STEP, ENDING, MISSING = "s", "e", "m"


def _key(kind: str, *parts) -> str:
    return ":".join([kind, *map(str, parts)])


class _Node(QGraphicsRectItem):
    """A clickable box; clicking selects `step_id` in the outline."""

    def __init__(self, rect: QRectF, step_id: str | None, on_click):
        super().__init__(rect)
        self.step_id = step_id
        self._on_click = on_click
        if step_id:
            self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        if self.step_id and event.button() == Qt.LeftButton:
            self._on_click(self.step_id)
        super().mousePressEvent(event)


class GraphView(QGraphicsView):
    node_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setBackgroundBrush(QColor(theme.BG))

        self.tree = Tree()
        self.base_issues = []
        self.current_id: str | None = None
        self.path: list[tuple[str, int]] = []   # (step_id, option_index) answers taken so far
        self.selected_id: str | None = None
        self.feedback: FlowFeedback | None = None

    # ---------- public API ----------

    def set_feedback(self, feedback: FlowFeedback | None):
        self.feedback = feedback
        self.rebuild()

    def set_tree(self, tree: Tree, issues=None):
        self.tree = tree
        self.base_issues = tree.check() if issues is None else issues
        self.rebuild()

    def set_progress(self, current_id: str | None, path: list[tuple[str, int]]):
        self.current_id, self.path = current_id, list(path)
        self.rebuild()

    def set_selected(self, step_id: str | None):
        if step_id != self.selected_id:
            self.selected_id = step_id
            self.rebuild()

    def fit(self):
        rect = self._scene.itemsBoundingRect()
        if not rect.isEmpty():
            self.resetTransform()
            self.fitInView(rect.adjusted(-20, -20, 20, 20), Qt.KeepAspectRatio)
            if self.transform().m11() > 1.0:   # don't blow small flows up past 100%
                self.resetTransform()

    def render_to_painter(self, painter: QPainter, target: QRectF):
        source = self._scene.itemsBoundingRect().adjusted(-EXPORT_MARGIN, -EXPORT_MARGIN, EXPORT_MARGIN, EXPORT_MARGIN)
        self._scene.render(painter, target, source)

    def export_size(self) -> QSizeF:
        return self._scene.itemsBoundingRect().adjusted(
            -EXPORT_MARGIN, -EXPORT_MARGIN, EXPORT_MARGIN, EXPORT_MARGIN).size()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)

    # ---------- building the picture ----------

    def _graph(self):
        """(node keys in stable order, edges as (src, dst, step_id, option_index, label), endings, missing)."""
        t = self.tree
        keys = [_key(STEP, sid) for sid in t.steps]
        edges = []
        for sid, step in t.steps.items():
            for i, o in enumerate(step.options):
                if o.next_id and o.next_id in t.steps:
                    dst = _key(STEP, o.next_id)
                elif o.next_id:
                    dst = _key(MISSING, sid, i)
                    keys.append(dst)
                else:
                    dst = _key(ENDING, sid, i)
                    keys.append(dst)
                edges.append((_key(STEP, sid), dst, sid, i, o.label, len(step.options)))
        return keys, edges

    def rebuild(self):
        scene = self._scene
        scene.clear()
        t = self.tree
        if not t.steps:
            return

        keys, edges = self._graph()
        placed = layout(keys, [(e[0], e[1]) for e in edges], _key(STEP, t.root_id) if t.root_id else None)

        issues_by_step: dict[str, list] = {}
        for issue in self.base_issues:
            if issue.step_id:
                issues_by_step.setdefault(issue.step_id, []).append(issue)
        unreachable = set(t.steps) - t.reachable_ids() if t.root_id in t.steps else set()
        visited = {sid for sid, _ in self.path} | ({self.current_id} if self.current_id else set())
        path_edges = set(self.path)

        col_w, row_h = NODE_W + X_GAP, NODE_H + Y_GAP
        boxes: dict[str, QRectF] = {}
        for key, p in placed.items():
            kind = key.split(":", 1)[0]
            w, h = (NODE_W, NODE_H) if kind == STEP else (END_W, END_H)
            x = p.layer * col_w + (NODE_W - w) / 2
            y = p.row * row_h + (NODE_H - h) / 2
            boxes[key] = QRectF(x, y, w, h)

        # edges first so nodes draw over their ends
        fb = self.feedback
        for src, dst, sid, i, label, n_options in edges:
            traffic = fb.edge_counts.get((sid, i), 0) if fb else None
            self._draw_edge(boxes[src], boxes[dst], label, i, n_options, traffic, taken=(sid, i) in path_edges,
                            broken=dst.startswith(MISSING + ":"), backwards=placed[dst].layer <= placed[src].layer)

        for key, box in boxes.items():
            kind, _, rest = key.partition(":")
            if kind == STEP:
                self._draw_step(box, t.steps[rest], issues_by_step.get(rest, []), rest in unreachable,
                                rest in visited, rest == self.current_id)
            elif kind == ENDING:
                sid, idx = rest.rsplit(":", 1)
                o = t.steps[sid].options[int(idx)]
                ending = t.ending_for(o)
                text = ending.text if ending else ""
                lines = text.strip().splitlines()
                stat = fb.endings.get(ending_key(t, sid, int(idx))) if fb else None
                self._draw_pill(box, "✓ " + (lines[0] if lines else "(no resolution)"), theme.GREEN, sid,
                                taken=(sid, int(idx)) in path_edges, tip=text, stat=stat,
                                with_stats=fb is not None)
            else:
                sid, idx = rest.rsplit(":", 1)
                o = t.steps[sid].options[int(idx)]
                self._draw_pill(box, f"✖ missing: {o.next_id}", theme.RED, sid, dashed=True,
                                tip=f"'{sid}' points at '{o.next_id}', which doesn't exist.")

        bounds = scene.itemsBoundingRect()
        scene.setSceneRect(bounds.adjusted(-200, -200, 200, 200))

    def _pen(self, color: str, width: float = 1.5, dashed: bool = False) -> QPen:
        pen = QPen(QColor(color), width)
        if dashed:
            pen.setStyle(Qt.DashLine)
        return pen

    def _draw_step(self, box, step, issues, unreachable, visited, current):
        is_root = step.id == self.tree.root_id
        errors = [i for i in issues if i.severity == SEVERITY_ERROR]
        if errors:
            border = theme.RED
        elif issues and not unreachable:
            border = AMBER
        elif visited:
            border = theme.GOLD
        else:
            border = theme.BORDER
        selected = step.id == self.selected_id
        node = _Node(box, step.id, self.node_clicked.emit)
        node.setBrush(QBrush(self._fill(current)))
        node.setPen(self._pen(theme.GOLD_BRIGHT if selected else border, 3 if selected else 2 if is_root or visited else 1.5,
                              dashed=unreachable))
        tip = [f"{step.id}: {step.question}"] + [f"{'✖' if i.is_error else '⚠'} {i.message}" for i in issues]
        if unreachable:
            tip.append("Unreachable from the start step.")
        node.setToolTip("\n".join(tip))
        self._scene.addItem(node)

        dim = unreachable and not visited
        title_font = QFont(self.font())
        title_font.setPointSize(10)
        title_font.setBold(True)
        first_line = (step.question.strip().splitlines() or ["(no question)"])[0]
        title = self._text(("★ " if is_root else "") + first_line, node, title_font,
                           theme.TEXT_DIM if dim else theme.TEXT, NODE_W - 20)
        title.setPos(box.x() + 10, box.y() + 8)
        sub_font = QFont(self.font())
        sub_font.setPointSize(8)
        detail = f"{step.id} · {len(step.options)} answer{'s' if len(step.options) != 1 else ''}"
        fb = self.feedback
        if fb is not None:
            n = fb.step_visits.get(step.id, 0)
            detail += f" · {n} visit{'s' if n != 1 else ''}"
        sub = self._text(detail, node, sub_font, theme.TEXT_DIM, NODE_W - 20)
        sub.setPos(box.x() + 10, box.y() + 31)
        if fb is not None and fb.comments.get(step.id):
            self._draw_comment_badge(box, fb.comments[step.id], node)

    def _draw_comment_badge(self, box: QRectF, comments, node):
        """A small numbered bubble on the step's top-right corner; its tooltip lists the comments."""
        d = 22
        badge = QGraphicsRectItem(QRectF(box.right() - d / 2 - 4, box.top() - d / 2, d, d), node)
        badge.setBrush(QColor(theme.GOLD))
        badge.setPen(QPen(QColor(theme.BG), 2))
        mark = {True: "▲", False: "▼", None: "•"}
        badge.setToolTip("\n".join(f"{mark[c.helpful]} {c.text}" + (f"  ({c.ticket_ref})" if c.ticket_ref else "")
                                   for c in comments))
        font = QFont(self.font())
        font.setPointSize(8)
        font.setBold(True)
        label = self._text(str(len(comments)), badge, font, theme.BG, d)
        label.setPos(badge.rect().center().x() - label.boundingRect().width() / 2,
                     badge.rect().center().y() - label.boundingRect().height() / 2)
        badge.setAcceptedMouseButtons(Qt.NoButton)

    def _fill(self, current: bool) -> QColor:
        if current:
            c = QColor(theme.GOLD)
            c.setAlphaF(0.30)
            return c
        return QColor(theme.PANEL)

    def _text(self, text: str, parent, font: QFont, color: str, max_width: int) -> QGraphicsSimpleTextItem:
        elided = QFontMetrics(font).elidedText(text, Qt.ElideRight, max_width)
        item = QGraphicsSimpleTextItem(elided, parent)
        item.setFont(font)
        item.setBrush(QColor(color))
        item.setAcceptedMouseButtons(Qt.NoButton)   # clicks fall through to the node
        return item

    def _draw_pill(self, box, text, color, step_id, dashed=False, taken=False, tip="", stat=None, with_stats=False):
        rate = stat.helpful_rate if stat else None
        if rate is not None and rate < 0.5:
            color = theme.RED                      # techs found this ending unhelpful
        node = _Node(box, step_id, self.node_clicked.emit)
        fill = QColor(color)
        fill.setAlphaF(0.30 if taken else 0.10)
        node.setBrush(QBrush(fill))
        node.setPen(self._pen(theme.GOLD if taken else color, 2 if taken else 1.2, dashed))
        node.setToolTip(tip)
        self._scene.addItem(node)
        font = QFont(self.font())
        font.setPointSize(9)
        label = self._text(text, node, font, color, int(box.width()) - 20)
        line_h = QFontMetrics(font).height()
        if not with_stats:
            label.setPos(box.x() + 10, box.y() + (box.height() - line_h) / 2)
            return
        label.setPos(box.x() + 10, box.y() + 6)
        if stat is None:
            detail = "no sessions"
        else:
            detail = f"{stat.count} session{'s' if stat.count != 1 else ''}"
            if stat.rated:
                detail += f" · {round(100 * stat.helpful_rate)}% helpful"
        small = QFont(self.font())
        small.setPointSize(8)
        sub = self._text(detail, node, small, theme.TEXT_DIM, int(box.width()) - 20)
        sub.setPos(box.x() + 10, box.y() + 6 + line_h + 2)
        if stat is not None:
            node.setToolTip(f"{tip}\n\n{detail}" + (f" ({stat.helpful} yes, {stat.unhelpful} no)" if stat.rated else ""))

    def _draw_edge(self, a: QRectF, b: QRectF, label: str, index: int, n_options: int, traffic, taken: bool, broken: bool, backwards: bool):
        if backwards:   # loop or same-column link: route underneath so it can't cut through boxes
            start, end = QPointF(a.center().x(), a.bottom()), QPointF(b.center().x(), b.bottom())
            drop = 46 + abs(a.center().x() - b.center().x()) * 0.08
            c1, c2 = QPointF(start.x(), start.y() + drop), QPointF(end.x(), end.y() + drop)
        else:
            # each answer leaves from its own point on the right side, so labels don't pile up
            start = QPointF(a.right(), a.top() + a.height() * (index + 1) / (n_options + 1))
            end = QPointF(b.left(), b.center().y())
            dx = max(40.0, (end.x() - start.x()) * 0.5)
            c1, c2 = QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y())
        path = QPainterPath(start)
        path.cubicTo(c1, c2, end)

        color = QColor(theme.GOLD if taken else (theme.RED if broken else theme.TEXT_DIM))
        width = 2.5 if taken else 1.2
        if traffic is not None and not taken:     # feedback loaded: thickness = share of the busiest answer
            peak = self.feedback.max_edge_count or 1
            width = 1.2 + 4.8 * traffic / peak
            if traffic == 0 and not broken:
                color.setAlpha(80)                # never taken
        item = QGraphicsPathItem(path)
        item.setPen(self._pen(color.name(QColor.HexArgb), width, dashed=broken))
        item.setZValue(1 if taken else 0)
        item.setToolTip(label if traffic is None else f"{label}\n{traffic} session{'s' if traffic != 1 else ''}")
        self._scene.addItem(item)

        # arrowhead along the curve's final tangent
        tangent = end - c2
        length = (tangent.x() ** 2 + tangent.y() ** 2) ** 0.5 or 1.0
        ux, uy = tangent.x() / length, tangent.y() / length
        size = 9
        tip = end
        left = QPointF(tip.x() - ux * size + uy * size * 0.5, tip.y() - uy * size - ux * size * 0.5)
        right = QPointF(tip.x() - ux * size - uy * size * 0.5, tip.y() - uy * size + ux * size * 0.5)
        head = QGraphicsPolygonItem(QPolygonF([tip, left, right]))
        head.setBrush(color)
        head.setPen(QPen(Qt.NoPen))
        head.setZValue(item.zValue())
        self._scene.addItem(head)

        font = QFont(self.font())
        font.setPointSize(8)
        shown = label if traffic is None else f"{label} ({traffic})"
        txt = QGraphicsSimpleTextItem(QFontMetrics(font).elidedText(shown, Qt.ElideRight, LABEL_W))
        txt.setFont(font)
        txt.setBrush(QColor(theme.GOLD_BRIGHT if taken else theme.TEXT_DIM))
        txt.setToolTip(label)
        r = txt.boundingRect()
        if backwards:   # under the loop, with a backing so the line doesn't strike through it
            mid = path.pointAtPercent(0.5)
            txt.setPos(mid.x() - r.width() / 2, mid.y() - r.height() / 2)
            bg = QGraphicsRectItem(QRectF(txt.pos().x() - 3, txt.pos().y(), r.width() + 6, r.height()))
            bg.setBrush(QColor(theme.BG))
            bg.setPen(QPen(Qt.NoPen))
            bg.setZValue(2)
            self._scene.addItem(bg)
        else:           # in the gap beside the source box, just above where the arrow leaves
            txt.setPos(start.x() + 6, start.y() - r.height() - 1)
        txt.setZValue(3)
        self._scene.addItem(txt)


class GraphPanel(QWidget):
    """The GraphView plus its toolbar (fit, export, legend)."""
    step_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        fit_btn = QPushButton("Fit")
        fit_btn.clicked.connect(lambda: self.view.fit())
        bar.addWidget(fit_btn)
        png_btn = QPushButton("Export PNG")
        png_btn.clicked.connect(self.export_png)
        bar.addWidget(png_btn)
        svg_btn = QPushButton("Export SVG")
        svg_btn.clicked.connect(self.export_svg)
        bar.addWidget(svg_btn)
        bar.addStretch()
        legend = QLabel("★ start · red/amber = errors/warnings · dashed = unreachable · gold = path in Test"
                        " · thick arrows = busy · numbered badge = comments")
        legend.setProperty("role", "subheading")
        bar.addWidget(legend)
        root.addLayout(bar)
        self.view = GraphView()
        self.view.node_clicked.connect(self.step_selected.emit)
        root.addWidget(self.view, 1)

    # ---------- export ----------

    def _ask_path(self, title: str, name: str, filt: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, title, name, filt)
        return path

    def export_png(self, path: str | None = None, scale: float = 2.0) -> bool:
        path = path or self._ask_path("Export graph as PNG", "flow-graph.png", "PNG image (*.png)")
        if not path:
            return False
        size = self.view.export_size()
        image = QImage(int(size.width() * scale), int(size.height() * scale), QImage.Format_ARGB32)
        image.fill(QColor(theme.BG))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        self.view.render_to_painter(painter, QRectF(0, 0, image.width(), image.height()))
        painter.end()
        if not image.save(path):
            QMessageBox.critical(self, "Couldn't save", f"Couldn't write {path}")
            return False
        return True

    def export_svg(self, path: str | None = None) -> bool:
        from PySide6.QtSvg import QSvgGenerator
        path = path or self._ask_path("Export graph as SVG", "flow-graph.svg", "SVG image (*.svg)")
        if not path:
            return False
        size = self.view.export_size()
        svg = QSvgGenerator()
        svg.setFileName(path)
        svg.setSize(size.toSize())
        svg.setViewBox(QRectF(0, 0, size.width(), size.height()))
        svg.setTitle("Longleaf flow graph")
        painter = QPainter(svg)
        painter.fillRect(QRectF(0, 0, size.width(), size.height()), QColor(theme.BG))
        self.view.render_to_painter(painter, QRectF(0, 0, size.width(), size.height()))
        painter.end()
        return True
