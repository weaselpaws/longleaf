"""
Quick regression check for the engine + widgets. Not a full test suite —
just enough to catch the class of bug where the UI silently corrupts the
model (see the StepEditor/OptionRow load-order bug this caught).

Run with: venv\\Scripts\\python.exe smoke_test.py
"""

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import QGraphicsSceneMouseEvent, QFileDialog, QMessageBox

from engine import Option, Tree, TroubleshootEngine
from theme import apply_theme
from widgets.player_widget import PlayerWidget
from widgets.editor_widget import EditorWidget
from widgets.step_editor import StepEditor
from build_client_release import assert_player_cannot_reach_editor

app = QApplication([])
apply_theme(app)

tree = Tree.load("sample_tree.json")

# --- engine: branching, resolution, and undo ---
eng = TroubleshootEngine(tree)
assert eng.current_step.id == "step_1"
eng.choose(eng.current_step.options[0])   # "No network access at all" -> step_2
assert eng.current_id == "step_2", eng.current_id
eng.choose(eng.current_step.options[0])   # Wi-Fi -> step_3
eng.choose(eng.current_step.options[1])   # wrong network -> resolution
assert eng.is_finished
assert "SSID" in eng.resolution

eng.go_back()
assert not eng.is_finished
assert eng.current_id == "step_3", eng.current_id
print("engine: branching / resolution / go_back OK")

warnings = tree.validate()
assert warnings == [], warnings
print("engine: sample_tree.json validates clean")

# --- PlayerWidget builds and renders without error ---
player = PlayerWidget(Tree.load("sample_tree.json"))
assert player.engine.current_step.id == "step_1"
print("PlayerWidget: builds OK")

# --- Player: finish screen collects ticket/notes and they land in the report ---
p2 = PlayerWidget(Tree.load("sample_tree.json"))
p2.operator_input.setText("Sam")
while not p2.engine.is_finished:
    p2._choose(p2.engine.current_step.options[0])
assert not p2.details_widget.isHidden() and not p2.report_box.isHidden()
p2.ticket_input.setText("INC-42")
p2.notes_input.setPlainText("swapped the cable")
rep = p2.report_box.toPlainText()
assert "INC-42" in rep and "swapped the cable" in rep and "Sam" in rep, rep
p2.restart()
assert p2.ticket_input.text() == "" and p2.operator_input.text() == "Sam" and p2.details_widget.isHidden()
assert p2.engine.operator == "Sam"
print("PlayerWidget: ticket/operator/notes flow into the report; name survives Start Over")

# --- a broken flow ends visibly, not blank ---
broken = Tree.load("sample_tree.json")
broken.steps[broken.root_id].options[0].next_id = "ghost"
p3 = PlayerWidget(broken)
p3._choose(broken.steps[broken.root_id].options[0])
assert p3.engine.outcome == "error" and "ghost" in p3.resolution_label.text()
print("PlayerWidget: dangling link shows a flow-error result")

# --- StepEditor must NOT corrupt option data on load (regression test) ---
step6 = tree.steps["step_6"]
before = [(o.label, o.next_id, o.resolution) for o in step6.options]
se = StepEditor()
se.set_all_steps_provider(lambda: [(sid, s.question[:20]) for sid, s in tree.steps.items()])
se.set_step(step6)
after = [(o.label, o.next_id, o.resolution) for o in step6.options]
assert before == after, f"StepEditor mutated option data on load!\n  before={before}\n  after={after}"
print("StepEditor: loading a step does not corrupt its options")

# --- EditorWidget builds end-to-end ---
editor = EditorWidget(Tree.load("sample_tree.json"))
assert editor.outline_list.count() == len(tree.steps)
print("EditorWidget: builds OK")

editor.client_input.setText("acme")
editor.version_input.setText("1.4.0")
assert (editor.tree.client, editor.tree.version) == ("acme", "1.4.0")
assert editor.status_label.text() == "✓ Valid", editor.status_label.text()
editor.tree.steps["step_1"].options[0].next_id = "ghost"
editor._refresh_outline()
assert "error" in editor.status_label.text() and "✖ " in editor.outline_list.item(0).text(), \
    (editor.status_label.text(), editor.outline_list.item(0).text())
from widgets.editor_widget import ValidationDialog
dlg = ValidationDialog(editor.tree.check())
assert dlg.list.count() == len(editor.tree.check())
print("EditorWidget: client/version fields, live validation status, validation dialog OK")

# --- branding + rich content ---
import tempfile
from PySide6.QtGui import QImage, QColor
import theme
from engine import Branding, Option, Step
from widgets.image_picker import relative_asset_path
from widgets.editor_widget import BrandingDialog

with tempfile.TemporaryDirectory() as d:
    for name in ("logo.png", "shot.png"):
        img = QImage(60, 40, QImage.Format_RGB32)
        img.fill(QColor("#3366CC"))
        assert img.save(os.path.join(d, name))
    bt = Tree(title="Acme", root_id="a", branding=Branding(name="Acme Assist", accent="#3366CC", logo="logo.png"),
              steps={"a": Step("a", "Line one\nSee https://example.com/help", [Option("Fix", None, "Done <b>", image="shot.png")],
                               image="shot.png", note="hint")})
    assert bt.check(d) == []
    pw = PlayerWidget(bt)
    pw.load_tree(bt, base_dir=d)
    pw.set_logo(bt.branding.logo)
    assert not pw.logo_label.isHidden() and not pw.image_label.isHidden()
    assert 'href="https://example.com/help"' in pw.question_label.text() and "<br>" in pw.question_label.text()
    pw._choose(bt.steps["a"].options[0])
    assert not pw.image_label.isHidden() and "&lt;b&gt;" in pw.resolution_label.text()
    pw.restart()
    assert not pw.image_label.isHidden()
    pw.base_dir = os.path.join(d, "nowhere")          # missing image must not break the flow
    pw.restart()
    assert pw.image_label.isHidden()
    apply_theme(app, "#3366CC")
    assert theme.GOLD == "#3366CC" and "#3366CC" in app.styleSheet() and "201,149,42" not in app.styleSheet()
    apply_theme(app)
    assert theme.GOLD == "#C9952A" and "201,149,42" in app.styleSheet()

    elsewhere = tempfile.mkdtemp()
    open(os.path.join(elsewhere, "x.png"), "wb").write(b"x")
    assert relative_asset_path(os.path.join(d, "shot.png"), d) == "shot.png"
    copied = relative_asset_path(os.path.join(elsewhere, "x.png"), d)
    assert copied == "images/x.png" and os.path.isfile(os.path.join(d, copied))
    assert relative_asset_path(os.path.join(elsewhere, "x.png"), d) == "images/x.png"   # idempotent

    dlg = BrandingDialog(bt.branding, lambda: d)
    dlg.accent_input.setText("nope")
    dlg._accept()
    assert dlg.result() == 0 and dlg.problem_label.text()
    dlg.accent_input.setText("#112233")
    dlg.name_input.setText("  New  ")
    dlg._accept()
    assert dlg.branding() == Branding(name="New", accent="#112233", logo="logo.png")

    ed = EditorWidget(bt)
    ed.current_path = os.path.join(d, "flow.json")
    ed.step_editor.set_step(bt.steps["a"])
    ed.step_editor.question_input.setPlainText("Two\nlines")
    ed.step_editor.image_picker.changed.emit("")
    assert bt.steps["a"].question == "Two\nlines" and bt.steps["a"].image == ""
