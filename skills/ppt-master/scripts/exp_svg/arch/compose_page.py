#!/usr/bin/env python3
"""
PPT Master - compose_page (experimental architecture helper, package B)

One call from facts to the finished slide file. The request is an
architecture scene (see arrange.py) plus two blocks:

  `page`  the template, the per-slide texts (eyebrow, title, source, folio)
          and the body region, handled by ../page_compose.py: texts are
          measured with the font file and wrapped, the chrome is copied
          verbatim, and the file is written in the form the export gate
          accepts.
  `root`  a layout (rows, columns or grid, exactly like a zone's `layout`)
          over the whole body region. It may list top-level zones, nodes
          outside every zone, annotations and the legend. With it no zone
          needs a `frame` and no node needs a `place` constraint: every box
          is sized from its measured text and the tool computes every
          coordinate.

The tool then runs the package's placement and routing (arrange primitive,
route orthogonal), reports what a ruler can see (capacity, overlaps, routes
that could not be drawn cleanly) and writes the whole page. Nothing is ever
dropped, merged or shrunk below the type floors.

  `buses` (optional) a bus is a vertical trunk that gathers many-to-many flows
          between two columns, e.g. four sources read by two connectors. List
          the bus id in a layout (it takes a narrow slot between the columns)
          and write each flow in two parts: source -> bus (no arrowhead) and
          bus -> target (arrowhead, optional label). Every branch is a straight
          horizontal line, so arrange the rows so that each node has a clear
          horizontal run to its bus; a blocked branch is reported, never bent
          through a box.

Extras over arrange.py scenes:
  - a zone of `kind: "group"` is a layout-only container (never drawn);
  - an annotation or the legend may be listed in any layout and then takes
    a slot like a box; annotations accept `fill`, `weight`, `italic`;
  - `style.node_kinds.<kind>.text` sets the label colour of a node kind.

Usage:
    python3 scripts/exp_svg/arch/compose_page.py --in scene.json --out composed.json --page <project>/svg_output/<page>.svg

Dependencies:
    Pillow
"""

from __future__ import annotations

import sys
from pathlib import Path

