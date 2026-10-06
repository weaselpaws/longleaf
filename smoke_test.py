"""
Quick regression check for the engine + widgets. Not a full test suite —
just enough to catch the class of bug where the UI silently corrupts the
model (see the StepEditor/OptionRow load-order bug this caught).

Run with: venv\\Scripts\\python.exe smoke_test.py
"""

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication

from engine import Tree, TroubleshootEngine
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

# --- Player must never be able to reach Editor code (service-model guard) ---
assert_player_cannot_reach_editor()  # exits the process if this ever fails

print("ALL SMOKE TESTS PASSED")
