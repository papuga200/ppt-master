#!/usr/bin/env python3
"""Geometry lint: measure a page in the browser that renders it, and report what a ruler can see.

    page_lint.py <project> <page> [--json] [--no-overlay] [--no-contract]
    page_lint.py --files a.svg b.svg ...            # tuning: many pages, one browser, no project

An author does not see collisions in its own page and a reviewer model misses 12-pixel defects and
sometimes invents them (FORK_RUN_LOG.md). Both are looking. This measures: the page is loaded in
Chromium exactly as the renderer loads it, every text line, stroked line and shape reports its real
rectangle, and plain arithmetic decides. No model call, under two seconds, nothing to hallucinate.

BLOCKERS (the page is not ready for the reviewer)
  TEXT_ON_TEXT    two text lines from different text elements overlap
  LINE_THROUGH_TEXT  a stroked line passes through a text line and keeps going (a line that ENDS at
                  the text is a tether or a connector attaching, and is fine)
  TIGHT_LEADING   a multi-line text set under the line-spacing floor of consulting-typesetting.md (body 1.28 x, heading 1.15 x, title 1.10 x)
  BAR_WITHOUT_LABEL  on a Gantt (six or more thin wide bars) a bar with no text on it or right beside it
  TEXT_OFF_SHAPE  light text runs past the edge of its dark shape onto the light page (invisible), or
                  text crosses the border of a framed box
  SHAPE_ON_TEXT   a small shape (a badge, a marker) sits on a text line that is not its own label
  OFF_CANVAS      text outside the canvas
  CONTRACT        the skill's own checker (svg_quality_checker.py on this one file) reports a blocking
                  issue - the same verdict the deck's final gate would reach, shown now
  MIN_TYPE        (certain, with a crop) text under the floor of its role: body 16 px, secondary 14 px (table
                  cells, diagram and chart labels, callouts, captions), footnote and furniture 11 px - or the
                  lock's `## type_floor`; the rendered size counts, so a scaled group is measured as drawn
  TITLE_SHRUNK / TITLE_LINES / TITLE_WIDOW  (flagged) a title under its layout's size, over two lines,
                  or ending on one word
  DEAD_BAND / UNDERFILLED / HUDDLED  (flagged, with a crop) an empty band across the body over 15% of its
                  height, content in under 55% of it, or the figure squeezed into a strip; never on a cover,
                  divider, statement or closing page (type_floor.page_context)
NOTES (judgement, never blocking)
  TEXT_PAST_SHAPE dark text starts on a shape and continues onto the page (legible; a Gantt habit)
  LINE_THROUGH_NODE a connector crosses a box it is not attached to
  UNUSED          an empty quadrant or an empty band of the content area

Intentional overlap is mostly decided by the geometry itself: text fully inside a shape is its label;
a line that ends at a text is attached to it; a shape covering a third of the canvas, or spanning most
of its width or height, is a container or a band and is ignored. For the rare deliberate exception an
author may put `data-lint-ok="<reason>"` on the element: the item is then WAIVED, never silently
dropped - it is listed for the independent reviewer to confirm. TEXT_ON_TEXT, OFF_CANVAS, light text
off a dark shape and CONTRACT are never waivable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
NEVER_WAIVABLE = {"TEXT_ON_TEXT", "OFF_CANVAS", "CONTRACT", "MIN_TYPE"}
HARD = {"TEXT_ON_TEXT", "OFF_CANVAS", "CONTRACT", "TEXT_INVISIBLE", "MIN_TYPE"}
CROPPED_HARD = {"MIN_TYPE"}  # certain, but the author and the reviewer still see where
FILL_KINDS = {"DEAD_BAND", "UNDERFILLED", "HUDDLED"}

JS_EXTRACT = r"""
() => {
  const svg = document.querySelector('svg');
  const inDefs = el => !!el.closest('defs,clipPath,mask,marker,pattern,symbol,linearGradient,radialGradient');
  const opacity = el => { let o = 1; for (let n = el; n && n.nodeType === 1; n = n.parentElement) { const cs = getComputedStyle(n); if (cs.display === 'none' || cs.visibility === 'hidden') return 0; o *= parseFloat(cs.opacity || '1'); } return o; };
  const groups = el => { const ids = []; for (let n = el.parentElement; n && n !== svg; n = n.parentElement) if (n.id) ids.push(n.id); return ids; };
  // what the markup says an element is, nearest first: role:chrome, layer:master, ph:title, rw:table, tr:<declared type role>
  const CTX = [['data-type-role', 'tr'], ['data-pptx-role', 'role'], ['data-pptx-layer', 'layer'], ['data-pptx-placeholder', 'ph'], ['data-pptx-replace-with', 'rw']];
  const ctx = el => { const out = []; for (let n = el; n && n.nodeType === 1 && n !== svg; n = n.parentElement) CTX.forEach(([a, k]) => { const v = n.getAttribute(a); if (v) out.push(k + ':' + v); }); return out; };
  const rootScale = (() => { const m = svg.getScreenCTM(); return m ? Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) || 1 : 1; })();
  const scaleOf = el => { const m = el.getScreenCTM ? el.getScreenCTM() : null; return m ? Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) / rootScale : 1; };
  const waiver = el => { for (let n = el; n && n.nodeType === 1 && n !== svg.parentElement; n = n.parentElement) { const w = n.getAttribute('data-lint-ok'); if (w !== null) return w || 'declared intentional'; } return null; };
  const R = r => [r.left, r.top, r.right, r.bottom];
  const out = {texts: [], lines: [], shapes: []};
  const order = new Map(); [...svg.querySelectorAll('*')].forEach((el, i) => order.set(el, i));
  const vb = svg.viewBox && svg.viewBox.baseVal && svg.viewBox.baseVal.width ? svg.viewBox.baseVal : {width: svg.clientWidth, height: svg.clientHeight};
  out.canvas = [vb.width, vb.height];
  svg.querySelectorAll('text').forEach((t, index) => {
    if (inDefs(t)) return; const o = opacity(t); if (o < 0.08) return;
    const cs = getComputedStyle(t);
    const painted = c => (c.fill && c.fill !== 'none' && parseFloat(c.fillOpacity || '1') > 0.05) || (c.stroke && c.stroke !== 'none' && parseFloat(c.strokeWidth || '0') > 0);
    const spans = [...t.querySelectorAll('tspan')].filter(s => s.textContent.trim().length);
    const scale = scaleOf(t);
    let parts = (spans.length ? spans : [t]).filter(s => painted(getComputedStyle(s))).map(s => ({rect: R(s.getBoundingClientRect()), text: s.textContent.trim().slice(0, 80), fill: getComputedStyle(s).fill, size: parseFloat(getComputedStyle(s).fontSize) * scale}));
    if (spans.length && painted(cs)) {  // "first line<tspan dy>second line</tspan>": the first line is a bare text node, not a tspan
      [...t.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim().length).forEach(n => {
        const range = document.createRange(); range.selectNodeContents(n);
        parts.unshift({rect: R(range.getBoundingClientRect()), text: n.textContent.trim().slice(0, 80), fill: cs.fill, size: parseFloat(cs.fontSize) * scale});
      });
    }
    parts = parts.filter(p => p.rect[2] - p.rect[0] > 0.5 && p.rect[3] - p.rect[1] > 0.5);
    if (!parts.length) return;
    out.texts.push({index, order: order.get(t), id: t.id || null, text: t.textContent.replace(/\s+/g, ' ').trim().slice(0, 90), parts, fill: cs.fill, size: parseFloat(cs.fontSize), opacity: o, groups: groups(t), waiver: waiver(t),
                    scale, ctx: ctx(t), weight: cs.fontWeight, family: cs.fontFamily, anchor: cs.textAnchor, words: t.textContent.trim().split(/\s+/).filter(Boolean).length});
  });
  const M = (el, p) => { const m = el.getScreenCTM(); return [m.a * p.x + m.c * p.y + m.e, m.b * p.x + m.d * p.y + m.f]; };
  const stroked = cs => cs.stroke && cs.stroke !== 'none' && parseFloat(cs.strokeWidth || '0') > 0 && parseFloat(cs.strokeOpacity || '1') > 0.05;
  const filled = cs => cs.fill && cs.fill !== 'none' && parseFloat(cs.fillOpacity || '1') > 0.05 && !/rgba\(\s*\d+,\s*\d+,\s*\d+,\s*0\s*\)/.test(cs.fill);
  svg.querySelectorAll('line,path,polyline,polygon,rect,circle,ellipse').forEach((el, index) => {
    if (inDefs(el)) return; const o = opacity(el); if (o < 0.08) return;
    const cs = getComputedStyle(el); const tag = el.tagName.toLowerCase();
    const isStroked = stroked(cs), isFilled = filled(cs) && tag !== 'line' && tag !== 'polyline';
    if (!isStroked && !isFilled) return;
    const rect = R(el.getBoundingClientRect());
    const base = {index, order: order.get(el), id: el.id || null, tag, rect, stroke: isStroked ? cs.stroke : null, width: parseFloat(cs.strokeWidth || '0'), dashed: cs.strokeDasharray && cs.strokeDasharray !== 'none',
                  fill: isFilled ? cs.fill : null, opacity: o, groups: groups(el), waiver: waiver(el), ctx: ctx(el)};
    const open = tag === 'line' || tag === 'polyline' || (tag === 'path' && !isFilled);
    const thin = isFilled && tag === 'rect' && Math.min(rect[2] - rect[0], rect[3] - rect[1]) <= 2.5 && Math.max(rect[2] - rect[0], rect[3] - rect[1]) > 12;
    if (thin) {
      const horizontal = (rect[2] - rect[0]) >= (rect[3] - rect[1]); const cx = (rect[0] + rect[2]) / 2, cy = (rect[1] + rect[3]) / 2;
      out.lines.push({...base, stroke: cs.fill, dashed: false, pts: horizontal ? [[rect[0], cy], [rect[2], cy]] : [[cx, rect[1]], [cx, rect[3]]]});
    } else if (open && isStroked) {
      let pts = [];
      if (tag === 'line') { pts = [M(el, {x: el.x1.baseVal.value, y: el.y1.baseVal.value}), M(el, {x: el.x2.baseVal.value, y: el.y2.baseVal.value})]; }
      else { let len = 0; try { len = el.getTotalLength(); } catch (e) { len = 0; } const n = Math.max(1, Math.min(600, Math.ceil(len / 5)));
             for (let i = 0; i <= n; i++) pts.push(M(el, el.getPointAtLength(len * i / n))); }
      out.lines.push({...base, pts});
    } else {
      out.shapes.push({...base, framed: isStroked});
    }
  });
  out.images = [...svg.querySelectorAll('image,use,foreignObject')].filter(el => !inDefs(el) && opacity(el) >= 0.08)
    .map(el => ({rect: R(el.getBoundingClientRect()), ctx: ctx(el), id: el.id || null})).filter(i => i.rect[2] - i.rect[0] > 1 && i.rect[3] - i.rect[1] > 1);
  out.pageRole = svg.getAttribute('data-pptx-page-role') || null;
  return out;
}
"""


def _rgb(colour: str | None) -> tuple[float, float, float] | None:
    match = re.match(r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)", colour or "")
    return tuple(float(match.group(i)) for i in (1, 2, 3)) if match else None


def luminance(colour: str | None) -> float | None:
    rgb = _rgb(colour)
    return None if rgb is None else (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255.0


def area(rect) -> float:
    return max(0.0, rect[2] - rect[0]) * max(0.0, rect[3] - rect[1])


def intersect(a, b):
    rect = [max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])]
    return rect if rect[2] > rect[0] and rect[3] > rect[1] else None


def contains(outer, inner, tolerance: float = 2.0) -> bool:
    return inner[0] >= outer[0] - tolerance and inner[1] >= outer[1] - tolerance and inner[2] <= outer[2] + tolerance and inner[3] <= outer[3] + tolerance


def ink(rect):
    """A text line's rectangle is its line box; the glyphs' ink sits inside it."""
    height = rect[3] - rect[1]
    return [rect[0] + 1.0, rect[1] + 0.20 * height, rect[2] - 1.0, rect[3] - 0.14 * height]


def text_lines(text: dict) -> list[dict]:
    """Merge a text element's tspans into visual lines (runs on one baseline are one line)."""
    lines: list[dict] = []
    for part in sorted(text["parts"], key=lambda p: (p["rect"][1], p["rect"][0])):
        for line in lines:
            overlap = min(line["rect"][3], part["rect"][3]) - max(line["rect"][1], part["rect"][1])
            if overlap > 0.6 * min(line["rect"][3] - line["rect"][1], part["rect"][3] - part["rect"][1]):
                line["rect"] = [min(line["rect"][0], part["rect"][0]), min(line["rect"][1], part["rect"][1]),
                                max(line["rect"][2], part["rect"][2]), max(line["rect"][3], part["rect"][3])]
                line["text"] = (line["text"] + " " + part["text"])[:80]
                break
        else:
            lines.append({"rect": list(part["rect"]), "text": part["text"], "fill": part.get("fill") or text["fill"]})
    return lines