print("branding / images / rich text / image picker / branding dialog OK")

# --- graph view ---
from widgets.graph_view import GraphPanel, _Node
from engine import SEVERITY_ERROR
gt = Tree.load("examples/it_helpdesk_no_network.json")
gt.add_step("Orphan")                                   # unreachable + dead end
gt.steps[gt.root_id].options.append(Option("Weird", "ghost"))   # dangling link
gp = GraphPanel()
gp.view.set_tree(gt)
nodes = [i for i in gp.view.scene().items() if isinstance(i, _Node)]
steps_drawn = {n.step_id for n in nodes}
assert set(gt.steps) <= steps_drawn, set(gt.steps) - steps_drawn
n_endings = sum(1 for s in gt.steps.values() for o in s.options if not o.next_id)
n_missing = 1
assert len(nodes) >= len(gt.steps) + n_endings + n_missing, len(nodes)
tips = " ".join(n.toolTip() for n in nodes)
assert "doesn't exist" in tips and "Unreachable" in tips
clicked = []
gp.step_selected.connect(clicked.append)
press = QGraphicsSceneMouseEvent(QEvent.GraphicsSceneMousePress)
press.setButton(Qt.LeftButton)
next(n for n in nodes if n.step_id == gt.root_id and n.toolTip().startswith(gt.root_id)).mousePressEvent(press)
assert clicked == [gt.root_id], clicked
gp.view.set_progress(gt.root_id, [(gt.root_id, 0)])     # path highlighting rebuilds without error
gp.view.set_selected(gt.root_id)
with tempfile.TemporaryDirectory() as d:
    png, svg = os.path.join(d, "g.png"), os.path.join(d, "g.svg")
    assert gp.export_png(png) and gp.export_svg(svg)
    assert open(png, "rb").read(4) == b"\x89PNG" and b"<svg" in open(svg, "rb").read(2000)
GraphPanel().view.set_tree(Tree())                      # empty flow is fine
ge = EditorWidget(Tree.load("sample_tree.json"))
ge.select_step("step_3")
assert ge.graph.view.selected_id == "step_3"
ge._on_test_step_changed("step_2")
assert ge.graph.view.current_id == "step_2"
print("graph view: draws steps/endings/missing links, click selects, progress, PNG+SVG export OK")

# --- local feedback capture ---
from feedback import SessionStore, load_bundle, write_bundle
from PySide6.QtCore import QCoreApplication

with tempfile.TemporaryDirectory() as d:
    store = SessionStore(os.path.join(d, "sessions"))
    ft = Tree.load("sample_tree.json")

    # Test pane (no store): no feedback UI, nothing recorded
    plain = PlayerWidget(Tree.load("sample_tree.json"))
    while not plain.engine.is_finished:
        plain._choose(plain.engine.current_step.options[0])
    assert plain.feedback_widget.isHidden()

    fp = PlayerWidget(ft, session_store=store)
    fp.show()
    assert fp.feedback_widget.isHidden()
    while not fp.engine.is_finished:
        fp._choose(fp.engine.current_step.options[0])
    assert not fp.feedback_widget.isHidden() and store.count() == 1       # saved the moment it finished
    sid = fp.engine.session_id

    fp.yes_btn.click()
    assert fp.yes_btn.isChecked() and fp.engine.feedback == {"helpful": True, "comment": ""}
    fp.no_btn.click()
    assert not fp.yes_btn.isChecked() and fp.engine.feedback["helpful"] is False
    fp.no_btn.click()                                                     # clicking the lit one clears it
    assert fp.engine.feedback is None
    fp.yes_btn.click()
    fp.feedback_comment.setText("Fixed it first try")
    fp.ticket_input.setText("INC-7")
    fp.flush()
    (saved,) = store.load_all()
    assert saved.session_id == sid and saved.ticket_ref == "INC-7"
    assert saved.feedback == {"helpful": True, "comment": "Fixed it first try"}

    fp._go_back()                                                          # un-finishing keeps the record, now in progress
    assert store.count() == 1 and store.load_all()[0].outcome == "in_progress" and fp.feedback_widget.isHidden()
    while not fp.engine.is_finished:
        fp._choose(fp.engine.current_step.options[0])
    assert store.count() == 1
    fp.restart()                                                          # new session: inputs cleared, old one kept
    assert store.count() == 1 and not fp.yes_btn.isChecked() and fp.feedback_comment.text() == ""
    while not fp.engine.is_finished:
        fp._choose(fp.engine.current_step.options[-1])
    assert store.count() == 2

    # a flow error is saved but isn't asked about
    eb = Tree.load("sample_tree.json")
    eb.steps[eb.root_id].options[0].next_id = "ghost"
    fe = PlayerWidget(eb, session_store=store)
    fe._choose(eb.steps[eb.root_id].options[0])
    assert fe.feedback_widget.isHidden() and store.count() == 3

    # the Player window: per-client store, export, clear
    import player_main
    os.environ[player_main.DATA_DIR_ENV] = os.path.join(d, "appdata")
    win = player_main.PlayerWindow()
    assert win.store is not None and str(win.store.folder).startswith(os.path.join(d, "appdata", "sessions"))
    while not win.player.engine.is_finished:
        win.player._choose(win.player.engine.current_step.options[0])
    win.player.yes_btn.click()
    win.player.flush()
    import outcome_log as _ol
    assert win.outcome_log is not None and str(win.outcome_log.path).startswith(os.path.join(d, "appdata", "logs"))
    _kinds = [e["event"] for e in win.outcome_log.read()]
    assert _kinds[0] == _ol.STARTED and _ol.FINISHED in _kinds and _kinds[-1] == _ol.UPDATED       # started ... finished, then the rating
    (_sum,) = _ol.fold_sessions(win.outcome_log.read()).values()
    assert _sum.status == _ol.STATUS_RESOLVED
    _logout = os.path.join(d, "log-export.jsonl")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (_logout, ""))
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    win._export_log()
    assert len(_ol.read_events(_logout)) == len(_kinds)
    out = os.path.join(d, "fb.json")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (out, ""))
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    win._export_feedback()
    (rec,) = load_bundle(out)
    assert rec.feedback == {"helpful": True, "comment": ""}
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    win._clear_sessions()
    assert win.store.count() == 0 and win.outcome_log.count() == 0                       # clearing removes the log too
    win.player.restart()
    win.player._choose(win.player.engine.current_step.options[0])
    if win.player.engine.is_finished:                                                    # a one-answer flow: nothing to abandon
        win.player.restart()
        win.player._choose(win.player.engine.current_step.options[0])
    win.close()                                                                          # closing part-way logs an abandoned session
    assert win.outcome_log.read()[-1]["event"] in (_ol.ABANDONED, _ol.FINISHED)
    del os.environ[player_main.DATA_DIR_ENV]

    # Editor: import files, overlay on the graph, step panel, summary, clear
    et = Tree.load("examples/it_helpdesk_no_network.json")
    et.client = "acme"
    ed2 = EditorWidget(et)
    recs = []
    for picks, helpful, comment in (([0, 0, 1], False, "Wi-Fi was fine, cable was loose"), ([0, 0, 0], True, ""), ([0, 0, 0], True, "")):
        e = TroubleshootEngine(et)
        for i in picks:
            if e.is_finished:
                break
            e.choose(e.current_step.options[min(i, len(e.current_step.options) - 1)])
        e.set_feedback(helpful, comment)
        recs.append(e.record())
    b1, b2 = os.path.join(d, "one.json"), os.path.join(d, "two.json")
    write_bundle(b1, recs[:2], et)
    write_bundle(b2, recs[1:], et)                                        # overlaps b1 by one session
    bad = os.path.join(d, "bad.json")
    open(bad, "w").write("{}")
    shown = []
    QMessageBox.information = staticmethod(lambda parent, title, text: shown.append(text))
    QMessageBox.warning = staticmethod(lambda parent, title, text: shown.append(text))
    ed2.import_feedback_files([b1, b2, bad])
    assert len(ed2.feedback_records) == 3 and ed2._feedback_dupes == 1
    assert "3 sessions matched" in shown[-1] and "1 duplicate skipped" in shown[-1] and "not a Longleaf feedback file" in shown[-1]
    assert ed2.right_tabs.currentWidget() is ed2.graph and ed2.graph.view.feedback is ed2.feedback
    root_id = et.root_id
    ed2.select_step(root_id)
    assert "visits from imported sessions" in ed2.step_editor.feedback_box.toPlainText()
    assert not ed2.step_editor.feedback_box.isHidden()
    tips = " ".join(i.toolTip() for i in ed2.graph.view.scene().items() if hasattr(i, "toolTip"))
    assert "cable was loose" in tips and "% helpful" in tips
    png = os.path.join(d, "overlay.png")
    assert ed2.graph.export_png(png)
    ed2.tree.steps[root_id].options[0].label = "Renamed"                  # editing the flow keeps the overlay consistent
    ed2._on_step_edited()
    assert ed2.feedback is not None and ed2.feedback.sessions == 3
    ed2._clear_feedback()
    assert ed2.feedback is None and ed2.graph.view.feedback is None and ed2.step_editor.feedback_box.isHidden()
