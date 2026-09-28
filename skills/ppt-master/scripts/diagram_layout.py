#!/usr/bin/env python3
"""Lay out a flow or architecture diagram with ELK and emit coordinates plus an SVG fragment in the authoring contract.

    diagram_layout.py spec.json [--svg out.svg] [--json out.json] [--prefix dg]

A page author describes WHAT is connected; ELK (the Eclipse Layout Kernel, vendored as elkjs under vendor/elkjs, EPL-2.0,
run through Node.js) decides WHERE: layered placement in the reading direction, orthogonal routes, edge labels placed
beside their edges with space reserved, containers sized around their children. Labels are measured with the same
DrawingML width estimator the checker uses (text_measure.py), so every box holds its words at the size asked for. The
layout is fitted into the region WITHOUT going under the type floors (16 px node text, 14 px sublabels and edge labels);
when it cannot fit, other directions, tighter spacing and narrower wraps are tried, and then it stops with the size it
needs - split the diagram or give it more room, never shrink the type.

Spec (JSON; sizes in slide px):
  {
    "region": {"x": 496, "y": 120, "w": 688, "h": 420},
    "direction": "RIGHT",                      # or "DOWN"
    "font": {"family": "Segoe UI", "node_px": 16, "sub_px": 14, "label_px": 14},
    "node_max_w": 220,                         # wrap node text to this width
    "nodes": [{"id": "lint", "label": "Geometry lint", "sublabel": "certain + flagged", "kind": "step"}],
                                               # list nodes in reading order: an edge pointing back up that order is a return
                                               # kind: step | end (an outcome, drawn as a pill) | decision | external (dashed)
    "groups": [{"id": "machine", "label": "YOUR MACHINE", "children": ["you", "host"]}],   # a child may be a group
    "edges": [{"source": "review", "target": "render", "label": "repair", "kind": "return"}],
                                               # kind: flow (arrow) | return (arrow, accent) | association (dashed, no head)
    "style": {"stroke": "#1F2937", "accent": "#B4162E", "text": "#111827", "muted": "#4B5563",
              "node_fill": "#FFFFFF", "group_fill": "#F3F4F6", "group_stroke": "#9CA3AF"}
  }

Output: the JSON (every node, group and edge in slide px, edge points with the arrowhead at the last point, label boxes,
the scale used, `fits`, and `checks` - label/edge/node collisions found after layout) on stdout or --json; the SVG with
--svg: a 1280x720 page holding the fragment in its region, so it can be previewed. Paste the `<g id="<prefix>">` group
and the `<marker>` from its `<defs>` into the page, then restyle colours and weights; do not move boxes or bend points by
hand - change the spec and run it again. Arrows are `<path>` elements of horizontal and vertical segments ending on the
node edges with `marker-end`: after export they become connectors glued to both boxes (pptx_text_in_shapes.py).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import text_measure  # noqa: E402

FLOOR_NODE_PX = 16.0
FLOOR_LABEL_PX = 14.0
PAD_X, PAD_Y = 12.0, 10.0
TITLE_PITCH, SUB_PITCH, LABEL_PITCH = 1.25, 1.4, 1.3
DEFAULT_STYLE = {"stroke": "#1F2937", "accent": "#B4162E", "text": "#111827", "muted": "#4B5563",
                 "node_fill": "#FFFFFF", "end_fill": "#F3F4F6", "group_fill": "#F3F4F6", "group_stroke": "#9CA3AF"}


class LayoutError(RuntimeError):
    pass


def node_executable() -> str:
    found = os.environ.get("PPT_MASTER_NODE") or shutil.which("node")
    if not found:
        raise LayoutError("diagram_layout.py needs Node.js 18 or later to run the vendored elkjs: put `node` on PATH or set "
                          "PPT_MASTER_NODE to node's full path. Nothing was laid out.")
    return found


def run_elk(graph):
    """Lay out one ELK graph (dict) or several (list) in one Node process."""
    runner = SCRIPTS / "diagram_layout_elk.js"
    if not (SCRIPTS / "vendor" / "elkjs" / "elk.bundled.js").is_file():
        raise LayoutError("vendor/elkjs/elk.bundled.js is missing: see vendor/elkjs/NOTICE.md to restore it")
    proc = subprocess.run([node_executable(), str(runner)], input=json.dumps(graph), capture_output=True, text=True, encoding="utf-8", timeout=120)
    if proc.returncode != 0:
        raise LayoutError(f"ELK failed: {proc.stderr.strip()[:600]}")
    return json.loads(proc.stdout)


def wrap(text: str, size: float, max_width: float, family: str, weight: str = "normal") -> tuple[list[str], float]:
    if not text:
        return [], 0.0
    lines, widths, _ = text_measure.wrap_text(text, size=size, max_width=max_width, family=family, weight=weight)
    return lines, max(widths) if widths else 0.0


def measure_node(node: dict, font: dict, max_w: float) -> dict:
    family = font["family"]
    inner = max_w - 2 * PAD_X
    title, title_w = wrap(node.get("label", node["id"]), font["node_px"], inner, family, "bold")
    sub, sub_w = wrap(node.get("sublabel", ""), font["sub_px"], inner, family)
    block = len(title) * TITLE_PITCH * font["node_px"] + (0.4 * font["sub_px"] + len(sub) * SUB_PITCH * font["sub_px"] if sub else 0.0)
    width = max(float(node.get("min_w") or 0), max(title_w, sub_w) + 2 * PAD_X + (font["node_px"] if node.get("kind") == "end" else 0))
    height = max(float(node.get("min_h") or 0), block + 2 * PAD_Y)
    return {"title": title, "sub": sub, "w": round(width, 1), "h": round(height, 1)}


def build_graph(spec: dict, measured: dict, labels: dict, direction: str, spacing: float, aspect: float | None = None) -> dict:
    font = spec["font"]
    groups = {g["id"]: g for g in spec.get("groups") or []}
    parent: dict[str, str] = {}
    for group in groups.values():
        for child in group.get("children") or []:
            parent[child] = group["id"]

    # a return (a loop) leaves its node and re-enters its target from the same side, under the row (or beside the column):
    # the U-shaped route a reader recognises as "goes back to", with room for its arrowhead
    loop_side = "SOUTH" if direction == "RIGHT" else "EAST"
    ports: dict[str, list] = {}
    for index, edge in enumerate(spec.get("edges") or []):
        if edge.get("kind") == "return":
            ports.setdefault(edge["source"], []).append({"id": f"p{index}s", "width": 0, "height": 0, "layoutOptions": {"elk.port.side": loop_side}})
            ports.setdefault(edge["target"], []).append({"id": f"p{index}t", "width": 0, "height": 0, "layoutOptions": {"elk.port.side": loop_side}})

    def elk_node(item_id: str) -> dict:
        if item_id in groups:
            caption = 1.4 * font["label_px"] + 12 if groups[item_id].get("label") else 12
            return {"id": item_id, "layoutOptions": {"elk.padding": f"[top={caption + 8:.0f},left=16,bottom=16,right=16]"},
                    "children": [elk_node(child) for child in groups[item_id].get("children") or []]}
        node = {"id": item_id, "width": measured[item_id]["w"], "height": measured[item_id]["h"]}
        if item_id in ports:
            node["ports"] = ports[item_id]
            node["layoutOptions"] = {"elk.portConstraints": "FIXED_SIDE"}
        return node

    # model order is reading order: a group takes the place of its first member, so ELK's model-order cycle breaking
    # treats exactly the edges that point back up the reading order as returns
    top: list[str] = []
    for node in spec["nodes"]:
        outer = node["id"]
        while outer in parent:
            outer = parent[outer]
        if outer not in top:
            top.append(outer)
    top += [g for g in groups if g not in parent and g not in top]
    edges = []
    for index, edge in enumerate(spec.get("edges") or []):
        returning = edge.get("kind") == "return"
        item = {"id": f"e{index}", "sources": [f"p{index}s" if returning else edge["source"]], "targets": [f"p{index}t" if returning else edge["target"]]}
        if labels.get(index):
            item["labels"] = [{"id": f"e{index}l", "text": " ".join(labels[index]["lines"]), "width": labels[index]["w"], "height": labels[index]["h"],
                               "layoutOptions": {"elk.edgeLabels.placement": "CENTER"}}]
        edges.append(item)
    return {"id": "root", "layoutOptions": {
        "elk.algorithm": "layered", "elk.direction": direction, "elk.edgeRouting": "ORTHOGONAL",
        "elk.hierarchyHandling": "INCLUDE_CHILDREN", "elk.json.edgeCoords": "ROOT", "elk.json.shapeCoords": "ROOT",
        "elk.edgeLabels.inline": "false", "elk.padding": "[top=0,left=0,bottom=0,right=0]",
        "elk.layered.considerModelOrder.strategy": "NODES_AND_EDGES", "elk.layered.cycleBreaking.strategy": "MODEL_ORDER",
        "elk.layered.nodePlacement.strategy": spec.get("placement", "NETWORK_SIMPLEX"),
        "elk.layered.spacing.nodeNodeBetweenLayers": f"{64 * spacing:.0f}", "elk.spacing.nodeNode": f"{36 * spacing:.0f}",
        "elk.spacing.edgeNode": f"{20 * spacing:.0f}", "elk.spacing.edgeEdge": f"{14 * spacing:.0f}",
        "elk.layered.spacing.edgeNodeBetweenLayers": f"{20 * spacing:.0f}", "elk.layered.spacing.edgeEdgeBetweenLayers": f"{12 * spacing:.0f}",
        "elk.spacing.edgeLabel": "6", "elk.layered.nodePlacement.favorStraightEdges": "true", "elk.layered.feedbackEdges": "true",
        **({"elk.layered.wrapping.strategy": "MULTI_EDGE", "elk.aspectRatio": f"{aspect:.2f}"} if aspect else {}),
        **(spec.get("elk") or {})},
        "children": [elk_node(item) for item in top], "edges": edges}


def collect(result: dict) -> tuple[dict, dict]:
    boxes: dict[str, dict] = {}

    def walk(node: dict) -> None:
        for child in node.get("children") or []:
            boxes[child["id"]] = {"x": child["x"], "y": child["y"], "w": child["width"], "h": child["height"]}
            walk(child)
    walk(result)
    edges = {}

    def walk_edges(node: dict) -> None:
        for edge in node.get("edges") or []:
            edges[edge["id"]] = edge
        for child in node.get("children") or []:
            walk_edges(child)
    walk_edges(result)
    return boxes, edges


def _ordered_sections(sections: list[dict]) -> list[dict]:
    """ELK splits some edges into sections linked by ids; walk them from the one with no incoming section."""
    if len(sections) < 2:
        return sections
    by_id = {s["id"]: s for s in sections}
    start = next((s for s in sections if not s.get("incomingSections")), sections[0])
    ordered, seen = [start], {start["id"]}
    while ordered[-1].get("outgoingSections"):
        nxt = next((by_id[i] for i in ordered[-1]["outgoingSections"] if i in by_id and i not in seen), None)
        if nxt is None:
            break
        ordered.append(nxt)
        seen.add(nxt["id"])
    return ordered if len(ordered) == len(sections) else sections


def _segments(points):
    return list(zip(points, points[1:]))


def _rect_hits_segment(rect, a, b, pad: float = 0.0) -> bool:
    x0, y0, x1, y1 = rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad
    if abs(a[1] - b[1]) < 0.01:  # horizontal
        return y0 < a[1] < y1 and min(a[0], b[0]) < x1 and max(a[0], b[0]) > x0
    if abs(a[0] - b[0]) < 0.01:  # vertical
        return x0 < a[0] < x1 and min(a[1], b[1]) < y1 and max(a[1], b[1]) > y0
    return False


def _overlap(a, b, pad: float = 0.0) -> bool:
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def layout(spec: dict) -> dict:
    spec = dict(spec)
    spec["font"] = {"family": "Segoe UI", "node_px": 16, "sub_px": 14, "label_px": 14, **(spec.get("font") or {})}
    font = spec["font"]
    if font["node_px"] < FLOOR_NODE_PX or min(font["sub_px"], font["label_px"]) < FLOOR_LABEL_PX:
        raise LayoutError(f"the spec asks for type under the floors ({FLOOR_NODE_PX:.0f} px node text, {FLOOR_LABEL_PX:.0f} px sublabels and labels)")
    ids = [n["id"] for n in spec.get("nodes") or []]
    if not ids or len(set(ids)) != len(ids):
        raise LayoutError("the spec needs nodes with unique ids")
    known = set(ids) | {g["id"] for g in spec.get("groups") or []}
    for edge in spec.get("edges") or []:
        if edge.get("source") not in known or edge.get("target") not in known:
            raise LayoutError(f"edge {edge.get('source')} -> {edge.get('target')} names an unknown node")
    region = spec.get("region") or {"x": 64, "y": 140, "w": 1152, "h": 500}
    direction = str(spec.get("direction") or "RIGHT").upper()
    other = "DOWN" if direction == "RIGHT" else "RIGHT"
    max_w = float(spec.get("node_max_w") or 220)
    # in order of preference: the direction asked for, looser before tighter; the other direction last
    attempts = [(d, spacing, max_w * shrink, same, wrapped) for wrapped in (False, True) for d in (direction, other) for spacing, shrink in
                ((1.0, 1.0), (0.75, 1.0), (0.55, 1.0), (0.75, 0.8), (0.55, 0.8), (0.55, 0.65))
                for same in ((True, False) if spec.get("uniform_width", True) else (False,))]
    prepared = []
    for att_direction, spacing, wrap_w, same_width, wrapped in attempts:
        measured = {n["id"]: measure_node(n, font, wrap_w) for n in spec["nodes"]}
        labels = {}
        for index, edge in enumerate(spec.get("edges") or []):
            if edge.get("label"):
                lines, width = wrap(edge["label"], font["label_px"], max(90.0, min(170.0, wrap_w)), font["family"])
                labels[index] = {"lines": lines, "w": round(width + 4, 1), "h": round(len(lines) * LABEL_PITCH * font["label_px"] + 2, 1)}
        if spec.get("uniform", True):  # equal boxes read as one row of steps, and keep the arrows between them straight
            steps = [m for n, m in zip(spec["nodes"], measured.values()) if n.get("kind", "step") in ("step", "decision", "external")]
            if steps:
                tallest = max(m["h"] for m in steps)
                widest = max(m["w"] for m in steps)
                for m in steps:
                    m["h"] = tallest
                    if same_width:
                        m["w"] = widest
        prepared.append((att_direction, spacing, wrap_w, measured, labels, wrapped))
    # a long chain that fits neither way is folded into rows (ELK graph wrapping) to the region's proportions
    results = run_elk([build_graph(spec, measured, labels, d, spacing, region["w"] / region["h"] if wrapped else None)
                       for d, spacing, _, measured, labels, wrapped in prepared])
    # the type floors bound the scale from below: a layout that needs more shrinking than that does not fit, and is shown
    # at the floor (overflowing its region) rather than with type nobody can read
    floor_scale = max(FLOOR_NODE_PX / font["node_px"], FLOOR_LABEL_PX / min(font["sub_px"], font["label_px"]))
    candidates = []
    for (att_direction, spacing, wrap_w, measured, labels, _), result in zip(prepared, results):
        if result is None:
            continue  # ELK could not lay out this variant
        width, height = float(result.get("width") or 1), float(result.get("height") or 1)
        wanted = min(1.0, region["w"] / width, region["h"] / height)
        fits = wanted >= floor_scale - 1e-4
        placed = place(spec, {"result": result, "measured": measured, "labels": labels, "scale": max(wanted, floor_scale), "fits": fits,
                              "direction": att_direction, "spacing": spacing, "wrap": wrap_w, "size": (width, height)}, region)
        sound = all(abs(a[0] - b[0]) < 0.2 or abs(a[1] - b[1]) < 0.2 for e in placed["edges"] for a, b in _segments(e["points"]))
        if sound:
            candidates.append((placed, wanted))
    if not candidates:
        raise LayoutError("ELK returned no orthogonal layout for this graph")
    # the first in order of preference that fits with a clean ruler check; else the first that fits; else the least overflow
    for placed, _ in candidates:
        if placed["fits"] and not placed["checks"]:
            return placed
    for placed, _ in candidates:
        if placed["fits"]:
            return placed
    return max(candidates, key=lambda item: item[1])[0]


def place(spec: dict, chosen: dict, region: dict) -> dict:
    font, scale = spec["font"], chosen["scale"]
    width, height = chosen["size"]
    ox = region["x"] + (region["w"] - width * scale) / 2
    oy = region["y"] + (region["h"] - height * scale) / 2
    tx = lambda v: round(ox + v * scale, 1)  # noqa: E731
    ty = lambda v: round(oy + v * scale, 1)  # noqa: E731
    boxes, elk_edges = collect(chosen["result"])
    groups = {g["id"]: g for g in spec.get("groups") or []}
    out_nodes, out_groups, out_edges = {}, {}, []
    for node in spec["nodes"]:
        b = boxes[node["id"]]
        m = chosen["measured"][node["id"]]
        out_nodes[node["id"]] = {"x": tx(b["x"]), "y": ty(b["y"]), "w": round(b["w"] * scale, 1), "h": round(b["h"] * scale, 1),
                                 "kind": node.get("kind", "step"), "title": m["title"], "sub": m["sub"]}
    for gid, group in groups.items():
        b = boxes[gid]
        out_groups[gid] = {"x": tx(b["x"]), "y": ty(b["y"]), "w": round(b["w"] * scale, 1), "h": round(b["h"] * scale, 1), "label": group.get("label", "")}
    for index, edge in enumerate(spec.get("edges") or []):
        elk_edge = elk_edges[f"e{index}"]
        points = []
        for section in _ordered_sections(elk_edge.get("sections") or []):
            chain = [section["startPoint"]] + list(section.get("bendPoints") or []) + [section["endPoint"]]
            for p in chain:
                q = (tx(p["x"]), ty(p["y"]))
                if not points or abs(points[-1][0] - q[0]) > 0.05 or abs(points[-1][1] - q[1]) > 0.05:
                    points.append(q)
        points = [list(p) for p in points]
        for a, b in zip(points, points[1:]):  # ELK leaves sub-pixel steps where a route crosses a container: square them off
            if abs(b[1] - a[1]) <= 1.5 and abs(b[0] - a[0]) > 1.5:
                b[1] = a[1]
            elif abs(b[0] - a[0]) <= 1.5 and abs(b[1] - a[1]) > 1.5:
                b[0] = a[0]
        item = {"source": edge["source"], "target": edge["target"], "kind": edge.get("kind", "flow"), "points": points}
        if chosen["labels"].get(index):
            lab = (elk_edge.get("labels") or [{}])[0]
            item["label"] = {"x": tx(lab.get("x", 0)), "y": ty(lab.get("y", 0)), "w": round(chosen["labels"][index]["w"] * scale, 1),
                             "h": round(chosen["labels"][index]["h"] * scale, 1), "lines": chosen["labels"][index]["lines"]}
        out_edges.append(item)
    sizes = {"node_px": round(font["node_px"] * scale, 1), "sub_px": round(font["sub_px"] * scale, 1), "label_px": round(font["label_px"] * scale, 1)}
    placed = {"region": region, "direction": chosen["direction"], "scale": round(scale, 4), "fits": chosen["fits"], "font": {**font, **sizes},
              "needs": {"w": round(chosen["size"][0], 1), "h": round(chosen["size"][1], 1)},
              "nodes": out_nodes, "groups": out_groups, "edges": out_edges}
    placed["checks"] = checks(placed)
    placed["attempt"] = {"direction": chosen["direction"], "spacing": chosen["spacing"], "wrap": round(chosen["wrap"], 1)}
    return placed


def checks(placed: dict) -> list[str]:
    """What a ruler says about the result: labels off every line and every box, no box on another, arrows ending on boxes."""
    found = []
    node_rects = {k: (v["x"], v["y"], v["x"] + v["w"], v["y"] + v["h"]) for k, v in placed["nodes"].items()}
    label_rects = [(i, (e["label"]["x"], e["label"]["y"], e["label"]["x"] + e["label"]["w"], e["label"]["y"] + e["label"]["h"]))
                   for i, e in enumerate(placed["edges"]) if e.get("label")]
    for i, rect in label_rects:
        for j, edge in enumerate(placed["edges"]):
            if any(_rect_hits_segment(rect, a, b, 1.0) for a, b in _segments(edge["points"])):
                found.append(f"label of edge {i} ({placed['edges'][i]['source']}->{placed['edges'][i]['target']}) touches edge {j}")
        for name, node in node_rects.items():
            if _overlap(rect, node):
                found.append(f"label of edge {i} overlaps node {name}")
        for k, other in label_rects:
            if k > i and _overlap(rect, other):
                found.append(f"labels of edges {i} and {k} overlap")
    names = list(node_rects)
    for a_index, a in enumerate(names):
        for b in names[a_index + 1:]:
            if _overlap(node_rects[a], node_rects[b], -0.5):
                found.append(f"nodes {a} and {b} overlap")
    for j, edge in enumerate(placed["edges"]):
        for name, rect in node_rects.items():
            if name in (edge["source"], edge["target"]):
                continue
            inner = (rect[0] + 1, rect[1] + 1, rect[2] - 1, rect[3] - 1)
            if any(_rect_hits_segment(inner, a, b) for a, b in _segments(edge["points"])):
                found.append(f"edge {j} ({edge['source']}->{edge['target']}) runs through node {name}")
    if not placed["fits"]:
        found.append(f"does not fit the region at the type floors: the layout needs {placed['needs']['w']:.0f} x {placed['needs']['h']:.0f} px at full size; "
                     f"the region is {placed['region']['w']:.0f} x {placed['region']['h']:.0f} - split the diagram or give it more room")
    return found


def _path_d(points) -> str:
    parts = [f"M{points[0][0]:g} {points[0][1]:g}"]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if abs(y1 - y0) < 0.05:
            parts.append(f"H{x1:g}")
        elif abs(x1 - x0) < 0.05:
            parts.append(f"V{y1:g}")
        else:
            parts.append(f"L{x1:g} {y1:g}")
    return "".join(parts)


def svg_fragment(placed: dict, spec: dict, prefix: str = "dg") -> tuple[str, str]:
    """(defs, group): the arrowhead markers and the diagram group, in the authoring contract."""
    style = {**DEFAULT_STYLE, **(spec.get("style") or {})}
    font = placed["font"]
    family = escape(font["family"])
    defs = (f'<marker id="{prefix}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<polygon points="0,0 10,5 0,10" fill="{style["stroke"]}"/></marker>'
            f'<marker id="{prefix}-arrow-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<polygon points="0,0 10,5 0,10" fill="{style["accent"]}"/></marker>')
    out = [f'<g id="{prefix}" font-family="{family}">']
    for gid, g in sorted(placed["groups"].items(), key=lambda kv: kv[1]["w"] * kv[1]["h"], reverse=True):
        out.append(f'<rect id="{prefix}-{gid}" x="{g["x"]:g}" y="{g["y"]:g}" width="{g["w"]:g}" height="{g["h"]:g}" fill="{style["group_fill"]}" '
                   f'stroke="{style["group_stroke"]}" stroke-width="1.2"/>')
        if g["label"]:
            out.append(f'<text x="{g["x"] + 16:g}" y="{g["y"] + 12 + font["label_px"]:g}" font-size="{font["label_px"]:g}" font-weight="bold" '
                       f'fill="{style["muted"]}">{escape(g["label"])}</text>')
    for nid, n in placed["nodes"].items():
        kind = n["kind"]
        rx = n["h"] / 2 if kind == "end" else 3
        fill = style["end_fill"] if kind == "end" else style["node_fill"]
        stroke = style["accent"] if kind == "decision" else style["stroke"]
        extra = ' stroke-dasharray="5 3"' if kind == "external" else ""
        out.append(f'<rect id="{prefix}-{nid}" x="{n["x"]:g}" y="{n["y"]:g}" width="{n["w"]:g}" height="{n["h"]:g}" rx="{rx:g}" fill="{fill}" '
                   f'stroke="{stroke}" stroke-width="{2 if kind == "decision" else 1.5}"{extra}/>')
        cx = round(n["x"] + n["w"] / 2, 1)
        np_, sp = font["node_px"], font["sub_px"]
        block = len(n["title"]) * TITLE_PITCH * np_ + ((0.4 * sp + len(n["sub"]) * SUB_PITCH * sp) if n["sub"] else 0)
        top = n["y"] + (n["h"] - block) / 2
        baseline = top + TITLE_PITCH * np_ * 0.5 + 0.35 * np_
        spans = "".join(f'<tspan x="{cx:g}" dy="{0 if i == 0 else round(TITLE_PITCH * np_, 2):g}">{escape(line)}</tspan>' for i, line in enumerate(n["title"]))
        out.append(f'<text x="{cx:g}" y="{baseline:.1f}" font-size="{np_:g}" font-weight="bold" text-anchor="middle" fill="{style["text"]}">{spans}</text>')
        if n["sub"]:
            sub_top = top + len(n["title"]) * TITLE_PITCH * np_ + 0.4 * sp
            sub_base = sub_top + SUB_PITCH * sp * 0.5 + 0.35 * sp
            spans = "".join(f'<tspan x="{cx:g}" dy="{0 if i == 0 else round(SUB_PITCH * sp, 2):g}">{escape(line)}</tspan>' for i, line in enumerate(n["sub"]))
            out.append(f'<text x="{cx:g}" y="{sub_base:.1f}" font-size="{sp:g}" text-anchor="middle" fill="{style["muted"]}">{spans}</text>')
    for index, e in enumerate(placed["edges"]):
        if len(e["points"]) < 2:
            continue
        colour = style["accent"] if e["kind"] == "return" else style["stroke"]
        marker = "" if e["kind"] == "association" else f' marker-end="url(#{prefix}-arrow{"-accent" if e["kind"] == "return" else ""})"'
        dash = ' stroke-dasharray="4 3"' if e["kind"] == "association" else ""
        out.append(f'<path id="{prefix}-e{index}" d="{_path_d(e["points"])}" fill="none" stroke="{colour}" stroke-width="1.5"{dash}{marker}/>')
        if e.get("label"):
            lab = e["label"]
            lp = font["label_px"]
            cx = round(lab["x"] + lab["w"] / 2, 1)
            base = lab["y"] + LABEL_PITCH * lp * 0.5 + 0.35 * lp + 1
            spans = "".join(f'<tspan x="{cx:g}" dy="{0 if i == 0 else round(LABEL_PITCH * lp, 2):g}">{escape(line)}</tspan>' for i, line in enumerate(lab["lines"]))
            out.append(f'<text x="{cx:g}" y="{base:.1f}" font-size="{lp:g}" text-anchor="middle" fill="{colour}">{spans}</text>')
    out.append("</g>")
    return defs, "\n".join(out)


def standalone_svg(defs: str, group: str, width: int = 1280, height: int = 720) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">\n'
            f'<defs>{defs}</defs>\n<rect width="{width}" height="{height}" fill="#FFFFFF"/>\n{group}\n</svg>\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("spec", help="the diagram spec (JSON file)")
    parser.add_argument("--svg", help="write a previewable 1280x720 SVG holding the fragment")
    parser.add_argument("--json", help="write the coordinates here instead of stdout")
    parser.add_argument("--prefix", default="dg", help="id prefix of the emitted elements (default dg)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    try:
        placed = layout(spec)
    except LayoutError as error:
        print(f"diagram_layout: {error}", file=sys.stderr)
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
        print(f"diagram_layout: CHECK {item}", file=sys.stderr)
    return 0 if placed["fits"] else 3


if __name__ == "__main__":
    sys.exit(main())
