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

Before every build, this script validates the flow and refuses to build if
it has any validation *errors* (warnings are printed but allowed), then
stamps the release version (and client, if the flow doesn't name one) into
the bundled copy so exported reports identify the exact build.

Images referenced by the flow (branding logo, step and answer screenshots) are
looked up relative to the flow file, checked for existence, and bundled next to
the staged flow.json at the same relative paths.

Also, before every build, this script statically re-checks that player_main.py's
import graph can't reach editor_main.py or any of the editor-only widgets
(widgets/editor_widget.py, widgets/step_editor.py, widgets/option_row.py,
widgets/image_picker.py, widgets/graph_view.py, graph_layout.py, undo_stack.py, autosave.py).
If that ever becomes false — e.g. someone adds an "Edit" menu item to the
Player down the road — the build refuses to run rather than silently
shipping editing capability to a client.
"""

import argparse
import ast
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from engine import FlowFormatError, Tree  # noqa: E402  (GUI-free; not part of the Player's import check)

ROOT = Path(__file__).parent.resolve()
PLAYER_ENTRY = ROOT / "player_main.py"
FORBIDDEN_MODULES = {"editor_main", "widgets.editor_widget", "widgets.step_editor", "widgets.option_row", "widgets.image_picker",
                     "widgets.graph_view", "graph_layout", "undo_stack", "autosave"}


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


def load_and_gate_flow(flow_path: Path) -> dict:
    """Read the flow, refuse to ship it if it has validation errors, and
    return the raw JSON (kept raw so unknown keys survive being stamped)."""
    try:
        raw = json.loads(flow_path.read_text(encoding="utf-8"))
        tree = Tree.from_dict(raw)
    except (OSError, json.JSONDecodeError, FlowFormatError) as e:
        sys.exit(f"Can't read flow {flow_path}: {e}")

    issues = tree.check(base_dir=str(flow_path.parent))
    errors = [i for i in issues if i.is_error]
    for i in issues:
        print(f"  {'ERROR  ' if i.is_error else 'warning'}  {i.message}")
    if errors:
        sys.exit(
            f"REFUSING TO BUILD: {flow_path.name} has {len(errors)} validation error(s) (listed above). "
            f"Fix them in the Editor — a client would hit these in the field."
        )
    if issues:
        print(f"Proceeding: {len(issues)} warning(s) only.")
    return raw


def stage_assets(raw_flow: dict, flow_dir: Path, staging: Path) -> list[tuple[Path, str]]:
    """Copy every image the flow references into `staging`, keeping its
    relative path, and return (staged file, bundle folder) pairs for
    PyInstaller's --add-data. load_and_gate_flow has already verified the
    paths are relative, inside the flow's folder, and exist."""
    pairs = []
    for rel in Tree.from_dict(raw_flow).asset_paths():
        dest = staging / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(flow_dir / rel, dest)
        pairs.append((dest, str(Path(rel).parent)))
    return pairs


def build(client: str, version: str, flow_path: Path):
    flow_path = flow_path.resolve()
    if not flow_path.exists():
        sys.exit(f"Flow file not found: {flow_path}")

    raw_flow = load_and_gate_flow(flow_path)
    # Stamp the release into the bundled copy so every report the client
    # exports names the exact build. The release version always wins; the
    # client slug only fills in if the flow doesn't already carry a
    # friendlier display name.
    raw_flow["version"] = version
    if not raw_flow.get("client"):
        raw_flow["client"] = client

    exe_name = f"Longleaf-Player-{client}-v{version}"
    print(f"Building {exe_name}.exe from {flow_path}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # player_main.py looks for a file literally named flow.json next to
        # the exe, regardless of what the client's source file was called.
        staged_flow = tmp / "flow.json"
        staged_flow.write_text(json.dumps(raw_flow, indent=2), encoding="utf-8")
        sep = ";" if sys.platform == "win32" else ":"
        asset_args = []
        for staged, bundle_dir in stage_assets(raw_flow, flow_path.parent, tmp):
            asset_args += ["--add-data", f"{staged}{sep}{bundle_dir}"]

        cmd = [
            sys.executable, "-m", "PyInstaller",
            str(PLAYER_ENTRY),
            "--noconfirm",
            "--onefile",
            "--noconsole",
            "--name", exe_name,
            "--add-data", f"{staged_flow}{sep}.",
            *asset_args,
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
