#!/usr/bin/env python3
"""
PPT Master - Architecture Group Space Ledger

Measure group capacity from a full compose request without routing or writing
a page. See scripts/docs/experimental-group-space.md for scope and fields.

Usage:
    python3 scripts/exp_svg/arch/measure_groups.py --in request.json --out ledger.json

Examples:
    python3 scripts/exp_svg/arch/measure_groups.py --in architecture.json --out space.json

Dependencies:
    Pillow (through the existing architecture measurement helpers)
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

_ARCH_DIR = Path(__file__).resolve().parent
for _path in (_ARCH_DIR, _ARCH_DIR.parent, _ARCH_DIR.parents[1]):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from console_encoding import configure_utf8_stdio  # noqa: E402
from _common import HelperError  # noqa: E402
import arrange  # noqa: E402
import compose_page  # noqa: E402
import page_compose  # noqa: E402
import scene as sc  # noqa: E402


def _check_parents(request: dict) -> None:
    parents = {z["id"]: z.get("parent") for z in request.get("zones") or []}
    for item_id in parents:
        seen = set()
        current = item_id
        while current in parents:
            if current in seen:
                raise HelperError(f"zone parent cycle at {current!r}; remove the cycle")
            seen.add(current)
            current = parents[current]


def _prepare(request: dict) -> dict:
    if not isinstance(request, dict):
        raise HelperError("request must be a JSON object containing page, zones and nodes")
    scene = copy.deepcopy(request)
    page = scene.pop("page", None)
    if not isinstance(page, dict):
        raise HelperError("measure_groups needs a full compose request with a page block")
    root = scene.pop("root", None)
    scene.pop("engine", None)
    scene.pop("route_engine", None)
    scene.pop("density_ladder", None)
    layout = page_compose.compose(page, scene.get("font") or {"family": "Segoe UI"})
    scene["region"] = dict(layout["region"])
    buses = {b["id"]: b for b in scene.pop("buses", None) or []}
    scene["edges"] = [e for e in scene.get("edges") or []
                      if e.get("source") not in buses and e.get("target") not in buses]
    spacers = [{"id": b["id"], "w": b.get("w", 16), "h": 1} for b in buses.values()]
    spacers += scene.get("spacers") or []
    scene["spacers"] = [
        {"id": s["id"], "box": {"x": 0.0, "y": 0.0,
                                  "w": float(s.get("w", 1)), "h": float(s.get("h", 1))}}
        for s in spacers
    ]
    _check_parents(scene)
    # This internal adapter owns compose-specific group and root semantics.
    compose_page._install_root(scene, root)
    return scene


def measure_groups(request: dict) -> dict:
    """Return capacity evidence at requested spacing, leaving the request untouched."""
    prepared = _prepare(request)
    _, placed, _ = arrange.arrange(prepared, "primitive")
    table = sc.by_id(placed)
    groups = []
    for zone in placed["zones"]:
        box = zone["box"]
        left, top, right, bottom = sc.zone_insets(placed, zone)
        inner_w, inner_h = box["w"] - left - right, box["h"] - top - bottom
        if zone.get("layout"):
            rows, _ = arrange._grid_lists(zone["layout"])
            items = [item for row in rows for item in row]
            sizes = {item: (table[item]["box"]["w"], table[item]["box"]["h"]) for item in items}
            need_w, need_h = arrange.layout_extent(zone["layout"], sizes)
            extent_kind = "layout_extent"
            alignment = None
            if zone["layout"].get("align_columns"):
                unaligned = dict(zone["layout"], align_columns=False)
                row_w, row_h = arrange.layout_extent(unaligned, sizes)
                alignment = {
                    "align_columns": True,
                    "slot_semantics": "Global column maxima across all rows; a singleton is not a spanning cell.",
                    "without_column_alignment": {"w": round(row_w, 2), "h": round(row_h, 2)},
                    "alignment_extra": {"w": round(max(0.0, need_w - row_w), 2),
                                        "h": round(max(0.0, need_h - row_h), 2)},
                    "scope": "Size diagnostic only. Does not change the request or certify routes/visual quality. Remeasure after any content or layout change.",
                }
        else:
            items = [n["id"] for n in placed["nodes"] if n.get("zone") == zone["id"]]
            items += [z["id"] for z in placed["zones"] if z.get("parent") == zone["id"]]
            boxes = [table[item]["box"] for item in items]
            need_w = max((b["x"] + b["w"] for b in boxes), default=0) - min(
                (b["x"] for b in boxes), default=0)
            need_h = max((b["y"] + b["h"] for b in boxes), default=0) - min(
                (b["y"] for b in boxes), default=0)
            extent_kind = "placed_child_union"
            alignment = None
        caption = zone["caption"]
        minimum_w = max(need_w, caption["w"]) + left + right
        minimum_h = need_h + top + bottom
        deficits = {"w": round(max(0.0, minimum_w - box["w"]), 2),
                    "h": round(max(0.0, minimum_h - box["h"]), 2)}
        culprits = {"w": [], "h": []}
        for item in items:
            b = table[item]["box"]
            if b["x"] < box["x"] + left - 0.01 or b["x"] + b["w"] > box["x"] + box["w"] - right + 0.01:
                culprits["w"].append(item)
            if b["y"] < box["y"] + top - 0.01 or b["y"] + b["h"] > box["y"] + box["h"] - bottom + 0.01:
                culprits["h"].append(item)
        gap = top - left - caption["h"]
        groups.append({
            "id": "root" if zone["id"] == compose_page.ROOT_ID else zone["id"],
            "parent": "root" if zone.get("parent") == compose_page.ROOT_ID else zone.get("parent"),
            "kind": zone["kind"],
            "frame_source": "page_body" if zone["id"] == compose_page.ROOT_ID else (
                "supplied_fixed" if zone.get("frame") else "content_sized"),
            "outer": dict(box),
            "inner": {"w": round(inner_w, 2), "h": round(inner_h, 2)},
            "padding": {"left": left, "top": left, "right": right, "bottom": bottom},
            "insets": {"left": left, "top": top, "right": right, "bottom": bottom},
            "heading": {"lines": list(caption["lines"]), "w": caption["w"], "h": caption["h"],
                        "gap": round(gap, 2), "wrap_width": zone.get("caption_max_w")},
            "content": {"w": round(need_w, 2), "h": round(need_h, 2), "extent_kind": extent_kind},
            "alignment_diagnostic": alignment,
            "minimum_outer": {"w": round(minimum_w, 2), "h": round(minimum_h, 2)},
            "deficit": deficits,
            "culprit_child_ids": culprits,
            "heading_exceeds_inner_width": caption["w"] > inner_w + 0.01,
            "children": [{"id": item, "w": table[item]["box"]["w"], "h": table[item]["box"]["h"]}
                         for item in items],
            "wrap_scale": zone.get("wrap_scale", 1.0),
        })
    return {"schema": "exp_svg.arch.group_space.v1", "units": "px",
            "scope": "primitive placement at requested spacing; no density retries or routing",
            "font_evidence": {weight: sc.measure_labels.resolve_font(placed["font"], weight)
                              for weight in ("normal", "bold")},
            "groups": groups}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="input", required=True, type=Path, help="Full architecture compose request")
    parser.add_argument("--out", required=True, type=Path, help="UTF-8 JSON ledger path (must end in .json)")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    args = build_parser().parse_args(argv)
    try:
        if args.out.suffix.lower() != ".json":
            raise HelperError("--out must end in .json; choose a separate ledger file")
        if args.input.resolve() == args.out.resolve():
            raise HelperError("--out must differ from --in; preserve the request")
        request = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise HelperError("request must be a JSON object containing page, zones and nodes")
        # Do not overwrite the page template or a font resource with the ledger.
        resources = [(request.get("page") or {}).get("template")]
        for config in (request.get("font") or {}, request.get("page") or {}):
            resources += list((config.get("files") or config.get("font_files") or {}).values())
        if any(path and Path(path).resolve() == args.out.resolve() for path in resources):
            raise HelperError("--out names an input resource; choose a separate ledger file")
        ledger = measure_groups(request)
        serialized = json.dumps(ledger, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        args.out.write_text(serialized, encoding="utf-8")
    except (HelperError, page_compose.PageError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"measure_groups: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ledger": str(args.out), "groups": len(ledger["groups"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
