#!/usr/bin/env python3
"""Lay out a Gantt chart or timeline from its record: every bar and marker exactly on the scale, every label placed where
it is read, nothing colliding. Emits coordinates and an SVG fragment in the authoring contract.

    timeline_layout.py spec.json [--svg out.svg] [--json out.json] [--prefix tl]
    timeline_layout.py spec.json --into <project>/svg_output/<stem>.svg [--group-id timeline] [--save-spec path]

--into writes the chart straight into the page as ONE group, `<g id="timeline" data-layout="timeline_layout" data-spec=...
data-spec-sha=... data-output-sha=...>`, replacing the group of that id or inserting it before `</svg>` (nothing else in the
page changes), and saves the spec beside the page as `svg_output/<stem>.timeline.json`. To change the chart, edit that spec and
run again with --into: the lint flags a group whose markup no longer matches its data-output-sha (TIMELINE_HAND_EDITED).

Hand-placed Gantts shipped with bars a week off the ruler, labels clipped or colliding, tick labels crowding each other,
and milestones written in a strip instead of at their marker (FORK_RUN_LOG; consulting-typesetting.md §6). This does the
arithmetic instead:
- x comes from the scale only: a bar {start: s, end: e} covers units s..e inclusive, from the left edge of unit s to the
  right edge of unit e; a milestone or gate `at` N sits at the end of unit N (`"marker_at": "start" | "middle" | "end"`).
- a bar's label goes INSIDE when it fits with 8 px padding at the label size, else BESIDE it (6 px after its end, or
  before its start when the right is taken or off the chart), else ABOVE it, wrapped - never truncated, never under 14 px;
  bars whose labels would collide go on separate rows of their lane;
- tick labels are thinned to the smallest regular step at which none collide;
- milestone and gate names sit at their markers, stacked into extra rows only where two would collide;
- dependencies are arrows from the end of one bar to the start of the other, routed through the gaps between rows.

Spec (JSON; sizes in slide px):
  {
    "region": {"x": 60, "y": 150, "w": 1160, "h": 480},
    "horizon": {"unit": "week", "start": 1, "end": 26, "prefix": "W", "marker_at": "end"},   # unit: week | month
    "font": {"family": "Segoe UI", "label_px": 14, "lane_px": 14, "tick_px": 14},
    "lane_label_w": 190,
    "lanes": [{"id": "A", "label": "Mobilise and manage",
               "bars": [{"id": "charter", "start": 1, "end": 3, "label": "Charter", "kind": "task"}]}],
                                          # kind: task (filled) | window (pale span) | deliverable (accent)
    "milestones": [{"at": 10, "label": "Anchor slice", "emphasis": true}],   # emphasis: the one to read first, bold
    "gates": [{"at": 4, "label": "Assumptions gate", "through": "A"}],   # through: the line stops at the foot of that lane
                                                                          # (default: it runs down through every lane)
    "deadlines": [{"at": 51.3, "label": "Aug 1, 2023 - latest first draft"}],
                                          # a dated solid line named at its top; `at` may be fractional and may lie past
                                          # the horizon's end: the scale is then extended (dashed axis) to show it
    "dependencies": [{"from": "charter", "to": "baseline"}],
    "colors": {"bar": "#1F5A8A", "window": "#C9D6E3", "deliverable": "#B4162E", "text": "#15181E", "muted": "#5B616C",
               "band": "#F3F4F6", "grid": "#D9DCE1", "gate": "#B4162E", "milestone": "#15181E", "dependency": "#15181E",
               "deadline": "#B4162E"}
  }

Output: JSON with every element's rectangle, `fits`, and `checks` - every remaining collision: label on label, labels on one
row closer than 8 px, a label within 4 px of a tick label, label on bar, a gate or deadline line through a label or tick, an
arrow through a label, anything outside the region; with --svg a previewable 1280x720 SVG holding the fragment. Bars are `<rect>` with
their label `<text>` drawn after them and inside them where it fits, so the export puts the label in the bar's own text
frame. A legend, if you add one, explains the symbols only (a diamond is a milestone, a dashed line a gate, an arrow a
dependency) - every name is already on the chart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import text_measure  # noqa: E402

FLOOR_PX = 14.0            # 10.5 pt: no label on the chart is set smaller
PAD_IN = 8.0               # a label inside a bar keeps this much from each end
GAP_BESIDE = 6.0           # a label beside a bar starts this far from it
ROW_GAP = 6.0              # vertical gap between the rows of a lane
ITEM_GAP = 10.0            # horizontal gap between two things sharing a row
ROW_LABEL_GAP = 8.0        # the check: two labels on one row are never closer than this
TICK_CLEAR = 4.0           # the check: no other label comes within this of a tick label (the ruler row is reserved)
DEFAULT_COLORS = {"bar": "#1F5A8A", "window": "#C9D6E3", "deliverable": "#B4162E", "text": "#15181E", "muted": "#5B616C",
                  "band": "#F3F4F6", "grid": "#D9DCE1", "gate": "#B4162E", "milestone": "#15181E", "dependency": "#15181E"}
LAYOUT_ATTR = "timeline_layout"  # the value of data-layout on a group this helper wrote into a page
NICE_STEPS = {"week": (1, 2, 4, 5, 8, 10, 13, 26, 52), "month": (1, 2, 3, 6, 12, 24)}


class TimelineError(RuntimeError):
    pass


def _width(text: str, size: float, family: str, weight: str = "normal") -> float:
    return text_measure.measure_text(text, size=size, family=family, weight=weight) if text else 0.0


def _wrap(text: str, size: float, max_width: float, family: str, weight: str = "normal") -> tuple[list[str], float]:
    lines, widths, _ = text_measure.wrap_text(text, size=size, max_width=max_width, family=family, weight=weight)
    return lines, (max(widths) if widths else 0.0)


def _luminance(colour: str) -> float:
    colour = colour.lstrip("#")
    if len(colour) != 6:
        return 0.0
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _overlap(a, b, gap: float = 0.0) -> bool:
    return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap


class Scale:
    """Units s..e map onto [x0, x0 + width]: unit u spans [x(u), x(u + 1))."""

    def __init__(self, start: int, end: int, x0: float, width: float, marker_at: str = "end") -> None:
        if end < start:
            raise TimelineError("the horizon ends before it starts")
        self.start, self.end, self.x0, self.width = start, end, x0, width
        self.unit = width / (end - start + 1)
        self.marker_at = marker_at

    def x(self, unit: float) -> float:
        return self.x0 + (unit - self.start) * self.unit

    def bar(self, start: float, end: float) -> tuple[float, float]:
        return self.x(start), self.x(end + 1)

    def marker(self, at: float) -> float:
        offset = {"start": 0.0, "middle": 0.5, "end": 1.0}.get(self.marker_at, 1.0)
        return self.x(at + offset)


def thin_ticks(scale: Scale, unit: str, prefix: str, size: float, family: str, last: int | None = None) -> tuple[int, list[dict]]:
    """The smallest regular step at which no two tick labels collide (and the last label never collides with its neighbour).
    `last`: the plan's final unit when the scale runs past it (to show a deadline after the horizon)."""
    last = scale.end if last is None else last
    for step in NICE_STEPS.get(unit, NICE_STEPS["week"]) + (last - scale.start + 1,):
        units = list(range(scale.start, last + 1, step))
        ticks = []
        for u in units:
            label = f"{prefix}{u}"
            w = _width(label, size, family)
            centre = scale.x(u + 0.5)
            if centre - w / 2 < scale.x0 - 12 or centre + w / 2 > scale.x0 + scale.width + 0.5:
                continue  # wider than its unit at the chart's right edge (or past the 12 px gutter on the left): left unlabelled
            ticks.append({"unit": u, "label": label, "x": centre, "w": w, "rect": [centre - w / 2, 0, centre + w / 2, 1]})
        if all(b["rect"][0] - a["rect"][2] >= 8 for a, b in zip(ticks, ticks[1:])):
            return step, ticks
    return last - scale.start + 1, ticks[:1]