print("feedback: Player rating + local save, export/clear, Editor import/dedupe/overlay/step panel OK")

# --- Editor: undo/redo, autosave and crash recovery ---
import tempfile as _tf
from PySide6.QtTest import QTest
from editor_main import EditorWindow

with _tf.TemporaryDirectory() as d:
    auto = os.path.join(d, "auto")
    win = EditorWindow(autosave_dir=auto)
    win.show()
    win.activateWindow()
    assert QTest.qWaitForWindowActive(win)
    ed = win.editor
    assert not win.undo_action.isEnabled() and not win.redo_action.isEnabled() and not ed._dirty
    first = ed.tree.root_id

    ed._add_step()                                                    # a structural edit
    assert len(ed.tree.steps) == 2 and ed._dirty and win.undo_action.isEnabled()
    ed.undo()
    assert len(ed.tree.steps) == 1 and not ed._dirty and win.redo_action.isEnabled()   # back to the clean state
    ed.redo()
    assert len(ed.tree.steps) == 2 and ed._dirty and ed.outline_list.count() == 2

    before = ed.tree.title
    ed.title_input.setFocus()
    QTest.keyClicks(ed.title_input, "Hello")                          # typing collapses into one undo step
    assert ed.tree.title == before + "Hello"
    ed.undo()
    assert ed.tree.title == before and ed.title_input.text() == before and len(ed.tree.steps) == 2

    # Ctrl+Z / Ctrl+Y work while the cursor is inside a text box (one history, not per-field)
    ed.select_step(first)
    ed.step_editor.question_input.setFocus()
    ed.step_editor.question_input.setPlainText("Is it plugged in?")
    assert ed.tree.steps[first].question == "Is it plugged in?"
    QTest.keyClick(ed.step_editor.question_input, Qt.Key_Z, Qt.ControlModifier)
    assert ed.tree.steps[first].question != "Is it plugged in?", "Ctrl+Z did nothing inside a text box"
    QTest.keyClick(ed.step_editor.question_input, Qt.Key_Y, Qt.ControlModifier)
    assert ed.tree.steps[first].question == "Is it plugged in?"

    ed.flush_autosave()                                               # unsaved work -> a recovery copy exists
    (rec,) = win.autosave.pending()
    assert rec.tree["steps"][first]["question"] == "Is it plugged in?"

    # A crash: the window never closes, a new launch finds the copy and recovers it.
    crashed = EditorWindow(autosave_dir=auto)
    (rec2,) = crashed.autosave.pending()
    asked = []
    class _Box:
        AcceptRole, DestructiveRole, RejectRole = QMessageBox.AcceptRole, QMessageBox.DestructiveRole, QMessageBox.RejectRole
        def __init__(self, *a): self.btns = {}
        def setWindowTitle(self, t): pass
        def setText(self, t): asked.append(t)
        def setInformativeText(self, t): pass
        def addButton(self, text, role): self.btns[text] = text; return text
        def exec(self): pass
        def clickedButton(self): return "Recover"
    import editor_main
    real_box = editor_main.QMessageBox
    editor_main.QMessageBox = _Box
    try:
        assert crashed.offer_recovery() is True
    finally:
        editor_main.QMessageBox = real_box
    assert "closed unexpectedly" in asked[0]
    assert crashed.editor.tree.steps[first].question == "Is it plugged in?" and crashed.editor._dirty
    assert crashed.editor.current_path is None and not crashed.editor._undo.can_undo()
    # the old copy is gone, a fresh one now belongs to the recovering session
    assert [r.slot for r in crashed.autosave.pending()] == [crashed.autosave.slot_for(None)]

    # Saving removes the recovery copy and leaves undo available; undoing past a save is dirty again.
    saved = os.path.join(d, "flow.json")
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (saved, ""))
    assert crashed.editor.save_tree_as() and not crashed.editor._dirty
    assert crashed.autosave.pending() == [] or all(r.flow_path != saved for r in crashed.autosave.pending())
    assert os.path.exists(saved)
    crashed.editor._add_step()
    crashed.editor.flush_autosave()
    assert any(r.flow_path == saved for r in crashed.autosave.pending())
    crashed.editor.undo()
    assert not crashed.editor._dirty
    crashed.editor.flush_autosave()
    assert not any(r.flow_path == saved for r in crashed.autosave.pending())
    crashed.editor.redo()
    crashed.editor.save_tree()
    crashed.editor.undo()
    assert crashed.editor._dirty                                      # differs from what is on disk now
    crashed.editor.flush_autosave()
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
    crashed.close()                                                   # discarded on exit -> nothing left to recover
    assert not any(r.flow_path == saved for r in crashed.autosave.pending())
    win.close()