def segment_hits_rect(p, q, rect) -> bool:
    """Liang-Barsky: does the segment p-q pass through the rectangle's interior?"""
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for edge_p, edge_q in ((-dx, p[0] - rect[0]), (dx, rect[2] - p[0]), (-dy, p[1] - rect[1]), (dy, rect[3] - p[1])):
        if abs(edge_p) < 1e-9:
            if edge_q < 0:
                return False
        else:
            r = edge_q / edge_p
            if edge_p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 > t1:
                return False
    return (t1 - t0) * (dx * dx + dy * dy) ** 0.5 > 2.0  # more than a graze


def inside_length(p, q, rect) -> tuple[float, float, float]:
    """Length of the segment p-q inside the rectangle, with its horizontal and vertical travel there."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for edge_p, edge_q in ((-dx, p[0] - rect[0]), (dx, rect[2] - p[0]), (-dy, p[1] - rect[1]), (dy, rect[3] - p[1])):
        if abs(edge_p) < 1e-9:
            if edge_q < 0:
                return 0.0, 0.0, 0.0
        else:
            r = edge_q / edge_p
            if edge_p < 0:
                t0 = max(t0, r)
            else:
                t1 = min(t1, r)
            if t0 > t1:
                return 0.0, 0.0, 0.0
    span = t1 - t0
    return span * (dx * dx + dy * dy) ** 0.5, abs(span * dx), abs(span * dy)


def traverses(runs: list[list], rect) -> bool:
    """A line crosses a text when it travels most of the way across it - top to bottom or side to side - wherever it starts."""
    travelled_x = sum(inside_length(p, q, rect)[1] for run in runs for p, q in zip(run, run[1:]))
    travelled_y = sum(inside_length(p, q, rect)[2] for run in runs for p, q in zip(run, run[1:]))
    return travelled_y >= 0.7 * (rect[3] - rect[1]) or travelled_x >= 0.7 * (rect[2] - rect[0])


def polyline_runs(points: list, step_hint: float = 5.0) -> list[list]:
    """Sampled paths jump between subpaths: break the polyline where consecutive samples are far apart."""
    runs, current = [], [points[0]] if points else []
    for previous, point in zip(points, points[1:]):
        if ((point[0] - previous[0]) ** 2 + (point[1] - previous[1]) ** 2) ** 0.5 > max(30.0, 6 * step_hint) and len(points) > 2:
            runs.append(current)
            current = [point]
        else:
            current.append(point)
    if current:
        runs.append(current)
    return [run for run in runs if len(run) > 1]


def near(point, rect, margin: float) -> bool:
    return rect[0] - margin <= point[0] <= rect[2] + margin and rect[1] - margin <= point[1] <= rect[3] + margin


def hidden_by(shapes: list[dict], region, below_order: int, above_order: int) -> bool:
    """Is `region` of something painted at `below_order` covered by an opaque shape painted later, under the text at `above_order`?"""
    return any(below_order < s["order"] < above_order and s["fill"] and s["opacity"] > 0.85 and contains(s["rect"], region, 1.0) for s in shapes)


class Pixels:
    def __init__(self, png_bytes: bytes | None, width: float, height: float) -> None:
        self.image = None
        if png_bytes:
            import io
            from PIL import Image
            self.image = Image.open(io.BytesIO(png_bytes)).convert("L")
            self.sx, self.sy = self.image.width / width, self.image.height / height

    def light_share(self, rect) -> float | None:
        """Share of light pixels in a region: where light text overhangs onto it, the text cannot be read."""
        if self.image is None or rect[2] - rect[0] < 1 or rect[3] - rect[1] < 1:
            return None
        box = (max(0, int(rect[0] * self.sx)), max(0, int(rect[1] * self.sy)), min(self.image.width, int(rect[2] * self.sx) + 1), min(self.image.height, int(rect[3] * self.sy) + 1))
        histogram = self.image.crop(box).histogram()
        total = sum(histogram)
        return sum(histogram[200:]) / total if total else None


def analyse(geometry: dict, png_bytes: bytes | None = None, content_area=None, is_cover: bool = False, page: dict | None = None) -> list[dict]:
    """`page`: the page context from type_floor.page_context (floors, title size, sparse). With it the type floor, the title checks
    and the fill checks run; without it (unit tests of the geometry rules) they do not."""
    width, height = geometry.get("canvas") or [1280, 720]
    canvas_area = width * height
    findings: list[dict] = []
    pixels = Pixels(png_bytes, width, height)

    def add(kind: str, severity: str, where, message: str, waiver: str | None = None) -> None:
        if waiver and kind not in NEVER_WAIVABLE and severity == "blocker":
            severity, message = "waived", f"{message} [declared intentional: {waiver}]"
        findings.append({"kind": kind, "severity": severity, "hard": kind in HARD, "rect": [round(v, 1) for v in where], "message": message})

    texts = [{**t, "lines": text_lines(t)} for t in geometry["texts"]]
    shapes = [s for s in geometry["shapes"] if area(s["rect"]) > 4]
    # a container, a band or a backdrop is not something text collides with
    def structural(shape) -> bool:
        w, h = shape["rect"][2] - shape["rect"][0], shape["rect"][3] - shape["rect"][1]
        return area(shape["rect"]) > 0.30 * canvas_area or w > 0.70 * width or h > 0.70 * height

    # TEXT_ON_TEXT
    flat = [(t, line) for t in texts for line in t["lines"]]
    for i, (ta, la) in enumerate(flat):
        for tb, lb in flat[i + 1:]:
            if ta["index"] == tb["index"]:
                continue
            hit = intersect(ink(la["rect"]), ink(lb["rect"]))
            if hit and la["text"] == lb["text"] and area(hit) > 0.8 * min(area(ink(la["rect"])), area(ink(lb["rect"]))):
                continue
            if hit and hit[2] - hit[0] > 1.5 and hit[3] - hit[1] > 1.0 and area(hit) > 0.04 * min(area(ink(la["rect"])), area(ink(lb["rect"]))):
                add("TEXT_ON_TEXT", "blocker", hit, f'"{la["text"][:48]}" overlaps "{lb["text"][:48]}" by {hit[2] - hit[0]:.0f}x{hit[3] - hit[1]:.0f} px')

    # TIGHT_LEADING: line spacing under the floor of consulting-typesetting.md §1 (one finding per text element)
    for t in texts:
        tops = sorted(line["rect"][1] for line in t["lines"])
        size = t.get("size") or 0
        if len(tops) < 2 or size <= 0:
            continue
        pitch = min(b - a for a, b in zip(tops, tops[1:]) if b - a > 0.5 * size) if any(b - a > 0.5 * size for a, b in zip(tops, tops[1:])) else None
        if pitch is None:
            continue
        floor, target = (1.10, "1.15-1.2") if size >= 24 else (1.15, "1.2-1.3") if size >= 15 else (1.28, "1.4-1.5")
        if pitch / size < floor:
            box = [min(l["rect"][0] for l in t["lines"]), tops[0], max(l["rect"][2] for l in t["lines"]), max(l["rect"][3] for l in t["lines"])]
            add("TIGHT_LEADING", "blocker", box, f'"{t["text"][:48]}" is set at {pitch / size:.2f} x line spacing ({size:.0f} px type, {pitch:.0f} px lines): '
                f"open it to {target} x - shorten the words or restructure, do not squeeze the lines", t["waiver"])

    # OFF_CANVAS
    for t, line in flat:
        r = line["rect"]
        if r[0] < -2 or r[1] < -2 or r[2] > width + 2 or r[3] > height + 2:
            add("OFF_CANVAS", "blocker", r, f'"{line["text"][:60]}" runs off the canvas')

    # LINE_THROUGH_TEXT and LINE_THROUGH_NODE
    nodes = [s for s in shapes if not structural(s) and area(s["rect"]) < 0.12 * canvas_area
             and any(contains(s["rect"], line["rect"], 3) for t in texts for line in t["lines"])]
    for ln in geometry["lines"]:
        if ln["opacity"] < 0.15 or len(ln["pts"]) < 2:
            continue
        ends = [ln["pts"][0], ln["pts"][-1]]
        runs = polyline_runs(ln["pts"])
        for t, line in flat:
            box = line["rect"]
            rect = [box[0] + 1.0, box[1] + 0.16 * (box[3] - box[1]), box[2] - 1.0, box[3] - 0.10 * (box[3] - box[1])]
            if not any(segment_hits_rect(p, q, rect) for run in runs for p, q in zip(run, run[1:])):
                continue
            if any(near(end, line["rect"], 5) for end in ends) and not traverses(runs, rect):
                continue  # the line ends at this text without running through it: a tether or a leader
            if True:
                if hidden_by(geometry["shapes"], rect, ln["order"], t["order"]):
                    continue  # the line runs behind the shape this text sits on (a grid line under a bar)
                name = ln["id"] or f'{ln["tag"]} #{ln["index"]}'
                add("LINE_THROUGH_TEXT", "blocker", line["rect"], f'"{line["text"][:60]}" is crossed by line {name}' + (" (dashed)" if ln["dashed"] else ""), t["waiver"] or ln["waiver"])
        for node in nodes:
            inner = [node["rect"][0] + 5, node["rect"][1] + 5, node["rect"][2] - 5, node["rect"][3] - 5]
            if inner[2] <= inner[0] or inner[3] <= inner[1] or any(near(end, node["rect"], 8) for end in ends):
                continue
            if node["fill"] and node["opacity"] > 0.85 and ln["order"] < node["order"]:
                continue  # painted before an opaque box: the line passes behind it
            if set(ln["groups"]) & set(node["groups"]) or (ln["groups"] and node["id"] and node["id"] in ln["groups"]):
                continue
            if any(segment_hits_rect(p, q, inner) for run in runs for p, q in zip(run, run[1:])):
                add("LINE_THROUGH_NODE", "note", node["rect"], f'line {ln["id"] or ln["tag"] + " #" + str(ln["index"])} crosses box {node["id"] or "#" + str(node["index"])} without attaching to it')

    # TEXT_OFF_SHAPE, TEXT_PAST_SHAPE, SHAPE_ON_TEXT
    for t, line in flat:
        rect = ink(line["rect"])
        text_lum = luminance(line.get("fill") or t["fill"])
        # the text's own background: the topmost opaque shape that holds the whole line (a numeral's badge, a label's box)
        backing = max((s["order"] for s in geometry["shapes"] if s["fill"] and s["opacity"] > 0.85 and s["order"] < t["order"] and contains(s["rect"], rect, 2.5)), default=-1)
        for shape in shapes:
            if structural(shape) or shape["order"] < backing:
                continue  # what lies under the text's own background does not touch the text
            hit = intersect(rect, shape["rect"])
            if not hit or contains(shape["rect"], rect, 2.5):
                continue
            share_of_text, share_of_shape = area(hit) / max(area(rect), 1), area(hit) / max(area(shape["rect"]), 1)
            sideways = max(shape["rect"][0] - rect[0], rect[2] - shape["rect"][2])
            vertical = max(shape["rect"][1] - rect[1], rect[3] - shape["rect"][3])
            outside = max(sideways, vertical)
            sticks_out = sideways > max(4.0, 0.45 * (t.get("size") or 12)) or vertical > 2.5
            shape_lum = luminance(shape["fill"])
            shape_name = shape["id"] or f'{shape["tag"]} #{shape["index"]}'
            if share_of_text >= 0.20 and sticks_out:
                overhang = [max(rect[0], shape["rect"][2]) if rect[2] > shape["rect"][2] + 3 else rect[0], rect[1],
                            min(rect[2], shape["rect"][0]) if rect[0] < shape["rect"][0] - 3 else rect[2], rect[3]]
                light_under = pixels.light_share(overhang) if overhang[2] > overhang[0] else None
                if text_lum is not None and shape_lum is not None and text_lum >= 0.70 and shape_lum <= 0.55 and (light_under is None or light_under > 0.80):
                    add("TEXT_INVISIBLE", "blocker", line["rect"], f'light text "{line["text"][:60]}" runs {outside:.0f} px past the edge of its dark shape {shape_name}: the overhang is invisible on the page')
                elif shape["framed"] and shape["fill"] is None:
                    add("TEXT_OFF_SHAPE", "blocker", line["rect"], f'"{line["text"][:60]}" crosses the border of box {shape_name} by {outside:.0f} px', t["waiver"] or shape["waiver"])
                elif shape["framed"]:
                    add("TEXT_OFF_SHAPE", "blocker", line["rect"], f'"{line["text"][:60]}" overflows box {shape_name} by {outside:.0f} px', t["waiver"] or shape["waiver"])
                elif vertical > 2.5 and vertical >= sideways:
                    # a line of text straddling a shape's top or bottom edge sits on two backgrounds at once, whatever its colour
                    add("TEXT_OFF_SHAPE", "blocker", line["rect"], f'"{line["text"][:60]}" straddles the edge of {shape_name}: {vertical:.0f} px of the line hangs outside it', t["waiver"] or shape["waiver"])
                else:
                    add("TEXT_PAST_SHAPE", "note", line["rect"], f'"{line["text"][:60]}" starts on {shape_name} and runs {outside:.0f} px past it')
            elif share_of_shape >= 0.35 and share_of_text < 0.20 and area(shape["rect"]) < 0.01 * canvas_area:
                add("SHAPE_ON_TEXT", "blocker", hit, f'shape {shape_name} sits on "{line["text"][:60]}"', t["waiver"] or shape["waiver"])

    # BAR_WITHOUT_LABEL: on a page that is visibly a Gantt (six or more thin wide bars), every bar is named on it or right beside it
    def bar_like(shape) -> bool:
        w, h = shape["rect"][2] - shape["rect"][0], shape["rect"][3] - shape["rect"][1]
        lum = luminance(shape["fill"])
        return (shape["tag"] == "rect" and shape["fill"] and not structural(shape) and 6 <= h <= 26 and w >= max(24, 2.2 * h) and w < 0.6 * width
                and lum is not None and lum < 0.80)  # a bar is painted; a pale band or a table stripe is not one

    bars = [s for s in shapes if bar_like(s)]
    if len(bars) >= 6:
        for bar in bars:
            left, top, right, bottom = bar["rect"]
            named = False
            for t, line in flat:
                r = line["rect"]
                level = min(bottom, r[3]) - max(top, r[1]) > 0.4 * min(bottom - top, r[3] - r[1])
                inside = r[0] >= left - 2 and r[2] <= right + 2
                beside = (0 <= r[0] - right <= 14) or (0 <= left - r[2] <= 14)
                straddles = r[0] < right and r[2] > left
                if level and (inside or beside or straddles):
                    named = True
                    break
            if not named:
                add("BAR_WITHOUT_LABEL", "blocker", bar["rect"], f"bar {bar['id'] or '#' + str(bar['index'])} ({right - left:.0f} px wide) has no label on it or beside it: "
                    "name every bar where it is - inside when it fits, otherwise starting 6 px after its end (consulting-typesetting.md §6)", bar["waiver"])

    # MIN_TYPE, TITLE_*, and DEAD_BAND / UNDERFILLED / HUDDLED: only when the caller gives the page's context (lint_page always does)
    if page is not None:
        classify_roles(texts, shapes, width, height, sparse=bool(page.get("sparse")) or is_cover)
        findings.extend(type_findings(texts, page, width, height))
        if not page.get("sparse") and not is_cover:
            findings.extend(fill_findings(geometry, texts, shapes, width, height, content_area))

    # UNUSED canvas (from the pixels): the quadrant and right-edge notes; the empty foot is DEAD_BAND's when the page context is known
    if png_bytes and not is_cover and not (page is not None and page.get("sparse")):
        findings.extend(u for u in unused_canvas(png_bytes, width, height, content_area) if page is None or "unused at the foot" not in u["message"])
    return findings


# ---------------------------------------------------------------------------------------------------------------------------
# Type floor (MIN_TYPE) and title checks. The role of each text decides its floor; the markup can say it (data-type-role), and
# otherwise the geometry does. Floors: type_floor.py (spec_lock.md `## type_floor`, default 16 / 14 / 11 px).
# ---------------------------------------------------------------------------------------------------------------------------
# Running text (body) is a paragraph wider than 30% of the canvas or one line wider than half of it. A narrower block is a callout, a gloss,
# a stage note or a label (secondary), and so is a single line of moderate width (a caption, a one-line descriptor). Tuned on the
# 28 Sep self-documentation deck, whose 352-368 px margin notes and one-line route descriptions are callouts, not prose.
BODY_PARAGRAPH_SHARE, BODY_LINE_SHARE = 0.30, 0.50
FURNITURE_CTX = {"role:chrome", "role:footer", "role:header", "role:page-number", "role:logo", "role:background", "layer:master", "layer:layout",
                 "ph:footer", "ph:slide-number", "ph:date", "ph:sldnum", "ph:ftr", "ph:dt"}
FURNITURE_ID = re.compile(r"(?i)(?:^|[-_])(?:chrome|footer|folio|running|(?:page|slide|deck|top)-?header|page-?number|slide-?number|page-?num|tracker|breadcrumb|eyebrow|kicker)(?:[-_]|$)")
TITLE_ID = re.compile(r"(?i)^(?:page-|slide-|sample-|main-|chrome-)?title(?:[-_](?:slot|carrier|text|group|block|zone|area|line\d*))?$")
# a source line is named so (`source`, `page-source`, `source-line`, `footnote`); a `source-rail` in a data-flow diagram is not one
SOURCE_ID = re.compile(r"(?i)^(?:(?:page|slide|sample|exhibit|figure|table|chart|footer|cost|deck)[-_])?(?:sources?|footnotes?|provenance)(?:[-_](?:line|lines|note|notes|slot|text|strip|carrier|and-folio))?$|footnote")
MONOSPACE = re.compile(r"(?i)mono|consolas|courier|menlo|monaco")
SOURCE_TEXT = re.compile(r"(?i)^\s*(?:sources?|notes?|footnotes?|n\.\s?b\.)\s*[:.–—-]|^\s*[*†‡¹²³⁴]\s*\S")
CALLOUT_ID = re.compile(r"(?i)(?:^|[-_])(?:caption|captions|legend|label|labels|gloss|glosses|annotation|annotations|callout|callouts|note|notes|badge|axis|tick|ticks|marker)(?:[-_\d]|$)")
LIST_MARKER = re.compile(r"^\s*(?:[■▪●•◆◇◦‣·–—-]|\d{1,2}[.)])\s+\S")
LETTER = re.compile(r"[^\W_]")  # a letter or digit in any script; a check mark, arrow or bullet on its own is not text
DECLARED_ROLES = ("title", "body", "secondary", "footnote", "furniture")


def _ctx(item) -> list[str]:
    return [c.casefold() for c in (item.get("ctx") or [])]


def _ids(text) -> list[str]:
    return [i for i in ([text.get("id")] + list(text.get("groups") or [])) if i]


def _box(text) -> list[float]:
    rects = [line["rect"] for line in text.get("lines") or []] or [p["rect"] for p in text.get("parts") or []] or ([text["rect"]] if text.get("rect") else [])
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)] if rects else [0, 0, 0, 0]


def effective_sizes(text) -> list[float]:
    """The rendered size of each run that carries letters or digits: its font size times the scale of every transform above it.
    A lone marker, a superscript note sign or a bullet does not set the text's size."""
    parts = text.get("parts") or []
    scale = text.get("scale") or 1.0
    sized = [(p.get("size") if p.get("size") else (text.get("size") or 0) * scale, p.get("text") or "") for p in parts]
    wordy = [size for size, words in sized if size and LETTER.search(words) and (len(words.strip()) > 2 or len(sized) == 1)]
    if wordy:
        return wordy
    fallback = [size for size, words in sized if size and LETTER.search(words)]
    return fallback or ([(text.get("size") or 0) * scale] if text.get("size") else [])