def place_bar_label(bar: dict, label_w: float, size: float, chart: tuple[float, float], family: str, lines_limit_w: float,
                    gate_xs: tuple = (), forbid: tuple = ()) -> dict:
    """inside | right | left | above, by the rules of consulting-typesetting.md §6. A label beside its bar never sits across a
    gate's line, never on the side an arrow leaves (a dependency's source) or arrives (its target)."""
    x0, x1 = bar["x0"], bar["x1"]
    if label_w + 2 * PAD_IN <= x1 - x0:
        return {"where": "inside", "lines": [bar["label"]], "w": label_w, "x": x0 + PAD_IN}
    beside = beside_options(bar, label_w, chart, gate_xs, forbid)
    return beside[0] if beside else place_above(bar, size, chart, family, lines_limit_w, gate_xs)


def beside_options(bar: dict, label_w: float, chart: tuple[float, float], gate_xs: tuple = (), forbid: tuple = ()) -> list[dict]:
    """Every clean place beside the bar (right, then left): the packer may take the other side when that saves a row."""
    clear = lambda a, b: not any(a - 3 <= g <= b + 3 for g in gate_xs)  # noqa: E731
    right, left = bar["x1"] + GAP_BESIDE, bar["x0"] - GAP_BESIDE - label_w
    found = []
    if "right" not in forbid and right + label_w <= chart[1] and clear(right, right + label_w):
        found.append({"where": "right", "lines": [bar["label"]], "w": label_w, "x": right})
    if "left" not in forbid and left >= chart[0] and clear(left, left + label_w):
        found.append({"where": "left", "lines": [bar["label"]], "w": label_w, "x": left})
    return found


def place_above(bar: dict, size: float, chart: tuple[float, float], family: str, lines_limit_w: float, gate_xs: tuple = ()) -> dict:
    x0, x1 = bar["x0"], bar["x1"]
    clear = lambda a, b: not any(a - 3 <= g <= b + 3 for g in gate_xs)  # noqa: E731
    room = max(lines_limit_w, 120.0)
    lines, width = _wrap(bar["label"], size, room, family)
    # above the bar, starting over it: at its start, or just past a gate line that would cut the name
    starts = [x0] + [g + 4 for g in gate_xs if x0 <= g + 4 <= max(x0, x1 - 12)] + [x1 - width]
    starts = [max(chart[0], min(x, chart[1] - width)) for x in starts]
    x = next((x for x in starts if clear(x, x + width) and x <= x1 and x + width >= x0), starts[0])
    return {"where": "above", "lines": lines, "w": width, "x": x}


def _footprint(item: dict, label: dict) -> tuple[float, float]:
    if label["where"] == "inside":
        return item["x0"], item["x1"]
    return min(item["x0"], label["x"]), max(item["x1"], label["x"] + label["w"])


def pack_rows(items: list[dict], search_limit: int = 1024) -> list[list[dict]]:
    """Bars into the rows of their lane: nothing (a bar or its label) shares a row with something closer than 8 px. Each bar's
    label takes its preferred place (`_options[0]`); where a bar's label could also sit on its other side, the sides that give the
    fewest rows win (fewest switched labels on a tie), searched exhaustively while that is at most `search_limit` combinations."""
    ordered = sorted(items, key=lambda b: (b["x0"], b["x1"]))
    flexible = [i for i, item in enumerate(ordered) if len(item.get("_options") or []) > 1]

    def first_fit(choice: dict) -> list[list[tuple[dict, dict]]]:
        rows: list[list[tuple[dict, dict, tuple]]] = []
        for i, item in enumerate(ordered):
            label = item["_options"][choice.get(i, 0)]
            span = _footprint(item, label)
            for row in rows:
                if all(span[0] >= o[1] + ROW_LABEL_GAP or span[1] + ROW_LABEL_GAP <= o[0] for _, _, o in row):
                    row.append((item, label, span))
                    break
            else:
                rows.append([(item, label, span)])
        return rows

    best = first_fit({})
    if flexible and 2 ** len(flexible) <= search_limit:
        best_key = (len(best), 0)
        for mask in range(1, 2 ** len(flexible)):
            choice = {i: 1 for bit, i in enumerate(flexible) if mask >> bit & 1}
            rows = first_fit(choice)
            key = (len(rows), len(choice))
            if key < best_key:
                best, best_key = rows, key
    out = []
    for row in best:
        for item, label, span in row:
            item["text"], item["footprint"] = label, span
            item.pop("_options", None)
        out.append([item for item, _, _ in row])
    return out