print("editor: undo/redo (incl. inside text boxes), dirty tracking, autosave, crash recovery OK")

# --- Editor: shared resolutions and KB articles ---
from widgets.option_row import OptionRow, _NEW
from widgets.shared_content import SharedContentDialog

# Loading an answer that uses a shared resolution must not alter it (same trap the StepEditor test guards).
_t = Tree.load("examples/shared_resolutions_and_kb.json")
_before = _t.to_dict()
_ed = EditorWidget(_t)
for _sid in _t.steps:
    _ed.select_step(_sid)
assert _t.to_dict() == _before, "selecting steps changed the flow"
_ed.select_step("queued")
_row = _ed.step_editor.options_layout.itemAt(0).widget()
assert isinstance(_row, OptionRow) and _row.ending_combo.currentData() == "restart_spooler"
assert _row.resolution_input.isHidden() and not _row.shared_preview.isHidden()
assert "Print Spooler" in _row.shared_preview.text()
assert _ed.step_editor.articles_label.text() == "None"
_ed.select_step("start")
assert "Printer troubleshooting basics" in _ed.step_editor.articles_label.text()

# An answer switched to a next step drops its resolution_id, so no IGNORED_RESOLUTION warning appears.
_ed.select_step("queued")
_row = _ed.step_editor.options_layout.itemAt(0).widget()
_row.target_combo.setCurrentIndex(_row.target_combo.findData("offline"))
assert _t.steps["queued"].options[0].resolution_id is None and _t.steps["queued"].options[0].next_id == "offline"
assert "IGNORED_RESOLUTION" not in {i.code for i in _t.check()}
_ed.undo()
assert _ed.tree.steps["queued"].options[0].resolution_id == "restart_spooler"          # and undo brings it back

# Pointing an answer at a different shared resolution, and back to inline text.
_ed.select_step("driver")
_row = _ed.step_editor.options_layout.itemAt(1).widget()                               # "No" -> inline text
assert _row.ending_combo.currentData() is None and not _row.resolution_input.isHidden()
_row.ending_combo.setCurrentIndex(_row.ending_combo.findData("restart_spooler"))
_o = _ed.tree.steps["driver"].options[1]
assert (_o.resolution_id, _o.resolution) == ("restart_spooler", None) and _o.next_id is None
_ed.select_step("driver")
_row = _ed.step_editor.options_layout.itemAt(1).widget()
_row.ending_combo.setCurrentIndex(0)                                                   # back to inline: the box is empty (text was replaced by the shared one)
assert _ed.tree.steps["driver"].options[1].resolution_id is None
_ed.select_step("driver")
_row = _ed.step_editor.options_layout.itemAt(1).widget()
_row.resolution_input.setPlainText("Run a head cleaning.")
assert _ed.tree.steps["driver"].options[1].resolution == "Run a head cleaning."

# "New shared resolution from this text": the inline text moves into a new shared resolution.
_ed.select_step("offline")
_row = _ed.step_editor.options_layout.itemAt(1).widget()
_row.resolution_input.setPlainText("Power cycle the printer.")
_row.ending_combo.setCurrentIndex(_row.ending_combo.findData(_NEW))
_o = _ed.tree.steps["offline"].options[1]
assert _o.resolution_id in _ed.tree.resolutions and _o.resolution is None
assert _ed.tree.resolutions[_o.resolution_id].text == "Power cycle the printer."
assert not [i for i in _ed.tree.check() if i.is_error]
_ed.undo()
assert _ed.tree.steps["offline"].options[1].resolution_id is None and not [r for r in _ed.tree.resolutions if r.startswith("res_")]   # created + assigned = one undo step

# The dialog edits a copy: Cancel changes nothing, OK is a single undo step.
_ed2 = EditorWidget(Tree.load("examples/shared_resolutions_and_kb.json"))
_snap = _ed2.tree.to_dict()
_copy = Tree.from_dict(_snap)
_dlg = SharedContentDialog(_copy, lambda: None)
_rt = _dlg.resolutions_tab
_rt.list.setCurrentRow(0)
_rt.text_input.setPlainText("Edited fix.")
_rt._add()
_rt.text_input.setPlainText("Brand new ending.")
_at = _dlg.articles_tab
_at._add()
_at.title_input.setText("New KB")
_at.body_input.setPlainText("Body")
assert _copy.resolutions["restart_spooler"].text == "Edited fix." and "res_1" in _copy.resolutions and "kb_1" in _copy.articles
assert _ed2.tree.to_dict() == _snap                                                    # original untouched until OK
_ed2._apply_tree_edit(_copy)
assert _ed2.tree.resolutions["restart_spooler"].text == "Edited fix." and _ed2._dirty
_ed2.undo()
assert _ed2.tree.to_dict() == _snap and not _ed2._dirty                                # one step back, clean again
# deleting a resolution unlinks the answers that used it; deleting an article removes it everywhere
_copy2 = Tree.from_dict(_snap)
_dlg2 = SharedContentDialog(_copy2, lambda: None)
_orig_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
_dlg2.resolutions_tab.list.setCurrentRow(0)
_dlg2.resolutions_tab._delete()
_dlg2.articles_tab.list.setCurrentRow(0)
_dlg2.articles_tab._delete()
QMessageBox.question = _orig_q
assert "restart_spooler" not in _copy2.resolutions and len(_copy2.articles) == 2
assert all(o.resolution_id != "restart_spooler" for st in _copy2.steps.values() for o in st.options)

# Choosing KB articles on a step (the picker dialog stubbed to tick one more).
_ed3 = EditorWidget(Tree.load("examples/shared_resolutions_and_kb.json"))
_ed3.select_step("queued")
import widgets.step_editor as _se
_real_choose = _se.choose_articles
_se.choose_articles = lambda parent, tree, selected: [*selected, "kb_spooler"]
_ed3.step_editor._choose_articles()
_se.choose_articles = _real_choose
assert _ed3.tree.steps["queued"].articles == ["kb_spooler"] and "Restarting the Print Spooler" in _ed3.step_editor.articles_label.text()
assert _ed3._dirty
print("editor: shared resolutions + KB articles (assign, create from text, switch to next step, dialog edit/undo/delete, step articles) OK")


