#!/usr/bin/env python3
"""
PPT Master - route_connections (experimental architecture helper)

Route every flow of an arranged scene between the node ports it names,
around the other nodes, zone captions, annotations and the legend, then place
each flow label beside a straight segment clear of every line, box and zone
outline. Boxes are NOT moved: this is the routing-only intervention for a
bespoke placement. Each route carries target-binding evidence: which node and
side each end sits on (distance to the edge in px), whether the last segment
points into the target, what it crosses, and whether the fork's export glue
pass (pptx_text_in_shapes.py) can turn it into a PowerPoint connector glued to
both boxes (a straight line or an L/Z of at most three segments).

Unroutable flows are kept with `route: null` and a residual; nothing is
dropped. Labels that find no clear spot are placed at the least-bad candidate
and reported.

Engines:
    orthogonal (default)  in-house orthogonal visibility-grid router, bend- and
                          crossing-penalised shortest path (no dependencies)
    libavoid              libavoid (adaptagrams, LGPL-2.1-or-later) through the
                          libavoid-js WebAssembly package; set PPT_MASTER_LIBAVOID_JS
                          to its directory (it is not vendored in the fork)

Usage:
    python3 scripts/exp_svg/arch/route_connections.py --in arranged.json --out routed.json [--svg preview.svg]

Input: the `result` scene of arrange.py (or the whole arrange.py result file),
with optional per-edge `source_side` / `target_side` (N, E, S, W).

Dependencies:
    Pillow; Node.js 18+ and libavoid-js for the libavoid engine
"""

from __future__ import annotations

import heapq
import json
import os
import shutil
import subprocess
import sys
from bisect import bisect_left, bisect_right
from pathlib import Path

_ARCH_DIR = Path(__file__).resolve().parent
if str(_ARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ARCH_DIR))

from _common import HelperError, check_engine, run_cli  # noqa: E402
import scene as sc  # noqa: E402

TOOL = "exp_svg.arch.route_connections"
MARGIN = 10.0          # clearance around node boxes
STUB = 14.0            # straight run out of a port before the first bend
BEND_PENALTY = 90.0    # px-equivalent cost of one bend (keeps routes to <= 3 segments where possible)
CROSS_PENALTY = 60.0   # per crossing of an already-routed flow
SHARE_PENALTY = 6.0    # per px run on top of an already-routed flow
BORDER_PENALTY = 3.0   # per px run along a zone outline
LABEL_GAP = 4.0
LABEL_MAX_W = 170.0
SIDES = ("N", "E", "S", "W")
OUTWARD = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}
GLUE_MAX_SEGMENTS = 3
UNGLUED_PENALTY = 150.0
SHARE_TOLERANCE = 6.0
ZONE_CHANNEL = 12.0      # grid lines this far inside and outside each zone outline    # parallel runs closer than this read as one line
FOREIGN_PENALTY = 1.5    # per px inside a zone that holds neither end of the flow  # a route the export cannot glue costs as much as ~1.7 extra bends


# ------------------------------------------------------------------------------------------------ ports

def _auto_sides(a: dict, b: dict) -> tuple[str, str]:
    ax0, ay0, ax1, ay1 = sc.rect(a)
    bx0, by0, bx1, by1 = sc.rect(b)
    gap_x = max(bx0 - ax1, ax0 - bx1)
    gap_y = max(by0 - ay1, ay0 - by1)
    if gap_x >= gap_y:
        return ("E", "W") if bx0 >= ax1 or (bx0 + bx1) / 2 > (ax0 + ax1) / 2 else ("W", "E")
    return ("S", "N") if by0 >= ay1 or (by0 + by1) / 2 > (ay0 + ay1) / 2 else ("N", "S")


PORT_SPACING = 14.0


def side_span(box: dict, side: str, inset: float = 10.0) -> tuple[float, float]:
    if side in ("N", "S"):
        return box["x"] + inset, box["x"] + box["w"] - inset
    return box["y"] + inset, box["y"] + box["h"] - inset


def port_coord(port: dict) -> float:
    return port["point"][0] if port["side"] in ("N", "S") else port["point"][1]


def set_coord(port: dict, coord: float) -> None:
    coord = round(coord, 2)
    port["point"] = (coord, port["point"][1]) if port["side"] in ("N", "S") else (port["point"][0], coord)


def slot_free(ports: dict, node_id: str, side: str, coord: float, exclude: set) -> bool:
    return all(abs(port_coord(p) - coord) >= PORT_SPACING for key, p in ports.items()
               if key not in exclude and p["node"] == node_id and p["side"] == side)


def free_port(ports: dict, box: dict, node_id: str, side: str, exclude: set) -> dict | None:
    """A port on a side of a box at the first free position (centre first), or None."""
    lo, hi = side_span(box, side)
    mid = (lo + hi) / 2
    for coord in [mid] + [mid + sign * k * PORT_SPACING for k in range(1, 30) for sign in (-1, 1)]:
        if lo <= coord <= hi and slot_free(ports, node_id, side, coord, exclude):
            if side in ("N", "S"):
                point = (round(coord, 2), box["y"] if side == "N" else box["y"] + box["h"])
            else:
                point = (box["x"] if side == "W" else box["x"] + box["w"], round(coord, 2))
            return {"node": node_id, "side": side, "point": point, "shared_side": 0}
    return None


