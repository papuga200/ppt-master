#!/usr/bin/env python3
"""
PPT Master - exp_svg inspect_svg (independent SVG checker)

Measures one SVG slide in headless Chromium after its fonts load and checks it against an
inspection request and an independent checklist. It is not the author's self-report: element
geometry comes from the browser (full CTM into slide pixels), and required content comes from
the checklist, not from the author's scene data. Every check is reported as passed, failed,
unverified (with the reason) or waived (by an explicit request entry), with element ids, units,
tolerances, the artifact sha256 and coverage counts. Unsupported geometry is listed, never
assumed to pass.

Usage:
    python3 inspect_svg.py --svg slide.svg [--in request.json] [--checklist checklist.json] --out report.json [--png render.png]
    python3 inspect_svg.py --summary report.json [--max-tokens 2000] [--summary-out summary.txt]
    python3 inspect_svg.py --summary report.json --only blocker|major|minor|unverified|failed [--offset N] [--limit N] [--family TF]

Request (all keys optional):
    {"canvas": [1280, 720], "type_floors_px": {"label": 13.333, "body": 16},
     "checks": ["type_floor", "text_fit", "off_canvas", "overlap", "connectors", "markers", "timeline", "semantic", "resources"],
     "checklist": "checklist.json" (path relative to the request) or an inline object,
     "roles": {"default": "label"|"body", "ids": {"<id>": "body"}, "id_patterns": {"^lbl-": "label"},
               "attribute_map": {...}, "exempt": {"<id>": "<reason>"}},
     "mapping": {"<checklist item id>": {"label": "<id>", "bar": "<id>", "marker": "<id>", "node": "<id>", "connector": "<id>"}},
     "timeline": {"scale": {"unit": "week"|"day", "origin": 1 | "2026-07-27", "origin_x": 300, "px_per_unit": 35.6,
                            "end_convention": "inclusive"|"exclusive", "milestone_anchor": "start"|"center"|"end", "tolerance_weeks": 0.5},
                  "lane_bands": {"<lane item id>": [y0, y1]}, "lane_band_mode": "label_top"|"label_center",
                  "marker_band": [y0, y1], "ticks": {"pattern": "W(\\d+)", "anchor": "center", "band": [y0, y1]}},
     "connectors": [{"id": "e1", "element": "<id>", "from": "<id or item>", "to": "<id or item>", "directed": true, "style": "solid"}],
     "containment": [{"child": "<id>", "parent": "<id>"}], "allowed_overlaps": [["<id>", "<id>", "<reason>"]],
     "text_containers": {"<text id>": "<shape id>"}, "connector_tolerance_px": 8, "label_gap_px": 10, "milestone_label_gap_px": 48}

Checklist:
    {"schema": "exp_svg.checklist/v1", "match_threshold": 0.8, "items": [
       {"id": "L1", "kind": "lane", "text": "...", "alt": ["..."], "role": "body"},
       {"id": "T1", "kind": "task", "lane": "L1", "text": "...", "start": 1, "end": 3, "role": "label"},
       {"id": "M1", "kind": "milestone"|"gate", "text": "...", "date": 10, "meaning": "...", "meaning_alt": []},
       {"id": "N1", "kind": "node", "text": "...", "inside": "Z1"}, {"id": "Z1", "kind": "zone", "element": "<id>"},
       {"id": "R1", "kind": "relationship"|"dependency", "from": "N1" | ["N1", "N2"], "to": "N3", "directed": true, "style": "dashed", "label": "..."},
       {"id": "K1", "kind": "legend", "text": "...", "symbol_color": "#B4162E", "symbol_style": "dashed", "applies_to": ["N6"]},
       {"id": "X1", "kind": "text", "text": "...", "region": [x, y, w, h], "near": "N1", "required": true}]}

Examples:
    python3 inspect_svg.py --svg page.svg --in request.json --out report.json --png page.png
    python3 inspect_svg.py --summary report.json --max-tokens 2000

Dependencies:
    playwright (Chromium) from the fork's venv
"""

from __future__ import annotations

import argparse
import collections
import sys
import time
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import common  # noqa: E402

common.ensure_scripts_path()

import checks as C  # noqa: E402
import summary as S  # noqa: E402

TOOL = "inspect_svg"
NOTES = [
    "A clean overlap check does not prove relationships: two shapes that do not collide may still be joined to the wrong nodes, and a label beside a bar may still name another bar. Relationships are only established by the connector and placement checks against the independent checklist.",
    "'passed' means the named measurement is within its tolerance; it is not an acceptance verdict for the slide.",
    "'unverified' means unknown - not a pass and not a failure.",
    "Coordinates are slide pixels of a 1280 x 720 canvas (13.333 x 7.5 in; 1 px = 0.75 pt).",
]