# --- Player: KB articles (read, attach to ticket, use as resolution) ---
import tempfile as _tf2
from feedback import SessionStore as _Store
from engine import ARTICLE_ATTACH as _ATT, ARTICLE_READ as _READ, ARTICLE_RESOLUTION as _RES

with _tf2.TemporaryDirectory() as d:
    kb = Tree.load("examples/shared_resolutions_and_kb.json")
    store = _Store(os.path.join(d, "sessions"))
    pw = PlayerWidget(kb, session_store=store)
    pw.show()
    panel = pw.articles_panel
    assert not panel.isHidden() and list(panel._rows) == ["kb_printer_basics"]             # offered on the start step
    row = panel._rows["kb_printer_basics"]
    assert row.body_label.isHidden() and not row.use_btn.isHidden()
    row.read_btn.setChecked(True)                                                         # Read expands it and logs it
    assert not row.body_label.isHidden() and "Check power" in row.body_label.text()
    assert [(e.article_id, e.action) for e in pw.engine.article_events] == [("kb_printer_basics", _READ)]
    row.read_btn.setChecked(False)
    row.read_btn.setChecked(True)
    assert len(pw.engine.article_events) == 2                                              # each open is a read
    row.attach_btn.click()                                                                # copies title + text, logs, marks it
    assert QApplication.clipboard().text().startswith("Printer troubleshooting basics\nCheck power")
    assert not row.attached_label.isHidden() and pw.engine.article_events[-1].action == _ATT
    row.attach_btn.click()
    assert [e.action for e in pw.engine.article_events].count(_ATT) == 1                  # attaching twice is one attachment

    row.use_btn.click()                                                                   # use as the resolution: session ends
    assert pw.engine.is_finished and pw.engine.resolution.startswith("KB article: Printer troubleshooting basics")
    assert not pw.resolution_label.isHidden() and "KB article" in pw.resolution_label.text()
    assert pw.back_btn.isEnabled() and store.count() == 1
    assert "KB attached: Printer troubleshooting basics" in pw.report_box.toPlainText()
    pw.back_btn.click()                                                                   # Back returns to the step; the record stays, in progress
    assert not pw.engine.is_finished and pw.engine.current_id == "start"
    assert store.count() == 1 and store.load_all()[0].outcome == "in_progress"
    assert not pw.articles_panel.isHidden() and not pw.articles_panel._rows["kb_printer_basics"].attached_label.isHidden()

    # A shared ending offers its own articles (read / attach only), and attaching there updates the saved session.
    pw.restart()
    pw._choose(kb.steps["start"].options[0])                                               # -> queued
    assert pw.articles_panel.isHidden()                                                   # that step offers none
    pw._choose(kb.steps["queued"].options[0])                                              # -> shared "restart_spooler"
    assert pw.engine.is_finished and pw.engine.resolution_id == "restart_spooler"
    r2 = pw.articles_panel._rows["kb_spooler"]
    assert r2.use_btn.isHidden()
    r2.attach_btn.click()
    assert "KB attached: Restarting the Print Spooler" in pw.report_box.toPlainText()
    pw.flush()
    assert store.count() == 2                                                             # the earlier session is kept too, in progress
    saved = next(r for r in store.load_all() if r.resolution_id == "restart_spooler")
    assert saved.resolution_id == "restart_spooler" and [(a.article_id, a.action) for a in saved.articles] == [("kb_spooler", _ATT)]
    pw.restart()
    assert pw.engine.article_events == []

    # Flows without articles show no panel at all, and a dangling article id never breaks the screen.
    plain = PlayerWidget(Tree.load("sample_tree.json"))
    assert plain.articles_panel.isHidden()
    broken = Tree.load("examples/shared_resolutions_and_kb.json")
    broken.steps["start"].articles = ["ghost", "kb_spooler"]
    bw = PlayerWidget(broken)
    assert list(bw.articles_panel._rows) == ["kb_spooler"]
print("player: KB articles read / attach / use as resolution, back, report, saved session OK")


# --- Player + Editor: rejected endings ("This didn't work"), skipping, escalation, overlay flag ---
from engine import Resolution as _Res
from feedback import analyze as _analyze, write_bundle as _write_bundle

