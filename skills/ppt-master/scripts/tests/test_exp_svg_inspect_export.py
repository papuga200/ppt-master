"""exp_svg render_export (SVG helpers experiment, 2026-09-30): temporary project, PPTX line ends, arrowhead comparison,
the machine-wide PowerPoint lock, and an end-to-end export.

The parsing and comparison tests run anywhere. The export test runs the fork's gate and exporter on a synthetic slide
(no PowerPoint) when Playwright Chromium is available. The PowerPoint render/parity test runs only when
EXP_SVG_TEST_POWERPOINT=1, because PowerPoint is a single shared COM instance on the machine.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
INSPECT = SCRIPTS / "exp_svg" / "inspect"
for folder in (SCRIPTS, INSPECT):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import render_export as R  # noqa: E402

SLIDE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
<p:cSld><p:spTree>
<p:sp><p:nvSpPr><p:cNvPr id="2" name="dep-1"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
<p:spPr><a:xfrm><a:off x="952500" y="952500"/><a:ext cx="952500" cy="476250"/></a:xfrm>
<a:custGeom><a:pathLst><a:path w="100" h="50"><a:moveTo><a:pt x="0" y="0"/></a:moveTo><a:lnTo><a:pt x="100" y="0"/></a:lnTo><a:lnTo><a:pt x="100" y="50"/></a:lnTo></a:path></a:pathLst></a:custGeom>
<a:ln w="19050"><a:tailEnd type="triangle" w="lg" len="lg"/></a:ln></p:spPr></p:sp>
<p:sp><p:nvSpPr><p:cNvPr id="3" name="back"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
<p:spPr><a:xfrm flipH="1"><a:off x="0" y="0"/><a:ext cx="952500" cy="0"/></a:xfrm><a:prstGeom prst="line"><a:avLst/></a:prstGeom>
<a:ln w="12700"><a:headEnd type="triangle"/></a:ln></p:spPr></p:sp>
</p:spTree></p:cSld></p:sld>"""


def test_line_ends_from_slide_xml():
    from lxml import etree
    ends = R._line_ends(etree.fromstring(SLIDE_XML.encode("utf-8")))
    dep = next(e for e in ends if e["name"] == "dep-1")
    assert dep["start"] == pytest.approx([100.0, 100.0]) and dep["end"] == pytest.approx([200.0, 150.0])
    assert dep["tail"] == {"type": "triangle", "w": "lg", "len": "lg"} and dep["head"] is None and dep["line_px"] == pytest.approx(2.0)
    back = next(e for e in ends if e["name"] == "back")
    assert back["start"] == pytest.approx([100.0, 0.0]) and back["end"] == pytest.approx([0.0, 0.0])  # flipH swaps the ends
    assert back["head"]["len"] == "med"


def test_arrow_findings_attribute_changes_to_conversion():
    lines = [{"name": "dep-1", "start": [100.0, 100.0], "end": [200.0, 150.0], "head": None, "tail": {"type": "triangle", "w": "lg", "len": "lg"}, "line_px": 2.0}]
    svg = [{"ref": "dep-1", "id": "dep-1", "which": "end", "tip": [200.0, 150.0], "marker": "a", "orient": "auto", "marker_len_px": 9.0, "stroke_px": 1.5},
           {"ref": "x", "id": "x", "which": "start", "tip": [100.0, 100.0], "marker": "a", "orient": "auto", "marker_len_px": 9.0, "stroke_px": 1.5},
           {"ref": "lost", "id": "lost", "which": "end", "tip": [600.0, 600.0], "marker": "a", "orient": "auto", "marker_len_px": 9.0, "stroke_px": 1.5}]
    rows = {r["svg_ref"]: r for r in R.arrow_findings(svg, lines)}
    assert rows["dep-1"]["code"] == "ARROWHEAD_KEPT"
    assert rows["x"]["code"] in ("ARROWHEAD_DROPPED", "ARROWHEAD_MOVED")  # the PPTX line has its end at the other tip
    assert rows["lost"]["code"] == "ARROWHEAD_DROPPED"
    assert all(r["attribution"] == "conversion" for r in rows.values())


def test_prepare_project_copies_referenced_files(tmp_path):
    src = tmp_path / "deck" / "svg_output"
    (tmp_path / "deck" / "images").mkdir(parents=True)
    src.mkdir(parents=True)
    (tmp_path / "deck" / "images" / "logo.png").write_bytes(b"\x89PNG fake")
    svg = src / "01 page.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="../images/logo.png"/><image href="../missing.png"/></svg>', encoding="utf-8")
    page, notes = R.prepare_project(svg, tmp_path / "proj")
    assert page.name == "01_page.svg" and (tmp_path / "proj" / "images" / "logo.png").is_file()
    assert {n["href"]: n["copied"] for n in notes} == {"../images/logo.png": True, "../missing.png": False}


def test_token_retention_detects_changed_words():
    assert R.token_retention(["Gate 1 decides rollout"], ["Gate 1", "decides rollout"])["equal"]
    diff = R.token_retention(["one governed system"], ["onegoverned system"])
    assert not diff["equal"] and diff["missing_in_pptx"] == {"one": 1, "governed": 1}


def test_powerpoint_lock_serializes_and_recovers_a_stale_lock(tmp_path):
    lock = tmp_path / "pp.lock"
    finished = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    lock.write_text(finished.stdout.strip(), encoding="ascii")  # a pid that has exited
    with R.PowerPointLock(lock) as held:
        assert held.took_over == int(finished.stdout.strip())
        assert lock.read_text(encoding="ascii") == str(os.getpid())
    assert not lock.exists()


def _browser() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _browser(), reason="Playwright Chromium not available")
def test_export_without_powerpoint(tmp_path):
    import synthetic
    svg = tmp_path / "slide.svg"
    svg.write_text(synthetic.architecture_svg(), encoding="utf-8")
    result = R.render_export(svg, tmp_path / "out", powerpoint=False)
    assert result["status"] == "ok" and result["pptx"]["zip_ok"] and result["pptx"]["slides"] == 1
    assert result["pptx"]["native"]["text_shapes"] == 10 and result["text_retention"]["equal"]
    assert {a["code"] for a in result["arrowheads"]} == {"ARROWHEAD_KEPT"}
    assert any(f["code"] == "POWERPOINT_SKIPPED" and f["attribution"] == "environment" for f in result["findings"])
    refused = tmp_path / "refused.svg"
    refused.write_text(synthetic.architecture_svg(marker_bugs=True), encoding="utf-8")  # fixed-orient marker: outside the exporter's contract
    bad = R.render_export(refused, tmp_path / "out2", powerpoint=False)
    assert bad["status"] == "error" and bad["findings"][0]["attribution"] == "exporter_contract"


@pytest.mark.skipif(os.environ.get("EXP_SVG_TEST_POWERPOINT") != "1", reason="set EXP_SVG_TEST_POWERPOINT=1 to drive PowerPoint")
def test_export_with_powerpoint(tmp_path):
    import synthetic
    svg = tmp_path / "slide.svg"
    svg.write_text(synthetic.architecture_svg(), encoding="utf-8")
    result = R.render_export(svg, tmp_path / "out")
    assert result["status"] == "ok" and result["pptx_render"] and result["parity"]["summary"]["slides"] == 1
    assert len(result["arrowhead_ink"]) == 5
