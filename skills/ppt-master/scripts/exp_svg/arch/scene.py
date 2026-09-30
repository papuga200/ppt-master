#!/usr/bin/env python3
"""
PPT Master - architecture scene model (experimental)

The scene is the JSON both the creator and the four arch helpers share: zones
(regional / trust boundaries, possibly nested), nodes with measured labels,
edges (flows) with semantic source/target ids, annotations attached to an
element, and a legend whose samples are drawn from the same style table as the
marks they explain. This module owns node sizing from measured labels, the
geometric checks every tool reports, and the SVG rendering in the fork's
authoring contract (rect + text nodes, orthogonal <path> connectors whose ends
sit on node edges so pptx_text_in_shapes.py can glue them after export).

Usage:
    Library module for arrange.py, route_connections.py and move_group.py.

Dependencies:
    Pillow (through measure_labels.py)
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

_ARCH_DIR = Path(__file__).resolve().parent
if str(_ARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ARCH_DIR))

from _common import (  # noqa: E402
    CANVAS_H,
    CANVAS_W,
    FLOOR_BODY_PX,
    FLOOR_LABEL_PX,
    FLOOR_TOLERANCE,
    HelperError,
    sha256_json,
)
import measure_labels  # noqa: E402

SCHEMA = "exp_svg.arch.scene/v1"
PITCH = measure_labels.LINE_PITCH
PAD_X, PAD_Y = 12.0, 8.0
SUB_GAP = 4.0
ZONE_PAD = 16.0
CAPTION_GAP = 8.0
MIN_GAP = 4.0

DEFAULT_TYPE = {"node_px": 16.0, "sub_px": 13.333, "edge_label_px": 13.333, "zone_label_px": 13.333,
                "annotation_px": 16.0, "legend_px": 13.333}
# node names are label-class text (style contracts list node labels with the labels, floor 13.33 px); the default stays 16
TYPE_ROLES = {"node_px": "label", "sub_px": "label", "edge_label_px": "label", "zone_label_px": "label",
              "annotation_px": "body", "legend_px": "label"}
DEFAULT_STYLE = {
    "text": "#1F2937", "muted": "#4B5563", "node_fill": "#FFFFFF", "node_stroke": "#1F2937", "node_stroke_width": 1.5,
    "node_radius": 0, "label_bg": "#FFFFFF",
    # node_radius 0 exports as a `rect` preset, which the glue/adoption pass (pptx_text_in_shapes.py) fills with the node's
    # text at exact insets; a rounded `roundRect` only adopts text centred as one block (set node_text: "single").
    "node_text": "separate",
    "node_kinds": {"external": {"fill": "#F3F4F6", "dash": "5 3"}, "datastore": {"fill": "#EEF2F7"}},
    "zone_kinds": {"region": {"fill": "#F7F8FA", "stroke": "#8A96A3", "width": 1.2, "dash": None},
                   "trust": {"fill": "none", "stroke": "#B4162E", "width": 1.5, "dash": "8 4"},
                   "group": {"fill": "none", "stroke": "none", "width": 0, "dash": None}},  # layout-only container, never drawn
    "edge_kinds": {"sync": {"stroke": "#1F2937", "width": 1.5, "dash": None, "head": True},
                   "async": {"stroke": "#1F2937", "width": 1.5, "dash": "6 4", "head": True},
                   "control": {"stroke": "#B4162E", "width": 1.5, "dash": None, "head": True},
                   "association": {"stroke": "#6B7280", "width": 1.2, "dash": "3 3", "head": False}},
}


# ------------------------------------------------------------------------------------------------ geometry

def rect(box: dict) -> tuple[float, float, float, float]:
    return (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])


def overlap(a, b, pad: float = 0.0) -> bool:
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def contains(outer, inner, tol: float = 0.5) -> bool:
    return outer[0] - tol <= inner[0] and outer[1] - tol <= inner[1] and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol


def segment_hits_rect(a, b, r, pad: float = 0.0) -> bool:
    """Axis-parallel segment a-b passes through the interior of rect r (shrunk by -pad)."""
    x0, y0, x1, y1 = r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad
    if abs(a[1] - b[1]) < 0.01:
        return y0 < a[1] < y1 and min(a[0], b[0]) < x1 and max(a[0], b[0]) > x0
    if abs(a[0] - b[0]) < 0.01:
        return x0 < a[0] < x1 and min(a[1], b[1]) < y1 and max(a[1], b[1]) > y0
    # diagonal: sample
    steps = 40
    for i in range(steps + 1):
        t = i / steps
        x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        if x0 < x < x1 and y0 < y < y1:
            return True
    return False


def point_on_rect_edge(p, r, tol: float = 0.75) -> str | None:
    """Which side of rect r the point lies on (N/E/S/W), or None."""
    x, y = p
    if r[0] - tol <= x <= r[2] + tol:
        if abs(y - r[1]) <= tol:
            return "N"
        if abs(y - r[3]) <= tol:
            return "S"
    if r[1] - tol <= y <= r[3] + tol:
        if abs(x - r[0]) <= tol:
            return "W"
        if abs(x - r[2]) <= tol:
            return "E"
    return None


def distance_to_rect_edge(p, r) -> float:
    x, y = p
    dx = max(r[0] - x, 0.0, x - r[2])
    dy = max(r[1] - y, 0.0, y - r[3])
    if dx == 0 and dy == 0:  # inside: distance to nearest edge
        return min(x - r[0], r[2] - x, y - r[1], r[3] - y)
    return (dx * dx + dy * dy) ** 0.5


def segments_cross(a1, a2, b1, b2) -> bool:
    """Proper crossing of two axis-parallel segments (perpendicular, interiors intersect)."""
    ah = abs(a1[1] - a2[1]) < 0.01
    bh = abs(b1[1] - b2[1]) < 0.01
    if ah == bh:
        return False
    h1, h2, v1, v2 = (a1, a2, b1, b2) if ah else (b1, b2, a1, a2)
    y = h1[1]
    x = v1[0]
    return (min(h1[0], h2[0]) + 0.5 < x < max(h1[0], h2[0]) - 0.5) and (min(v1[1], v2[1]) + 0.5 < y < max(v1[1], v2[1]) - 0.5)


def segments_overlap_collinear(a1, a2, b1, b2, tol: float = 2.0) -> float:
    """Length two parallel segments run on top of each other (within tol px)."""
    ah = abs(a1[1] - a2[1]) < 0.01
    bh = abs(b1[1] - b2[1]) < 0.01
    av = abs(a1[0] - a2[0]) < 0.01
    bv = abs(b1[0] - b2[0]) < 0.01
    if ah and bh and abs(a1[1] - b1[1]) <= tol:
        lo = max(min(a1[0], a2[0]), min(b1[0], b2[0]))
        hi = min(max(a1[0], a2[0]), max(b1[0], b2[0]))
        return max(0.0, hi - lo)
    if av and bv and abs(a1[0] - b1[0]) <= tol:
        lo = max(min(a1[1], a2[1]), min(b1[1], b2[1]))
        hi = min(max(a1[1], a2[1]), max(b1[1], b2[1]))
        return max(0.0, hi - lo)
    return 0.0


# ------------------------------------------------------------------------------------------------ normalisation

def normalize(scene: dict) -> dict:
    """Fill defaults, validate ids and references, enforce type floors (never lowers a size)."""
    if not isinstance(scene, dict):
        raise HelperError("scene must be an object")
    scene.setdefault("schema", SCHEMA)
    scene["canvas"] = {"w": CANVAS_W, "h": CANVAS_H, **(scene.get("canvas") or {})}
    scene["region"] = scene.get("region") or {"x": 40.0, "y": 100.0, "w": 1200.0, "h": 590.0}
    scene["font"] = scene.get("font") or {"family": "Segoe UI"}
    scene["type"] = {**DEFAULT_TYPE, **(scene.get("type") or {})}
    style = dict(DEFAULT_STYLE)
    for key, value in (scene.get("style") or {}).items():
        if isinstance(value, dict) and isinstance(style.get(key), dict):
            style[key] = {**style[key], **value}
        else:
            style[key] = value
    scene["style"] = style
    for key, role in TYPE_ROLES.items():
        size = float(scene["type"][key])
        floor = FLOOR_BODY_PX if role == "body" else FLOOR_LABEL_PX
        if size + FLOOR_TOLERANCE < floor:
            raise HelperError(f"type.{key} = {size} px is under the {role} floor of {floor} px; tools never shrink "
                              f"type below the floor - raise the size")
    scene.setdefault("zones", [])
    scene.setdefault("nodes", [])
    scene.setdefault("edges", [])
    scene.setdefault("annotations", [])
    ids: list[str] = []
    for group in ("zones", "nodes", "edges", "annotations"):
        for item in scene[group]:
            if not item.get("id"):
                raise HelperError(f"every item in {group} needs an id")
            ids.append(item["id"])
    if scene.get("legend"):
        scene["legend"].setdefault("id", "legend")
        ids.append(scene["legend"]["id"])
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise HelperError(f"duplicate ids: {duplicates}")
    zone_ids = {z["id"] for z in scene["zones"]}
    node_ids = {n["id"] for n in scene["nodes"]}
    for zone in scene["zones"]:
        if zone.get("parent") and zone["parent"] not in zone_ids:
            raise HelperError(f"zone {zone['id']} names unknown parent {zone['parent']}")
    for node in scene["nodes"]:
        if node.get("zone") and node["zone"] not in zone_ids:
            raise HelperError(f"node {node['id']} names unknown zone {node['zone']}")
    for edge in scene["edges"]:
        for end in ("source", "target"):
            if edge.get(end) not in node_ids:
                raise HelperError(f"edge {edge['id']} {end} {edge.get(end)!r} is not a node id")
        kind = edge.get("kind") or "sync"
        if kind not in scene["style"]["edge_kinds"]:
            raise HelperError(f"edge {edge['id']} kind {kind!r} has no style.edge_kinds entry")
        edge["kind"] = kind
    for zone in scene["zones"]:
        zone["kind"] = zone.get("kind") or "region"
        if zone["kind"] not in scene["style"]["zone_kinds"]:
            raise HelperError(f"zone {zone['id']} kind {zone['kind']!r} has no style.zone_kinds entry")
    return scene


def zone_chain(scene: dict, zone_id: str | None) -> list[str]:
    parents = {z["id"]: z.get("parent") for z in scene["zones"]}
    chain = []
    while zone_id:
        chain.append(zone_id)
        zone_id = parents.get(zone_id)
    return chain


def zone_members(scene: dict, zone_id: str) -> tuple[list[str], list[str]]:
    """(nodes, zones) inside zone_id at any depth, the zone itself excluded."""
    zones = [z["id"] for z in scene["zones"] if z["id"] != zone_id and zone_id in zone_chain(scene, z["id"])]
    nodes = [n["id"] for n in scene["nodes"] if zone_id in zone_chain(scene, n.get("zone"))]
    return nodes, zones


def subtree(scene: dict, item_id: str) -> tuple[list[str], list[str]]:
    """(node ids, zone ids) that move with item_id: a node alone, or a zone with everything inside it."""
    if any(z["id"] == item_id for z in scene["zones"]):
        nodes, zones = zone_members(scene, item_id)
        return nodes, [item_id] + zones
    return [item_id], []


def translate(scene: dict, node_ids: list[str], zone_ids: list[str], dx: float, dy: float) -> None:
    table = by_id(scene)
    for item_id in list(node_ids) + list(zone_ids):
        box = table[item_id].get("box")
        if box is None:
            continue
        box["x"] = round(box["x"] + dx, 2)
        box["y"] = round(box["y"] + dy, 2)
        caption = table[item_id].get("caption") or {}
        if caption.get("box"):
            caption["box"]["x"] = round(caption["box"]["x"] + dx, 2)
            caption["box"]["y"] = round(caption["box"]["y"] + dy, 2)


def by_id(scene: dict) -> dict:
    table = {}
    for group in ("zones", "nodes", "edges", "annotations"):
        for item in scene[group]:
            table[item["id"]] = item
    if scene.get("legend"):
        table[scene["legend"]["id"]] = scene["legend"]
    for item in scene.get("spacers") or []:  # compose_page.py: layout slots with a size and no drawing (connector buses)
        table[item["id"]] = item
    return table


# ------------------------------------------------------------------------------------------------ measurement

def measure_text(scene: dict, text: str, size: float, role: str, weight: str = "normal", max_width: float | None = None) -> dict:
    return measure_labels.measure_label({"id": "_", "text": text, "size_px": size, "role": role, "weight": weight,
                                         "max_width": max_width}, scene["font"])


def size_node(scene: dict, node: dict, wrap_scale: float = 1.0) -> None:
    """Measured box for a node: title (bold, body size) and optional sublabel; never smaller than its text."""
    t = scene["type"]
    max_w = float(node.get("max_w") or scene.get("node_max_w") or 200.0) * wrap_scale
    pad_x, pad_y = (float(v) for v in (scene.get("node_pad") or (PAD_X, PAD_Y)))  # compose_page.py density ladder
    inner = max(max_w - 2 * pad_x, 40.0)
    title = measure_text(scene, node.get("label") or node["id"], t["node_px"], "body", "bold", inner)
    sub = measure_text(scene, node["sublabel"], t["sub_px"], "label", "normal", inner) if node.get("sublabel") else None
    text_w = max(title["width_px"], sub["width_px"] if sub else 0.0)
    title_h = len(title["lines"]) * PITCH * t["node_px"]
    sub_h = (SUB_GAP + len(sub["lines"]) * PITCH * t["sub_px"]) if sub else 0.0
    need_w = text_w + 2 * pad_x
    need_h = title_h + sub_h + 2 * pad_y
    node["measure"] = {"title_lines": title["lines"], "title_widths": title["line_widths_px"],
                       "sub_lines": sub["lines"] if sub else [], "sub_widths": sub["line_widths_px"] if sub else [],
                       "need_w": round(need_w, 2), "need_h": round(need_h, 2), "wrap_width": round(inner, 1),
                       "font_evidence": title["font"]["source"], "measurement": title["measurement"],
                       "oversized_words": title["oversized_words"] + (sub["oversized_words"] if sub else [])}
    width = max(need_w, float(node.get("min_w") or 0))
    height = max(need_h, float(node.get("min_h") or 0))
    box = node.get("box") or {}
    node["box"] = {"x": box.get("x", 0.0), "y": box.get("y", 0.0), "w": round(width, 2), "h": round(height, 2)}


def zone_caption(scene: dict, zone: dict) -> dict:
    if not zone.get("label"):
        return {"lines": [], "w": 0.0, "h": 0.0}
    size = scene["type"]["zone_label_px"]
    width = zone.get("caption_max_w")
    got = measure_text(scene, zone["label"], size, "label", "bold", float(width) if width else None)
    return {"lines": got["lines"], "w": got["width_px"], "h": round(len(got["lines"]) * PITCH * size, 2)}


def zone_insets(scene: dict, zone: dict) -> tuple[float, float, float, float]:
    """(left, top, right, bottom) space between the zone outline and its content."""
    pad = ZONE_PAD if zone.get("pad") is None else float(zone["pad"])
    caption = zone.get("caption") or zone_caption(scene, zone)
    top = pad + (caption["h"] + float(scene.get("caption_gap", CAPTION_GAP)) if caption["h"] else 0.0)
    return pad, top, pad, pad


def size_annotation(scene: dict, note: dict) -> None:
    size = scene["type"]["annotation_px"] if (note.get("role") or "body") == "body" else scene["type"]["legend_px"]
    role = note.get("role") or "body"
    got = measure_text(scene, note["text"], size, role, note.get("weight") or "normal", float(note.get("max_w") or 260))
    note["measure"] = {"lines": got["lines"], "widths": got["line_widths_px"], "size_px": size, "role": role,
                       "oversized_words": got["oversized_words"]}
    box = note.get("box") or {}
    note["box"] = {"x": box.get("x", 0.0), "y": box.get("y", 0.0), "w": round(got["width_px"], 2),
                   "h": round(len(got["lines"]) * PITCH * size, 2)}


def place_annotation(scene: dict, note: dict, table: dict) -> None:
    attach = note.get("attach") or {}
    if note.get("at"):
        note["box"]["x"], note["box"]["y"] = float(note["at"]["x"]), float(note["at"]["y"])
        return
    target = table.get(attach.get("to"))
    if target is None or "box" not in target:
        raise HelperError(f"annotation {note['id']} attaches to unknown or unplaced {attach.get('to')!r}")
    r = rect(target["box"])
    gap = float(attach.get("gap") or 8.0)
    side = attach.get("side") or "S"
    w, h = note["box"]["w"], note["box"]["h"]
    align = attach.get("align") or "center"
    if side in ("S", "N"):
        x = r[0] if align == "start" else (r[2] - w if align == "end" else (r[0] + r[2]) / 2 - w / 2)
        y = r[3] + gap if side == "S" else r[1] - gap - h
    else:
        y = r[1] if align == "start" else (r[3] - h if align == "end" else (r[1] + r[3]) / 2 - h / 2)
        x = r[2] + gap if side == "E" else r[0] - gap - w
    note["box"]["x"], note["box"]["y"] = round(x, 2), round(y, 2)


def size_legend(scene: dict) -> None:
    legend = scene.get("legend")
    if not legend:
        return
    size = scene["type"]["legend_px"]
    sample_w, gap_in, gap_between = 40.0, 8.0, 28.0
    max_w = float(legend.get("max_w") or scene["region"]["w"])
    title = measure_text(scene, legend["title"], size, "label", "bold") if legend.get("title") else None
    x = (title["width_px"] + gap_between) if title else 0.0
    y = 0.0
    row_h = PITCH * size
    items = []
    for index, item in enumerate(legend.get("items") or []):
        if not item.get("text"):
            raise HelperError(f"legend item {index} needs text")
        if item.get("kind") and item["kind"] not in scene["style"]["edge_kinds"]:
            raise HelperError(f"legend item {item['text']!r} names edge kind {item['kind']!r} with no style")
        if item.get("zone_kind") and item["zone_kind"] not in scene["style"]["zone_kinds"]:
            raise HelperError(f"legend item {item['text']!r} names zone kind {item['zone_kind']!r} with no style")
        got = measure_text(scene, item["text"], size, "label")
        width = sample_w + gap_in + got["width_px"]
        if x > 0 and x + width > max_w:
            x, y = 0.0, y + row_h + 6.0
        items.append({**item, "id": item.get("id") or f"{legend['id']}-item{index}", "dx": x, "dy": y,
                      "text_w": got["width_px"], "sample_w": sample_w, "gap": gap_in})
        x += width + gap_between
    legend["measure"] = {"items": items, "title": title["lines"][0] if title else None,
                         "title_w": title["width_px"] if title else 0.0, "size_px": size, "row_h": row_h}
    width = max([it["dx"] + it["sample_w"] + it["gap"] + it["text_w"] for it in items] + [legend["measure"]["title_w"]])
    height = y + row_h
    box = legend.get("box") or {}
    legend["box"] = {"x": box.get("x", 0.0), "y": box.get("y", 0.0), "w": round(width, 2), "h": round(height, 2)}


def place_legend(scene: dict) -> None:
    legend = scene.get("legend")
    if not legend:
        return
    region = scene["region"]
    if legend.get("at"):
        legend["box"]["x"], legend["box"]["y"] = float(legend["at"]["x"]), float(legend["at"]["y"])
    else:
        dock = legend.get("dock") or "bottom"
        if dock == "bottom":
            legend["box"]["x"] = region["x"]
            legend["box"]["y"] = round(region["y"] + region["h"] - legend["box"]["h"], 2)
        elif dock == "top":
            legend["box"]["x"], legend["box"]["y"] = region["x"], region["y"]
        else:
            raise HelperError(f"legend dock {dock!r} is not supported (top, bottom or at)")


# ------------------------------------------------------------------------------------------------ checks

def node_checks(scene: dict) -> list[dict]:
    """Residual constraints a ruler can see in placed zones, nodes, annotations and legend."""
    found: list[dict] = []
    canvas = (0.0, 0.0, scene["canvas"]["w"], scene["canvas"]["h"])
    zones = {z["id"]: z for z in scene["zones"]}
    nodes = scene["nodes"]
    for node in nodes:
        r = rect(node["box"])
        if node["box"]["w"] + 0.01 < node["measure"]["need_w"] or node["box"]["h"] + 0.01 < node["measure"]["need_h"]:
            found.append({"kind": "text_exceeds_box", "id": node["id"], "message": "the node box is smaller than its measured text"})
        if not contains(canvas, r, 0.0):
            found.append({"kind": "off_canvas", "id": node["id"], "message": f"node {node['id']} leaves the canvas"})
        chain = zone_chain(scene, node.get("zone"))
        if node.get("zone"):
            zone = zones[node["zone"]]
            left, top, right, bottom = zone_insets(scene, zone)
            inner = (zone["box"]["x"] + left - 0.5, zone["box"]["y"] + top - 0.5,
                     zone["box"]["x"] + zone["box"]["w"] - right + 0.5, zone["box"]["y"] + zone["box"]["h"] - bottom + 0.5)
            if not contains(rect(zone["box"]), r, 0.0):
                found.append({"kind": "containment_violation", "id": node["id"], "zone": zone["id"],
                              "message": f"node {node['id']} is not inside its zone {zone['id']} (a containment fact)"})
            elif not contains(inner, r, 0.0):
                found.append({"kind": "zone_padding", "id": node["id"], "zone": zone["id"],
                              "message": f"node {node['id']} sits in the padding or caption band of {zone['id']}"})
        for zone in scene["zones"]:
            if zone["id"] in chain:
                continue
            if overlap(rect(zone["box"]), r):
                found.append({"kind": "false_containment", "id": node["id"], "zone": zone["id"],
                              "message": f"node {node['id']} overlaps zone {zone['id']}, which does not contain it"})
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            if overlap(rect(a["box"]), rect(b["box"]), MIN_GAP - 0.01):
                found.append({"kind": "node_overlap", "ids": [a["id"], b["id"]],
                              "message": f"nodes {a['id']} and {b['id']} overlap or sit closer than {MIN_GAP} px"})
    for zone in scene["zones"]:
        zr = rect(zone["box"])
        caption = zone.get("caption") or {}
        if caption.get("box") and not contains(zr, rect(caption["box"]), 0.5):
            found.append({"kind": "caption_exceeds_zone", "id": zone["id"],
                          "message": f"the caption of {zone['id']} runs past its outline"})
        if not contains(canvas, zr, 0.0):
            found.append({"kind": "off_canvas", "id": zone["id"], "message": f"zone {zone['id']} leaves the canvas"})
        if zone.get("parent") and not contains(rect(zones[zone["parent"]]["box"]), zr):
            found.append({"kind": "containment_violation", "id": zone["id"], "zone": zone["parent"],
                          "message": f"zone {zone['id']} is not inside its parent {zone['parent']}"})
    zlist = scene["zones"]
    for i, a in enumerate(zlist):
        for b in zlist[i + 1:]:
            nested = a["id"] in zone_chain(scene, b["id"]) or b["id"] in zone_chain(scene, a["id"])
            if not nested and overlap(rect(a["box"]), rect(b["box"])):
                found.append({"kind": "zone_overlap", "ids": [a["id"], b["id"]],
                              "message": f"zones {a['id']} and {b['id']} overlap without nesting (a containment fact)"})
    extras = [(n["id"], "annotation", n) for n in scene["annotations"]]
    if scene.get("legend"):
        extras.append((scene["legend"]["id"], "legend", scene["legend"]))
    for item_id, kind, item in extras:
        r = rect(item["box"])
        if not contains(canvas, r, 0.0):
            found.append({"kind": "off_canvas", "id": item_id, "message": f"{kind} {item_id} leaves the canvas"})
        for node in nodes:
            if overlap(r, rect(node["box"]), 2.0):
                found.append({"kind": f"{kind}_overlaps_node", "ids": [item_id, node["id"]],
                              "message": f"{kind} {item_id} overlaps node {node['id']}"})
        for zone in scene["zones"]:
            zr = rect(zone["box"])
            if overlap(r, zr) and not contains(zr, r, 0.0):
                found.append({"kind": f"{kind}_crosses_boundary", "ids": [item_id, zone["id"]],
                              "message": f"{kind} {item_id} crosses the outline of zone {zone['id']}"})
            caption = zone.get("caption") or {}
            if caption.get("box") and overlap(r, rect(caption["box"])):
                found.append({"kind": f"{kind}_overlaps_caption", "ids": [item_id, zone["id"]],
                              "message": f"{kind} {item_id} overlaps the caption of {zone['id']}"})
    for a_index, a in enumerate(extras):
        for b in extras[a_index + 1:]:
            if overlap(rect(a[2]["box"]), rect(b[2]["box"]), 2.0):
                found.append({"kind": "text_block_overlap", "ids": [a[0], b[0]], "message": f"{a[0]} overlaps {b[0]}"})
    return found


def set_caption_box(scene: dict, zone: dict) -> None:
    caption = zone.get("caption") or zone_caption(scene, zone)
    pad = ZONE_PAD if zone.get("pad") is None else float(zone["pad"])
    caption["box"] = {"x": round(zone["box"]["x"] + pad, 2), "y": round(zone["box"]["y"] + pad * 0.6, 2),
                      "w": caption["w"], "h": caption["h"]}
    zone["caption"] = caption


# ------------------------------------------------------------------------------------------------ SVG

def _num(v: float) -> str:
    return f"{round(v, 2):g}"


def path_d(points) -> str:
    parts = [f"M{_num(points[0][0])} {_num(points[0][1])}"]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if abs(y1 - y0) < 0.01:
            parts.append(f"H{_num(x1)}")
        elif abs(x1 - x0) < 0.01:
            parts.append(f"V{_num(y1)}")
        else:
            parts.append(f"L{_num(x1)} {_num(y1)}")
    return "".join(parts)


def _text_block(lines, x, top, size, fill, weight="normal", anchor="middle", content_id=None) -> str:
    pitch = PITCH * size
    baseline = top + pitch / 2 + 0.35 * size
    spans = "".join(f'<tspan x="{_num(x)}" dy="{0 if i == 0 else _num(pitch)}">{escape(line)}</tspan>'
                    for i, line in enumerate(lines))
    weight_attr = f' font-weight="{weight}"' if weight != "normal" else ""
    data = f' data-arch-text="{escape(content_id)}"' if content_id else ""
    return (f'<text x="{_num(x)}" y="{_num(baseline)}" font-size="{_num(size)}"{weight_attr} text-anchor="{anchor}" '
            f'fill="{fill}"{data}>{spans}</text>')


def _node_text(m: dict, cx: float, top: float, t: dict, style: dict, node_id: str) -> str:
    """Title and sublabel as ONE centred <text>: one text box after export, adoptable by rounded shapes too."""
    np_, sp = t["node_px"], t["sub_px"]
    pitch_t, pitch_s = PITCH * np_, PITCH * sp
    baseline = top + pitch_t / 2 + 0.35 * np_
    spans = []
    for i, line in enumerate(m["title_lines"]):
        dy = 0 if i == 0 else pitch_t
        spans.append(f'<tspan x="{_num(cx)}" dy="{_num(dy)}" font-weight="bold">{escape(line)}</tspan>')
    for i, line in enumerate(m["sub_lines"]):
        # from the last title baseline to the first sublabel baseline: rest of the title line, the gap, half a sub line
        dy = (pitch_t / 2 - 0.35 * np_ + SUB_GAP + pitch_s / 2 + 0.35 * sp) if i == 0 else pitch_s
        spans.append(f'<tspan x="{_num(cx)}" dy="{_num(dy)}" font-size="{_num(sp)}" fill="{style["muted"]}">{escape(line)}</tspan>')
    return (f'<text x="{_num(cx)}" y="{_num(baseline)}" font-size="{_num(np_)}" text-anchor="middle" fill="{style["text"]}" '
            f'data-arch-text="{escape(node_id)}:label">{"".join(spans)}</text>')


def marker_defs(scene: dict, prefix: str) -> str:
    """One marker per edge kind. userSpaceOnUse 8 x 8 px is what the exporter maps to a DrawingML `med` triangle and what
    PowerPoint then draws (about 8 px wide for 1-2 px lines, measured 30 Sep 2026): the SVG preview and the slide agree.
    strokeWidth-relative markers do not: PowerPoint keeps a minimum head size, so they grow 1.5-2.3x after export."""
    out = []
    for kind, style in scene["style"]["edge_kinds"].items():
        if not style.get("head", True):
            continue
        out.append(f'<marker id="{prefix}-head-{kind}" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" '
                   f'markerHeight="8" markerUnits="userSpaceOnUse" orient="auto">'
                   f'<path d="M0 0 L10 5 L0 10 Z" fill="{style["stroke"]}"/></marker>')
    return "".join(out)


def render_group(scene: dict, prefix: str = "arch") -> str:
    """The diagram as one <g>: zones, nodes, edges (under nodes), edge labels, annotations, legend."""
    style = scene["style"]
    family = escape(str(scene["font"].get("family") or "Segoe UI"))
    t = scene["type"]
    out = [f'<g id="{prefix}" font-family="{family}" data-arch-scene="{SCHEMA}">']
    depth = {z["id"]: len(zone_chain(scene, z["id"])) for z in scene["zones"]}
    for zone in sorted(scene["zones"], key=lambda z: depth[z["id"]]):
        if zone["kind"] == "group":
            continue  # a layout-only container: nothing is drawn
        zs = style["zone_kinds"][zone["kind"]]
        b = zone["box"]
        dash = f' stroke-dasharray="{zs["dash"]}"' if zs.get("dash") else ""
        out.append(f'<g id="{prefix}-zone-{zone["id"]}" data-arch-id="{zone["id"]}" data-arch-role="zone">'
                   f'<rect x="{_num(b["x"])}" y="{_num(b["y"])}" width="{_num(b["w"])}" height="{_num(b["h"])}" '
                   f'fill="{zs.get("fill", "none")}" stroke="{zs["stroke"]}" stroke-width="{zs.get("width", 1.2)}"{dash}/>')
        caption = zone.get("caption") or {}
        if caption.get("lines"):
            cb = caption["box"]
            out.append(_text_block(caption["lines"], cb["x"], cb["y"], t["zone_label_px"], zs["stroke"], "bold", "start",
                                   f'{zone["id"]}:caption'))
        out.append("</g>")
    edges_svg, labels_svg = [], []
    for edge in scene["edges"]:
        route = edge.get("route")
        if not route or not route.get("points"):
            continue
        es = style["edge_kinds"][edge["kind"]]
        dash = f' stroke-dasharray="{es["dash"]}"' if es.get("dash") else ""
        head = f' marker-end="url(#{prefix}-head-{edge["kind"]})"' if es.get("head", True) else ""
        edges_svg.append(f'<path id="{prefix}-edge-{edge["id"]}" data-arch-id="{edge["id"]}" data-arch-role="edge" '
                         f'data-arch-source="{edge["source"]}" data-arch-target="{edge["target"]}" '
                         f'd="{path_d(route["points"])}" fill="none" stroke="{es["stroke"]}" '
                         f'stroke-width="{es.get("width", 1.5)}"{dash}{head}/>')
        label = route.get("label")
        if label and label.get("box"):
            lb = label["box"]
            labels_svg.append(_text_block(label["lines"], lb["x"] + lb["w"] / 2, lb["y"], t["edge_label_px"], es["stroke"],
                                          "normal", "middle", f'{edge["id"]}:label'))
    for node in scene["nodes"]:
        b = node["box"]
        ns = {"fill": style["node_fill"], "stroke": style["node_stroke"], "width": style["node_stroke_width"],
              **(style["node_kinds"].get(node.get("kind") or "", {}))}
        dash = f' stroke-dasharray="{ns["dash"]}"' if ns.get("dash") else ""
        m = node["measure"]
        cx = b["x"] + b["w"] / 2
        title_h = len(m["title_lines"]) * PITCH * t["node_px"]
        sub_h = (SUB_GAP + len(m["sub_lines"]) * PITCH * t["sub_px"]) if m["sub_lines"] else 0.0
        top = b["y"] + (b["h"] - title_h - sub_h) / 2
        out.append(f'<g id="{prefix}-node-{node["id"]}" data-arch-id="{node["id"]}" data-arch-role="node">'
                   f'<rect x="{_num(b["x"])}" y="{_num(b["y"])}" width="{_num(b["w"])}" height="{_num(b["h"])}" '
                   f'rx="{style["node_radius"]}" fill="{ns["fill"]}" stroke="{ns["stroke"]}" stroke-width="{ns["width"]}"{dash}/>')
        ink = ns.get("text") or style["text"]
        if m["sub_lines"] and style.get("node_text", "separate") == "separate":
            out.append(_text_block(m["title_lines"], cx, top, t["node_px"], ink, "bold", "middle", f'{node["id"]}:title'))
            out.append(_text_block(m["sub_lines"], cx, top + title_h + SUB_GAP, t["sub_px"], style["muted"], "normal",
                                   "middle", f'{node["id"]}:sub'))
        else:
            out.append(_node_text(m, cx, top, t, {**style, "text": ink}, node["id"]))
        out.append("</g>")
    # nodes, then flow labels and annotations, then the flows on top: the export pass that puts text into shapes (pptx_text_in_shapes.py) adopts
    # a text into the smallest shape painted beneath it, and an unglued freeform arrow's bounding box can hold another
    # flow's label (measured 30 Sep 2026: labels ended up inside unrelated arrows, and an arrow holding text is not glued)
    out.extend(labels_svg)
    for note in scene["annotations"]:
        b = note["box"]
        out.append(f'<g id="{prefix}-note-{note["id"]}" data-arch-id="{note["id"]}" data-arch-role="annotation">'
                   + _text_block(note["measure"]["lines"], b["x"], b["y"], note["measure"]["size_px"],
                                 note.get("fill") or style["muted"], note.get("weight") or "normal", "start",
                                 f'{note["id"]}:text').replace("<text ", '<text font-style="italic" ' if note.get("italic") else "<text ", 1)
                   + "</g>")
    out.extend(edges_svg)
    legend = scene.get("legend")
    if legend and legend.get("measure"):
        b = legend["box"]
        m = legend["measure"]
        parts = [f'<g id="{prefix}-legend" data-arch-id="{legend["id"]}" data-arch-role="legend">']
        if m["title"]:
            parts.append(_text_block([m["title"]], b["x"], b["y"], m["size_px"], style["text"], "bold", "start",
                                     f'{legend["id"]}:title'))
        for item in m["items"]:
            x0, y0 = b["x"] + item["dx"], b["y"] + item["dy"]
            mid = y0 + m["row_h"] / 2
            if item.get("kind"):
                es = style["edge_kinds"][item["kind"]]
                dash = f' stroke-dasharray="{es["dash"]}"' if es.get("dash") else ""
                head = f' marker-end="url(#{prefix}-head-{item["kind"]})"' if es.get("head", True) else ""
                parts.append(f'<path data-arch-legend-kind="{item["kind"]}" d="M{_num(x0)} {_num(mid)}H{_num(x0 + item["sample_w"])}" '
                             f'fill="none" stroke="{es["stroke"]}" stroke-width="{es.get("width", 1.5)}"{dash}{head}/>')
            elif item.get("zone_kind"):
                zs = style["zone_kinds"][item["zone_kind"]]
                dash = f' stroke-dasharray="{zs["dash"]}"' if zs.get("dash") else ""
                parts.append(f'<rect data-arch-legend-zone-kind="{item["zone_kind"]}" x="{_num(x0 + 4)}" y="{_num(mid - 8)}" '
                             f'width="{_num(item["sample_w"] - 8)}" height="16" fill="{zs.get("fill", "none")}" '
                             f'stroke="{zs["stroke"]}" stroke-width="{zs.get("width", 1.2)}"{dash}/>')
            parts.append(_text_block([item["text"]], x0 + item["sample_w"] + item["gap"], y0, m["size_px"], style["text"],
                                     "normal", "start", f'{item["id"]}:text'))
        parts.append("</g>")
        out.append("".join(parts))
    out.append("</g>")
    return "\n".join(out)


def render_svg(scene: dict, prefix: str = "arch", title: str | None = None) -> str:
    w, h = int(scene["canvas"]["w"]), int(scene["canvas"]["h"])
    family = escape(str(scene["font"].get("family") or "Segoe UI"))
    heading = ""
    if title:
        heading = (f'<text x="40" y="58" font-family="{family}" font-size="28" font-weight="bold" '
                   f'fill="{scene["style"]["text"]}">{escape(title)}</text>\n')
    lang = escape(str(scene.get("lang") or "en-GB"))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" lang="{lang}" '
            f'font-family="{family}">\n'
            f'<defs>{marker_defs(scene, prefix)}</defs>\n<rect width="{w}" height="{h}" fill="#FFFFFF"/>\n'
            f'{heading}{render_group(scene, prefix)}\n</svg>\n')


def scene_hash(scene: dict) -> str:
    return sha256_json({k: v for k, v in scene.items() if k != "provenance"})


def content_ids(scene: dict) -> list[str]:
    ids = [item["id"] for group in ("zones", "nodes", "edges", "annotations") for item in scene[group]]
    if scene.get("legend"):
        ids.append(scene["legend"]["id"])
    return ids