def load_request(path: Optional[Path]) -> tuple[dict, Optional[str], Optional[Path]]:
    if path is None:
        return {}, None, None
    data = common.read_json(path)
    return data, common.sha256_bytes(common.canonical_json(data)), path.parent


def load_checklist(request: dict, base: Optional[Path], override: Optional[Path]) -> tuple[Optional[dict], Optional[str], Optional[str]]:
    src = override or request.get("checklist")
    if src is None:
        return None, None, None
    if isinstance(src, dict):
        return src, common.sha256_bytes(common.canonical_json(src)), "inline"
    path = Path(src)
    if not path.is_absolute() and base is not None and override is None:
        path = base / path
    data = common.read_json(path)
    return data, common.sha256_file(path), str(path)


def coverage(records: list[dict], model: C.Model, checklist: Optional[dict], requested: tuple, presence: dict) -> dict:
    by = collections.OrderedDict()
    for check in requested:
        by[check] = {"passed": 0, "failed": 0, "unverified": 0, "waived": 0}
    for rec in records:
        by.setdefault(rec["check"], {"passed": 0, "failed": 0, "unverified": 0, "waived": 0})[rec["status"]] += 1
    geometry = model.geometry
    filters = sorted({f["on"] for coll in (geometry["texts"], geometry["shapes"]) for el in coll for f in el.get("filters", [])})
    masks = sorted({f["on"] for coll in (geometry["texts"], geometry["shapes"]) for el in coll for f in el.get("masks", [])})
    clips = sorted({c["on"] for coll in (geometry["texts"], geometry["shapes"]) for el in coll for c in el.get("clips", [])})
    out = {"by_check": by,
           "elements": {"texts": len(model.texts), "text_lines": len(model.lines), "hidden_texts": len(model.hidden), "shapes": len(model.shapes),
                        "closed_shapes": len(model.closed), "connectors": len(model.connectors), "groups_with_id": len(model.groups),
                        "unsupported_count": len(geometry.get("unsupported", [])), "unsupported": geometry.get("unsupported", [])[:50],
                        "under_filter": filters[:50], "under_mask": masks[:50], "clipped": clips[:50]}}
    if checklist:
        pres = collections.Counter(presence.values())
        out["checklist"] = {"items": len(checklist.get("items", [])), "with_text": len(presence), "present": pres["present"],
                            "partial": pres["partial"], "missing": pres["missing"],
                            "not_present": sorted(k for k, v in presence.items() if v != "present")}
    return out


def limits(model: C.Model) -> dict:
    g = model.geometry
    present = []
    for u in g.get("unsupported", []):
        present.append(f"{u['kind']} {u.get('ref', '')} not measured inside")
    for coll in (g["texts"], g["shapes"]):
        for el in coll:
            for f in el.get("filters", []):
                present.append(f"filter on {f['on']}: effect extent not measured")
            for f in el.get("masks", []):
                present.append(f"mask on {f['on']}: visibility not evaluated")
    for s in model.shapes:
        if s["tag"] == "image":
            present.append(f"image {s['ref']}: pixels not read")
    return {"never_measured": C.UNMEASURED, "present_on_this_slide": sorted(set(present))}


def _id_key(check_id: str) -> tuple[str, int]:
    prefix = check_id.rstrip("0123456789")
    return prefix, int(check_id[len(prefix):] or 0)


