"""Guards for the merge contract: the core package never imports Gradio."""

import ast
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "birdie"


def test_core_never_imports_gradio():
    offenders = []
    for path in CORE.rglob("*.py"):
        if "ui" in path.relative_to(CORE).parts:
            continue  # UI code may import Gradio
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n == "gradio" or n.startswith("gradio.") or n.startswith("birdie.ui") for n in names):
                offenders.append(str(path.relative_to(CORE)))
    assert offenders == []


def test_no_frames_written_by_core():
    """No image or video writing calls in the core (frames stay in memory)."""
    banned = ("imwrite(", "VideoWriter(", ".save(")
    hits = []
    for path in CORE.rglob("*.py"):
        if "ui" in path.relative_to(CORE).parts:
            continue
        text = path.read_text(encoding="utf-8")
        hits += [f"{path.name}: {b}" for b in banned if b in text]
    assert hits == []
