"""Fork tools of the consulting-quality profile: the review journal and reference matching."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import page_review  # noqa: E402
import reference_library  # noqa: E402


def _project(tmp_path: Path) -> Path:
    (tmp_path / "svg_output").mkdir()
    (tmp_path / "svg_output" / "01_cover.svg").write_text("<svg/>", encoding="utf-8")
    return tmp_path


def _render_args(project: Path, **extra):
    import argparse
    return argparse.Namespace(project=str(project), page="01_cover", crop=None, **extra)


def test_revision_counts_changed_content_only(tmp_path, monkeypatch):
    project = _project(tmp_path)
    png = project / "p.png"
    png.write_bytes(b"x")
    monkeypatch.setattr(page_review, "_render", lambda root, pages: [{"ok": True, "path": str(png)}])
    page_review.cmd_render(_render_args(project))
    page_review.cmd_render(_render_args(project))  # same content: a second look, not a revision
    entry = page_review.load_journal(project)["pages"]["01_cover"]
    assert (entry["renders"], entry["revisions"], len(entry["backups"])) == (2, 0, 1)
    (project / "svg_output" / "01_cover.svg").write_text("<svg id='b'/>", encoding="utf-8")
    page_review.cmd_render(_render_args(project))
    entry = page_review.load_journal(project)["pages"]["01_cover"]
    assert (entry["revisions"], len(entry["backups"])) == (1, 2)


def test_restore_brings_back_an_earlier_revision(tmp_path, monkeypatch):
    project = _project(tmp_path)
    png = project / "p.png"
    png.write_bytes(b"x")
    monkeypatch.setattr(page_review, "_render", lambda root, pages: [{"ok": True, "path": str(png)}])
    page_review.cmd_render(_render_args(project))
    svg = project / "svg_output" / "01_cover.svg"
    svg.write_text("<svg id='worse'/>", encoding="utf-8")
    page_review.cmd_render(_render_args(project))
    import argparse
    page_review.cmd_restore(argparse.Namespace(project=str(project), page="01_cover", rev=0))
    assert svg.read_text(encoding="utf-8") == "<svg/>"


def test_outcome_needs_a_look_first(tmp_path):
    import argparse
    import pytest
    project = _project(tmp_path)
    with pytest.raises(SystemExit):
        page_review.cmd_note(argparse.Namespace(project=str(project), page="01_cover", outcome="accepted", text="fine"))


def test_rejected_entries_never_match_positively():
    good = {"id": "a", "labels": {"communication_form": "timeline", "devices": ["phase ruler"]}}
    score_good, _ = reference_library.score(good, "timeline", {"phase", "ruler"}, None)
    assert score_good > reference_library.WEAK_SCORE
    assert reference_library._rejected({"verdict": "rejected"}) and not reference_library._rejected(good)


def test_form_outranks_shared_words():
    same_form = {"labels": {"communication_form": "architecture"}}
    other_form = {"labels": {"communication_form": "cover", "devices": ["hub", "band"]}}
    assert reference_library.score(same_form, "architecture", {"hub", "band"}, None)[0] > \
        reference_library.score(other_form, "architecture", {"hub", "band"}, None)[0]