def inspect_file(svg: Path, request: dict, checklist: Optional[dict], *, browser=None, png: Optional[Path] = None,
                 request_hash: Optional[str] = None, checklist_hash: Optional[str] = None, checklist_src: Optional[str] = None) -> dict:
    started = time.perf_counter()
    svg = Path(svg).resolve()
    data = svg.read_bytes()
    art = {"path": str(svg), "sha256": common.sha256_bytes(data), "bytes": len(data)}
    canvas = tuple(request.get("canvas") or (common.CANVAS_W, common.CANVAS_H))
    try:
        defs = C.parse_defs(data)
    except C.ET.ParseError as exc:
        rep = common.envelope(TOOL, input_hash=art["sha256"], status="error", started=started, artifact=art, error=f"SVG does not parse: {exc}")
        return rep
    t_render = time.perf_counter()
    own = None
    try:
        if browser is None:
            from svg_geometry import Browser
            own = Browser(canvas).__enter__()
            geometry = own.measure(svg, png)
        else:
            geometry = browser.measure(svg, png)
    finally:
        if own is not None:
            own.__exit__(None, None, None)
    t_measured = time.perf_counter()
    if geometry.get("error"):
        return common.envelope(TOOL, input_hash=art["sha256"], status="error", started=started, artifact=art, error=geometry["error"])
    model = C.Model(geometry, defs)
    inspector = C.Inspector(model, request, checklist)
    records = inspector.run()
    order = {"failed": 0, "unverified": 1, "waived": 2, "passed": 3}
    findings = sorted((r for r in records if r["status"] == "failed"), key=lambda r: (C.SEVERITY_ORDER.get(r["severity"], 9), _id_key(r["check_id"])))
    status = "partial" if any(r["status"] == "unverified" for r in records) else "ok"
    report = common.envelope(TOOL, input_hash=art["sha256"], status=status, started=started)
    report.update({
        "artifact": art,
        "request_sha256": request_hash,
        "checklist": {"source": checklist_src, "sha256": checklist_hash, "items": len((checklist or {}).get("items", []))} if checklist else None,
        "canvas": {"width": canvas[0], "height": canvas[1], "viewBox": geometry["viewBox"], "slide_in": [13.333, 7.5], "px_per_pt": 4.0 / 3.0},
        "type_floors_px": inspector.floors,
        "browser": geometry.get("browser"),
        "fonts": geometry.get("fonts"),
        "timings_s": {"render_and_measure": round(t_measured - t_render, 3), "checks": round(time.perf_counter() - t_measured, 3)},
        "coverage": coverage(records, model, checklist, tuple(inspector.checks), inspector.item_presence),
        "limits": limits(model),
        "notes": NOTES,
        "result": {"failed": {s: sum(1 for r in findings if r["severity"] == s) for s in C.SEVERITY_ORDER},
                   "unverified": sum(1 for r in records if r["status"] == "unverified"),
                   "passed": sum(1 for r in records if r["status"] == "passed"),
                   "waived": sum(1 for r in records if r["status"] == "waived")},
        "findings": [r["check_id"] for r in findings],
        "checks": sorted(records, key=lambda r: (order[r["status"]], C.SEVERITY_ORDER.get(r["severity"], 9), _id_key(r["check_id"]))),
    })
    report["output_sha256"] = common.sha256_bytes(common.canonical_json(report["checks"]))
    report["elapsed_s"] = round(time.perf_counter() - started, 3)
    if png is not None and Path(png).is_file():
        report["render_png"] = common.file_fact(Path(png))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Independent SVG slide checker (browser geometry + checklist).",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--svg", type=Path, help="SVG to inspect")
    parser.add_argument("--in", dest="request", type=Path, help="inspection request JSON")
    parser.add_argument("--checklist", type=Path, help="independent checklist JSON (overrides request.checklist)")
    parser.add_argument("--out", type=Path, help="report JSON to write")
    parser.add_argument("--png", type=Path, help="also save the browser render used for measurement")
    parser.add_argument("--summary", type=Path, help="render a reviewer summary of an existing report")
    parser.add_argument("--max-tokens", type=int, default=2000, help="summary budget (estimated tokens, default 2000)")
    parser.add_argument("--summary-out", type=Path, help="write the summary here as well as stdout")
    parser.add_argument("--only", choices=["blocker", "major", "minor", "unverified", "failed"], help="targeted diagnostic view")
    parser.add_argument("--family", help="restrict the targeted view to one check family (e.g. type_floor or TF)")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=60)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from console_encoding import configure_utf8_stdio
    configure_utf8_stdio()
    if args.summary:
        if args.svg or args.out:
            parser.error("--summary renders an existing report; do not combine it with --svg/--out")
        report = common.read_json(args.summary)
        text = S.targeted(report, args.only, args.offset, args.limit, args.family) if args.only else S.render(report, args.max_tokens, str(args.summary))
        if args.summary_out:
            args.summary_out.parent.mkdir(parents=True, exist_ok=True)
            args.summary_out.write_text(text, encoding="utf-8")
        sys.stdout.write(text)
        print(f"(estimated tokens: {S.estimate_tokens(text)} of {args.max_tokens})", file=sys.stderr)
        return 0
    if not args.svg or not args.out:
        parser.error("--svg and --out are required (or use --summary)")
    if not args.svg.is_file():
        print(f"error: no such SVG: {args.svg}", file=sys.stderr)
        return 1
    request, rhash, base = load_request(args.request)
    checklist, chash, csrc = load_checklist(request, base, args.checklist)
    report = inspect_file(args.svg, request, checklist, png=args.png, request_hash=rhash, checklist_hash=chash, checklist_src=csrc)
    file_hash = common.write_json(args.out, report)
    res = report.get("result", {})
    print(f"{TOOL}: status {report['status']} | failed {res.get('failed')} | unverified {res.get('unverified')} | "
          f"report {args.out} (sha256 {file_hash[:16]}) | {report['elapsed_s']} s")
    if report["status"] == "error":
        print(report.get("error"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
