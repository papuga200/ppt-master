"""F10: a review that names no defect lets the page be accepted with notes; a review with a blocker still refuses."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import page_review  # noqa: E402


def _project(tmp_path: Path, verdict: str, blockers: int) -> Path:
    project = tmp_path / "p"
    (project / "svg_output").mkdir(parents=True)
    svg = project / "svg_output" / "03_page.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"/>', encoding="utf-8")
    digest = hashlib.sha256(svg.read_bytes()).hexdigest()
    journal = page_review.load_journal(project)
    journal["pages"]["03_page"] = {"renders": 2, "revisions": 1, "last_sha": digest, "backups": [], "outcome": None,
                                   "review": {"sha": digest, "verdict": verdict, "blockers": blockers, "file": "r.md"}}
    page_review.save_journal(project, journal)
    return project


def _note(project: Path):
    return page_review.cmd_note(argparse.Namespace(project=str(project), page="03_page", outcome="accepted", text="Preserve: x", no_review=False))


def test_polish_only_review_is_accepted_with_notes(tmp_path):
    project = _project(tmp_path, "EXECUTION_REPAIR", 0)
    assert _note(project) == 0
    assert json.loads((project / "quality-run.json").read_text(encoding="utf-8"))["pages"]["03_page"]["outcome"] == "accepted"
    assert "polish notes: 0 blockers" in (project / ".review" / "notes" / "03_page.md").read_text(encoding="utf-8")


def test_a_review_with_a_blocker_still_refuses(tmp_path):
    with pytest.raises(SystemExit):
        _note(_project(tmp_path, "EXECUTION_REPAIR", 1))
    with pytest.raises(SystemExit):
        _note(_project(tmp_path / "b", "CONCEPT_REPLAN", 0))
