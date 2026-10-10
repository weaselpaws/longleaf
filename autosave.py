"""
Longleaf - Editor autosave and crash recovery (no GUI).

While a flow has unsaved changes, the Editor writes a recovery copy to the
app-data folder (one small file per flow, replaced atomically). A normal
save, discard or close deletes it, so any file still there at the next start
is work that was lost to a crash or power cut and is offered back.

The flow's own file is never touched by autosave. Editor only; the Player
never imports this (see build_client_release.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

KIND = "longleaf-autosave"


@dataclass
class Recovery:
    slot: str
    flow_path: Optional[str]   # where the flow was saved, or None if it was never saved
    title: str
    saved_at: str              # ISO-8601
    tree: dict

    @property
    def label(self) -> str:
        name = os.path.basename(self.flow_path) if self.flow_path else (self.title or "Untitled Flow")
        try:
            when = datetime.fromisoformat(self.saved_at).strftime("%b %d, %H:%M")
        except ValueError:
            when = self.saved_at
        return f"{name} (autosaved {when})"


class AutosaveStore:
    def __init__(self, folder: str | os.PathLike):
        self.folder = Path(folder)
        self.session = uuid.uuid4().hex[:12]   # names the slot of a flow that has no file yet

    def slot_for(self, flow_path: Optional[str]) -> str:
        if flow_path:
            return "flow-" + hashlib.sha1(os.path.abspath(flow_path).encode("utf-8")).hexdigest()[:16]
        return f"untitled-{self.session}"

    def _file(self, slot: str) -> Path:
        return self.folder / f"{slot}.autosave.json"

    def write(self, flow_path: Optional[str], tree: dict) -> bool:
        """Replace this flow's recovery copy. Returns False (never raises) if the folder isn't writable."""
        slot = self.slot_for(flow_path)
        body = {"kind": KIND, "flow_path": flow_path, "title": tree.get("title", ""),
                "saved_at": datetime.now().astimezone().isoformat(), "tree": tree}
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self._file(slot).with_suffix(".tmp")
            tmp.write_text(json.dumps(body), encoding="utf-8")
            os.replace(tmp, self._file(slot))
            return True
        except OSError:
            return False

    def discard(self, flow_path: Optional[str]):
        try:
            self._file(self.slot_for(flow_path)).unlink(missing_ok=True)
        except OSError:
            pass

    def pending(self) -> list[Recovery]:
        """Recovery copies left behind, newest first. Unreadable files are skipped."""
        found = []
        for p in self.folder.glob("*.autosave.json") if self.folder.is_dir() else []:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("kind") != KIND or not isinstance(d.get("tree"), dict):
                    continue
                found.append(Recovery(p.name[:-len(".autosave.json")], d.get("flow_path"), d.get("title", ""),
                                      d.get("saved_at", ""), d["tree"]))
            except (OSError, ValueError):
                continue
        return sorted(found, key=lambda r: r.saved_at, reverse=True)

    def discard_slot(self, slot: str):
        try:
            self._file(slot).unlink(missing_ok=True)
        except OSError:
            pass