def classify_roles(texts: list[dict], shapes: list[dict], width: float, height: float, sparse: bool = False) -> None:
    """Give every text a type role (title, body, secondary, footnote, furniture), the reason, and its smallest rendered size, in place."""
    containers = [s for s in shapes if (s.get("fill") or s.get("framed")) and area(s["rect"]) < 0.30 * width * height
                  and s["rect"][2] - s["rect"][0] < 0.70 * width and not (set(_ctx(s)) & FURNITURE_CTX)]
    # a small line at the foot of the page is a note or source line only when no other content text sits below it
    content_tops = [_box(t)[1] for t in texts if not (set(_ctx(t)) & FURNITURE_CTX) and not any(FURNITURE_ID.search(i) for i in _ids(t))
                    and _box(t)[1] < 0.95 * height]
    for t in texts:
        ctx, ids, box = _ctx(t), _ids(t), _box(t)
        words = t.get("text") or ""
        sizes = effective_sizes(t)
        size = max(sizes) if sizes else 0
        declared = next((c.split(":", 1)[1] for c in ctx if c.startswith("tr:")), None)
        lines = len(t.get("lines") or [])
        if declared in DECLARED_ROLES:
            role, why = declared, "declared data-type-role"
        elif set(ctx) & FURNITURE_CTX:
            role, why = "furniture", "chrome, running header or footer"
        elif any(c in ("rw:table", "rw:chart") for c in ctx) and not SOURCE_TEXT.match(words):
            role, why = "secondary", "native " + next(c.split(":")[1] for c in ctx if c in ("rw:table", "rw:chart")) + " text"
        elif any(FURNITURE_ID.search(i) for i in ids):
            role, why = "furniture", "chrome, running header or footer"
        elif any(c in ("ph:title", "ph:ctrtitle", "ph:center-title") for c in ctx) or any(TITLE_ID.match(i) for i in ids):
            role, why = "title", "title placeholder"
        elif any(SOURCE_ID.search(i) for i in ids) or SOURCE_TEXT.match(words):
            role, why = "footnote", "source or note line"
        elif re.fullmatch(r"\d{1,3}", words.strip()) and box[1] > 0.85 * height:
            role, why = "furniture", "folio"
        elif box[3] < 0.08 * height and size < 16:
            role, why = "furniture", "running header band"
        elif box[1] > 0.85 * height and size < 13 and lines == 1 and not any(top > box[3] - 2 for top in content_tops):
            role, why = "footnote", "small last line at the foot of the page"
        elif sparse and box[1] > 0.55 * height and size < 16:
            role, why = "furniture", "meta line on a cover or closing page"
        elif any(CALLOUT_ID.search(i) for i in ids):
            role, why = "secondary", "caption, label, note or legend"
        elif MONOSPACE.search(t.get("family") or ""):
            role, why = "secondary", "code, command or reference set in monospace"
        else:
            holder = min((s for s in containers if contains(s["rect"], box, 3.0)), key=lambda s: area(s["rect"]), default=None)
            text_width = box[2] - box[0]
            word_count = t.get("words") or len(words.split())
            if LIST_MARKER.match(words) and (lines >= 2 or word_count >= 6):
                role, why = "body", "list item"
            elif holder is not None and holder["rect"][2] - holder["rect"][0] < BODY_PARAGRAPH_SHARE * width:
                role, why = "secondary", "label or note inside a shape"
            elif lines >= 3 and word_count >= 20:
                role, why = "body", "running text (a paragraph)"
            elif lines >= 2 and text_width >= BODY_PARAGRAPH_SHARE * width:
                role, why = "body", "running text (a paragraph)"
            elif text_width >= BODY_LINE_SHARE * width:
                role, why = "body", "running text (a line across half the page)"
            else:
                role, why = "secondary", "label, callout, note or caption" if lines >= 2 else "short label, callout or caption"
        t["role"], t["role_why"], t["px"] = role, why, (min(sizes) if sizes and LETTER.search(words) else 0.0)  # a lone symbol is not text
    # a title group can hold an eyebrow above the title and a deck line under it: only its largest type is the title
    titles = [t for t in texts if t["role"] == "title" and t["role_why"] != "declared data-type-role"]
    if titles:
        top_size = max(max(effective_sizes(t) or [0]) for t in titles)
        title_top = min(_box(t)[1] for t in titles if max(effective_sizes(t) or [0]) >= 0.8 * top_size)
        for t in titles:
            if max(effective_sizes(t) or [0]) < 0.8 * top_size:
                above = _box(t)[3] <= title_top + 2
                t["role"], t["role_why"] = ("furniture", "eyebrow above the title") if above else ("body", "line under the title")
    elif texts:
        # no marked title: the largest type in the top third of the page, when it is display-sized
        candidates = [t for t in texts if t["role"] not in ("furniture", "footnote") and _box(t)[1] < 0.30 * height and max(effective_sizes(t) or [0]) >= 20]
        if candidates:
            top_size = max(max(effective_sizes(t)) for t in candidates)
            for t in candidates:
                if max(effective_sizes(t)) >= 0.9 * top_size:
                    t["role"], t["role_why"] = "title", "largest type at the top of the page"


