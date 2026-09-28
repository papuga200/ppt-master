"""Curated reference library: build from a spec, retrieve by exhibit form and need, print the take/avoid notes (F09)."""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / "reference_library.py"


def _spec(tmp: Path) -> Path:
    img = tmp / "page.png"
    Image.new("RGB", (160, 90), "white").save(img)
    entries = [
        {"id": "a-flow", "image_source": str(img), "crop": [0, 0, 80, 45], "form": "process-flow", "page": 1, "source": "deck.pdf",
         "purpose": "phases with activities and deliverables", "use_cases": ["approach"], "take": ["chevron headers"], "avoid": ["tiny text"],
         "why": "grid answers what and when", "restrictions": "structure only"},
        {"id": "b-gantt", "image_source": str(img), "form": "timeline", "page": 2, "purpose": "workplan with milestones", "use_cases": ["plan"]},
        {"id": "c-loop", "image_source": str(img), "form": "loop", "page": 3, "purpose": "review cycle", "use_cases": ["iteration"]},
    ]
    spec = tmp / "spec.json"
    spec.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return spec


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=True).stdout


def test_curate_crops_and_indexes(tmp_path):
    lib = tmp_path / "lib"
    _run("curate", str(_spec(tmp_path)), "--library", str(lib))
    index = json.loads((lib / "index.json").read_text(encoding="utf-8"))["entries"]
    assert [e["id"] for e in index] == ["a-flow", "b-gantt", "c-loop"]
    assert Image.open(lib / "images" / "a-flow.png").size == (80, 45)
    assert index[0]["labels"]["communication_form"] == "process-flow" and index[0]["verdict"] == "good"


def test_match_prefers_form_and_need_and_drops_weak_padding(tmp_path):
    lib = tmp_path / "lib"
    _run("curate", str(_spec(tmp_path)), "--library", str(lib))
    out = _run("match", "--library", str(lib), "--form", "process-flow", "--need", "delivery phases and deliverables", "--limit", "3")
    refs = [line for line in out.splitlines() if line.startswith("reference ")]
    assert refs[0].startswith("reference a-flow")
    assert len(refs) == 1, out  # loop and timeline are only related/weak: not padded in
    assert "take: chevron headers" in out and "avoid: tiny text" in out and "provenance: structure only" in out


def test_related_form_still_found_when_no_exact(tmp_path):
    lib = tmp_path / "lib"
    _run("curate", str(_spec(tmp_path)), "--library", str(lib))
    out = _run("match", "--library", str(lib), "--form", "architecture", "--need", "phases", "--limit", "3")
    assert "reference a-flow" in out and "related form" in out
