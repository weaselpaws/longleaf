"""
Longleaf - Player (v1)

The version that ships to field techs: opens a flow file and walks it.
No editing capability at all — just Play, answer, get a report.

A Player can also serve several businesses at once (a call center taking calls on
behalf of many): each business is a *persona*, a folder beside the exe with its own
flow (see persona.py). The agent swaps persona while on a call; the call in progress
is parked, never dropped. With no personas folder it is the single-flow Player it
always was.
"""

import shutil
import sys
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QLabel, QMainWindow, QMessageBox, QStackedWidget, QToolBar,
)
from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QAction, QActionGroup, QKeySequence

from engine import Tree
from feedback import SessionStore, write_bundle
from outcome_log import OutcomeLog
from persona import PersonaInfo, discover_personas, load_persona, slug as _slug
from theme import apply_theme
from widgets.player_widget import PlayerWidget

DEFAULT_FLOW_NAME = "flow.json"
DATA_DIR_ENV = "LONGLEAF_DATA_DIR"           # override where finished sessions are kept (portable installs, tests)
PERSONAS_DIR_ENV = "LONGLEAF_PERSONAS_DIR"   # override where persona folders are looked for
PERSONAS_DIR_NAME = "personas"


def _data_dir() -> Path:
    override = os.environ.get(DATA_DIR_ENV)
    return Path(override) if override else Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))


def _app_dir() -> Path:
    """Beside the exe when frozen, beside this script in development."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def _personas_dir() -> Path:
    override = os.environ.get(PERSONAS_DIR_ENV)
    return Path(override) if override else _app_dir() / PERSONAS_DIR_NAME


def _client_slug(tree: Tree) -> str:
    return _slug(tree.client) or "default"


def _log_for(key: str) -> OutcomeLog:
    """The append-only outcome log, one file per business next to (not inside) the session files."""
    return OutcomeLog(_data_dir() / "logs" / key)


def _store_for(key: str) -> SessionStore:
    """Sessions are kept per business, so one persona's calls never mix with another's."""
    return SessionStore(_data_dir() / "sessions" / key)


def _bundled_flow_path() -> str:
    """The flow shipped alongside the exe (or this script, in dev)."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, DEFAULT_FLOW_NAME)


@dataclass
class _Slot:
    """One persona's place in the window. The Player page is built the first time it is swapped to."""
    info: PersonaInfo
    key: str                          # names its session and log folders
    player: PlayerWidget | None = None
    tree: Tree | None = None