def assign_ports(scene: dict) -> dict:
    """Side and point of both ends of every edge; ends sharing a side are spread along it in the order of their partners."""
    nodes = {n["id"]: n for n in scene["nodes"]}
    ends: dict[tuple[str, str], list[tuple[str, str]]] = {}
    sides: dict[str, tuple[str, str]] = {}
    for edge in scene["edges"]:
        auto = _auto_sides(nodes[edge["source"]]["box"], nodes[edge["target"]]["box"])
        s_side = edge.get("source_side") or auto[0]
        t_side = edge.get("target_side") or auto[1]
        for side in (s_side, t_side):
            if side not in SIDES:
                raise HelperError(f"edge {edge['id']} names side {side!r} (N, E, S or W)")
        sides[edge["id"]] = (s_side, t_side)
        ends.setdefault((edge["source"], s_side), []).append((edge["id"], "source"))
        ends.setdefault((edge["target"], t_side), []).append((edge["id"], "target"))
    edges = {e["id"]: e for e in scene["edges"]}
    ports: dict[tuple[str, str], dict] = {}

    def partner_centre(edge_id: str, end: str) -> tuple[float, float]:
        other = edges[edge_id]["target" if end == "source" else "source"]
        b = nodes[other]["box"]
        return b["x"] + b["w"] / 2, b["y"] + b["h"] / 2

    for (node_id, side), members in ends.items():
        b = nodes[node_id]["box"]
        horizontal_side = side in ("N", "S")
        members.sort(key=lambda m: partner_centre(*m)[0 if horizontal_side else 1])
        length = b["w"] if horizontal_side else b["h"]
        start = b["x"] if horizontal_side else b["y"]
        count = len(members)
        for index, (edge_id, end) in enumerate(members):
            along = start + length * (index + 1) / (count + 1)
            if count == 1:  # a single end lines up with its partner when their spans overlap: a straight flow
                other = nodes[edges[edge_id]["target" if end == "source" else "source"]]["box"]
                lo = max(start, other["x"] if horizontal_side else other["y"])
                hi = min(start + length, (other["x"] + other["w"]) if horizontal_side else (other["y"] + other["h"]))
                if hi - lo > 16:
                    along = (lo + hi) / 2
            if horizontal_side:
                point = (round(along, 2), b["y"] if side == "N" else b["y"] + b["h"])
            else:
                point = (b["x"] if side == "W" else b["x"] + b["w"], round(along, 2))
            ports[(edge_id, end)] = {"node": node_id, "side": side, "point": point, "shared_side": count}
    # a flow between facing sides whose boxes overlap along that side is made straight when both ports can move there
    for edge_id, (s_side, t_side) in sides.items():
        src, dst = ports[(edge_id, "source")], ports[(edge_id, "target")]
        if OUTWARD[s_side] != tuple(-v for v in OUTWARD[t_side]):
            continue
        sb, tb = nodes[src["node"]]["box"], nodes[dst["node"]]["box"]
        lo_s, hi_s = side_span(sb, s_side)
        lo_t, hi_t = side_span(tb, t_side)
        lo, hi = max(lo_s, lo_t), min(hi_s, hi_t)
        if hi < lo:
            continue
        mid = (lo + hi) / 2
        candidates = [mid] + [mid + sign * k * PORT_SPACING / 2 for k in range(1, 40) for sign in (-1, 1)]
        for coord in candidates:
            if not lo <= coord <= hi:
                continue
            if slot_free(ports, src["node"], s_side, coord, {(edge_id, "source")}) and                     slot_free(ports, dst["node"], t_side, coord, {(edge_id, "target")}):
                set_coord(src, coord)
                set_coord(dst, coord)
                break
    return ports


# ------------------------------------------------------------------------------------------------ obstacles

def obstacles(scene: dict) -> list[dict]:
    """Rectangles a route must not enter: nodes (with clearance), zone captions, annotations, legend."""
    out = []
    for node in scene["nodes"]:
        x0, y0, x1, y1 = sc.rect(node["box"])
        out.append({"id": node["id"], "kind": "node", "rect": (x0 - MARGIN, y0 - MARGIN, x1 + MARGIN, y1 + MARGIN),
                    "core": (x0, y0, x1, y1)})
    for zone in scene["zones"]:
        caption = zone.get("caption") or {}
        if caption.get("box"):
            x0, y0, x1, y1 = sc.rect(caption["box"])
            out.append({"id": f"{zone['id']}:caption", "kind": "caption", "rect": (x0 - 4, y0 - 4, x1 + 4, y1 + 4),
                        "core": (x0, y0, x1, y1)})
    for note in scene["annotations"]:
        x0, y0, x1, y1 = sc.rect(note["box"])
        out.append({"id": note["id"], "kind": "annotation", "rect": (x0 - 6, y0 - 6, x1 + 6, y1 + 6), "core": (x0, y0, x1, y1)})
    if scene.get("legend"):
        x0, y0, x1, y1 = sc.rect(scene["legend"]["box"])
        out.append({"id": scene["legend"]["id"], "kind": "legend", "rect": (x0 - 8, y0 - 8, x1 + 8, y1 + 8),
                    "core": (x0, y0, x1, y1)})
    return out


# ------------------------------------------------------------------------------------------------ orthogonal router

