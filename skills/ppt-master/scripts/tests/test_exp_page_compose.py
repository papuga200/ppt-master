"""Whole-page composition for the experimental SVG helpers (package B): page_compose.py, build_timeline.py --page,
arch/compose_page.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
EXP = SCRIPTS / "exp_svg"
for _p in (SCRIPTS, EXP, EXP / "arch", EXP / "timeline"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import page_compose  # noqa: E402
import text_measure  # noqa: E402

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" width="1280" height="720" font-family="Segoe UI" data-pptx-page-role="content">
  <g id="chrome" data-pptx-role="chrome" data-pptx-bounds="0 0 1280 720">
    <text id="chrome-wordmark" x="64" y="42" font-size="16" font-weight="bold" fill="#0B5D3B">Example</text>
    <g id="chrome-rules"><line id="chrome-header-rule" x1="64" y1="56" x2="1216" y2="56" stroke="#E6E1D8" stroke-width="1"/></g>
  </g>
  <g id="sample"><text id="sample-title" x="64" y="128" font-size="30">Sample</text></g>
</svg>
"""
LONG_TITLE = "Seven overlapping workstreams reach go-live on 4 January 2027, with a week of float"


def _template(tmp_path: Path) -> Path:
    path = tmp_path / "content.svg"
    path.write_text(TEMPLATE, encoding="utf-8")
    return path


def _page(tmp_path: Path, title: str = "A short title", body: dict | None = None) -> dict:
    return {"template": str(_template(tmp_path)), "chrome_group_id": "chrome",
            "texts": [{"id": "eyebrow", "text": "Plan", "x": 54, "baseline": 86, "size_px": 14, "weight": "bold", "edge": "top"},
                      {"id": "title", "text": title, "x": 54, "baseline": 118, "line_pitch_px": 33, "size_px": 28, "weight": "bold",
                       "max_w": 1172, "max_lines": 2, "edge": "top"},
                      {"id": "source", "text": "Source: example.", "x": 54, "baseline": 656, "baseline_of": "last", "size_px": 14,
                       "max_w": 1080, "max_lines": 2, "edge": "bottom"}],
            "body": body or {"x": 54, "y": 176, "w": 1172, "h": 440}}


def _timeline_request(tmp_path: Path, **page_kw) -> dict:
    return {"schema": "exp_svg.build_timeline.request.v2", "page": _page(tmp_path, **page_kw),
            "calendar": {"start": "2028-02-07", "horizon_weeks": 12, "prefix": "W"},
            "ruler": {"edge_labels": ["7 Feb 2028", "28 Apr 2028"]},
            "lanes": [{"id": "a", "name": "Build"}, {"id": "b", "name": "Test and train"}],
            "tasks": [{"id": "t1", "name": "Racking", "lane": "a", "weeks": [1, 4]}, {"id": "t2", "name": "Systems", "lane": "a", "weeks": [3, 8]},
                      {"id": "t3", "name": "Trial picks", "lane": "b", "weeks": [7, 10]}],
            "milestones": [{"id": "g1", "name": "G1: go or no-go", "week": 6, "kind": "gate"},
                           {"id": "m1", "name": "Opening day", "week": 12, "kind": "milestone", "focal": True}],
            "windows": [{"id": "peak", "name": "Peak trading: no changes on site", "weeks": [9, 10]},
                        {"id": "float", "name": "Float (unplanned)", "weeks": [13, 13], "style": "dashed"}],
            "dependencies": [{"id": "d1", "from": "t2", "to": "t3"}],
            "legend": [{"symbol": "gate", "text": "Decision point"}],
            "style": {"font_family": "Segoe UI", "label_px": 14}, "floors": {"label_px": 13.33, "body_px": 16}}


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)


def test_chrome_is_copied_verbatim_with_nested_groups(tmp_path):
    layout = page_compose.compose(_page(tmp_path), {"family": "Segoe UI"})
    assert layout["chrome"].startswith('<g id="chrome"') and layout["chrome"].endswith("</g>")
    assert layout["chrome"].count("<g") == 2 and "chrome-header-rule" in layout["chrome"]
    assert "sample-title" not in layout["chrome"]
    page = page_compose.assemble(layout, '<g id="body"/>')
    assert page.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"')
    assert '<g id="slide-body" data-pptx-bounds="0 0 1280 720"' in page and page.rstrip().endswith("</svg>")


