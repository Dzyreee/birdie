"""Guards for the code structure in CLAUDE.md section 5.

- The core package never imports Gradio (only app.py and birdie/ui/ do).
- Only birdie/api.py imports FastAPI (or Starlette).
- No module writes frames or images: frames stay in memory.
- Nothing of the dropped features (booking, check-in, QR codes, the LLM assistant) is left.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "birdie"


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _python_files() -> list[Path]:
    files = [ROOT / "app.py", *CORE.rglob("*.py"), *(ROOT / "tools").rglob("*.py"), *(ROOT / "jobs").rglob("*.py")]
    return [p for p in files if "__pycache__" not in p.parts]


def test_core_never_imports_gradio():
    offenders = [
        str(p.relative_to(ROOT)) for p in CORE.rglob("*.py")
        if "ui" not in p.relative_to(CORE).parts
        and any(n == "gradio" or n.startswith("gradio.") or n.startswith("birdie.ui") for n in _imports(p))
    ]
    assert offenders == []


def test_only_api_module_imports_fastapi():
    offenders = [
        str(p.relative_to(ROOT)) for p in _python_files()
        if p != CORE / "api.py"
        and any(n.split(".")[0] in ("fastapi", "starlette") for n in _imports(p))
    ]
    assert offenders == []


def test_no_frames_written():
    """No image or video writing calls anywhere in the app (frames stay in memory).

    tools/extract_frames.py is the one exception: it writes PIXELATED copies for the labelling tool.
    """
    banned = ("imwrite(", "VideoWriter(", ".save(")
    hits = []
    for path in [ROOT / "app.py", *CORE.rglob("*.py")]:
        text = path.read_text(encoding="utf-8")
        hits += [f"{path.relative_to(ROOT)}: {b}" for b in banned if b in text]
    assert hits == []


def test_dropped_features_are_gone():
    assert not (CORE / "booking.py").exists()
    assert not (CORE / "assistant").exists()
    assert not (CORE / "ui" / "checkin.py").exists() and not (CORE / "ui" / "find.py").exists()
    patterns = (r"\bqrcode\b", r"\bbookings?\b", r"\bcheck[_-]?in\b", r"\bfanar\b")
    hits = [
        f"{p.relative_to(ROOT)}: {pattern}" for p in [ROOT / "app.py", *CORE.rglob("*.py")]
        for pattern in patterns if re.search(pattern, p.read_text(encoding="utf-8").lower())
    ]
    assert hits == []
    assert "qrcode" not in (ROOT / "requirements.txt").read_text()
