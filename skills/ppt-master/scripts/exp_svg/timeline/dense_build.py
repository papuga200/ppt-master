#!/usr/bin/env python3
"""
PPT Master - Experimental build_timeline, dense engine path (request v1 and v2)

Validates a request, normalises it to day offsets, runs dense_layout.py (at the requested label size, then, only if
that does not fit, at the label floor - never below it), classifies the outcome and returns the SVG group, scene and
unsatisfied constraints. Called by build_timeline.py; see README.md beside this file for the schema.

Dependencies:
    Standard library, timeline_fonts.py, dense_layout.py; timeline_layout.py only for its group digest (lint contract)
"""

from __future__ import annotations

import re
from datetime import date
from xml.sax.saxutils import escape

import timeline_layout
from dense_layout import ENGINE, ENGINE_VERSION, DenseLayout
from timeline_fonts import FontMetrics

REQUEST_SCHEMAS = ("exp_svg.build_timeline.request.v1", "exp_svg.build_timeline.request.v2")
DEFAULT_FLOORS = {"label_px": 13.33, "body_px": 16.0}
# user decision 2026-09-30 (experiment D015): timeline-chart labels may go to 8 pt = 10.667 px; a request asks for it explicitly
ABSOLUTE_TIMELINE_LABEL_FLOOR_PX = 10.667
DEFAULT_BOUNDS = {"x": 60, "y": 150, "w": 1160, "h": 480}
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_WEEK_AT = {"start": 0.0, "middle": 3.5, "end": 7.0}


def _date(value, where: str, problems: list) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        problems.append(f"{where}: {value!r} is not an ISO date (YYYY-MM-DD)")
        return None


def _span(obj: dict, start: date | None, where: str, problems: list) -> tuple | None:
    """(d0, d1) day offsets, end exclusive: from `weeks: [a, b]` (start of week a to end of week b) or `start`/`end` dates
    (inclusive end date)."""
    if "weeks" in obj:
        wk = obj["weeks"]
        if not (isinstance(wk, list) and len(wk) == 2 and all(isinstance(v, int) and v >= 1 for v in wk) and wk[1] >= wk[0]):
            problems.append(f"{where}: weeks must be [a, b] with 1 <= a <= b")
            return None
        return 7.0 * (wk[0] - 1), 7.0 * wk[1]
    s, e = _date(obj.get("start"), f"{where}.start", problems), _date(obj.get("end"), f"{where}.end", problems)
    if s is None or e is None or start is None:
        return None
    if e < s:
        problems.append(f"{where}: end {e} is before start {s}")
        return None
    return float((s - start).days), float((e - start).days + 1)


def _point(obj: dict, start: date | None, anchor: str, where: str, problems: list) -> float | None:
    if "week" in obj:
        n = obj["week"]
        if not (isinstance(n, int) and n >= 1):
            problems.append(f"{where}: week must be an integer >= 1")
            return None
        return 7.0 * (n - 1) + _WEEK_AT.get(obj.get("at", "end"), 7.0)
    d = _date(obj.get("date"), f"{where}.date", problems)
    if d is None or start is None:
        return None
    return float((d - start).days) + (1.0 if anchor == "end_of_day" else 0.0)


