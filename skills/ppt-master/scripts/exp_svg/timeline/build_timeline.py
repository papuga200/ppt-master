#!/usr/bin/env python3
"""
PPT Master - Experimental build_timeline (SVG helpers experiment, 2026-09-30)

JSON in, JSON out: lay out a one-slide Gantt/timeline from dated tasks, milestones, lanes and
dependencies, and write it as an SVG group with stable content IDs, scene data and a receipt.

v0.2.0 (round 2): the default engine is dense_layout.py in this folder (dense_build.py normalises request v1/v2):
labels at the 13.33 px floor when needed, wrapped and stacked gate/milestone names with no line through any name, lane
events, windows, beyond-horizon spans, dependencies between any items, density search, capacity_failure with the
binding constraint. `--engine timeline_layout` keeps the round-1 behaviour described below.

Round-1 engine: the fork's timeline_layout.py (unchanged), driven through this adapter, which
  - converts calendar dates to exact fractional week positions (day precision, stated endpoint
    convention) instead of whole units;
  - measures labels with the real font file (timeline_fonts.py) instead of the family-blind
    estimator; the engine's own placement, packing, collision checks and SVG drawing are reused;
  - classifies the outcome: ok | partial | capacity_failure | error. Nothing is shortened,
    merged or dropped to reach ok; a layout that does not fit is still written (best draft)
    and reported as capacity_failure with its binding constraints;
  - stamps every element with data-content-id / data-role so a checker or a creator can find
    each task, milestone, gate and dependency by the request's own IDs.

Request schema, conventions and an example: README.md beside this file.

Usage:
    python3 scripts/exp_svg/timeline/build_timeline.py --in request.json --out result.json
        [--svg preview.svg] [--into <project>/svg_output/<page>.svg] [--group-id timeline]

Examples:
    python3 scripts/exp_svg/timeline/build_timeline.py --in plan.json --out plan.result.json --svg plan.svg

Exit codes: 0 ok, 3 partial, 4 capacity_failure, 2 error (the result JSON is written in every case).

Dependencies:
    Standard library, PPT Master sibling modules (timeline_layout.py, text_measure.py); Pillow
    for real font metrics (optional: falls back to the estimator and says so in the receipt)
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

_HERE = Path(__file__).resolve().parent
_SCRIPTS_DIR = _HERE.parents[1]
for _path in (_SCRIPTS_DIR, _HERE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import timeline_layout  # noqa: E402
from timeline_fonts import FontMetrics  # noqa: E402

TOOL = "exp_svg.build_timeline"
TOOL_VERSION = "0.3.0"
REQUEST_SCHEMA = "exp_svg.build_timeline.request.v1"
RESULT_SCHEMA = "exp_svg.build_timeline.result.v1"
ENGINE = "timeline_layout"  # round-1 engine; selectable with --engine timeline_layout
ENGINES = ("dense", "timeline_layout")


def _pinned_engines() -> set:
    """`PPT_MASTER_EXP_ENGINES="timeline:dense;..."` limits which engine a package's creators may use."""
    import os
    out: set = set()
    for part in (os.environ.get("PPT_MASTER_EXP_ENGINES") or "").split(";"):
        if part.strip().startswith("timeline:"):
            out.update(x.strip() for x in part.split(":", 1)[1].split(",") if x.strip())
    return out
DEFAULT_ENGINE = "dense"
ENGINE_FLOOR_PX = timeline_layout.FLOOR_PX  # the engine refuses smaller type (14 px = 10.5 pt)
DEFAULT_FLOORS = {"label_px": 13.33, "body_px": 16.0}
DEFAULT_BOUNDS = {"x": 60, "y": 150, "w": 1160, "h": 480}
EXIT_CODES = {"ok": 0, "partial": 3, "capacity_failure": 4, "error": 2}
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_TASK_KINDS = ("task", "window", "deliverable")
_MILESTONE_KINDS = ("milestone", "gate")


class RequestError(ValueError):
    pass


