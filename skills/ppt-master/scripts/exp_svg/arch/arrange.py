#!/usr/bin/env python3
"""
PPT Master - arrange (experimental architecture helper)

Place the named objects of an architecture scene: nodes auto-sized from their
MEASURED labels (measure_labels.py), zones (regional / trust boundaries) laid
out as rows, columns or an aligned grid inside a fixed frame or fitted around
their content, then relative-placement operations applied in order
(right_of, left_of, below, above, align, distribute, same_size, place).
Annotations attach to the element they explain; the legend is measured and
docked. Nothing is ever removed or shortened to fit: when a zone's content
cannot fit its frame at the type floors (after narrower wraps are tried) the
result is `capacity_failure` with the binding numbers, and the best draft is
still returned.

Engines:
    primitive (default)  the relative-placement path above (deterministic, no deps)
    elk                  full auto-layout through the fork's diagram_layout.py
                         (vendored elkjs, EPL-2.0): placement AND orthogonal routes

Usage:
    python3 scripts/exp_svg/arch/arrange.py --in scene.json --out arranged.json [--svg preview.svg]

Scene (sizes in slide px; see scene.py for defaults):
    {"region": {"x": 40, "y": 100, "w": 1200, "h": 590},
     "font": {"family": "Segoe UI", "files": {"normal": "...segoeui.ttf", "bold": "...segoeuib.ttf"}},
     "zones": [{"id": "eu", "label": "EU region", "kind": "region", "frame": {"x":..,"y":..,"w":..,"h":..},
                "layout": {"type": "rows", "rows": [["api", "orders"], ["db"]], "gap_x": 32, "gap_y": 28,
                           "justify": "space-evenly", "align_columns": false}}],
     "nodes": [{"id": "api", "label": "API gateway", "sublabel": "TLS, auth", "zone": "eu", "max_w": 200}],
     "edges": [{"id": "f1", "source": "api", "target": "orders", "label": "order calls", "kind": "sync"}],
     "annotations": [{"id": "n1", "text": "...", "attach": {"to": "db", "side": "S", "gap": 8}}],
     "legend": {"dock": "bottom", "items": [{"kind": "sync", "text": "Synchronous call"}]},
     "constraints": [{"op": "right_of", "id": "x", "of": "y", "gap": 40, "align": "center"}]}

Dependencies:
    Pillow; Node.js 18+ for the elk engine
"""

from __future__ import annotations

import sys
from pathlib import Path

_ARCH_DIR = Path(__file__).resolve().parent
if str(_ARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ARCH_DIR))

from _common import HelperError, check_engine, run_cli  # noqa: E402
import scene as sc  # noqa: E402

TOOL = "exp_svg.arch.arrange"
WRAP_SCALES = (1.0, 0.9, 0.8, 0.7, 0.6)
DEFAULT_GAP_X, DEFAULT_GAP_Y = 32.0, 28.0


# ------------------------------------------------------------------------------------------------ layouts

def _grid_lists(layout: dict) -> tuple[list[list[str]], bool]:
    """Normalised rows (list of item-id lists) and whether axes are swapped (a columns layout)."""
    kind = layout.get("type") or "rows"
    if kind == "rows":
        return [list(r) for r in layout["rows"]], False
    if kind == "columns":
        return [list(c) for c in layout["columns"]], True
    if kind == "grid":
        items, cols = list(layout["items"]), int(layout.get("columns") or 2)
        return [items[i:i + cols] for i in range(0, len(items), cols)], False
    raise HelperError(f"layout type {kind!r} is not supported (rows, columns, grid)")


def _spread(extra: float, count: int, justify: str) -> tuple[float, float]:
    """(leading offset, added gap) for `count` items sharing `extra` px."""
    if extra <= 0 or count <= 0:
        return 0.0, 0.0
    if justify == "start":
        return 0.0, 0.0
    if justify == "center" or count == 1 and justify == "space-between":
        return extra / 2, 0.0
    if justify == "space-between":
        return 0.0, extra / (count - 1)
    return extra / (count + 1), extra / (count + 1)  # space-evenly


def _pair_gap(layout: dict, a: str, b: str, main_gap: float) -> float:
    """Gap between two row neighbours: the layout gap, or more when a labelled flow runs between them."""
    gaps = layout.get("label_gaps") or {}
    return max(main_gap, gaps.get(f"{a}|{b}", 0.0), gaps.get(f"{b}|{a}", 0.0))


