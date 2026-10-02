#!/usr/bin/env python3
"""PPT Master - prepare three measured timeline note cards.

Prepare page.extra_svg with three aligned native semantic shapes. This helper
never writes a slide; capacity_preflight and guided_build own slide creation.
This fixed three-card, 16 px helper does not certify arbitrary page.extra_svg
or collisions with page.texts; the caller must inspect the composed page.

Usage: python prepare_note_cards.py --in request.json --out prepared.json --receipt cards.json
Examples: prepare a request containing page.note_cards before capacity preflight.
Dependencies: Pillow through the existing font measurement helper.
"""

import argparse
import copy
import json
import math
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
for directory in (HERE.parent / "arch", HERE.parents[1]):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

import measure_labels  # noqa: E402
from console_encoding import configure_utf8_stdio  # noqa: E402
from exp_svg.contracts import add_contract_arguments, check_paths, load_contract  # noqa: E402


def _rectangle(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} needs an x/y/w/h object")
    result = {}
    for key in ("x", "y", "w", "h"):
        number = value.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise ValueError(f"{name}.{key} must be finite numeric")
        try:
            finite = math.isfinite(number)
        except OverflowError:
            finite = False
        if not finite or (key in ("w", "h") and number <= 0):
            raise ValueError(f"{name}.{key} must be finite; dimensions must be positive")
        result[key] = float(number)
    return result


def _inside(inner, outer):
    return (inner["x"] >= outer["x"] and inner["y"] >= outer["y"]
            and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
            and inner["y"] + inner["h"] <= outer["y"] + outer["h"])


def _overlap(left, right):
    return (left["x"] < right["x"] + right["w"] and right["x"] < left["x"] + left["w"]
            and left["y"] < right["y"] + right["h"] and right["y"] < left["y"] + left["h"])


