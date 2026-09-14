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

# --- Player must never be able to reach Editor code (service-model guard) ---
assert_player_cannot_reach_editor()  # exits the process if this ever fails

print("ALL SMOKE TESTS PASSED")