class Grid:
    """Orthogonal visibility grid over obstacle edges, channel midlines and port stubs."""

    def __init__(self, scene: dict, blocks: list[dict], extra_x: list[float], extra_y: list[float]):
        self.blocks = [b["rect"] for b in blocks]
        cw, ch = scene["canvas"]["w"], scene["canvas"]["h"]
        xs = {4.0, cw - 4.0, *extra_x}
        ys = {4.0, ch - 4.0, *extra_y}
        for x0, y0, x1, y1 in self.blocks:
            xs.update((x0, x1))
            ys.update((y0, y1))
        for zone in scene["zones"]:  # channels just inside and just outside every zone outline
            x0, y0, x1, y1 = sc.rect(zone["box"])
            xs.update((x0 - ZONE_CHANNEL, x0 + ZONE_CHANNEL, x1 - ZONE_CHANNEL, x1 + ZONE_CHANNEL))
            ys.update((y0 - ZONE_CHANNEL, y0 + ZONE_CHANNEL, y1 - ZONE_CHANNEL, y1 + ZONE_CHANNEL))
        for values in (xs, ys):
            ordered = sorted(values)
            for a, b in zip(ordered, ordered[1:]):
                if b - a > 2 * MARGIN:
                    values.add((a + b) / 2)
        self.xs = sorted(round(v, 2) for v in xs if 0 <= v <= cw)
        self.ys = sorted(round(v, 2) for v in ys if 0 <= v <= ch)
        self.zone_lines = []
        for zone in scene["zones"]:
            x0, y0, x1, y1 = sc.rect(zone["box"])
            self.zone_lines += [((x0, y0), (x1, y0)), ((x0, y1), (x1, y1)), ((x0, y0), (x0, y1)), ((x1, y0), (x1, y1))]
        self.free_point = {}
        self.moves: dict[tuple[int, int, int], bool] = {}
        self.penalty_cache: dict[tuple[int, int, int], float] = {}
        self.foreign: list = []

    def inside(self, x: float, y: float) -> bool:
        return any(x0 < x < x1 and y0 < y < y1 for x0, y0, x1, y1 in self.blocks)

    def ok_point(self, i: int, j: int) -> bool:
        key = (i, j)
        if key not in self.free_point:
            self.free_point[key] = not self.inside(self.xs[i], self.ys[j])
        return self.free_point[key]

    def ok_move(self, i: int, j: int, d: int) -> bool:
        """Grid step from (i, j) in direction d (0 E, 1 S, 2 W, 3 N) stays clear of every block."""
        key = (i, j, d)
        if key in self.moves:
            return self.moves[key]
        di, dj = ((1, 0), (0, 1), (-1, 0), (0, -1))[d]
        ni, nj = i + di, j + dj
        good = 0 <= ni < len(self.xs) and 0 <= nj < len(self.ys) and self.ok_point(ni, nj)
        if good:
            a, b = (self.xs[i], self.ys[j]), (self.xs[ni], self.ys[nj])
            good = not any(sc.segment_hits_rect(a, b, r) for r in self.blocks)
        self.moves[key] = good
        return good


def _dir_index(vec: tuple[int, int]) -> int:
    return {(1, 0): 0, (0, 1): 1, (-1, 0): 2, (0, -1): 3}[vec]


def _simplify(points: list) -> list:
    out = [list(points[0])]
    for p in points[1:]:
        if abs(p[0] - out[-1][0]) < 0.01 and abs(p[1] - out[-1][1]) < 0.01:
            continue
        out.append(list(p))
    changed = True
    while changed and len(out) > 2:
        changed = False
        for k in range(1, len(out) - 1):
            a, b, c = out[k - 1], out[k], out[k + 1]
            if (abs(a[0] - b[0]) < 0.01 and abs(b[0] - c[0]) < 0.01) or (abs(a[1] - b[1]) < 0.01 and abs(b[1] - c[1]) < 0.01):
                del out[k]
                changed = True
                break
    return out


def _inside_length(a, b, r) -> float:
    """Length of an axis-parallel segment inside rect r."""
    if abs(a[1] - b[1]) < 0.01:
        if not r[1] < a[1] < r[3]:
            return 0.0
        return max(0.0, min(max(a[0], b[0]), r[2]) - max(min(a[0], b[0]), r[0]))
    if not r[0] < a[0] < r[2]:
        return 0.0
    return max(0.0, min(max(a[1], b[1]), r[3]) - max(min(a[1], b[1]), r[1]))


def _step_penalty(a, b, routed: list, zone_lines: list, foreign: list | tuple = ()) -> float:
    cost = 0.0
    for p, q in routed:
        if sc.segments_cross(a, b, p, q):
            cost += CROSS_PENALTY
        shared = sc.segments_overlap_collinear(a, b, p, q, SHARE_TOLERANCE)
        if shared:
            cost += SHARE_PENALTY * shared
    for p, q in zone_lines:
        along = sc.segments_overlap_collinear(a, b, p, q, 3.0)
        if along:
            cost += BORDER_PENALTY * along
    for r in foreign:
        cost += FOREIGN_PENALTY * _inside_length(a, b, r)
    return cost


def foreign_zones(scene: dict, edge: dict) -> list:
    """Zones that contain neither end of the flow: running through one suggests the flow transits it."""
    own = set(sc.zone_chain(scene, next(n for n in scene["nodes"] if n["id"] == edge["source"]).get("zone")))
    own |= set(sc.zone_chain(scene, next(n for n in scene["nodes"] if n["id"] == edge["target"]).get("zone")))
    return [(z["id"], sc.rect(z["box"])) for z in scene["zones"] if z["id"] not in own]


def _stub(port: dict) -> tuple[float, float]:
    ox, oy = OUTWARD[port["side"]]
    return round(port["point"][0] + ox * STUB, 2), round(port["point"][1] + oy * STUB, 2)


def _straight(src: dict, dst: dict, blocks: list, edge: dict) -> list | None:
    """A single segment between facing ports when nothing is in the way."""
    a, b = src["point"], dst["point"]
    if not (abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01):
        return None
    if OUTWARD[src["side"]] != tuple(-v for v in OUTWARD[dst["side"]]):
        return None
    ox, oy = OUTWARD[src["side"]]
    if (b[0] - a[0]) * ox + (b[1] - a[1]) * oy <= 0:
        return None
    others = [blk["rect"] for blk in blocks if blk["id"] not in (edge["source"], edge["target"])]
    if any(sc.segment_hits_rect(a, b, r) for r in others):
        return None
    return [list(a), list(b)]


def _glueable(points: list) -> bool:
    if len(points) > GLUE_MAX_SEGMENTS + 1:
        return False
    try:
        import pptx_text_in_shapes
    except ImportError:
        return True
    return pptx_text_in_shapes.elbow_connector([(p[0] * pptx_text_in_shapes.PX, p[1] * pptx_text_in_shapes.PX)
                                                for p in points]) is not None