with _tf2.TemporaryDirectory() as d:
    rt = Tree.load("examples/shared_resolutions_and_kb.json")
    rt.resolutions["escalate"] = _Res("escalate", "Call the print vendor.")
    rt.escalation_id = "escalate"
    assert not [i for i in rt.check() if i.is_error]
    store = _Store(os.path.join(d, "sessions"))
    pw = PlayerWidget(rt, session_store=store)
    pw.show()
    assert pw.reject_btn.isHidden() and pw.escalate_btn.isHidden() and pw.tried_label.isHidden()
    pw._choose(rt.steps["start"].options[1])                                              # offline
    pw._choose(rt.steps["offline"].options[0])                                            # shared "restart_spooler"
    assert pw.engine.resolution_id == "restart_spooler" and not pw.reject_btn.isHidden() and store.count() == 1
    pw.reject_btn.click()                                                                 # it didn't work
    assert not pw.engine.is_finished and pw.engine.current_id == "offline"
    assert store.count() == 1 and store.load_all()[0].outcome == "in_progress"
    assert not pw.tried_label.isHidden() and "Restart the Print Spooler" in pw.tried_label.text()
    btns = [pw.answers_layout.itemAt(i).widget() for i in range(pw.answers_layout.count())]
    assert [b.isEnabled() for b in btns] == [False, True] and "already tried" in btns[0].text()
    assert pw.escalate_btn.isHidden()                                                     # the other answer is still available
    pw.back_btn.click()                                                                   # back to the start step
    btns = [pw.answers_layout.itemAt(i).widget() for i in range(pw.answers_layout.count())]
    assert [b.isEnabled() for b in btns] == [True, True, True]                            # queued still has "No" -> offline -> a cable fix
    pw._choose(rt.steps["start"].options[0])                                              # queued: "Yes" ends at restart_spooler
    btns = [pw.answers_layout.itemAt(i).widget() for i in range(pw.answers_layout.count())]
    assert btns[0].isEnabled() is False and "already tried" in btns[0].text() and btns[1].isEnabled()   # same shared ending, other path
    pw._choose(rt.steps["queued"].options[1])                                             # "No" -> offline
    pw._choose(rt.steps["offline"].options[1])                                            # inline "power cycle" ending
    assert pw.engine.resolution_id is None and not pw.reject_btn.isHidden()
    pw.reject_btn.click()                                                                 # reject that one too: nothing left here
    assert pw.engine.nothing_left() and not pw.escalate_btn.isHidden()
    assert all(not pw.answers_layout.itemAt(i).widget().isEnabled() for i in range(pw.answers_layout.count()))
    pw.escalate_btn.click()                                                               # the designated escalation card
    assert pw.engine.is_finished and "Call the print vendor" in pw.resolution_label.text()
    assert pw.reject_btn.isHidden() and not pw.tried_label.isHidden()
    rec = pw.engine.record()
    assert rec.resolution_id == "escalate" and len(rec.rejected_resolutions) == 2
    assert "Tried, didn't work:" in pw.report_box.toPlainText()
    pw.flush()
    (saved,) = store.load_all()
    assert len(saved.rejected_resolutions) == 2
    pw.back_btn.click()
    assert pw.engine.current_id == "offline" and not pw.escalate_btn.isHidden() and not pw.engine.is_finished   # still stuck there; Back undid only the escalation
    pw.restart()
    assert pw.engine.rejected == [] and pw.tried_label.isHidden()

    # Without a designated card the Player still says what to do.
    rt2 = Tree.load("examples/shared_resolutions_and_kb.json")
    p2 = PlayerWidget(rt2)
    p2._choose(rt2.steps["start"].options[2])                                             # driver
    p2._choose(rt2.steps["driver"].options[0])                                            # shared reinstall_driver
    p2.reject_btn.click()
    p2.back_btn.click()
    p2._choose(rt2.steps["start"].options[2])
    assert [b for b in range(p2.answers_layout.count()) if p2.answers_layout.itemAt(b).widget().isEnabled()] == [1]

    # Editor: three sessions that rejected the same shared ending flag it on the graph and in the summary.
    et = Tree.load("examples/shared_resolutions_and_kb.json")
    recs = []
    for _ in range(3):
        e = TroubleshootEngine(et)
        e.choose(e.current_step.options[1])
        e.choose(e.current_step.options[0])
        e.reject_current_ending()
        e.choose(e.current_step.options[1])
        recs.append(e.record())
    bpath = os.path.join(d, "rej.json")
    _write_bundle(bpath, recs, et)
    shown = []
    QMessageBox.information = staticmethod(lambda parent, title, text: shown.append(text))
    edr = EditorWidget(et)
    edr.import_feedback_files([bpath])
    assert "Endings techs keep rejecting" in shown[-1] and "rejected 3 of 3 times (100%)" in shown[-1]
    tips = " ".join(i.toolTip() for i in edr.graph.view.scene().items() if hasattr(i, "toolTip"))
    assert "Rejected 3 of 3 times" in tips
    edr.select_step("offline")
    assert "rejected 3 of 3 times" in edr.step_editor.feedback_box.toPlainText()

    # Editor dialog: designate / clear the escalation card; deleting it clears the designation.
    from widgets.shared_content import SharedContentDialog as _Dlg
    ec = Tree.from_dict(et.to_dict())
    dlg = _Dlg(ec, lambda: None)
    dlg.resolutions_tab.list.setCurrentRow(1)
    dlg.resolutions_tab.escalation_check.setChecked(True)
    assert ec.escalation_id == "reinstall_driver" and "escalation card" in dlg.resolutions_tab.used_label.text()
    dlg.resolutions_tab.list.setCurrentRow(0)
    assert not dlg.resolutions_tab.escalation_check.isChecked() and ec.escalation_id == "reinstall_driver"
    dlg.resolutions_tab.list.setCurrentRow(1)
    dlg.resolutions_tab.escalation_check.setChecked(False)
    assert ec.escalation_id == ""
print("rejected endings: this-didn't-work, skip tried paths, escalate, Back, report/saved session, Editor flag + escalation card OK")


# --- Player search box + Editor tags ---
from engine import Step as _Step, Option as _Opt
from widgets.step_editor import parse_tags

assert parse_tags(" wifi, No internet;WIFI\n, ") == ["wifi", "No internet"]
with _tf2.TemporaryDirectory() as d:
    st = Tree(title="Help desk", root_id="start", steps={
        "start": _Step("start", "What is the symptom?", [_Opt("Can't get online", "wifi"), _Opt("Can't print", "printer")]),
        "wifi": _Step("wifi", "Does the Wi-Fi icon show as connected?", [_Opt("Yes", None, "Power cycle the router."),
                                                                          _Opt("No", None, "Join the network.")],
                      tags=["wifi", "no internet"]),
        "printer": _Step("printer", "Does the printer show as offline?", [_Opt("Yes", None, "Restart the spooler.")], tags=["printer"]),
    })
    store = _Store(os.path.join(d, "sessions"))
    sw = PlayerWidget(st, session_store=store, autofocus_search=True)
    sw.show()
    assert not sw.search_input.isHidden() and sw.search_status.isHidden() and sw.answers_layout.count() == 2
    sw.search_input.setText("no internet")                                                # results replace the question
    assert sw.question_label.isHidden() and not sw.search_status.isHidden()
    btns = [sw.answers_layout.itemAt(i).widget() for i in range(sw.answers_layout.count())]
    assert btns and "Wi-Fi icon" in btns[0].text() and "Tag: no internet" in btns[0].text()
    sw.search_input.setText("zzzz")
    assert sw.answers_layout.count() == 0 and "No matches" in sw.search_status.text()
    sw.search_input.setText("")                                                           # cleared: the normal start screen again
    assert not sw.question_label.isHidden() and sw.answers_layout.count() == 2 and sw.search_status.isHidden()

    sw.search_input.setText("printer")
    sw.search_input.returnPressed.emit()                                                  # Enter takes the top result
    assert sw.engine.current_id == "printer" and sw.engine.entry_step_id == "printer"
    assert sw.search_input.isHidden() and sw.search_input.text() == "" and sw.back_btn.isEnabled()
    assert sw.question_label.text().startswith("Does the printer") and sw.answers_layout.count() == 1
    sw.back_btn.click()                                                                   # Back returns to the start step and its search box
    assert sw.engine.current_id == "start" and not sw.search_input.isHidden() and sw.engine.entry_step_id is None

    sw.search_input.setText("wifi")
    btn = sw.answers_layout.itemAt(0).widget()
    btn.click()                                                                           # or click a result
    sw._choose(st.steps["wifi"].options[0])
    assert sw.engine.is_finished and sw.search_input.isHidden()
    rec = sw.engine.record()
    assert (rec.entry_step_id, rec.search_query) == ("wifi", "wifi") and "Searched for: wifi" in sw.report_box.toPlainText()
    (saved,) = store.load_all()
    assert saved.entry_step_id == "wifi" and saved.search_query == "wifi"
    sw.restart()
    assert sw.engine.entry_step_id is None and sw.search_input.text() == "" and not sw.search_input.isHidden()
    # a one-step flow has nothing to jump to, so no search box
    one = PlayerWidget(Tree(title="T", root_id="a", steps={"a": _Step("a", "Q", [_Opt("x", None, "r")])}))
    assert one.search_input.isHidden()

    # Editor: the tags field edits Step.tags without reformatting what is being typed, and is undoable.
    et = Tree.from_dict(st.to_dict())
    ed = EditorWidget(et)
    ed.select_step("printer")
    ed.step_editor.tags_input.setText("printer, printing,")
    assert et.steps["printer"].tags == ["printer", "printing"]
    assert ed.step_editor.tags_input.text() == "printer, printing,"                       # the trailing comma survived the refresh
    ed.select_step("wifi")
    assert ed.step_editor.tags_input.text() == "wifi, no internet"
    ed.select_step("printer")
    assert ed.step_editor.tags_input.text() == "printer, printing"
    ed.undo()
    assert ed.tree.steps["printer"].tags == ["printer"]