def _column_gaps(layout: dict, rows: list, main_gap: float) -> list[float]:
    ncols = max(len(r) for r in rows)
    return [max([main_gap] + [_pair_gap(layout, r[c], r[c + 1], main_gap) for r in rows if c + 1 < len(r)])
            for c in range(ncols - 1)]


def layout_extent(layout: dict, sizes: dict) -> tuple[float, float]:
    rows, swapped = _grid_lists(layout)
    gx = float(layout.get("gap_x", DEFAULT_GAP_X))
    gy = float(layout.get("gap_y", DEFAULT_GAP_Y))
    main_gap, cross_gap = (gy, gx) if swapped else (gx, gy)
    dims = [[(sizes[i][1], sizes[i][0]) if swapped else sizes[i] for i in row] for row in rows]
    if layout.get("align_columns"):
        ncols = max(len(r) for r in dims)
        col_w = [max((r[c][0] for r in dims if c < len(r)), default=0.0) for c in range(ncols)]
        main = sum(col_w) + sum(_column_gaps(layout, rows, main_gap))
    else:
        main = max(sum(d[0] for d in r) + sum(_pair_gap(layout, a, b, main_gap) for a, b in zip(row, row[1:]))
                   for r, row in zip(dims, rows))
    cross = sum(max(d[1] for d in r) for r in dims) + cross_gap * (len(dims) - 1)
    return (cross, main) if swapped else (main, cross)


def layout_place(layout: dict, sizes: dict, origin: tuple[float, float], avail: tuple[float, float]) -> dict:
    """Top-left of every item; rows centred on their line, extra space spread per `justify`."""
    rows, swapped = _grid_lists(layout)
    gx = float(layout.get("gap_x", DEFAULT_GAP_X))
    gy = float(layout.get("gap_y", DEFAULT_GAP_Y))
    main_gap, cross_gap = (gy, gx) if swapped else (gx, gy)
    justify = layout.get("justify") or "space-evenly"
    justify_cross = layout.get("justify_rows") or justify
    ox, oy = origin
    avail_main, avail_cross = (avail[1], avail[0]) if swapped else avail
    dims = [[(sizes[i][1], sizes[i][0]) if swapped else sizes[i] for i in row] for row in rows]
    row_cross = [max(d[1] for d in r) for r in dims]
    total_cross = sum(row_cross) + cross_gap * (len(dims) - 1)
    lead_c, add_c = _spread(avail_cross - total_cross, len(dims), justify_cross)
    placed = {}
    cursor_c = lead_c
    ncols = max(len(r) for r in dims)
    col_w = [max((r[c][0] for r in dims if c < len(r)), default=0.0) for c in range(ncols)]
    col_gaps = _column_gaps(layout, rows, main_gap) if layout.get("align_columns") else []
    for row, row_dims, rc in zip(rows, dims, row_cross):
        if layout.get("align_columns"):
            widths = col_w[:len(row)] if len(row) == ncols else col_w
            gaps = col_gaps[:len(widths) - 1]
            total_main = sum(widths) + sum(gaps)
            lead_m, add_m = _spread(avail_main - total_main, len(widths), justify)
            cursor_m = lead_m
            slots = []
            for k, w in enumerate(widths):
                slots.append((cursor_m, w))
                cursor_m += w + (gaps[k] if k < len(gaps) else 0.0) + add_m
            slots = slots[:len(row)]
        else:
            gaps = [_pair_gap(layout, a, b, main_gap) for a, b in zip(row, row[1:])]
            total_main = sum(d[0] for d in row_dims) + sum(gaps)
            lead_m, add_m = _spread(avail_main - total_main, len(row), justify)
            cursor_m = lead_m
            slots = []
            for k, d in enumerate(row_dims):
                slots.append((cursor_m, d[0]))
                cursor_m += d[0] + (gaps[k] if k < len(gaps) else 0.0) + add_m
        for item, d, (slot_start, slot_w) in zip(row, row_dims, slots):
            m = slot_start + (slot_w - d[0]) / 2
            c = cursor_c + (rc - d[1]) / 2
            x, y = (c, m) if swapped else (m, c)
            placed[item] = (round(ox + x, 2), round(oy + y, 2))
        cursor_c += rc + cross_gap + add_c
    return placed


# ------------------------------------------------------------------------------------------------ primitive engine