def layout(spec: dict) -> dict:
    font = {"family": "Segoe UI", "label_px": 14, "lane_px": 14, "tick_px": 14, **(spec.get("font") or {})}
    if min(font["label_px"], font["lane_px"], font["tick_px"]) < FLOOR_PX:
        raise TimelineError(f"the spec asks for type under the {FLOOR_PX:.0f} px floor (10.5 pt)")
    family, size = font["family"], float(font["label_px"])
    region = spec.get("region") or {"x": 60, "y": 150, "w": 1160, "h": 480}
    horizon = spec.get("horizon") or {}
    unit = horizon.get("unit", "week")
    prefix = horizon.get("prefix", "W" if unit == "week" else "M")
    start, end = int(horizon.get("start", 1)), int(horizon["end"])
    lane_label_w = float(spec.get("lane_label_w", 190))
    chart_x0 = region["x"] + lane_label_w + 12
    chart_x1 = region["x"] + region["w"]
    marker_at = horizon.get("marker_at", "end")
    offset = {"start": 0.0, "middle": 0.5, "end": 1.0}.get(marker_at, 1.0)
    scale_end = end  # a deadline past the horizon's end extends the scale by the units it needs, and no further
    for d in spec.get("deadlines") or []:
        position = float(d["at"]) + offset
        if position < start:
            raise TimelineError(f"deadline {d.get('label')!r} at {d['at']} is before the horizon starts ({start})")
        scale_end = max(scale_end, math.ceil(position - 1e-9) - 1)
    scale = Scale(start, scale_end, chart_x0, chart_x1 - chart_x0, marker_at)
    line_h = round(size * 1.3, 2)

    deadline_xs = tuple(round(scale.x(float(d["at"]) + offset), 2) for d in spec.get("deadlines") or [])
    lane_ids = [str(lane.get("id", i)) for i, lane in enumerate(spec.get("lanes") or [])]

    def reach(item: dict) -> int:
        """The last lane a gate's or deadline's line runs through: `through: <lane id>` stops it at that lane's foot."""
        if item.get("through") is None:
            return len(lane_ids) - 1
        if str(item["through"]) not in lane_ids:
            raise TimelineError(f"{item.get('label')!r} runs through lane {item['through']!r}, which is not a lane")
        return lane_ids.index(str(item["through"]))

    line_reach = [(round(scale.marker(g["at"]), 2), reach(g)) for g in spec.get("gates") or []]
    line_reach += [(x, reach(d)) for d, x in zip(spec.get("deadlines") or [], deadline_xs)]
    sources = {d.get("from") for d in spec.get("dependencies") or []}
    targets = {d.get("to") for d in spec.get("dependencies") or []}
    bars_by_id: dict[str, dict] = {}
    lanes_out = []
    for lane_index, lane in enumerate(spec.get("lanes") or []):
        lane_lines, _ = _wrap(lane.get("label", ""), font["lane_px"], lane_label_w - 16, family, "bold")
        placed_bars = []
        gate_xs = tuple(x for x, last in line_reach if last >= lane_index)  # only the lines that run through this lane
        for bar_index, bar in enumerate(lane.get("bars") or []):
            if bar["end"] < bar["start"] or bar["start"] < start or bar["end"] > end:
                raise TimelineError(f"bar {bar.get('label')!r} ({bar['start']}-{bar['end']}) is outside the horizon {start}-{end}")
            x0, x1 = scale.bar(bar["start"], bar["end"])
            item = {"id": bar.get("id") or f"{lane.get('id', lane_index)}.{bar_index}", "lane": lane_index, "label": bar.get("label", ""),
                    "kind": bar.get("kind", "task"), "start": bar["start"], "end": bar["end"], "x0": round(x0, 2), "x1": round(x1, 2)}
            forbid = tuple(side for side, ends in (("right", sources), ("left", targets)) if item["id"] in ends)
            label_w = _width(item["label"], size, family)
            label = place_bar_label(item, label_w, size, (chart_x0, chart_x1), family, x1 - x0, gate_xs, forbid)
            item["_options"] = [label] + ([o for o in beside_options(item, label_w, (chart_x0, chart_x1), gate_xs, forbid) if o["where"] != label["where"]]
                                          if label["where"] in ("right", "left") else [])
            placed_bars.append(item)
            bars_by_id[item["id"]] = item
        rows = pack_rows(placed_bars)
        lanes_out.append({"index": lane_index, "id": lane.get("id", str(lane_index)), "label": lane.get("label", ""), "label_lines": lane_lines, "rows": rows})

    # markers along the top (gates) and the bottom (milestones): names at their markers, stacked only where they would collide
    def stack(items: list[dict], kind: str) -> int:
        """Names at their markers, in as few rows as possible. A gate's name starts at its dashed line (the line hangs from
        under the name); a milestone's name is centred under its diamond (else set just after or before it), joined by a
        leader when it drops a row. No name sits across another marker's line or leader, or on another name. Each name first
        takes the first place that is clean at the lowest row; when choosing other sides (searched exhaustively up to 2048
        combinations) saves a row, those sides win."""
        ordered = sorted(items, key=lambda m: m["x"])
        widths, option_lists = [], []
        for item in ordered:
            w = _width(item["label"], size, family, "bold" if item.get("emphasis") else "normal")
            after = item["x"] + 4 if item["x"] + 4 + w <= chart_x1 else item["x"] - 4 - w
            before = item["x"] - 4 - w if item["x"] - 4 - w >= chart_x0 else after
            options = [after, before] if kind == "gate" else [min(max(item["x"] - w / 2, chart_x0), chart_x1 - w), after, before]
            widths.append(w)
            option_lists.append(list(dict.fromkeys(round(x, 4) for x in options)))
        best, unresolved = assign_levels(ordered, widths, option_lists, kind, None)
        combos = math.prod(len(o) for o in option_lists)
        if 1 < combos <= 2048:
            import itertools
            best_key = (unresolved, 1 + max((level for _, level in best), default=-1), 0)
            for choice in itertools.product(*(range(len(o)) for o in option_lists)):
                trial, unresolved = assign_levels(ordered, widths, option_lists, kind, choice)
                key = (unresolved, 1 + max((level for _, level in trial), default=-1), sum(1 for c in choice if c))
                if key < best_key:
                    best, best_key = trial, key
        for item, w, (x, level) in zip(ordered, widths, best):
            item.update(level=level, text_x=x, text_w=w)
        return 1 + max((item["level"] for item in ordered), default=-1)

    def assign_levels(ordered: list[dict], widths: list[float], option_lists: list[list[float]], kind: str, choice) -> tuple[list[tuple[float, int]], int]:
        """(x, level) for each name, and how many found no clean place (each then takes a new row, for the checks to report)."""
        placed_items: list[dict] = []

        def clashes(item, span, level) -> bool:
            for other in placed_items:
                o_span, o_level = other["_span"], other["level"]
                if o_level == level and not (span[0] >= o_span[1] + ITEM_GAP or span[1] + ITEM_GAP <= o_span[0]):
                    return True
                if kind == "gate":  # a gate's line hangs from its name down through the rows under it
                    if o_level < level and span[0] - 3 <= other["x"] <= span[1] + 3:
                        return True
                    if o_level > level and o_span[0] - 3 <= item["x"] <= o_span[1] + 3:
                        return True
                else:  # a milestone's leader rises from its name up to its diamond, through the rows above it
                    if o_level < level and o_span[0] - 3 <= item["x"] <= o_span[1] + 3:
                        return True
                    if o_level > level and span[0] - 3 <= other["x"] <= span[1] + 3:
                        return True
            return False

        result, unresolved = [], 0
        for index, item in enumerate(ordered):
            w = widths[index]
            options = option_lists[index] if choice is None else [option_lists[index][choice[index]]]
            found = None
            for level in range(8):
                for x in options:
                    if not clashes(item, (x, x + w), level):
                        found = (x, level)
                        break
                if found:
                    break
            if found is None:  # nowhere clean within eight rows: take the next free row and let the check report it
                found = (options[0], 1 + max((o["level"] for o in placed_items), default=-1))
                unresolved += 1
            placed_items.append({"x": item["x"], "level": found[1], "_span": (found[0], found[0] + w)})
            result.append(found)
        return result, unresolved

    gates = [{"at": g["at"], "label": g.get("label", ""), "x": round(scale.marker(g["at"]), 2), "kind": "gate", "reach": reach(g)} for g in spec.get("gates") or []]
    deadlines = [{"at": d["at"], "label": d.get("label", ""), "x": x, "kind": "deadline", "reach": reach(d)} for d, x in zip(spec.get("deadlines") or [], deadline_xs)]
    milestones = [{"at": m["at"], "label": m.get("label", ""), "x": round(scale.marker(m["at"]), 2), **({"emphasis": True} if m.get("emphasis") else {})}
                  for m in spec.get("milestones") or []]
    # gates and deadlines share the header: each name at the top of its own line, stacked only where two would collide
    gate_levels = stack(gates + deadlines, "gate") if gates or deadlines else 0
    milestone_levels = stack(milestones, "milestone") if milestones else 0
    step, ticks = thin_ticks(scale, unit, prefix, font["tick_px"], family, last=end)
    if scale_end > end:  # the extension past the plan is labelled with its first unit where that label fits
        label = f"{prefix}{end + 1}"
        w = _width(label, font["tick_px"], family)
        centre = scale.x(end + 1.5)
        rect = [centre - w / 2, 0, centre + w / 2, 1]
        if rect[2] <= chart_x1 and (not ticks or rect[0] - ticks[-1]["rect"][2] >= 8):
            ticks.append({"unit": end + 1, "label": label, "x": centre, "w": w, "rect": rect, "extension": True})
    lines_x = [g["x"] for g in gates + deadlines]
    ticks = [t for t in ticks if not any(t["rect"][0] - 3 <= x <= t["rect"][2] + 3 for x in lines_x)]  # a gate's line runs through the ruler

    # vertical budget: the most generous spacing that fits, never smaller type
    def lane_height(lane: dict, pad: float, bar_h: float, row_gap: float) -> float:
        rows_h = sum(bar_h + max((len(b["text"]["lines"]) for b in row if b["text"]["where"] == "above"), default=0) * line_h for row in lane["rows"])
        rows_h += row_gap * max(0, len(lane["rows"]) - 1)
        label_h = len(lane["label_lines"]) * font["lane_px"] * 1.3
        return max(rows_h, label_h) + 2 * pad

    header = gate_levels * line_h + (6 if gate_levels else 0) + font["tick_px"] * 1.4 + 8
    footer = (28 + milestone_levels * line_h) if milestones else 0
    bar_h = row_gap = pad = total = 0.0
    fits = False
    for bar_h, row_gap, pad in ((max(26.0, size + 12), 6.0, 8.0), (max(24.0, size + 10), 5.0, 6.0), (max(22.0, size + 8), 4.0, 4.0),
                                (max(20.0, size + 6), 3.0, 3.0), (max(18.0, size + 4), 2.0, 2.0)):  # dense plans: the type never shrinks
        total = header + sum(lane_height(lane, pad, bar_h, row_gap) for lane in lanes_out) + footer
        if total <= region["h"] + 0.5:
            fits = True
            break
    if fits and lanes_out:  # give spare height to the lanes (up to 10 px more padding each) so the chart fills its region
        pad += max(0.0, min(10.0, (region["h"] - total) / (2 * len(lanes_out))))
        total = header + sum(lane_height(lane, pad, bar_h, row_gap) for lane in lanes_out) + footer

    y = region["y"]
    gate_top = y
    y += gate_levels * line_h + (6 if gate_levels else 0)  # the tick row below is reserved: no marker name reaches into it
    tick_base = y + font["tick_px"] * 1.05
    y += font["tick_px"] * 1.4 + 8
    axis_y = y - 4
    lanes_top = y
    out_bars = []
    row_bands = []  # (lane index, top, bottom) of every row: the gaps between them carry the dependency arrows
    for lane in lanes_out:
        top = y
        height = lane_height(lane, pad, bar_h, row_gap)
        lane["y"], lane["h"] = round(top, 2), round(height, 2)
        row_y = top + pad
        for row in lane["rows"]:
            above = max((len(b["text"]["lines"]) for b in row if b["text"]["where"] == "above"), default=0)
            bar_y = row_y + above * line_h
            for b in row:
                b["y"], b["h"] = round(bar_y, 2), bar_h
                t = b["text"]
                if t["where"] == "above":
                    t["y0"] = round(bar_y - len(t["lines"]) * line_h, 2)
                    t["baselines"] = [round(t["y0"] + (i + 0.5) * line_h + 0.35 * size, 2) for i in range(len(t["lines"]))]
                else:
                    t["y0"] = round(bar_y + (bar_h - line_h) / 2, 2)
                    t["baselines"] = [round(bar_y + bar_h / 2 + 0.35 * size, 2)]
                t["rect"] = [round(t["x"], 2), t["y0"], round(t["x"] + t["w"], 2), round(t["y0"] + len(t["lines"]) * line_h, 2)]
                out_bars.append(b)
            row_bands.append((lane["index"], row_y, bar_y + bar_h))
            row_y = bar_y + bar_h + row_gap
        y = top + height
    lanes_bottom = y
    milestone_y = y + 6 + 8 if milestones else None
    for m in milestones:
        m["marker"] = [m["x"] - 7, milestone_y - 7, m["x"] + 7, milestone_y + 7]
        m["y0"] = round(milestone_y + 8 + 4 + m["level"] * line_h, 2)
        m["rect"] = [round(m["text_x"], 2), m["y0"], round(m["text_x"] + m["text_w"], 2), round(m["y0"] + line_h, 2)]
    for g in gates + deadlines:
        g["y0"] = round(gate_top + g["level"] * line_h, 2)
        g["rect"] = [round(g["text_x"], 2), g["y0"], round(g["text_x"] + g["text_w"], 2), round(g["y0"] + line_h, 2)]
        foot = lanes_out[g["reach"]]["y"] + lanes_out[g["reach"]]["h"] if lanes_out and g["reach"] >= 0 else lanes_bottom
        g["line"] = [g["x"], round(gate_top + g["level"] * line_h + line_h, 2), g["x"], round(foot, 2)]
    for t in ticks:
        t["rect"] = [round(t["rect"][0], 2), round(tick_base - font["tick_px"], 2), round(t["rect"][2], 2), round(tick_base + 0.3 * font["tick_px"], 2)]
        t["baseline"] = round(tick_base, 2)

    # dependencies: finish-to-start arrows. The vertical run goes where it crosses the fewest bars and labels; when the next
    # task starts before this one ends, the route drops into the gap under the source row and comes back to the target's start
    # arrows are drawn behind the bars, so passing under a bar costs little; crossing a label that sits on the band costs a lot
    obstacles = [([b["x0"], b["y"], b["x1"], b["y"] + b["h"]], 1) for b in out_bars] +                 [(b["text"]["rect"], 10) for b in out_bars if b["text"]["where"] != "inside"] +                 [(m["rect"], 10) for m in milestones] + [(g["rect"], 10) for g in gates + deadlines]

    def crossings(points) -> int:
        count = 0
        for p, q in zip(points, points[1:]):
            box = [min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])]
            count += sum(weight for o, weight in obstacles if _overlap(box, [o[0] + 1, o[1] + 1, o[2] - 1, o[3] - 1]))
        return count

    deps = []
    for dep in spec.get("dependencies") or []:
        a, b = bars_by_id.get(dep["from"]), bars_by_id.get(dep["to"])
        if a is None or b is None:
            raise TimelineError(f"dependency {dep.get('from')} -> {dep.get('to')} names an unknown bar")
        ay, by = a["y"] + a["h"] / 2, b["y"] + b["h"] / 2
        options = []
        if b["x0"] >= a["x1"] + 12:
            for k in range(int(a["x1"] + 6), int(b["x0"] - 5), 2):
                options.append([[a["x1"], ay], [k, ay], [k, by], [b["x0"], by]])
        below = by > ay
        gaps = sorted({round(bottom + row_gap / 2, 2) for _, _, bottom in row_bands} | {round(top - row_gap / 2, 2) for _, top, _ in row_bands})
        between = [g for g in gaps if (a["y"] + a["h"] <= g <= b["y"]) or (b["y"] + b["h"] <= g <= a["y"])] or [a["y"] + a["h"] + row_gap / 2 if below else a["y"] - row_gap / 2]
        for gap_y in between:
            for back in range(10, int(max(12, b["x0"] - chart_x0 + 6)), 4):
                options.append([[a["x1"], ay], [a["x1"] + 6, ay], [a["x1"] + 6, gap_y], [b["x0"] - back, gap_y], [b["x0"] - back, by], [b["x0"], by]])
        best = min(options, key=lambda pts: (crossings(pts), len(pts), abs(pts[1][0] - (b["x0"] - 10))))
        points = [[round(x, 2), round(yy, 2)] for x, yy in best]
        clean = [points[0]]
        for p in points[1:]:
            if abs(p[0] - clean[-1][0]) > 0.01 or abs(p[1] - clean[-1][1]) > 0.01:
                clean.append(p)
        corners = [clean[0]]
        for here, after in zip(clean[1:], clean[2:] + [None]):  # drop points on a straight run: an arrow is its corners
            if after is not None and ((corners[-1][0] == here[0] == after[0]) or (corners[-1][1] == here[1] == after[1])):
                continue
            corners.append(here)
        deps.append({"from": dep["from"], "to": dep["to"], "points": corners})

    placed = {"region": region, "scale": {"start": start, "end": end, "unit": unit, "x0": round(chart_x0, 2), "unit_w": round(scale.unit, 4),
                                           "marker_at": scale.marker_at, "tick_step": step, "extended_to": scale_end},
              "font": font, "fits": fits, "needs_h": round(total, 1), "lane_pad": round(pad, 2), "axis_y": round(axis_y, 2), "lanes_top": round(lanes_top, 2),
              "lanes_bottom": round(lanes_bottom, 2), "milestone_y": milestone_y,
              "lanes": [{k: v for k, v in lane.items() if k != "rows"} | {"rows": len(lane["rows"])} for lane in lanes_out],
              "bars": [{k: v for k, v in b.items() if k != "footprint"} for b in out_bars],
              "ticks": ticks, "gates": gates, "deadlines": deadlines, "milestones": milestones, "dependencies": deps}
    placed["checks"] = checks(placed)
    return placed


