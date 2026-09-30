#!/usr/bin/env python3
"""
PPT Master - Experimental dense timeline layout (SVG helpers experiment, round 2)

A layout engine for one-slide Gantt charts at the confirmed label floor (13.33 px), written in the adapter layer. It takes
the ideas of the fork's timeline_layout.py (scale arithmetic, label beside/inside, packing, orthogonal dependency
routing) and adds what dense plans need, never dropping, merging, abbreviating or shrinking anything:
- bar labels inside (one or two lines), or beside on the same row (right or left, one or two lines);
- lane-bound point events (e.g. steering updates) packed in their lane's rows with their names beside the marker;
- gate names stacked above the ruler and milestone names stacked below the lanes, each wrapped to 1-3 lines, placed so
  that no gate line and no milestone leader passes through any name (constraint checked while placing);
- gate lines drawn as segments that stop at every label they would cross (the line passes "behind" the label);
- shaded windows and dashed beyond-horizon spans, named in the header stack; dependencies between any two items
  (bar, event, milestone, gate);
- a density search (row gap, lane padding, rail width) from generous to dense; when nothing fits the region the best
  draft is still laid out and the binding constraint is reported (required vs available height, per-part breakdown).

Library module used by build_timeline.py (engine "dense"); no CLI of its own.

Dependencies:
    Standard library; timeline_fonts.py (Pillow for real metrics)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

ENGINE = "exp_svg.dense_layout"
ENGINE_VERSION = "0.4.0"
LINE = 1.3             # line height / font size for labels (the fork lint's multi-line floor is 1.28 x: TIGHT_LEADING)
GAP_BESIDE = 6.0       # a beside label starts this far from its bar or marker
ITEM_GAP = 8.0         # horizontal gap between two footprints sharing a row
NAME_GAP = 8.0         # horizontal gap between two stacked names
LINE_CLEAR = 3.0
LEADER_SIDE_CLEAR = 14.0  # a strip name keeps this far from another milestone's leader (else it reads as that one's)
MARKER_R = 6.0         # half-size of a milestone diamond
EVENT_R = 5.5          # half-size of a lane event triangle
ABOVE_CLEAR = 6.0      # a name set above its bar keeps this much more room from the row above than from its own bar
ENDPOINT_CLEAR = 14.0  # a dependency never starts or ends this close to a marker that is not its own end (it would read as attached)
DEFAULT_COLORS = {"bar": "#1F5A8A", "bar_text": "#FFFFFF", "text": "#15181E", "muted": "#5B616C", "band": "#F3F4F6",
                  "rail_text": "#15181E", "gate": "#B4162E", "milestone": "#15181E", "focal": "#F2A31B", "event": "#5B616C",
                  "dependency": "#15181E", "window": "#E6E2DA", "float": "#9A958D", "axis": "#9A958D", "leader": "#9A958D"}


# ------------------------------------------------------------------------------------------------ model

@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    def overlaps(self, other: "Box", gx: float = 0.0, gy: float = 0.0) -> bool:
        return self.x0 < other.x1 + gx and other.x0 < self.x1 + gx and self.y0 < other.y1 + gy and other.y0 < self.y1 + gy

    def list(self) -> list:
        return [round(self.x0, 2), round(self.y0, 2), round(self.x1, 2), round(self.y1, 2)]


@dataclass
class Label:
    lines: list
    w: float
    where: str            # inside | right | left | below | above (for stacked names: right | left | centre)
    x: float = 0.0        # left edge of the text block
    y0: float = 0.0       # top of the text block
    size: float = 14.0
    weight: str = "normal"
    gap: float = GAP_BESIDE  # distance from its bar or marker, for a label set beside it
    rot: bool = False     # set reading upward (rotated -90 degrees): w is the block's width on the slide, span its height
    span: float = 0.0

    @property
    def h(self) -> float:
        return self.span if self.rot else len(self.lines) * self.size * LINE

    def box(self) -> Box:
        return Box(self.x, self.y0, self.x + self.w, self.y0 + self.h)


@dataclass
class Item:
    id: str
    kind: str             # task | event | milestone | gate | window
    name: str
    lane: str | None = None
    d0: float = 0.0       # day offset of the start (tasks, windows) or the point (markers, gates)
    d1: float = 0.0       # day offset of the exclusive end
    style: dict = field(default_factory=dict)
    x0: float = 0.0
    x1: float = 0.0
    y: float = 0.0        # bar top / marker centre
    h: float = 0.0
    label: Label | None = None
    row: int = -1
    level_top: float = 0.0


# ------------------------------------------------------------------------------------------------ helpers

class Metrics:
    def __init__(self, fm) -> None:
        self.fm = fm
        self._cache: dict = {}

    def width(self, text: str, size: float, weight: str = "normal") -> float:
        key = (text, size, weight)
        if key not in self._cache:
            self._cache[key] = self.fm.width(text, size, weight)
        return self._cache[key]

    def wrap(self, text: str, size: float, max_w: float, weight: str = "normal") -> tuple[list, float]:
        return self.fm.wrap(text, size, max_w, weight)

    def wraps(self, text: str, size: float, max_lines: int, weight: str = "normal", min_w: float = 40.0) -> list:
        """Distinct wrappings of text into 1..max_lines lines (narrowest first for each line count), never cutting a word."""
        key = ("wraps", text, size, max_lines, weight, min_w)
        if key not in self._cache:
            self._cache[key] = self._wraps(text, size, max_lines, weight, min_w)
        return self._cache[key]

    def _wraps(self, text: str, size: float, max_lines: int, weight: str, min_w: float) -> list:
        full = self.width(text, size, weight)
        out = [([text], full)]
        words = text.split()
        for n in range(2, max_lines + 1):
            if len(words) < n:
                break
            target = max(min_w, full / n)
            best = None
            w = target
            while w <= full:
                lines, lw = self.wrap(text, size, w, weight)
                if len(lines) <= n:
                    best = (lines, lw)
                    break
                w += 4
            if best and len(best[0]) == n and all(best[1] < o[1] - 1 for o in out):
                out.append(best)
        return out


def _clear_of(x: float, box: Box, pad: float = LINE_CLEAR) -> bool:
    return not (box.x0 - pad <= x <= box.x1 + pad)


# ------------------------------------------------------------------------------------------------ the engine

class DenseLayout:
    def __init__(self, spec: dict, fm) -> None:
        self.spec = spec
        self.m = Metrics(fm)
        font = spec["font"]
        self.family = font["family"]
        self.size = float(font["label_px"])
        self.lane_px = float(font["lane_px"])
        self.tick_px = float(font["tick_px"])
        self.pad_x = float(spec.get("bar_pad_x", 8.0))
        self.pad_y = float(spec.get("bar_pad_y", 4.0))
        self.max_lines = int(spec.get("name_max_lines", 3))
        self.region = spec["region"]
        self.colors = {**DEFAULT_COLORS, **(spec.get("colors") or {})}
        self.days = float(spec["days"])           # horizon length in days
        self.extent_days = float(spec["extent_days"])  # scale length (>= horizon when items lie beyond it)
        self.line_h = self.size * LINE
        self.thin = spec.get("bar_mode") == "thin"   # thin bars: every label beside (or above) its bar, rows one text line high
        self.thin_h = float(spec.get("bar_h_thin", 10.0))
        self.legend_mode = "bottom"
        self.straddle_first = False  # set by solve() when the chosen layout has height to spare
        self.above_clear: dict = {}  # id(row) -> extra room above a name set over its bar (a bar just above it would claim it)

    # ---------------------------------------------------------------- scale
    def x(self, day: float) -> float:
        return self.chart_x0 + day * self.px_day

    def label_right(self) -> float:
        """Lane labels end at the plan horizon when a dashed span lies beyond it (the float box keeps a clean border)."""
        return self.x(self.days) if self.extent_days > self.days + 0.01 else self.chart_x1

    def set_scale(self, rail_w: float) -> None:
        r = self.region
        self.rail_w = rail_w
        self.chart_x0 = r["x"] + rail_w + 8
        self.chart_x1 = r["x"] + r["w"]
        self.px_day = (self.chart_x1 - self.chart_x0) / self.extent_days

    # ---------------------------------------------------------------- items
    def build_items(self) -> None:
        s = self.spec
        self.lanes = [{"id": l["id"], "name": l["name"]} for l in s["lanes"]]
        self.tasks = [Item(t["id"], "task", t["name"], t["lane"], t["d0"], t["d1"], t.get("style") or {}) for t in s["tasks"]]
        self.events, self.milestones, self.gates = [], [], []
        for mk in s["markers"]:
            item = Item(mk["id"], mk["kind"], mk["name"], mk.get("lane"), mk["d"], mk["d"], mk.get("style") or {})
            {"event": self.events, "milestone": self.milestones, "gate": self.gates}[mk["kind"]].append(item)
        self.windows = [Item(w["id"], "window", w["name"], None, w["d0"], w["d1"], w.get("style") or {}) for w in s.get("windows") or []]
        self.by_id = {i.id: i for i in self.tasks + self.events + self.milestones + self.gates + self.windows}
        self.dep_sources = {d["from"] for d in s.get("dependencies") or []}
        self.dep_targets = {d["to"] for d in s.get("dependencies") or []}

    # ---------------------------------------------------------------- lane packing
    def lane_options(self, it: Item, chart_left: float, chart_right: float) -> list:
        """(label, footprint x0, x1, lines) options in preference order: one-line options first (cached per scale)."""
        key = (it.id, round(chart_left, 3), round(chart_right, 3), round(self.px_day, 6), self.size)
        cache = self.__dict__.setdefault("_opt_cache", {})
        if key not in cache:
            cache[key] = self._lane_options(it, chart_left, chart_right)
        it.x0, it.x1 = (self.x(it.d0), self.x(it.d1)) if it.kind == "task" else (self.x(it.d0), self.x(it.d0))
        return [(Label(list(l.lines), l.w, l.where, size=l.size, weight=l.weight, gap=l.gap), a, b, n) for l, a, b, n in cache[key]]

    def _straddles(self, it: Item, lab: Label) -> int:
        """1 when a label outside its bar would sit half on a shaded window column and half off it (an edge of the column
        runs through the text); such a placement is taken only when no alternative of equal or lower height exists."""
        if it.kind == "task" and lab.where == "inside":
            return 0
        if it.kind == "task":
            x0 = {"right": self.x(it.d1) + lab.gap, "left": self.x(it.d0) - lab.gap - lab.w}.get(lab.where)
            if x0 is None:  # above: starts over the bar, clamped to the chart
                x0 = min(max(self.x(it.d0), self.chart_x0), self.label_right() - lab.w)
        else:
            mx = self.x(it.d0)
            x0 = mx + EVENT_R + lab.gap if lab.where == "right" else mx - EVENT_R - lab.gap - lab.w
        x1 = x0 + lab.w
        for w in self.windows:
            if w.style.get("dashed"):
                continue
            for edge in (self.x(w.d0), self.x(w.d1)):
                if x0 + 1 < edge < x1 - 1:
                    return 1
        return 0

    def _lane_options(self, it: Item, chart_left: float, chart_right: float) -> list:
        size = self.size
        opts = []
        if it.kind == "task":
            it.x0, it.x1 = self.x(it.d0), self.x(it.d1)
            bar_w = it.x1 - it.x0
            one = self.m.width(it.name, size)
            forbid_right = it.id in self.dep_sources
            forbid_left = it.id in self.dep_targets
            if not self.thin and one + 2 * self.pad_x <= bar_w:
                opts.append((Label([it.name], one, "inside", size=size), it.x0, it.x1, 1))
            for lines, w in self.m.wraps(it.name, size, self.max_lines):
                n = len(lines)
                if not self.thin and n > 1 and w + 2 * self.pad_x <= bar_w:
                    opts.append((Label(lines, w, "inside", size=size), it.x0, it.x1, n))
                if not forbid_right and it.x1 + GAP_BESIDE + w <= chart_right:
                    opts.append((Label(lines, w, "right", size=size), it.x0, it.x1 + GAP_BESIDE + w, n))
                if not forbid_left and it.x0 - GAP_BESIDE - w >= chart_left:
                    opts.append((Label(lines, w, "left", size=size), it.x0 - GAP_BESIDE - w, it.x1, n))
                # above the bar in its own row, starting over the bar (last resort: costs a label line of height)
                lx = min(max(it.x0, chart_left), chart_right - w)
                if lx >= chart_left - 0.5:
                    opts.append((Label(lines, w, "above", size=size), min(lx, it.x0), max(lx + w, it.x1), n + 1))
        else:  # lane event: a marker with its name beside it
            it.x0 = it.x1 = self.x(it.d0)
            for lines, w in self.m.wraps(it.name, size, self.max_lines):
                n = len(lines)
                if it.x0 + EVENT_R + GAP_BESIDE + w <= chart_right:
                    opts.append((Label(lines, w, "right", size=size), it.x0 - EVENT_R, it.x0 + EVENT_R + GAP_BESIDE + w, n))
                if it.x0 - EVENT_R - GAP_BESIDE - w >= chart_left:
                    opts.append((Label(lines, w, "left", size=size), it.x0 - EVENT_R - GAP_BESIDE - w, it.x0 + EVENT_R, n))
        opts = [self._nudge(it, o, chart_left, chart_right) for o in opts]
        opts.sort(key=lambda o: (o[3], self._straddles(it, o[0]), {"inside": 0, "right": 1, "left": 2, "above": 3}[o[0].where]))
        return opts

    def _nudge(self, it: Item, opt: tuple, chart_left: float, chart_right: float) -> tuple:
        """A beside label that would cross a shaded window's edge by at most 3 px moves just clear of it, keeping its distance
        from its own bar or marker between 3 and 10 px (still read as beside it)."""
        lab, fx0, fx1, n = opt
        if lab.where not in ("right", "left") or not self._straddles(it, lab):
            return opt
        near = (self.x(it.d1) if it.kind == "task" else self.x(it.d0) + EVENT_R) if lab.where == "right" else                (self.x(it.d0) if it.kind == "task" else self.x(it.d0) - EVENT_R)
        for w in self.windows:
            if w.style.get("dashed"):
                continue
            for edge in (self.x(w.d0), self.x(w.d1)):
                x0 = near + lab.gap if lab.where == "right" else near - lab.gap - lab.w
                x1 = x0 + lab.w
                if not (x0 + 1 < edge < x1 - 1):
                    continue
                for shift in ((edge + 1.5) - x0, (edge - 1.5) - x1):  # move the label's start past the edge, or its end before it
                    if abs(shift) > 3.0:
                        continue
                    gap = lab.gap + shift if lab.where == "right" else lab.gap - shift
                    if 3.0 <= gap <= 10.0:
                        moved = Label(list(lab.lines), lab.w, lab.where, size=lab.size, weight=lab.weight, gap=gap)
                        if not self._straddles(it, moved):
                            nx0 = near + gap if lab.where == "right" else near - gap - lab.w
                            if chart_left <= nx0 and nx0 + lab.w <= chart_right:
                                span0, span1 = (fx0, nx0 + lab.w) if lab.where == "right" else (nx0, fx1)
                                return moved, span0, span1, n
        return opt

    def pack_lane_best(self, lane_id: str, items: list, chart_left: float, chart_right: float) -> list:
        """The packing with the least lane height over item orders (every order up to 6 items, else heuristics plus a
        deterministic sample); rows are then ordered by their earliest start (reading order)."""
        import itertools
        import random
        key = (lane_id, round(chart_left, 3), round(self.px_day, 6), self.size, self.straddle_first)
        cache = self.__dict__.setdefault("_pack_cache", {})
        if key in cache:
            return cache[key]
        orders = [sorted(items, key=lambda i: (i.d0, -(i.d1 - i.d0), i.id)), sorted(items, key=lambda i: (-(i.d1 - i.d0), i.d0, i.id))]
        if len(items) <= 6:
            orders += [list(p) for p in itertools.permutations(items)]
        else:
            rng = random.Random(7)
            for _ in range(600):
                o = list(items)
                rng.shuffle(o)
                orders.append(o)
        best = None
        for o in orders:
            rows = self.pack_lane(o, chart_left, chart_right)
            score = (sum(self.row_height(r) for r in rows) + 3 * len(rows),
                     sum(self._straddles(it, lab) for r in rows for it, lab, *_ in r), sum(n for r in rows for *_, n in r))
            if self.straddle_first:
                score = (score[1], score[0], score[2])
            if best is None or score < best[0]:
                best = (score, rows)
        rows = sorted(best[1], key=lambda r: min(it.d0 for it, *_ in r))
        cache[key] = rows
        return rows

    def pack_lane(self, keyed: list, chart_left: float, chart_right: float) -> list:
        """Rows of (item, label, footprint x0, x1, lines) for items in the given order. Each item takes, over every existing
        row and every label option (and a new row as the last resort), the placement that adds the least height; ties go
        to a label that does not straddle a shaded window's edge, then to the earlier row, fewer lines, inside/right/left."""
        rows: list = []
        where_rank = {"inside": 0, "right": 1, "left": 2, "above": 3}
        for it in keyed:
            opts = self.lane_options(it, chart_left, chart_right)
            if not opts:  # wider than the chart even wrapped: take the narrowest wrap on the right, the check reports it
                lines, w = self.m.wraps(it.name, self.size, self.max_lines)[-1]
                opts = [(Label(lines, w, "right", size=self.size), it.x0, it.x1 + GAP_BESIDE + w, len(lines))]
            best = None
            for ri, row in enumerate(rows + [[]]):
                current = self.row_height(row) if row else 0.0
                for lab, fx0, fx1, n in opts:
                    if row and not all(fx0 >= o[3] + ITEM_GAP or fx1 + ITEM_GAP <= o[2] for o in row):
                        continue
                    grow = self.row_height(row + [(it, lab, fx0, fx1, n)]) - current
                    key = (round(grow, 2), self._straddles(it, lab), ri, n, where_rank[lab.where])
                    if self.straddle_first:  # spending spare height: a clean placement first, then the least growth
                        key = (self._straddles(it, lab),) + key
                    if best is None or key < best[0]:
                        best = (key, ri, (it, lab, fx0, fx1, n))
            _, ri, entry = best
            if ri == len(rows):
                rows.append([entry])
            else:
                rows[ri].append(entry)
        # second pass: a label that straddles a window edge takes another option in its own row when that fits and does not
        # make the row taller (items placed later may have made the row taller than when this one was placed)
        for row in rows:
            height = self.row_height(row)
            for idx, (it, lab, fx0, fx1, n) in enumerate(list(row)):
                if not self._straddles(it, lab):
                    continue
                others = row[:idx] + row[idx + 1:]
                for alt, ax0, ax1, an in self.lane_options(it, chart_left, chart_right):
                    if self._straddles(it, alt) or not all(ax0 >= o[3] + ITEM_GAP or ax1 + ITEM_GAP <= o[2] for o in others):
                        continue
                    trial = others[:idx] + [(it, alt, ax0, ax1, an)] + others[idx:]
                    if self.row_height(trial) <= height + 0.01:
                        row[idx] = (it, alt, ax0, ax1, an)
                        break
        return rows

    def bar_h(self) -> float:
        return self.thin_h if self.thin else self.line_h + 2 * self.pad_y

    def row_height(self, row: list) -> float:
        bar_h = self.bar_h()
        h = bar_h
        for it, lab, _, _, n in row:
            if it.kind == "task" and lab.where == "inside":
                h = max(h, n * self.line_h + 2 * self.pad_y)
            elif it.kind == "task" and lab.where == "above":
                h = max(h, self.above_clear.get(id(row), 0.0) + len(lab.lines) * self.line_h + 2 + bar_h)
            else:
                h = max(h, n * self.line_h)
        return h

    # ---------------------------------------------------------------- stacked names (header above the ruler, strip below)
    def stack(self, entries: list, upward: bool) -> float:
        """Place names in a skyline away from the axis. entry: dict(item, anchor x, options[(label, x_left)], line: bool).
        A gate's line (upward) or a milestone's leader (downward) runs from the axis to its name; no such line may pass
        through another name, and no two names may overlap. Returns the stack depth (px from the axis)."""
        import random
        rng = random.Random(1729)  # deterministic search
        order_sets = [sorted(entries, key=lambda e: e["x"]), sorted(entries, key=lambda e: -e["x"]),
                      sorted(entries, key=lambda e: -e["opts"][0][0].w)]
        for _ in range(int(self.spec.get("stack_search", 150))):
            shuffled = list(entries)
            rng.shuffle(shuffled)
            order_sets.append(shuffled)
        best = None
        for ordered in order_sets:
            placed, violations = [], 0
            for e in ordered:
                choice = None
                for oi, (lab, lx) in enumerate(e["opts"]):
                    w, h = lab.w, lab.h
                    for d in sorted({0.0} | {p[1][3] + 2 for p in placed}):
                        if d > 0 and e.get("leader_to_centre") and lab.where not in ("centre", "hang_r", "hang_l"):
                            break  # below the first level a name hangs from a leader into its centre
                        box = (lx, d, lx + w, d + h)
                        if self._stack_ok(e, box, placed):
                            key = (d + h, len(lab.lines), oi)
                            if choice is None or key < choice[0]:
                                choice = (key, lab, lx, box)
                            break
                if choice is None:  # no clean place: take the first option on a new top level; the checks report it
                    violations += 1
                    lab, lx = e["opts"][0]
                    top = max((p[1][3] for p in placed), default=-2.0) + 2
                    choice = ((0,), lab, lx, (lx, top, lx + lab.w, top + lab.h))
                _, lab, lx, box = choice
                placed.append((e, box, lab))
            depth = max((p[1][3] for p in placed), default=0.0)
            key = (violations, round(depth, 2), sum(len(p[2].lines) for p in placed))
            if best is None or key < best[0]:
                best = (key, [(pe, pb, Label(list(pl.lines), pl.w, pl.where, size=pl.size, weight=pl.weight)) for pe, pb, pl in placed])
        if best[0][0] > 0:  # greedy orders left a name with no clean place: search exhaustively (bounded) for one without
            found = self._stack_dfs(sorted(entries, key=lambda e: e["x"]), limit=int(self.spec.get("stack_dfs_nodes", 20000)))
            if found is not None:
                best = ((0, found[0], 0), found[1])
        (violations, depth, _), placed = best
        self.stack_violations = getattr(self, "stack_violations", 0) + violations
        for e, box, lab in placed:
            lab.x = box[0]
            e["item"].label = lab
            e["item"].level_top = box[1]
            e["box"] = box
        return depth

    def _stack_dfs(self, ordered: list, limit: int):
        """Depth-first search over every entry's options (lowest clean level for each), minimising the stack depth, with
        no name left without a clean place. Returns (depth, placed) or None when none is found within `limit` nodes."""
        best = [None]
        nodes = [0]

        def rec(i: int, placed: list, depth: float) -> None:
            nodes[0] += 1
            if nodes[0] > limit or (best[0] is not None and depth >= best[0][0] - 1e-6):
                return
            if i == len(ordered):
                best[0] = (depth, [(pe, pb, Label(list(pl.lines), pl.w, pl.where, size=pl.size, weight=pl.weight)) for pe, pb, pl in placed])
                return
            e = ordered[i]
            tried = []
            for lab, lx in e["opts"]:
                for d in sorted({0.0} | {p[1][3] + 2 for p in placed}):
                    if d > 0 and e.get("leader_to_centre") and lab.where not in ("centre", "hang_r", "hang_l"):
                        break
                    box = (lx, d, lx + lab.w, d + lab.h)
                    if self._stack_ok(e, box, placed):
                        tried.append((d + lab.h, len(lab.lines), lab, box))
                        break
            for top, _, lab, box in sorted(tried, key=lambda t: (t[0], t[1])):
                placed.append((e, box, lab))
                rec(i + 1, placed, max(depth, top))
                placed.pop()

        rec(0, [], 0.0)
        return best[0]

    @staticmethod
    def _reads_as_own(e: dict, box: tuple) -> bool:
        """A strip name must read as belonging to its own marker: scored the way a reader (and the inspector) pairs a
        label with a marker - distance, plus 6 px when the marker is inside the name's span (plus a quarter of the offset
        from the name's centre), plus 12 px when it is not - its own marker must win by 4 px over every other marker."""
        x0, d0, x1, d1 = box
        r = MARKER_R * 1.4
        dy = d0 + 4.0  # the names hang below the marker row

        def score(xm: float) -> float:
            dx = max(0.0, x0 - (xm + r), (xm - r) - x1)
            dist = (dx * dx + dy * dy) ** 0.5
            if x0 <= xm <= x1:
                return dist + 6 + abs((x0 + x1) / 2 - xm) / 4
            return dist + 12

        own = score(e["x"])
        return all(own + 4 <= score(xo) for xo in e["others"])

    @staticmethod
    def _stack_ok(e: dict, box: tuple, placed: list) -> bool:
        x0, d0, x1, d1 = box
        if e.get("others") is not None and not DenseLayout._reads_as_own(e, box):
            return False
        for pe, pb, _ in placed:
            if x0 < pb[2] + NAME_GAP and pb[0] < x1 + NAME_GAP and d0 < pb[3] + 2 and pb[1] < d1 + 2:
                return False
            # the placed entry's line runs from the axis (d=0) to its name (pb[1]): it must not cross this name
            # in the milestone strip a leader beside a name reads as that name's marker: keep names well clear of other leaders
            clear = LEADER_SIDE_CLEAR if e.get("others") is not None else LINE_CLEAR
            if pe["line"] and d0 < pb[1] and pb[1] > 0.5 and x0 - clear <= pe["x"] <= x1 + clear:
                return False
            if pe["line"] and d0 < pb[1] and x0 - LINE_CLEAR <= pe["x"] <= x1 + LINE_CLEAR:
                return False
            # this entry's line runs from the axis to d0: it must not cross a placed name below it, nor pass close beside one
            if e["line"] and pb[1] < d0 and d0 > 0.5 and pb[0] - clear <= e["x"] <= pb[2] + clear:
                return False
            if e["line"] and pb[1] < d0 and pb[0] - LINE_CLEAR <= e["x"] <= pb[2] + LINE_CLEAR:
                return False
        return True

    def header_entries(self) -> list:
        entries, size = [], self.size
        left, right = self.chart_x0, self.chart_x1
        for g in self.gates:
            gx = self.x(g.d0)
            opts = []
            for lines, w in self.m.wraps(g.name, size, self.max_lines, "bold"):
                if gx + 4 + w <= right:
                    opts.append((Label(lines, w, "right", size=size, weight="bold"), gx + 4))
                if gx - 4 - w >= self.region["x"]:
                    opts.append((Label(lines, w, "left", size=size, weight="bold"), gx - 4 - w))
            entries.append({"item": g, "x": gx, "opts": opts or [(Label([g.name], self.m.width(g.name, size, "bold"), "right", size=size, weight="bold"), gx + 4)], "line": True})
        for wdw in self.windows:
            if wdw.id not in self.header_windows:
                continue  # named inside its own band (window_labels: "band"), placed in finish()
            wx0, wx1 = self.x(wdw.d0), self.x(wdw.d1)
            opts = []
            for lines, w in self.m.wraps(wdw.name, size, self.max_lines):
                for lx, where in ((wx0, "right"), (wx1 - w, "left"), ((wx0 + wx1 - w) / 2, "centre")):
                    lx = min(max(lx, self.region["x"]), self.region["x"] + self.region["w"] - w)
                    if lx < wx1 and lx + w > wx0:
                        opts.append((Label(lines, w, where, size=size), lx))
            cx = (wx0 + wx1) / 2
            opts = [(lab, lx) for lab, lx in opts if lx + 2 <= cx <= lx + lab.w - 2] or opts
            entries.append({"item": wdw, "x": cx, "opts": opts, "line": True})
        for i, text in enumerate(self.spec.get("edge_labels") or []):
            if not text or self.compact:  # compact: the two ruler dates are set in the rail corner beside the ruler
                continue
            w = self.m.width(text, size)
            it = Item(f"edge{i}", "edge", text)
            lx = left if i == 0 else self.x(self.days) - 6 - w
            entries.append({"item": it, "x": lx, "opts": [(Label([text], w, "right" if i == 0 else "left", size=size), lx)], "line": False})
        for e in entries:
            e["opts"].sort(key=lambda o: (len(o[0].lines), o[0].w))
        return entries

    def strip_marker_xs(self) -> dict:
        """Where each strip marker is drawn. Markers closer than one marker width (e.g. two milestones on the same day) are set
        side by side, centred on their mean date, so that each stays visible and each name has its own marker; every
        offset is reported in the scene (weeks)."""
        spacing = 2 * MARKER_R * 1.4 + 3
        items = sorted(self.milestones, key=lambda m: (self.x(m.d0), m.id))
        out, cluster = {}, []

        def flush():
            if not cluster:
                return
            mean = sum(self.x(m.d0) for m in cluster) / len(cluster)
            for k, m in enumerate(cluster):
                out[m.id] = mean + (k - (len(cluster) - 1) / 2) * spacing
            cluster.clear()

        for m in items:
            if cluster and self.x(m.d0) - self.x(cluster[-1].d0) >= spacing:
                flush()
            cluster.append(m)
        flush()
        return out

    def strip_entries(self) -> list:
        entries, size = [], self.size
        xs = self.strip_marker_xs()
        lo, hi = self.region["x"], self.region["x"] + self.region["w"]
        if self.legend_mode == "rail":  # the rail column under the lane names holds the legend: names stay over the chart
            lo = self.chart_x0 - 4
        for mk in self.milestones:
            mx = xs[mk.id]
            weight = "bold" if mk.style.get("focal") else "normal"
            opts = []
            for lines, w in self.m.wraps(mk.name, size, self.max_lines, weight):
                for lx, where in (((mx - w / 2), "centre"), (mx + MARKER_R + 4, "right"), (mx - MARKER_R - 4 - w, "left"),
                                  (mx - 3, "hang_r"), (mx + 3 - w, "hang_l")):  # hang_*: below a leader, the name starts or ends at it
                    if lo <= lx and lx + w <= hi:
                        opts.append((Label(lines, w, where, size=size, weight=weight), lx))
            if not opts:
                lines, w = self.m.wraps(mk.name, size, self.max_lines, weight)[-1]
                opts = [(Label(lines, w, "centre", size=size, weight=weight), min(max(mx - w / 2, lo), hi - w))]
            entries.append({"item": mk, "x": mx, "opts": opts, "line": True, "leader_to_centre": True,
                            "others": [x for mid, x in xs.items() if mid != mk.id]})
        for e in entries:
            e["opts"].sort(key=lambda o: (len(o[0].lines), {"centre": 0, "right": 1, "left": 2, "hang_r": 3, "hang_l": 4}[o[0].where], o[0].w))
        return entries

    # ---------------------------------------------------------------- ruler
    def ticks(self) -> list:
        weeks_total = int(math.ceil(self.extent_days / 7 - 1e-9))
        horizon_weeks = int(math.ceil(self.days / 7 - 1e-9))
        prefix = self.spec.get("prefix", "W")
        for step in (1, 2, 3, 4, 5, 6, 8, 10, 13, 26, 52):
            out = []
            for n in range(1, weeks_total + 1):
                if (n - 1) % step and n != horizon_weeks + 1:
                    continue
                text = f"{prefix}{n}"
                w = self.m.width(text, self.tick_px)
                cx = self.x(7 * (n - 1) + 3.5)
                out.append({"week": n, "label": text, "cx": cx, "w": w, "beyond": n > horizon_weeks})
            if all(b["cx"] - b["w"] / 2 - (a["cx"] + a["w"] / 2) >= 6 for a, b in zip(out, out[1:])):
                return out
        return out[:1]

    # ---------------------------------------------------------------- one full layout at given density
    def attempt(self, rail_w: float, row_gap: float, lane_pad: float, order: str, legend_mode: str = "bottom") -> dict:
        self.set_scale(rail_w)
        self.legend_mode = legend_mode
        size = self.size
        chart_left, chart_right = self.chart_x0, self.label_right()
        # header
        header_entries, header_depth = self.cached_stack("header", self.header_entries)
        header_h = header_depth + (4 if header_entries else 0)
        ruler_h = self.tick_px * LINE + (5 if self.compact else 8)
        self.corner_lines = []
        if self.compact:
            for text in self.spec.get("edge_labels") or []:
                if text:
                    self.corner_lines += self.m.wrap(text, size, rail_w - 12)[0]
            header_h = max(header_h, len(self.corner_lines) * self.line_h + 2 - ruler_h)
        # lanes
        lane_rows, lane_heights, lane_name_lines = [], [], []
        self.above_clear = {}
        for lane in self.lanes:
            items = [t for t in self.tasks if t.lane == lane["id"]] + [e for e in self.events if e.lane == lane["id"]]
            rows = self.pack_lane_best(lane["id"], items, chart_left, chart_right)
            for row in rows:  # cached packings carry labels, not positions: place every item on THIS scale
                for it, *_ in row:
                    it.x0 = self.x(it.d0)
                    it.x1 = self.x(it.d1) if it.kind == "task" else it.x0
            previous_row = None  # rows of the lane above sit in another band: the lane padding and band edge separate them
            for row in rows:  # a name above its bar needs clear room from any bar of the row above that spans it
                for it, lab, *_ in row:
                    if it.kind == "task" and lab.where == "above" and previous_row:
                        lx = min(max(it.x0, chart_left), chart_right - lab.w)
                        if any(o.kind == "task" and o.x0 - 4 < lx + lab.w and lx < o.x1 + 4 for o, *_ in previous_row):
                            self.above_clear[id(row)] = ABOVE_CLEAR
                previous_row = row
            names, _ = self.m.wrap(lane["name"], self.lane_px, rail_w - 12, "bold")
            rows_h = sum(self.row_height(r) for r in rows) + row_gap * max(0, len(rows) - 1)
            name_h = len(names) * self.lane_px * LINE
            lane_rows.append(rows)
            lane_name_lines.append(names)
            lane_heights.append(max(rows_h, name_h) + 2 * lane_pad)
        # strip
        strip_entries, strip_depth = self.cached_stack("strip", self.strip_entries)
        marker_row = (2 * MARKER_R * (1.4 if any(m.style.get("focal") for m in self.milestones) else 1)) + 6 if self.milestones else 0.0
        strip_h = marker_row + strip_depth  # names end at the region edge: no trailing pad
        legend = self.spec.get("legend") or []
        legend_h = 0.0
        if legend and legend_mode == "rail":
            block = len(legend) * self.line_h + 2 if self.compact else len(legend) * (self.line_h + 2) + 4
            widest = max(20 + self.m.width(e["text"], size) for e in legend)
            if widest > rail_w - 8:
                legend_h = float("inf")  # does not fit the rail column
            strip_h = max(strip_h, block)
        elif legend:
            legend_h = self.line_h + 8
        total = header_h + ruler_h + sum(lane_heights) + strip_h + legend_h
        return {"rail_w": rail_w, "row_gap": row_gap, "lane_pad": lane_pad, "order": order, "header_h": header_h,
                "ruler_h": ruler_h, "lane_heights": lane_heights, "lane_rows": lane_rows, "lane_name_lines": lane_name_lines,
                "strip_h": strip_h, "marker_row": marker_row, "legend_h": legend_h, "total": total, "legend_mode": legend_mode,
                "pad_y": self.pad_y,
                "straddle_first": self.straddle_first,
                "straddles": sum(self._straddles(it, lab) for rows in lane_rows for row in rows for it, lab, *_ in row),
                "header_entries": header_entries, "strip_entries": strip_entries,
                "rows": sum(len(r) for r in lane_rows)}

    def cached_stack(self, kind: str, make) -> tuple:
        """Stacked names depend only on the scale and the label size: compute once per scale, re-apply the labels after."""
        key = (kind, round(self.chart_x0, 3), round(self.px_day, 6), self.size, self.legend_mode if kind == "strip" else "",
               tuple(sorted(self.header_windows)) if kind == "header" else ())
        cache = self.__dict__.setdefault("_stack_cache", {})
        if key not in cache:
            entries = make()
            depth = self.stack(entries, upward=(kind == "header")) if entries else 0.0
            cache[key] = (entries, depth, [(e["item"], e["item"].label, e["box"]) for e in entries])
        entries, depth, labels = cache[key]
        for item, lab, box in labels:
            item.label = Label(list(lab.lines), lab.w, lab.where, x=lab.x, y0=lab.y0, size=lab.size, weight=lab.weight)
        for e, (_, _, box) in zip(entries, labels):
            e["box"] = box
        return entries, depth

    def rail_candidates(self) -> list:
        given = self.spec.get("lane_label_w")
        if given:
            return [float(given)]
        longest = max((self.m.width(l["name"], self.lane_px, "bold") for l in self.spec["lanes"]), default=100)
        base = [120, 140, 160, 180, 200, 220, 250]
        return sorted({float(min(max(b, 90), max(120, longest + 14))) for b in base})

    def solve(self) -> dict:
        """Solve; a window named inside its band (window_labels: "band") that finds no free place there returns to the
        header stack and the layout is solved again, so the reported height always matches what is drawn."""
        self.build_items()
        self.compact = self.spec.get("header") == "compact"
        self.header_windows = set() if self.compact else {w.id for w in self.windows}
        geo = None
        for _ in range(len(self.windows) + 1):
            self.band_misses = set()
            geo = self._solve_once()
            if not self.band_misses:
                break
            self.header_windows |= self.band_misses
        return geo

    def _solve_once(self) -> dict:
        """The most generous density that fits; else the attempt needing the least height (reported as capacity failure)."""
        densities = self.spec.get("densities") or [(6, 8), (4, 6), (3, 4), (2, 3), (2, 2), (1, 1)]
        best_fail = None
        asked = float(self.spec.get("bar_pad_y", 4.0))
        # compact: when nothing fits at the asked bar padding, tighter padding is tried before reporting a capacity failure
        pads = [asked] + ([p for p in (3.0, 2.0, 1.0) if p < asked] if self.compact and not self.thin else [])
        for pad_y, (row_gap, lane_pad) in [(p, d) for p in pads for d in densities]:
            self.pad_y = pad_y
            fits = []
            for rail in self.rail_candidates():
                for legend_mode in (("rail", "bottom") if self.spec.get("legend") else ("bottom",)):
                    a = self.attempt(rail, row_gap, lane_pad, "search", legend_mode)
                    if a["total"] <= self.region["h"] + 0.01:
                        fits.append(a)
                    if best_fail is None or a["total"] < best_fail["total"]:
                        best_fail = a
            if fits:
                chosen = min(fits, key=lambda a: (a["total"], -a["rail_w"]))
                if chosen["straddles"]:
                    # labels straddle a window edge: spend spare height on clean placements when the result still fits
                    self.straddle_first = True
                    trial = self.attempt(chosen["rail_w"], chosen["row_gap"], chosen["lane_pad"], "search", chosen["legend_mode"])
                    if trial["total"] <= self.region["h"] + 0.01 and trial["straddles"] < chosen["straddles"]:
                        chosen = trial
                    else:
                        self.straddle_first = False
                return self.finish(chosen, True)
        return self.finish(best_fail, False)

    # ---------------------------------------------------------------- final geometry
    def finish(self, a: dict, fits: bool) -> dict:
        # re-run the chosen attempt so every item carries its geometry
        self.stack_violations = 0
        self.straddle_first = a.get("straddle_first", False)
        self.pad_y = a.get("pad_y", self.pad_y)
        a = self.attempt(a["rail_w"], a["row_gap"], a["lane_pad"], a["order"], a["legend_mode"])
        chart_left, chart_right = self.chart_x0, self.label_right()
        r = self.region
        spare = max(0.0, r["h"] - a["total"]) if fits else 0.0
        extra_pad = min(6.0, spare / (2 * max(1, len(self.lanes)))) if fits else 0.0
        y = r["y"]
        header_top = y
        y += a["header_h"]
        axis_top = y
        tick_base = y + self.tick_px * 1.0
        y += a["ruler_h"]
        axis_y = y - 3
        lanes_top = y
        lanes = []
        row_bands = []
        for li, lane in enumerate(self.lanes):
            pad = a["lane_pad"] + extra_pad
            height = a["lane_heights"][li] + 2 * extra_pad
            top = y
            ry = top + pad
            rows_h = sum(self.row_height(rw) for rw in a["lane_rows"][li]) + a["row_gap"] * max(0, len(a["lane_rows"][li]) - 1)
            ry += max(0.0, (height - 2 * pad - rows_h) / 2)  # centre the rows when the lane name is taller
            for ri, row in enumerate(a["lane_rows"][li]):
                rh = self.row_height(row)
                for it, lab, fx0, fx1, n in row:
                    it.row = ri
                    it.label = lab
                    if it.kind == "task" and lab.where == "above":
                        it.h = self.bar_h()
                        it.y = ry + rh - it.h
                        lab.x = min(max(it.x0, chart_left), chart_right - lab.w)
                        lab.y0 = it.y - 2 - lab.h
                    elif it.kind == "task":
                        bar_h = n * self.line_h + 2 * self.pad_y if lab.where == "inside" else self.bar_h()
                        it.h = bar_h
                        it.y = ry + (rh - bar_h) / 2
                        cy = it.y + bar_h / 2
                        if lab.where == "inside":
                            lab.x = it.x0 + self.pad_x
                        elif lab.where == "right":
                            lab.x = it.x1 + lab.gap
                        else:
                            lab.x = it.x0 - lab.gap - lab.w
                        lab.y0 = cy - lab.h / 2
                    else:
                        it.y = ry + rh / 2
                        it.h = 2 * EVENT_R
                        lab.x = it.x0 + EVENT_R + lab.gap if lab.where == "right" else it.x0 - EVENT_R - lab.gap - lab.w
                        lab.y0 = it.y - lab.h / 2
                row_bands.append((li, ry, ry + rh))
                ry += rh + a["row_gap"]
            lanes.append({"id": lane["id"], "name": lane["name"], "y": round(top, 2), "h": round(height, 2),
                          "rows": len(a["lane_rows"][li]), "name_lines": a["lane_name_lines"][li]})
            y = top + height
        lanes_bottom = y
        # header names: stack depth is measured upward from the axis top
        for e in a["header_entries"]:
            it, lab, box = e["item"], e["item"].label, e["box"]
            lab.y0 = axis_top - 4 - box[3]
        # strip: markers then names downward
        marker_y = lanes_bottom + a["marker_row"] / 2 + 2 if self.milestones else lanes_bottom
        strip_top = lanes_bottom + a["marker_row"]
        strip_xs = self.strip_marker_xs()
        for e in a["strip_entries"]:
            it, lab, box = e["item"], e["item"].label, e["box"]
            it.y = marker_y
            it.x0 = it.x1 = strip_xs[it.id]
            lab.y0 = strip_top + box[1]
        legend_y = None
        if self.spec.get("legend"):
            legend_y = (lanes_bottom + (2 if self.compact else 4)) if a["legend_mode"] == "rail" else lanes_bottom + a["strip_h"] + 4
        for g in self.gates:
            g.x0 = g.x1 = self.x(g.d0)
        for w in self.windows:
            w.x0, w.x1 = self.x(w.d0), self.x(w.d1)
        self.geo = {"fits": fits, "attempt": a, "header_top": header_top, "axis_top": axis_top, "axis_y": axis_y,
                    "tick_base": tick_base, "lanes_top": lanes_top, "lanes_bottom": lanes_bottom, "lanes": lanes,
                    "row_bands": row_bands, "marker_y": marker_y, "strip_top": strip_top, "legend_y": legend_y,
                    "ticks": self.ticks(), "extra_pad": extra_pad}
        self.place_band_names(lanes_top, lanes_bottom)
        self.cut_gate_lines()        # first: a dependency on a gate must start or end on a VISIBLE part of its line
        self.route_dependencies()
        return self.geo

    def place_band_names(self, lanes_top: float, lanes_bottom: float) -> None:
        """A window named inside its own band: the name is wrapped to the band's width and set in the highest stretch of
        the band that no bar, label or marker touches. No free stretch: the window goes back to the header (solve())."""
        size = self.size
        for w in self.windows:
            if w.id in self.header_windows:
                continue
            avail = (w.x1 - w.x0) - 6.0
            cx = (w.x0 + w.x1) / 2
            solid = []
            for t in self.tasks:
                solid.append(Box(t.x0, t.y, t.x1, t.y + t.h))
            for e in self.events:
                solid.append(Box(e.x0 - EVENT_R, e.y - EVENT_R, e.x0 + EVENT_R, e.y + EVENT_R))
            for oid, box in self.label_boxes():
                if oid != w.id:
                    solid.append(box)
            placed = None
            for lines, lw in sorted(self.m.wraps(w.name, size, int(self.spec.get("band_name_max_lines", 6)), min_w=24.0),
                                    key=lambda o: len(o[0])):
                if lw > avail:
                    continue
                h = len(lines) * self.line_h
                x0, x1 = cx - lw / 2, cx + lw / 2
                hits = sorted((b.y0, b.y1) for b in solid if b.x0 < x1 + 3 and x0 - 3 < b.x1)
                cursor = lanes_top + 2
                for y0, y1 in hits + [(lanes_bottom - 2, lanes_bottom)]:
                    if y0 - 2 - cursor >= h:
                        placed = (lines, lw, x0, cursor)
                        break
                    cursor = max(cursor, y1 + 2)
                if placed:
                    break
            rot = None
            if placed is None:  # too narrow for its words: set the name reading upward where the band is empty
                for lines, lw in sorted(self.m.wraps(w.name, size, 2, min_w=24.0), key=lambda o: len(o[0])):
                    bw = len(lines) * self.line_h
                    if bw > avail:
                        continue
                    x0, x1 = cx - bw / 2, cx + bw / 2
                    hits = sorted((b.y0, b.y1) for b in solid if b.x0 < x1 + 3 and x0 - 3 < b.x1)
                    cursor = lanes_top + 2
                    for y0, y1 in hits + [(lanes_bottom - 2, lanes_bottom)]:
                        if y0 - 2 - cursor >= lw:
                            rot = (lines, bw, x0, cursor + max(0.0, (min(y0 - 2, lanes_bottom - 2) - cursor - lw) / 2), lw)
                            break
                        cursor = max(cursor, y1 + 2)
                    if rot:
                        break
            if rot:
                lines, bw, lx, top, span = rot
                w.label = Label(list(lines), bw, "band", x=lx, y0=top, size=size, rot=True, span=span)
                continue
            if placed is None:
                self.band_misses.add(w.id)
                lines, lw = self.m.wraps(w.name, size, self.max_lines)[0]
                placed = (lines, lw, min(max(cx - lw / 2, self.region["x"]), self.region["x"] + self.region["w"] - lw), lanes_top + 2)
            lines, lw, lx, top = placed
            w.label = Label(list(lines), lw, "band", x=lx, y0=top, size=size)

    # ---------------------------------------------------------------- dependencies
    def label_boxes(self) -> list:
        out = []
        for it in self.tasks + self.events:
            if it.label and not (it.kind == "task" and it.label.where == "inside"):
                out.append((it.id, it.label.box()))
        for it in self.gates + self.windows + self.milestones:
            if it.label:
                out.append((it.id, it.label.box()))
        return out

    def route_dependencies(self) -> None:
        """Orthogonal routes between any two items. Hard rules (cost 1000 each, so a route breaks them only when no route
        avoids them): a route never passes over or within 10 px of a marker that is not its own end, never starts or ends
        within 14 px of such a marker (it would read as attached to it), and a route that starts or ends on a gate does so
        on a visible segment of the gate's line. Soft: crossing a label (200), passing behind another bar (2), length."""
        geo = self.geo
        bars = [(t.id, Box(t.x0, t.y, t.x1, t.y + t.h)) for t in self.tasks]
        markers = []
        for m in self.milestones + self.events:
            r = (MARKER_R * (1.4 if m.style.get("focal") else 1) if m.kind == "milestone" else EVENT_R) + 4
            markers.append((m.id, Box(m.x0 - r, m.y - r, m.x0 + r, m.y + r)))
        labels = self.label_boxes()
        gaps = sorted({round(b + 1.5, 2) for _, _, b in geo["row_bands"]} | {round(t - 1.5, 2) for _, t, _ in geo["row_bands"]})

        def dist(pt, b: Box) -> float:
            dx = max(b.x0 - pt[0], 0, pt[0] - b.x1)
            dy = max(b.y0 - pt[1], 0, pt[1] - b.y1)
            return (dx * dx + dy * dy) ** 0.5

        def cost(points, src: Item, dst: Item) -> float:
            c = 0.0
            for p, q in zip(points, points[1:]):
                seg = Box(min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
                c += 0.002 * (seg.x1 - seg.x0 + seg.y1 - seg.y0)
                for iid, b in labels:
                    if seg.overlaps(Box(b.x0 + 1, b.y0 + 1, b.x1 - 1, b.y1 - 1)):
                        c += 200
                for iid, b in bars:
                    if iid not in (src.id, dst.id) and seg.overlaps(Box(b.x0 + 1, b.y0 + 1, b.x1 - 1, b.y1 - 1)):
                        c += 2
                for iid, b in markers:
                    if iid not in (src.id, dst.id) and seg.overlaps(Box(b.x0 - 6, b.y0 - 6, b.x1 + 6, b.y1 + 6)):
                        c += 1000  # never over, and never within 10 px of, a marker that is not its own end
            for end_pt in (points[0], points[-1]):
                for iid, b in markers:
                    if iid not in (src.id, dst.id) and dist(end_pt, b) < ENDPOINT_CLEAR - 4:  # b already carries 4 px
                        c += 1000
            if src.kind == "gate" and not self._on_visible_line(src, points[0][1]):
                c += 1000
            if dst.kind == "gate" and not self._on_visible_line(dst, points[-1][1]):
                c += 1000
            return c + 0.2 * len(points)

        self.deps = []
        for i, dep in enumerate(self.spec.get("dependencies") or []):
            s, t = self.by_id[dep["from"]], self.by_id[dep["to"]]
            options = self._dep_options(s, t, gaps)
            scored = [(cost(pts, s, t), pts) for pts in options]
            best_cost, best = min(scored, key=lambda cp: cp[0]) if scored else (0.0, [])
            clean = [best[0]] if best else []
            for p in best[1:]:
                if abs(p[0] - clean[-1][0]) > 0.01 or abs(p[1] - clean[-1][1]) > 0.01:
                    clean.append(p)
            corners = clean[:1]
            for here, nxt in zip(clean[1:], clean[2:] + [None]):
                if nxt is not None and ((corners[-1][0] == here[0] == nxt[0]) or (corners[-1][1] == here[1] == nxt[1])):
                    continue
                corners.append(here)
            self.deps.append({"id": dep.get("id") or f"dep{i + 1}", "from": s.id, "to": t.id, "route_cost": round(best_cost, 2),
                              "points": [[round(px, 2), round(py, 2)] for px, py in corners]})

    def _on_visible_line(self, gate: Item, y: float) -> bool:
        return any(y0 + 1 <= y <= y1 - 1 for y0, y1 in self.gate_segments.get(gate.id, []))

    def _gate_points(self, gate: Item, gaps: list, hint: float) -> list:
        """Candidate points on a gate's visible line: each visible segment's lowest point, the row gaps inside it, and the
        other end's height when that is visible."""
        ys = []
        for y0, y1 in self.gate_segments.get(gate.id, []):
            if y1 - y0 < 3:
                continue
            ys.append(y1 - 1.5)
            ys += [g for g in gaps if y0 + 2 <= g <= y1 - 2]
        if self._on_visible_line(gate, hint):
            ys.append(hint)
        ys = sorted(set(round(y, 2) for y in ys))
        return [(gate.x0, y) for y in ys] or [(gate.x0, self.geo["lanes_bottom"])]

    def _anchor(self, it: Item, role: str, other_y: float) -> tuple:
        """Where a dependency leaves (role 'out') or enters (role 'in') an item."""
        if it.kind == "task":
            cy = it.y + it.h / 2
            return (it.x1, cy) if role == "out" else (it.x0, cy)
        if it.kind in ("event", "milestone"):
            r = EVENT_R if it.kind == "event" else MARKER_R * (1.4 if it.style.get("focal") else 1)
            return (it.x0 + r, it.y) if role == "out" else (it.x0 - r, it.y)
        if it.kind == "gate":
            top, bottom = self.geo["lanes_top"], self.geo["lanes_bottom"]
            return (it.x0, min(max(other_y, top), bottom))
        return (it.x0, other_y)

    def _dep_options(self, s: Item, t: Item, gaps: list) -> list:
        ty_hint = (t.y + t.h / 2) if t.kind == "task" else t.y
        sy_hint = (s.y + s.h / 2) if s.kind == "task" else s.y
        starts = self._gate_points(s, gaps, ty_hint) if s.kind == "gate" else [self._anchor(s, "out", ty_hint)]
        ends = self._gate_points(t, gaps, sy_hint) if t.kind == "gate" else [self._anchor(t, "in", sy_hint)]
        if t.kind in ("milestone", "event"):  # a marker may also be entered from its right-hand point
            r = EVENT_R if t.kind == "event" else MARKER_R * (1.4 if t.style.get("focal") else 1)
            ends.append((t.x0 + r, t.y))
        left, right = self.chart_x0, self.chart_x1
        opts = []
        for a in starts:
            for b in ends:
                if abs(a[1] - b[1]) < 0.5 and abs(b[0] - a[0]) > 4:
                    opts.append([a, b])
                entering_left = b[0] <= t.x0  # the end point is on the target's left: arrive moving right
                ks = range(int(left) + 2, int(right) - 1, 3)
                for k in ks:
                    if s.kind == "task" and k < a[0] + 6:
                        continue  # a bar's arrow leaves forward from its end
                    if entering_left and k > b[0] - 6 or (not entering_left and k < b[0] + 6):
                        continue
                    opts.append([a, (k, a[1]), (k, b[1]), b])
                if s.kind == "task" and b[0] < a[0] + 12:  # target starts at or before the source's end: leave from the underside
                    under = s.y + s.h
                    for gy in [g for g in gaps if g > under - 0.5][:3] + [under + 3]:
                        if t.kind == "gate":
                            x_start = min(a[0] - 10, b[0] - 10)
                            opts.append([(x_start, under), (x_start, gy), (b[0], gy)])
                        elif entering_left:
                            for back in range(8, 40, 4):
                                opts.append([(a[0] - 6, under), (a[0] - 6, gy), (b[0] - back, gy), (b[0] - back, b[1]), b])
                if s.kind == "task" and entering_left:
                    for gy in [g for g in gaps if min(a[1], b[1]) <= g <= max(a[1], b[1])]:
                        for back in range(8, 40, 4):
                            opts.append([a, (a[0] + 6, a[1]), (a[0] + 6, gy), (b[0] - back, gy), (b[0] - back, b[1]), b])
        return opts

    # ---------------------------------------------------------------- gate lines as segments
    def cut_gate_lines(self) -> None:
        """Each gate line runs from under its name to the foot of the lanes, interrupted wherever it would cross a label
        that is not inside a bar (bars are painted over the line, which hides it there)."""
        geo = self.geo
        blockers = [b for iid, b in self.label_boxes() if self.by_id.get(iid) is None or self.by_id[iid].kind != "gate"]
        blockers += [Box(e.x0 - EVENT_R - 1, e.y - EVENT_R - 1, e.x0 + EVENT_R + 1, e.y + EVENT_R + 1) for e in self.events]
        tick_boxes = [Box(t["cx"] - t["w"] / 2, geo["tick_base"] - self.tick_px * 0.78, t["cx"] + t["w"] / 2, geo["tick_base"] + 0.22 * self.tick_px)
                      for t in geo["ticks"]]
        self.gate_segments = {}
        for g in self.gates:
            top = g.label.y0 + g.label.h + 1 if g.label else geo["axis_top"]
            bottom = geo["lanes_bottom"]
            cuts = sorted((b.y0 - 2, b.y1 + 2) for b in blockers + tick_boxes if b.x0 - 2 <= g.x0 <= b.x1 + 2 and b.y1 > top and b.y0 < bottom)
            segs, y = [], top
            for c0, c1 in cuts:
                if c0 > y + 1:
                    segs.append((y, c0))
                y = max(y, c1)
            if bottom > y + 1:
                segs.append((y, bottom))
            self.gate_segments[g.id] = segs

    # ---------------------------------------------------------------- checks
    def checks(self) -> list:
        found = []
        geo = self.geo
        r = self.region
        texts = []
        for it in self.tasks + self.events + self.gates + self.milestones + self.windows:
            if it.label:
                texts.append((f"{it.kind} {it.id}", it.label.box(), it))
        for lane, lines in zip(geo["lanes"], [l["name_lines"] for l in geo["lanes"]]):
            texts.append((f"lane {lane['id']}", Box(r["x"] + 8, lane["y"], r["x"] + self.rail_w, lane["y"] + len(lines) * self.lane_px * LINE), None))
        for i, (na, a, _) in enumerate(texts):
            for nb, b, _ in texts[i + 1:]:
                if a.overlaps(b, -0.5, -0.5):
                    found.append(f"{na} overlaps {nb}")
        bars = [(t.id, Box(t.x0, t.y, t.x1, t.y + t.h)) for t in self.tasks]
        for name, box, it in texts:
            for bid, bb in bars:
                inside_own = it is not None and it.id == bid and it.label.where == "inside"
                if not inside_own and box.overlaps(Box(bb.x0 + 0.5, bb.y0 + 0.5, bb.x1 - 0.5, bb.y1 - 0.5)):
                    found.append(f"{name} lies on bar {bid}")
            if box.x0 < r["x"] - 0.5 or box.x1 > r["x"] + r["w"] + 0.5 or box.y0 < r["y"] - 0.5 or box.y1 > r["y"] + r["h"] + 0.5:
                found.append(f"{name} leaves the region")
        for t in self.tasks:
            if t.label.where == "inside" and t.label.x + t.label.w > t.x1 - self.pad_x + 0.5:
                found.append(f"task {t.id} label runs out of its bar")
        for dep in self.deps:
            for p, q in zip(dep["points"], dep["points"][1:]):
                seg = Box(min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
                for name, box, it in texts:
                    if it is not None and it.kind == "task" and it.label.where == "inside":
                        continue
                    if seg.overlaps(Box(box.x0 + 1, box.y0 + 1, box.x1 - 1, box.y1 - 1)):
                        found.append(f"dependency {dep['id']} crosses {name}")
        for m in self.milestones:  # leaders: from the marker down to a name below the first level
            if m.label and m.label.y0 > geo["strip_top"] + 1:
                for name, box, it in texts:
                    if it is not m and box.y1 > m.y + MARKER_R and box.y0 < m.label.y0 and box.x0 - 1 < m.x0 < box.x1 + 1:
                        found.append(f"milestone leader {m.id} crosses {name}")
        if not geo["fits"]:
            found.append("does not fit the region")
        return list(dict.fromkeys(found))

    # ---------------------------------------------------------------- SVG
    def svg_children(self, prefix: str) -> tuple:
        c, geo, r = self.colors, self.geo, self.region
        size, out = self.size, []

        def attrs(cid, role, extra_id=None):
            return (f' id="{escape(extra_id)}"' if extra_id else "") + f' data-content-id="{escape(cid)}" data-role="{role}"'

        def text(lab: Label, cid, role, fill, anchor_id=None, weight=None):
            if lab.rot:  # one <text> per line, rotated about its own centre (reads upward)
                parts = []
                cy = lab.y0 + lab.span / 2
                for i, line in enumerate(lab.lines):
                    bx = lab.x + (i + 0.5) * lab.size * LINE + 0.35 * lab.size
                    parts.append(f'<text{attrs(cid, role, anchor_id if i == 0 else None)} x="{bx:.2f}" y="{cy:.2f}" font-size="{lab.size:g}" '
                                 f'text-anchor="middle" transform="rotate(-90 {bx:.2f} {cy:.2f})" fill="{fill}">{escape(line)}</text>')
                return "".join(parts)
            spans = "".join(f'<tspan x="{lab.x:.2f}" dy="{0 if i == 0 else round(lab.size * LINE, 2):g}">{escape(line)}</tspan>'
                            for i, line in enumerate(lab.lines))
            base = lab.y0 + 0.5 * lab.size * LINE + 0.35 * lab.size
            w = weight or lab.weight
            return (f'<text{attrs(cid, role, anchor_id)} x="{lab.x:.2f}" y="{base:.2f}" font-size="{lab.size:g}"'
                    f'{" font-weight=\"bold\"" if w == "bold" else ""} fill="{fill}">{spans}</text>')

        # compact (0.4.0): a fixed 8 px head in slide units is what PowerPoint draws for 1-2 px lines, so preview and slide agree
        units = ' markerWidth="8" markerHeight="8" markerUnits="userSpaceOnUse"' if self.compact else ' markerWidth="6" markerHeight="6"'
        defs = (f'<marker id="{prefix}-arrow" viewBox="0 0 10 10" refX="9" refY="5"{units} orient="auto">'
                f'<polygon points="0,0 10,5 0,10" fill="{c["dependency"]}"/></marker>')
        lanes_top, lanes_bottom = geo["lanes_top"], geo["lanes_bottom"]
        # 1 lane bands and names
        for i, lane in enumerate(geo["lanes"]):
            if i % 2 == 0:
                out.append(f'<rect{attrs("lane:" + lane["id"], "lane-band")} x="{r["x"]:g}" y="{lane["y"]:g}" width="{r["w"]:g}" height="{lane["h"]:g}" fill="{c["band"]}"/>')
            lab = Label(lane["name_lines"], 0, "rail", size=self.lane_px, weight="bold")
            lab.x, lab.y0 = r["x"] + 8, lane["y"] + max(2.0, (lane["h"] - lab.h) / 2)
            out.append(text(lab, "lane:" + lane["id"], "lane-label", c["rail_text"], f"{prefix}-lane-{lane['id']}-label"))
        # 2 windows
        for w in self.windows:
            if w.style.get("dashed"):
                out.append(f'<rect{attrs("window:" + w.id, "window", f"{prefix}-window-{w.id}")} x="{w.x0:.2f}" y="{lanes_top:.2f}" width="{w.x1 - w.x0:.2f}" height="{lanes_bottom - lanes_top:.2f}" fill="none" stroke="{c["float"]}" stroke-width="1" stroke-dasharray="4 4"/>')
            else:
                out.append(f'<rect{attrs("window:" + w.id, "window", f"{prefix}-window-{w.id}")} x="{w.x0:.2f}" y="{lanes_top:.2f}" width="{w.x1 - w.x0:.2f}" height="{lanes_bottom - lanes_top:.2f}" fill="{c["window"]}"/>')
        # 3 ruler
        horizon_x = self.x(self.days)
        out.append(f'<line{attrs("axis", "axis")} x1="{self.chart_x0:.2f}" y1="{geo["axis_y"]:.2f}" x2="{horizon_x:.2f}" y2="{geo["axis_y"]:.2f}" stroke="{c["axis"]}" stroke-width="1"/>')
        if self.extent_days > self.days + 0.01:
            out.append(f'<line{attrs("axis", "axis-extension")} x1="{horizon_x:.2f}" y1="{geo["axis_y"]:.2f}" x2="{self.chart_x1:.2f}" y2="{geo["axis_y"]:.2f}" stroke="{c["axis"]}" stroke-width="1" stroke-dasharray="3 3"/>')
        for t in geo["ticks"]:
            tx = self.x(7 * (t["week"] - 1))
            out.append(f'<line{attrs("tick:" + str(t["week"]), "tick-mark")} x1="{tx:.2f}" y1="{geo["axis_y"]:.2f}" x2="{tx:.2f}" y2="{geo["axis_y"] + 4:.2f}" stroke="{c["axis"]}" stroke-width="1"/>')
            out.append(f'<text{attrs("tick:" + str(t["week"]), "tick-label")} x="{t["cx"]:.2f}" y="{geo["tick_base"]:.2f}" font-size="{self.tick_px:g}" text-anchor="middle" fill="{c["muted"]}">{escape(t["label"])}</text>')
        # 4 gate lines (segments)
        for g in self.gates:
            for k, (y0, y1) in enumerate(self.gate_segments[g.id]):
                out.append(f'<line{attrs("milestone:" + g.id, "gate-line", f"{prefix}-ms-{g.id}-line{k}")} x1="{g.x0:.2f}" y1="{y0:.2f}" x2="{g.x0:.2f}" y2="{y1:.2f}" stroke="{c["gate"]}" stroke-width="1.5" stroke-dasharray="5 3"/>')
        # 5 dependencies (behind bars)
        for dep in self.deps:
            d = "M" + " L".join(f"{px:g} {py:g}" for px, py in dep["points"])
            out.append(f'<path{attrs("dependency:" + dep["id"], "dependency", f"{prefix}-dep-{dep["id"]}")} d="{d}" fill="none" stroke="{c["dependency"]}" stroke-width="1.5" marker-end="url(#{prefix}-arrow)"/>')
        # 6 bars and labels, lane events
        for t in self.tasks:
            fill = t.style.get("fill") or c["bar"]
            out.append(f'<rect{attrs("task:" + t.id, "bar", f"{prefix}-task-{t.id}")} x="{t.x0:.2f}" y="{t.y:.2f}" width="{t.x1 - t.x0:.2f}" height="{t.h:.2f}" fill="{fill}"/>')
            colour = (t.style.get("text") or c["bar_text"]) if t.label.where == "inside" else c["text"]
            out.append(text(t.label, "task:" + t.id, "bar-label", colour, f"{prefix}-task-{t.id}-label"))
        for e in self.events:
            x, y = e.x0, e.y
            out.append(f'<polygon{attrs("milestone:" + e.id, "milestone-marker", f"{prefix}-ms-{e.id}")} points="{x:.2f},{y - EVENT_R:.2f} {x + EVENT_R:.2f},{y + EVENT_R * 0.8:.2f} {x - EVENT_R:.2f},{y + EVENT_R * 0.8:.2f}" fill="{c["event"]}"/>')
            out.append(text(e.label, "milestone:" + e.id, "milestone-label", c["text"], f"{prefix}-ms-{e.id}-label"))
        # 7 strip: leaders, markers, names
        for m in self.milestones:
            x, y = m.x0, m.y
            rr = MARKER_R * (1.4 if m.style.get("focal") else 1)
            if m.label.y0 > geo["strip_top"] + 1:
                out.append(f'<line{attrs("milestone:" + m.id, "milestone-leader")} x1="{x:.2f}" y1="{y + rr:.2f}" x2="{x:.2f}" y2="{m.label.y0 + 1:.2f}" stroke="{c["leader"]}" stroke-width="0.75"/>')
            if m.style.get("payment"):
                pr = rr + 3.5
                out.append(f'<polygon{attrs("milestone:" + m.id, "payment-ring")} points="{x:.2f},{y - pr:.2f} {x + pr:.2f},{y:.2f} {x:.2f},{y + pr:.2f} {x - pr:.2f},{y:.2f}" fill="none" stroke="{c["milestone"]}" stroke-width="1"/>')
            fill = c["focal"] if m.style.get("focal") else c["milestone"]
            out.append(f'<polygon{attrs("milestone:" + m.id, "milestone-marker", f"{prefix}-ms-{m.id}")} points="{x:.2f},{y - rr:.2f} {x + rr:.2f},{y:.2f} {x:.2f},{y + rr:.2f} {x - rr:.2f},{y:.2f}" fill="{fill}"/>')
            out.append(text(m.label, "milestone:" + m.id, "milestone-label", c["text"], f"{prefix}-ms-{m.id}-label"))
        # 8 header names
        for g in self.gates:
            out.append(text(g.label, "milestone:" + g.id, "gate-label", c["gate"], f"{prefix}-ms-{g.id}-label"))
        for w in self.windows:
            cx = (w.x0 + w.x1) / 2
            y_from = w.label.y0 + w.label.h + 1
            if geo["axis_top"] - y_from > 2:  # a leader from the name down to the ruler over the span's centre
                out.append(f'<line{attrs("window:" + w.id, "window-leader")} x1="{cx:.2f}" y1="{y_from:.2f}" x2="{cx:.2f}" y2="{geo["axis_top"]:.2f}" stroke="{c["leader"]}" stroke-width="0.75"/>')
            out.append(text(w.label, "window:" + w.id, "window-label", c["text"], f"{prefix}-window-{w.id}-label"))
        for e in geo["attempt"]["header_entries"]:
            if e["item"].kind == "edge":
                out.append(text(e["item"].label, "ruler", "edge-label", c["muted"]))
        if self.compact and self.corner_lines:  # the ruler's two dates, in the rail corner, ending on the tick baseline
            lab = Label(list(self.corner_lines), 0, "corner", size=size)
            lab.x, lab.y0 = r["x"] + 8, lanes_top - 6 - lab.h
            out.append(text(lab, "ruler", "edge-label", c["muted"]))
        # 9 legend (symbols only)
        if self.spec.get("legend") and geo["legend_y"] is not None:
            rail = geo["attempt"]["legend_mode"] == "rail"
            lx, ly = (r["x"] + 8 if rail else self.chart_x0), geo["legend_y"] + self.line_h / 2
            for k, entry in enumerate(self.spec["legend"]):
                sym = entry.get("symbol")
                cid = f"legend:{k}"
                gl = 5.5 if self.compact else 7.0  # compact: samples one text line high, so stacked rows do not touch
                if sym == "gate":
                    out.append(f'<line{attrs(cid, "legend-symbol")} x1="{lx + 6:.2f}" y1="{ly - gl:.2f}" x2="{lx + 6:.2f}" y2="{ly + gl:.2f}" stroke="{c["gate"]}" stroke-width="1.5" stroke-dasharray="5 3"/>')
                elif sym == "event":
                    out.append(f'<polygon{attrs(cid, "legend-symbol")} points="{lx + 6:.2f},{ly - EVENT_R:.2f} {lx + 6 + EVENT_R:.2f},{ly + EVENT_R * 0.8:.2f} {lx + 6 - EVENT_R:.2f},{ly + EVENT_R * 0.8:.2f}" fill="{c["event"]}"/>')
                elif sym == "window":
                    out.append(f'<rect{attrs(cid, "legend-symbol")} x="{lx:.2f}" y="{ly - 6:.2f}" width="12" height="12" fill="{c["window"]}"/>')
                elif sym == "float":
                    out.append(f'<rect{attrs(cid, "legend-symbol")} x="{lx:.2f}" y="{ly - 6:.2f}" width="12" height="12" fill="none" stroke="{c["float"]}" stroke-dasharray="3 2"/>')
                elif sym == "dependency":
                    out.append(f'<path{attrs(cid, "legend-symbol")} d="M{lx:.2f} {ly:.2f} L{lx + 14:.2f} {ly:.2f}" fill="none" stroke="{c["dependency"]}" stroke-width="1.5" marker-end="url(#{prefix}-arrow)"/>')
                else:  # milestone / payment / focal diamonds
                    rr = 4.0 if self.compact else MARKER_R
                    if sym == "payment":
                        pr = rr + (2.5 if self.compact else 3.5)
                        out.append(f'<polygon{attrs(cid, "legend-symbol")} points="{lx + 6:.2f},{ly - pr:.2f} {lx + 6 + pr:.2f},{ly:.2f} {lx + 6:.2f},{ly + pr:.2f} {lx + 6 - pr:.2f},{ly:.2f}" fill="none" stroke="{c["milestone"]}" stroke-width="1"/>')
                    fill = c["focal"] if sym == "focal" else c["milestone"]
                    out.append(f'<polygon{attrs(cid, "legend-symbol")} points="{lx + 6:.2f},{ly - rr:.2f} {lx + 6 + rr:.2f},{ly:.2f} {lx + 6:.2f},{ly + rr:.2f} {lx + 6 - rr:.2f},{ly:.2f}" fill="{fill}"/>')
                lab = Label([entry["text"]], self.m.width(entry["text"], size), "legend", size=size)
                lab.x, lab.y0 = lx + 20, ly - lab.h / 2
                out.append(text(lab, cid, "legend-label", c["muted"]))
                if rail:
                    ly += self.line_h if self.compact else self.line_h + 2
                else:
                    lx += 20 + lab.w + 22
        return defs, out

    # ---------------------------------------------------------------- report
    def placed(self) -> dict:
        geo, a = self.geo, self.geo["attempt"]
        return {
            "fits": geo["fits"], "needs_h": round(a["total"], 1), "available_h": self.region["h"],
            "breakdown": {"header_names": round(a["header_h"], 1), "ruler": round(a["ruler_h"], 1),
                          "lanes": [round(h, 1) for h in a["lane_heights"]], "lanes_total": round(sum(a["lane_heights"]), 1),
                          "rows": a["rows"], "rows_per_lane": [len(r) for r in a["lane_rows"]],
                          "milestone_strip": round(a["strip_h"], 1), "legend": round(a["legend_h"], 1)},
            "density": {"rail_w": a["rail_w"], "row_gap": a["row_gap"], "lane_pad": a["lane_pad"], "pack_order": a["order"],
                        "labels_straddling_window_edges": a["straddles"], "spare_height_spent_on_window_edges": a["straddle_first"],
                        "bar_h": round(self.bar_h(), 2), "bar_mode": "thin" if self.thin else "labelled",
                        "bar_pad_y": self.pad_y, "label_px": self.size, "legend": geo["attempt"]["legend_mode"]},
            "scale": {"x_of_calendar_start": round(self.chart_x0, 3), "px_per_day": round(self.px_day, 6),
                      "px_per_week": round(7 * self.px_day, 4), "horizon_days": self.days, "extent_days": self.extent_days},
            "region": self.region, "font": self.spec["font"],
            "lanes": geo["lanes"],
            "tasks": [{"id": t.id, "lane": t.lane, "x0": round(t.x0, 2), "x1": round(t.x1, 2), "y": round(t.y, 2), "h": round(t.h, 2),
                       "row": t.row, "label": {"where": t.label.where, "lines": t.label.lines, "rect": t.label.box().list()}} for t in self.tasks],
            "markers": [{"id": m.id, "kind": m.kind, "lane": m.lane, "x": round(m.x0, 2), "y": round(m.y, 2),
                         "label": {"where": m.label.where, "lines": m.label.lines, "rect": m.label.box().list()} if m.label else None,
                         "date_x": round(self.x(m.d0), 2), "offset_weeks": round((m.x0 - self.x(m.d0)) / (7 * self.px_day), 3),
                         **({"line_segments": [[round(a0, 2), round(a1, 2)] for a0, a1 in self.gate_segments.get(m.id, [])]} if m.kind == "gate" else {})}
                        for m in self.events + self.milestones + self.gates],
            "windows": [{"id": w.id, "x0": round(w.x0, 2), "x1": round(w.x1, 2), "label": {"lines": w.label.lines, "rect": w.label.box().list()}}
                        for w in self.windows],
            "dependencies": self.deps,
        }
