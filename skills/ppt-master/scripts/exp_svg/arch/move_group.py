#!/usr/bin/env python3
"""
PPT Master - move_group (experimental architecture helper)

Move a zone (with everything inside it), a node, or a set of them as ONE
atomic edit, keeping every semantic binding: annotations attached to a moved
element follow it, flows with both ends inside the group are translated
unchanged, flows with one end inside are re-routed from the same source/target
ids, and any other flow the moved group now blocks is re-routed too. Labels
that end up in conflict are re-placed. The result lists every changed id and
proves the bindings survived (same source/target ids, ends on the intended
outlines). A move that lands on something is still performed and reported as
`partial` with the collisions; nothing is dropped or resized.

Usage:
    python3 scripts/exp_svg/arch/move_group.py --in move.json --out moved.json [--svg preview.svg]

Request:
    {"scene": <routed scene, or a whole arrange/route result file>,
     "group": "eu"  |  {"ids": ["eu_api", "eu_orders"]},
     "delta": {"dx": 0, "dy": 40}  |  "to": {"x": 60, "y": 140},     # `to` = new top-left of the group
     "reroute": "orthogonal" | "libavoid" | "none"}

Dependencies:
    Pillow; see route_connections.py for the libavoid engine
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

_ARCH_DIR = Path(__file__).resolve().parent
if str(_ARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ARCH_DIR))

from _common import HelperError, run_cli  # noqa: E402
import scene as sc  # noqa: E402
import route_connections as rc  # noqa: E402

TOOL = "exp_svg.arch.move_group"


def _members(scene: dict, group) -> tuple[list[str], list[str]]:
    ids = [group] if isinstance(group, str) else list((group or {}).get("ids") or [])
    if not ids:
        raise HelperError("group must be an id or {\"ids\": [...]}")
    table = sc.by_id(scene)
    nodes, zones = [], []
    for item_id in ids:
        if item_id not in table or item_id in {e["id"] for e in scene["edges"]}:
            raise HelperError(f"group member {item_id!r} is not a zone or node")
        n, z = sc.subtree(scene, item_id)
        nodes += [i for i in n if i not in nodes]
        zones += [i for i in z if i not in zones]
    return nodes, zones


def move(scene: dict, group, delta: dict | None, to: dict | None, reroute: str = "orthogonal",
         libavoid: str | None = None) -> tuple[str, dict, list[dict], dict]:
    if "result" in scene and "tool" in scene:
        scene = scene["result"]
    scene = sc.normalize(copy.deepcopy(scene))
    nodes, zones = _members(scene, group)
    table = sc.by_id(scene)
    boxes = [table[i]["box"] for i in nodes + zones]
    if to is not None:
        dx = float(to["x"]) - min(b["x"] for b in boxes)
        dy = float(to["y"]) - min(b["y"] for b in boxes)
    elif delta is not None:
        dx, dy = float(delta.get("dx", 0.0)), float(delta.get("dy", 0.0))
    else:
        raise HelperError("give `delta` {dx, dy} or `to` {x, y}")
    before = {e["id"]: (e["source"], e["target"]) for e in scene["edges"]}

    def label_conflicts() -> dict:
        found = {}
        for e in scene["edges"]:
            lab = (e.get("route") or {}).get("label")
            if lab and lab.get("box"):
                others = [(o["id"], o["route"]["label"]["box"]) for o in scene["edges"]
                          if o["id"] != e["id"] and ((o.get("route") or {}).get("label") or {}).get("box")]
                found[e["id"]] = set(rc._label_conflicts(lab["box"], scene, others, e["id"]))
        return found

    conflicts_before = label_conflicts()
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        residuals = rc.edge_checks(scene) + sc.node_checks(scene)
        changes = {"delta": {"dx": 0.0, "dy": 0.0}, "moved_nodes": [], "moved_zones": [], "moved_annotations": [],
                   "translated_edges": [], "rerouted_edges": [], "relabelled_edges": [], "bindings_preserved": True,
                   "semantic_ids_unchanged": True, "note": "zero move: nothing changed"}
        return ("ok" if not residuals else "partial"), scene, residuals, changes
    moved_zone_rects = [sc.rect(table[z]["box"]) for z in zones]
    sc.translate(scene, nodes, zones, dx, dy)
    member_set = set(nodes) | set(zones)
    moved_notes = []
    for note in scene["annotations"]:
        attach = note.get("attach") or {}
        if attach.get("to") in member_set:
            sc.place_annotation(scene, note, table)
            moved_notes.append(note["id"])
        elif note.get("at") and any(sc.contains(r, sc.rect(note["box"])) for r in moved_zone_rects):
            note["box"]["x"] += dx
            note["box"]["y"] += dy
            note["at"] = {"x": note["box"]["x"], "y": note["box"]["y"]}
            moved_notes.append(note["id"])
    translated, rerouted = [], []
    node_set = set(nodes)
    for edge in scene["edges"]:
        inside = (edge["source"] in node_set) + (edge["target"] in node_set)
        route = edge.get("route") or {}
        if inside == 2 and route.get("points"):
            route["points"] = [[round(p[0] + dx, 2), round(p[1] + dy, 2)] for p in route["points"]]
            if (route.get("label") or {}).get("box"):
                route["label"]["box"]["x"] += dx
                route["label"]["box"]["y"] += dy
            translated.append(edge["id"])
        elif inside == 1:
            rerouted.append(edge["id"])
    # flows that do not touch the group but now run through one of its boxes
    moved_cores = [sc.rect(table[n]["box"]) for n in nodes]
    for edge in scene["edges"]:
        if edge["id"] in translated or edge["id"] in rerouted:
            continue
        pts = (edge.get("route") or {}).get("points") or []
        segs = list(zip(pts, pts[1:]))
        if any(sc.segment_hits_rect(a, b, (r[0] - 2, r[1] - 2, r[2] + 2, r[3] + 2)) for a, b in segs for r in moved_cores):
            rerouted.append(edge["id"])
    info = {"engine": reroute}
    if reroute != "none":
        from _common import check_engine
        check_engine("routing", reroute)
    if reroute != "none" and rerouted:
        info["version"] = rc.apply_routes(scene, reroute, libavoid, set(rerouted))
    elif rerouted:
        for edge_id in rerouted:
            edge = next(e for e in scene["edges"] if e["id"] == edge_id)
            edge["route"] = {"engine": "none", "points": None, "failure": "reroute disabled after move"}
    # labels of untouched flows that the move now collides with are re-placed beside their own routes
    relabelled = []
    for edge in scene["edges"]:
        label = (edge.get("route") or {}).get("label")
        if edge["id"] in rerouted or not label or not label.get("box"):
            continue
        others = [(e["id"], e["route"]["label"]["box"]) for e in scene["edges"]
                  if e["id"] != edge["id"] and ((e.get("route") or {}).get("label") or {}).get("box")]
        now = set(rc._label_conflicts(label["box"], scene, others, edge["id"]))
        if now - conflicts_before.get(edge["id"], set()):  # only conflicts this move created
            relabelled.append(edge["id"])
    if relabelled and reroute != "none":
        rc.place_labels(scene, set(relabelled))
    residuals = rc.edge_checks(scene) + sc.node_checks(scene)
    after = {e["id"]: (e["source"], e["target"]) for e in scene["edges"]}
    bound = all(((e.get("route") or {}).get("binding") or {}).get(end, {}).get("id") == e[end]
                and ((e.get("route") or {}).get("binding") or {}).get(end, {}).get("bound")
                for e in scene["edges"] if (e.get("route") or {}).get("points") for end in ("source", "target"))
    changes = {"delta": {"dx": round(dx, 2), "dy": round(dy, 2)}, "moved_nodes": nodes, "moved_zones": zones,
               "moved_annotations": moved_notes, "translated_edges": translated, "rerouted_edges": sorted(rerouted),
               "relabelled_edges": relabelled, "bindings_preserved": before == after and bound,
               "semantic_ids_unchanged": before == after}
    scene["provenance"] = {**(scene.get("provenance") or {}), "last_move": {"tool": TOOL, **info, **changes["delta"]}}
    status = "ok" if not residuals else "partial"
    return status, scene, residuals, changes


def _add_arguments(parser) -> None:
    parser.add_argument("--libavoid", default=None, help="libavoid-js package directory (else PPT_MASTER_LIBAVOID_JS)")


def _work(request: dict, args) -> tuple[str, dict, list, list, dict]:
    if "scene" not in request:
        raise HelperError("request.scene is required")
    status, scene, residuals, changes = move(request["scene"], request.get("group"), request.get("delta"),
                                             request.get("to"), request.get("reroute") or "orthogonal", args.libavoid)
    if args.svg:
        Path(args.svg).write_text(sc.render_svg(scene, title=scene.get("title")), encoding="utf-8")
    changed = changes["moved_nodes"] + changes["moved_zones"] + changes["moved_annotations"] + changes["translated_edges"] \
        + changes["rerouted_edges"] + changes["relabelled_edges"]
    return status, scene, residuals, sc.content_ids(scene), {"changes": changes, "changed_ids": sorted(set(changed)),
                                                               "scene_sha256": sc.scene_hash(scene)}


def main(argv: list[str] | None = None) -> int:
    return run_cli(TOOL, argv, _work, _add_arguments, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