def _zone_depths(scene: dict) -> dict:
    return {z["id"]: len(sc.zone_chain(scene, z["id"])) for z in scene["zones"]}


def _layout_items(zone: dict) -> list[str]:
    rows, _ = _grid_lists(zone["layout"])
    return [i for r in rows for i in r]


def _box_of(scene: dict, table: dict, item_id: str) -> dict:
    item = table.get(item_id)
    if item is None:
        raise HelperError(f"constraint names unknown id {item_id!r}")
    return item["box"]


def _apply_op(scene: dict, table: dict, op: dict, placed: set, residuals: list) -> None:
    kind = op.get("op")

    def move_to(item_id: str, x: float | None, y: float | None) -> None:
        box = _box_of(scene, table, item_id)
        dx = 0.0 if x is None else x - box["x"]
        dy = 0.0 if y is None else y - box["y"]
        nodes, zones = sc.subtree(scene, item_id)
        sc.translate(scene, nodes, zones, dx, dy)
        placed.update(nodes)
        placed.update(zones)

    def need(item_id: str) -> dict:
        if item_id not in placed:
            raise HelperError(f"constraint {kind} refers to {item_id!r} before it is placed; order the constraints")
        return _box_of(scene, table, item_id)

    if kind == "place":
        move_to(op["id"], float(op["x"]), float(op["y"]))
    elif kind in ("right_of", "left_of", "below", "above"):
        ref = need(op["of"])
        box = _box_of(scene, table, op["id"])
        gap = float(op.get("gap", 40.0))
        align = op.get("align", "center")
        if kind in ("right_of", "left_of"):
            x = ref["x"] + ref["w"] + gap if kind == "right_of" else ref["x"] - gap - box["w"]
            y = {"top": ref["y"], "bottom": ref["y"] + ref["h"] - box["h"],
                 "center": ref["y"] + (ref["h"] - box["h"]) / 2}.get(align)
            move_to(op["id"], x, None if y is None else y)
        else:
            y = ref["y"] + ref["h"] + gap if kind == "below" else ref["y"] - gap - box["h"]
            x = {"left": ref["x"], "right": ref["x"] + ref["w"] - box["w"],
                 "center": ref["x"] + (ref["w"] - box["w"]) / 2}.get(align)
            move_to(op["id"], None if x is None else x, y)
    elif kind == "align":
        ids = list(op["ids"])
        edge = op.get("edge", "cy")
        to = op.get("to", ids[0])
        if isinstance(to, (int, float)):
            value = float(to)
        else:
            ref = need(to)
            value = {"left": ref["x"], "right": ref["x"] + ref["w"], "top": ref["y"], "bottom": ref["y"] + ref["h"],
                     "cx": ref["x"] + ref["w"] / 2, "cy": ref["y"] + ref["h"] / 2}[edge]
        for item_id in ids:
            if item_id == to:
                continue
            box = _box_of(scene, table, item_id)
            if edge in ("left", "right", "cx"):
                x = value if edge == "left" else (value - box["w"] if edge == "right" else value - box["w"] / 2)
                move_to(item_id, x, None)
            else:
                y = value if edge == "top" else (value - box["h"] if edge == "bottom" else value - box["h"] / 2)
                move_to(item_id, None, y)
    elif kind == "distribute":
        ids = list(op["ids"])
        axis = op.get("axis", "x")
        boxes = [_box_of(scene, table, i) for i in ids]
        size_key, pos_key = ("w", "x") if axis == "x" else ("h", "y")
        if "span" in op:
            start, end = (float(v) for v in op["span"])
            total = sum(b[size_key] for b in boxes)
            gap = (end - start - total) / max(1, len(ids) - 1)
            if gap < sc.MIN_GAP:
                residuals.append({"kind": "capacity", "op": "distribute", "ids": ids,
                                  "needs_px": round(total + sc.MIN_GAP * (len(ids) - 1), 1), "has_px": round(end - start, 1),
                                  "message": f"distribute cannot fit {ids} into {end - start:.0f} px"})
        else:
            start = boxes[0][pos_key] if ids[0] in placed else float(op.get("start", 0.0))
            gap = float(op.get("gap", DEFAULT_GAP_X))
        cursor = start
        for item_id, box in zip(ids, boxes):
            move_to(item_id, cursor if axis == "x" else None, cursor if axis == "y" else None)
            cursor += box[size_key] + gap
    elif kind == "same_size":
        ids = list(op["ids"])
        dims = op.get("dims", "both")
        items = [table[i] for i in ids]
        if dims in ("w", "both"):
            w = max(i["box"]["w"] for i in items)
            for i in items:
                i["box"]["w"] = w
        if dims in ("h", "both"):
            h = max(i["box"]["h"] for i in items)
            for i in items:
                i["box"]["h"] = h
    else:
        raise HelperError(f"unknown constraint op {kind!r}")