def _facing_ok(side: str, box: dict, other: dict) -> bool:
    """A side is a sensible exit when it does not face directly away from the partner."""
    bx0, by0, bx1, by1 = sc.rect(box)
    ox0, oy0, ox1, oy1 = sc.rect(other)
    return {"E": ox1 > bx1, "W": ox0 < bx0, "N": oy0 < by0, "S": oy1 > by1}[side]


def route_orthogonal(scene: dict, ports: dict, only: set | None = None) -> tuple[dict, dict]:
    """Shortest bend- and crossing-penalised orthogonal route per edge, shortest flows first.

    An edge without declared sides whose route needs more than three segments also tries the other sensible side
    pairs (free port positions) and keeps the cheapest: a straight, L or Z route glues after export.
    With `only`, just those edges are routed; the others keep their routes and count as already-routed lines."""
    blocks = obstacles(scene)
    nodes = {n["id"]: n for n in scene["nodes"]}
    todo = [e for e in scene["edges"] if only is None or e["id"] in only]
    order = sorted(todo, key=lambda e: abs(ports[(e["id"], "source")]["point"][0] - ports[(e["id"], "target")]["point"][0])
                   + abs(ports[(e["id"], "source")]["point"][1] - ports[(e["id"], "target")]["point"][1]))
    routed_segments: list = []
    for edge in scene["edges"]:
        if only is not None and edge["id"] not in only and (edge.get("route") or {}).get("points"):
            pts = edge["route"]["points"]
            routed_segments += list(zip(map(tuple, pts), map(tuple, pts[1:])))
    routes, failures = {}, {}
    for edge in order:
        keys = ((edge["id"], "source"), (edge["id"], "target"))
        combos = [(ports[keys[0]], ports[keys[1]])]
        points = _straight(combos[0][0], combos[0][1], blocks, edge)
        if points is None:
            best = None
            tried_alternatives = False
            while True:
                extra_x, extra_y = [], []
                for port in list(ports.values()) + [p for combo in combos for p in combo]:
                    stub = _stub(port)
                    extra_x += [stub[0], port["point"][0]]
                    extra_y += [stub[1], port["point"][1]]
                # the two end boxes keep only their bare outline as an obstacle: their stubs sit in the clearance
                own = [dict(b, rect=b["core"]) if b["id"] in (edge["source"], edge["target"]) else b for b in blocks]
                grid = Grid(scene, own, extra_x, extra_y)
                grid.foreign = [r for _zid, r in foreign_zones(scene, edge)]
                for src, dst in combos:
                    if best is not None and (src, dst) == best[2]:
                        continue
                    straight = _straight(src, dst, blocks, edge)
                    if straight is not None:
                        found = (0.0, [])
                        candidate = straight
                    else:
                        found = _dijkstra(grid, _stub(src), _stub(dst), OUTWARD[src["side"]],
                                          tuple(-v for v in OUTWARD[dst["side"]]), routed_segments, edge, blocks)
                        if found is None:
                            continue
                        candidate = _simplify([src["point"]] + found[1] + [dst["point"]])
                    cost = found[0] + (0.0 if _glueable(candidate) else UNGLUED_PENALTY)
                    if best is None or cost < best[0]:
                        best = (cost, candidate, (src, dst))
                auto = not edge.get("source_side") and not edge.get("target_side")
                if tried_alternatives or not auto or (best is not None and _glueable(best[1])):
                    break
                tried_alternatives = True
                sbox, tbox = nodes[edge["source"]]["box"], nodes[edge["target"]]["box"]
                alternatives = []
                for s_side in SIDES:
                    for t_side in SIDES:
                        if (s_side, t_side) == (combos[0][0]["side"], combos[0][1]["side"]):
                            continue
                        if not (_facing_ok(s_side, sbox, tbox) or _facing_ok(t_side, tbox, sbox)):
                            continue
                        src = free_port(ports, sbox, edge["source"], s_side, set(keys))
                        dst = free_port(ports, tbox, edge["target"], t_side, set(keys))
                        if src and dst:
                            alternatives.append((src, dst))
                if not alternatives:
                    break
                combos = alternatives
            if best is None:
                failures[edge["id"]] = "no orthogonal path clear of the other boxes between any pair of ports"
                continue
            points = best[1]
            ports[keys[0]], ports[keys[1]] = best[2]
        routes[edge["id"]] = points
        routed_segments += list(zip(map(tuple, points), map(tuple, points[1:])))
    return routes, failures


