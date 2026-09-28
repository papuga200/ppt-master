#!/usr/bin/env python3
"""Lay out a Gantt chart or timeline from its record: every bar and marker exactly on the scale, every label placed where
it is read, nothing colliding. Emits coordinates and an SVG fragment in the authoring contract.

    timeline_layout.py spec.json [--svg out.svg] [--json out.json] [--prefix tl]

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
    "milestones": [{"at": 10, "label": "Anchor slice"}],
    "gates": [{"at": 4, "label": "Assumptions gate"}],
    "dependencies": [{"from": "charter", "to": "baseline"}],
    "colors": {"bar": "#1F5A8A", "window": "#C9D6E3", "deliverable": "#B4162E", "text": "#15181E", "muted": "#5B616C",
               "band": "#F3F4F6", "grid": "#D9DCE1", "gate": "#B4162E", "milestone": "#15181E", "dependency": "#15181E"}
  }

Output: JSON with every element's rectangle, `fits`, and `checks` (label/label and label/bar collisions, arrows through
labels, anything outside the region); with --svg a previewable 1280x720 SVG holding the fragment. Bars are `<rect>` with
their label `<text>` drawn after them and inside them where it fits, so the export puts the label in the bar's own text
frame. A legend, if you add one, explains the symbols only (a diamond is a milestone, a dashed line a gate, an arrow a
dependency) - every name is already on the chart.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
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
DEFAULT_COLORS = {"bar": "#1F5A8A", "window": "#C9D6E3", "deliverable": "#B4162E", "text": "#15181E", "muted": "#5B616C",
                  "band": "#F3F4F6", "grid": "#D9DCE1", "gate": "#B4162E", "milestone": "#15181E", "dependency": "#15181E"}
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


def thin_ticks(scale: Scale, unit: str, prefix: str, size: float, family: str) -> tuple[int, list[dict]]:
    """The smallest regular step at which no two tick labels collide (and the last label never collides with its neighbour)."""
    for step in NICE_STEPS.get(unit, NICE_STEPS["week"]) + (scale.end - scale.start + 1,):
        units = list(range(scale.start, scale.end + 1, step))
        ticks = []
        for u in units:
            label = f"{prefix}{u}"
            w = _width(label, size, family)
            centre = scale.x(u + 0.5)
            ticks.append({"unit": u, "label": label, "x": centre, "w": w, "rect": [centre - w / 2, 0, centre + w / 2, 1]})
        if all(b["rect"][0] - a["rect"][2] >= 8 for a, b in zip(ticks, ticks[1:])):
            return step, ticks
    return scale.end - scale.start + 1, ticks[:1]


def place_bar_label(bar: dict, label_w: float, size: float, chart: tuple[float, float], family: str, lines_limit_w: float,
                    gate_xs: tuple = (), forbid: tuple = ()) -> dict:
    """inside | right | left | above, by the rules of consulting-typesetting.md §6. A label beside its bar never sits across a
    gate's line, never on the side an arrow leaves (a dependency's source) or arrives (its target)."""
    x0, x1 = bar["x0"], bar["x1"]
    if label_w + 2 * PAD_IN <= x1 - x0:
        return {"where": "inside", "lines": [bar["label"]], "w": label_w, "x": x0 + PAD_IN}
    clear = lambda a, b: not any(a - 3 <= g <= b + 3 for g in gate_xs)  # noqa: E731
    right, left = x1 + GAP_BESIDE, x0 - GAP_BESIDE - label_w
    if "right" not in forbid and right + label_w <= chart[1] and clear(right, right + label_w):
        return {"where": "right", "lines": [bar["label"]], "w": label_w, "x": right}
    if "left" not in forbid and left >= chart[0] and clear(left, left + label_w):
        return {"where": "left", "lines": [bar["label"]], "w": label_w, "x": left}
    room = max(lines_limit_w, 120.0)
    lines, width = _wrap(bar["label"], size, room, family)
    # above the bar, starting over it: at its start, or just past a gate line that would cut the name
    starts = [x0] + [g + 4 for g in gate_xs if x0 <= g + 4 <= max(x0, x1 - 12)] + [x1 - width]
    starts = [max(chart[0], min(x, chart[1] - width)) for x in starts]
    x = next((x for x in starts if clear(x, x + width) and x <= x1 and x + width >= x0), starts[0])
    return {"where": "above", "lines": lines, "w": width, "x": x}


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
    scale = Scale(start, end, chart_x0, chart_x1 - chart_x0, horizon.get("marker_at", "end"))
    line_h = round(size * 1.3, 2)

    gate_xs = tuple(round(scale.marker(g["at"]), 2) for g in spec.get("gates") or [])
    sources = {d.get("from") for d in spec.get("dependencies") or []}
    targets = {d.get("to") for d in spec.get("dependencies") or []}
    bars_by_id: dict[str, dict] = {}
    lanes_out = []
    for lane_index, lane in enumerate(spec.get("lanes") or []):
        lane_lines, _ = _wrap(lane.get("label", ""), font["lane_px"], lane_label_w - 16, family, "bold")
        placed_bars = []
        for bar_index, bar in enumerate(lane.get("bars") or []):
            if bar["end"] < bar["start"] or bar["start"] < start or bar["end"] > end:
                raise TimelineError(f"bar {bar.get('label')!r} ({bar['start']}-{bar['end']}) is outside the horizon {start}-{end}")
            x0, x1 = scale.bar(bar["start"], bar["end"])
            item = {"id": bar.get("id") or f"{lane.get('id', lane_index)}.{bar_index}", "lane": lane_index, "label": bar.get("label", ""),
                    "kind": bar.get("kind", "task"), "start": bar["start"], "end": bar["end"], "x0": round(x0, 2), "x1": round(x1, 2)}
            forbid = tuple(side for side, ends in (("right", sources), ("left", targets)) if item["id"] in ends)
            label = place_bar_label(item, _width(item["label"], size, family), size, (chart_x0, chart_x1), family, x1 - x0, gate_xs, forbid)
            item["text"] = label
            lo = min(x0, label["x"]) if label["where"] != "inside" else x0
            hi = max(x1, label["x"] + label["w"]) if label["where"] != "inside" else x1
            item["footprint"] = (lo, hi)
            placed_bars.append(item)
            bars_by_id[item["id"]] = item
        # pack bars into rows: nothing (bar or its label) shares a row with something it would touch
        rows: list[list[dict]] = []
        for item in sorted(placed_bars, key=lambda b: (b["x0"], b["x1"])):
            for row in rows:
                if all(item["footprint"][0] >= other["footprint"][1] + ITEM_GAP or item["footprint"][1] + ITEM_GAP <= other["footprint"][0] for other in row):
                    row.append(item)
                    break
            else:
                rows.append([item])
        lanes_out.append({"index": lane_index, "id": lane.get("id", str(lane_index)), "label": lane.get("label", ""), "label_lines": lane_lines, "rows": rows})

    # markers along the top (gates) and the bottom (milestones): names at their markers, stacked only where they would collide
    def stack(items: list[dict], kind: str) -> int:
        """Names at their markers, in as few rows as possible. A gate's name starts at its dashed line (the line hangs from
        under the name); a milestone's name is centred under its diamond (else set just after or before it), joined by a
        leader when it drops a row. No name sits across another marker's line or leader, or on another name."""
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

        for item in sorted(items, key=lambda m: m["x"]):
            w = _width(item["label"], size, family)
            after = item["x"] + 4 if item["x"] + 4 + w <= chart_x1 else item["x"] - 4 - w
            before = item["x"] - 4 - w if item["x"] - 4 - w >= chart_x0 else after
            if kind == "gate":
                options = [after, before]
            else:
                options = [min(max(item["x"] - w / 2, chart_x0), chart_x1 - w), after, before]
            choice = None
            for level in range(8):
                for x in options:
                    if not clashes(item, (x, x + w), level):
                        choice = (x, level)
                        break
                if choice:
                    break
            if choice is None:  # nowhere clean within eight rows: take the next free row and let the check report it
                choice = (options[0], 1 + max((o["level"] for o in placed_items), default=-1))
            x, level = choice
            item.update(level=level, text_x=x, text_w=w, _span=(x, x + w))
            placed_items.append(item)
        for item in placed_items:
            item.pop("_span", None)
        return 1 + max((item["level"] for item in placed_items), default=-1)

    gates = [{"at": g["at"], "label": g.get("label", ""), "x": round(scale.marker(g["at"]), 2)} for g in spec.get("gates") or []]
    milestones = [{"at": m["at"], "label": m.get("label", ""), "x": round(scale.marker(m["at"]), 2)} for m in spec.get("milestones") or []]
    gate_levels = stack(gates, "gate") if gates else 0
    milestone_levels = stack(milestones, "milestone") if milestones else 0
    step, ticks = thin_ticks(scale, unit, prefix, font["tick_px"], family)
    ticks = [t for t in ticks if not any(t["rect"][0] - 3 <= g["x"] <= t["rect"][2] + 3 for g in gates)]  # a gate's line runs through the ruler

    # vertical budget: the most generous spacing that fits, never smaller type
    def lane_height(lane: dict, pad: float, bar_h: float, row_gap: float) -> float:
        rows_h = sum(bar_h + max((len(b["text"]["lines"]) for b in row if b["text"]["where"] == "above"), default=0) * line_h for row in lane["rows"])
        rows_h += row_gap * max(0, len(lane["rows"]) - 1)
        label_h = len(lane["label_lines"]) * font["lane_px"] * 1.3
        return max(rows_h, label_h) + 2 * pad

    header = gate_levels * line_h + (6 if gates else 0) + font["tick_px"] * 1.4 + 8
    footer = (28 + milestone_levels * line_h) if milestones else 0
    bar_h = row_gap = pad = total = 0.0
    fits = False
    for bar_h, row_gap, pad in ((max(26.0, size + 12), 6.0, 8.0), (max(24.0, size + 10), 5.0, 6.0), (max(22.0, size + 8), 4.0, 4.0)):
        total = header + sum(lane_height(lane, pad, bar_h, row_gap) for lane in lanes_out) + footer
        if total <= region["h"] + 0.5:
            fits = True
            break
    if fits and lanes_out:  # give spare height to the lanes (up to 10 px more padding each) so the chart fills its region
        pad += max(0.0, min(10.0, (region["h"] - total) / (2 * len(lanes_out))))
        total = header + sum(lane_height(lane, pad, bar_h, row_gap) for lane in lanes_out) + footer

    y = region["y"]
    gate_top = y
    y += gate_levels * line_h + (6 if gates else 0)
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
    for g in gates:
        g["y0"] = round(gate_top + g["level"] * line_h, 2)
        g["rect"] = [round(g["text_x"], 2), g["y0"], round(g["text_x"] + g["text_w"], 2), round(g["y0"] + line_h, 2)]
        g["line"] = [g["x"], round(gate_top + g["level"] * line_h + line_h, 2), g["x"], round(lanes_bottom, 2)]
    for t in ticks:
        t["rect"] = [round(t["rect"][0], 2), round(tick_base - font["tick_px"], 2), round(t["rect"][2], 2), round(tick_base + 0.3 * font["tick_px"], 2)]
        t["baseline"] = round(tick_base, 2)

    # dependencies: finish-to-start arrows. The vertical run goes where it crosses the fewest bars and labels; when the next
    # task starts before this one ends, the route drops into the gap under the source row and comes back to the target's start
    # arrows are drawn behind the bars, so passing under a bar costs little; crossing a label that sits on the band costs a lot
    obstacles = [([b["x0"], b["y"], b["x1"], b["y"] + b["h"]], 1) for b in out_bars] +                 [(b["text"]["rect"], 10) for b in out_bars if b["text"]["where"] != "inside"] +                 [(m["rect"], 10) for m in milestones] + [(g["rect"], 10) for g in gates]

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
                                           "marker_at": scale.marker_at, "tick_step": step},
              "font": font, "fits": fits, "needs_h": round(total, 1), "axis_y": round(axis_y, 2), "lanes_top": round(lanes_top, 2),
              "lanes_bottom": round(lanes_bottom, 2), "milestone_y": milestone_y,
              "lanes": [{k: v for k, v in lane.items() if k != "rows"} | {"rows": len(lane["rows"])} for lane in lanes_out],
              "bars": [{k: v for k, v in b.items() if k != "footprint"} for b in out_bars],
              "ticks": ticks, "gates": gates, "milestones": milestones, "dependencies": deps}
    placed["checks"] = checks(placed)
    return placed