def prepare(request: dict, *, body_px_min: float = 16) -> dict:
    """Return a copied request and measured card evidence, without shortening text."""
    value = copy.deepcopy(request)
    page = value["page"]
    notes = page.pop("note_cards")
    if page.get("extra_svg"):
        raise ValueError("Prepare cards before adding page.extra_svg; existing SVG is not overwritten")
    body = _rectangle(page.get("body"), "page.body")
    chart = _rectangle(value.get("bounds"), "bounds")
    strip = _rectangle(notes.get("strip"), "note_cards.strip")
    if not _inside(chart, body) or not _inside(strip, body):
        raise ValueError("Chart and note strip must lie inside page.body")
    if strip["x"] != body["x"] or strip["w"] != body["w"]:
        raise ValueError("The three-card strip must span the full page.body width")
    if _overlap(chart, strip) or strip["y"] < chart["y"] + chart["h"]:
        raise ValueError("Note cards must sit underneath, without overlapping chart bounds")
    cards = notes.get("cards")
    if not isinstance(cards, list) or len(cards) != 3:
        raise ValueError("page.note_cards.cards needs exactly three cards")
    font = {"family": value.get("style", {}).get("font_family", "Segoe UI"),
            "files": page.get("font_files") or {}}
    size, pitch, padding, gap = 16.0, 21.0, 14.0, 14.0
    if max(body_px_min, value.get("floors", {}).get("body_px", 16)) > size:
        raise ValueError("This fixed 16 px card helper cannot satisfy a higher body floor")
    value.setdefault("floors", {})["body_px"] = size
    width = (strip["w"] - 2 * gap) / 3
    if width <= 2 * padding or strip["h"] <= 2 * padding:
        raise ValueError("Note strip is too small for card padding")
    groups, geometry, ids = [], [], set()
    for index, card in enumerate(cards):
        identifier = card.get("id", "")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", identifier):
            raise ValueError("Card ids need unique lowercase SVG-safe names")
        if identifier in ids:
            raise ValueError(f"Duplicate card id {identifier}")
        ids.add(identifier)
        frame = {"x": strip["x"] + index * (width + gap), "y": strip["y"],
                 "w": width, "h": strip["h"]}
        measured = []
        for field, weight in (("heading", "bold"), ("text", "normal")):
            text = card.get(field)
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"Card {identifier}.{field} needs nonempty text")
            result = measure_labels.measure_label({
                "id": identifier + "-" + field, "text": text, "role": "body",
                "size_px": size, "weight": weight, "max_width": width - 2 * padding,
                "line_pitch_px": pitch,
            }, font)
            if not result["font"]["file"] or result["oversized_words"]:
                raise ValueError(f"Card {identifier}.{field} requires a real font and fitting words")
            measured.append(result)
        heading, prose = measured
        line_count = len(heading["lines"]) + len(prose["lines"])
        ink_height = (line_count - 1) * pitch + 6 + 1.2 * size
        if ink_height > strip["h"] - 2 * padding:
            raise ValueError(f"Card {identifier} needs {ink_height:g} px of text height; enlarge the strip")
        x, baseline = frame["x"] + padding, frame["y"] + padding + size
        tspans, line_boxes = [], []
        for part, result in enumerate(measured):
            if part:
                baseline += 6
            for row, (line, advance) in enumerate(zip(result["lines"], result["line_widths_px"])):
                continuation = ' data-paragraph-soft-break="1"' if row else ' data-paragraph-soft-break="0"'
                dy = 0 if part == 0 and row == 0 else pitch + (6 if part and row == 0 else 0)
                weight = "bold" if part == 0 else "normal"
                colour = "#0F5C3A" if part == 0 else "#1C1C1A"
                tspans.append(f'<tspan x="{x:g}" dy="{dy:g}" font-weight="{weight}" '
                              f'fill="{colour}"{continuation}>{escape(line)}</tspan>')
                box = {"x": x, "y": baseline - size, "w": advance, "h": 1.2 * size}
                if not _inside(box, frame):
                    raise ValueError(f"Measured text leaves card {identifier}")
                line_boxes.append(box)
                baseline += pitch
        dimensions = " ".join(f"{frame[k]:g}" for k in ("x", "y", "w", "h"))
        groups.append(
            f'<g id="note-{identifier}" data-name="note-{identifier}" '
            f'data-pptx-semantic-object="shape" data-pptx-frame="{dimensions}">'
            f'<rect data-pptx-part="geometry" x="{frame["x"]:g}" y="{frame["y"]:g}" '
            f'width="{width:g}" height="{strip["h"]:g}" rx="4" fill="#F4F2EE" '
            f'stroke="#D6D1C9" stroke-width="1"/>'
            f'<text x="{x:g}" y="{frame["y"] + padding + size:g}" font-size="16" '
            f'font-family="{escape(font["family"])}" data-paragraph-line-height="21">'
            + "".join(tspans) + '</text></g>'
        )
        geometry.append({"id": identifier, "frame": frame, "line_boxes": line_boxes,
                         "measurements": measured, "text_unchanged": True})
    page["extra_svg"] = "\n".join(groups)
    return {"request": value, "geometry": geometry, "status": "prepared",
            "limitations": "Fixed three-card, 16 px helper. Font advances are approximate; verify browser and native export. Does not certify arbitrary extra_svg or collisions with page.texts."}


def main(argv=None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source", required=True)
    parser.add_argument("--out", required=True, help="Prepared request JSON, not a slide")
    parser.add_argument("--receipt", required=True)
    add_contract_arguments(parser)
    args = parser.parse_args(argv)
    source = Path(args.source).resolve()
    outputs = [Path(args.out).resolve(), Path(args.receipt).resolve()]
    if source in outputs or len(set(outputs)) != len(outputs):
        parser.error("Prepared request and receipt must be distinct and must not replace the input")
    try:
        floor = 16
        if args.contract:
            canvas, contract_path, workspace = load_contract(args)
            check_paths(source, outputs, workspace, resources=[contract_path])
            floor = canvas["type_floors"].get("body_px_min", 16)
        result = prepare(json.loads(Path(args.source).read_text(encoding="utf-8")), body_px_min=floor)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"note cards: {exc}", file=sys.stderr)
        return 2
    for path in (Path(args.out), Path(args.receipt)):
        path.parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result.pop("request"), indent=2) + "\n", encoding="utf-8")
    Path(args.receipt).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