def _dijkstra(grid: Grid, start, goal, start_dir, goal_dir, routed, edge, blocks):
    """A* between two stub points over the grid; cost = length + bends + crossings + shared runs. Returns (cost, path)."""
    if start[0] not in grid.xs or start[1] not in grid.ys or goal[0] not in grid.xs or goal[1] not in grid.ys:
        return None  # a port stub off the canvas: no route
    si, sj = grid.xs.index(start[0]), grid.ys.index(start[1])
    gi, gj = grid.xs.index(goal[0]), grid.ys.index(goal[1])
    gx, gy = goal
    d0 = _dir_index(start_dir)
    goal_d = _dir_index(goal_dir)
    dist = {(si, sj, d0): 0.0}
    heap = [(abs(start[0] - gx) + abs(start[1] - gy), 0.0, si, sj, d0)]
    prev = {}
    best = None
    penalties = grid.penalty_cache
    while heap:
        _f, cost, i, j, d = heapq.heappop(heap)
        if cost > dist.get((i, j, d), float("inf")) + 1e-9:
            continue
        if best is not None and _f >= best[0]:
            break
        if (i, j) == (gi, gj):
            final = cost + (0.0 if d == goal_d else BEND_PENALTY * (2 if (d + 2) % 4 == goal_d else 1))
            if best is None or final < best[0]:
                best = (final, (i, j, d))
            continue
        for nd in range(4):
            if nd == (d + 2) % 4 or not grid.ok_move(i, j, nd):
                continue
            di, dj = ((1, 0), (0, 1), (-1, 0), (0, -1))[nd]
            ni, nj = i + di, j + dj
            key = (i, j, nd)
            step = penalties.get(key)
            if step is None:
                a, b = (grid.xs[i], grid.ys[j]), (grid.xs[ni], grid.ys[nj])
                step = abs(b[0] - a[0]) + abs(b[1] - a[1]) + _step_penalty(a, b, routed, grid.zone_lines, grid.foreign)
                penalties[key] = step
            new = cost + step + (BEND_PENALTY if nd != d else 0.0)
            if new < dist.get((ni, nj, nd), float("inf")) - 1e-9:
                dist[(ni, nj, nd)] = new
                prev[(ni, nj, nd)] = (i, j, d)
                heapq.heappush(heap, (new + abs(grid.xs[ni] - gx) + abs(grid.ys[nj] - gy), new, ni, nj, nd))
    if best is None:
        return None
    state = best[1]
    path = []
    while state in prev:
        path.append([grid.xs[state[0]], grid.ys[state[1]]])
        state = prev[state]
    path.append([grid.xs[state[0]], grid.ys[state[1]]])
    path.reverse()
    return best[0], path


# ------------------------------------------------------------------------------------------------ libavoid engine

def libavoid_package(request_value: str | None) -> Path:
    found = request_value or os.environ.get("PPT_MASTER_LIBAVOID_JS")
    if not found:
        raise HelperError("the libavoid engine needs the libavoid-js package: `npm install libavoid-js@0.5.0-beta.5` in a "
                          "folder you own and set PPT_MASTER_LIBAVOID_JS to <folder>/node_modules/libavoid-js (LGPL-2.1-or-later; "
                          "not vendored in the fork)")
    path = Path(found)
    if not (path / "dist" / "index-node.mjs").is_file():
        raise HelperError(f"{path} is not a libavoid-js package (dist/index-node.mjs missing)")
    return path


def route_libavoid(scene: dict, ports: dict, package: Path) -> tuple[dict, dict, str]:
    node = os.environ.get("PPT_MASTER_NODE") or shutil.which("node")
    if not node:
        raise HelperError("the libavoid engine needs Node.js 18+ on PATH (or PPT_MASTER_NODE)")
    shapes = []
    for blk in obstacles(scene):
        x0, y0, x1, y1 = blk["core"] if blk["kind"] == "node" else blk["rect"]
        shapes.append({"id": blk["id"], "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    boxes = {n["id"]: n["box"] for n in scene["nodes"]}
    conns = []
    for edge in scene["edges"]:
        ends = {}
        auto = not edge.get("source_side") and not edge.get("target_side")
        for end in ("source", "target"):
            port = ports[(edge["id"], end)]
            b = boxes[port["node"]]
            pins = [{"dx": port["point"][0] - b["x"], "dy": port["point"][1] - b["y"], "dir": port["side"]}]
            if auto:  # the other sides are offered too (at a free spot, with a small cost): libavoid picks per route
                for side in SIDES:
                    if side == port["side"]:
                        continue
                    alt = free_port(ports, b, port["node"], side, {(edge["id"], end)})
                    if alt:
                        pins.append({"dx": alt["point"][0] - b["x"], "dy": alt["point"][1] - b["y"], "dir": side, "cost": 40})
            ends[end] = {"shape": port["node"], "pins": pins}
        conns.append({"id": edge["id"], "src": ends["source"], "dst": ends["target"]})
    payload = {"shapes": shapes, "conns": conns, "params": {"shapeBufferDistance": MARGIN, "idealNudgingDistance": 8,
                                                             "segmentPenalty": BEND_PENALTY, "crossingPenalty": 200}}
    runner = _ARCH_DIR / "libavoid_runner.mjs"
    proc = subprocess.run([node, str(runner), str(package)], input=json.dumps(payload), capture_output=True, text=True,
                          encoding="utf-8", timeout=300)
    if proc.returncode != 0:
        raise HelperError(f"libavoid failed: {proc.stderr.strip()[:600]}")
    got = json.loads(proc.stdout)["routes"]
    routes, failures = {}, {}
    for edge in scene["edges"]:
        points = got.get(edge["id"])
        if not points or len(points) < 2:
            failures[edge["id"]] = "libavoid returned no route"
            continue
        routes[edge["id"]] = _simplify([[round(x, 2), round(y, 2)] for x, y in points])
    version = json.loads((package / "package.json").read_text(encoding="utf-8")).get("version", "?")
    return routes, failures, f"libavoid-js {version}"


# ------------------------------------------------------------------------------------------------ labels

def _label_candidates(points: list, w: float, h: float, cuts: tuple = ((), ())):
    """Label boxes beside each segment (longest first): spread along it, then flush with either end or with a zone
    outline the segment crosses (`cuts` = x lines, y lines), so a label can sit wholly on one side of a boundary."""
    segments = sorted(zip(points, points[1:]), key=lambda s: -(abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1])))
    for a, b in segments:
        horizontal = abs(a[1] - b[1]) < 0.01
        length = abs(b[0] - a[0]) if horizontal else abs(b[1] - a[1])
        room = w if horizontal else h
        fits = length >= room + 12
        lo, hi = (min(a[0], b[0]), max(a[0], b[0])) if horizontal else (min(a[1], b[1]), max(a[1], b[1]))
        centres = [lo + (hi - lo) * t for t in (0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.12, 0.88)]
        centres += [lo + 6 + room / 2, hi - 6 - room / 2]
        for cut in (cuts[0] if horizontal else cuts[1]):
            if lo < cut < hi:
                centres += [cut - 6 - room / 2, cut + 6 + room / 2]
        for c in centres:
            for extra in (0.0, 6.0):
                if horizontal:
                    for y in (a[1] - LABEL_GAP - extra - h, a[1] + LABEL_GAP + extra):
                        yield {"x": round(c - w / 2, 2), "y": round(y, 2), "w": w, "h": h}, fits
                else:
                    for x in (a[0] + LABEL_GAP + 2 + extra, a[0] - LABEL_GAP - 2 - extra - w):
                        yield {"x": round(x, 2), "y": round(c - h / 2, 2), "w": w, "h": h}, fits