def _label_gaps(scene: dict, zone: dict) -> None:
    rows, swapped = _grid_lists(zone["layout"])
    if swapped or not zone["layout"].get("reserve_label_gaps", True) or "label_gaps" in zone["layout"]:
        return
    # a labelled flow between two row neighbours needs its label's width between them (plus 14 px each side)
    neighbours = {frozenset((a, b)) for row in rows for a, b in zip(row, row[1:])}
    gaps = {}
    for edge in scene["edges"]:
        pair = frozenset((edge["source"], edge["target"]))
        if edge.get("label") and pair in neighbours:
            got = sc.measure_text(scene, edge["label"], scene["type"]["edge_label_px"], "label", "normal",
                                  float(edge.get("label_max_w") or 170.0))
            key = f"{edge['source']}|{edge['target']}"
            gaps[key] = max(gaps.get(key, 0.0), round(got["width_px"] + 28.0, 1))
    if gaps:
        zone["layout"]["label_gaps"] = gaps


def _resize(scene: dict, zone: dict, table: dict, scale: float) -> tuple[float, float]:
    """Content size of a layout zone with its nodes (and nested unframed zones) wrapped at `scale`."""
    items = _layout_items(zone)
    node_ids = {n["id"] for n in scene["nodes"]}
    for item in items:
        if item not in node_ids and table[item].get("layout") and not table[item].get("frame"):
            child = table[item]
            w, h = _resize(scene, child, table, scale)
            left, top, right, bottom = sc.zone_insets(scene, child)
            width = max(w + left + right, child["caption"]["w"] + left + right)
            box = child.get("box") or {"x": 0.0, "y": 0.0}
            child["box"] = {"x": box.get("x", 0.0), "y": box.get("y", 0.0), "w": round(width, 2), "h": round(h + top + bottom, 2)}
    node_items = [i for i in items if i in node_ids]
    for item in node_items:
        sc.size_node(scene, table[item], scale)
    if zone["layout"].get("uniform") and node_items:
        w = max(table[i]["box"]["w"] for i in node_items)
        h = max(table[i]["box"]["h"] for i in node_items)
        for i in node_items:
            table[i]["box"]["w"], table[i]["box"]["h"] = w, h
    _label_gaps(scene, zone)
    sizes = {i: (table[i]["box"]["w"], table[i]["box"]["h"]) for i in items}
    return layout_extent(zone["layout"], sizes)


def _fit_zone_layout(scene: dict, zone: dict, table: dict) -> tuple[tuple[float, float], list[dict]]:
    """Size a layout zone's content; a framed zone tries narrower wraps (nested zones included) until it fits."""
    items = _layout_items(zone)
    node_ids = {n["id"] for n in scene["nodes"]}
    for item in items:
        if item not in table:
            raise HelperError(f"zone {zone['id']} layout names unknown id {item!r}")
        zone_ids = {z["id"] for z in scene["zones"]}
        if item not in node_ids and item not in zone_ids:
            continue  # an annotation or the legend takes a layout slot like a box (its measured text block)
        owner = table[item].get("zone") if item in node_ids else table[item].get("parent")
        if owner != zone["id"]:
            raise HelperError(f"zone {zone['id']} layout lists {item!r}, which does not belong to that zone")
    left, top, right, bottom = sc.zone_insets(scene, zone)
    frame = zone.get("frame")
    if not frame:
        return _resize(scene, zone, table, 1.0), []
    avail_w = float(frame["w"]) - left - right
    avail_h = float(frame["h"]) - top - bottom
    attempts = []
    for scale in WRAP_SCALES:
        need_w, need_h = _resize(scene, zone, table, scale)
        attempts.append((scale, need_w, need_h))
        if need_w <= avail_w + 0.01 and need_h <= avail_h + 0.01:
            zone["wrap_scale"] = scale
            return (need_w, need_h), []
    best = min(attempts, key=lambda a: max(0.0, a[1] - avail_w) + max(0.0, a[2] - avail_h))
    _resize(scene, zone, table, best[0])
    zone["wrap_scale"] = best[0]
    residual = {"kind": "capacity", "zone": zone["id"], "needs": {"w": round(best[1], 1), "h": round(best[2], 1)},
                "has": {"w": round(avail_w, 1), "h": round(avail_h, 1)},
                "binding": [d for d, over in (("width", best[1] > avail_w + 0.01), ("height", best[2] > avail_h + 0.01)) if over],
                "tried_wrap_scales": list(WRAP_SCALES),
                "items": {i: [round(table[i]["box"]["w"]), round(table[i]["box"]["h"])] for i in items if table[i].get("box")},
                "message": (f"zone {zone['id']} needs {best[1]:.0f} x {best[2]:.0f} px for its {len(items)} items at the type "
                            f"floors; its frame holds {avail_w:.0f} x {avail_h:.0f}. Nothing was dropped or shrunk: give it more "
                            f"room or change the structure")}
    return (best[1], best[2]), [residual]


