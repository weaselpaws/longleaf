"""Assemble the folder a tester downloads from the Windows build: the demo Player exe, the Editor exe,
a personas/ folder beside the Player (so the persona switcher is there to try), the demo flow with its
images, a made-up sample outcome log to try the Editor's Analytics with, and a short checklist.

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
  4. Analytics (the second button in the toolbar, Ctrl+2): "Open outcome logs..." and choose
     sample-data\\outcome-log-SAMPLE.jsonl. It is MADE-UP data (three flows, a month of calls) so there is
     something to look at. Try: the flow picker, the Cards tab (amber = where techs give up; open the
     flow personas\\acme-it\\flow.json in the Editor to see card names), Endings (orange = fixes techs keep rejecting),
     Searches (what found nothing), Export summary... (a Markdown review you could send a client).
     To look at your own calls, use the Player's File > Export Outcome Log... and open that file instead.
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
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_sample_log
    import outcome_log
    sample = out / "sample-data" / "outcome-log-SAMPLE.jsonl"
    sample.parent.mkdir()
    log = outcome_log.OutcomeLog(sample.parent)
    log.path = sample
    for event in make_sample_log.generate():
        log.emit(event)
    (out / "TRY-ME.txt").write_text(TRY_ME, encoding="utf-8")
    print("assembled", out, sorted(p.name for p in out.iterdir()))


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    main(Path(a[0]), Path(a[1]), Path(a[2]) if len(a) > 2 else None, Path(a[3]) if len(a) > 3 else None)