def label_rects(placed: dict) -> list[tuple[str, list]]:
    rects = [(f"tick {t['label']}", t["rect"]) for t in placed["ticks"]]
    rects += [(f"bar label {b['label']!r}", b["text"]["rect"]) for b in placed["bars"]]
    rects += [(f"gate {g['label']!r}", g["rect"]) for g in placed["gates"]]
    rects += [(f"deadline {d['label']!r}", d["rect"]) for d in placed.get("deadlines") or []]
    rects += [(f"milestone {m['label']!r}", m["rect"]) for m in placed["milestones"]]
    return rects


def checks(placed: dict) -> list[str]:
    """Every remaining collision, each named, so the author sees exactly what is left to fix in the spec."""
    found = []
    rects = label_rects(placed)
    for i, (name_a, a) in enumerate(rects):
        for name_b, b in rects[i + 1:]:
            if _overlap(a, b, -0.5):
                found.append(f"{name_a} overlaps {name_b}")
                continue
            # two labels on one row (their line boxes share most of their height) keep 8 px between them
            shared = min(a[3], b[3]) - max(a[1], b[1])
            gap = max(b[0] - a[2], a[0] - b[2])
            if shared > 0.5 * min(a[3] - a[1], b[3] - b[1]) and gap < ROW_LABEL_GAP - 0.01:
                found.append(f"{name_a} and {name_b} are {max(gap, 0.0):.1f} px apart on one row ({ROW_LABEL_GAP:.0f} px minimum)")
    lane_px = placed["font"]["lane_px"]
    for lane in placed["lanes"]:  # a lane's name stays inside its own band
        bottom = lane["y"] + min(8.0, placed.get("lane_pad", 8.0)) + len(lane["label_lines"]) * lane_px * 1.3
        if bottom > lane["y"] + lane["h"] + 0.5:
            found.append(f"lane name {lane['label']!r} runs {bottom - lane['y'] - lane['h']:.1f} px past its lane")
    # the ruler row is reserved: no other label comes within 4 px of a tick label
    tick_rects = [(t["label"], t["rect"]) for t in placed["ticks"]]
    for name, rect in rects:
        if name.startswith("tick "):
            continue
        for label, tick in tick_rects:
            if _overlap(rect, tick, TICK_CLEAR) and not _overlap(rect, tick, -0.5):
                found.append(f"{name} comes within {TICK_CLEAR:.0f} px of tick {label}")
    for b in placed["bars"]:
        own = [b["x0"], b["y"], b["x1"], b["y"] + b["h"]]
        for other in placed["bars"]:
            rect = [other["x0"], other["y"], other["x1"], other["y"] + other["h"]]
            if other is not b and _overlap(own, rect, -0.5):
                found.append(f"bars {b['label']!r} and {other['label']!r} overlap")
            if other is not b and _overlap(b["text"]["rect"], rect, -0.5):
                found.append(f"bar label {b['label']!r} lies on bar {other['label']!r}")
        if b["text"]["where"] != "inside" and _overlap(b["text"]["rect"], own, -0.5):
            found.append(f"bar label {b['label']!r} straddles its bar")
        if b["text"]["where"] == "inside" and not (b["text"]["rect"][0] >= b["x0"] and b["text"]["rect"][2] <= b["x1"]):
            found.append(f"bar label {b['label']!r} runs out of its bar")
    for g in placed["gates"] + (placed.get("deadlines") or []):
        x1, y1, x2, y2 = g["line"]
        kind = g.get("kind", "gate")
        for b in placed["bars"]:
            r = b["text"]["rect"]
            if b["text"]["where"] != "inside" and r[0] + 1 < x1 < r[2] - 1 and r[1] < y2 and r[3] > y1:
                found.append(f"{kind} line {g['label']!r} crosses bar label {b['label']!r}")
        for t in placed["ticks"]:
            if t["rect"][0] - 1 < x1 < t["rect"][2] + 1:
                found.append(f"{kind} line {g['label']!r} crosses tick {t['label']}")
        for other in placed["gates"] + (placed.get("deadlines") or []):
            r = other["rect"]
            if other is not g and r[0] + 1 < x1 < r[2] - 1 and r[1] < y2 and r[3] > y1:
                found.append(f"{kind} line {g['label']!r} crosses {other.get('kind', 'gate')} {other['label']!r}")
    on_band = [(name, rect) for name, rect in rects if not any(name == f"bar label {b['label']!r}" and b["text"]["where"] == "inside" for b in placed["bars"])]
    for dep in placed["dependencies"]:  # drawn behind the bars: a label inside a bar hides the arrow, one on the band is crossed
        for name, rect in on_band:
            inner = [rect[0] + 1, rect[1] + 1, rect[2] - 1, rect[3] - 1]
            for p, q in zip(dep["points"], dep["points"][1:]):
                box = [min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])]
                if _overlap(box, inner):
                    found.append(f"dependency {dep['from']}->{dep['to']} crosses {name}")
                    break
    region = placed["region"]
    bounds = [region["x"] - 0.5, region["y"] - 0.5, region["x"] + region["w"] + 0.5, region["y"] + region["h"] + 0.5]
    for name, rect in rects:
        if rect[0] < bounds[0] or rect[2] > bounds[2] or rect[1] < bounds[1] or rect[3] > bounds[3]:
            found.append(f"{name} leaves the region")
    if not placed["fits"]:
        found.append(f"does not fit the region at the 14 px floor: needs {placed['needs_h']:.0f} px of height, the region has {region['h']:.0f} - "
                     "shorten labels, merge bars, or give the chart more room")
    return list(dict.fromkeys(found))