def normalise(request: dict) -> tuple[dict | None, list, list]:
    """The dense spec, problems (errors) and notes (e.g. a label size raised to the floor)."""
    problems, notes = [], []
    if request.get("schema", REQUEST_SCHEMAS[0]) not in REQUEST_SCHEMAS:
        problems.append(f"schema is {request.get('schema')!r}; this tool reads {REQUEST_SCHEMAS}")
    cal = request.get("calendar") or {}
    start = _date(cal.get("start"), "calendar.start", problems)
    anchor = cal.get("milestone_anchor", "end_of_day")
    if anchor not in ("end_of_day", "start_of_day"):
        problems.append("calendar.milestone_anchor must be 'end_of_day' or 'start_of_day'")
    if "horizon_weeks" in cal:
        horizon = 7.0 * int(cal["horizon_weeks"])
    else:
        end = _date(cal.get("end"), "calendar.end", problems)
        horizon = float((end - start).days + 1) if (end and start) else 0.0
    seen = set()

    def check_id(value, where):
        if not isinstance(value, str) or not _ID_RE.match(value):
            problems.append(f"{where}: id {value!r} must match {_ID_RE.pattern}")
        elif value in seen:
            problems.append(f"{where}: id {value!r} is used twice")
        else:
            seen.add(value)

    lanes = request.get("lanes") or []
    if not lanes:
        problems.append("lanes: at least one lane is required")
    lane_ids = set()
    for i, lane in enumerate(lanes):
        check_id(lane.get("id"), f"lanes[{i}]")
        lane_ids.add(lane.get("id"))
        if not str(lane.get("name", "")).strip():
            problems.append(f"lanes[{i}]: name is required")
    tasks, markers, windows, extent = [], [], [], horizon
    for i, t in enumerate(request.get("tasks") or []):
        where = f"tasks[{i}] ({t.get('id')})"
        check_id(t.get("id"), where)
        if not str(t.get("name", "")).strip():
            problems.append(f"{where}: name is required")
        if t.get("lane") not in lane_ids:
            problems.append(f"{where}: lane {t.get('lane')!r} is not a lane")
        span = _span(t, start, where, problems)
        if span:
            if span[0] < 0 or (span[1] > horizon and not t.get("beyond_horizon")):
                problems.append(f"{where}: lies outside the calendar horizon")
            extent = max(extent, span[1])
            style = {k: t[k] for k in ("fill", "text") if k in t}
            tasks.append({"id": t["id"], "name": t["name"], "lane": t["lane"], "d0": span[0], "d1": span[1], "style": style})
    for i, m in enumerate(request.get("milestones") or []):
        where = f"milestones[{i}] ({m.get('id')})"
        check_id(m.get("id"), where)
        if not str(m.get("name", "")).strip():
            problems.append(f"{where}: name is required")
        kind = m.get("kind", "milestone")
        if kind not in ("milestone", "gate"):
            problems.append(f"{where}: kind must be 'milestone' or 'gate'")
        if m.get("lane") is not None and m.get("lane") not in lane_ids:
            problems.append(f"{where}: lane {m.get('lane')!r} is not a lane")
        placement = m.get("placement", "strip")
        if placement not in ("strip", "lane"):
            problems.append(f"{where}: placement must be 'strip' or 'lane'")
        if placement == "lane" and not m.get("lane"):
            problems.append(f"{where}: placement 'lane' needs a lane")
        d = _point(m, start, anchor, where, problems)
        if d is not None:
            if d < 0 or d > max(horizon, extent) + 0.01:
                problems.append(f"{where}: lies outside the calendar horizon")
            markers.append({"id": m["id"], "name": m["name"], "d": d, "lane": m.get("lane"),
                            "kind": "gate" if kind == "gate" else ("event" if placement == "lane" else "milestone"),
                            "style": {"focal": bool(m.get("focal") or m.get("emphasis")), "payment": bool(m.get("payment"))}})
    for i, w in enumerate(request.get("windows") or []):
        where = f"windows[{i}] ({w.get('id')})"
        check_id(w.get("id"), where)
        if not str(w.get("name", "")).strip():
            problems.append(f"{where}: name is required")
        span = _span(w, start, where, problems)
        if span:
            extent = max(extent, span[1])
            windows.append({"id": w["id"], "name": w["name"], "d0": span[0], "d1": span[1],
                            "style": {"dashed": w.get("style") == "dashed"}})
    item_ids = {t["id"] for t in tasks} | {m["id"] for m in markers}
    deps = []
    for i, dep in enumerate(request.get("dependencies") or []):
        where = f"dependencies[{i}]"
        if dep.get("id") is not None:
            check_id(dep.get("id"), where)
        for end_name in ("from", "to"):
            if dep.get(end_name) not in item_ids:
                problems.append(f"{where}: {end_name} {dep.get(end_name)!r} is not a task or milestone id")
        if dep.get("from") == dep.get("to"):
            problems.append(f"{where}: an item cannot depend on itself")
        deps.append({"id": dep.get("id") or f"dep{i + 1}", "from": dep.get("from"), "to": dep.get("to")})
    bounds = {**DEFAULT_BOUNDS, **(request.get("bounds") or {})}
    if bounds["x"] < 0 or bounds["y"] < 0 or bounds["x"] + bounds["w"] > 1280 or bounds["y"] + bounds["h"] > 720:
        problems.append("bounds must lie inside the 1280 x 720 canvas")
    style = request.get("style") or {}
    floors = {**DEFAULT_FLOORS, **(request.get("floors") or {})}
    floor = float(floors["label_px"])
    if floor < ABSOLUTE_TIMELINE_LABEL_FLOOR_PX - 1e-9:
        problems.append(f"floors.label_px {floor:g} is below the confirmed timeline-chart label floor {ABSOLUTE_TIMELINE_LABEL_FLOOR_PX:g} px")
    font = {"family": style.get("font_family", "Segoe UI")}
    for key in ("label_px", "lane_px", "tick_px"):
        asked = float(style.get(key, 14))
        if asked < floor:
            notes.append({"kind": "style_raised", "detail": f"style.{key} {asked:g} px raised to the floor {floor:g} px"})
        font[key] = max(asked, floor)
    if problems:
        return None, problems, notes
    ruler = request.get("ruler") or {}
    spec = {"font": font, "floor_px": floor, "region": bounds, "days": horizon, "extent_days": extent,
            "prefix": cal.get("prefix", "W"), "lanes": [{"id": l["id"], "name": l["name"]} for l in lanes],
            "tasks": tasks, "markers": markers, "windows": windows, "dependencies": deps,
            "edge_labels": ruler.get("edge_labels") or [], "legend": request.get("legend") or [],
            "colors": style.get("colors") or {}, "bar_pad_x": float(style.get("bar_pad_x", 8)),
            "bar_pad_y": float(style.get("bar_pad_y", 4)), "name_max_lines": int(style.get("name_max_lines", 3)),
            "bar_mode": style.get("bar_mode", "labelled"), "bar_h_thin": float(style.get("bar_h_thin", 10)),
            "header": style.get("header", "stacked"), "rev2": bool(style.get("rev2"))}
    if style.get("lane_label_w"):
        spec["lane_label_w"] = float(style["lane_label_w"])
    return spec, [], notes


