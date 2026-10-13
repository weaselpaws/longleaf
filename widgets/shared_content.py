"""
Shared content dialogs (Editor-only): create, edit and delete the flow's
shared resolutions and KB articles, and pick which articles a step or
resolution offers.

SharedContentDialog edits a *copy* of the flow, so Cancel really cancels and
the Editor records the whole change as one undo step on OK.
"""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from engine import Tree
from theme import RED, TEXT_DIM
from widgets.image_picker import ImagePicker


def resolution_label(text: str, rid: str) -> str:
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return (first[:48] + "…" if len(first) > 48 else first) or f"({rid}: no text)"


def article_summary(tree: Tree, ids: list[str]) -> str:
    if not ids:
        return "None"
    return ", ".join(tree.articles[a].title or a if a in tree.articles else f"⚠ {a} (missing)" for a in ids)


def choose_articles(parent, tree: Tree, selected: list[str]) -> list[str] | None:
    """Tick the KB articles to offer. Returns the new id list, or None if cancelled."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("KB articles to offer")
    dlg.resize(380, 320)
    layout = QVBoxLayout(dlg)
    if not tree.articles and not selected:
        layout.addWidget(QLabel("This flow has no KB articles yet. Add some under Shared → KB articles."))
    lst = QListWidget()
    for aid in [*tree.articles, *[a for a in selected if a not in tree.articles]]:
        art = tree.articles.get(aid)
        item = QListWidgetItem(art.title or aid if art else f"⚠ {aid} (missing — untick to remove)")
        item.setData(Qt.UserRole, aid)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if aid in selected else Qt.Unchecked)
        lst.addItem(item)
    layout.addWidget(lst, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    if dlg.exec() != QDialog.Accepted:
        return None
    return [lst.item(i).data(Qt.UserRole) for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]


class _ArticleField(QWidget):
    """A one-line summary of which articles are offered, plus a Choose… button."""

    def __init__(self, tree: Tree, on_change, parent=None):
        super().__init__(parent)
        self.tree, self.on_change = tree, on_change
        self.ids: list[str] = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("None")
        self.summary.setWordWrap(True)
        row.addWidget(self.summary, 1)
        btn = QPushButton("Choose…")
        btn.clicked.connect(self._choose)
        row.addWidget(btn)

    def set_ids(self, ids: list[str]):
        self.ids = ids
        self.summary.setText(article_summary(self.tree, ids))

    def _choose(self):
        picked = choose_articles(self, self.tree, self.ids)
        if picked is not None:
            self.on_change(picked)
            self.set_ids(picked)


class _ResolutionsTab(QWidget):
    def __init__(self, tree: Tree, base_dir_provider, parent=None):
        super().__init__(parent)
        self.tree = tree
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton("+ New")
        add.clicked.connect(self._add)
        row.addWidget(add)
        delete = QPushButton("Delete")
        delete.setProperty("role", "danger")
        delete.clicked.connect(self._delete)
        row.addWidget(delete)
        left.addLayout(row)
        root.addLayout(left, 1)

        self.form = QWidget()
        form = QFormLayout(self.form)
        self.id_label = QLabel("")
        self.id_label.setStyleSheet(f"color: {TEXT_DIM};")
        form.addRow("Id:", self.id_label)
        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText("What the tech is told to do. Shown at every path that ends here.")
        self.text_input.textChanged.connect(self._text_changed)
        form.addRow("Resolution:", self.text_input)
        self.image_picker = ImagePicker("Screenshot (optional)", base_dir_provider=base_dir_provider)
        self.image_picker.changed.connect(self._image_changed)
        form.addRow("Screenshot:", self.image_picker)
        self.articles = _ArticleField(tree, self._articles_changed)
        form.addRow("KB articles:", self.articles)
        self.used_label = QLabel("")
        self.used_label.setStyleSheet(f"color: {TEXT_DIM};")
        form.addRow(self.used_label)
        root.addWidget(self.form, 2)
        self.refresh()

    def _current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def refresh(self, select: str | None = None):
        keep = select or self._current_id()
        self.list.blockSignals(True)
        self.list.clear()
        for rid, res in self.tree.resolutions.items():
            item = QListWidgetItem(resolution_label(res.text, rid))
            item.setData(Qt.UserRole, rid)
            self.list.addItem(item)
            if rid == keep:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._select(self.list.currentItem(), None)

    def _uses(self, rid: str) -> int:
        return sum(o.resolution_id == rid for s in self.tree.steps.values() for o in s.options)

    def _select(self, item, _prev):
        rid = item.data(Qt.UserRole) if item else None
        res = self.tree.resolutions.get(rid) if rid else None
        self.form.setEnabled(res is not None)
        for w in (self.text_input,):
            w.blockSignals(True)
        self.text_input.setPlainText(res.text if res else "")
        self.text_input.blockSignals(False)
        self.image_picker.set_path(res.image if res else "")
        self.articles.set_ids(list(res.articles) if res else [])
        self.id_label.setText(rid or "")
        n = self._uses(rid) if rid else 0
        self.used_label.setText("" if not res else f"Used by {n} answer{'s' if n != 1 else ''}."
                                + ("" if n else " Nothing ends here yet."))

    def _add(self):
        res = self.tree.add_resolution()
        self.refresh(select=res.id)
        self.text_input.setFocus()

    def _delete(self):
        rid = self._current_id()
        if not rid:
            return
        n = self._uses(rid)
        if n and QMessageBox.question(
                self, "Delete shared resolution",
                f"{n} answer{'s' if n != 1 else ''} end{'s' if n == 1 else ''} here. They will be left with no ending "
                f"until you give them one. Delete it?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.tree.delete_resolution(rid)
        self.refresh()

    def _text_changed(self):
        rid = self._current_id()
        if rid in self.tree.resolutions:
            self.tree.resolutions[rid].text = self.text_input.toPlainText()
            self.list.currentItem().setText(resolution_label(self.text_input.toPlainText(), rid))

    def _image_changed(self, rel: str):
        rid = self._current_id()
        if rid in self.tree.resolutions:
            self.tree.resolutions[rid].image = rel

    def _articles_changed(self, ids: list[str]):
        rid = self._current_id()
        if rid in self.tree.resolutions:
            self.tree.resolutions[rid].articles = ids


class _ArticlesTab(QWidget):
    def __init__(self, tree: Tree, parent=None):
        super().__init__(parent)
        self.tree = tree
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._select)
        left.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton("+ New")
        add.clicked.connect(self._add)
        row.addWidget(add)
        delete = QPushButton("Delete")
        delete.setProperty("role", "danger")
        delete.clicked.connect(self._delete)
        row.addWidget(delete)
        left.addLayout(row)
        root.addLayout(left, 1)

        self.form = QWidget()
        form = QFormLayout(self.form)
        self.id_label = QLabel("")
        self.id_label.setStyleSheet(f"color: {TEXT_DIM};")
        form.addRow("Id:", self.id_label)
        self.title_input = QLineEdit()
        self.title_input.textChanged.connect(self._title_changed)
        form.addRow("Title:", self.title_input)
        self.body_input = QPlainTextEdit()
        self.body_input.setPlaceholderText("Text the tech reads (plain text; web addresses become links).")
        self.body_input.textChanged.connect(self._body_changed)
        form.addRow("Text:", self.body_input)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Link to the article in the client's own knowledge base (optional)")
        self.url_input.textChanged.connect(self._url_changed)
        form.addRow("Link:", self.url_input)
        self.used_label = QLabel("")
        self.used_label.setStyleSheet(f"color: {TEXT_DIM};")
        form.addRow(self.used_label)
        root.addWidget(self.form, 2)
        self.refresh()

    def _current_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def refresh(self, select: str | None = None):
        keep = select or self._current_id()
        self.list.blockSignals(True)
        self.list.clear()
        for aid, art in self.tree.articles.items():
            item = QListWidgetItem(art.title or f"({aid}: no title)")
            item.setData(Qt.UserRole, aid)
            self.list.addItem(item)
            if aid == keep:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._select(self.list.currentItem(), None)

    def _offered_by(self, aid: str) -> int:
        return (sum(aid in s.articles for s in self.tree.steps.values())
                + sum(aid in r.articles for r in self.tree.resolutions.values()))

    def _select(self, item, _prev):
        aid = item.data(Qt.UserRole) if item else None
        art = self.tree.articles.get(aid) if aid else None
        self.form.setEnabled(art is not None)
        for w in (self.title_input, self.body_input, self.url_input):
            w.blockSignals(True)
        self.title_input.setText(art.title if art else "")
        self.body_input.setPlainText(art.body if art else "")
        self.url_input.setText(art.url if art else "")
        for w in (self.title_input, self.body_input, self.url_input):
            w.blockSignals(False)
        self.id_label.setText(aid or "")
        n = self._offered_by(aid) if aid else 0
        self.used_label.setText("" if not art else f"Offered by {n} step{'s' if n != 1 else ''}/ending{'s' if n != 1 else ''}."
                                + ("" if n else " Offer it from a step's “KB articles” or a shared resolution."))

    def _add(self):
        art = self.tree.add_article()
        self.refresh(select=art.id)
        self.title_input.setFocus()
        self.title_input.selectAll()

    def _delete(self):
        aid = self._current_id()
        if not aid:
            return
        n = self._offered_by(aid)
        if n and QMessageBox.question(
                self, "Delete KB article", f"It is offered in {n} place{'s' if n != 1 else ''}; it will be removed from "
                f"{'them' if n != 1 else 'it'}. Delete it?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.tree.delete_article(aid)
        self.refresh()

    def _title_changed(self, text):
        aid = self._current_id()
        if aid in self.tree.articles:
            self.tree.articles[aid].title = text
            self.list.currentItem().setText(text or f"({aid}: no title)")

    def _body_changed(self):
        aid = self._current_id()
        if aid in self.tree.articles:
            self.tree.articles[aid].body = self.body_input.toPlainText()

    def _url_changed(self, text):
        aid = self._current_id()
        if aid in self.tree.articles:
            self.tree.articles[aid].url = text.strip()


class SharedContentDialog(QDialog):
    """Manage the flow's shared resolutions and KB articles. Works on `tree`
    (a copy made by the Editor); the caller keeps it only if this is accepted."""

    def __init__(self, tree: Tree, base_dir_provider=lambda: None, select_resolution: str | None = None, parent=None):
        super().__init__(parent)
        self.tree = tree
        self.setWindowTitle("Shared endings and KB articles")
        self.resize(760, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "A shared resolution is written once and any number of answers can end at it. "
            "KB articles can be offered on steps and on shared resolutions."))
        self.tabs = QTabWidget()
        self.resolutions_tab = _ResolutionsTab(tree, base_dir_provider)
        self.articles_tab = _ArticlesTab(tree)
        self.tabs.addTab(self.resolutions_tab, "Shared resolutions")
        self.tabs.addTab(self.articles_tab, "KB articles")
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if select_resolution:
            self.resolutions_tab.refresh(select=select_resolution)
        # The articles a resolution offers can be created from the other tab; keep that summary honest.
        self.tabs.currentChanged.connect(lambda _i: self.resolutions_tab.refresh())