def label_rects(placed: dict) -> list[tuple[str, list]]:
    rects = [(f"tick {t['label']}", t["rect"]) for t in placed["ticks"]]
    rects += [(f"bar label {b['label']!r}", b["text"]["rect"]) for b in placed["bars"]]
    rects += [(f"gate {g['label']!r}", g["rect"]) for g in placed["gates"]]
    rects += [(f"milestone {m['label']!r}", m["rect"]) for m in placed["milestones"]]
    return rects


def checks(placed: dict) -> list[str]:
    found = []
    rects = label_rects(placed)
    for i, (name_a, a) in enumerate(rects):
        for name_b, b in rects[i + 1:]:
            if _overlap(a, b, -0.5):
                found.append(f"{name_a} overlaps {name_b}")
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
    for g in placed["gates"]:
        x1, y1, x2, y2 = g["line"]
        for b in placed["bars"]:
            r = b["text"]["rect"]
            if b["text"]["where"] != "inside" and r[0] + 1 < x1 < r[2] - 1 and r[1] < y2 and r[3] > y1:
                found.append(f"gate line {g['label']!r} crosses bar label {b['label']!r}")
        for t in placed["ticks"]:
            if t["rect"][0] - 1 < x1 < t["rect"][2] + 1:
                found.append(f"gate line {g['label']!r} crosses tick {t['label']}")
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
    colors = {**DEFAULT_COLORS, **(spec.get("colors") or {})}
    font = placed["font"]
    size, lane_px, tick_px = font["label_px"], font["lane_px"], font["tick_px"]
    region = placed["region"]
    chart_x0 = placed["scale"]["x0"]
    chart_x1 = region["x"] + region["w"]
    defs = (f'<marker id="{prefix}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
            f'<polygon points="0,0 10,5 0,10" fill="{colors["dependency"]}"/></marker>')
    out = [f'<g id="{prefix}" font-family="{escape(font["family"])}">']
    for i, lane in enumerate(placed["lanes"]):
        if i % 2 == 0:
            out.append(f'<rect id="{prefix}-lane-{escape(str(lane["id"]))}" x="{region["x"]:g}" y="{lane["y"]:g}" width="{region["w"]:g}" height="{lane["h"]:g}" fill="{colors["band"]}"/>')
        base = lane["y"] + 8 + 0.5 * lane_px * 1.3 + 0.35 * lane_px
        spans = "".join(f'<tspan x="{region["x"] + 8:g}" dy="{0 if j == 0 else round(lane_px * 1.3, 2):g}">{escape(line)}</tspan>' for j, line in enumerate(lane["label_lines"]))
        out.append(f'<text x="{region["x"] + 8:g}" y="{base:.1f}" font-size="{lane_px:g}" font-weight="bold" fill="{colors["text"]}">{spans}</text>')
    for t in placed["ticks"]:
        tick_x = placed["scale"]["x0"] + (t["unit"] - placed["scale"]["start"]) * placed["scale"]["unit_w"]
        # a short tick on the axis, not a grid line: a line down the lanes would cut every label set beside a bar
        out.append(f'<line x1="{tick_x:.2f}" y1="{placed["axis_y"]:g}" x2="{tick_x:.2f}" y2="{placed["axis_y"] + 5:g}" stroke="{colors["muted"]}" stroke-width="1"/>')
        out.append(f'<text x="{t["x"]:.2f}" y="{t["baseline"]:g}" font-size="{tick_px:g}" text-anchor="middle" fill="{colors["muted"]}">{escape(t["label"])}</text>')
    out.append(f'<line x1="{chart_x0:g}" y1="{placed["axis_y"]:g}" x2="{chart_x1:g}" y2="{placed["axis_y"]:g}" stroke="{colors["muted"]}" stroke-width="1"/>')
    for g in placed["gates"]:
        x1, y1, x2, y2 = g["line"]
        out.append(f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{colors["gate"]}" stroke-width="1.5" stroke-dasharray="5 3"/>')
        out.append(f'<text x="{g["text_x"]:.2f}" y="{g["y0"] + 0.5 * size * 1.3 + 0.35 * size:.1f}" font-size="{size:g}" font-weight="bold" fill="{colors["gate"]}">{escape(g["label"])}</text>')
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
        out.append(f'<text x="{m["text_x"]:.2f}" y="{m["y0"] + 0.5 * size * 1.3 + 0.35 * size:.1f}" font-size="{size:g}" fill="{colors["text"]}">{escape(m["label"])}</text>')
    out.append("</g>")
    return defs, "\n".join(out)


def standalone_svg(defs: str, group: str, width: int = 1280, height: int = 720) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
            f'<defs>{defs}</defs>\n<rect width="{width}" height="{height}" fill="#FFFFFF"/>\n{group}\n</svg>\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec")
    parser.add_argument("--svg", help="write a previewable 1280x720 SVG holding the fragment")
    parser.add_argument("--json", help="write the coordinates here instead of stdout")
    parser.add_argument("--prefix", default="tl")
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
    defs, group = svg_fragment(placed, spec, args.prefix)
    placed["svg"] = {"defs": defs, "group": group}
    text = json.dumps(placed, indent=1, ensure_ascii=False)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.svg:
        Path(args.svg).write_text(standalone_svg(defs, group), encoding="utf-8")
    for item in placed["checks"]:
        print(f"timeline_layout: CHECK {item}", file=sys.stderr)
    return 0 if placed["fits"] and not placed["checks"] else 3


if __name__ == "__main__":
    sys.exit(main())