def test_title_wraps_inside_the_width_the_export_gate_estimates(tmp_path):
    layout = page_compose.compose(_page(tmp_path, title=LONG_TITLE), {"family": "Segoe UI"})
    title = next(b for b in layout["blocks"] if b["id"] == "title")
    assert len(title["lines"]) == 2 and not layout["residuals"]
    assert " ".join(title["lines"]) == LONG_TITLE  # nothing cut
    for line in title["lines"]:
        estimate = text_measure.measure_text(line, size=28, family="Segoe UI", weight="bold", include_headroom=True)
        assert 54 + estimate <= 1280 * 1.05
    assert len(title["lines"][1].split()) > 1  # balanced: no single word left alone


def test_more_lines_than_allowed_is_reported_not_cut(tmp_path):
    layout = page_compose.compose(_page(tmp_path, title=LONG_TITLE + " and " + LONG_TITLE + " and " + LONG_TITLE), {"family": "Segoe UI"})
    assert any(r["kind"] == "page_text_overflow" and r["id"] == "title" for r in layout["residuals"])
    title = next(b for b in layout["blocks"] if b["id"] == "title")
    assert " ".join(title["lines"]).count("Seven") == 3


def test_body_between_texts(tmp_path):
    layout = page_compose.compose(_page(tmp_path, body={"x": 54, "w": 1172, "fit": "between_texts"}), {"family": "Segoe UI"})
    region = layout["region"]
    assert 125 < region["y"] < 145 and 630 < region["y"] + region["h"] < 645


def test_extra_svg_is_validated(tmp_path):
    page = _page(tmp_path)
    page["extra_svg"] = "<script>alert(1)</script>"
    with pytest.raises(page_compose.PageError):
        page_compose.compose(page, {"family": "Segoe UI"})


def test_timeline_page_is_the_whole_slide(tmp_path):
    request = tmp_path / "timeline.json"
    request.write_text(json.dumps(_timeline_request(tmp_path)), encoding="utf-8")
    out, page = tmp_path / "result.json", tmp_path / "slide.svg"
    done = _run(EXP / "timeline" / "build_timeline.py", "--in", str(request), "--out", str(out), "--page", str(page))
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] in ("ok", "partial"), done.stdout + done.stderr
    assert result["page"]["region"] == {"x": 54.0, "y": 176.0, "w": 1172.0, "h": 440.0}
    text = page.read_text(encoding="utf-8")
    assert '<g id="chrome"' in text and 'id="title"' in text and '<g id="timeline"' in text and "sample-title" not in text
    # compact header (the default with a page block): window names sit inside their own bands
    windows = {w["id"]: w for w in result["scene"]["windows"]}
    lanes_top = min(lane["y"] for lane in result["scene"]["lanes"])
    for w in windows.values():
        x0, y0, x1, y1 = w["label"]["rect"]
        assert y0 >= lanes_top - 0.5 and x0 >= w["x0"] - 0.5 and x1 <= w["x1"] + 0.5
    assert 'transform="rotate(-90' in text  # the one-week float is named reading upward
    assert 'markerUnits="userSpaceOnUse"' in text


def test_timeline_without_page_keeps_the_stacked_header(tmp_path):
    spec = _timeline_request(tmp_path)
    spec.pop("page")
    spec["bounds"] = {"x": 54, "y": 150, "w": 1172, "h": 470}
    request = tmp_path / "timeline.json"
    request.write_text(json.dumps(spec), encoding="utf-8")
    out = tmp_path / "result.json"
    _run(EXP / "timeline" / "build_timeline.py", "--in", str(request), "--out", str(out))
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] in ("ok", "partial") and "page" not in result
    lanes_top = min(lane["y"] for lane in result["scene"]["lanes"])
    assert all(w["label"]["rect"][3] <= lanes_top + 0.5 for w in result["scene"]["windows"])  # names above the ruler
    assert "rotate(" not in result["svg"]["fragment"] and "userSpaceOnUse" not in result["svg"]["fragment"]


def test_page_flag_needs_a_page_block(tmp_path):
    spec = _timeline_request(tmp_path)
    spec.pop("page")
    request = tmp_path / "timeline.json"
    request.write_text(json.dumps(spec), encoding="utf-8")
    out = tmp_path / "result.json"
    _run(EXP / "timeline" / "build_timeline.py", "--in", str(request), "--out", str(out), "--page", str(tmp_path / "slide.svg"))
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "error"
    assert not (tmp_path / "slide.svg").exists()