def arrange_primitive(scene: dict) -> tuple[list[dict], dict]:
    table = sc.by_id(scene)
    for zone in scene["zones"]:
        if zone.get("frame") and not zone.get("caption_max_w"):  # a framed zone wraps its caption to the frame
            zone["caption_max_w"] = float(zone["frame"]["w"]) - 2 * float(zone.get("pad") or sc.ZONE_PAD)
        zone["caption"] = sc.zone_caption(scene, zone)
    for node in scene["nodes"]:
        sc.size_node(scene, node)
    for note in scene["annotations"]:
        sc.size_annotation(scene, note)
    sc.size_legend(scene)
    sc.place_legend(scene)
    residuals: list[dict] = []
    depths = _zone_depths(scene)
    content: dict[str, tuple[float, float]] = {}
    # size pass, innermost zones first
    for zone in sorted(scene["zones"], key=lambda z: -depths[z["id"]]):
        left, top, right, bottom = sc.zone_insets(scene, zone)
        if zone.get("layout"):
            size, found = _fit_zone_layout(scene, zone, table)
            content[zone["id"]] = size
            residuals += found
        if zone.get("frame"):
            f = zone["frame"]
            zone["box"] = {"x": float(f["x"]), "y": float(f["y"]), "w": float(f["w"]), "h": float(f["h"])}
        elif zone.get("layout"):
            w, h = content[zone["id"]]
            at = zone.get("at") or {}
            width = max(w + left + right, zone["caption"]["w"] + left + right)
            zone["box"] = {"x": float(at.get("x", 0.0)), "y": float(at.get("y", 0.0)),
                           "w": round(width, 2), "h": round(h + top + bottom, 2)}
        else:
            zone["box"] = None  # fitted around its members after placement
    placed: set[str] = set()
    for zone in scene["zones"]:
        if zone.get("frame") or zone.get("at"):
            placed.add(zone["id"])
    for node in scene["nodes"]:
        if node.get("at"):
            node["box"]["x"], node["box"]["y"] = float(node["at"]["x"]), float(node["at"]["y"])
            placed.add(node["id"])
    # position pass, outermost first: a layout zone places its items inside its box
    for zone in sorted(scene["zones"], key=lambda z: depths[z["id"]]):
        if not zone.get("layout") or zone.get("box") is None:
            continue
        left, top, right, bottom = sc.zone_insets(scene, zone)
        b = zone["box"]
        sizes = {i: (table[i]["box"]["w"], table[i]["box"]["h"]) for i in _layout_items(zone)}
        spots = layout_place(zone["layout"], sizes, (b["x"] + left, b["y"] + top), (b["w"] - left - right, b["h"] - top - bottom))
        for item, (x, y) in spots.items():
            nodes, zones = sc.subtree(scene, item)
            if table[item].get("box") is None:
                continue
            dx, dy = x - table[item]["box"]["x"], y - table[item]["box"]["y"]
            sc.translate(scene, nodes, zones, dx, dy)
            placed.add(item)
            placed.update(nodes)
            placed.update(zones)
    for op in scene.get("constraints") or []:
        _apply_op(scene, table, op, placed, residuals)
    # zones with neither frame nor layout wrap their members
    for zone in sorted(scene["zones"], key=lambda z: -depths[z["id"]]):
        if zone["box"] is not None:
            continue
        nodes, zones = sc.zone_members(scene, zone["id"])
        members = [table[i]["box"] for i in nodes + zones if table[i].get("box")]
        if not members:
            raise HelperError(f"zone {zone['id']} has no frame, no layout and no placed members")
        left, top, right, bottom = sc.zone_insets(scene, zone)
        x0 = min(m["x"] for m in members) - left
        y0 = min(m["y"] for m in members) - top
        x1 = max(max(m["x"] + m["w"] for m in members) + right, x0 + zone["caption"]["w"] + left + right)
        y1 = max(m["y"] + m["h"] for m in members) + bottom
        zone["box"] = {"x": round(x0, 2), "y": round(y0, 2), "w": round(x1 - x0, 2), "h": round(y1 - y0, 2)}
        placed.add(zone["id"])
    unplaced = [n["id"] for n in scene["nodes"] if n["id"] not in placed]
    if unplaced:
        raise HelperError(f"nodes with no layout slot, `at` or constraint: {unplaced}")
    for zone in scene["zones"]:
        sc.set_caption_box(scene, zone)
    slotted = {i for z in scene["zones"] if z.get("layout") for i in _layout_items(z)}
    for note in scene["annotations"]:
        if note["id"] in slotted:  # placed by its layout slot, not by `attach`
            note["at"] = {"x": note["box"]["x"], "y": note["box"]["y"]}
        sc.place_annotation(scene, note, table)
    legend = scene.get("legend")
    if legend and legend["id"] in slotted:
        legend["at"] = {"x": legend["box"]["x"], "y": legend["box"]["y"]}
    return residuals, {"engine": "primitive"}


