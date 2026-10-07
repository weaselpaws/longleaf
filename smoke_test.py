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
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

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

# --- Player must never be able to reach Editor code (service-model guard) ---
assert_player_cannot_reach_editor()  # exits the process if this ever fails

print("ALL SMOKE TESTS PASSED")