def _arch_request(tmp_path: Path) -> dict:
    names = {"north": "North shop", "south": "South shop", "east": "East shop"}
    return {"font": {"family": "Segoe UI"}, "page": {**_page(tmp_path), "body": {"x": 64, "y": 208, "w": 1152, "h": 440}},
            "style": {"edge_kinds": {"read": {"stroke": "#8A847B", "dash": "4 4", "head": True}, "sync": {"stroke": "#1F2937", "head": True}},
                      "zone_kinds": {"region": {"fill": "#F7F8FA", "stroke": "#8A96A3"}}},
            "buses": [{"id": "feed", "kind": "read"}],
            "root": {"layout": {"type": "rows", "rows": [["shops", "feed", "hub"], ["legend"]], "label_gaps": {"feed|hub": 130}}},
            "zones": [{"id": "shops", "kind": "group", "layout": {"type": "columns", "columns": [["north", "south", "east"]]}},
                      {"id": "hub", "kind": "region", "label": "Head office", "layout": {"type": "rows", "rows": [["pricing", "stock"], ["note"]]}}],
            "nodes": [{"id": k, "label": v, "zone": "shops"} for k, v in names.items()]
                     + [{"id": "pricing", "label": "Pricing service", "zone": "hub"}, {"id": "stock", "label": "Stock service", "zone": "hub"}],
            "edges": [{"id": "r1", "source": "north", "target": "feed"}, {"id": "r2", "source": "south", "target": "feed"},
                      {"id": "r3", "source": "east", "target": "feed"},
                      {"id": "r4", "source": "feed", "target": "pricing", "label": "hourly prices"},
                      {"id": "f1", "source": "pricing", "target": "stock", "kind": "sync", "label": "price list"}],
            "annotations": [{"id": "note", "text": "Prices are set centrally", "role": "label", "max_w": 200}],
            "legend": {"items": [{"kind": "read", "text": "Read"}, {"kind": "sync", "text": "Call"}]}}


def test_arch_compose_places_everything_without_coordinates(tmp_path):
    request = tmp_path / "scene.json"
    request.write_text(json.dumps(_arch_request(tmp_path)), encoding="utf-8")
    out, page = tmp_path / "composed.json", tmp_path / "slide.svg"
    done = _run(EXP / "arch" / "compose_page.py", "--in", str(request), "--out", str(out), "--page", str(page))
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] in ("ok", "partial"), done.stderr
    boxes = result["result"]["boxes"]
    assert "shops" not in boxes and "__page__" not in boxes  # layout-only zones are never drawn
    for box in boxes.values():
        assert box["x"] >= 64 - 0.5 and box["y"] >= 208 - 0.5 and box["x"] + box["w"] <= 1216.5 and box["y"] + box["h"] <= 648.5
    hub, note = boxes["hub"], boxes["note"]
    assert hub["x"] <= note["x"] and note["y"] + note["h"] <= hub["y"] + hub["h"]  # the note took its slot inside the zone
    bus = result["result"]["buses"]["feed"]
    assert len(bus["branches"]) == 4 and bus["y0"] < bus["y1"]
    text = page.read_text(encoding="utf-8")
    assert 'id="arch-bus-feed"' in text and 'id="arch-edge-r4"' in text and 'id="arch-zone-shops"' not in text
    assert text.count('data-pptx-bounds="0 0 1280 720"') == 2  # chrome and the one slide-body group
    assert "r4" in result["content_ids"] and "f1" in result["content_ids"]


def test_arch_capacity_failure_names_item_sizes(tmp_path):
    spec = _arch_request(tmp_path)
    spec["page"]["body"] = {"x": 64, "y": 208, "w": 300, "h": 120}
    request = tmp_path / "scene.json"
    request.write_text(json.dumps(spec), encoding="utf-8")
    out = tmp_path / "composed.json"
    done = _run(EXP / "arch" / "compose_page.py", "--in", str(request), "--out", str(out), "--page", str(tmp_path / "slide.svg"))
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "capacity_failure" and done.returncode == 4
    capacity = next(r for r in result["residual_constraints"] if r["kind"] == "capacity")
    assert capacity["zone"] == "root" and "shops" in capacity["items"] and "the body region holds 300 x 120" in capacity["message"]


def test_arch_engine_pin_refuses_compose_in_package_a(tmp_path, monkeypatch):
    request = tmp_path / "scene.json"
    request.write_text(json.dumps(_arch_request(tmp_path)), encoding="utf-8")
    out = tmp_path / "composed.json"
    env = {**__import__("os").environ, "PPT_MASTER_EXP_ENGINES": "placement:primitive;routing:orthogonal;compose:none"}
    done = subprocess.run([sys.executable, str(EXP / "arch" / "compose_page.py"), "--in", str(request), "--out", str(out),
                           "--page", str(tmp_path / "slide.svg")], capture_output=True, text=True, env=env)
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "error" and done.returncode == 2