class PlayerWindow(QMainWindow):
    def __init__(self, personas_dir: str | Path | None = None):
        super().__init__()
        self.setWindowTitle("Longleaf")
        self.resize(900, 640)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.slots: dict[str, _Slot] = {}
        self.current: _Slot | None = None
        self._adhoc = 0
        self._building_switcher = False

        self._build_menu()
        self._build_switcher()
        self._load_personas(Path(personas_dir) if personas_dir else _personas_dir())

    # ---- what the rest of the window (and the tests) treat as "the" player ----

    @property
    def player(self) -> PlayerWidget | None:
        return self.current.player if self.current else None

    @property
    def store(self) -> SessionStore | None:
        return _store_for(self.current.key) if self.current else None

    @property
    def outcome_log(self) -> OutcomeLog | None:
        return _log_for(self.current.key) if self.current else None

    # ---------- menus and the persona switcher ----------

    def _build_menu(self):
        menu = self.menuBar().addMenu("&File")
        open_action = QAction("&Open Flow…", self)
        open_action.triggered.connect(lambda: self._open_flow())
        menu.addAction(open_action)
        restart_action = QAction("&Restart", self)
        restart_action.triggered.connect(lambda: self.player and self.player.restart())
        menu.addAction(restart_action)
        menu.addSeparator()
        export_action = QAction("&Export Feedback…", self)
        export_action.triggered.connect(self._export_feedback)
        menu.addAction(export_action)
        log_action = QAction("Export &Outcome Log…", self)
        log_action.triggered.connect(self._export_log)
        menu.addAction(log_action)
        clear_action = QAction("&Clear Saved Sessions…", self)
        clear_action.triggered.connect(self._clear_sessions)
        menu.addAction(clear_action)
        self.persona_menu = self.menuBar().addMenu("&Persona")
        self.persona_actions = QActionGroup(self)
        self.persona_actions.setExclusive(True)

    def _build_switcher(self):
        self.switcher_bar = QToolBar("Persona", self)
        self.switcher_bar.setMovable(False)
        self.switcher_bar.addWidget(QLabel("  Speaking for: "))
        self.switcher = QComboBox()
        self.switcher.setMinimumWidth(220)
        self.switcher.activated.connect(self._switcher_picked)
        self.switcher_bar.addWidget(self.switcher)
        self.addToolBar(self.switcher_bar)
        self.switcher_bar.setVisible(False)

    def _rebuild_switcher(self):
        """Keep the combo box and the Persona menu in step with the slots. Shown only with 2+ usable personas."""
        self._building_switcher = True
        self.switcher.clear()
        for a in list(self.persona_actions.actions()):
            self.persona_actions.removeAction(a)
            self.persona_menu.removeAction(a)
        for n, slot in enumerate(self.slots.values()):
            info = slot.info
            label = self._label(slot)
            self.switcher.addItem(label, userData=info.id)
            idx = self.switcher.count() - 1
            action = QAction(f"{n + 1}  {info.name}" if info.usable else f"{info.name} (can't load)", self, checkable=True)
            action.setData(info.id)
            action.setEnabled(info.usable)
            if info.usable and n < 9:
                action.setShortcut(QKeySequence(f"Ctrl+{n + 1}"))
            action.triggered.connect(lambda _c=False, pid=info.id: self.switch_to(pid))
            self.persona_actions.addAction(action)
            self.persona_menu.addAction(action)
            if not info.usable:
                item = self.switcher.model().item(idx)
                item.setEnabled(False)
                self.switcher.setItemData(idx, info.error, 3)   # tooltip role
                action.setToolTip(info.error)
        self._building_switcher = False
        self._sync_switcher_selection()
        multiple = sum(s.info.usable for s in self.slots.values()) > 1
        self.switcher_bar.setVisible(multiple)
        self.persona_menu.menuAction().setVisible(multiple or any(not s.info.usable for s in self.slots.values()))

    def _label(self, slot: _Slot) -> str:
        busy = slot.player is not None and slot.player.has_open_call()
        return ("● " if busy else "") + slot.info.name

    def _sync_switcher_selection(self):
        if not self.current:
            return
        self._building_switcher = True
        idx = self.switcher.findData(self.current.info.id)
        if idx >= 0:
            self.switcher.setCurrentIndex(idx)
        for a in self.persona_actions.actions():
            a.setChecked(a.data() == self.current.info.id)
        self._building_switcher = False

    def _refresh_indicators(self):
        """Mark personas that have a call in progress, so a parked call is never forgotten."""
        self._building_switcher = True
        for i, slot in enumerate(self.slots.values()):
            self.switcher.setItemText(i, self._label(slot))
        self._building_switcher = False

    def _switcher_picked(self, index: int):
        if not self._building_switcher:
            self.switch_to(self.switcher.itemData(index))

    # ---------- loading personas ----------

    def _load_personas(self, personas_dir: Path):
        found: list[PersonaInfo] = []
        bundled = _bundled_flow_path()
        if os.path.exists(bundled):
            found.append(load_persona(Path(bundled).parent, persona_id="default"))
        bundled_real = os.path.realpath(bundled)
        for info in discover_personas(personas_dir):
            if os.path.realpath(info.flow_path) != bundled_real:
                found.append(info)
        for info in found:
            # The bundled flow keeps its old storage name (the client), so an upgrade finds its sessions.
            key = (_client_slug(Tree.load(info.flow_path)) if info.id == "default" and info.usable
                   else f"persona-{info.id}")
            self.slots[info.id] = _Slot(info, key)
        usable = [s for s in self.slots.values() if s.info.usable]
        broken = [s for s in self.slots.values() if not s.info.usable]
        if broken:
            self.statusBar().showMessage(
                f"{len(broken)} persona{'s' if len(broken) != 1 else ''} couldn't be loaded: "
                + "; ".join(f"{s.info.name} — {s.info.error}" for s in broken), 15000)
        if not usable:
            self._rebuild_switcher()
            self._open_flow(required=True)
            return
        self._ensure_player(usable[0])
        self.current = usable[0]
        self.stack.setCurrentWidget(usable[0].player)
        self._apply_branding(usable[0])
        self._rebuild_switcher()
        usable[0].player.resume()

    def _ensure_player(self, slot: _Slot) -> bool:
        if slot.player is not None:
            return True
        try:
            tree = Tree.load(slot.info.flow_path)
        except Exception as e:
            QMessageBox.critical(self, "Couldn't open flow", f"{slot.info.name}: {e}")
            return False
        slot.tree = tree
        slot.player = PlayerWidget(Tree(), autofocus_search=True, tools=slot.info.tools,
                                   session_store=_store_for(slot.key), event_sink=_log_for(slot.key).emit)
        slot.player.load_tree(tree, base_dir=os.path.dirname(os.path.abspath(slot.info.flow_path)))
        slot.player.set_logo(tree.branding.logo)
        slot.player.session_state_changed.connect(self._refresh_indicators)
        self.stack.addWidget(slot.player)
        return True

    def _apply_branding(self, slot: _Slot):
        tree = slot.tree
        apply_theme(QApplication.instance(), tree.branding.accent)   # empty accent -> stock gold
        many = sum(s.info.usable for s in self.slots.values()) > 1
        self.setWindowTitle(f"{tree.branding.name or 'Longleaf'} — {tree.title}" if not many or tree.branding.name
                            else f"Longleaf — {slot.info.name} — {tree.title}")

    def switch_to(self, persona_id: str):
        """Swap to another business. The call in progress is parked exactly where it is (and saved and
        logged as parked); swapping back resumes it."""
        slot = self.slots.get(persona_id)
        if slot is None or not slot.info.usable or slot is self.current:
            self._sync_switcher_selection()
            return
        if not self._ensure_player(slot):
            self._sync_switcher_selection()
            return
        if self.current and self.current.player:
            self.current.player.park()
        self.current = slot
        self.stack.setCurrentWidget(slot.player)
        self._apply_branding(slot)
        slot.player.resume()
        self._sync_switcher_selection()
        self._refresh_indicators()

    # ---------- opening a flow by hand ----------

    def _open_flow(self, required: bool = False):
        path, _ = QFileDialog.getOpenFileName(self, "Open Flow", "", "YARI Flow (*.json)")
        if not path:
            if required:
                QMessageBox.warning(
                    self, "No flow loaded",
                    "No flow file was found or selected. Use File → Open Flow to load one."
                )
            return
        self._load(path)

    def _load(self, path: str):
        """Open a flow file as one more persona (the call in progress, if any, is parked, not lost)."""
        try:
            tree = Tree.load(path)
        except Exception as e:
            QMessageBox.critical(self, "Couldn't open flow", str(e))
            return
        self._adhoc += 1
        pid = f"opened-{self._adhoc}"
        info = PersonaInfo(pid, tree.branding.name or tree.client or tree.title or Path(path).stem, path,
                           os.path.dirname(os.path.abspath(path)))
        self.slots[pid] = _Slot(info, _client_slug(tree))
        self._rebuild_switcher()
        self.switch_to(pid) if self.current else self._first_slot(self.slots[pid])

    def _first_slot(self, slot: _Slot):
        if self._ensure_player(slot):
            self.current = slot
            self.stack.setCurrentWidget(slot.player)
            self._apply_branding(slot)
            self._rebuild_switcher()
            slot.player.resume()

    # ---------- exports (always for the persona you are on) ----------

    def _export_feedback(self):
        if not self.current:
            return
        self.player.flush()
        records = self.store.load_all()
        if not records:
            QMessageBox.information(self, "Export Feedback", "No sessions have been saved yet.")
            return
        tree = self.player.engine.tree
        slug = _slug(tree.client)
        default = f"longleaf_feedback_{slug + '_' if slug else ''}{datetime.now():%Y%m%d}.json"
        path, _ = QFileDialog.getSaveFileName(self, "Export Feedback", default, "Longleaf feedback (*.json)")
        if not path:
            return
        try:
            n = write_bundle(path, records, tree)
        except OSError as e:
            QMessageBox.critical(self, "Couldn't save feedback", str(e))
            return
        QMessageBox.information(
            self, "Export Feedback",
            f"Saved {n} session{'s' if n != 1 else ''} to:\n{path}\n\n"
            f"Send this file to whoever maintains this flow. It includes the tickets, notes and "
            f"comments entered on those sessions.")

    def _export_log(self):
        if not self.current:
            return
        self.player.flush()
        log = self.outcome_log
        if not log.path.exists() or not log.count():
            QMessageBox.information(self, "Export Outcome Log", "Nothing has been logged yet.")
            return
        slug = _client_slug(self.player.engine.tree)
        default = f"longleaf_outcome_log_{slug}_{datetime.now():%Y%m%d}.jsonl"
        path, _ = QFileDialog.getSaveFileName(self, "Export Outcome Log", default, "Outcome log (*.jsonl)")
        if not path:
            return
        try:
            shutil.copyfile(log.path, path)
        except OSError as e:
            QMessageBox.critical(self, "Couldn't save the log", str(e))
            return
        QMessageBox.information(
            self, "Export Outcome Log",
            f"Saved the outcome log ({log.count()} events) to:\n{path}\n\n"
            f"It records what happened in each session (steps taken, how it ended, ticket ids, what was "
            f"searched for) but not notes or comments.")

    def _clear_sessions(self):
        if not self.current:
            return
        store, log = self.store, self.outcome_log
        n, events = store.count(), log.count()
        if not n and not events:
            QMessageBox.information(self, "Clear Saved Sessions", "There are no saved sessions or logged events.")
            return
        reply = QMessageBox.question(
            self, "Clear Saved Sessions",
            f"Delete {n} saved session{'s' if n != 1 else ''} and {events} logged event{'s' if events != 1 else ''} "
            f"for {self.current.info.name} from this computer? Export them first if they haven't been sent yet.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            store.clear()
            log.clear()

    def closeEvent(self, event):
        for slot in self.slots.values():
            if slot.player is not None:
                slot.player.flush()
                slot.player.shutdown()            # a call left part-way (parked or not) is logged and saved, never dropped
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("Yellowhammer")
    app.setApplicationName("Longleaf")
    apply_theme(app)
    window = PlayerWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
