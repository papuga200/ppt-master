"""exp_svg inspection tools (SVG helpers experiment, 2026-09-30): inspect_svg, the reviewer summary and submit_check.

Pure tests (geometry helpers, text matching, the summary budget, the pass ledger) run anywhere. The browser tests
build the deterministic synthetic cases of exp_svg/inspect/synthetic.py in a temporary folder and run the checker in
headless Chromium; they skip themselves when Playwright or its Chromium is not available. No network, no model calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
INSPECT = SCRIPTS / "exp_svg" / "inspect"
for folder in (SCRIPTS, INSPECT):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import checks as C  # noqa: E402
import common  # noqa: E402
import geom as G  # noqa: E402
import summary as S  # noqa: E402


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001 - any failure means the browser tests cannot run here
        return False


BROWSER = _browser_available()
needs_browser = pytest.mark.skipif(not BROWSER, reason="Playwright Chromium not available")


# --------------------------------------------------------------------------------------------------------------------
# pure helpers
# --------------------------------------------------------------------------------------------------------------------
def test_geometry_helpers():
    assert G.dist_point_rect((0, 0), [3, 4, 10, 10]) == 5.0
    assert G.contains_rect([0, 0, 10, 10], [1, 1, 9, 9])
    assert G.overflow([0, 0, 10, 10], [-2, 0, 12, 10]) == {"left": 2, "top": 0, "right": 2, "bottom": 0}
    tri = [(0, 0), (10, 0), (0, 10)]
    assert G.point_in_polygon((2, 2), tri) and not G.point_in_polygon((8, 8), tri)
    # two triangles whose boxes overlap but whose outlines do not
    a, b = [(0, 0), (10, 0), (0, 10)], [(10, 10), (10, 2), (2, 10)]
    assert G.overlap_area([0, 0, 10, 10], a, [2, 2, 10, 10], b) <= 1.0
    assert G.angle_diff(350, 10) == 20


def test_match_score_exact_tokens_and_numbers():
    assert C.match_score("Gate 1 decides rollout", "W16 Gate 1 decides rollout")[0] == 1.0
    score, kind, missing = C.match_score("W21 Ask Meridian evaluation", "W21 Ask evaluation")
    assert kind == "tokens" and missing == ["meridian"] and score == pytest.approx(0.75)
    assert C.tokens("Data – platform’s build") == ["data", "platform's", "build"]


def test_marker_and_clip_defs_parse():
    svg = (b'<svg xmlns="http://www.w3.org/2000/svg"><defs><marker id="a" viewBox="0 0 10 10" markerWidth="6" orient="auto">'
           b'<path d="M0 0 L10 5 L0 10 Z"/></marker><clipPath id="c"><rect x="1" y="2" width="3" height="4"/></clipPath></defs></svg>')
    defs = C.parse_defs(svg)
    assert defs["markers"]["a"]["points"] == [(0.0, 0.0), (10.0, 5.0), (0.0, 10.0)]
    assert defs["clips"]["c"]["rects"] == [[1.0, 2.0, 4.0, 6.0]]


def _fake_report(blockers: int, majors: int = 3) -> dict:
    checks = [{"check_id": f"TF{i}", "check": "type_floor", "status": "failed", "severity": "blocker", "certainty": "measured",
               "targets": [f"t{i}"], "message": f"{10 + i % 3:.2f} px < label floor 13.333 px", "measured": 10.0 + i % 3, "units": "px"} for i in range(1, blockers + 1)]
    checks += [{"check_id": f"SEM{i}", "check": "semantic", "status": "failed", "severity": "blocker", "certainty": "measured",
                "targets": [f"T{i}"], "message": f"T{i} label is 400 px from its bar"} for i in range(1, 30)]
    checks += [{"check_id": f"FIT{i}", "check": "text_fit", "status": "failed", "severity": "major", "certainty": "measured",
                "targets": [f"x{i}"], "message": "text runs 4 px past its container"} for i in range(1, majors + 1)]
    checks.append({"check_id": "UNS1", "check": "unsupported", "status": "unverified", "severity": None, "certainty": "measured",
                   "targets": ["fo"], "message": "foreignObject", "reason": "foreignObject: content not measured"})
    return {"version": "t", "status": "partial", "artifact": {"sha256": "0" * 64}, "coverage": {"by_check": {}}, "limits": {}, "checks": checks}


def _accounted_blockers(text: str) -> tuple[set, int]:
    """Blocker ids a summary names (full lines or index lists) and the count it only states in a per-family tally."""
    import re
    ids = set(re.findall(r"\[([A-Z]+\d+)\]", text))
    index_re = r"(?<![A-Za-z])([A-Z]{2,3}): ((?:\d+,)*\d+)(?!\d)"
    for prefix, nums in re.findall(index_re, text):
        ids.update(f"{prefix}{n}" for n in nums.split(","))
    tally = 0
    m = re.search(r"OVERFLOW INDEX: (\d+) more blockers not shown \(([^)]*)\); ids too many", text)
    if m:
        tally = int(m.group(1))
        assert tally == sum(int(v) for v in re.findall(r": (\d+)", m.group(2)))
    return ids, tally


def test_summary_never_drops_a_blocker():
    report = _fake_report(300)
    blockers = {r["check_id"] for r in report["checks"] if r.get("severity") == "blocker"}
    for budget in (2000, 600, 250, 60):
        text = S.render(report, budget)
        assert "BLOCKERS (329)" in text
        ids, tally = _accounted_blockers(text)
        named = ids & blockers
        assert len(named) + tally >= len(blockers), f"budget {budget}: {len(named)} named + {tally} tallied < {len(blockers)}"
    # meaning findings come before measurement families and stay one per line
    text = S.render(report, 2000)
    assert text.index("[SEM1]") < text.index("type_floor x300")


def test_summary_targeted_view_and_budget():
    report = _fake_report(10)
    text = S.render(report, 2000)
    assert S.estimate_tokens(text) <= 2000
    view = S.targeted(report, "blocker", offset=0, limit=5)
    assert view.splitlines()[0].startswith("blocker findings 1..5 of 39")


def test_submit_check_refuses_beyond_limit_without_rendering(tmp_path):
    import submit_check
    svg = tmp_path / "page.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"/>', encoding="utf-8")
    ledger = tmp_path / "run" / "passes.json"
    ledger.parent.mkdir()
    ledger.write_text(json.dumps({"schema": "exp_svg.passes/v1", "passes": [
        {"pass_id": f"draft-{i}", "stage": "draft", "svg_sha256": f"{i}" * 64, "result": {"status": "ok"}} for i in (1, 2, 3)]}), encoding="utf-8")
    code, res, text = submit_check.submit(svg, "draft", None, tmp_path / "run", ledger, {"draft": 3, "repair": 2})
    assert code == submit_check.REFUSED_EXIT and res["refused"] and "REFUSED" in text
    assert not (tmp_path / "run" / "passes" / "draft-4").exists()
    passes = json.loads(ledger.read_text(encoding="utf-8"))["passes"]
    assert passes[-1]["refused"] is True


def test_submit_check_repeat_is_not_counted(tmp_path):
    import submit_check
    svg = tmp_path / "page.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"/>', encoding="utf-8")
    digest = common.sha256_file(svg)
    summary = tmp_path / "s.txt"
    summary.write_text("previous summary\n", encoding="utf-8")
    ledger = tmp_path / "passes.json"
    ledger.write_text(json.dumps({"passes": [{"pass_id": "draft-1", "stage": "draft", "svg_sha256": digest, "result": {"status": "ok"},
                                              "summary": str(summary), "png": None, "report": None}]}), encoding="utf-8")
    code, res, text = submit_check.submit(svg, "draft", None, tmp_path, ledger, {"draft": 3, "repair": 2})
    assert code == 0 and res["repeat_of"] == "draft-1" and text.startswith("REPEAT") and "previous summary" in text


def test_limits_come_from_environment(monkeypatch):
    import submit_check
    monkeypatch.setenv("EXP_SVG_PASS_LIMIT_DRAFT", "5")
    monkeypatch.delenv("EXP_SVG_PASS_LIMIT_REPAIR", raising=False)
    assert submit_check.limits({}) == {"draft": 5, "repair": 2}
    assert submit_check.limits({"limits": {"repair": 1}})["repair"] == 1


# --------------------------------------------------------------------------------------------------------------------
# browser: the synthetic cases with planted defects
# --------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def synthetic_reports(tmp_path_factory):
    if not BROWSER:
        pytest.skip("Playwright Chromium not available")
    import inspect_svg
    import synthetic
    from svg_geometry import Browser
    out = tmp_path_factory.mktemp("synthetic")
    reports = {}
    with Browser() as browser:
        for folder in synthetic.write_cases(out):
            request, rhash, base = inspect_svg.load_request(folder / "request.json")
            checklist, chash, csrc = inspect_svg.load_checklist(request, base, None)
            reports[folder.name] = (inspect_svg.inspect_file(folder / "slide.svg", request, checklist, browser=browser),
                                    json.loads((folder / "expected.json").read_text(encoding="utf-8")))
    return reports


def _hits(report: dict, check: str, target: str) -> list[dict]:
    return [r for r in report["checks"] if r["status"] == "failed" and r["check"] == check
            and any(t == target or t.split(":line")[0] == target for t in r["targets"])]


@needs_browser
def test_every_planted_defect_is_found(synthetic_reports):
    for name, (report, expected) in synthetic_reports.items():
        for defect in expected["expected_defects"]:
            assert any(_hits(report, defect["check"], t) for t in defect["targets"]), f"{name}: missed {defect}"


@needs_browser
def test_clean_controls_have_no_failures(synthetic_reports):
    for name in ("S00_clean_timeline", "S16_clean_architecture", "S17_clean_gate_rule"):
        report, _ = synthetic_reports[name]
        failed = [r for r in report["checks"] if r["status"] == "failed"]
        assert failed == [], f"{name}: {[(r['check_id'], r['message']) for r in failed]}"
        assert report["status"] == "ok" and report["artifact"]["sha256"]


@needs_browser
def test_planted_cases_raise_no_other_failures(synthetic_reports):
    for name, (report, expected) in synthetic_reports.items():
        for rec in (r for r in report["checks"] if r["status"] == "failed"):
            assert any(rec["check"] == d["check"] and any(t in rec["targets"] or t in [x.split(":line")[0] for x in rec["targets"]] for t in d["targets"])
                       for d in expected["expected_defects"]), f"{name}: unexpected {rec['check_id']} {rec['message']}"


@needs_browser
def test_transforms_are_resolved_into_slide_pixels(synthetic_reports):
    report, _ = synthetic_reports["S08_transforms"]
    small = [r for r in report["checks"] if r["check"] == "type_floor" and r["targets"] == ["note-small"]][0]
    assert small["status"] == "failed" and small["measured"] == pytest.approx(12.0, abs=0.05)
    bars = [r for r in report["checks"] if r["check"] == "timeline" and r["targets"][:1] and r["targets"][0].startswith("T")]
    assert bars and all(r["status"] == "passed" for r in bars)
    rotated = [r for r in report["checks"] if r["check"] == "type_floor" and r["targets"] == ["rot-label"]][0]
    assert rotated["status"] == "passed"


@needs_browser
def test_unsupported_geometry_is_unverified_not_passed(synthetic_reports):
    report, _ = synthetic_reports["S15_unsupported"]
    uns = [r for r in report["checks"] if r["check"] == "unsupported"]
    assert {r["status"] for r in uns} == {"unverified"}
    assert any("foreignObject" in r["message"] for r in uns) and any("filter" in r["message"] for r in uns)
    assert report["status"] == "partial"


@needs_browser
def test_report_carries_coverage_and_notes(synthetic_reports):
    report, _ = synthetic_reports["S05_wrong_target"]
    assert report["tool"] == "inspect_svg" and report["status"] in ("ok", "partial") and report["output_sha256"]
    assert set(report["coverage"]["by_check"]) >= set(C.ALL_CHECKS)
    assert any("does not prove relationships" in n for n in report["notes"])
    rel = [r for r in report["checks"] if r["check"] == "connectors" and r["targets"][:1] == ["E2"]][0]
    assert rel["status"] == "failed" and rel["severity"] == "blocker"
    text = S.render(report, 2000)
    assert "[CON" in text and S.estimate_tokens(text) <= 2000


def _inspect_snippet(tmp_path, body: str, request: dict, checklist: dict) -> dict:
    import inspect_svg
    svg = tmp_path / "s.svg"
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" font-family="Segoe UI, Arial">{body}</svg>', encoding="utf-8")
    return inspect_svg.inspect_file(svg, request, checklist)


@needs_browser
def test_must_include_is_all_of_and_own_wording_wins(tmp_path):
    body = ('<text id="a" x="100" y="100" font-size="16">Discovery complete</text>'
            '<text id="b" x="100" y="200" font-size="16">Mobilisation and discovery</text>')
    item = {"id": "L1", "kind": "text", "text": "Mobilisation and discovery", "must_include": ["mobilisation", "discovery"]}
    rep = _inspect_snippet(tmp_path, body, {"checks": ["semantic"]}, {"items": [item]})
    ok = [r for r in rep["checks"] if r["check"] == "semantic" and r["status"] == "passed"][0]
    assert "b" in ok["targets"] and "a" not in ok["targets"]
    item2 = {"id": "L2", "kind": "text", "text": "Mobilisation and planning", "must_include": ["mobilisation", "planning"]}
    rep = _inspect_snippet(tmp_path, body, {"checks": ["semantic"]}, {"items": [item2]})
    assert [r["status"] for r in rep["checks"] if r["check"] == "semantic"] == ["failed"]  # one keyword alone is not enough


@needs_browser
def test_roles_checklist_before_author_markup_and_named_floors(tmp_path):
    body = ('<text id="lane" data-role="lane-label" x="60" y="100" font-size="10.667">Data ingestion and platform</text>'
            '<text id="src" data-role="source" x="60" y="700" font-size="12">Source: assumed plan</text>'
            '<text id="title" data-role="lane-label" x="60" y="50" font-size="12">Seven workstreams reach go-live</text>')
    request = {"checks": ["type_floor", "semantic"], "type_floors_px": {"label": 10.667, "body": 16, "furniture": 13.333}, "roles": {"default": "label"}}
    checklist = {"items": [{"id": "L", "kind": "lane", "text": "Data ingestion and platform", "role": "label"},
                           {"id": "T", "kind": "text", "text": "Seven workstreams reach go-live", "role": "body"}]}
    rep = _inspect_snippet(tmp_path, body, request, checklist)
    tf = {r["targets"][0]: r for r in rep["checks"] if r["check"] == "type_floor"}
    assert tf["lane"]["status"] == "passed" and tf["lane"]["role"] == "label"
    assert tf["src"]["status"] == "failed" and tf["src"]["role"] == "furniture"  # source text keeps the 13.333 px floor
    assert tf["title"]["status"] == "failed" and tf["title"]["role"] == "body"  # the checklist says body whatever the markup says


def test_label_pairing_prefers_the_same_row():
    label = [916.0, 530.0, 1033.0, 545.0]
    beside = [899.7, 533.0, 910.7, 543.0]      # the steering triangle the label sits beside
    rule_above = [1012.0, 160.0, 1013.5, 529.0]  # another decision's rule ending just above the label
    assert C._col_key(label, beside) < C._col_key(label, rule_above)
    row_bar, stacked_bar = [905.0, 431.0, 1155.0, 441.0], [834.0, 416.0, 905.0, 426.0]
    live_pilot = [858.0, 428.0, 900.0, 442.0]
    assert C._row_key(live_pilot, row_bar) < C._row_key(live_pilot, stacked_bar)
