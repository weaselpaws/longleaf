"""
ArticlePanel — the KB articles on offer at the current step or ending.
Each article can be read (expands in place), attached to the ticket (copied
to the clipboard) and, on a step, used as the resolution. The panel only
reports what the tech clicked; PlayerWidget logs it through the engine.
"""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
from PySide6.QtCore import Qt, Signal

from engine import Article, rich_html
from theme import GREEN, TEXT_DIM


class _ArticleRow(QFrame):
    read = Signal(str)       # article id, when expanded
    attach = Signal(str)
    use = Signal(str)

    def __init__(self, article: Article, attached: bool, can_use: bool, parent=None):
        super().__init__(parent)
        self.article = article
        self.setObjectName("articleRow")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 2)
        root.setSpacing(4)

        top = QHBoxLayout()
        self.title_label = QLabel(article.title or article.id)
        self.title_label.setStyleSheet("font-weight: 600;")
        self.title_label.setWordWrap(True)
        top.addWidget(self.title_label, 1)
        self.attached_label = QLabel("✓ Attached")
        self.attached_label.setStyleSheet(f"color: {GREEN};")
        self.attached_label.setVisible(attached)
        top.addWidget(self.attached_label)
        self.read_btn = QPushButton("Read")
        self.read_btn.setCheckable(True)
        self.read_btn.toggled.connect(self._toggled)
        top.addWidget(self.read_btn)
        self.attach_btn = QPushButton("Attach to ticket")
        self.attach_btn.setToolTip("Copies the article's link (or text) to the clipboard to paste into the ticket")
        self.attach_btn.clicked.connect(lambda: self.attach.emit(article.id))
        top.addWidget(self.attach_btn)
        self.use_btn = QPushButton("Use as resolution")
        self.use_btn.setVisible(can_use)
        self.use_btn.clicked.connect(lambda: self.use.emit(article.id))
        top.addWidget(self.use_btn)
        root.addLayout(top)

        self.body_label = QLabel("")
        self.body_label.setWordWrap(True)
        self.body_label.setTextFormat(Qt.RichText)
        self.body_label.setOpenExternalLinks(True)
        self.body_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        body = rich_html(article.body) if article.body.strip() else f'<span style="color:{TEXT_DIM}">(No text in this article.)</span>'
        if article.url:
            body += ("<br>" if article.body.strip() else "") + rich_html(article.url)
        self.body_label.setText(body)
        self.body_label.setVisible(False)
        root.addWidget(self.body_label)

    def _toggled(self, on: bool):
        self.body_label.setVisible(on)
        self.read_btn.setText("Hide" if on else "Read")
        if on:
            self.read.emit(self.article.id)

    def set_attached(self, attached: bool):
        self.attached_label.setVisible(attached)


class ArticlePanel(QWidget):
    read = Signal(str)
    attach = Signal(str)
    use = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: dict[str, _ArticleRow] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)
        root.setSpacing(4)
        self.header = QLabel("Knowledge base")
        self.header.setProperty("role", "subheading")
        root.addWidget(self.header)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(2)
        root.addLayout(self.rows_layout)
        self.setVisible(False)

    def set_articles(self, articles: list[Article], attached: set[str], can_use: bool):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._rows = {}
        for art in articles:
            row = _ArticleRow(art, art.id in attached, can_use)
            row.read.connect(self.read.emit)
            row.attach.connect(self.attach.emit)
            row.use.connect(self.use.emit)
            self.rows_layout.addWidget(row)
            self._rows[art.id] = row
        self.setVisible(bool(articles))

    def mark_attached(self, article_id: str):
        if article_id in self._rows:
            self._rows[article_id].set_attached(True)