def svg_fragment(placed: dict, spec: dict, prefix: str = "tl") -> tuple[str, str]:
    defs, children = svg_parts(placed, spec, prefix)
    return defs, "\n".join([f'<g id="{prefix}" font-family="{escape(placed["font"]["family"], {chr(34): "&quot;"})}">', *children, "</g>"])


def svg_parts(placed: dict, spec: dict, prefix: str = "tl") -> tuple[str, list[str]]:
    """The arrowhead definition and the chart's elements in paint order. Deterministic: the same spec gives the same bytes."""
    colors = {**DEFAULT_COLORS, **(spec.get("colors") or {})}
    colors.setdefault("deadline", colors["gate"])
    font = placed["font"]
    size, lane_px, tick_px = font["label_px"], font["lane_px"], font["tick_px"]
    region = placed["region"]
    chart_x0 = placed["scale"]["x0"]
    chart_x1 = region["x"] + region["w"]
    defs = (f'<marker id="{prefix}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
            f'<polygon points="0,0 10,5 0,10" fill="{colors["dependency"]}"/></marker>')
    out = []
    for i, lane in enumerate(placed["lanes"]):
        if i % 2 == 0:
            out.append(f'<rect id="{prefix}-lane-{escape(str(lane["id"]))}" x="{region["x"]:g}" y="{lane["y"]:g}" width="{region["w"]:g}" height="{lane["h"]:g}" fill="{colors["band"]}"/>')
        # the lane's name starts at its padding (8 px at most): a two-line name stays inside a dense lane, clear of the next band
        base = lane["y"] + min(8.0, placed.get("lane_pad", 8.0)) + 0.5 * lane_px * 1.3 + 0.35 * lane_px
        spans = "".join(f'<tspan x="{region["x"] + 8:g}" dy="{0 if j == 0 else round(lane_px * 1.3, 2):g}">{escape(line)}</tspan>' for j, line in enumerate(lane["label_lines"]))
        out.append(f'<text x="{region["x"] + 8:g}" y="{base:.1f}" font-size="{lane_px:g}" font-weight="bold" fill="{colors["text"]}">{spans}</text>')
    for t in placed["ticks"]:
        tick_x = placed["scale"]["x0"] + (t["unit"] - placed["scale"]["start"]) * placed["scale"]["unit_w"]
        # a short tick on the axis, not a grid line: a line down the lanes would cut every label set beside a bar
        out.append(f'<line x1="{tick_x:.2f}" y1="{placed["axis_y"]:g}" x2="{tick_x:.2f}" y2="{placed["axis_y"] + 5:g}" stroke="{colors["muted"]}" stroke-width="1"/>')
        out.append(f'<text x="{t["x"]:.2f}" y="{t["baseline"]:g}" font-size="{tick_px:g}" text-anchor="middle" fill="{colors["muted"]}">{escape(t["label"])}</text>')
    scale = placed["scale"]
    plan_x1 = round(scale["x0"] + (scale["end"] + 1 - scale["start"]) * scale["unit_w"], 2) if scale.get("extended_to", scale["end"]) > scale["end"] else chart_x1
    out.append(f'<line x1="{chart_x0:g}" y1="{placed["axis_y"]:g}" x2="{plan_x1:g}" y2="{placed["axis_y"]:g}" stroke="{colors["muted"]}" stroke-width="1"/>')
    if plan_x1 < chart_x1:  # the scale runs past the plan to show a deadline: the extension's axis is dashed
        out.append(f'<line id="{prefix}-extension" x1="{plan_x1:g}" y1="{placed["axis_y"]:g}" x2="{chart_x1:g}" y2="{placed["axis_y"]:g}" stroke="{colors["muted"]}" stroke-width="1" stroke-dasharray="3 3"/>')
    for g in placed["gates"]:
        x1, y1, x2, y2 = g["line"]
        out.append(f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{colors["gate"]}" stroke-width="1.5" stroke-dasharray="5 3"/>')
        out.append(f'<text x="{g["text_x"]:.2f}" y="{g["y0"] + 0.5 * size * 1.3 + 0.35 * size:.1f}" font-size="{size:g}" font-weight="bold" fill="{colors["gate"]}">{escape(g["label"])}</text>')
    for i, d in enumerate(placed.get("deadlines") or []):  # a dated solid line, its date and meaning written at its top
        x1, y1, x2, y2 = d["line"]
        out.append(f'<line id="{prefix}-deadline-{i}" x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{colors["deadline"]}" stroke-width="2"/>')
        out.append(f'<text x="{d["text_x"]:.2f}" y="{d["y0"] + 0.5 * size * 1.3 + 0.35 * size:.1f}" font-size="{size:g}" font-weight="bold" fill="{colors["deadline"]}">{escape(d["label"])}</text>')
    for i, dep in enumerate(placed["dependencies"]):
        d = "M" + " L".join(f"{x:g} {y:g}" for x, y in dep["points"])
        out.append(f'<path id="{prefix}-dep-{i}" d="{d}" fill="none" stroke="{colors["dependency"]}" stroke-width="1.3" marker-end="url(#{prefix}-arrow)"/>')
    for b in placed["bars"]:
        fill = colors.get(b["kind"], colors["bar"]) if b["kind"] in ("window", "deliverable") else colors["bar"]
        out.append(f'<rect id="{prefix}-bar-{escape(str(b["id"]))}" x="{b["x0"]:g}" y="{b["y"]:g}" width="{round(b["x1"] - b["x0"], 2):g}" height="{b["h"]:g}" fill="{fill}"/>')
        t = b["text"]
        colour = ("#FFFFFF" if _luminance(fill) < 0.5 else colors["text"]) if t["where"] == "inside" else colors["text"]
        spans = "".join(f'<tspan x="{t["x"]:.2f}" dy="{0 if j == 0 else round(size * 1.3, 2):g}">{escape(line)}</tspan>' for j, line in enumerate(t["lines"]))
        if t["where"] == "left":  # anchored at its end, so the gap to the bar is exactly 6 px whatever the font's real advance
            end_x = t["x"] + t["w"]
            out.append(f'<text x="{end_x:.2f}" y="{t["baselines"][0]:g}" font-size="{size:g}" text-anchor="end" fill="{colour}">{escape(t["lines"][0])}</text>')
        else:
            out.append(f'<text x="{t["x"]:.2f}" y="{t["baselines"][0]:g}" font-size="{size:g}" fill="{colour}">{spans}</text>')
    for m in placed["milestones"]:
        x, y = m["x"], placed["milestone_y"]
        if m["level"] > 0:  # a name that drops a row keeps a leader to its diamond
            out.append(f'<line x1="{x:g}" y1="{y + 7:g}" x2="{x:g}" y2="{m["y0"] + 2:g}" stroke="{colors["muted"]}" stroke-width="0.75"/>')
        out.append(f'<polygon points="{x:g},{y - 7:g} {x + 7:g},{y:g} {x:g},{y + 7:g} {x - 7:g},{y:g}" fill="{colors["milestone"]}"/>')
        style = f'font-weight="bold" fill="{colors["milestone"]}"' if m.get("emphasis") else f'fill="{colors["text"]}"'
        out.append(f'<text x="{m["text_x"]:.2f}" y="{m["y0"] + 0.5 * size * 1.3 + 0.35 * size:.1f}" font-size="{size:g}" {style}>{escape(m["label"])}</text>')
    return defs, out


# --------------------------------------------------------------------------------------------- the chart as a group of the page

def group_digest(inner: str) -> str:
    """sha256 of a group's inner markup, normalised so that re-indenting or re-quoting it does not count as an edit but any change
    to an element, an attribute or a text does: the canonical XML (C14N 2.0, whitespace-only text dropped); markup that does not
    parse is hashed with its whitespace collapsed. page_lint recomputes this to see a hand edit."""
    try:
        canonical = ET.canonicalize(xml_data=f"<g>{inner}</g>", strip_text=True)
    except ET.ParseError:
        canonical = re.sub(r">\s+<", "><", re.sub(r"\s+", " ", inner.strip()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_G_TAG = re.compile(r"<(/?)g\b[^>]*?(/?)>", re.S)
_ATTR = re.compile(r"""([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def find_groups(page: str, group_id: str | None = None, layout: str | None = None) -> list[dict]:
    """Groups of the page by id or by data-layout: [{start, end, open_end, close_start, attrs, inner}], the span covering the whole
    element. Nested groups are matched by counting."""
    found = []
    for match in _G_TAG.finditer(page):
        if match.group(1) or match.group(2):
            continue
        attrs = {m.group(1): m.group(2) if m.group(2) is not None else m.group(3) for m in _ATTR.finditer(match.group(0))}
        if (group_id is not None and attrs.get("id") != group_id) or (layout is not None and attrs.get("data-layout") != layout):
            continue
        depth = 1
        for inner in _G_TAG.finditer(page, match.end()):
            if inner.group(2):
                continue
            depth += -1 if inner.group(1) else 1
            if depth == 0:
                found.append({"start": match.start(), "end": inner.end(), "open_end": match.end(), "close_start": inner.start(),
                              "attrs": attrs, "inner": page[match.end():inner.start()]})
                break
    return found


def spec_text(spec: dict) -> str:
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def page_group(placed: dict, spec: dict, group_id: str, prefix: str, spec_ref: str, spec_sha: str) -> str:
    defs, children = svg_parts(placed, spec, prefix)
    inner = "\n" + "\n".join([f"<defs>{defs}</defs>", *children]) + "\n"
    family = escape(placed["font"]["family"], {'"': "&quot;"})
    region = placed["region"]  # a root module of the page declares its layout box (the contract's data-pptx-bounds)
    bounds = " ".join(f"{float(region[k]):g}" for k in ("x", "y", "w", "h"))
    return (f'<g id="{escape(group_id)}" data-layout="{LAYOUT_ATTR}" data-spec="{escape(spec_ref)}" data-spec-sha="{spec_sha}" '
            f'data-output-sha="{group_digest(inner)}" data-pptx-bounds="{bounds}" font-family="{family}">{inner}</g>')


def write_into(page_path: Path, spec: dict, placed: dict, group_id: str = "timeline", prefix: str | None = None,
               save_spec: Path | None = None) -> dict:
    """Save the spec beside the page and write the chart into the page as one group: replace the group with this id, or insert it
    before `</svg>`. Nothing else in the page changes; the same spec twice gives the same bytes."""
    page_path = Path(page_path)
    text = page_path.read_bytes().decode("utf-8")  # bytes, not read_text: the page's own line endings stay as they are
    save_spec = Path(save_spec) if save_spec else page_path.with_name(f"{page_path.stem}.timeline.json")
    body = spec_text(spec)
    save_spec.parent.mkdir(parents=True, exist_ok=True)
    save_spec.write_text(body, encoding="utf-8", newline="\n")
    spec_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    project = page_path.resolve().parent.parent
    try:
        spec_ref = save_spec.resolve().relative_to(project).as_posix()
    except ValueError:
        spec_ref = Path(os.path.relpath(save_spec.resolve(), page_path.resolve().parent)).as_posix()
    group = page_group(placed, spec, group_id, prefix or group_id, spec_ref, spec_sha)
    existing = find_groups(text, group_id=group_id)
    if existing:
        span = existing[0]
        new = text[:span["start"]] + group + text[span["end"]:]
        action = "replaced"
    else:
        close = text.rfind("</svg>")
        if close < 0:
            raise TimelineError(f"{page_path} has no closing </svg> to insert the chart before")
        new = text[:close] + group + "\n" + text[close:]
        action = "inserted"
    if new != text:
        page_path.write_bytes(new.encode("utf-8"))
    return {"page": str(page_path), "group": group_id, "action": action, "spec": spec_ref, "spec_sha": spec_sha,
            "output_sha": find_groups(new, group_id=group_id)[0]["attrs"]["data-output-sha"]}


def standalone_svg(defs: str, group: str, width: int = 1280, height: int = 720) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
            f'<defs>{defs}</defs>\n<rect width="{width}" height="{height}" fill="#FFFFFF"/>\n{group}\n</svg>\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec")
    parser.add_argument("--svg", help="write a previewable 1280x720 SVG holding the fragment")
    parser.add_argument("--json", help="write the coordinates here instead of stdout")
    parser.add_argument("--prefix", default=None, help="id prefix of the chart's elements (default: tl, or the group id with --into)")
    parser.add_argument("--into", help="write the chart into this page SVG as one group (replacing the group of --group-id, or before </svg>)")
    parser.add_argument("--group-id", default="timeline", help="with --into: the id of the chart's group in the page (default: timeline)")
    parser.add_argument("--save-spec", help="with --into: where to keep the spec (default: beside the page, <stem>.timeline.json)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    try:
        placed = layout(spec)
    except TimelineError as error:
        print(f"timeline_layout: {error}", file=sys.stderr)
        return 2
    prefix = args.prefix or (args.group_id if args.into else "tl")
    defs, group = svg_fragment(placed, spec, prefix)
    if args.into:
        if not Path(args.into).is_file():
            print(f"timeline_layout: no such page: {args.into}", file=sys.stderr)
            return 2
        try:
            written = write_into(Path(args.into), spec, placed, args.group_id, prefix, Path(args.save_spec) if args.save_spec else None)
        except TimelineError as error:
            print(f"timeline_layout: {error}", file=sys.stderr)
            return 2
        if args.json:
            Path(args.json).write_text(json.dumps(placed, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"timeline_layout: {written['action']} group #{written['group']} in {written['page']}; spec kept at {written['spec']} "
              f"(to change the chart, edit that spec and run again with --into - a hand edit inside the group is flagged by the lint)")
    else:
        placed["svg"] = {"defs": defs, "group": group}
        text = json.dumps(placed, indent=1, ensure_ascii=False)
        if args.json:
            Path(args.json).write_text(text, encoding="utf-8")
        else:
            print(text)
    if args.svg:
        Path(args.svg).write_text(standalone_svg(defs, group), encoding="utf-8")
    if args.into:  # the author reads stdout: every remaining collision is listed there, by name
        print(f"timeline_layout: {len(placed['checks'])} check(s) " + ("- none: no label touches another label, a tick, a bar or a line"
                                                                       if not placed["checks"] else "remain - fix them in the spec:"))
        for item in placed["checks"]:
            print(f"  CHECK {item}")
    else:
        for item in placed["checks"]:
            print(f"timeline_layout: CHECK {item}", file=sys.stderr)
    return 0 if placed["fits"] and not placed["checks"] else 3


if __name__ == "__main__":
    sys.exit(main())