print("search: Player search box (results, Enter, click, Back, record, restart) and Editor tags field OK")


# --- Outcome log: every event leaves the Player through one sink ---
import json as _json
import re as _re
import outcome_log as _ol2

_doc = open("docs/API.md", encoding="utf-8").read()
_documented = {e["event"]: set(e) for e in _json.loads(_re.search(r"<!-- outcome-log-example -->\s*```json\n(.*?)```", _doc, _re.S).group(1))}
rl = Tree.load("examples/shared_resolutions_and_kb.json")
events = []
lw = PlayerWidget(rl, event_sink=lambda e: events.append(e) or True)
lw.show()
assert events == []                                                                       # opening the Player logs nothing
lw.end_session()
assert events == []                                                                       # ...and neither does leaving untouched
lw._choose(rl.steps["start"].options[1])                                                  # offline
lw._choose(rl.steps["offline"].options[0])                                                # shared "restart_spooler" ending
kinds = [e["event"] for e in events]
assert kinds == [_ol2.STARTED, _ol2.ANSWERED, _ol2.ANSWERED, _ol2.FINISHED], kinds
fin = events[-1]
assert (fin["outcome"], fin["resolution_id"], fin["helpful"], fin["answers"]) == ("resolved", "restart_spooler", None, 2)
assert all(e["session_id"] == lw.engine.session_id and e["flow_title"] == rl.title for e in events)
lw._save_now()
assert len(events) == 4                                                                   # nothing changed, so nothing is logged again
lw.ticket_input.setText("INC-77")
lw.yes_btn.click()
lw.flush()
assert [e["event"] for e in events[4:]] == [_ol2.UPDATED] and events[-1]["helpful"] is True and events[-1]["ticket_ref"] == "INC-77"
lw.reject_btn.click()                                                                     # "this didn't work": rejected, then reopened
assert [e["event"] for e in events[5:]] == [_ol2.REJECTED, _ol2.REOPENED]
assert events[5]["resolution_id"] == "restart_spooler" and events[5]["step_id"] == "offline"
first_sid = lw.engine.session_id
lw.restart()                                                                              # Start Over part-way is a reset, never a silent drop
assert events[-1]["event"] == _ol2.RESET and events[-1]["last_step_id"] == "offline" and events[-1]["answers"] == 1
assert events[-1]["restart_count"] == 1
n = len(events)
lw.search_input.setText("zxqv wlmn")
lw.search_input.returnPressed.emit()                                                      # nothing matches: worth logging, once
lw.search_input.returnPressed.emit()
assert [e["event"] for e in events[n:]] == [_ol2.NO_RESULTS] and events[-1]["query"] == "zxqv wlmn"
lw.search_input.setText("printer offline")
lw.search_input.returnPressed.emit()                                                      # a search that lands starts the session there
assert events[-1]["event"] == _ol2.STARTED and events[-1]["entry_step_id"] == "offline" and events[-1]["search_query"] == "printer offline"
assert (events[-1]["restarted_from"], events[-1]["restart_count"]) == (first_sid, 1)         # the chain of resets is recoverable
lw._choose(rl.steps["offline"].options[1])                                                # an inline ending, left unrated
lw.end_session()
assert events[-1]["event"] == _ol2.FINISHED
got = _ol2.fold_sessions(events)
statuses = {x.session_id: x.status for x in got.values()}
assert list(statuses.values()) == [_ol2.STATUS_RESET, _ol2.STATUS_FINISHED], statuses
assert got[first_sid].backs == 0 and got[lw.engine.session_id].restart_count == 1 and got[lw.engine.session_id].restarted_from == first_sid
# Back is logged; parking keeps the call and logs it; resuming logs again; a parked call is saved, not dropped
n = len(events)
lw.restart()                                                                              # a finished session: Start Over is just the next call
assert events[n:] == [] and lw._chain == {"from": None, "count": 0}
lw._choose(rl.steps["start"].options[1])
lw._go_back()
assert events[-1]["event"] == _ol2.BACK and events[-1]["from_step_id"] == "offline"
lw._choose(rl.steps["start"].options[1])
lw.park()
lw.park()                                                                                 # idempotent
assert [e["event"] for e in events[-1:]] == [_ol2.PARKED] and events[-1]["last_step_id"] == "offline"
lw.resume()
assert events[-1]["event"] == _ol2.RESUMED and lw.engine.current_id == "offline"
lw.resume()
assert [e["event"] for e in events].count(_ol2.RESUMED) == 1
assert _ol2.fold_sessions(events)[lw.engine.session_id].parks == 1
lw.end_session()
# every kind that was emitted carries exactly the keys docs/API.md shows for it
for e in events:
    assert set(e) == _documented[e["event"]], (e["event"], set(e) ^ _documented[e["event"]])
# a broken sink must never break the tech's work, and the Editor's Test pane (no sink) logs nothing
bad = PlayerWidget(rl, event_sink=lambda e: False)
bad._choose(rl.steps["start"].options[1])
assert bad.engine.current_id == "offline"
quiet = PlayerWidget(rl)
quiet._choose(rl.steps["start"].options[1])
quiet.restart()
print("outcome log: started/answered/finished/updated/rejected/reopened/abandoned/no-results via one sink, keys match docs, window export + clear OK")

# --- Records are never dropped: reset, parked and abandoned sessions are saved in progress ---
with _tf2.TemporaryDirectory() as d:
    kt = Tree.load("examples/shared_resolutions_and_kb.json")
    nstore = _Store(os.path.join(d, "s"))
    nw = PlayerWidget(kt, session_store=nstore)
    assert nstore.count() == 0
    nw._choose(kt.steps["start"].options[1])                                              # a session with one answer...
    nw.restart()                                                                          # ...started over: kept
    nw._choose(kt.steps["start"].options[1])
    nw.park()                                                                             # ...parked: kept as it stands
    nw.resume()
    nw._choose(kt.steps["offline"].options[0])                                            # ...and finished
    recs = nstore.load_all()
    assert [r.outcome for r in recs].count("in_progress") == 1 and [r.outcome for r in recs].count("resolved") == 1
    nw.restart()
    nw._choose(kt.steps["start"].options[2])
    nw.load_tree(kt)                                                                      # leaving for another flow: kept too
    assert nstore.count() == 3 and sorted(r.outcome for r in nstore.load_all()) == ["in_progress", "in_progress", "resolved"]
    nw.restart()                                                                          # nothing answered: nothing to keep
    assert nstore.count() == 3
    # the Editor's import counts the in-progress ones as traffic, not as endings
    from feedback import analyze as _an
    fbk = _an(kt, nstore.load_all())
    assert fbk.sessions == 3 and fbk.resolved == 1 and fbk.step_visits["start"] == 3