def _label_conflicts(box: dict, scene: dict, placed_labels: list, own_id: str) -> list[str]:
    r = sc.rect(box)
    hits = []
    cw, ch = scene["canvas"]["w"], scene["canvas"]["h"]
    if r[0] < 0 or r[1] < 0 or r[2] > cw or r[3] > ch:
        hits.append("off_canvas")
    for node in scene["nodes"]:
        if sc.overlap(r, sc.rect(node["box"]), 3.0):
            hits.append(f"node:{node['id']}")
    for edge in scene["edges"]:
        route = edge.get("route") or {}
        for a, b in zip(route.get("points") or [], (route.get("points") or [])[1:]):
            if sc.segment_hits_rect(a, b, r, 2.0 if edge["id"] != own_id else 0.5):
                hits.append(f"edge:{edge['id']}")
                break
    for other_id, other in placed_labels:
        if sc.overlap(r, sc.rect(other), 3.0):
            hits.append(f"label:{other_id}")
    for zone in scene["zones"]:
        zr = sc.rect(zone["box"])
        if sc.overlap(r, zr) and not sc.contains(zr, r, 0.0):
            hits.append(f"zone_outline:{zone['id']}")
        caption = zone.get("caption") or {}
        if caption.get("box") and sc.overlap(r, sc.rect(caption["box"]), 2.0):
            hits.append(f"caption:{zone['id']}")
    for note in scene["annotations"]:
        if sc.overlap(r, sc.rect(note["box"]), 3.0):
            hits.append(f"annotation:{note['id']}")
    if scene.get("legend") and sc.overlap(r, sc.rect(scene["legend"]["box"]), 3.0):
        hits.append("legend")
    return hits


def place_labels(scene: dict, only: set | None = None) -> list[dict]:
    residuals = []
    placed: list[tuple[str, dict]] = []
    if only is not None:
        placed = [(e["id"], e["route"]["label"]["box"]) for e in scene["edges"]
                  if e["id"] not in only and ((e.get("route") or {}).get("label") or {}).get("box")]
    size = scene["type"]["edge_label_px"]
    for edge in scene["edges"]:
        if only is not None and edge["id"] not in only:
            continue
        route = edge.get("route")
        if not edge.get("label") or not route or not route.get("points"):
            continue
        got = sc.measure_text(scene, edge["label"], size, "label", "normal", float(edge.get("label_max_w") or LABEL_MAX_W))
        w, h = round(got["width_px"] + 4, 2), round(len(got["lines"]) * sc.PITCH * size, 2)
        best = None
        cuts = ([v for z in scene["zones"] for v in (z["box"]["x"], z["box"]["x"] + z["box"]["w"])],
                [v for z in scene["zones"] for v in (z["box"]["y"], z["box"]["y"] + z["box"]["h"])])
        for box, fits in _label_candidates(route["points"], w, h, cuts):
            hits = _label_conflicts(box, scene, placed, edge["id"])
            score = len(hits) * 10 + (0 if fits else 1)
            if best is None or score < best[0]:
                best = (score, box, hits)
            if score == 0:
                break
        route["label"] = {"lines": got["lines"], "box": best[1], "conflicts": best[2]}
        placed.append((edge["id"], best[1]))
        if best[2]:
            residuals.append({"kind": "edge_label_conflict", "id": edge["id"], "conflicts": best[2],
                              "message": f"label of {edge['id']} found no clear spot beside its route: {best[2]}"})
    return residuals


# ------------------------------------------------------------------------------------------------ checks

def _binding(scene: dict, edge: dict, points: list) -> dict:
    nodes = {n["id"]: n for n in scene["nodes"]}
    evidence = {}
    for end, point, idx in (("source", points[0], 0), ("target", points[-1], -1)):
        node = nodes[edge[end]]
        r = sc.rect(node["box"])
        side = sc.point_on_rect_edge(point, r)
        others = [n["id"] for n in scene["nodes"] if n["id"] != node["id"]
                  and sc.distance_to_rect_edge(point, sc.rect(n["box"])) <= 6.0]
        evidence[end] = {"id": node["id"], "side": side, "point": [round(point[0], 2), round(point[1], 2)],
                         "distance_to_edge_px": round(abs(sc.distance_to_rect_edge(point, r)), 2),
                         "bound": side is not None, "other_nodes_within_6px": others}
    a, b = points[-2], points[-1]
    vec = (b[0] - a[0], b[1] - a[1])
    side = evidence["target"]["side"]
    inward = {"W": vec[0] > 0 and abs(vec[1]) < 0.01, "E": vec[0] < 0 and abs(vec[1]) < 0.01,
              "N": vec[1] > 0 and abs(vec[0]) < 0.01, "S": vec[1] < 0 and abs(vec[0]) < 0.01}.get(side, False)
    evidence["head_points_into_target"] = inward
    return evidence


