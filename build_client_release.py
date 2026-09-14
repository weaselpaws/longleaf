"""
Build a standalone Player .exe for one client, with their flow baked in.

This is a service-model build: each client gets a Longleaf-Player exe
with their flow.json bundled in via PyInstaller's `datas`, and nothing
else — no Editor, no other client's flow, no editing capability. There
is no public release step here; the output is a file you hand to that
one client.

Usage:
    venv\\Scripts\\python.exe build_client_release.py <client-slug> <version> <path-to-flow.json>

Example:
    venv\\Scripts\\python.exe build_client_release.py acme-hvac 1.0.0 clients\\acme-hvac\\flow.json

Produces:
    dist\\Longleaf-Player-acme-hvac-v1.0.0.exe

Before every build, this script statically re-checks that player_main.py's
import graph can't reach editor_main.py or any of the editor-only widgets
(widgets/editor_widget.py, widgets/step_editor.py, widgets/option_row.py).
If that ever becomes false — e.g. someone adds an "Edit" menu item to the
Player down the road — the build refuses to run rather than silently
shipping editing capability to a client.
"""

import argparse
import ast
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
PLAYER_ENTRY = ROOT / "player_main.py"
FORBIDDEN_MODULES = {"editor_main", "widgets.editor_widget", "widgets.step_editor", "widgets.option_row"}


def _imported_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def assert_player_cannot_reach_editor():
    """Walk the Player's local (non-stdlib, non-PySide6) import graph and
    refuse to build if it can reach anything editor-only."""
    seen: set[Path] = set()
    to_visit = [PLAYER_ENTRY]
    reached_modules: set[str] = set()

    while to_visit:
        current = to_visit.pop()
        if current in seen or not current.exists():
            continue
        seen.add(current)

        for mod in _imported_modules(current):
            top = mod.split(".")[0]
            reached_modules.add(mod)
            # Only follow local modules (this repo), not stdlib/PySide6.
            candidate = ROOT / f"{mod.replace('.', '/')}.py"
            if candidate.exists():
                to_visit.append(candidate)
            else:
                candidate = ROOT / f"{top}.py"
                if candidate.exists():
                    to_visit.append(candidate)

    hit = reached_modules & FORBIDDEN_MODULES
    if hit:
        sys.exit(
            f"REFUSING TO BUILD: player_main.py's import graph reaches {hit} "
            f"— a client build would include editor capability. Fix the "
            f"import before building a client release."
        )
    print(f"OK: player_main.py's import graph ({len(seen)} local files) does not reach {FORBIDDEN_MODULES}")


def build(client: str, version: str, flow_path: Path):
    flow_path = flow_path.resolve()
    if not flow_path.exists():
        sys.exit(f"Flow file not found: {flow_path}")

    exe_name = f"Longleaf-Player-{client}-v{version}"
    print(f"Building {exe_name}.exe from {flow_path}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # player_main.py looks for a file literally named flow.json next to
        # the exe, regardless of what the client's source file was called.
        staged_flow = tmp / "flow.json"
        shutil.copy(flow_path, staged_flow)

        sep = ";" if sys.platform == "win32" else ":"
        cmd = [
            sys.executable, "-m", "PyInstaller",
            str(PLAYER_ENTRY),
            "--noconfirm",
            "--onefile",
            "--noconsole",
            "--name", exe_name,
            "--add-data", f"{staged_flow}{sep}.",
            "--workpath", str(ROOT / "build"),
            "--specpath", str(tmp),
            "--distpath", str(ROOT / "dist"),
        ]
        subprocess.run(cmd, check=True, cwd=ROOT)

    print(f"Done: dist\\{exe_name}.exe")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("client", help="Client slug, e.g. acme-hvac (used in the output filename)")
    parser.add_argument("version", help="Version string, e.g. 1.0.0")
    parser.add_argument("flow", type=Path, help="Path to the client's flow .json file")
    args = parser.parse_args()

    assert_player_cannot_reach_editor()
    build(args.client, args.version, args.flow)