# ------------------------------------------------------------------------------------------------ ELK engine

def arrange_elk(scene: dict) -> tuple[list[dict], dict]:
    """Full auto-layout through the fork's diagram_layout.py; zones become ELK compound nodes."""
    import diagram_layout

    t = scene["type"]
    region = dict(scene["region"])
    sc.size_legend(scene)
    if scene.get("legend"):
        region["h"] = region["h"] - scene["legend"]["box"]["h"] - 16.0
    deviations = []
    sub_px, label_px = max(t["sub_px"], diagram_layout.FLOOR_LABEL_PX), max(t["edge_label_px"], diagram_layout.FLOOR_LABEL_PX)
    if sub_px != t["sub_px"] or label_px != t["edge_label_px"]:
        deviations.append(f"diagram_layout.py enforces a {diagram_layout.FLOOR_LABEL_PX:g} px label floor: sublabels and edge "
                          f"labels set at {label_px:g} px instead of {t['edge_label_px']:g} px")
    groups = []
    for zone in scene["zones"]:
        children = [n["id"] for n in scene["nodes"] if n.get("zone") == zone["id"]]
        children += [z["id"] for z in scene["zones"] if z.get("parent") == zone["id"]]
        groups.append({"id": zone["id"], "label": zone.get("label", ""), "children": children})
    kind_map = {"external": "external"}
    spec = {"region": region, "direction": scene.get("direction", "RIGHT"),
            "font": {"family": scene["font"].get("family", "Segoe UI"), "node_px": t["node_px"], "sub_px": sub_px,
                     "label_px": label_px},
            "node_max_w": float(scene.get("node_max_w") or 200.0), "uniform": False,
            "nodes": [{"id": n["id"], "label": n.get("label", n["id"]), "sublabel": n.get("sublabel", ""),
                       "kind": kind_map.get(n.get("kind") or "", "step")} for n in scene["nodes"]],
            "groups": groups,
            "edges": [{"source": e["source"], "target": e["target"], "label": e.get("label", ""),
                       "kind": "association" if e["kind"] == "association" else "flow"} for e in scene["edges"]]}
    try:
        placed = diagram_layout.layout(spec)
    except diagram_layout.LayoutError as exc:
        raise HelperError(f"ELK layout failed: {exc}") from exc
    residuals: list[dict] = []
    if placed["scale"] < 0.999:
        residuals.append({"kind": "type_scaled", "scale": placed["scale"],
                          "message": f"diagram_layout scaled the drawing by {placed['scale']}: type is smaller than requested"})
    t["sub_px"], t["edge_label_px"] = placed["font"]["sub_px"], placed["font"]["label_px"]
    for node in scene["nodes"]:
        got = placed["nodes"][node["id"]]
        sc.size_node(scene, node)
        title_widths = [sc.measure_text(scene, line, t["node_px"], "body", "bold")["width_px"] for line in got["title"]]
        sub_widths = [sc.measure_text(scene, line, t["sub_px"], "label")["width_px"] for line in got["sub"]]
        title_h = len(got["title"]) * sc.PITCH * t["node_px"]
        sub_h = (sc.SUB_GAP + len(got["sub"]) * sc.PITCH * t["sub_px"]) if got["sub"] else 0.0
        node["measure"].update({"title_lines": got["title"], "sub_lines": got["sub"], "title_widths": title_widths,
                                "sub_widths": sub_widths,
                                "need_w": round(max(title_widths + sub_widths) + 2 * sc.PAD_X, 2),
                                "need_h": round(min(got["h"], title_h + sub_h + 2 * sc.PAD_Y), 2)})
        node["box"] = {"x": got["x"], "y": got["y"], "w": got["w"], "h": got["h"]}
    for zone in scene["zones"]:
        got = placed["groups"][zone["id"]]
        zone["box"] = {"x": got["x"], "y": got["y"], "w": got["w"], "h": got["h"]}
        zone["caption"] = sc.zone_caption(scene, zone)
        zone["pad"] = 16.0
        sc.set_caption_box(scene, zone)
    for index, edge in enumerate(scene["edges"]):
        got = placed["edges"][index]
        route = {"engine": "elk", "points": [list(p) for p in got["points"]]}
        if got.get("label"):
            lab = got["label"]
            route["label"] = {"lines": lab["lines"], "box": {"x": lab["x"], "y": lab["y"], "w": lab["w"], "h": lab["h"]}}
        edge["route"] = route
    if not placed["fits"]:
        residuals.append({"kind": "capacity", "needs": placed["needs"], "has": {"w": region["w"], "h": region["h"]},
                          "message": (f"ELK needs {placed['needs']['w']:.0f} x {placed['needs']['h']:.0f} px at the type floors; "
                                      f"the region holds {region['w']:.0f} x {region['h']:.0f}. Nothing was dropped or shrunk")})
    for message in placed["checks"]:
        if "does not fit" not in message:
            residuals.append({"kind": "elk_check", "message": message})
    sc.place_legend(scene)
    table = sc.by_id(scene)
    for note in scene["annotations"]:
        sc.size_annotation(scene, note)
        sc.place_annotation(scene, note, table)
    return residuals, {"engine": "elk", "elk_attempt": placed["attempt"], "deviations": deviations,
                       "elk_version": "elkjs 0.12.0 (vendored)"}