_ARCH_DIR = Path(__file__).resolve().parent
for _p in (_ARCH_DIR, _ARCH_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from _common import HelperError, check_engine, run_cli  # noqa: E402
import arrange as arrange_mod  # noqa: E402
import page_compose  # noqa: E402
import route_connections  # noqa: E402
import scene as sc  # noqa: E402

TOOL = "exp_svg.arch.compose_page"
ROOT_ID = "__page__"
# spacing scales tried in order when the layout does not fit at the requested spacing (compose engine "page2")
DENSITY_LEVELS = (1.0, 0.8, 0.65, 0.5)


def _densify(request: dict, root: dict | None, f: float) -> tuple[dict, dict | None]:
    """A copy of the request with gaps, zone padding and node padding scaled by f (floors keep things apart)."""
    import copy
    req, rt = copy.deepcopy(request), copy.deepcopy(root)
    if f >= 0.999:
        return req, rt
    layouts = [z["layout"] for z in req.get("zones") or [] if isinstance(z.get("layout"), dict)]
    if rt and isinstance(rt.get("layout"), dict):
        layouts.append(rt["layout"])
    for layout in layouts:
        layout["gap_x"] = round(max(8.0, float(layout.get("gap_x", arrange_mod.DEFAULT_GAP_X)) * f), 1)
        layout["gap_y"] = round(max(5.0, float(layout.get("gap_y", arrange_mod.DEFAULT_GAP_Y)) * f), 1)
    for zone in req.get("zones") or []:
        if zone.get("kind") != "group":
            zone["pad"] = round(max(5.0, float(sc.ZONE_PAD if zone.get("pad") is None else zone["pad"]) * f), 1)
    req["node_pad"] = [round(max(8.0, sc.PAD_X * f), 1), round(max(4.0, sc.PAD_Y * f), 1)]
    req["caption_gap"] = round(max(3.0, sc.CAPTION_GAP * f), 1)
    return req, rt


def _install_root(scene: dict, root: dict | None) -> None:
    """Turn `root.layout` into a layout-only zone framed by the body region, and default group zones to no padding."""
    for zone in scene.get("zones") or []:
        if zone.get("kind") == "group":
            zone.setdefault("pad", 0)
            zone["label"] = ""
    if not root:
        return
    layout = root.get("layout")
    if not isinstance(layout, dict):
        raise HelperError("`root` needs a `layout` (rows, columns or grid) over the body region")
    rows, _ = arrange_mod._grid_lists(layout)
    listed = [i for row in rows for i in row]
    zones = {z["id"]: z for z in scene.get("zones") or []}
    nodes = {n["id"]: n for n in scene.get("nodes") or []}
    notes = {a["id"]: a for a in scene.get("annotations") or []}
    legend_id = (scene.get("legend") or {}).get("id", "legend") if scene.get("legend") else None
    for item in listed:
        if item in zones:
            if zones[item].get("parent"):
                raise HelperError(f"root layout lists zone {item!r}, which has a parent: list it in its parent's layout")
            if zones[item].get("frame"):
                raise HelperError(f"zone {item!r} is in the root layout, so it must not also have a `frame`")
            if not zones[item].get("layout"):
                raise HelperError(f"zone {item!r} is in the root layout, so it needs its own `layout` (the tool sizes it from that)")
            zones[item]["parent"] = ROOT_ID
        elif item in nodes:
            if nodes[item].get("zone"):
                raise HelperError(f"root layout lists node {item!r}, which sits in zone {nodes[item]['zone']!r}: list it there")
            nodes[item]["zone"] = ROOT_ID
        elif item in notes or item == legend_id or item in {b["id"] for b in scene.get("spacers") or []}:
            continue
        else:
            raise HelperError(f"root layout names unknown id {item!r}")
    scene.setdefault("zones", []).insert(0, {"id": ROOT_ID, "label": "", "kind": "group", "pad": 0,
                                             "frame": dict(scene["region"]), "layout": layout})


def _strip_groups(scene: dict) -> None:
    """Remove layout-only zones before routing and drawing; their members move up to the nearest drawn zone."""
    groups = {z["id"]: z.get("parent") for z in scene["zones"] if z["kind"] == "group"}

    def drawn(zone_id):
        while zone_id in groups:
            zone_id = groups[zone_id]
        return zone_id

    for zone in scene["zones"]:
        if zone.get("parent") in groups:
            zone["parent"] = drawn(zone["parent"])
    for node in scene["nodes"]:
        if node.get("zone") in groups:
            node["zone"] = drawn(node["zone"])
    scene["zones"] = [z for z in scene["zones"] if z["id"] not in groups]


def _hits(y: float, xa: float, xb: float, rect: tuple) -> bool:
    x0, y0, x1, y1 = rect
    return y0 - 1 < y < y1 + 1 and min(xa, xb) < x1 and x0 < max(xa, xb)


def _draw_buses(scene: dict, buses: dict, bus_edges: list[dict]) -> tuple[str, list[dict], dict]:
    """Trunks, straight branches and branch labels for the scene's buses: (svg, residuals, report)."""
    if not buses:
        return "", [], {}
    table = sc.by_id(scene)
    style, t = scene["style"], scene["type"]
    node_ids = {n["id"] for n in scene["nodes"]}
    blocks = [(o["id"], o["core"]) for o in route_connections.obstacles(scene)]
    residuals, lines, labels, report = [], [], [], {}
    sides: dict[tuple, list] = {}
    plan = []
    for edge in bus_edges:
        bus_id = edge["target"] if edge.get("target") in buses else edge["source"]
        node_id = edge["source"] if bus_id == edge.get("target") else edge["target"]
        if node_id in buses:
            raise HelperError(f"bus flow {edge.get('id')!r} joins two buses; a branch joins one node to one bus")
        if node_id not in node_ids:
            raise HelperError(f"bus flow {edge.get('id')!r}: {node_id!r} is not a node id")
        kind = edge.get("kind") or buses[bus_id].get("kind") or "sync"
        if kind not in style["edge_kinds"]:
            raise HelperError(f"bus flow {edge.get('id')!r} kind {kind!r} has no style.edge_kinds entry")
        bx = table[bus_id]["box"]["x"] + table[bus_id]["box"]["w"] / 2
        nb = table[node_id]["box"]
        side = "E" if nb["x"] + nb["w"] / 2 < bx else "W"
        item = {"edge": edge, "bus": bus_id, "node": node_id, "kind": kind, "bx": bx, "side": side,
                "to_node": edge.get("source") == bus_id}
        sides.setdefault((node_id, side), []).append(item)
        plan.append(item)
    for (node_id, side), items in sides.items():  # several branches on one side share it evenly
        nb = table[node_id]["box"]
        for k, item in enumerate(items):
            item["y"] = round(nb["y"] + nb["h"] * (k + 1) / (len(items) + 1), 2)
            item["nx"] = round(nb["x"] + nb["w"], 2) if side == "E" else round(nb["x"], 2)
    placed_labels: list[tuple] = []
    # routed flows and zone outlines a branch must not run along (crossing them is fine)
    h_runs, v_runs = [], []
    for e in scene["edges"]:
        pts = (e.get("route") or {}).get("points") or []
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            (h_runs if abs(ya - yb) < 0.01 else v_runs).append((min(xa, xb), min(ya, yb), max(xa, xb), max(ya, yb)))
    for z in scene["zones"]:
        x0, y0, x1, y1 = sc.rect(z["box"])
        h_runs += [(x0, y0, x1, y0), (x0, y1, x1, y1)]
        v_runs += [(x0, y0, x0, y1), (x1, y0, x1, y1)]

    def clear_h(y: float, xa: float, xb: float, own: str) -> list[str]:
        found = [oid for oid, core in blocks if oid != own and _hits(y, xa, xb, core)]
        if any(abs(y - r[1]) < 5 and min(xa, xb) < r[2] - 2 and r[0] + 2 < max(xa, xb) for r in h_runs):
            found.append("a line it would run along")
        return found

    def clear_v(x: float, ya: float, yb: float, own: str) -> bool:
        lo, hi = min(ya, yb), max(ya, yb)
        if any(oid != own and core[0] - 1 < x < core[2] + 1 and lo < core[3] and core[1] < hi for oid, core in blocks):
            return False
        return not any(abs(x - r[0]) < 5 and lo < r[3] - 2 and r[1] + 2 < hi for r in v_runs)

    for item in plan:
        edge, y, nx, bx = item["edge"], item["y"], item["nx"], item["bx"]
        es = style["edge_kinds"][item["kind"]]
        nb = table[item["node"]]["box"]
        points = [(nx, y), (bx, y)]  # node end first
        blockers = clear_h(y, nx, bx, item["node"])
        if blockers:  # one bend: leave the node upward or downward, then run to the trunk in a clear channel
            found = None
            px = round(nb["x"] + nb["w"] / 2 + (6 if item["side"] == "E" else -6), 2)
            for off in (10, 14, 18, 24, 30):
                for edge_y, y2 in ((nb["y"], nb["y"] - off), (nb["y"] + nb["h"], nb["y"] + nb["h"] + off)):
                    if clear_v(px, edge_y, y2, item["node"]) and not clear_h(y2, px, bx, item["node"]) \
                            and not any(abs(y2 - o.get("trunk_y", -99)) < 6 and o["bus"] == item["bus"] for o in plan if o is not item):
                        found = [(px, edge_y), (px, y2), (bx, y2)]
                        break
                if found:
                    break
            if found:
                points = found
            else:
                residuals.append({"kind": "bus_branch_blocked", "id": edge["id"], "by": blockers,
                                  "message": f"branch {edge['id']} ({item['node']} - bus {item['bus']}) is blocked by {blockers} and no "
                                             f"clear channel was found above or below {item['node']}: arrange the rows to give it a "
                                             f"clear run to the bus"})
        item["points"] = points
        item["trunk_y"] = points[-1][1]
        item["run"] = (min(points[-2][0], points[-1][0]), max(points[-2][0], points[-1][0]))  # the horizontal part by the trunk
        dash = f' stroke-dasharray="{es["dash"]}"' if es.get("dash") else ""
        head = f' marker-end="url(#arch-head-{item["kind"]})"' if item["to_node"] and es.get("head", True) else ""
        drawn = list(reversed(points)) if item["to_node"] else points
        lines.append(f'<path id="arch-edge-{edge["id"]}" data-arch-id="{edge["id"]}" data-arch-role="edge" '
                     f'data-arch-source="{edge["source"]}" data-arch-target="{edge["target"]}" '
                     f'd="{sc.path_d(drawn)}" fill="none" stroke="{es["stroke"]}" '
                     f'stroke-width="{es.get("width", 1.5)}"{dash}{head}/>')
        rec = report.setdefault(item["bus"], {"x": round(bx, 2), "branches": [], "paths": []})
        rec["branches"].append({"flow": edge["id"], "node": item["node"], "side": item["side"], "y": item["trunk_y"], "bends": len(points) - 2})
        rec["paths"].append([(round(px_, 2), round(py_, 2)) for px_, py_ in points])
    for item in plan:  # the label code below works on the horizontal part that meets the trunk
        item["y"] = item["trunk_y"]
        item["nx"] = item["run"][0] if abs(item["run"][1] - item["bx"]) < 0.01 else item["run"][1]
    for item in plan:  # a label sits on its branch, starting at the trunk or node end nearer the left, above the line
        edge = item["edge"]
        if not edge.get("label"):
            continue
        run = abs(item["bx"] - item["nx"])
        got = sc.measure_text(scene, edge["label"], t["edge_label_px"], "label", "normal",
                              max(float(edge.get("label_max_w") or run - 14), 48.0))
        h = len(got["lines"]) * sc.PITCH * t["edge_label_px"]
        lx = min(item["bx"], item["nx"]) + 7
        box = (lx, item["y"] - 3 - h, lx + got["width_px"], item["y"] - 3)
        clashes = [oid for oid, core in blocks if box[0] < core[2] and core[0] < box[2] and box[1] < core[3] and core[1] < box[3]]
        clashes += [o["edge"]["id"] for o in plan if o is not item and _hits(o["y"], o["nx"], o["bx"], box)]
        clashes += [pid for pid, pb in placed_labels if box[0] < pb[2] and pb[0] < box[2] and box[1] < pb[3] and pb[1] < box[3]]
        if got["width_px"] > run - 8 or clashes:
            residuals.append({"kind": "bus_label_conflict", "id": edge["id"], "with": clashes,
                              "message": f"label of {edge['id']} needs {got['width_px']:.0f} x {h:.0f} px above its branch "
                                         f"(run {run:.0f} px)" + (f" and touches {clashes}" if clashes else "")
                                         + ": widen the gap beside the bus or space the nodes"})
        placed_labels.append((edge["id"], box))
        labels.append(sc._text_block(got["lines"], lx, box[1], t["edge_label_px"], style["edge_kinds"][item["kind"]]["stroke"],
                                     "normal", "start", f'{edge["id"]}:label'))
    for bus_id, rec in report.items():
        ys = [b["y"] for b in rec["branches"]]
        kind = buses[bus_id].get("kind") or next(i["kind"] for i in plan if i["bus"] == bus_id)
        es = style["edge_kinds"][kind]
        dash = f' stroke-dasharray="{es["dash"]}"' if es.get("dash") else ""
        rec.update(y0=min(ys), y1=max(ys))
        if max(ys) - min(ys) > 0.5:
            lines.append(f'<path id="arch-bus-{bus_id}" data-arch-id="{bus_id}" data-arch-role="bus" '
                         f'd="M{sc._num(rec["x"])} {sc._num(min(ys))}V{sc._num(max(ys))}" fill="none" stroke="{es["stroke"]}" '
                         f'stroke-width="{es.get("width", 1.5)}"{dash}/>')
    for bus_id in buses:
        if bus_id not in report:
            residuals.append({"kind": "bus_unused", "id": bus_id, "message": f"bus {bus_id} has no flows"})
    return "\n".join(labels + lines), residuals, report


def _add_arguments(parser) -> None:
    parser.add_argument("--page", required=True, help="the slide file to write (whole page; replaces the file)")


def _work(request: dict, args) -> tuple[str, dict, list, list, dict]:
    check_engine("placement", "primitive")
    check_engine("routing", "orthogonal")
    import os as _os
    check_engine("compose", "page2" if "compose:page2" in (_os.environ.get("PPT_MASTER_EXP_ENGINES") or "") else "page")
    page = request.pop("page", None)
    if not isinstance(page, dict):
        raise HelperError("compose_page needs a `page` block (template, texts, body)")
    root = request.pop("root", None)
    request.pop("engine", None)
    request.pop("route_engine", None)
    font = request.get("font") or {"family": "Segoe UI"}
    try:
        layout = page_compose.compose(page, font)
    except page_compose.PageError as exc:
        raise HelperError(str(exc)) from exc
    request["region"] = dict(layout["region"])
    request["route_bounds"] = dict(layout["region"])
    buses = {b["id"]: b for b in request.pop("buses", None) or []}
    bus_edges = [e for e in request.get("edges") or [] if e.get("source") in buses or e.get("target") in buses]
    for e in bus_edges:
        if not e.get("id"):
            raise HelperError("every flow needs an id")
    request["edges"] = [e for e in request.get("edges") or [] if e not in bus_edges]
    spacers = [{"id": b["id"], "box": {"x": 0.0, "y": 0.0, "w": float(b.get("w", 16)), "h": 1.0}} for b in buses.values()]
    for sp in request.get("spacers") or []:  # an empty layout slot of a given size (room for branch labels, for example)
        if not sp.get("id"):
            raise HelperError("every spacer needs an id")
        spacers.append({"id": sp["id"], "box": {"x": 0.0, "y": 0.0, "w": float(sp.get("w", 1)), "h": float(sp.get("h", 1))}})
    request["spacers"] = spacers
    # placement: the requested spacing first; with the "page2" engine, tighter spacing is tried before a capacity failure
    import os
    ladder = DENSITY_LEVELS if "compose:page2" in (os.environ.get("PPT_MASTER_EXP_ENGINES") or "") or request.pop("density_ladder", False) else (1.0,)
    density = 1.0
    for density in ladder:
        req, rt = _densify(request, root, density)
        _install_root(req, rt)
        _, scene, arranged = arrange_mod.arrange(req, "primitive")
        if not any(r.get("kind") == "capacity" for r in arranged):
            break
    _strip_groups(scene)
    if len(ladder) > 1:  # bus lines are known once boxes are placed: the router crosses them but does not run along them
        _, _, plan_report = _draw_buses(scene, buses, bus_edges)
        scene["pre_routed"] = [[(b["x"], b["y0"]), (b["x"], b["y1"])] for b in plan_report.values() if "y0" in b] + \
                              [p for b in plan_report.values() for p in b.get("paths", [])]
    _, scene, routed = route_connections.route(scene, "orthogonal")
    residuals = [r for r in arranged if r.get("kind") == "capacity" or r.get("op")]
    for r in residuals:  # the page-wide layout is the body region: say so in the creator's words
        if r.get("zone") == ROOT_ID:
            r["zone"] = "root"
            r["message"] = (f"the root layout needs {r['needs']['w']:.0f} x {r['needs']['h']:.0f} px; the body region holds "
                            f"{r['has']['w']:.0f} x {r['has']['h']:.0f}. Sizes (w x h) of its items: "
                            + ", ".join(f"{k} {v[0]}x{v[1]}" for k, v in (r.get("items") or {}).items())
                            + ". Nothing was dropped or shrunk: change the structure, the wraps (max_w) or the gaps and pads")
    seen = {str(sorted(r.items(), key=lambda kv: kv[0])) for r in residuals}
    for r in routed + [{"kind": p["kind"], "id": p.get("id"), "message": p["message"]} for p in layout["residuals"]]:
        key = str(sorted(r.items(), key=lambda kv: kv[0]))
        if key not in seen:
            seen.add(key)
            residuals.append(r)
    bus_svg, bus_residuals, bus_report = _draw_buses(scene, buses, bus_edges)
    residuals += bus_residuals
    region = scene["region"]
    bounds = " ".join(f"{float(region[k]):g}" for k in ("x", "y", "w", "h"))
    group = sc.render_group(scene, "arch").replace('<g id="arch" ', f'<g id="arch" data-pptx-bounds="{bounds}" ', 1)
    if bus_svg:
        group = group[:group.rindex("</g>")] + bus_svg + "\n</g>"
    page_path = Path(args.page)
    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(page_compose.assemble(layout, group, defs=sc.marker_defs(scene, "arch")), encoding="utf-8", newline="\n")
    if args.svg:
        Path(args.svg).write_text(sc.render_svg(scene, title=scene.get("title")), encoding="utf-8")
    if any(r.get("kind") == "capacity" for r in residuals):
        status = "capacity_failure"
    elif residuals:
        status = "partial"
    else:
        status = "ok"
    bindings = {e["id"]: {"source": (e["route"].get("binding") or {}).get("source"),
                          "target": (e["route"].get("binding") or {}).get("target"),
                          "glue_expected": (e["route"].get("glue") or {}).get("expected")} for e in scene["edges"]}
    boxes = {item["id"]: item["box"] for group_name in ("zones", "nodes", "annotations") for item in scene[group_name]}
    for rec in bus_report.values():
        rec.pop("paths", None)
    summary = {"page": {**page_compose.report(layout), "path": str(page_path)}, "boxes": boxes, "bindings": bindings,
               "buses": bus_report, "spacing_scale": density}
    if density < 0.999:
        residuals.append({"kind": "spacing_tightened", "scale": density,
                          "message": f"the layout did not fit at the requested spacing: gaps and paddings were scaled to {density:g} "
                                     f"of what you asked (nothing was dropped or shrunk). Free room elsewhere to get the spacing back"})
    return status, summary, residuals, sc.content_ids(scene) + [e["id"] for e in bus_edges], {"scene_sha256": sc.scene_hash(scene)}


def main(argv: list[str] | None = None) -> int:
    return run_cli(TOOL, argv, _work, _add_arguments, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