def title_lines(texts: list[dict]) -> list[dict]:
    lines = [dict(line) for t in texts if t.get("role") == "title" for line in (t.get("lines") or [])]
    lines.sort(key=lambda l: (l["rect"][1], l["rect"][0]))
    merged: list[dict] = []
    for line in lines:
        if merged and min(merged[-1]["rect"][3], line["rect"][3]) - max(merged[-1]["rect"][1], line["rect"][1]) > 0.5 * (line["rect"][3] - line["rect"][1]):
            merged[-1]["text"] += " " + line["text"]
            merged[-1]["rect"] = [min(merged[-1]["rect"][0], line["rect"][0]), merged[-1]["rect"][1], max(merged[-1]["rect"][2], line["rect"][2]), merged[-1]["rect"][3]]
        else:
            merged.append(line)
    return merged


def type_findings(texts: list[dict], page: dict, width: float, height: float) -> list[dict]:
    """MIN_TYPE (certain) for text under its role's floor, grouped by role, size and owning group; TITLE_SHRUNK, TITLE_LINES and
    TITLE_WIDOW (flagged) for a title set under the layout's title size, over two lines, or ending on one word."""
    floors = dict(page.get("floors") or {"body": 16.0, "secondary": 14.0, "footnote": 11.0})
    floors.setdefault("furniture", floors.get("footnote", 11.0))
    groups: dict[tuple, dict] = {}
    for t in texts:
        role = t.get("role")
        if role not in floors or role == "title":
            continue
        floor = floors[role]
        px = t.get("px") or 0.0
        if px <= 0 or px >= floor - 0.05:
            continue
        owner = next((g for g in (t.get("groups") or []) if g and g.lower() not in ("page", "content", "body")), None)
        key = (role, round(px, 1), owner)
        entry = groups.setdefault(key, {"rects": [], "texts": [], "why": t.get("role_why") or ""})
        entry["rects"].append(_box(t))
        entry["texts"].append((t.get("text") or "")[:40])
    findings = []
    for (role, px, owner), entry in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        rects = entry["rects"]
        rect = [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]
        floor = floors[role]
        sample = "; ".join(f'"{x}"' for x in entry["texts"][:3]) + (f" and {len(entry['texts']) - 3} more" if len(entry["texts"]) > 3 else "")
        where = f" in {owner}" if owner else ""
        label = "furniture (header, footer, folio, eyebrow)" if role == "furniture" else role
        findings.append({"kind": "MIN_TYPE", "severity": "blocker", "hard": True, "rect": [round(v, 1) for v in rect], "role": role, "px": px, "floor": floor,
                         "count": len(entry["texts"]),
                         "message": f"{len(entry['texts'])} {label} text(s){where} at {px:g} px, under the {floor:g} px floor for {role} "
                                    f"({entry['why']}): {sample}. Never shrink below the floor to fit: cut the copy, move detail to the notes or an "
                                    f"appendix page, or change the exhibit; then set it at {floor:g} px or more"})
    title_size = page.get("title_size")
    titles = [t for t in texts if t.get("role") == "title"]
    if titles and title_size:
        drawn = max(max(effective_sizes(t) or [0]) for t in titles)
        if 0 < drawn < title_size - 1.0:
            box = _box(max(titles, key=lambda t: max(effective_sizes(t) or [0])))
            findings.append({"kind": "TITLE_SHRUNK", "severity": "blocker", "hard": False, "rect": [round(v, 1) for v in box],
                             "message": f"the title is set at {drawn:g} px, under the layout's {title_size:g} px title size: shorten the title "
                                        "(a full-sentence claim of 15 words or fewer, two lines at most) instead of shrinking it"})
    lines = title_lines(titles)
    if len(lines) > 2:
        box = [min(l["rect"][0] for l in lines), lines[0]["rect"][1], max(l["rect"][2] for l in lines), lines[-1]["rect"][3]]
        findings.append({"kind": "TITLE_LINES", "severity": "blocker", "hard": False, "rect": [round(v, 1) for v in box],
                         "message": f"the title runs to {len(lines)} lines; a consulting title is two lines at most at the design size: cut it to its claim"})
    if len(lines) >= 2 and len(lines[-1]["text"].split()) == 1:
        findings.append({"kind": "TITLE_WIDOW", "severity": "blocker", "hard": False, "rect": [round(v, 1) for v in lines[-1]["rect"]],
                         "message": f'the title\'s last line is one word ("{lines[-1]["text"].strip()}"): rewrap or reword so the last line carries at least two words'})
    return findings


