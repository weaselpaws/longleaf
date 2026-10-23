"""
Longleaf - personas (no GUI).

A persona is one business an agent speaks for. A BPO call center takes calls
for many businesses; each gets a folder:

    personas/
      acme-hvac/
        flow.json          the business's flow (branding and images live with it)
        persona.json       optional: {"name": "Acme HVAC", "tools": ["notepad"]}
      globex-support/
        flow.json

The Player lists them and the agent swaps between them while on a call (the
call in progress is parked, not dropped). Adding a business is copying a
folder; no rebuild. With no personas folder the Player behaves as before: one
flow, no switcher.

persona.json is optional. `tools` picks which small tools sit beside the flow
for this persona (today: "notepad"); leave it out for the default, or give an
empty list for none. Unknown tool names are ignored and reported.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from engine import Tree

PERSONA_FILE = "persona.json"
FLOW_FILE = "flow.json"
KNOWN_TOOLS = ("notepad",)
DEFAULT_TOOLS = ("notepad",)


@dataclass
class PersonaInfo:
    id: str
    name: str
    flow_path: str
    folder: str
    tools: tuple = DEFAULT_TOOLS
    error: str = ""                      # set when the persona can't be used (flow missing or unreadable)
    warnings: list = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not self.error


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text or "").strip("-")


def read_persona_json(path: Path) -> tuple[dict, list[str]]:
    """The persona.json settings, plus anything wrong with them. A missing file is fine; a broken one
    is reported but doesn't stop the persona loading."""
    if not path.exists():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {}, [f"{PERSONA_FILE} couldn't be read ({e}); using defaults."]
    if not isinstance(data, dict):
        return {}, [f"{PERSONA_FILE} must be an object; using defaults."]
    return data, []


def load_persona(folder: str | Path, persona_id: Optional[str] = None, flow_name: str = FLOW_FILE) -> PersonaInfo:
    """Read one persona folder. Never raises: problems come back in `error` / `warnings`."""
    folder = Path(folder)
    pid = persona_id or slug(folder.name) or "persona"
    flow_path = folder / flow_name
    if not flow_path.exists():
        return PersonaInfo(pid, folder.name, str(flow_path), str(folder), error=f"no {flow_name} in {folder.name}/")
    try:
        tree = Tree.load(str(flow_path))
    except Exception as e:   # unreadable JSON, wrong shape, ...
        return PersonaInfo(pid, folder.name, str(flow_path), str(folder), error=f"{flow_name} can't be read: {e}")
    data, warnings = read_persona_json(folder / PERSONA_FILE)
    tools = DEFAULT_TOOLS
    if "tools" in data:
        raw = data["tools"]
        if isinstance(raw, list) and all(isinstance(t, str) for t in raw):
            tools = tuple(dict.fromkeys(t for t in raw if t in KNOWN_TOOLS))
            unknown = [t for t in raw if t not in KNOWN_TOOLS]
            if unknown:
                warnings.append(f"Unknown tool{'s' if len(unknown) != 1 else ''} ignored: {', '.join(unknown)}.")
        else:
            warnings.append(f'"tools" must be a list of names; using the default ({", ".join(DEFAULT_TOOLS) or "none"}).')
    name = (str(data.get("name") or "").strip() if isinstance(data.get("name"), (str, int)) else "") \
        or tree.branding.name or tree.client or tree.title or folder.name
    return PersonaInfo(pid, name, str(flow_path), str(folder), tools, warnings=warnings)


def discover_personas(root: str | Path) -> list[PersonaInfo]:
    """Every subfolder of `root` that has a flow.json, by name. Folders that aren't personas
    (no flow.json) are ignored; ones whose flow is broken are listed with an `error`."""
    root = Path(root)
    found = []
    try:
        folders = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    except OSError:
        return []
    seen: set[str] = set()
    for folder in folders:
        if not (folder / FLOW_FILE).exists():
            continue
        info = load_persona(folder)
        base, n = info.id, 2
        while info.id in seen:                 # two folders that slug the same way still get separate ids
            info.id = f"{base}-{n}"
            n += 1
        seen.add(info.id)
        found.append(info)
    return sorted(found, key=lambda p: p.name.lower())