def predict_glue(points: list, binding: dict, diagonal: bool) -> dict:
    """Whether the fork's export glue pass will make this route a connector glued to both boxes.

    Mirrors pptx_text_in_shapes.glue_connectors: both ends on a box outline, and the corners must be a preset the pass
    can draw exactly (elbow_connector: straight, L or Z; a U-turn with level ends and 4+ segments stay freeforms)."""
    if diagonal:
        return {"expected": False, "preset": None, "segments": len(points) - 1, "reason": "diagonal segment"}
    if not (binding["source"]["bound"] and binding["target"]["bound"]):
        return {"expected": False, "preset": None, "segments": len(points) - 1, "reason": "an end is not on a box outline"}
    try:
        import pptx_text_in_shapes
    except ImportError as exc:
        return {"expected": None, "preset": None, "segments": len(points) - 1, "reason": f"unverified: {exc}"}
    emu = [(p[0] * pptx_text_in_shapes.PX, p[1] * pptx_text_in_shapes.PX) for p in points]
    found = pptx_text_in_shapes.elbow_connector(emu) if len(points) <= 4 else None
    if found is None:
        why = ("four or more segments" if len(points) > 4 else "a U-turn whose ends are level: no connector preset draws it")
        return {"expected": False, "preset": None, "segments": len(points) - 1,
                "reason": f"{why}: exports as a freeform that does not follow the boxes"}
    return {"expected": True, "preset": found[0], "segments": len(points) - 1,
            "reason": "pptx_text_in_shapes.py can glue it (elbow_connector matched a preset)"}


def edge_checks(scene: dict) -> list[dict]:
    """Binding evidence and residuals for every edge; writes route.binding / route.glue / route.stats."""
    residuals = []
    all_segments = {}
    for edge in scene["edges"]:
        route = edge.get("route")
        if route and route.get("points"):
            all_segments[edge["id"]] = list(zip(map(tuple, route["points"]), map(tuple, route["points"][1:])))
    for edge in scene["edges"]:
        route = edge.get("route")
        if not route or not route.get("points"):
            residuals.append({"kind": "unrouted", "id": edge["id"], "source": edge["source"], "target": edge["target"],
                              "message": f"flow {edge['id']} ({edge['source']} -> {edge['target']}) has no route: "
                                         f"{(route or {}).get('failure', 'not routed')}"})
            continue
        points = route["points"]
        binding = _binding(scene, edge, points)
        route["binding"] = binding
        route["ports"] = {"source": binding["source"]["side"], "target": binding["target"]["side"]}
        for end in ("source", "target"):
            if not binding[end]["bound"]:
                residuals.append({"kind": "endpoint_unbound", "id": edge["id"], "end": end, "node": edge[end],
                                  "message": f"{end} end of {edge['id']} is {binding[end]['distance_to_edge_px']} px from "
                                             f"{edge[end]}'s outline"})
            if binding[end]["other_nodes_within_6px"]:
                residuals.append({"kind": "endpoint_ambiguous", "id": edge["id"], "end": end,
                                  "near": binding[end]["other_nodes_within_6px"],
                                  "message": f"{end} end of {edge['id']} also touches {binding[end]['other_nodes_within_6px']}"})
        es = scene["style"]["edge_kinds"][edge["kind"]]
        if es.get("head", True) and not binding["head_points_into_target"]:
            residuals.append({"kind": "head_not_into_target", "id": edge["id"],
                              "message": f"the last segment of {edge['id']} does not run into {edge['target']}"})
        segments = all_segments[edge["id"]]
        diagonal = [s for s in segments if abs(s[0][0] - s[1][0]) > 0.01 and abs(s[0][1] - s[1][1]) > 0.01]
        if diagonal:
            residuals.append({"kind": "diagonal_segment", "id": edge["id"], "message": f"{edge['id']} has a diagonal segment"})
        through = []
        for node in scene["nodes"]:
            if node["id"] in (edge["source"], edge["target"]):
                continue
            core = sc.rect(node["box"])
            inner = (core[0] + 1, core[1] + 1, core[2] - 1, core[3] - 1)
            if any(sc.segment_hits_rect(a, b, inner) for a, b in segments):
                through.append(node["id"])
        for node_id in (edge["source"], edge["target"]):  # a route must not cut back through its own ends
            core = sc.rect(next(n for n in scene["nodes"] if n["id"] == node_id)["box"])
            inner = (core[0] + 1, core[1] + 1, core[2] - 1, core[3] - 1)
            if any(sc.segment_hits_rect(a, b, inner) for a, b in segments):
                through.append(node_id)
        if through:
            residuals.append({"kind": "route_through_node", "id": edge["id"], "nodes": through,
                              "message": f"{edge['id']} runs through {through}"})
        crossings, shared = [], []
        for other_id, other in all_segments.items():
            if other_id == edge["id"]:
                continue
            if any(sc.segments_cross(a, b, p, q) for a, b in segments for p, q in other):
                crossings.append(other_id)
            run = sum(sc.segments_overlap_collinear(a, b, p, q, SHARE_TOLERANCE) for a, b in segments for p, q in other)
            if run > 8.0:
                shared.append(other_id)
        if shared:
            residuals.append({"kind": "shared_path", "id": edge["id"], "with": shared,
                              "message": f"{edge['id']} runs on top of {shared}: which end belongs to which flow is ambiguous"})
        boundaries = []
        for zone in scene["zones"]:
            zr = sc.rect(zone["box"])
            lines = [((zr[0], zr[1]), (zr[2], zr[1])), ((zr[0], zr[3]), (zr[2], zr[3])),
                     ((zr[0], zr[1]), (zr[0], zr[3])), ((zr[2], zr[1]), (zr[2], zr[3]))]
            along = sum(sc.segments_overlap_collinear(a, b, p, q, 2.0) for a, b in segments for p, q in lines)
            if along > 8.0:
                boundaries.append(zone["id"])
        transits = [zid for zid, r in foreign_zones(scene, edge) if sum(_inside_length(a, b, r) for a, b in segments) > 4.0]
        route["transits_zones"] = transits
        if transits:
            residuals.append({"kind": "route_transits_foreign_zone", "id": edge["id"], "zones": transits,
                              "message": f"{edge['id']} runs through {transits}, which hold neither of its ends: "
                                         f"a reader may take it to pass through that boundary"})
        if boundaries:
            residuals.append({"kind": "route_along_boundary", "id": edge["id"], "zones": boundaries,
                              "message": f"{edge['id']} runs along the outline of {boundaries}"})
        for other in scene["edges"]:
            other_points = (other.get("route") or {}).get("points")
            if other["id"] <= edge["id"] or not other_points:
                continue
            for mine in (points[0], points[-1]):
                for theirs in (other_points[0], other_points[-1]):
                    if abs(mine[0] - theirs[0]) + abs(mine[1] - theirs[1]) < 6.0:
                        residuals.append({"kind": "shared_port", "ids": [edge["id"], other["id"]], "point": list(mine),
                                          "message": f"{edge['id']} and {other['id']} end at the same point"})
        cw, ch = scene["canvas"]["w"], scene["canvas"]["h"]
        if any(not (0 <= p[0] <= cw and 0 <= p[1] <= ch) for p in points):
            residuals.append({"kind": "off_canvas", "id": edge["id"], "message": f"{edge['id']} leaves the canvas"})
        n_segments = len(points) - 1
        glue = predict_glue(points, binding, bool(diagonal))
        route["glue"] = glue
        glue_ok = glue["expected"]
        route["stats"] = {"segments": n_segments, "bends": max(0, n_segments - 1),
                          "length_px": round(sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in segments), 1),
                          "crosses": sorted(crossings)}
        if not glue_ok and not diagonal:
            residuals.append({"kind": "not_glueable", "id": edge["id"], "segments": n_segments,
                              "message": f"{edge['id']}: {glue['reason']}"})
        label = route.get("label")
        if edge.get("label") and label and label.get("conflicts"):
            pass  # reported by place_labels / re-checked below
    for edge in scene["edges"]:
        route = edge.get("route") or {}
        label = route.get("label")
        if edge.get("label") and label and label.get("box"):
            hits = _label_conflicts(label["box"], scene, [(e["id"], e["route"]["label"]["box"]) for e in scene["edges"]
                                                          if e["id"] != edge["id"] and (e.get("route") or {}).get("label")],
                                    edge["id"])
            label["conflicts"] = hits
            if hits:
                residuals.append({"kind": "edge_label_conflict", "id": edge["id"], "conflicts": hits,
                                  "message": f"label of {edge['id']} touches {hits}"})
        elif edge.get("label") and route.get("points"):
            residuals.append({"kind": "edge_label_missing", "id": edge["id"], "message": f"{edge['id']} has no placed label"})
    return residuals