# ------------------------------------------------------------------------------------------ helpers

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _file_sha(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError:
        return ""


def _parse_date(value, where: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise RequestError(f"{where}: {value!r} is not an ISO date (YYYY-MM-DD)") from exc


# ------------------------------------------------------------------------------------ validation

def validate_request(request: dict) -> list[str]:
    """Every problem with the request, each named. An empty list means it can be laid out."""
    problems: list[str] = []
    if not isinstance(request, dict):
        return ["the request is not a JSON object"]
    schema = request.get("schema", REQUEST_SCHEMA)
    if schema != REQUEST_SCHEMA:
        problems.append(f"schema is {schema!r}; this tool reads {REQUEST_SCHEMA!r}")
    cal = request.get("calendar") or {}
    try:
        start = _parse_date(cal.get("start"), "calendar.start")
        end = _parse_date(cal.get("end"), "calendar.end")
        if end < start:
            problems.append("calendar.end is before calendar.start")
    except RequestError as exc:
        problems.append(str(exc))
        start = end = None
    if cal.get("unit", "week") != "week":
        problems.append("calendar.unit: only 'week' is supported (month rulers are not linear in days; unverified)")
    if cal.get("milestone_anchor", "end_of_day") not in ("end_of_day", "start_of_day"):
        problems.append("calendar.milestone_anchor must be 'end_of_day' or 'start_of_day'")
    seen: set[str] = set()

    def check_id(value, where: str) -> None:
        if not isinstance(value, str) or not _ID_RE.match(value):
            problems.append(f"{where}: id {value!r} must match {_ID_RE.pattern}")
        elif value in seen:
            problems.append(f"{where}: id {value!r} is used twice (ids are unique across lanes, tasks, milestones, dependencies)")
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
    task_ids = set()
    for i, task in enumerate(request.get("tasks") or []):
        where = f"tasks[{i}] ({task.get('id')})"
        check_id(task.get("id"), where)
        task_ids.add(task.get("id"))
        if not str(task.get("name", "")).strip():
            problems.append(f"{where}: name is required")
        if task.get("lane") not in lane_ids:
            problems.append(f"{where}: lane {task.get('lane')!r} is not a lane")
        if task.get("kind", "task") not in _TASK_KINDS:
            problems.append(f"{where}: kind must be one of {_TASK_KINDS}")
        try:
            s, e = _parse_date(task.get("start"), f"{where}.start"), _parse_date(task.get("end"), f"{where}.end")
            if e < s:
                problems.append(f"{where}: end {e} is before start {s}")
            if start and end and (s < start or e > end):
                problems.append(f"{where}: {s}..{e} lies outside the calendar {start}..{end}")
        except RequestError as exc:
            problems.append(str(exc))
    for i, ms in enumerate(request.get("milestones") or []):
        where = f"milestones[{i}] ({ms.get('id')})"
        check_id(ms.get("id"), where)
        if not str(ms.get("name", "")).strip():
            problems.append(f"{where}: name is required")
        if ms.get("lane") is not None and ms.get("lane") not in lane_ids:
            problems.append(f"{where}: lane {ms.get('lane')!r} is not a lane")
        if ms.get("kind", "milestone") not in _MILESTONE_KINDS:
            problems.append(f"{where}: kind must be one of {_MILESTONE_KINDS}")
        try:
            d = _parse_date(ms.get("date"), f"{where}.date")
            if start and end and not (start <= d <= end):
                problems.append(f"{where}: {d} lies outside the calendar {start}..{end}")
        except RequestError as exc:
            problems.append(str(exc))
    for i, dep in enumerate(request.get("dependencies") or []):
        where = f"dependencies[{i}]"
        if dep.get("id") is not None:
            check_id(dep.get("id"), where)
        for end_name in ("from", "to"):
            if dep.get(end_name) not in task_ids:
                problems.append(f"{where}: {end_name} {dep.get(end_name)!r} is not a task id (v1 links task to task)")
        if dep.get("from") == dep.get("to"):
            problems.append(f"{where}: a task cannot depend on itself")
    bounds = request.get("bounds") or DEFAULT_BOUNDS
    for key in ("x", "y", "w", "h"):
        if not isinstance(bounds.get(key), (int, float)):
            problems.append(f"bounds.{key} must be a number")
    if all(isinstance(bounds.get(k), (int, float)) for k in ("x", "y", "w", "h")):
        if bounds["x"] < 0 or bounds["y"] < 0 or bounds["x"] + bounds["w"] > 1280 or bounds["y"] + bounds["h"] > 720:
            problems.append("bounds must lie inside the 1280 x 720 canvas")
    return problems


# --------------------------------------------------------------------------- dates -> scale units

class BarEnd(float):
    """The `end` of a bar as timeline_layout reads it: the bar is drawn to x(end + 1). With fractional
    (day-precise) units a bar shorter than one week has end + 1 - start < 1, i.e. end < start, which the
    engine rejects as 'outside the horizon'. This value compares as its drawn right edge: it is 'less
    than' the start only when the bar would have no length. Arithmetic is plain float arithmetic."""

    def __lt__(self, other):
        return float(self) + 1 <= float(other)

    def __gt__(self, other):
        return float(self) > float(other)


class Calendar:
    """Calendar days onto week units. Unit 1 starts at calendar.start 00:00; a position p (in days
    from the start, fractional) is unit 1 + p / 7. Tasks cover [start 00:00, end + 1 day 00:00)
    (inclusive end dates); a milestone sits at the end of its day (default) or its start."""

    def __init__(self, cal: dict) -> None:
        self.start = date.fromisoformat(cal["start"])
        self.end = date.fromisoformat(cal["end"])
        self.anchor = cal.get("milestone_anchor", "end_of_day")
        self.days = (self.end - self.start).days + 1
        self.weeks = math.ceil(self.days / 7)

    def unit(self, day: date, end_of_day: bool = False) -> float:
        return 1 + ((day - self.start).days + (1 if end_of_day else 0)) / 7

    def bar_units(self, start: date, end: date) -> tuple[float, float]:
        """timeline_layout draws bar {start: s, end: e} from x(s) to x(e + 1)."""
        return self.unit(start), BarEnd(self.unit(end, end_of_day=True) - 1)

    def marker_unit(self, day: date) -> float:
        return self.unit(day, end_of_day=self.anchor == "end_of_day")


# ------------------------------------------------------------------------------- request -> spec

def resolve_style(request: dict) -> tuple[dict, list[dict]]:
    """Font sizes at or above the floors: never shrunk, raised to the engine's floor when asked lower."""
    style = request.get("style") or {}
    floors = {**DEFAULT_FLOORS, **(request.get("floors") or {})}
    notes = []
    font = {"family": style.get("font_family", "Segoe UI")}
    for key, default in (("label_px", 14.0), ("lane_px", 14.0), ("tick_px", 14.0)):
        asked = float(style.get(key, default))
        size = max(asked, floors["label_px"], ENGINE_FLOOR_PX)
        if size != asked:
            notes.append({"kind": "style_raised", "detail": f"style.{key} {asked:g} px raised to {size:g} px "
                          f"(label floor {floors['label_px']:g} px, engine floor {ENGINE_FLOOR_PX:g} px)"})
        font[key] = size
    return font, notes


def to_spec(request: dict) -> tuple[dict, dict, list[dict]]:
    """The timeline_layout spec, the id maps back to the request, and notes."""
    cal = Calendar(request["calendar"])
    font, notes = resolve_style(request)
    style = request.get("style") or {}
    bounds = {**DEFAULT_BOUNDS, **(request.get("bounds") or {})}
    lanes = []
    for lane in request["lanes"]:
        bars = []
        for task in request.get("tasks") or []:
            if task["lane"] != lane["id"]:
                continue
            s, e = cal.bar_units(date.fromisoformat(task["start"]), date.fromisoformat(task["end"]))
            bar = {"id": task["id"], "start": s, "end": e, "label": task["name"]}
            if task.get("kind", "task") != "task":
                bar["kind"] = task["kind"]
            bars.append(bar)
        lanes.append({"id": lane["id"], "label": lane["name"], "bars": bars})
    gates, milestones, order = [], [], {"gates": [], "milestones": []}
    for ms in request.get("milestones") or []:
        at = cal.marker_unit(date.fromisoformat(ms["date"]))
        if ms.get("kind", "milestone") == "gate":
            item = {"at": at, "label": ms["name"]}
            if ms.get("lane"):
                item["through"] = ms["lane"]
            gates.append(item)
            order["gates"].append(ms["id"])
        else:
            item = {"at": at, "label": ms["name"]}
            if ms.get("emphasis"):
                item["emphasis"] = True
            milestones.append(item)
            order["milestones"].append(ms["id"])
    spec = {
        "region": bounds,
        "horizon": {"unit": "week", "start": 1, "end": cal.weeks, "prefix": request["calendar"].get("prefix", "W"),
                    "marker_at": "start"},
        "font": font,
        "lane_label_w": float(style.get("lane_label_w", 190)),
        "lanes": lanes,
        "milestones": milestones,
        "gates": gates,
        "dependencies": [{"from": d["from"], "to": d["to"]} for d in request.get("dependencies") or []],
    }
    if style.get("colors"):
        spec["colors"] = dict(style["colors"])
    dep_ids = [d.get("id") or f"dep{i + 1}" for i, d in enumerate(request.get("dependencies") or [])]
    return spec, {"order": order, "dep_ids": dep_ids, "calendar": cal}, notes


@contextlib.contextmanager
def engine_metrics(metrics: FontMetrics):
    """Run timeline_layout with real font widths. The engine is unchanged; only its two width hooks are swapped."""
    saved = timeline_layout._width, timeline_layout._wrap
    if metrics.method != "estimator":
        timeline_layout._width = lambda text, size, family, weight="normal": metrics.width(text, size, weight) if text else 0.0
        timeline_layout._wrap = lambda text, size, max_width, family, weight="normal": metrics.wrap(text, size, max_width, weight)
    try:
        yield
    finally:
        timeline_layout._width, timeline_layout._wrap = saved


# ------------------------------------------------------------------------------ SVG with content ids

_TAG_RE = re.compile(r"^<([a-zA-Z]+)")


def _stamp(element: str, tag: str, content_id: str, role: str, new_id: str | None = None) -> str:
    match = _TAG_RE.match(element)
    if not match or match.group(1) != tag:
        raise RuntimeError(f"engine output order changed: expected <{tag}> for {content_id} ({role}), got {element[:60]!r}")
    body = re.sub(r'\sid="[^"]*"', "", element, count=1) if new_id else element
    extra = (f' id="{escape(new_id)}"' if new_id else "") + f' data-content-id="{escape(content_id)}" data-role="{role}"'
    return f"<{tag}{extra}{body[len(tag) + 1:]}"


def stamp_children(children: list[str], placed: dict, maps: dict, prefix: str) -> list[str]:
    """Walk timeline_layout.svg_parts' paint order and stamp each element with the request's IDs."""
    out, i = [], 0

    def take(tag: str, content_id: str, role: str, new_id: str | None = None) -> None:
        nonlocal i
        out.append(_stamp(children[i], tag, content_id, role, new_id))
        i += 1

    for n, lane in enumerate(placed["lanes"]):
        if n % 2 == 0:
            take("rect", f"lane:{lane['id']}", "lane-band")
        take("text", f"lane:{lane['id']}", "lane-label", f"{prefix}-lane-{lane['id']}-label")
    for tick in placed["ticks"]:
        take("line", f"tick:{tick['unit']}", "tick-mark")
        take("text", f"tick:{tick['unit']}", "tick-label")
    take("line", "axis", "axis")
    scale = placed["scale"]
    if scale.get("extended_to", scale["end"]) > scale["end"]:
        take("line", "axis", "axis-extension")
    for gate_id, _gate in zip(maps["order"]["gates"], placed["gates"]):
        take("line", f"milestone:{gate_id}", "gate-line", f"{prefix}-ms-{gate_id}-line")
        take("text", f"milestone:{gate_id}", "gate-label", f"{prefix}-ms-{gate_id}-label")
    for dep_id, _dep in zip(maps["dep_ids"], placed["dependencies"]):
        take("path", f"dependency:{dep_id}", "dependency", f"{prefix}-dep-{dep_id}")
    for bar in placed["bars"]:
        take("rect", f"task:{bar['id']}", "bar", f"{prefix}-task-{bar['id']}")
        take("text", f"task:{bar['id']}", "bar-label", f"{prefix}-task-{bar['id']}-label")
    for ms_id, ms in zip(maps["order"]["milestones"], placed["milestones"]):
        if ms["level"] > 0:
            take("line", f"milestone:{ms_id}", "milestone-leader")
        take("polygon", f"milestone:{ms_id}", "milestone-marker", f"{prefix}-ms-{ms_id}")
        take("text", f"milestone:{ms_id}", "milestone-label", f"{prefix}-ms-{ms_id}-label")
    if i != len(children):
        raise RuntimeError(f"engine output order changed: {len(children) - i} element(s) left unmapped")
    return out


def build_group(placed: dict, spec: dict, maps: dict, group_id: str, spec_ref: str = "", spec_sha: str = "") -> tuple[str, str]:
    """(group markup, inner markup) in the page contract timeline_layout's lint understands."""
    defs, children = timeline_layout.svg_parts(placed, spec, group_id)
    children = stamp_children(children, placed, maps, group_id)
    inner = "\n" + "\n".join([f"<defs>{defs}</defs>", *children]) + "\n"
    family = escape(placed["font"]["family"], {'"': "&quot;"})
    region = placed["region"]
    bounds = " ".join(f"{float(region[k]):g}" for k in ("x", "y", "w", "h"))
    group = (f'<g id="{escape(group_id)}" data-layout="{timeline_layout.LAYOUT_ATTR}" data-builder="{TOOL}" '
             f'data-spec="{escape(spec_ref)}" data-spec-sha="{spec_sha}" data-output-sha="{timeline_layout.group_digest(inner)}" '
             f'data-pptx-bounds="{bounds}" font-family="{family}">{inner}</g>')
    return group, inner


def standalone_svg(group: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">\n'
            '<rect width="1280" height="720" fill="#FFFFFF"/>\n' + group + "\n</svg>\n")


def write_into(page: Path, group: str, group_id: str) -> str:
    text = page.read_bytes().decode("utf-8")
    existing = timeline_layout.find_groups(text, group_id=group_id)
    if existing:
        span = existing[0]
        new = text[:span["start"]] + group + text[span["end"]:]
        action = "replaced"
    else:
        close = text.rfind("</svg>")
        if close < 0:
            raise RequestError(f"{page} has no closing </svg> to insert the timeline before")
        new = text[:close] + group + "\n" + text[close:]
        action = "inserted"
    if new != text:
        page.write_bytes(new.encode("utf-8"))
    return action


# ---------------------------------------------------------------------------------- classification

def leader_crossings(placed: dict) -> list[str]:
    """A milestone name dropped to a lower row hangs from its diamond by a leader line; the engine does not check that
    line against the names on the rows it passes (qualification t03: leaders cut through 'Tender issued' and 'Permit
    submitted' while the engine reported no check). Reported here so the status is not 'ok' when it happens."""
    found = []
    milestones = placed.get("milestones") or []
    top = placed.get("milestone_y")
    for m in milestones:
        if m.get("level", 0) <= 0 or top is None:
            continue
        x, y0, y1 = m["x"], top + 7, m["y0"] + 2
        for other in milestones:
            if other is m:
                continue
            r = other["rect"]
            if r[0] + 1 < x < r[2] - 1 and r[1] < y1 and r[3] > y0:
                found.append(f"milestone leader {m['label']!r} crosses milestone {other['label']!r}")
    return found


def classify(placed: dict, notes: list[dict]) -> tuple[str, list[dict], dict]:
    """Status, unsatisfied constraints and the capacity summary. Never alters content."""
    unsatisfied = [dict(n) for n in notes if n["kind"] != "style_raised"]
    unsatisfied += [{"kind": "collision", "detail": item, "source": "adapter"} for item in leader_crossings(placed)]
    region = placed["region"]
    capacity = {"region": region, "needs_h": placed["needs_h"], "fits_height": bool(placed["fits"]), "binding": []}
    if not placed["fits"]:
        capacity["binding"].append({"constraint": "height", "needs_px": placed["needs_h"], "available_px": region["h"],
                                    "detail": "every lane at the densest spacing, labels at the floor, still exceeds the region"})
    for check in placed["checks"]:
        if "does not fit the region" in check:
            continue
        if "leaves the region" in check:
            capacity["binding"].append({"constraint": "bounds", "detail": check})
        else:
            unsatisfied.append({"kind": "collision", "detail": check})
    if capacity["binding"]:
        return "capacity_failure", unsatisfied, capacity
    return ("partial" if unsatisfied else "ok"), unsatisfied, capacity


def scene_of(placed: dict, request: dict, maps: dict) -> dict:
    """Scene data keyed by the request's IDs, in slide px (1280 x 720 canvas, 1 px = 0.75 pt)."""
    cal: Calendar = maps["calendar"]
    scale = placed["scale"]
    unit_w = scale["unit_w"]
    tasks_by_id = {t["id"]: t for t in request.get("tasks") or []}
    tasks = []
    for bar in placed["bars"]:
        task = tasks_by_id[bar["id"]]
        text = bar["text"]
        tasks.append({"id": bar["id"], "name": task["name"], "lane": task["lane"], "start": task["start"], "end": task["end"],
                      "x0": bar["x0"], "x1": bar["x1"], "y": bar["y"], "h": bar["h"],
                      "label": {"where": text["where"], "lines": text["lines"], "rect": text["rect"]}})
    ms_by_id = {m["id"]: m for m in request.get("milestones") or []}
    milestones = []
    for ms_id, gate in zip(maps["order"]["gates"], placed["gates"]):
        ms = ms_by_id[ms_id]
        milestones.append({"id": ms_id, "name": ms["name"], "kind": "gate", "date": ms["date"], "lane": ms.get("lane"),
                           "placement": "header-line", "x": gate["x"], "line": gate["line"], "label_rect": gate["rect"],
                           "label_level": gate["level"]})
    for ms_id, item in zip(maps["order"]["milestones"], placed["milestones"]):
        ms = ms_by_id[ms_id]
        milestones.append({"id": ms_id, "name": ms["name"], "kind": "milestone", "date": ms["date"], "lane": ms.get("lane"),
                           "placement": "milestone-strip", "x": item["x"], "marker": item["marker"],
                           "label_rect": item["rect"], "label_level": item["level"]})
    deps = [{"id": dep_id, "from": dep["from"], "to": dep["to"], "points": dep["points"]}
            for dep_id, dep in zip(maps["dep_ids"], placed["dependencies"])]
    return {
        "canvas": {"w": 1280, "h": 720, "px_per_pt": 4 / 3},
        "region": placed["region"],
        "scale": {"calendar_start": cal.start.isoformat(), "calendar_end": cal.end.isoformat(), "x_of_calendar_start": scale["x0"],
                  "px_per_day": round(unit_w / 7, 6), "px_per_week": unit_w, "weeks": cal.weeks, "tick_step_weeks": scale["tick_step"],
                  "endpoint_convention": "task: [start 00:00, end + 1 day 00:00) (inclusive end date); "
                                         f"milestone: {'end' if cal.anchor == 'end_of_day' else 'start'} of its day; calendar days, no exclusions"},
        "font": placed["font"],
        "lanes": [{"id": lane["id"], "name": lane["label"], "y": lane["y"], "h": lane["h"], "rows": lane["rows"],
                   "label_lines": lane["label_lines"]} for lane in placed["lanes"]],
        "tasks": tasks, "milestones": milestones, "dependencies": deps,
        "engine_checks": placed["checks"],
    }


# --------------------------------------------------------------------------------------- build

def build(request: dict, group_id: str = "timeline", engine: str | None = None) -> dict:
    """The whole operation without file I/O: {status, group, scene, unsatisfied_constraints, capacity, ...}.
    engine: 'dense' (default, v0.2.0: dense_layout.py in this folder) or 'timeline_layout' (round 1: the fork's engine)."""
    engine = engine or (request.get("options") or {}).get("engine") or DEFAULT_ENGINE
    if engine not in ENGINES:
        return {"status": "error", "errors": [f"engine {engine!r} is not one of {ENGINES}"]}
    if engine == "dense":
        from dense_build import build_dense
        return build_dense(request, group_id)
    return build_timeline_layout(request, group_id)


def build_timeline_layout(request: dict, group_id: str = "timeline") -> dict:
    """Round-1 path: the fork's timeline_layout.py through this adapter (request v1 only)."""
    problems = validate_request(request)
    if problems:
        return {"status": "error", "errors": problems}
    spec, maps, notes = to_spec(request)
    metrics = FontMetrics(spec["font"]["family"])
    if metrics.method == "estimator":
        notes.append({"kind": "measurement", "detail": f"no font file found for {spec['font']['family']!r}: widths are the "
                      "text_measure estimator's (family-blind); fit decisions are unverified"})
    try:
        with engine_metrics(metrics):
            placed = timeline_layout.layout(spec)
    except timeline_layout.TimelineError as exc:
        return {"status": "error", "errors": [f"engine: {exc}"]}
    status, unsatisfied, capacity = classify(placed, notes)
    group, _inner = build_group(placed, spec, maps, group_id)

    def group_for(spec_ref: str = "", spec_sha: str = "") -> str:
        return build_group(placed, spec, maps, group_id, spec_ref, spec_sha)[0]

    return {"status": status, "spec": spec, "placed": placed, "maps": maps, "group": group, "group_for": group_for,
            "engine": ENGINE, "engine_version": _file_sha(Path(timeline_layout.__file__))[:12],
            "scene": scene_of(placed, request, maps), "unsatisfied_constraints": unsatisfied, "capacity": capacity,
            "notes": [n for n in notes if n["kind"] == "style_raised"], "measurement": metrics.describe()}


def time_scale_of(scene: dict, prefix: str = "W") -> dict:
    """The creator-declared time scale the harness reads from <workspace>/work/scene.json (decision D011): the x of the start of
    week 1 (calendar.start 00:00), px per week, and the ruler's tick labels (centred on their week)."""
    sc = scene["scale"]
    return {"origin_x": round(float(sc["x_of_calendar_start"]), 3), "px_per_week": round(float(sc["px_per_week"]), 4),
            "tick_pattern": re.escape(prefix) + r"(\d+)", "tick_anchor": "center"}


def write_scene(path: Path, time_scale: dict) -> None:
    """Merge {"time_scale": ...} into the creator's scene.json (other keys are kept)."""
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data["time_scale"] = time_scale
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def run(request_path: Path, out_path: Path, svg_path: Path | None = None, into: Path | None = None,
        group_id: str = "timeline", engine: str | None = None, scene_path: Path | None = None) -> dict:
    started = time.perf_counter()
    raw = request_path.read_bytes()
    code_files = sorted(_HERE.glob("*.py"))
    receipt = {"tool": TOOL, "tool_version": TOOL_VERSION,
               "engine_sha256": _file_sha(Path(timeline_layout.__file__)), "adapter_sha256": _file_sha(Path(__file__)),
               "adapter_files_sha256": {f.name: _file_sha(f) for f in code_files},
               "input_path": str(request_path), "input_sha256": sha256_bytes(raw),
               "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    result: dict = {"schema": RESULT_SCHEMA}
    request: dict = {}
    try:
        request = json.loads(raw.decode("utf-8"))
        built = build(request, group_id, engine)
    except (ValueError, RequestError) as exc:
        built = {"status": "error", "errors": [str(exc)]}
    except RuntimeError as exc:  # the engine's paint order no longer matches the stamping walk
        built = {"status": "error", "errors": [f"adapter: {exc}"]}
    status = built["status"]
    receipt["engine"] = built.get("engine", engine or DEFAULT_ENGINE)
    receipt["engine_version"] = built.get("engine_version")
    if status == "error":
        result.update(status="error", errors=built["errors"], unsatisfied_constraints=[], svg=None, scene=None)
        output_bytes = canonical_json(built["errors"])
    else:
        group = built["group"]
        svg_info: dict = {"group_id": group_id, "group_sha256": sha256_bytes(group.encode("utf-8")), "fragment": group}
        if svg_path:
            svg_path.parent.mkdir(parents=True, exist_ok=True)
            svg_path.write_text(standalone_svg(group), encoding="utf-8", newline="\n")
            svg_info["preview_path"] = str(svg_path)
        if into:
            if not into.is_file():
                raise SystemExit(f"build_timeline: no such page: {into}")
            request_copy = into.with_name(f"{into.stem}.timeline.request.json")
            request_copy.write_bytes(raw)
            spec_ref = request_copy.name
            group = built["group_for"](spec_ref, sha256_bytes(raw))
            svg_info.update(page=str(into), action=write_into(into, group, group_id), fragment=group,
                            group_sha256=sha256_bytes(group.encode("utf-8")), request_copy=str(request_copy))
        result.update(status=status, svg=svg_info, scene=built["scene"], capacity=built["capacity"],
                      unsatisfied_constraints=built["unsatisfied_constraints"], notes=built["notes"],
                      measurement=built["measurement"])
        output_bytes = svg_info["fragment"].encode("utf-8") + canonical_json(built["scene"])
    if status != "error":
        ts = time_scale_of(built["scene"], (request.get("calendar") or {}).get("prefix", "W"))
        receipt["time_scale"] = ts
        result["time_scale"] = ts
        if scene_path:
            write_scene(scene_path, ts)
            result["scene_path"] = str(scene_path)
    receipt.update(status=status, output_sha256=sha256_bytes(output_bytes),
                   elapsed_ms=round((time.perf_counter() - started) * 1000, 1))
    result["receipt"] = receipt
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lay out a one-slide timeline from a JSON request (experimental).",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--in", dest="request", required=True, help="request JSON (schema exp_svg.build_timeline.request.v1 or v2)")
    parser.add_argument("--out", required=True, help="result JSON: status, receipt, scene, svg fragment, unsatisfied constraints")
    parser.add_argument("--svg", help="also write a previewable 1280x720 SVG holding the group")
    parser.add_argument("--into", help="write the group into this page SVG (replacing the group of --group-id, or before </svg>)")
    parser.add_argument("--group-id", default="timeline", help="id of the timeline group and prefix of its element ids")
    parser.add_argument("--scene", help="also merge {\"time_scale\": ...} into this scene.json (the creator's work/scene.json)")
    parser.add_argument("--engine", choices=ENGINES, default=None,
                        help="layout engine (default: request options.engine, else 'dense'); 'timeline_layout' = round-1 behaviour")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        from console_encoding import configure_utf8_stdio
        configure_utf8_stdio()
    except (ImportError, RuntimeError, ValueError, OSError):
        pass
    if not _ID_RE.match(args.group_id):
        print(f"build_timeline: --group-id must match {_ID_RE.pattern}", file=sys.stderr)
        return 2
    request_path = Path(args.request)
    if not request_path.is_file():
        print(f"build_timeline: no such request: {request_path}", file=sys.stderr)
        return 2
    pinned = _pinned_engines()  # experiment packages pin their engine (orchestrator decision D020)
    chosen = args.engine or "dense"
    if pinned and chosen not in pinned:
        print(f"build_timeline: timeline engine {chosen!r} is not part of this package (allowed: {sorted(pinned)})", file=sys.stderr)
        return 2
    result = run(request_path, Path(args.out), Path(args.svg) if args.svg else None,
                 Path(args.into) if args.into else None, args.group_id, args.engine, Path(args.scene) if args.scene else None)
    receipt = result["receipt"]
    print(f"build_timeline: status={result['status']} elapsed_ms={receipt['elapsed_ms']} out={args.out}")
    for item in result.get("errors") or []:
        print(f"  ERROR {item}")
    for item in (result.get("capacity") or {}).get("binding") or []:
        print(f"  CAPACITY {item.get('constraint')}: {item.get('detail')}")
    for item in result.get("unsatisfied_constraints") or []:
        print(f"  UNSATISFIED {item['kind']}: {item['detail']}")
    return EXIT_CODES[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
