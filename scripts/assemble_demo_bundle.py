"""Assemble the folder a tester downloads from the Windows build: the demo Player exe, the Editor exe,
a personas/ folder beside the Player (so the persona switcher is there to try), the demo flow with its
images, and a short checklist.

Usage: python scripts/assemble_demo_bundle.py <out-dir> <player-exe> [<editor-exe>] [<demo-flow-dir>]
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TRY_ME = """Longleaf - things to try
=========================

Files
  Longleaf-Player-*.exe   the Player (branded demo flow: logo, blue accent, screenshots)
  personas/               two more businesses for the Player to speak for (copy a folder to add one)
  Longleaf-Editor.exe     the Editor (internal tool; never goes to a client)
  demo-flow/              the demo flow with its images, to open in the Editor

Player (keep personas\\ in the same folder as the exe)
  1. It opens with a search box focused. Type "printer offline": results appear; Enter jumps to the step.
  2. The logo, blue accent and the screenshots show. The first question has a Knowledge base list.
  3. A "Speaking for" box at the top lists the demo flow, Acme IT Help Desk and Globex Customer Support.
     Answer a question or two, type something in the Notepad on the right, then pick another business
     (or Ctrl+2). Come back: the call and the notes are exactly where you left them. A dot marks a
     business with a call open.
  4. Finish a call: Notepad text appears in the report under "Additional notes". Answer "Did this solve it?"
  5. On an ending, "This didn't work" returns you to try something else; the tried answer is greyed out.
  6. File > Export Feedback, File > Export Outcome Log (a .jsonl file), File > Clear Saved Sessions.
  7. Saved data lives under %APPDATA%\\Yellowhammer\\Longleaf (sessions\\ and logs\\ per business).

Editor
  1. File > Open Flow: demo-flow\\flow.json. Edit something, then Edit > Undo / Redo (Ctrl+Z, Ctrl+Y).
  2. Close it without saving after an edit: the next launch offers to recover your work.
  3. Shared... opens shared resolutions and KB articles; the step form has Search tags and KB articles.
"""


def main(out: Path, player: Path, editor: Path | None, demo_dir: Path | None):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy2(player, out / player.name)
    if editor and editor.exists():
        shutil.copy2(editor, out / editor.name)
    shutil.copytree(ROOT / "examples" / "personas", out / "personas")
    if demo_dir and demo_dir.is_dir():
        shutil.copytree(demo_dir, out / "demo-flow")
    (out / "TRY-ME.txt").write_text(TRY_ME, encoding="utf-8")
    print("assembled", out, sorted(p.name for p in out.iterdir()))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    main(Path(a[0]), Path(a[1]), Path(a[2]) if len(a) > 2 else None, Path(a[3]) if len(a) > 3 else None)