# ------------------------------------------------------------------------------------------------ entry

def apply_routes(scene: dict, engine: str, libavoid: str | None, only: set | None = None) -> str:
    """Route `only` (default: every edge) and place their labels; other edges keep their routes and labels."""
    ports = assign_ports(scene)
    if engine == "orthogonal":
        routes, failures = route_orthogonal(scene, ports, only)
        version = "in-house orthogonal grid router"
    elif engine == "libavoid":
        routes, failures, version = route_libavoid(scene, ports, libavoid_package(libavoid))
    else:
        raise HelperError(f"unknown engine {engine!r} (orthogonal or libavoid)")
    for edge in scene["edges"]:
        if only is not None and edge["id"] not in only:
            continue
        if edge["id"] in routes:
            edge["route"] = {"engine": engine, "points": routes[edge["id"]],
                             "ports": {"source": ports[(edge["id"], "source")]["side"],
                                       "target": ports[(edge["id"], "target")]["side"]}}
        else:
            edge["route"] = {"engine": engine, "points": None, "failure": failures.get(edge["id"], "not routed")}
    place_labels(scene, only)
    return version


def route(scene: dict, engine: str = "orthogonal", libavoid: str | None = None) -> tuple[str, dict, list[dict]]:
    if "result" in scene and "tool" in scene:  # a whole arrange.py result file
        scene = scene["result"]
    scene = sc.normalize(scene)
    for group in ("zones", "nodes"):
        for item in scene[group]:
            if not item.get("box"):
                raise HelperError(f"{item['id']} has no box: run arrange.py first")
    version = apply_routes(scene, engine, libavoid)
    residuals = edge_checks(scene)
    residuals += sc.node_checks(scene)
    scene["provenance"] = {**(scene.get("provenance") or {}), "routed_by": {"tool": TOOL, "engine": engine, "version": version}}
    status = "ok" if not residuals else "partial"
    return status, scene, residuals


def _add_arguments(parser) -> None:
    parser.add_argument("--engine", default=None, choices=("orthogonal", "libavoid"),
                        help="routing engine (default: the request's `route_engine`, else orthogonal)")
    parser.add_argument("--libavoid", default=None, help="libavoid-js package directory (else PPT_MASTER_LIBAVOID_JS)")


def _work(request: dict, args) -> tuple[str, dict, list, list, dict]:
    body = request.get("result") if "result" in request and "tool" in request else request
    engine = args.engine or body.pop("route_engine", None) or "orthogonal"
    check_engine("routing", engine)
    status, scene, residuals = route(body, engine, args.libavoid)
    if args.svg:
        Path(args.svg).write_text(sc.render_svg(scene, title=scene.get("title")), encoding="utf-8")
    bindings = {e["id"]: {"source": (e["route"].get("binding") or {}).get("source"),
                          "target": (e["route"].get("binding") or {}).get("target"),
                          "glue_expected": (e["route"].get("glue") or {}).get("expected")} for e in scene["edges"]}
    return status, scene, residuals, sc.content_ids(scene), {"scene_sha256": sc.scene_hash(scene), "bindings": bindings}


def main(argv: list[str] | None = None) -> int:
    return run_cli(TOOL, argv, _work, _add_arguments, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