# ---------------------------------------------------------------------------------------------------------------------------
# Fill: is the body zone used? A band across the whole width with no ink, a page whose content stops early, or a figure huddled
# in a strip. Flagged, never certain: whitespace around a hero element is a design choice, and the reviewer rules from the crop.
# ---------------------------------------------------------------------------------------------------------------------------
DEAD_BAND_SHARE = 0.15
UNDERFILLED_SHARE = 0.55
HUDDLED_SHARE, HUDDLED_EMPTY = 0.35, 0.30
EXCLUDED_CTX = {"role:chrome", "role:background", "role:header", "role:footer", "role:logo", "role:page-number", "layer:master", "layer:layout"}


def body_zone(texts: list[dict], width: float, height: float, content_area=None) -> tuple[float, float]:
    """From the bottom of the title block (title, eyebrow, running header) to the top of the footer block (sources, footer, folio)."""
    top_items = [_box(t)[3] for t in texts if t.get("role") in ("title", "furniture") and _box(t)[1] < 0.35 * height]
    top = max(top_items) if top_items else (content_area[1] if content_area else 0.18 * height)
    foot_items = [_box(t)[1] for t in texts if t.get("role") in ("footnote", "furniture") and _box(t)[1] > 0.75 * height]
    bottom = min(foot_items) if foot_items else (content_area[3] if content_area else height - 56)
    return top + 6, bottom - 6


