#!/usr/bin/env python3
"""
PPT Master - page composer (experimental, shared by the timeline and architecture helpers)

Builds the whole slide file around a helper-drawn body, so the creator never
assembles SVG by hand:

  - the template's root <svg> tag and its chrome group are copied verbatim;
  - the per-slide texts (eyebrow, title, source line, folio) are measured with
    the real font file, wrapped to their width, and written at the positions
    the style contract gives;
  - the body region is either the one the request gives or, with
    `body.fit: "between_texts"`, the space left between the texts marked
    `edge: "top"` and those marked `edge: "bottom"`;
  - everything outside the chrome sits in ONE root group with
    data-pptx-bounds, which is what the fork's export gate accepts.

Wrapping also keeps every line inside the width the fork's export gate
estimates (svg_quality_checker.py refuses a text whose ESTIMATED width leaves
the canvas by more than 5 %; its estimate runs wider than the font file for
bold text), so a page this module writes is not refused for a title that
fits on screen.

Usage:
    Library module for timeline/build_timeline.py (--page) and arch/compose_page.py.

    page = {"template": "<workspace>/inputs/fixture/template/content.svg", "chrome_group_id": "chrome",
            "texts": [{"id": "title", "text": "...", "x": 54, "baseline": 118, "size_px": 28, "weight": "bold",
                       "fill": "#1C1C1A", "max_w": 1172, "max_lines": 2, "line_pitch_px": 33, "edge": "top"},
                      {"id": "source", "text": "...", "x": 54, "baseline": 656, "baseline_of": "last", "size_px": 14,
                       "fill": "#5E5A54", "max_w": 1080, "max_lines": 2, "line_pitch_px": 18, "edge": "bottom"}],
            "body": {"x": 54, "w": 1172, "fit": "between_texts", "gap_top": 10, "gap_bottom": 6},
            "extra_svg": "<g id=\"extra\">...</g>"}

Dependencies:
    Pillow (through arch/measure_labels.py)
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape

_HERE = Path(__file__).resolve().parent
for _p in (_HERE / "arch", _HERE.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import measure_labels  # noqa: E402

VERSION = "0.1.0"
CANVAS_W, CANVAS_H = 1280.0, 720.0
GATE_OVERFLOW = 0.05     # svg_quality_checker.py: a text estimated to leave its group by more than 5 % is an error
ASCENT, DESCENT = 0.80, 0.25   # of the font size: the ink box of a line around its baseline
FORBIDDEN_EXTRA = ("script", "image", "foreignObject", "use", "style")


class PageError(ValueError):
    """A page block the composer cannot act on."""


def _num(v: float) -> str:
    return f"{round(float(v), 2):g}"


def _gate_ok(line: str, size: float, family: str, weight: str, x: float, anchor: str) -> bool:
    try:  # the same call the export gate makes (svg_quality_checker.py): headroom included
        import text_measure
        est = text_measure.measure_text(line, size=size, family=family, weight=weight, include_headroom=True)
    except (ImportError, ValueError):
        return True
    limit = CANVAS_W * GATE_OVERFLOW
    if anchor == "end":
        return x - est >= -limit + 1
    if anchor == "middle":
        return x - est / 2 >= -limit + 1 and x + est / 2 <= CANVAS_W + limit - 1
    return x + est <= CANVAS_W + limit - 1


def layout_text(spec: dict, font: dict) -> tuple[dict, list[dict]]:
    """One page text: wrapped lines, baselines and ink box. Never shortens or shrinks the text."""
    for key in ("id", "text", "x", "baseline", "size_px"):
        if spec.get(key) in (None, ""):
            raise PageError(f"page text {spec.get('id')!r} needs `{key}`")
    size = float(spec["size_px"])
    weight = str(spec.get("weight") or "normal")
    anchor = str(spec.get("anchor") or "start")
    x = float(spec["x"])
    family = str(font.get("family") or "Segoe UI")
    max_w = float(spec["max_w"]) if spec.get("max_w") else None
    residuals: list[dict] = []
    width = max_w
    measured = None
    for _ in range(12):
        measured = measure_labels.measure_label({"id": spec["id"], "text": str(spec["text"]), "size_px": size, "role": "label",
                                                 "weight": weight, "max_width": width}, font)
        if all(_gate_ok(line, size, family, weight, x, anchor) for line in measured["lines"]):
            break
        # the exporter's estimate is wider than the font: wrap a little narrower so the page is not refused at export
        width = (width or measured["width_px"]) * 0.96
    wrap_mode = str(spec.get("wrap") or ("balanced" if weight == "bold" else "greedy"))
    if wrap_mode == "balanced" and len(measured["lines"]) > 1:
        # even line lengths (no single word left alone on the last line): the narrowest width that keeps the line count
        count, lo, hi = len(measured["lines"]), 40.0, float(width or measured["width_px"])
        for _ in range(14):
            mid = (lo + hi) / 2
            trial = measure_labels.measure_label({"id": spec["id"], "text": str(spec["text"]), "size_px": size, "role": "label",
                                                  "weight": weight, "max_width": mid}, font)
            if len(trial["lines"]) <= count and not trial["oversized_words"]:
                hi, measured = mid, trial
            else:
                lo = mid
    lines = measured["lines"]
    max_lines = int(spec.get("max_lines") or 0)
    if max_lines and len(lines) > max_lines:
        residuals.append({"kind": "page_text_overflow", "id": spec["id"], "lines": len(lines), "max_lines": max_lines,
                          "message": f"page text {spec['id']} needs {len(lines)} lines at {size:g} px; the contract allows "
                                     f"{max_lines}. Nothing was cut: shorten the wording yourself only if the brief allows, "
                                     f"or give it more width"})
    if measured["oversized_words"]:
        residuals.append({"kind": "page_text_overflow", "id": spec["id"], "message": f"a word of {spec['id']} is wider than its width"})
    pitch = float(spec.get("line_pitch_px") or round(1.2 * size, 2))
    first = float(spec["baseline"])
    if spec.get("baseline_of") == "last":
        first -= pitch * (len(lines) - 1)
    widest = max(measured["line_widths_px"] or [0.0])
    left = x if anchor == "start" else (x - widest if anchor == "end" else x - widest / 2)
    box = {"x": round(left, 2), "y": round(first - ASCENT * size, 2), "w": round(widest, 2),
           "h": round(pitch * (len(lines) - 1) + (ASCENT + DESCENT) * size, 2)}
    block = {"id": spec["id"], "lines": lines, "x": x, "first_baseline": round(first, 2), "pitch": pitch, "size": size,
             "weight": weight, "fill": spec.get("fill") or "#1C1C1A", "anchor": anchor, "style": spec.get("style"),
             "edge": spec.get("edge"), "box": box, "role": spec.get("role"), "font_evidence": measured["font"]["source"]}
    return block, residuals


def _chrome(template: Path, group_id: str) -> tuple[str, str]:
    """(root <svg ...> opening tag, the chrome group verbatim)."""
    text = template.read_text(encoding="utf-8")
    root = re.search(r"<svg\b[^>]*>", text)
    if not root:
        raise PageError(f"{template} has no <svg> root")
    start = re.search(r"<g\b[^>]*\bid=\"%s\"[^>]*>" % re.escape(group_id), text)
    if not start:
        raise PageError(f"{template} has no <g id=\"{group_id}\">")
    depth, pos = 0, start.start()
    for m in re.finditer(r"<g\b[^>]*?(/?)>|</g>", text[start.start():]):
        if m.group(0).startswith("</g"):
            depth -= 1
        elif m.group(1) != "/":
            depth += 1
        if depth == 0:
            pos = start.start() + m.end()
            break
    else:
        raise PageError(f"{template}: the chrome group is not closed")
    return root.group(0), text[start.start():pos]


def _check_extra(extra: str) -> None:
    try:
        tree = ET.fromstring(f'<g xmlns="http://www.w3.org/2000/svg">{extra}</g>')
    except ET.ParseError as exc:
        raise PageError(f"page.extra_svg is not well-formed SVG: {exc}") from exc
    for el in tree.iter():
        tag = el.tag.split("}")[-1]
        if tag in FORBIDDEN_EXTRA:
            raise PageError(f"page.extra_svg may not contain <{tag}>")


def compose(page: dict, font: dict) -> dict:
    """Measure the page texts and resolve the body region. Returns the layout `assemble` writes."""
    if not isinstance(page, dict):
        raise PageError("`page` must be an object")
    template = Path(str(page.get("template") or ""))
    if not template.is_file():
        raise PageError(f"page.template {str(template)!r} is not a file")
    root_open, chrome = _chrome(template, str(page.get("chrome_group_id") or "chrome"))
    blocks, residuals = [], []
    seen = set()
    for spec in page.get("texts") or []:
        block, found = layout_text(spec, font)
        if block["id"] in seen:
            raise PageError(f"duplicate page text id {block['id']!r}")
        seen.add(block["id"])
        blocks.append(block)
        residuals += found
    body = dict(page.get("body") or {})
    for key in ("x", "w"):
        if not isinstance(body.get(key), (int, float)):
            raise PageError("page.body needs numeric x and w")
    if body.get("fit") == "between_texts":
        tops = [b["box"]["y"] + b["box"]["h"] for b in blocks if b["edge"] == "top"]
        bottoms = [b["box"]["y"] for b in blocks if b["edge"] == "bottom"]
        if not tops or not bottoms:
            raise PageError("body.fit between_texts needs at least one text with edge top and one with edge bottom")
        y0 = max(tops) + float(body.get("gap_top", 10))
        y1 = min(bottoms) - float(body.get("gap_bottom", 6))
        if isinstance(body.get("y_min"), (int, float)):
            y0 = max(y0, float(body["y_min"]))
        if isinstance(body.get("y_max"), (int, float)):
            y1 = min(y1, float(body["y_max"]))
        region = {"x": float(body["x"]), "y": round(y0, 2), "w": float(body["w"]), "h": round(y1 - y0, 2)}
    else:
        for key in ("y", "h"):
            if not isinstance(body.get(key), (int, float)):
                raise PageError("page.body needs numeric y and h, or fit: \"between_texts\"")
        region = {k: float(body[k]) for k in ("x", "y", "w", "h")}
        for b in blocks:
            bx = b["box"]
            if b["edge"] and bx["y"] < region["y"] + region["h"] and region["y"] < bx["y"] + bx["h"] and \
                    bx["x"] < region["x"] + region["w"] and region["x"] < bx["x"] + bx["w"]:
                residuals.append({"kind": "page_text_in_body", "id": b["id"],
                                  "message": f"page text {b['id']} (y {bx['y']:.0f}-{bx['y'] + bx['h']:.0f}) reaches into the body region"})
    if region["h"] <= 0 or region["w"] <= 0:
        raise PageError(f"the body region is empty: {region}")
    extra = str(page.get("extra_svg") or "")
    if extra:
        _check_extra(extra)
    return {"version": VERSION, "root_open": root_open, "chrome": chrome, "blocks": blocks, "region": region,
            "residuals": residuals, "extra": extra, "template": str(template)}


def _text_svg(b: dict) -> str:
    attrs = [f'id="{escape(b["id"])}"', f'x="{_num(b["x"])}"', f'y="{_num(b["first_baseline"])}"', f'font-size="{_num(b["size"])}"']
    if b["weight"] != "normal":
        attrs.append(f'font-weight="{escape(b["weight"])}"')
    if b.get("style") == "italic":
        attrs.append('font-style="italic"')
    if b["anchor"] != "start":
        attrs.append(f'text-anchor="{b["anchor"]}"')
    attrs.append(f'fill="{escape(b["fill"])}"')
    if b.get("role"):
        attrs.append(f'data-role="{escape(b["role"])}"')
    body = escape(b["lines"][0]) + "".join(f'<tspan x="{_num(b["x"])}" dy="{_num(b["pitch"])}">{escape(line)}</tspan>'
                                           for line in b["lines"][1:])
    return f'<text {" ".join(attrs)}>{body}</text>'


def assemble(layout: dict, body_svg: str, defs: str = "") -> str:
    """The whole page: template root tag, chrome verbatim, then one bounded root group holding the texts and the body."""
    parts = [layout["root_open"]]
    if defs:
        parts.append(f"<defs>{defs}</defs>")
    parts.append(layout["chrome"])
    parts.append(f'<g id="slide-body" data-pptx-bounds="0 0 {_num(CANVAS_W)} {_num(CANVAS_H)}" data-composer="exp_svg.page_compose {VERSION}">')
    parts.append('<g id="page-text">' + "".join(_text_svg(b) for b in layout["blocks"]) + "</g>")
    parts.append(body_svg)
    if layout.get("extra"):
        parts.append(f'<g id="page-extra">{layout["extra"]}</g>')
    parts.append("</g>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def report(layout: dict) -> dict:
    """What the result file says about the page: region, text boxes, residuals."""
    return {"composer": f"exp_svg.page_compose {VERSION}", "region": layout["region"],
            "texts": [{"id": b["id"], "lines": b["lines"], "box": b["box"], "first_baseline": b["first_baseline"]} for b in layout["blocks"]],
            "residuals": layout["residuals"]}
