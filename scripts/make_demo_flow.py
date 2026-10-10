"""Write a branded demo flow with a logo and screenshots into a folder, for
trying out build_client_release.py (images must bundle and display).

Usage: python scripts/make_demo_flow.py <out-dir>
Writes <out-dir>/flow.json plus images/. Uses Qt offscreen to draw the PNGs.
"""
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter  # noqa: E402


def draw(path: Path, w: int, h: int, bg: str, text: str):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(bg))
    p = QPainter(img)
    p.setPen(QColor("white"))
    p.setFont(QFont("Sans", 20, QFont.Bold))
    p.drawText(img.rect(), 0x84, text)   # centred
    p.end()
    path.parent.mkdir(parents=True, exist_ok=True)
    assert img.save(str(path)), path


def main(out: Path):
    app = QGuiApplication([])  # noqa: F841  (QPainter needs it)
    draw(out / "images/logo.png", 240, 64, "#1f6feb", "ACME LOGO")
    draw(out / "images/step_shot.png", 480, 200, "#444444", "STEP SCREENSHOT")
    draw(out / "images/fix_shot.png", 480, 200, "#2e7d32", "SHARED FIX SCREENSHOT")
    flow = json.loads((Path(__file__).resolve().parent.parent / "examples/shared_resolutions_and_kb.json").read_text(encoding="utf-8"))
    flow["title"] = "Demo: Printer Won't Print"
    flow["client"] = "Acme Demo"
    flow["branding"] = {"name": "Acme IT Help", "accent": "#1f6feb", "logo": "images/logo.png"}
    flow["steps"]["start"]["image"] = "images/step_shot.png"
    flow["resolutions"]["restart_spooler"]["image"] = "images/fix_shot.png"
    (out / "flow.json").write_text(json.dumps(flow, indent=2), encoding="utf-8")
    print("wrote", out / "flow.json")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