def ink_items(geometry: dict, texts: list[dict], shapes: list[dict], width: float, height: float, top: float, bottom: float) -> list[dict]:
    """What a reader sees as content in the body zone: text lines, shapes that are not backdrops, lines, images; not the chrome."""
    items = []
    for t in texts:
        if t.get("role") == "title" or set(_ctx(t)) & EXCLUDED_CTX:
            continue
        for line in t.get("lines") or []:
            items.append({"rect": ink(line["rect"]), "kind": "text"})
    for s in shapes:
        w, h = s["rect"][2] - s["rect"][0], s["rect"][3] - s["rect"][1]
        if set(_ctx(s)) & EXCLUDED_CTX or area(s["rect"]) > 0.30 * width * height or w > 0.70 * width or h > 0.70 * height:
            continue
        items.append({"rect": s["rect"], "kind": "shape"})
    for ln in geometry.get("lines") or []:
        if set(_ctx(ln)) & EXCLUDED_CTX or ln.get("opacity", 1) < 0.15 or len(ln.get("pts") or []) < 2:
            continue
        xs, ys = [p[0] for p in ln["pts"]], [p[1] for p in ln["pts"]]
        if max(ys) - min(ys) > 0.70 * (bottom - top) and max(xs) - min(xs) < 6:
            continue  # a full-height divider structures the page; it does not fill it
        items.append({"rect": [min(xs), min(ys), max(xs), max(ys)], "kind": "line"})
    for image in geometry.get("images") or []:
        if not set(_ctx(image)) & EXCLUDED_CTX:
            items.append({"rect": image["rect"], "kind": "image"})
    return [i for i in items if i["rect"][3] > top and i["rect"][1] < bottom]