def _digest_group(children: list, defs: str, group_id: str, font_family: str, region: dict, spec_ref: str, spec_sha: str) -> str:
    inner = "\n" + "\n".join([f"<defs>{defs}</defs>", *children]) + "\n"
    family = escape(font_family, {'"': "&quot;"})
    bounds = " ".join(f"{float(region[k]):g}" for k in ("x", "y", "w", "h"))
    return (f'<g id="{escape(group_id)}" data-layout="{timeline_layout.LAYOUT_ATTR}" data-builder="exp_svg.build_timeline" '
            f'data-engine="{ENGINE} {ENGINE_VERSION}" data-spec="{escape(spec_ref)}" data-spec-sha="{spec_sha}" '
            f'data-output-sha="{timeline_layout.group_digest(inner)}" data-pptx-bounds="{bounds}" font-family="{family}">{inner}</g>')


def build_dense(request: dict, group_id: str = "timeline") -> dict:
    spec, problems, notes = normalise(request)
    if problems:
        return {"status": "error", "errors": problems}
    fm = FontMetrics(spec["font"]["family"])
    if fm.method == "estimator":
        notes.append({"kind": "measurement", "detail": f"no font file for {spec['font']['family']!r}: widths estimated; fit unverified"})
    asked = spec["font"]["label_px"]
    # labels shrink only as far as needed: the asked size, then each standard step down to (never below) the floor
    ladder = (13.33, 12.0, 11.333, 10.667)
    sizes = [asked] + [v for v in ladder if spec["floor_px"] - 1e-9 <= v < asked - 1e-9]
    if spec["floor_px"] < asked - 1e-9 and all(abs(v - spec["floor_px"]) > 1e-6 for v in sizes):
        sizes.append(spec["floor_px"])
    engine, best = None, None
    for size in sizes:
        trial = dict(spec, font=dict(spec["font"], label_px=size, lane_px=max(spec["floor_px"], min(spec["font"]["lane_px"], size)),
                                     tick_px=max(spec["floor_px"], min(spec["font"]["tick_px"], size))))
        eng = DenseLayout(trial, fm)
        geo = eng.solve()
        if geo["fits"]:
            engine = eng
            break
        if best is None or geo["attempt"]["total"] < best.geo["attempt"]["total"]:
            best = eng
    engine = engine or best
    placed = engine.placed()
    if placed["font"]["label_px"] < asked:
        notes.append({"kind": "dense_font", "detail": f"labels set at the floor {placed['font']['label_px']:g} px (asked {asked:g} px) to fit"})
    checks = engine.checks()
    unsatisfied = [dict(n) for n in notes if n["kind"] not in ("style_raised", "dense_font")]
    capacity = {"region": spec["region"], "needs_h": placed["needs_h"], "available_h": spec["region"]["h"],
                "fits_height": placed["fits"], "breakdown": placed["breakdown"], "density": placed["density"], "binding": []}
    if not placed["fits"]:
        b = placed["breakdown"]
        parts = {"lanes (rows)": b["lanes_total"], "header names": b["header_names"], "milestone strip": b["milestone_strip"],
                 "ruler": b["ruler"], "legend": b["legend"]}
        capacity["binding"].append({
            "constraint": "height", "needs_px": placed["needs_h"], "available_px": spec["region"]["h"],
            "over_by_px": round(placed["needs_h"] - spec["region"]["h"], 1),
            "detail": (f"at the densest spacing and {placed['font']['label_px']:g} px labels the chart needs {placed['needs_h']:.0f} px: "
                       + ", ".join(f"{k} {v:.0f}" for k, v in parts.items() if v)
                       + f"; {b['rows']} rows of {placed['density']['bar_h']:g} px bars (vertical bar padding {placed['density']['bar_pad_y']:g} px)")})
    for c in checks:
        if c == "does not fit the region":
            continue
        if "leaves the region" in c:
            capacity["binding"].append({"constraint": "bounds", "detail": c})
        else:
            unsatisfied.append({"kind": "collision", "detail": c})
    status = "capacity_failure" if capacity["binding"] else ("partial" if unsatisfied else "ok")
    defs, children = engine.svg_children(group_id)

    def group_for(spec_ref: str = "", spec_sha: str = "") -> str:
        return _digest_group(children, defs, group_id, spec["font"]["family"], spec["region"], spec_ref, spec_sha)

    names = {t["id"]: t["name"] for t in spec["tasks"]} | {m["id"]: m["name"] for m in spec["markers"]}
    scene = {"engine": f"{ENGINE} {ENGINE_VERSION}", "canvas": {"w": 1280, "h": 720, "px_per_pt": 4 / 3},
             **{k: placed[k] for k in ("region", "font", "scale", "density", "breakdown", "lanes", "windows", "dependencies")},
             "scale_convention": "day offsets from calendar.start; task [d0, d1) (weeks a-b: start of a to end of b; dates: inclusive end); "
                                 "points at the end of their day/week unless `at` says otherwise; calendar days, no exclusions",
             "tasks": [dict(t, name=names[t["id"]]) for t in placed["tasks"]],
             "milestones": [dict(m, name=names[m["id"]]) for m in placed["markers"]],
             "engine_checks": checks}
    return {"status": status, "group": group_for(), "group_for": group_for, "scene": scene,
            "unsatisfied_constraints": unsatisfied, "capacity": capacity,
            "notes": [n for n in notes if n["kind"] in ("style_raised", "dense_font")], "measurement": fm.describe(),
            "engine": ENGINE, "engine_version": ENGINE_VERSION}