print("records: reset / parked / abandoned / taken-back sessions are kept in progress, never dropped OK")


# --- Personas: one Player, many businesses; hot-swap parks the call; notepad is a per-persona tool ---
import json as _pj
import shutil as _sh
import player_main as _pm
import outcome_log as _pol

with _tf2.TemporaryDirectory() as d:
    pdir = os.path.join(d, "personas")
    _sh.copytree("examples/personas", pdir)
    os.makedirs(os.path.join(pdir, "broken"))
    open(os.path.join(pdir, "broken", "flow.json"), "w").write("{not json")
    os.makedirs(os.path.join(pdir, "no-notepad"))
    _sh.copy("examples/customer_support_triage.json", os.path.join(pdir, "no-notepad", "flow.json"))
    open(os.path.join(pdir, "no-notepad", "persona.json"), "w").write(_pj.dumps({"name": "Initech", "tools": []}))
    os.environ[_pm.DATA_DIR_ENV] = os.path.join(d, "appdata")
    pw0 = _pm.PlayerWindow(personas_dir=pdir)
    pw0.show()
    ids = list(pw0.slots)
    assert ids[0] == "default" and set(ids) == {"default", "acme-it", "globex-support", "broken", "no-notepad"}, ids
    assert not pw0.switcher_bar.isHidden() and pw0.switcher.count() == 5
    assert not pw0.slots["broken"].info.usable and not pw0.switcher.model().item(ids.index("broken")).isEnabled()
    assert "couldn't be loaded" in pw0.statusBar().currentMessage()
    assert pw0.slots["acme-it"].player is None                                            # built the first time you swap to it

    # first persona: take a call part-way, with notes
    first = pw0.player
    assert first.notepad is not None and first.tools_tabs is not None and first.notes_input.isHidden()
    first._choose(first.engine.current_step.options[0])
    first.notepad.setPlainText("Caller is Dana, laptop on guest wifi")
    assert first.engine.notes.startswith("Caller is Dana") and first.has_open_call()
    pw0._refresh_indicators()
    assert pw0.switcher.itemText(0).startswith("● ")

    # swap to Acme: the first call is parked (saved + logged), the window takes on Acme's look and tools
    pw0.switch_to("acme-it")
    assert pw0.current.info.id == "acme-it" and pw0.player is not first and pw0.stack.currentWidget() is pw0.player
    assert pw0.player.notepad is not None and "Acme IT Help Desk" in pw0.windowTitle()
    log0 = _pm._log_for(pw0.slots["default"].key).read()
    assert [e["event"] for e in log0][-1] == _pol.PARKED
    assert [r.outcome for r in _pm._store_for(pw0.slots["default"].key).load_all()] == ["in_progress"]   # not dropped
    assert _pm._store_for(pw0.slots["acme-it"].key).count() == 0 and "persona-acme-it" in str(pw0.store.folder)

    # work an Acme call; notes are per persona
    acme = pw0.player
    acme._choose(acme.engine.current_step.options[0])
    acme.notepad.setPlainText("Acme only")
    assert first.notepad.toPlainText().startswith("Caller is Dana") and acme.engine.notes == "Acme only"

    # swap by keyboard action and by the combo box; a persona without tools has no notepad dock
    pw0.persona_actions.actions()[ids.index("no-notepad")].trigger()
    assert pw0.current.info.id == "no-notepad" and pw0.player.tools_tabs is None and not pw0.player.notes_input.isHidden()
    pw0.switcher.setCurrentIndex(ids.index("default"))
    pw0._switcher_picked(ids.index("default"))
    assert pw0.player is first and first.engine.current_step is not None
    assert [e["event"] for e in _pm._log_for(pw0.slots["default"].key).read()][-1] == _pol.RESUMED
    assert first.engine.notes.startswith("Caller is Dana")                                # the parked call is exactly as it was
    pw0.switch_to("broken")                                                                # an unusable persona can't be swapped to
    assert pw0.player is first

    # finish the first call: the report carries the notepad under "Additional notes"
    while not first.engine.is_finished:
        first._choose(first.engine.current_step.options[0])
    assert "Additional notes" in first.report_box.toPlainText() and "Caller is Dana" in first.report_box.toPlainText()
    assert "Additional notes" in first.engine.record().to_markdown()

    # exports act on the persona you are on
    exported = []
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (os.path.join(d, "log-%d.jsonl" % len(exported)), ""))
    QMessageBox.information = staticmethod(lambda parent, title, text: exported.append(text))
    pw0.switch_to("acme-it")
    pw0._export_log()
    assert len(_pol.read_events(os.path.join(d, "log-0.jsonl"))) == _pm._log_for("persona-acme-it").count()
    assert not any(e["flow_client"] == "default" for e in _pol.read_events(os.path.join(d, "log-0.jsonl")))
    pw0.close()                                                                            # closing logs/saves every open call
    assert [e["event"] for e in _pm._log_for("persona-acme-it").read()][-1] in (_pol.ABANDONED, _pol.FINISHED)

    # a lone flow behaves as before: no switcher, but the notepad is there by default
    os.environ[_pm.PERSONAS_DIR_ENV] = os.path.join(d, "nothing-here")
    solo = _pm.PlayerWindow()
    assert solo.switcher_bar.isHidden() and list(solo.slots) == ["default"] and solo.player.notepad is not None
    # File > Open Flow adds the flow as one more persona and parks the current call
    solo.player._choose(solo.player.engine.current_step.options[0])
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: ("examples/customer_support_triage.json", ""))
    solo._open_flow()
    assert len(solo.slots) == 2 and not solo.switcher_bar.isHidden() and solo.current.info.id == "opened-1"
    assert [e["event"] for e in _pm._log_for(solo.slots["default"].key).read()][-1] == _pol.PARKED
    solo.close()
    del os.environ[_pm.PERSONAS_DIR_ENV], os.environ[_pm.DATA_DIR_ENV]
print("personas: discovery, broken persona listed, hot-swap parks + resumes, per-persona notes/store/log, notepad tool, exports, solo mode OK")

# --- Player must never be able to reach Editor code (service-model guard) ---
assert_player_cannot_reach_editor()  # exits the process if this ever fails

print("ALL SMOKE TESTS PASSED")