# ------------------------------------------------------------------------------------------------ entry

def arrange(scene: dict, engine: str = "primitive") -> tuple[str, dict, list[dict]]:
    scene = sc.normalize(scene)
    if engine == "elk":
        residuals, info = arrange_elk(scene)
    elif engine == "primitive":
        residuals, info = arrange_primitive(scene)
    else:
        raise HelperError(f"unknown engine {engine!r} (primitive or elk)")
    residuals += sc.node_checks(scene)
    if engine == "elk":
        import route_connections
        residuals += route_connections.edge_checks(scene)
    scene["provenance"] = {**(scene.get("provenance") or {}), "arranged_by": {"tool": TOOL, **info}}
    if any(r["kind"] == "capacity" for r in residuals):
        status = "capacity_failure"
    elif residuals:
        status = "partial"
    else:
        status = "ok"
    return status, scene, residuals


def _add_arguments(parser) -> None:
    parser.add_argument("--engine", default=None, choices=("primitive", "elk"),
                        help="placement engine (default: the request's `engine`, else primitive)")


def _work(request: dict, args) -> tuple[str, dict, list, list, dict]:
    engine = args.engine or request.pop("engine", None) or "primitive"
    request.pop("engine", None)
    check_engine("placement", engine)
    status, scene, residuals = arrange(request, engine)
    if args.svg:
        Path(args.svg).write_text(sc.render_svg(scene, title=scene.get("title")), encoding="utf-8")
    return status, scene, residuals, sc.content_ids(scene), {"scene_sha256": sc.scene_hash(scene)}


def main(argv: list[str] | None = None) -> int:
    return run_cli(TOOL, argv, _work, _add_arguments, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