def fill_findings(geometry: dict, texts: list[dict], shapes: list[dict], width: float, height: float, content_area=None) -> list[dict]:
    top, bottom = body_zone(texts, width, height, content_area)
    body_h = bottom - top
    if body_h < 0.2 * height:
        return []
    x0, x1 = (content_area[0], content_area[2]) if content_area else (0.04 * width, 0.96 * width)
    items = ink_items(geometry, texts, shapes, width, height, top, bottom)
    step = 4.0
    rows = int(body_h // step)
    inked = [False] * rows
    for item in items:
        first = max(0, int((item["rect"][1] - top) // step))
        last = min(rows - 1, int((item["rect"][3] - top) // step))
        for r in range(first, last + 1):
            inked[r] = True
    findings: list[dict] = []
    if not any(inked):
        return [{"kind": "UNDERFILLED", "severity": "blocker", "hard": False, "rect": [round(x0, 1), round(top, 1), round(x1, 1), round(bottom, 1)],
                 "message": "the body zone between the title and the footer is empty: is this page meant to be a divider?"}]
    first_ink = inked.index(True)
    last_ink = rows - 1 - inked[::-1].index(True)
    extent = (last_ink - first_ink + 1) * step
    underfilled = extent < UNDERFILLED_SHARE * body_h
    if underfilled:
        findings.append({"kind": "UNDERFILLED", "severity": "blocker", "hard": False, "rect": [round(x0, 1), round(top, 1), round(x1, 1), round(bottom, 1)],
                         "message": f"the content spans y={top + first_ink * step:.0f}-{top + (last_ink + 1) * step:.0f}, {100 * extent / body_h:.0f}% of the body "
                                    f"height ({top:.0f}-{bottom:.0f}): intended whitespace around a hero element, or dead space? Enlarge the exhibit, "
                                    "spread the groups, or plan a sparser page"})
    run_start = None
    for r in range(rows + 1):
        empty = r < rows and not inked[r]
        if empty and run_start is None:
            run_start = r
        elif not empty and run_start is not None:
            span = (r - run_start) * step
            at_edge = run_start == 0 or r == rows
            if span > DEAD_BAND_SHARE * body_h and not (underfilled and at_edge):
                y_a, y_b = top + run_start * step, top + r * step
                where = "above the content" if run_start == 0 else "below the content" if r == rows else "between two groups"
                findings.append({"kind": "DEAD_BAND", "severity": "blocker", "hard": False, "rect": [round(x0, 1), round(y_a, 1), round(x1, 1), round(y_b, 1)],
                                 "message": f"a band across the full width, y={y_a:.0f}-{y_b:.0f} ({span:.0f} px, {100 * span / body_h:.0f}% of the body height), "
                                            f"holds nothing ({where}): intended whitespace around a hero element, or dead space? Use it - enlarge the "
                                            "figure, move the takeaway or evidence into it - or close it up"})
            run_start = None
    # HUDDLED: the page's figure (the largest cluster of shapes and connectors) squeezed into a strip while the body stays empty
    graphic = [i for i in items if i["kind"] in ("shape", "line")]
    if len(graphic) >= 4:
        parent = list(range(len(graphic)))

        def find(a: int) -> int:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for a in range(len(graphic)):
            ra = graphic[a]["rect"]
            for b in range(a + 1, len(graphic)):
                rb = graphic[b]["rect"]
                if ra[0] - 16 <= rb[2] and rb[0] - 16 <= ra[2] and ra[1] - 16 <= rb[3] and rb[1] - 16 <= ra[3]:
                    parent[find(a)] = find(b)
        clusters: dict[int, list] = {}
        for a in range(len(graphic)):
            clusters.setdefault(find(a), []).append(graphic[a])
        best = max(clusters.values(), key=len)
        if len(best) >= 4 and any(i["kind"] == "line" for i in best):
            box = [min(i["rect"][0] for i in best), min(i["rect"][1] for i in best), max(i["rect"][2] for i in best), max(i["rect"][3] for i in best)]
            empty_share = 1 - sum(inked) / rows
            fig_h = min(box[3], bottom) - max(box[1], top)
            if fig_h < HUDDLED_SHARE * body_h and empty_share > HUDDLED_EMPTY:
                findings.append({"kind": "HUDDLED", "severity": "blocker", "hard": False, "rect": [round(v, 1) for v in box],
                                 "message": f"the figure is {fig_h:.0f} px tall, {100 * fig_h / body_h:.0f}% of the body height, while {100 * empty_share:.0f}% "
                                            "of the body rows hold nothing: give the figure the space (larger nodes, type at the floor or above, room for its labels)"})
    return findings


def unused_canvas(png_bytes: bytes, width: float, height: float, content_area) -> list[dict]:
    import io
    from PIL import Image
    image = Image.open(io.BytesIO(png_bytes)).convert("L")
    sx, sy = image.width / width, image.height / height
    x0, y0, x1, y1 = content_area or (54, 146, width - 54, height - 56)
    cell = 16
    columns, rows = int((x1 - x0) // cell), int((y1 - y0) // cell)
    if columns < 4 or rows < 4:
        return []
    background = image.getpixel((int((x0 + 4) * sx), int((y0 + 4) * sy)))
    grid = []
    for r in range(rows):
        row = []
        for c in range(columns):
            box = (int((x0 + c * cell) * sx), int((y0 + r * cell) * sy), int((x0 + (c + 1) * cell) * sx), int((y0 + (r + 1) * cell) * sy))
            low, high = image.crop(box).getextrema()
            row.append(abs(low - background) > 14 or abs(high - background) > 14)
        grid.append(row)
    total = sum(sum(row) for row in grid) / (rows * columns)
    out = []
    if total < 0.12:
        return out
    half_r, half_c = rows // 2, columns // 2
    names = {(0, 0): "upper-left", (0, 1): "upper-right", (1, 0): "lower-left", (1, 1): "lower-right"}
    for (qr, qc), name in names.items():
        cells = [grid[r][c] for r in range(qr * half_r, (qr + 1) * half_r) for c in range(qc * half_c, (qc + 1) * half_c)]
        share = sum(cells) / max(len(cells), 1)
        if share < 0.06:
            rect = [x0 + qc * half_c * cell, y0 + qr * half_r * cell, x0 + (qc + 1) * half_c * cell, y0 + (qr + 1) * half_r * cell]
            out.append({"kind": "UNUSED", "severity": "note", "hard": False, "rect": rect, "message": f"the {name} quadrant of the content area is {100 * (1 - share):.0f}% empty"})
    empty_bottom = next((i for i, row in enumerate(reversed(grid)) if any(row)), rows)
    if empty_bottom * cell > 0.22 * (y1 - y0):
        out.append({"kind": "UNUSED", "severity": "note", "hard": False, "rect": [x0, y1 - empty_bottom * cell, x1, y1],
                    "message": f"the figure stops at y={y1 - empty_bottom * cell:.0f}; the content area runs to y={y1:.0f} ({empty_bottom * cell:.0f} px unused at the foot)"})
    empty_right = next((i for i in range(columns) if any(row[columns - 1 - i] for row in grid)), columns)
    if empty_right * cell > 0.22 * (x1 - x0):
        out.append({"kind": "UNUSED", "severity": "note", "hard": False, "rect": [x1 - empty_right * cell, y0, x1, y1],
                    "message": f"the figure stops at x={x1 - empty_right * cell:.0f}; the content area runs to x={x1:.0f} ({empty_right * cell:.0f} px unused on the right)"})
    return out


NATIVE_PARITY_HINT = ("the exporter will refuse this native table: every `<text>` inside the table group must equal, as one string, a cell's text in the "
                      "JSON (a cell whose text runs over several lines ends each line with a space before the next `<tspan>`, or lists the lines as that "
                      "cell's `paragraphs`; a heading plus a paragraph in one cell are both `paragraphs`), and each cell's alignment, weight and colour must "
                      "be in the JSON as drawn (header cells carry `\"align\"`). Fix the JSON or the drawn text, then run stamp_native_fallbacks.py --write")


def native_parity_issues(svg: Path) -> list[dict]:
    """The exporter's own gate for native tables and charts (the check behind `--native-charts-and-tables`), run while the page is
    drawn instead of at export: a mismatch between the drawn fallback and the JSON otherwise surfaces only as a repair after the deck."""
    try:
        if "data-pptx-replace-with=" not in svg.read_text(encoding="utf-8", errors="replace"):
            return []
        from svg_to_pptx.pptx_package.cli import _native_object_projection_findings
        findings = _native_object_projection_findings([svg])
    except Exception:  # noqa: BLE001 - the exporter still checks at the end; never block a render on the checker itself
        return []
    return [{"kind": "NATIVE", "severity": "blocker", "hard": True, "rect": [0, 0, 0, 0],
             "message": f"{marker}: {finding}"[:500] + (" - " + NATIVE_PARITY_HINT if number == 0 else "")}
            for number, (_, marker, finding) in enumerate(findings)]


def start_contract(svg: Path) -> dict:
    """Start the skill's own checker on this one file in the background (it takes seconds, mostly imports): the caller measures
    the page in the browser meanwhile and collects the verdict with finish_contract."""
    scratch = tempfile.mkdtemp(prefix="lint-")
    report = Path(scratch) / "report.json"
    env = {**os.environ, "PYTHONUTF8": "1"}
    proc = subprocess.Popen([sys.executable, str(SCRIPTS / "svg_quality_checker.py"), str(svg), "--canonical-authoring", "--json", "--json-output", str(report)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    native = None
    try:  # a page with a native table or chart also gets the exporter's own parity gate, in its own process alongside
        if "data-pptx-replace-with=" in svg.read_text(encoding="utf-8", errors="replace"):
            native = subprocess.Popen([sys.executable, str(SCRIPTS / "native_parity.py"), str(svg)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                      text=True, encoding="utf-8", errors="replace", env=env)
    except OSError:
        native = None
    return {"svg": svg, "proc": proc, "scratch": scratch, "report": report, "native": native}


def _native_findings(native) -> list[dict]:
    if native is None:
        return []
    try:
        out, _ = native.communicate(timeout=300)
        items = json.loads(out.strip() or "[]")
    except Exception:  # noqa: BLE001 - the exporter still checks at the end; never block a render on the checker itself
        native.kill()
        return []
    return [{"kind": "NATIVE", "severity": "blocker", "hard": True, "rect": [0, 0, 0, 0],
             "message": f"{item.get('marker')}: {item.get('finding')}"[:500] + (" - " + NATIVE_PARITY_HINT if number == 0 else "")}
            for number, item in enumerate(items)]


def finish_contract(handle: dict) -> list[dict]:
    import shutil
    svg = handle["svg"]
    native = _native_findings(handle.get("native"))
    try:
        try:
            handle["proc"].wait(timeout=300)
        except subprocess.TimeoutExpired:
            handle["proc"].kill()
            return native
        if not handle["report"].is_file():
            return native
        data = json.loads(handle["report"].read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(handle["scratch"], ignore_errors=True)
    issues = ((data.get("categories") or {}).get("blocking") or {}).get("issues") or []
    # only what is wrong with this file: the roster of the whole deck is incomplete while pages are still being authored
    issues = [issue for issue in issues if Path(str(issue.get("file") or "")).stem == svg.stem and "Outline roster" not in str(issue.get("message") or "")]
    def hint(message: str) -> str:  # the fix every author needed on its first render (53 of 59 pages, 24 Sep 2026)
        if 'id="chrome"' in message and "overlap" in message:
            return message + ' - the chrome group needs data-pptx-role="chrome" (keep it on `<g id="chrome">`); that exempts it from the overlap check'
        return message
    return [{"kind": "CONTRACT", "severity": "blocker", "hard": True, "rect": [0, 0, 0, 0], "message": hint(str(issue.get("message") or "")[:600])} for issue in issues] + native


def folio_issues(geometry: dict, stem: str) -> list[dict]:
    """The page number printed in the footer must be this page's number (taken from the file stem, `08_...` -> 8). A lone one- or
    two-digit text in the bottom-right corner is the folio. Wrong folios shipped in four decks (kirkland1, both self-documentation
    runs) and a whole-deck review missed one; this is arithmetic, not judgement."""
    match = re.match(r"(\d{1,2})_", stem)
    if not match:
        return []
    width, height = geometry.get("canvas") or (1280, 720)
    folios = []
    for text in geometry.get("texts") or []:
        value = (text.get("text") or "").strip()
        if not re.fullmatch(r"\d{1,2}", value):
            continue
        x0, y0, x1, y1 = text["parts"][0]["rect"]
        if x0 > width * 0.72 and y0 > height * 0.86:
            folios.append((value, [x0, y0, x1, y1]))
    expected = str(int(match.group(1)))
    if not folios or any(value == expected for value, _ in folios):
        return []
    value, rect = folios[0]
    return [{"kind": "FOLIO", "severity": "blocker", "hard": True, "rect": rect,
             "message": f"the page number in the footer reads {value}, but this is page {expected} (from the file name): set the folio to {expected}"}]


def stop_contract(handle: dict) -> None:
    """Abandon a started check (the render failed first): stop both background processes and leave nothing behind."""
    import shutil
    for key in ("proc", "native"):
        if handle.get(key) is not None:
            handle[key].kill()
    shutil.rmtree(handle["scratch"], ignore_errors=True)


def contract_issues(svg: Path) -> list[dict]:
    """The skill's own checker on this one file: the verdict the deck's final gate would reach."""
    return finish_contract(start_contract(svg))


def _content_area(project: Path | None):
    spec = project / "design_spec.md" if project else None
    if spec and spec.is_file():
        match = re.search(r"Content Area\s*\|\s*x\s*=\s*([\d.]+)\s*\.\.\s*([\d.]+)\s*,\s*y\s*=\s*([\d.]+)\s*\.\.\s*([\d.]+)", spec.read_text(encoding="utf-8"))
        if match:
            x0, x1, y0, y1 = (float(match.group(i)) for i in (1, 2, 3, 4))
            return (x0, y0, x1, y1)
    return None


def page_context(project: Path | None, stem: str, geometry: dict | None = None) -> dict:
    """Floors, the layout's title size and whether the page is sparse by design (type_floor.py), for analyse()."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import type_floor
    return type_floor.page_context(project, stem, (geometry or {}).get("pageRole"))


MEASURED_PAGE: list = [None]  # the open browser page of the file measure() last yielded


def crop_findings(findings: list[dict], out_dir: Path, stem: str, canvas=(1280, 720), pad: float = 44.0, limit: int = 8) -> None:
    """A zoomed picture of each soft finding, for the reviewer to rule on. Adds `crop` to the finding."""
    page = MEASURED_PAGE[0]
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(f"{stem}_item*.png"):
        old.unlink()
    number = 0
    for finding in findings:
        rect = finding["rect"]
        certain = finding.get("hard") and finding["kind"] not in CROPPED_HARD
        if finding["severity"] != "blocker" or certain or rect[2] - rect[0] < 1 or number >= limit or page is None:
            continue
        number += 1
        x, y = max(0.0, rect[0] - pad), max(0.0, rect[1] - pad)
        w, h = min(canvas[0], rect[2] + pad) - x, min(canvas[1], rect[3] + pad) - y
        if finding["kind"] not in FILL_KINDS:  # a band or an underfilled page is judged whole; anything else around its start
            w, h = min(w, 460.0), min(h, 300.0)  # a long line is shown around its start; the message names the rest
        target = out_dir / f"{stem}_item{number}.png"
        page.screenshot(path=str(target), type="png", clip={"x": x, "y": y, "width": w, "height": h})
        finding["crop"], finding["item"] = str(target), number


def measure(svg_files: list[Path], browser=None):
    """Yield (path, geometry, png_bytes) for each file, in one browser - the caller's, when it lends one."""
    if browser is not None:
        yield from _measure_in(browser, svg_files)
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("PPT_MASTER_BROWSER_CHANNEL") or None)
        try:
            yield from _measure_in(browser, svg_files)
        finally:
            browser.close()


def _measure_in(browser, svg_files: list[Path]):
    context = browser.new_context(device_scale_factor=3)  # crops of a finding are read by a reviewer: sharp at 3x
    try:
        page = context.new_page()
        for svg in svg_files:
            text = svg.read_text(encoding="utf-8")
            text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
            box = re.search(r'viewBox="\s*[\d.-]+[ ,]+[\d.-]+[ ,]+([\d.]+)[ ,]+([\d.]+)', text)
            width, height = (int(float(box.group(1))), int(float(box.group(2)))) if box else (1280, 720)
            page.set_viewport_size({"width": width, "height": height})
            page.set_content("<!DOCTYPE html><html><head><style>html,body{margin:0;padding:0;background:#FFFFFF;overflow:hidden}"
                             f"svg{{display:block;width:{width}px;height:{height}px}}</style></head><body>{text}</body></html>", wait_until="load")
            page.wait_for_timeout(60)
            MEASURED_PAGE[0] = page
            yield svg, page.evaluate(JS_EXTRACT), page.screenshot(type="png", full_page=False)
    finally:
        MEASURED_PAGE[0] = None
        context.close()


def overlay(png_bytes: bytes, findings: list[dict], out: Path) -> Path:
    import io
    from PIL import Image, ImageDraw
    image = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    scale = image.width / 1280.0 if image.width > 1400 else 1.0
    if scale != 1.0:
        image = image.resize((int(image.width / scale), int(image.height / scale)), Image.LANCZOS)
    draw = ImageDraw.Draw(image)
    colours = {"blocker": (220, 0, 0), "waived": (150, 0, 200), "note": (230, 140, 0)}
    for number, finding in enumerate(findings, start=1):
        rect = finding["rect"]
        if rect[2] - rect[0] < 1:
            continue
        colour = colours.get(finding["severity"], (230, 140, 0))
        draw.rectangle([rect[0] - 3, rect[1] - 3, rect[2] + 3, rect[3] + 3], outline=colour, width=2)
        draw.text((rect[0] - 2, max(0, rect[1] - 14)), str(number), fill=colour)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out)
    return out


def lint_page(project: Path, stem: str, *, contract: bool = True, write_overlay: bool = True, browser=None, contract_handle: dict | None = None) -> dict:
    """`browser`: a browser the caller already holds. `contract_handle`: the contract check the caller started (start_contract) while
    it rendered; otherwise it is started here, still alongside the measurement."""
    svg = project / "svg_output" / f"{stem}.svg"
    result = None
    if contract and contract_handle is None:
        contract_handle = start_contract(svg)
    try:
        for _, geometry, png in measure([svg], browser=browser):
            findings = analyse(geometry, png, _content_area(project), is_cover="cover" in stem.lower(), page=page_context(project, stem, geometry))
            findings.extend(folio_issues(geometry, stem))
            if contract_handle is not None:
                findings.extend(finish_contract(contract_handle))
                contract_handle = None
            crop_findings(findings, project / ".preview" / "lint", stem, tuple(geometry.get("canvas") or (1280, 720)))
            image = None
            if write_overlay and any(f["severity"] != "note" for f in findings):
                image = overlay(png, [f for f in findings if f["kind"] != "CONTRACT"], project / ".preview" / "lint" / f"{stem}.png")
            result = {"page": stem, "blockers": [f for f in findings if f["severity"] == "blocker"], "waived": [f for f in findings if f["severity"] == "waived"],
                      "notes": [f for f in findings if f["severity"] == "note"], "overlay": str(image) if image else None}
    finally:
        if contract_handle is not None:  # the measurement failed: stop the background check, leave nothing behind
            stop_contract(contract_handle)
    return result or {"page": stem, "blockers": [], "waived": [], "notes": [], "overlay": None}


def render_text(result: dict) -> str:
    hard = [f for f in result["blockers"] if f.get("hard")]
    lines = [f"LINT {result['page']}: {len(hard)} certain defect(s), {len(result['blockers']) - len(hard)} flagged for judgement, {len(result['notes'])} note(s)"]
    for label, key in (("BLOCKER", "blockers"), ("WAIVED", "waived"), ("note", "notes")):
        for number, finding in enumerate(result[key], start=1):
            rect = finding["rect"]
            where = f" at x={rect[0]:.0f}-{rect[2]:.0f}, y={rect[1]:.0f}-{rect[3]:.0f}" if rect[2] - rect[0] >= 1 else ""
            tag = ("CERTAIN" if finding.get("hard") else "FLAGGED") if key == "blockers" else label
            lines.append(f"  {tag} {finding['kind']}{where}: {finding['message']}")
    if not result["blockers"] and not result["waived"]:
        lines.append("  geometry is clean: no text on text, no line through text, no text off its shape, nothing off the canvas, contract check passed")
    elif result["blockers"]:
        lines.append("  CERTAIN items are measured facts: fix them; the reviewer is not asked while one stands. FLAGGED items are probably defects: fix those that are, "
                     "and leave one only when you have looked and it is intended - the reviewer will rule on each from a zoomed crop.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", nargs="?")
    parser.add_argument("page", nargs="?")
    parser.add_argument("--files", nargs="*", help="tuning: lint these SVG files in one browser, without a project or the contract check")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-overlay", action="store_true")
    parser.add_argument("--no-contract", action="store_true")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if args.files:
        for svg, geometry, png in measure([Path(f) for f in args.files]):
            findings = analyse(geometry, png, _content_area(svg.parent.parent), is_cover="cover" in svg.stem.lower(), page=page_context(svg.parent.parent, svg.stem, geometry))
            result = {"page": f"{svg.parent.parent.name}/{svg.stem}", "blockers": [f for f in findings if f["severity"] == "blocker"],
                      "waived": [f for f in findings if f["severity"] == "waived"], "notes": [f for f in findings if f["severity"] == "note"], "overlay": None}
            print(json.dumps(result) if args.json else render_text(result))
        return 0
    if not args.project or not args.page:
        parser.error("give <project> <page>, or --files")
    project = Path(args.project).resolve()
    stem = Path(args.page).stem
    if not (project / "svg_output" / f"{stem}.svg").is_file():
        raise SystemExit(f"no such page: {project / 'svg_output' / (stem + '.svg')}")
    result = lint_page(project, stem, contract=not args.no_contract, write_overlay=not args.no_overlay)
    print(json.dumps(result) if args.json else render_text(result))
    if result["overlay"]:
        print(f"IMAGE: {result['overlay']}")
    return 1 if result["blockers"] else 0


if __name__ == "__main__":
    sys.exit(main())
