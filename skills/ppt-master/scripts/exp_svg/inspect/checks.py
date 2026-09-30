#!/usr/bin/env python3
"""
PPT Master - exp_svg inspection: the checks

Turns the browser geometry of one SVG (svg_geometry.py), the inspection request and the
independent checklist into check records. Every record is `passed`, `failed`, `unverified`
(with the reason) or `waived` (by an explicit request entry, listed), and carries the element
references, measured and expected values, units and tolerance. Nothing here calls a model.

Checks (ids are prefixed per family):
    TF   type_floor   effective font size at final scale against the label / body floor
    FIT  text_fit     text inside the container it sits in; clip-path cuts; textLength squeeze
    OFF  off_canvas   content outside the 1280 x 720 canvas
    OVL  overlap      text on text, lines through text, shapes on text, text straddling a
                      shape edge, partial shape overlaps; declared containment facts
    CON  connectors   arrow heads bound to something, T-junctions onto directed connectors,
                      declared / checklist relationships joined endpoint to endpoint
    MRK  markers      arrowhead direction against the path end, fixed-angle markers,
                      marker-start pointing inwards
    TL   timeline     bars and milestones against the declared date scale; ruler ticks
    SEM  semantic     independent checklist items present, complete and in the right place;
                      legend swatches agree with their meaning
    RES  resources    images and other referenced files the browser failed to load
    UNS  unsupported  geometry this checker cannot measure (foreignObject, use, nested svg, textPath,
                      switch, filters, masks): always `unverified`, never passed

Usage:
    Imported by inspect_svg.py; not a command.

Dependencies:
    None (only uses standard library)
"""

from __future__ import annotations

import collections
import datetime as _dt
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from typing import Any, Optional

if __name__ == "__main__" and any(arg in {"-h", "--help", "help"} for arg in sys.argv[1:]):
    print(__doc__)
    raise SystemExit(0)

import geom as G  # noqa: E402  (sibling module; the caller puts this folder on sys.path)

SVG_NS = "{http://www.w3.org/2000/svg}"
SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2, "info": 3}
PREFIX = {"type_floor": "TF", "text_fit": "FIT", "off_canvas": "OFF", "overlap": "OVL", "connectors": "CON",
          "markers": "MRK", "timeline": "TL", "semantic": "SEM", "resources": "RES", "unsupported": "UNS"}
ALL_CHECKS = tuple(PREFIX)
SYMBOLS = set("▲▼◆◇●○■□★♦◀▶►◄⬤⬥⬦△▽◊")
DEFAULT_ROLE_MAP = {
    # a role absent from the request's type_floors_px falls back to "label" (e.g. furniture without its own floor)
    "furniture": ["furniture", "eyebrow", "source", "footnote", "folio"],
    "label": ["label", "caption", "axis", "tick", "tick-label", "annotation", "legend", "legend-label", "secondary",
              "marker-label", "milestone-label", "gate-label", "window-label", "bar-label", "node-label", "edge-label",
              "lane", "lane-label"],
    "body": ["body", "title", "heading", "subtitle", "paragraph", "bullet"],
}
UNMEASURED = [
    {"property": "glyph ink", "why": "text boxes are the browser's glyph cells (ascent to descent); ink is approximated by shrinking the cell 20% at the top and 10% at the bottom for collision tests"},
    {"property": "stroke outline", "why": "shape boxes are fill geometry (getBBox); stroke width is recorded but joins, caps and miter extents are not added to bounds"},
    {"property": "filter effects", "why": "shadows, blurs and other filter regions are not measured; elements under a filter are listed"},
    {"property": "mask effects", "why": "mask luminance is not evaluated; masked elements are listed"},
    {"property": "clip-path shapes", "why": "clip regions are reduced to the bounding box of rect / circle / ellipse / polygon children; other clip geometry is unverified"},
    {"property": "marker geometry", "why": "marker direction is derived from polygon / straight-path vertices only; curved marker paths and marker-mid are unverified; marker boxes are not added to the connector box"},
    {"property": "foreignObject, use, nested svg, switch, textPath", "why": "their content is not measured; listed as unsupported"},
    {"property": "raster content", "why": "pixels inside <image> are not read: text drawn in an image or text over an image is not verified"},
    {"property": "colour contrast", "why": "contrast is not a check here; fill colours are reported as evidence only"},
    {"property": "semantic truth", "why": "a connector joining the right shapes, or a label beside the right bar, is geometric evidence; the words and meaning are matched to the checklist by tokens, not understood"},
]


# ---------------------------------------------------------------------------------------------
# text normalisation and matching
# ---------------------------------------------------------------------------------------------
_STOP = {"and", "the", "of", "a", "an", "to", "for", "in", "on", "by", "with", "at", "is", "are", "or"}
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")
_QUOTES = dict.fromkeys(map(ord, "‘’‛′"), "'")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").casefold().translate(_DASHES).translate(_QUOTES)
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[^\W_]+(?:'[^\W_]+)?", norm(text)) if t not in _STOP]


def match_score(alt: str, unit_text: str) -> tuple[float, str, list[str]]:
    """Score of one expected phrase against one text unit: (score, kind, missing tokens)."""
    na, nu = norm(alt), norm(unit_text)
    if na and na in nu:
        return 1.0, "exact", []
    want = tokens(alt)
    if not want:
        return 0.0, "none", []
    have = collections.Counter(tokens(unit_text))
    missing = []
    hit = 0
    for tok in want:
        if have[tok] > 0:
            have[tok] -= 1
            hit += 1
        else:
            missing.append(tok)
    return hit / len(want), "tokens", missing


# ---------------------------------------------------------------------------------------------
# SVG definitions the browser does not lay out: markers and clip paths
# ---------------------------------------------------------------------------------------------
def _num(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(re.sub(r"[a-z%]+$", "", (value or "").strip()))
    except ValueError:
        return default


def _path_vertices(d: str) -> Optional[list[tuple[float, float]]]:
    """Vertices of a path made only of M/L/H/V/Z (absolute or relative); None for curves."""
    toks = re.findall(r"[MmLlHhVvZzCcSsQqTtAa]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d or "")
    pts: list[tuple[float, float]] = []
    x = y = 0.0
    cmd = None
    i = 0
    while i < len(toks):
        t = toks[i]
        if re.fullmatch(r"[A-Za-z]", t):
            cmd = t
            i += 1
            if cmd in "Zz":
                continue
            if cmd not in "MmLlHhVv":
                return None
            continue
        if cmd is None:
            return None
        try:
            if cmd in "MmLl":
                nx, ny = float(toks[i]), float(toks[i + 1])
                i += 2
                x, y = (x + nx, y + ny) if cmd.islower() else (nx, ny)
                if cmd == "m":
                    cmd = "l"
                elif cmd == "M":
                    cmd = "L"
            elif cmd in "Hh":
                v = float(toks[i])
                i += 1
                x = x + v if cmd == "h" else v
            elif cmd in "Vv":
                v = float(toks[i])
                i += 1
                y = y + v if cmd == "v" else v
        except (IndexError, ValueError):
            return None
        pts.append((x, y))
    return pts


def parse_defs(svg_bytes: bytes) -> dict:
    """Markers and clip paths by id, from the SVG source."""
    root = ET.fromstring(svg_bytes)
    markers, clips = {}, {}
    for el in root.iter():
        tag = el.tag.replace(SVG_NS, "")
        if tag == "marker" and el.get("id"):
            pts: list[tuple[float, float]] = []
            curved = False
            for child in el.iter():
                ctag = child.tag.replace(SVG_NS, "")
                if ctag in ("polygon", "polyline"):
                    nums = [float(v) for v in re.findall(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?", child.get("points") or "")]
                    pts += list(zip(nums[0::2], nums[1::2]))
                elif ctag == "path":
                    v = _path_vertices(child.get("d") or "")
                    if v is None:
                        curved = True
                    else:
                        pts += v
                elif ctag == "line":
                    pts += [(_num(child.get("x1")), _num(child.get("y1"))), (_num(child.get("x2")), _num(child.get("y2")))]
                elif ctag in ("circle", "ellipse"):
                    curved = True
                elif ctag == "rect":
                    x, y, w, h = (_num(child.get(k)) for k in ("x", "y", "width", "height"))
                    pts += [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
            vb = [_num(v) for v in re.split(r"[\s,]+", (el.get("viewBox") or "").strip()) if v] or None
            markers[el.get("id")] = {
                "orient": (el.get("orient") or "0").strip(), "refX": _num(el.get("refX")), "refY": _num(el.get("refY")),
                "markerWidth": _num(el.get("markerWidth"), 3.0), "markerHeight": _num(el.get("markerHeight"), 3.0),
                "markerUnits": el.get("markerUnits") or "strokeWidth", "viewBox": vb if vb and len(vb) == 4 else None,
                "points": pts, "curved": curved,
            }
        elif tag == "clipPath" and el.get("id"):
            rects, unsupported = [], []
            for child in el:
                ctag = child.tag.replace(SVG_NS, "")
                if child.get("transform"):
                    unsupported.append(ctag + "[transform]")
                    continue
                if ctag == "rect":
                    x, y, w, h = (_num(child.get(k)) for k in ("x", "y", "width", "height"))
                    rects.append([x, y, x + w, y + h])
                elif ctag == "circle":
                    cx, cy, r = _num(child.get("cx")), _num(child.get("cy")), _num(child.get("r"))
                    rects.append([cx - r, cy - r, cx + r, cy + r])
                elif ctag == "ellipse":
                    cx, cy, rx, ry = (_num(child.get(k)) for k in ("cx", "cy", "rx", "ry"))
                    rects.append([cx - rx, cy - ry, cx + rx, cy + ry])
                elif ctag == "polygon":
                    nums = [float(v) for v in re.findall(r"-?\d*\.?\d+", child.get("points") or "")]
                    if nums:
                        rects.append([min(nums[0::2]), min(nums[1::2]), max(nums[0::2]), max(nums[1::2])])
                else:
                    unsupported.append(ctag)
            clips[el.get("id")] = {"units": el.get("clipPathUnits") or "userSpaceOnUse", "rects": rects,
                                   "unsupported": unsupported, "shape_is_rect_only": all(c.tag.endswith("rect") for c in el)}
    return {"markers": markers, "clips": clips}


def _apply(m: list[float], x: float, y: float, vb: dict, k: tuple[float, float]) -> tuple[float, float]:
    return ((m[0] * x + m[2] * y + m[4] - vb["x"]) * k[0], (m[1] * x + m[3] * y + m[5] - vb["y"]) * k[1])


# ---------------------------------------------------------------------------------------------
# the measured page
# ---------------------------------------------------------------------------------------------
def _join_parts(parts: list) -> str:
    """Text of one visual line: runs touching each other are glued, runs with a gap get a space."""
    out = ""
    prev = None
    for rect, run in parts:
        piece = run["text"]
        if prev is not None:
            gap = rect[0] - prev[0][2]
            if gap > 0.15 * max(run["font_px"], 1.0) or prev[1].get("ws_after") or run.get("ws_before"):
                out = out.rstrip() + " " + piece.lstrip()
            else:
                out += piece
        else:
            out = piece
        prev = (rect, run)
    return re.sub(r"\s+", " ", out).strip()


def _self_dated(text: str, item: dict) -> bool:
    """True when the label names its own week(s), e.g. 'W21 Ask Meridian evaluation' or '... (wk 2-8)': the date in the
    text ties it to its bar or marker, so a nearer rival does not make it ambiguous."""
    t = norm(text)
    weeks = [item.get("date")] if "date" in item else [item.get("start"), item.get("end")]
    weeks = [w for w in weeks if isinstance(w, (int, float))]
    if not weeks:
        return False
    for w in weeks:
        n = int(w) if float(w).is_integer() else w
        if not re.search(rf"(?<![\d.])(w|wk|week)\s?{n}(?![\d.])", t) and not re.search(rf"(?<![\d.]){n}\s?[-–]\s?\d|\d\s?[-–]\s?{n}(?![\d.])", t):
            return False
    return True


def _direction_at(points: list, s: float):
    """Unit direction of a polyline at arc length s."""
    acc = 0.0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if seg > 1e-9 and acc + seg >= s - 1e-9:
            return ((b[0] - a[0]) / seg, (b[1] - a[1]) / seg)
        acc += seg
    return None


ROW_PENALTY = {"row": 0.0, "stacked": 6.0, "column": 6.0, "other": 12.0}


def _row_key(label: list[float], bar: list[float]) -> float:
    """How strongly a reader pairs a label with a bar (lower is stronger): distance, plus nothing on the same row,
    a small penalty when the label is centred just above or below the bar, a larger one otherwise."""
    lh, bh = G.height(label), G.height(bar)
    d = G.dist_rect_rect(label, bar)
    if abs(G.center(label)[1] - G.center(bar)[1]) <= 0.75 * (lh + bh) / 2:
        return d + ROW_PENALTY["row"]
    if abs(G.center(label)[0] - G.center(bar)[0]) <= 0.25 * G.width(label) and d <= 0.8 * lh:
        return d + ROW_PENALTY["stacked"]
    return d + ROW_PENALTY["other"]


def _col_key(label: list[float], marker: list[float]) -> float:
    """How strongly a reader pairs a label with a milestone marker or rule (lower is stronger): a label beside
    the marker on its row first; a label with the marker inside its span next, the one nearest its centre;
    otherwise distance plus a penalty."""
    d = G.dist_rect_rect(label, marker)
    lh = G.height(label)
    if G.height(marker) <= 3 * lh and abs(G.center(label)[1] - G.center(marker)[1]) <= 0.75 * (lh + G.height(marker)) / 2:
        return d + ROW_PENALTY["row"]
    mx = G.center(marker)[0]
    if label[0] - 2 <= mx <= label[2] + 2:
        return d + ROW_PENALTY["column"] + 0.25 * abs(G.center(label)[0] - mx)
    return d + ROW_PENALTY["other"]


def _ink(rect: list[float]) -> list[float]:
    h = G.height(rect)
    return [rect[0], rect[1] + 0.2 * h, rect[2], rect[3] - 0.1 * h]


class Model:
    """Visible texts (split into lines), shapes, connectors and groups of one measured SVG."""

    def __init__(self, geometry: dict, defs: dict):
        self.geometry = geometry
        self.defs = defs
        self.W, self.H = geometry["canvas"]
        self.canvas_rect = [0.0, 0.0, float(self.W), float(self.H)]
        self.canvas_area = float(self.W) * float(self.H)
        self.vb = geometry["viewBox"]
        self.k = tuple(geometry["scale"])
        self.texts: list[dict] = []
        self.lines: list[dict] = []
        self.hidden: list[str] = []
        for t in geometry["texts"]:
            runs = [r for r in t["runs"] if r.get("fill") not in (None, "none") and r.get("fill_opacity", 1) > 0.05
                    or (r.get("stroke") not in (None, "none"))]
            if t["opacity"] < 0.05 or not runs:
                self.hidden.append(t["ref"])
                continue
            t = dict(t)
            t["visible_runs"] = runs
            t["lines"] = self._lines_of(t, runs)
            t["rect"] = G.union(line["rect"] for line in t["lines"])
            t["raw_text"] = t["text"]
            t["text"] = " ".join(line["text"] for line in t["lines"])  # lines joined with a space (textContent glues tspans)
            t["min_px"] = min(r["font_px"] for r in runs)
            self.texts.append(t)
            self.lines.extend(t["lines"])
        self.shapes = [s for s in geometry["shapes"] if s["opacity"] >= 0.05 and (s["fill"] or s["stroke"] or s["tag"] in ("image", "use", "foreignObject"))]
        for s in self.shapes:
            s["rect"] = s["bbox"]
        self.closed = [s for s in self.shapes if s["closed"] and (s["fill"] or s["stroke"]) and G.area(s["rect"]) >= 20]
        self.connectors = []
        for s in self.shapes:
            pts = s.get("points")
            if not pts or len(pts) < 2:
                continue
            length = G.polyline_length(pts)
            if length < 6 and not (any(s["markers"].values()) and length > 0.5):
                continue  # a stub shorter than 6 px counts only when it carries an arrowhead
            s["length"] = length
            self.connectors.append(s)
        self.groups = [g for g in geometry["groups"] if g["opacity"] >= 0.05]
        for g in self.groups:
            g["rect"] = g["bbox"]
        self.by_ref: dict[str, dict] = {}
        for coll, kind in ((self.groups, "group"), (self.shapes, "shape"), (self.texts, "text")):
            for item in coll:
                item.setdefault("kind", kind)
                self.by_ref[item["ref"]] = item
                if item.get("id"):
                    self.by_ref[item["id"]] = item
                self.by_ref[item["path"]] = item

    @staticmethod
    def _lines_of(t: dict, runs: list[dict]) -> list[dict]:
        pieces = []
        for run in runs:
            for rect in run["rects"]:
                pieces.append((rect, run))
        pieces.sort(key=lambda p: ((p[0][1] + p[0][3]) / 2, p[0][0]))
        lines: list[list] = []
        for rect, run in pieces:
            cy, h = (rect[1] + rect[3]) / 2, rect[3] - rect[1]
            for line in lines:
                lr = line[0]
                if abs((lr[1] + lr[3]) / 2 - cy) <= 0.35 * min(h, lr[3] - lr[1]):
                    line[0] = G.union([lr, rect])
                    line[1].append((rect, run))
                    break
            else:
                lines.append([list(rect), [(rect, run)]])
        out = []
        for i, (rect, parts) in enumerate(lines):
            parts.sort(key=lambda p: p[0][0])
            out.append({"ref": t["ref"] if len(lines) == 1 else f"{t['ref']}:line{i + 1}", "text_ref": t["ref"],
                        "text": _join_parts(parts), "rect": rect, "ink": _ink(rect),
                        "font_px": min(p[1]["font_px"] for p in parts), "fill": parts[0][1]["fill"],
                        "order": t["order"], "ancestors": t["ancestors"], "rotated": t["rotated"],
                        "runs": [p[1] for p in parts]})
        return out

    def rect_of(self, ref: str) -> Optional[list[float]]:
        item = self.by_ref.get(ref)
        if item:
            return item["rect"]
        els = self.resolve(ref)
        return G.union(e["rect"] for e in els) if els else None

    def resolve(self, ref: str) -> list[dict]:
        """Elements named by an id / ref / path, or every element carrying data-content-id=ref."""
        if ref in self.by_ref:
            return [self.by_ref[ref]]
        return [e for coll in (self.texts, self.shapes, self.groups) for e in coll if (e.get("data") or {}).get("data-content-id") == ref]

    def is_background(self, s: dict) -> bool:
        return G.area(s["rect"]) >= 0.85 * self.canvas_area

    def is_band(self, s: dict) -> bool:
        return G.width(s["rect"]) >= 0.6 * self.W or G.height(s["rect"]) >= 0.6 * self.H

    def container_of(self, rect: list[float], exclude: tuple = ()) -> Optional[dict]:
        """Smallest closed painted shape containing the rect's centre and at least half its area."""
        c = G.center(rect)
        best = None
        for s in self.closed:
            if s["ref"] in exclude or self.is_background(s) or s["tag"] in ("image", "use", "foreignObject"):
                continue
            if not G.contains_point(s["rect"], c):
                continue
            if G.area(s["rect"]) < 0.5 * G.area(rect):
                continue
            if best is None or G.area(s["rect"]) < G.area(best["rect"]):
                best = s
        return best

    def related(self, a: dict, b: dict) -> bool:
        """True when one element is an ancestor group of the other or they are the same text."""
        ra, rb = a.get("text_ref", a["ref"]), b.get("text_ref", b["ref"])
        if ra == rb:
            return True
        ia, ib = a.get("id"), b.get("id")
        return (ia is not None and ia in b.get("ancestors", ())) or (ib is not None and ib in a.get("ancestors", ()))


# ---------------------------------------------------------------------------------------------
# report collection
# ---------------------------------------------------------------------------------------------
class Records:
    def __init__(self):
        self.items: list[dict] = []
        self.counter: collections.Counter = collections.Counter()

    def add(self, check: str, status: str, *, targets: list[str], message: str, severity: Optional[str] = None,
            certainty: str = "measured", **evidence: Any) -> dict:
        self.counter[check] += 1
        rec = {"check_id": f"{PREFIX[check]}{self.counter[check]}", "check": check, "status": status,
               "severity": severity if status == "failed" else None, "certainty": certainty,
               "targets": [t for t in targets if t], "message": message}
        rec.update({k: _round(v) for k, v in evidence.items() if v is not None})
        self.items.append(rec)
        return rec


def _round(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 2)
    if isinstance(v, (list, tuple)):
        return [_round(x) for x in v]
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


# ---------------------------------------------------------------------------------------------
# the inspection
# ---------------------------------------------------------------------------------------------
class Inspector:
    def __init__(self, model: Model, request: dict, checklist: Optional[dict]):
        self.m = model
        self.req = request
        self.cl = checklist or {"items": []}
        self.rec = Records()
        self.floors = {"label": float(request.get("type_floors_px", {}).get("label", 13.333)),
                       "body": float(request.get("type_floors_px", {}).get("body", 16.0))}
        # further named roles (e.g. "furniture" for eyebrow/source text on a timeline slide, decision D015)
        self.floors.update({k: float(v) for k, v in (request.get("type_floors_px") or {}).items()
                            if k not in self.floors and isinstance(v, (int, float))})
        self.lowest_floor = min(self.floors.values())
        self.checks = tuple(request.get("checks") or ALL_CHECKS)
        self.items = {it["id"]: it for it in self.cl.get("items", [])}
        self.mapping = request.get("mapping") or {}
        self.threshold = float(self.cl.get("match_threshold", request.get("match_threshold", 0.8)))
        self.item_units: dict[str, list[dict]] = {}   # matched text units per item (best first)
        self.item_anchor: dict[str, dict] = {}        # resolved geometry per item: {"rect", "ref", "how"}
        self.item_alternates: dict[str, list] = {}    # further drawn instances of a node item (any-of for relationships)
        self.text_roles: dict[str, tuple[str, str]] = {}
        self.item_presence: dict[str, str] = {}      # present / partial / missing per checklist item with text
        self.units = self._units()
        self.scale = self._scale()

    # ---------------- text units ----------------
    def _units(self) -> list[dict]:
        units = []
        for t in self.m.texts:
            units.append({"ref": t["ref"], "refs": [t["ref"]], "text": t["text"], "rect": t["rect"], "font_px": t["min_px"], "kind": "element"})
            if len(t["lines"]) > 1:
                for line in t["lines"]:
                    units.append({"ref": line["ref"], "refs": [t["ref"]], "text": line["text"], "rect": line["rect"], "font_px": line["font_px"], "kind": "line"})
        # blocks: vertically stacked text elements that read as one label
        texts = sorted(self.m.texts, key=lambda t: (t["rect"][1], t["rect"][0]))
        parent = list(range(len(texts)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        conts = [self.m.container_of(t["rect"]) for t in texts]
        for i, a in enumerate(texts):
            for j in range(i + 1, len(texts)):
                b = texts[j]
                gap = b["rect"][1] - a["rect"][3]
                if gap > 0.8 * max(a["min_px"], b["min_px"]):
                    if b["rect"][1] > a["rect"][3] + 3 * max(a["min_px"], b["min_px"]):
                        break
                    continue
                if gap < -0.3 * G.height(a["rect"]):
                    continue
                ca, cb = conts[i], conts[j]
                if (ca and ca["ref"]) != (cb and cb["ref"]):
                    continue
                left = abs(a["rect"][0] - b["rect"][0]) <= 2.5
                mid = abs(G.center(a["rect"])[0] - G.center(b["rect"])[0]) <= 2.5
                right = abs(a["rect"][2] - b["rect"][2]) <= 2.5
                if left or mid or right:
                    parent[find(j)] = find(i)
        groups = collections.defaultdict(list)
        for i, t in enumerate(texts):
            groups[find(i)].append(t)
        for members in groups.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda t: t["rect"][1])
            units.append({"ref": "+".join(t["ref"] for t in members), "refs": [t["ref"] for t in members],
                          "text": " ".join(t["text"] for t in members), "rect": G.union(t["rect"] for t in members),
                          "font_px": min(t["min_px"] for t in members), "kind": "block"})
        return units

    def find_text(self, item: dict, which: str = "text") -> list[dict]:
        """Candidate units for an item's text (or meaning), best first, with scores."""
        main = item.get(which)
        if not main:
            return []
        alts = [main] + list(item.get("alt" if which == "text" else f"{which}_alt", []) or [])
        must = [m for m in (item.get("must_include" if which == "text" else f"{which}_must_include") or []) if m]
        found = []
        for unit in self.units:
            best = None
            for rank, alt in enumerate(alts):
                score, kind, missing = match_score(alt, unit["text"])
                nums = [t for t in tokens(alt) if any(ch.isdigit() for ch in t)]
                if nums and kind != "exact":
                    have = set(tokens(unit["text"]))
                    if any(n not in have for n in nums):
                        score = min(score, self.threshold - 0.01)
                        kind = "tokens-number-mismatch"
                via = 0 if rank == 0 else 1
                if best is None or (score, -via) > (best[0], -best[4]):
                    best = (score, kind, missing, alt, via)
            if must and (best is None or best[0] < self.threshold):
                have_text = " " + " ".join(tokens(unit["text"])) + " "
                absent = [m for m in must if " " + " ".join(tokens(m)) + " " not in have_text]
                if not absent:
                    best = (1.0, "must_include", [], " + ".join(must), 2)
                elif best is None or best[0] < 0.34:
                    part = 1 - len(absent) / len(must)
                    if part >= 0.34:
                        best = (part, "must_include-partial", absent, " + ".join(must), 2)
            if best and best[0] >= 0.34:
                found.append({**unit, "score": best[0], "match": best[1], "missing": best[2], "alt": best[3], "via": best[4]})
        # the item's own wording first, then accepted alternates, then keyword-only acceptance; shorter units first
        found.sort(key=lambda u: (-u["score"], u["via"], len(u["text"])))
        return found

    def _mapped(self, item_id: str, want: str) -> Optional[dict]:
        """The creator's mapping for one checklist item and role (label, bar, marker, node, connector), resolved
        to geometry. A value may be an element id or a data-content-id shared by several elements (a gate rule
        broken into segments is one anchor)."""
        ref = (self.mapping.get(item_id) or {}).get(want)
        if not ref:
            return None
        els = self.m.resolve(ref)
        if want == "label":
            els = [e for e in els if e["kind"] == "text"]
        elif want in ("bar", "marker", "node"):
            els = [e for e in els if e["kind"] in ("shape", "group")]
        if not els:
            return None
        return {"ref": ref, "rect": G.union(e["rect"] for e in els), "refs": [e["ref"] for e in els], "shape": "mapped"}

    # ---------------- scale ----------------
    def _scale(self) -> Optional[dict]:
        tl = self.req.get("timeline") or {}
        sc = tl.get("scale")
        if not sc:
            return None
        sc = dict(sc)
        unit = sc.get("unit", "week")
        origin = sc.get("origin", 1)
        if isinstance(origin, str):
            sc["_origin_date"] = _dt.date.fromisoformat(origin)
        if "px_per_unit" not in sc:
            end, end_x = sc.get("end"), sc.get("end_x")
            sc["px_per_unit"] = (end_x - sc["origin_x"]) / (self._units_of(end, sc) - self._units_of(origin, sc))
        tol_weeks = float(sc.get("tolerance_weeks", 0.5))
        sc["tolerance_units"] = float(sc.get("tolerance_units", tol_weeks * (7.0 if unit == "day" else 1.0)))
        sc["tolerance_px"] = sc["tolerance_units"] * sc["px_per_unit"]
        sc.setdefault("end_convention", "inclusive")
        sc.setdefault("milestone_anchor", "end")
        sc["unit"] = unit
        return sc

    @staticmethod
    def _units_of(value: Any, sc: dict) -> float:
        if isinstance(value, str):
            d0 = sc.get("_origin_date") or _dt.date.fromisoformat(sc["origin"])
            days = (_dt.date.fromisoformat(value) - d0).days
            return days if sc.get("unit", "week") == "day" else days / 7.0
        o = sc.get("origin", 1)
        return float(value) - (0.0 if isinstance(o, str) else float(o))

    def x_of(self, value: Any, edge: str) -> float:
        """x of a date: edge 'start' (beginning of the unit), 'end' (end of it) or 'center'."""
        sc = self.scale
        u = self._units_of(value, sc)
        if edge == "end":
            u += 1.0 if sc["end_convention"] == "inclusive" else 0.0
        elif edge == "center":
            u += 0.5
        return sc["origin_x"] + u * sc["px_per_unit"]

    # ---------------- run ----------------
    def run(self) -> list[dict]:
        if "semantic" in self.checks or "timeline" in self.checks:
            self.semantic_and_timeline()
        if "type_floor" in self.checks:
            self.type_floor()
        if "text_fit" in self.checks:
            self.text_fit()
        if "off_canvas" in self.checks:
            self.off_canvas()
        if "overlap" in self.checks:
            self.overlap()
        if "connectors" in self.checks:
            self.connectors()
        if "markers" in self.checks:
            self.markers()
        if "resources" in self.checks:
            self.resources()
        if "unsupported" in self.checks:
            self.unsupported()
        return self.rec.items

    # ---------------- UNS: what is not measured on this slide ----------------
    def unsupported(self) -> None:
        g = self.m.geometry
        seen = set()
        for u in g.get("unsupported", []):
            key = (u["kind"], u.get("ref"))
            if key in seen:
                continue
            seen.add(key)
            self.rec.add("unsupported", "unverified", targets=[u.get("ref")], reason=f"{u['kind']}: content not measured",
                         message=f"{u['kind']} {u.get('ref')}: its content is not measured (text size, fit, overlap unknown)")
        for coll in (g["texts"], g["shapes"]):
            for el in coll:
                for f in el.get("filters", []):
                    key = ("filter", f["on"])
                    if key not in seen:
                        seen.add(key)
                        self.rec.add("unsupported", "unverified", targets=[f["on"]], reason="filter: effect extent not measured",
                                     message=f"filter on {f['on']}: shadow/blur extent and legibility effects not measured")
                for f in el.get("masks", []):
                    key = ("mask", f["on"])
                    if key not in seen:
                        seen.add(key)
                        self.rec.add("unsupported", "unverified", targets=[f["on"]], reason="mask: visibility not evaluated",
                                     message=f"mask on {f['on']}: what the mask hides is not evaluated")

    # ---------------- RES: resources ----------------
    def resources(self) -> None:
        failed = (self.m.geometry.get("browser") or {}).get("failed_requests") or []
        for url in failed:
            self.rec.add("resources", "failed", severity="major", targets=[url], message="a referenced file failed to load: the slide shows nothing there")
        images = [s for s in self.m.shapes if s["tag"] == "image"]
        if not failed:
            self.rec.add("resources", "passed", targets=[s["ref"] for s in images][:10], message=f"all referenced files loaded ({len(images)} image elements)")

    # ---------------- TF: type floor ----------------
    def _role(self, t: dict) -> tuple[Optional[str], str]:
        roles = self.req.get("roles") or {}
        exempt = roles.get("exempt") or {}
        for key in (t["ref"], t.get("id"), *t.get("ancestors", [])):
            if key and key in exempt:
                return "exempt", f"request roles.exempt[{key}]: {exempt[key]}"
        ids = roles.get("ids") or {}
        for key in (t["ref"], t.get("id"), *t.get("ancestors", [])):
            if key and key in ids:
                return ids[key], f"request roles.ids[{key}]"
        for pattern, role in (roles.get("id_patterns") or {}).items():
            if t.get("id") and re.search(pattern, t["id"]):
                return role, f"request roles.id_patterns {pattern}"
        # the independent checklist outranks the author's own markup (an author must not choose its floor)
        if t["ref"] in self.text_roles:
            role, item = self.text_roles[t["ref"]]
            return self._floor_role(role), f"checklist item {item}"
        amap = roles.get("attribute_map") or DEFAULT_ROLE_MAP
        for attr in ("data-type-role", "data-text-role", "data-role"):
            v = (t.get("data") or {}).get(attr)
            if v:
                if v.lower() in self.floors:
                    return v.lower(), f"{attr}={v}"
                for role, names in amap.items():
                    if v.lower() in names:
                        return self._floor_role(role), f"{attr}={v} (attribute map)"
        default = roles.get("default")
        if default:
            return default, "request roles.default"
        return None, "role not resolved"

    def _floor_role(self, role: str) -> str:
        """A named role without its own floor in the request is checked as a label."""
        return role if role in self.floors or role == "exempt" else "label"

    def type_floor(self) -> None:
        for t in self.m.texts:
            role, why = self._role(t)
            size = t["min_px"]
            base = dict(targets=[t["ref"]], measured=size, units="px at final slide size (1 px = 0.75 pt)", text=t["text"][:80], role=role, role_source=why,
                        tolerance=0.005, runs_px=sorted({round(r["font_px"], 2) for r in t["visible_runs"]}))
            if t.get("rotated"):
                base["note"] = "rotated text: size uses the uniform scale of the CTM"
            if role == "exempt":
                self.rec.add("type_floor", "waived", message=f"floor waived by request ({why})", **base)
                continue
            if role in self.floors:
                floor = self.floors[role]
                ok = size >= floor - 0.005
                self.rec.add("type_floor", "passed" if ok else "failed", severity="blocker", expected=f">= {floor} ({role})",
                             message=f"{size:.2f} px {'>=' if ok else '<'} {role} floor {floor} px", **base)
                continue
            if size < self.lowest_floor - 0.005:
                self.rec.add("type_floor", "failed", severity="blocker", expected=f">= {self.lowest_floor} (lowest floor)",
                             message=f"{size:.2f} px is below the lowest floor ({self.lowest_floor} px) whatever its role", **base)
            elif size >= self.floors["body"] - 0.005:
                self.rec.add("type_floor", "passed", expected=f">= {self.floors['body']} (any role)", message=f"{size:.2f} px meets both floors", **base)
            else:
                self.rec.add("type_floor", "unverified", expected=f">= {self.floors['body']} if body",
                             reason="role not resolved: meets the lowest floor, below the body floor",
                             message=f"{size:.2f} px: meets the lowest floor ({self.lowest_floor} px), fails as body; role unknown", **base)

    # ---------------- FIT: text fit and clipping ----------------
    def _clip_rects(self, chain: list[dict]) -> tuple[Optional[list[list[float]]], Optional[str]]:
        rects = []
        for clip in chain:
            spec = self.m.defs["clips"].get(clip.get("id") or "")
            if spec is None:
                return None, f"clip-path {clip.get('raw')} not found or not a local url"
            if spec["unsupported"]:
                return None, f"clip-path #{clip['id']} has unsupported children {spec['unsupported']}"
            if not spec["rects"]:
                return None, f"clip-path #{clip['id']} has no measurable children"
            m = clip["m"]
            for r in spec["rects"]:
                if spec["units"] == "objectBoundingBox":
                    bb = clip.get("bbox_local")
                    if not bb:
                        return None, "objectBoundingBox clip without a measurable box"
                    r = [bb[0] + r[0] * bb[2], bb[1] + r[1] * bb[3], bb[0] + r[2] * bb[2], bb[1] + r[3] * bb[3]]
                corners = [_apply(m, x, y, self.m.vb, self.m.k) for x, y in ((r[0], r[1]), (r[2], r[1]), (r[0], r[3]), (r[2], r[3]))]
                rects.append([min(c[0] for c in corners), min(c[1] for c in corners), max(c[0] for c in corners), max(c[1] for c in corners)])
        return rects, None

    def text_fit(self) -> None:
        declared = self.req.get("text_containers") or {}
        for t in self.m.texts:
            if t.get("clips"):
                clip_rects, why = self._clip_rects(t["clips"])
                if clip_rects is None:
                    self.rec.add("text_fit", "unverified", targets=[t["ref"]], reason=why, message="clip region not measurable")
                else:
                    region = clip_rects[0]
                    for r in clip_rects[1:]:
                        region = G.intersection(region, r) or [0, 0, 0, 0]
                    for line in t["lines"]:
                        ov = G.overflow(region, line["ink"])
                        worst = max(ov.values())
                        self.rec.add("text_fit", "passed" if worst <= 0.5 else "failed", severity="blocker", targets=[line["ref"], *[c["on"] for c in t["clips"]]],
                                     message=("text inside its clip region" if worst <= 0.5 else f"text cut by clip-path by {worst:.1f} px"),
                                     measured=ov, expected="inside clip region", tolerance=0.5, units="px", clip_rect=region,
                                     certainty="measured" if all(self.m.defs["clips"][c["id"]]["shape_is_rect_only"] for c in t["clips"]) else "approximate (clip reduced to its box)")
            if t.get("text_length_attr"):
                self.rec.add("text_fit", "failed", severity="minor", targets=[t["ref"]], certainty="flagged",
                             message="textLength forces the text to a width; fit is by squeezing, legibility not verified")
            for line in t["lines"]:
                cref = declared.get(line["text_ref"])
                container = self.m.by_ref.get(cref) if cref else self.m.container_of(line["rect"])
                if container is None:
                    continue
                ov = G.overflow(container["rect"], line["rect"])
                ov_ink = G.overflow(container["rect"], line["ink"])
                h_over = max(ov["left"], ov["right"])
                v_over = max(ov_ink["top"], ov_ink["bottom"])
                approx = line["rotated"] or container["tag"] in ("circle", "ellipse", "polygon", "path")
                ev = dict(targets=[line["ref"], container["ref"]], measured={"horizontal_px": h_over, "vertical_ink_px": v_over},
                          tolerance={"horizontal": 1.0, "vertical_ink": 1.0}, units="px", text=line["text"][:60],
                          container_rect=container["rect"], text_rect=line["rect"],
                          certainty="approximate (non-rectangular container or rotated text: box test)" if approx else "measured (vertical: approximate ink box)",
                          container_source="request text_containers" if cref else "smallest painted shape containing the text centre")
                if h_over <= 1.0 and v_over <= 1.0:
                    self.rec.add("text_fit", "passed", message="text inside its container", **ev)
                    continue
                backdrop = not cref and not self._node_like(container)
                if h_over > 1.0:
                    dark_bg = (G.luminance(container.get("fill")) or 1) < 0.35
                    light_text = (G.luminance(line["fill"]) or 0) > 0.6
                    sev = "minor" if h_over <= 3.0 else ("blocker" if (dark_bg and light_text) else "major")
                    msg = f"text runs {h_over:.1f} px past its container horizontally"
                    if dark_bg and light_text:
                        msg += " (light text leaving a dark shape: the part outside is likely invisible)"
                    elif backdrop:
                        sev = "minor"
                        msg = f"text crosses the edge of a backdrop (a band or column holding several labels) by {h_over:.1f} px"
                else:
                    sev = "minor"
                    msg = f"text ink exceeds its container vertically by about {v_over:.1f} px"
                self.rec.add("text_fit", "failed", severity=sev, message=msg, **ev)

    # ---------------- OFF: canvas ----------------
    def off_canvas(self) -> None:
        cr = self.m.canvas_rect
        for line in self.m.lines:
            ov = G.overflow(cr, line["rect"])
            worst = max(ov.values())
            self.rec.add("off_canvas", "passed" if worst <= 0.5 else "failed", severity="blocker", targets=[line["ref"]], measured=ov, tolerance=0.5, units="px",
                         message="text on canvas" if worst <= 0.5 else f"text extends {worst:.1f} px beyond the canvas")
        for s in self.m.shapes:
            r = s["rect"]
            ov = G.overflow(cr, r)
            worst = max(ov.values())
            if worst <= 0.5:
                self.rec.add("off_canvas", "passed", targets=[s["ref"]], measured=worst, tolerance=0.5, units="px", message="on canvas")
                continue
            inside = G.intersection(cr, r)
            fully_off = inside is None
            self.rec.add("off_canvas", "failed", severity="major" if fully_off else "minor", targets=[s["ref"]], measured=ov, tolerance=0.5, units="px",
                         certainty="measured (fill geometry; stroke not added)",
                         message=("element entirely outside the canvas" if fully_off else f"element bleeds {worst:.1f} px past the canvas edge"))

    # ---------------- OVL: overlaps and containment ----------------
    def _allowed(self, a: dict, b: dict) -> Optional[str]:
        for entry in self.req.get("allowed_overlaps") or []:
            x, y = entry[0], entry[1]
            ka = {a["ref"], a.get("text_ref"), a.get("id"), *a.get("ancestors", [])}
            kb = {b["ref"], b.get("text_ref"), b.get("id"), *b.get("ancestors", [])}
            if (x in ka and y in kb) or (x in kb and y in ka):
                return entry[2] if len(entry) > 2 else "declared intentional"
        return None

    def _node_like(self, s: dict) -> bool:
        """A shape that reads as an object of its own: it has an outline or carries a label."""
        if s.get("stroke"):
            return True
        inside = [line for line in self.m.lines if G.contains_point(s["rect"], G.center(line["ink"]))]
        return 1 <= len(inside) <= 3 and sum(G.area(line["rect"]) for line in inside) >= 0.08 * G.area(s["rect"])

    def _occluded(self, line_el: dict, region: list[float]) -> bool:
        """True when an opaque shape painted after the stroke covers the region (the stroke is hidden there)."""
        for s in self.m.closed:
            if s["order"] <= line_el["order"] or not s.get("fill") or s.get("fill_opacity", 1) < 0.9 or s["opacity"] < 0.9:
                continue
            if G.contains_rect(s["rect"], region, 0.5):
                return True
        return False

    def overlap(self) -> None:
        lines = self.m.lines
        pairs = 0
        for i, a in enumerate(lines):
            for b in lines[i + 1:]:
                if a["text_ref"] == b["text_ref"]:
                    continue
                inter = G.intersection(a["ink"], b["ink"])
                if not inter:
                    continue
                pairs += 1
                if G.width(inter) <= 0.8 or G.height(inter) <= 0.8:
                    continue
                ev = dict(targets=[a["ref"], b["ref"]], measured={"overlap_w": G.width(inter), "overlap_h": G.height(inter)}, units="px",
                          tolerance=0.8, texts=[a["text"][:40], b["text"][:40]])
                why = self._allowed(a, b)
                same = norm(a["text"]) == norm(b["text"]) and all(abs(x - y) <= 1.0 for x, y in zip(a["rect"], b["rect"]))
                if why:
                    self.rec.add("overlap", "waived", message=f"text overlap declared intentional: {why}", **ev)
                elif same:
                    self.rec.add("overlap", "failed", severity="minor", certainty="measured",
                                 message="the same text is drawn twice at the same place (looks single in the render; duplicated in the editable PPTX)", **ev)
                else:
                    self.rec.add("overlap", "failed", severity="blocker", message="two texts collide", **ev)
        self.rec.add("overlap", "passed", targets=[], message=f"text-on-text examined over {len(lines)} lines", measured={"lines": len(lines), "candidate_pairs": pairs})
        # lines through text
        for c in self.m.connectors:
            pts = c["points"]
            ends = (pts[0], pts[-1])
            for line in lines:
                ink = line["ink"]
                if not G.polyline_hits_rect(pts, ink):
                    continue
                if any(G.dist_point_rect(e, line["rect"]) <= 4.0 for e in ends):
                    continue  # a line ending at text is a tether or an attaching connector
                hor = G.height(c["rect"]) <= 1.5
                if hor and line["rect"][3] - 0.3 * G.height(line["rect"]) <= c["rect"][1] <= line["rect"][3] + 3:
                    continue  # underline
                if c["order"] < line["order"] and self._occluded(c, G.intersection(ink, G.inflate(c["rect"], 1.0)) or ink):
                    continue  # the stroke is painted over by a shape before the text is drawn
                why = self._allowed(c, line)
                faint = (G.luminance(c.get("stroke")) or 0) > 0.6 or c.get("stroke_px", 1) < 0.75
                ev = dict(targets=[c["ref"], line["ref"]], text=line["text"][:40], units="px", certainty="measured (centre line vs approximate glyph ink box)",
                          stroke=G.hex_of(c.get("stroke")))
                if why:
                    self.rec.add("overlap", "waived", message=f"line through text declared intentional: {why}", **ev)
                else:
                    self.rec.add("overlap", "failed", severity="minor" if faint else "major",
                                 message=("a faint stroke (grid or guide) runs through a text line" if faint else "a stroked line passes through a text line"), **ev)
        # shapes on text / text straddling shape edges
        for line in lines:
            container = self.m.container_of(line["rect"])
            for s in self.m.closed:
                if s is container or self.m.is_background(s) or s["tag"] in ("use", "foreignObject"):
                    continue
                inter = G.intersection(line["ink"], s["rect"])
                if not inter or G.width(inter) <= 1.0 or G.height(inter) <= 1.0:
                    continue
                if G.contains_rect(s["rect"], line["ink"], tol=1.0):
                    continue  # text inside a bigger shape (nested container)
                if self.m.related(s, line):
                    continue
                if s.get("outline") and G.overlap_area(line["ink"], None, s["rect"], s["outline"]) <= 2.0:
                    continue  # the box overlaps, the drawn outline does not
                small = G.area(s["rect"]) < 3 * G.area(line["rect"]) and G.area(s["rect"]) < 2500
                if s["tag"] == "image":
                    self.rec.add("overlap", "unverified", targets=[line["ref"], s["ref"]], reason="text over a raster image: pixels not read",
                                 message="text over image")
                    continue
                if s["order"] < line["order"] and not s.get("stroke") and (s.get("fill_opacity", 1) < 0.35 or s["opacity"] < 0.35):
                    continue  # a translucent wash under the text (e.g. a highlighted window) is not an edge the text crosses
                why = self._allowed(s, line)
                ev = dict(targets=[line["ref"], s["ref"]], text=line["text"][:40], measured={"overlap_w": G.width(inter), "overlap_h": G.height(inter)}, units="px")
                if why:
                    self.rec.add("overlap", "waived", message=f"declared intentional: {why}", **ev)
                elif small:
                    self.rec.add("overlap", "failed", severity="major", message="a small shape sits on a text line that is not inside it", **ev)
                elif not self._node_like(s) and (G.luminance(s.get("fill")) or 1) >= 0.35:
                    self.rec.add("overlap", "failed", severity="minor", certainty="flagged (legibility judgement)",
                                 message="text crosses the edge of a light backdrop (a band or column holding several labels)", **ev)
                else:
                    self.rec.add("overlap", "failed", severity="major", message="text straddles the edge of a shape (neither fully inside nor beside it)", **ev)
        # partial overlaps between node-like shapes (containment is fine)
        nodes = [s for s in self.m.closed if not self.m.is_band(s) and 60 <= G.area(s["rect"]) <= 0.3 * self.m.canvas_area
                 and s["tag"] not in ("use", "foreignObject") and self._node_like(s)]
        contained = 0
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                inter = G.intersection(a["rect"], b["rect"])
                if not inter or G.area(inter) <= 4:
                    continue
                if G.contains_rect(a["rect"], b["rect"], 1.0) or G.contains_rect(b["rect"], a["rect"], 1.0):
                    contained += 1
                    continue
                shared = G.overlap_area(a["rect"], a.get("outline"), b["rect"], b.get("outline"))
                if shared <= 4.0:
                    continue
                why = self._allowed(a, b)
                ev = dict(targets=[a["ref"], b["ref"]], measured={"overlap_w": G.width(inter), "overlap_h": G.height(inter), "shared_area_px2": shared}, units="px",
                          certainty="flagged (outline-sampled; may be intentional)")
                if why:
                    self.rec.add("overlap", "waived", message=f"declared intentional: {why}", **ev)
                else:
                    self.rec.add("overlap", "failed", severity="minor", message="two labelled or outlined shapes partially overlap (not containment)", **ev)
        self.rec.add("overlap", "passed", targets=[], message=f"shape pairs examined among {len(nodes)} node-like shapes; {contained} full containments treated as intentional",
                     measured={"shapes": len(nodes), "containments": contained})
        for fact in self.req.get("containment") or []:
            child, parent = self.m.rect_of(fact["child"]), self.m.rect_of(fact["parent"])
            if child is None or parent is None:
                self.rec.add("overlap", "unverified", targets=[fact["child"], fact["parent"]], reason="element not found", message="declared containment not measurable")
                continue
            ov = G.overflow(parent, child)
            ok = max(ov.values()) <= 1.0
            self.rec.add("overlap", "passed" if ok else "failed", severity="blocker", targets=[fact["child"], fact["parent"]], measured=ov, tolerance=1.0, units="px",
                         message="declared containment holds" if ok else "child is not inside its declared container")

    # ---------------- CON: connectors ----------------
    def _connector_role(self, c: dict) -> Optional[str]:
        role = ((c.get("data") or {}).get("data-role") or (c.get("data") or {}).get("data-kind") or "").lower()
        return role or None

    def _is_structural_line(self, c: dict) -> bool:
        role = self._connector_role(c)
        if role in ("axis", "gridline", "grid", "divider", "rule", "underline", "decor", "guide", "leader"):
            return True
        if any(c["markers"].values()):
            return False
        r = c["rect"]
        return (G.height(r) <= 1.5 and G.width(r) >= 0.5 * self.m.W) or (G.width(r) <= 1.5 and G.height(r) >= 0.5 * self.m.H)

    def _bindables(self) -> list[dict]:
        out = []
        for s in self.m.closed:
            if self.m.is_background(s):
                continue
            out.append({"ref": s["ref"], "rect": s["rect"], "kind": "shape", "area": G.area(s["rect"]), "band": self.m.is_band(s)})
        for line in self.m.lines:
            if len(line["text"].strip()) == 1 and line["text"].strip() in SYMBOLS:
                out.append({"ref": line["ref"], "rect": line["ink"], "kind": "symbol", "area": G.area(line["ink"]), "band": False})
            else:
                out.append({"ref": line["ref"], "rect": line["rect"], "kind": "text", "area": G.area(line["rect"]), "band": False})
        return out

    @staticmethod
    def _attach_dist(p, b: dict, tol: float) -> float:
        """How far a connector end is from attaching to an element. Outside: distance to the box. Inside a
        small element (text, marker, badge): 0. Inside a large shape: distance to its nearest edge, so an
        end deep inside a container or band is not read as attached to it."""
        r = b["rect"]
        if not G.contains_point(r, p):
            return G.dist_point_rect(p, r)
        if b["kind"] != "shape" or min(G.width(r), G.height(r)) <= 4 * tol:
            return 0.0
        return min(p[0] - r[0], r[2] - p[0], p[1] - r[1], r[3] - p[1])

    def _owner(self, p, bindables: list[dict], exclude: set, tol: float) -> tuple[Optional[dict], float]:
        best, best_d = None, float("inf")
        for b in bindables:
            if b["ref"] in exclude:
                continue
            d = self._attach_dist(p, b, tol)
            if d > tol:
                continue
            if d < best_d - 1e-9 or (abs(d - best_d) <= 1e-9 and best is not None and b["area"] < best["area"]):
                best, best_d = b, d
        return best, best_d

    @staticmethod
    def _outward(c: dict, end: int):
        """Unit vector pointing away from the connector at its start (end=0) or end (end=1)."""
        v = G.direction(c["points"], at_end=(end == 1))
        if v is None:
            return None
        return v if end == 1 else (-v[0], -v[1])

    def _ray_to_targets(self, p, v, targets: list[dict], bindables: list[dict], reach: float) -> Optional[float]:
        """Distance along a ray from p to the first target (e.g. a thin gate rule), unless another element is met first."""
        d = 1.0
        while d <= reach:
            q = (p[0] + v[0] * d, p[1] + v[1] * d)
            if any(G.contains_point(G.inflate(a["rect"], 1.5), q) for a in targets):
                return d
            if any(G.contains_point(b["rect"], q) and not b["band"] and not G.contains_point(b["rect"], p)
                   and G.height(b["rect"]) <= 44 for b in bindables):
                return None
            d += 1.0
        return None

    def _ray_owner(self, p, v, bindables: list[dict], reach: float):
        """First element hit by a ray from p along v within reach: (element, distance)."""
        step = 1.0
        d = step
        while d <= reach:
            q = (p[0] + v[0] * d, p[1] + v[1] * d)
            hits = [b for b in bindables if G.contains_point(b["rect"], q) and not b["band"] and not G.contains_point(b["rect"], p)]
            if hits:
                return min(hits, key=lambda b: b["area"]), d
            d += step
        return None

    def _end_owner(self, c: dict, end: int, bindables: list[dict], tol: float) -> Optional[str]:
        p = c["points"][0] if end == 0 else c["points"][-1]
        owner, _ = self._owner(p, bindables, set(), tol)
        if owner is None:
            v = self._outward(c, end)
            hit = self._ray_owner(p, v, bindables, 60.0) if v is not None else None
            owner = hit[0] if hit else None
        return owner["ref"].split(":line")[0] if owner else None

    def _links(self, conns: list[dict], bindables: list[dict], tol: float) -> list[bool]:
        """Per connector: directed, with its two ends attached to two different elements."""
        out = []
        for c in conns:
            if not (c["markers"]["end"] or c["markers"]["start"]):
                out.append(False)
                continue
            a, b = self._end_owner(c, 0, bindables, tol), self._end_owner(c, 1, bindables, tol)
            out.append(bool(a and b and a != b))
        return out

    def _junctions(self, conns: list[dict]) -> dict:
        """Endpoint-to-endpoint joins and T-junctions (an endpoint on another connector's interior)."""
        joins = collections.defaultdict(list)
        for i, a in enumerate(conns):
            for ei, e in enumerate((a["points"][0], a["points"][-1])):
                for j, b in enumerate(conns):
                    if i == j:
                        continue
                    bends = (b["points"][0], b["points"][-1])
                    dend = min(math.hypot(e[0] - q[0], e[1] - q[1]) for q in bends)
                    if dend <= 3.0:
                        joins[i].append({"to": j, "end": ei, "kind": "end-to-end", "d": dend})
                        continue
                    d, s = G.dist_point_polyline(e, b["points"])
                    if d <= 2.5:
                        arrive = G.direction(a["points"], at_end=(ei == 1))
                        along = _direction_at(b["points"], s)
                        collinear = arrive is not None and along is not None and abs(arrive[0] * along[1] - arrive[1] * along[0]) < 0.34  # |sin| < 20 deg
                        joins[i].append({"to": j, "end": ei, "kind": "t-junction", "d": d, "at": s, "collinear": collinear,
                                         "onto_directed": bool(b["markers"]["end"] or b["markers"]["start"]) and not collinear})
        return joins

    def connectors(self) -> None:
        conns = [c for c in self.m.connectors if not self._is_structural_line(c)]
        bindables = self._bindables()
        tol = float(self.req.get("connector_tolerance_px", 8.0))
        joins = self._junctions(conns)
        links = self._links(conns, bindables, tol)
        for lst in joins.values():
            for j in lst:
                j["onto_link"] = j["kind"] == "t-junction" and links[j["to"]] and not j.get("collinear")
        self._conn_cache = (conns, bindables, joins, tol)
        self._link_flags = links
        for i, c in enumerate(conns):
            if self._legend_sample(c, bindables, tol):
                self.rec.add("connectors", "passed", targets=[c["ref"]], certainty="classified as a legend sample (short, both ends free, text beside it)",
                             message="legend sample line: not checked as a connector")
                continue
            guide = not any(c["markers"].values()) and ((G.luminance(c.get("stroke")) or 0) > 0.6 or c.get("stroke_px", 1) < 0.75)
            for j in joins.get(i, []):
                if j["onto_link"] and not guide:
                    other = conns[j["to"]]
                    endp = c["points"][0] if j["end"] == 0 else c["points"][-1]
                    self.rec.add("connectors", "failed", severity="major", targets=[c["ref"], other["ref"]], certainty="geometry measured; meaning ambiguous",
                                 measured={"endpoint": list(endp), "distance_to_other_px": j["d"], "position_along_other_px": j["at"]}, units="px", tolerance=2.5,
                                 message="connector ends on the middle of an arrow that joins two other elements (T-junction): which one it attaches to is ambiguous")
            heads = []
            if c["markers"]["end"]:
                heads.append(("end", c["points"][-1]))
            if c["markers"]["start"]:
                heads.append(("start", c["points"][0]))
            for which, p in heads:
                owner, d = self._owner(p, bindables, set(), tol)
                on_conn = any(j["end"] == (1 if which == "end" else 0) for j in joins.get(i, []))
                if owner is None and not on_conn:
                    self.rec.add("connectors", "failed", severity="major", targets=[c["ref"]], measured={"tip": list(p)}, tolerance=tol, units="px",
                                 message=f"arrowhead ({which}) points at empty space: nothing within {tol:.0f} px")
                else:
                    self.rec.add("connectors", "passed", targets=[c["ref"], owner["ref"] if owner else None], measured={"tip": list(p), "distance_px": d if owner else 0},
                                 tolerance=tol, units="px", message=f"arrowhead ({which}) lands on {owner['ref'] if owner else 'another connector'}")
        for spec in self.req.get("connectors") or []:
            self._relationship(spec.get("id") or spec.get("element") or "connector", self._resolve_refs(spec.get("from")), self._resolve_refs(spec.get("to")),
                               directed=spec.get("directed", True), style=spec.get("style"), label=None, element=spec.get("element"), source="request connectors")
        self.rec.add("connectors", "passed", targets=[], message=f"connectors examined: {len(conns)} (structural lines excluded: {len(self.m.connectors) - len(conns)})",
                     measured={"connectors": len(conns), "structural_excluded": len(self.m.connectors) - len(conns)})

    def _leader_gap(self, label: list[float], target: list[float], gap: float) -> Optional[float]:
        """A thin unarrowed stroke that starts at the label (within 4 px) and ends within leader_gap_px (default 24 px,
        room for a week ruler) of the target, inside the target's horizontal span, attaches the label to it (a leader
        across a ruler or header). Returns the remaining gap in px, or None."""
        best = None
        for c in self.m.connectors:
            if any(c["markers"].values()) or c.get("length", 0) > 160:
                continue
            a, b = c["points"][0], c["points"][-1]
            for near, far in ((a, b), (b, a)):
                if G.dist_point_rect(near, label) > 4.0:
                    continue
                if not (target[0] - 2 <= far[0] <= target[2] + 2):
                    continue
                d = G.dist_point_rect(far, target)
                if d <= float(self.req.get("leader_gap_px", 24.0)) and (best is None or d < best):
                    best = d
        return best

    def _style_verdict(self, style: str, chain: list[dict]) -> tuple[Optional[bool], str]:
        """solid / dashed are checked directly. A named style ('read', 'scoped write') is checked against the request's
        style_map, else against the slide's own legend sample whose text names it; otherwise it is unverified."""
        st = norm(style)
        if st in ("solid", "dashed"):
            got = ["dashed" if c.get("dashed") else "solid" for c in chain]
            return all(g == st for g in got), f"drawn {got}"
        spec = (self.req.get("style_map") or {}).get(style)
        source = "request style_map"
        if spec is None:
            spec, source = self._legend_style(st)
        if spec is None:
            return None, f"'{style}' is not solid/dashed, has no style_map entry and no legend entry names it"
        bad = []
        for c in chain:
            if "dashed" in spec and bool(c.get("dashed")) != bool(spec["dashed"]):
                bad.append(f"{c['ref']} {'dashed' if c.get('dashed') else 'solid'}")
            dist = G.color_distance(c.get("stroke"), spec.get("stroke")) if spec.get("stroke") else None
            if dist is not None and dist > float(spec.get("tolerance", 60.0)):
                bad.append(f"{c['ref']} colour {G.hex_of(c.get('stroke'))} vs {G.hex_of(spec['stroke'])}")
        return (not bad), (f"{source}: " + ("; ".join(bad) if bad else "matches"))

    def _legend_style(self, style_norm: str) -> tuple[Optional[dict], str]:
        """The legend sample line whose text contains the style's words (e.g. 'read', 'scoped write')."""
        want = tokens(style_norm)
        if not want:
            return None, ""
        for c in self.m.connectors:
            r = c["rect"]
            if c.get("length", 0) > 60 or G.height(r) > 3:
                continue
            cy = (r[1] + r[3]) / 2
            for line in self.m.lines:
                lr = line["rect"]
                if not (lr[1] - 2 <= cy <= lr[3] + 2 and 0 <= lr[0] - r[2] <= 16):
                    continue
                have = tokens(line["text"])
                if all(w in have for w in want) and len(have) <= len(want) + 3:
                    return {"dashed": bool(c.get("dashed")), "stroke": c.get("stroke")}, f"legend sample {c['ref']} ('{line['text']}')"
        return None, ""

    def _legend_sample(self, c: dict, bindables: list[dict], tol: float) -> bool:
        """A short stroke with both ends free and a text label right beside it on the same line (a key entry)."""
        role = self._connector_role(c) or ""
        if role in ("legend", "key", "legend-sample"):
            return True
        if c.get("length", 0) > 60:
            return False
        for end in (0, 1):
            p = c["points"][0] if end == 0 else c["points"][-1]
            owner, _ = self._owner(p, bindables, set(), 2.0)
            if owner is not None and owner["kind"] != "text":
                return False
        r = c["rect"]
        cy = (r[1] + r[3]) / 2
        for line in self.m.lines:
            lr = line["rect"]
            if lr[1] - 2 <= cy <= lr[3] + 2 and (0 <= lr[0] - r[2] <= 16 or 0 <= r[0] - lr[2] <= 16):
                return True
        return False

    def _resolve_refs(self, spec: Any) -> list[dict]:
        """Endpoint target geometry from element refs or checklist item ids (any-of)."""
        if spec is None:
            return []
        specs = spec if isinstance(spec, list) else [spec]
        out = []
        for s in specs:
            if s in self.item_anchor:
                out.append(self.item_anchor[s])
                out.extend(self.item_alternates.get(s, []))
            elif self.m.rect_of(s) is not None:
                out.append({"ref": s, "rect": self.m.rect_of(s), "refs": [s], "how": "element ref"})
        return out

    def _relationship(self, rid: str, src: list[dict], dst: list[dict], *, directed: bool, style: Optional[str], label: Optional[str],
                      element: Optional[str], source: str, item: Optional[dict] = None) -> None:
        if not hasattr(self, "_conn_cache"):
            conns = [c for c in self.m.connectors if not self._is_structural_line(c)]
            bindables, tol0 = self._bindables(), float(self.req.get("connector_tolerance_px", 8.0))
            joins = self._junctions(conns)
            links = self._links(conns, bindables, tol0)
            for lst in joins.values():
                for j in lst:
                    j["onto_link"] = j["kind"] == "t-junction" and links[j["to"]] and not j.get("collinear")
            self._link_flags = links
            self._conn_cache = (conns, bindables, joins, tol0)
        conns, bindables, joins, tol = self._conn_cache
        tgt = [rid] + [a["ref"] for a in src] + [a["ref"] for a in dst]
        if not src or not dst:
            self.rec.add("connectors", "unverified", targets=tgt, reason="an endpoint of the relationship could not be located", message=f"relationship {rid}: endpoints not located ({source})")
            return
        src_refs = {r for a in src for r in a.get("refs", [a["ref"]])}
        dst_refs = {r for a in dst for r in a.get("refs", [a["ref"]])}

        candidates = range(len(conns))
        if element:
            candidates = [i for i, c in enumerate(conns) if element in (c["ref"], c.get("id"), *c.get("ancestors", []))]
            if not candidates:
                self.rec.add("connectors", "failed", severity="blocker", targets=tgt + [element], message=f"relationship {rid}: declared connector {element} not found or not a stroke")
                return

        def search(tol: float, loose_pass: bool = False) -> tuple[list[dict], Optional[dict]]:
            def bound(p, targets: list[dict], own: set, outward=None) -> Optional[float]:
                d_t = min(G.dist_point_rect(p, a["rect"]) for a in targets)
                if d_t <= tol:
                    owner, d_o = self._owner(p, bindables, set(), tol)
                    if owner is None or owner["ref"] in own or owner["ref"].split(":line")[0] in own or d_t <= d_o + 1.0:
                        return d_t
                    if any(G.contains_rect(a["rect"], owner["rect"], 1.0) for a in targets):
                        return d_t
                if loose_pass and outward is not None:
                    direct = self._ray_to_targets(p, outward, targets, bindables, 60.0)
                    if direct is not None:
                        return direct
                    hit = self._ray_owner(p, outward, bindables, 60.0)
                    if hit is not None and (hit[0]["ref"] in own or hit[0]["ref"].split(":line")[0] in own
                                            or any(G.contains_rect(a["rect"], hit[0]["rect"], 1.0) for a in targets)):
                        return hit[1]
                return None

            best_fail = None
            results = []
            for i in candidates:
                c = conns[i]
                for start_end in (0, 1):
                    p = c["points"][0] if start_end == 0 else c["points"][-1]
                    d_src = bound(p, src, src_refs, self._outward(c, start_end))
                    if d_src is None:
                        continue
                    # walk the connector graph from the far end of this connector
                    seen = {i}
                    frontier = [(i, 1 - start_end, [c["ref"]], False)]
                    while frontier:
                        k, far, chain, ambiguous = frontier.pop()
                        ck = conns[k]
                        q = ck["points"][0] if far == 0 else ck["points"][-1]
                        d_dst = bound(q, dst, dst_refs, self._outward(ck, far))
                        if d_dst is not None:
                            head_at_dst = bool(ck["markers"]["end"] if far == 1 else ck["markers"]["start"])
                            first = conns[i]
                            head_at_src = bool(first["markers"]["start"] if start_end == 0 else first["markers"]["end"])
                            results.append({"chain": chain, "d_src": d_src, "d_dst": d_dst, "head_at_dst": head_at_dst, "head_at_src": head_at_src,
                                            "ambiguous": ambiguous, "styles": ["dashed" if self.m.by_ref[r]["dashed"] else "solid" for r in chain]})
                        for j in joins.get(k, []):
                            # this connector's far end meets another connector
                            if j["end"] != far or j["to"] in seen:
                                continue
                            nxt = conns[j["to"]]
                            seen.add(j["to"])
                            if j["kind"] == "end-to-end":
                                e0 = math.hypot(nxt["points"][0][0] - q[0], nxt["points"][0][1] - q[1])
                                e1 = math.hypot(nxt["points"][-1][0] - q[0], nxt["points"][-1][1] - q[1])
                                frontier.append((j["to"], 1 if e0 <= e1 else 0, chain + [nxt["ref"]], ambiguous))
                            else:
                                amb = ambiguous or j.get("onto_link", j["onto_directed"])
                                for nf in (0, 1):
                                    frontier.append((j["to"], nf, chain + [nxt["ref"]], amb))
                        # other connectors whose own endpoint meets this one (end to end at q, or branching off it)
                        directed_k = self._link_flags[k] if getattr(self, "_link_flags", None) else bool(ck["markers"]["end"] or ck["markers"]["start"])
                        for other, lst in joins.items():
                            if other in seen:
                                continue
                            for j in lst:
                                if j["to"] != k:
                                    continue
                                oc = conns[other]
                                oe = oc["points"][0] if j["end"] == 0 else oc["points"][-1]
                                if j["kind"] == "end-to-end" and math.hypot(oe[0] - q[0], oe[1] - q[1]) > 3.0:
                                    continue
                                seen.add(other)
                                amb = ambiguous or (j["kind"] == "t-junction" and directed_k)
                                frontier.append((other, 1 - j["end"], chain + [oc["ref"]], amb))
                                break
                    if best_fail is None:
                        best_fail = {"from_connector": c["ref"], "far_end": list(conns[i]["points"][-1] if start_end == 0 else conns[i]["points"][0])}
            return results, best_fail

        results, best_fail = search(tol)
        loose = None
        if not results:
            loose_tol = min(3.0 * tol, 30.0)
            results, _ = search(loose_tol, loose_pass=True)
            if results:
                loose = loose_tol
        ev = dict(targets=tgt, units="px", tolerance=tol, source=source)
        if not results:
            msg = f"relationship {rid}: no drawn connector joins {'/'.join(a['ref'] for a in src)} to {'/'.join(a['ref'] for a in dst)}"
            if best_fail:
                ev["nearest_attempt"] = best_fail
            self.rec.add("connectors", "failed", severity="blocker", message=msg, **ev)
            return
        good = [r for r in results if not r["ambiguous"]]
        pick = (good or results)[0]
        if directed:
            fwd = [r for r in (good or results) if r["head_at_dst"]]
            if fwd:
                pick = fwd[0]
        ev.update(measured={"chain": pick["chain"], "src_distance_px": pick["d_src"], "dst_distance_px": pick["d_dst"], "styles": pick["styles"]})
        if pick["ambiguous"]:
            self.rec.add("connectors", "failed", severity="major", certainty="geometry measured; attachment ambiguous",
                         message=f"relationship {rid}: joined only through a T-junction onto another connector; the attachment is ambiguous", **ev)
            return
        if directed and not pick["head_at_dst"]:
            reason = "arrowhead at the source end: direction reversed" if pick["head_at_src"] else "no arrowhead at the target end: direction not shown"
            self.rec.add("connectors", "failed", severity="major", message=f"relationship {rid}: {reason}", **ev)
            return
        if style:
            verdict, why = self._style_verdict(style, [self.m.by_ref[r] for r in pick["chain"]])
            if verdict is False:
                self.rec.add("connectors", "failed", severity="major", message=f"relationship {rid}: line style does not match '{style}' ({why})", **ev)
                return
            if verdict is None:
                self.rec.add("connectors", "unverified", targets=tgt, reason=why, message=f"relationship {rid}: line style '{style}' not checked")
        if loose is not None:
            gap = max(pick["d_src"], pick["d_dst"])
            self.rec.add("connectors", "failed", severity="minor", certainty=f"flagged: joined only within the loose tolerance ({loose:.0f} px, or a 60 px ray along the line from a free end)",
                         message=f"relationship {rid}: drawn, but a line end stops {gap:.0f} px short of its node", **ev)
        else:
            self.rec.add("connectors", "passed", message=f"relationship {rid}: drawn endpoint to endpoint", **ev)
        if label:
            pts = [p for r in pick["chain"] for p in self.m.by_ref[r]["points"]]
            cands = self.find_text({"text": label, "alt": (item or {}).get("label_alt", [])})
            cands = [u for u in cands if u["score"] >= self.threshold]
            if not cands:
                self.rec.add("semantic", "failed", severity="blocker", targets=[rid], message=f"relationship {rid}: label '{label}' not found")
            else:
                d = min(min(G.dist_point_rect(p, u["rect"]) for p in pts) for u in cands)
                self.rec.add("semantic", "passed" if d <= 24 else "failed", severity="major", targets=[rid, cands[0]["ref"]], measured=d, tolerance=24, units="px",
                             message=f"relationship {rid}: label {'beside' if d <= 24 else 'away from'} its connector ({d:.1f} px)")

    # ---------------- MRK: markers ----------------
    def markers(self) -> None:
        for c in self.m.connectors:
            for which in ("start", "end", "mid"):
                mid_ = c["markers"].get(which)
                if not mid_:
                    continue
                spec = self.m.defs["markers"].get(mid_)
                tgt = [c["ref"], "#" + mid_]
                if which == "mid":
                    self.rec.add("markers", "unverified", targets=tgt, reason="marker-mid is not verified", message="marker-mid present")
                    continue
                if spec is None:
                    self.rec.add("markers", "failed", severity="major", targets=tgt, message=f"marker-{which} references #{mid_}, which is not a local <marker>")
                    continue
                size = spec["markerWidth"] * (c["stroke_px"] if spec["markerUnits"] != "userSpaceOnUse" else c["scale"])
                pts = spec["points"]
                if spec["curved"] or len(pts) < 2:
                    self.rec.add("markers", "unverified", targets=tgt, reason="marker drawn with curves/circles: direction not derived", message=f"marker-{which} present",
                                 measured={"size_px": size})
                    continue
                cx = sum(p[0] for p in pts) / len(pts)
                tip_x = max(p[0] for p in pts)
                back_x = min(p[0] for p in pts)
                span = tip_x - back_x
                if span <= 1e-6:
                    self.rec.add("markers", "unverified", targets=tgt, reason="marker has no horizontal extent", message="marker direction unknown")
                    continue
                forward = (tip_x - cx) > (cx - back_x) + 0.05 * span  # tip on +x: arrow drawn pointing along +x
                backward = (cx - back_x) > (tip_x - cx) + 0.05 * span
                symmetric = not forward and not backward
                orient = spec["orient"]
                tangent = G.direction(c["points"], at_end=(which == "end"))
                if tangent is None:
                    self.rec.add("markers", "unverified", targets=tgt, reason="path too short for a tangent", message="direction unknown")
                    continue
                want = G.angle_deg(tangent) if which == "end" else G.angle_deg((-tangent[0], -tangent[1]))
                if orient == "auto":
                    base = G.angle_deg(tangent)
                elif orient == "auto-start-reverse":
                    base = G.angle_deg(tangent) if which == "end" else G.angle_deg((-tangent[0], -tangent[1]))
                else:
                    try:
                        base = float(re.sub(r"deg$", "", orient))
                    except ValueError:
                        self.rec.add("markers", "unverified", targets=tgt, reason=f"orient={orient} not understood", message="direction unknown")
                        continue
                if symmetric:
                    self.rec.add("markers", "passed", targets=tgt, certainty="symmetric marker (dot/diamond/bar): no direction to check",
                                 measured={"size_px": size, "orient": orient}, message=f"marker-{which} symmetric")
                    continue
                drawn = base if forward else base + 180.0
                diff = G.angle_diff(drawn, want)
                ev = dict(targets=tgt, measured={"arrow_angle_deg": drawn % 360, "outward_angle_deg": want % 360, "difference_deg": diff, "size_px": size, "orient": orient},
                          tolerance=20.0, units="degrees", certainty="measured from marker vertices and path tangent")
                if diff <= 20.0:
                    self.rec.add("markers", "passed", message=f"marker-{which} points outward along the path", **ev)
                else:
                    extra = " (marker-start with orient=auto points into the line; use auto-start-reverse or a reversed marker)" if which == "start" and orient == "auto" else ""
                    self.rec.add("markers", "failed", severity="major", message=f"marker-{which} points {diff:.0f} degrees away from the path direction{extra}", **ev)

    # ---------------- SEM + TL: checklist ----------------
    def _lane_bands(self) -> dict:
        """Lane y-bands: declared in the request, else the lane's own background row (a wide filled rect around its
        label), else between the neighbouring lanes' rows, else derived from the label positions."""
        tl = self.req.get("timeline") or {}
        bands = dict(tl.get("lane_bands") or {})
        lanes = [it for it in self.cl.get("items", []) if it.get("kind") == "lane"]
        found = []
        for lane in lanes:
            if lane["id"] in bands:
                continue
            cands = [u for u in self.find_text(lane) if u["score"] >= self.threshold]
            if cands:
                found.append((lane["id"], cands[0]["rect"]))
        found.sort(key=lambda f: f[1][1])
        rows = [s for s in self.m.closed if s.get("fill") and G.width(s["rect"]) >= 0.5 * self.m.W and not self.m.is_background(s)
                and G.height(s["rect"]) <= 0.2 * self.m.H]
        own: dict[str, list[float]] = {}
        for lid, rect in found:
            c = G.center(rect)
            hits = [r for r in rows if G.contains_point(r["rect"], c)]
            if hits:
                r = min(hits, key=lambda h: G.area(h["rect"]))["rect"]
                own[lid] = [r[1], r[3]]
        mode = tl.get("lane_band_mode", "label_top")
        pad = float(tl.get("lane_band_pad", 4.0))
        for i, (lid, rect) in enumerate(found):
            if lid in own:
                bands[lid] = [own[lid][0], own[lid][1], "lane background row"]
                continue
            prev_id = found[i - 1][0] if i > 0 else None
            next_id = found[i + 1][0] if i + 1 < len(found) else None
            if (prev_id in own or prev_id is None) and (next_id in own or next_id is None) and (prev_id or next_id):
                top = own[prev_id][1] if prev_id else rect[1] - pad
                bottom = own[next_id][0] if next_id else rect[3] + (own[prev_id][1] - own[prev_id][0] if prev_id else 40)
                bands[lid] = [top, bottom, "between neighbouring lane rows"]
                continue
            if mode == "label_center":
                cy = G.center(rect)[1]
                prev_c = G.center(found[i - 1][1])[1] if i > 0 else None
                next_c = G.center(found[i + 1][1])[1] if i + 1 < len(found) else None
                top = (cy + prev_c) / 2 if prev_c is not None else cy - ((next_c - cy) / 2 if next_c else 20)
                bottom = (cy + next_c) / 2 if next_c is not None else cy + ((cy - prev_c) / 2 if prev_c else 20)
            else:
                top = rect[1] - pad
                bottom = found[i + 1][1][1] - pad if i + 1 < len(found) else rect[1] - pad + (rect[1] - found[i - 1][1][1] if i > 0 else 40)
            bands[lid] = [top, bottom, f"derived from labels ({mode})"]
        return bands

    def _bar_candidates(self) -> list[dict]:
        x0 = self.scale["origin_x"] - 3 * self.scale["tolerance_px"] if self.scale else 0
        left = self.scale["origin_x"] - 2 * self.scale["tolerance_px"] if self.scale else -1e9
        # a lane row or band starts left of the time axis; a bar never does
        # a near-white plate behind a label (no outline) is the label's background, not a bar
        return [s for s in self.m.closed if s["fill"] and 2.0 <= G.height(s["rect"]) <= 44 and G.width(s["rect"]) >= 2.0
                and s["rect"][2] >= x0 and s["rect"][0] >= left and not self.m.is_background(s) and s["tag"] in ("rect", "path", "polygon")
                and not ((G.luminance(s["fill"]) or 0) > 0.85 and not s.get("stroke"))]

    def _marker_candidates(self) -> list[dict]:
        """Glyph markers (small filled shapes, symbol characters) and vertical rules. A rule is a dark, unarrowed,
        vertical stroke at least 30 px long; collinear segments of one rule (broken around labels) are one anchor.
        Faint strokes (grid lines) and arrows are not rules."""
        out = []
        for s in self.m.closed:
            r = s["rect"]
            if s["fill"] and G.width(r) <= 26 and G.height(r) <= 26 and G.area(r) <= 520:
                out.append({"ref": s["ref"], "rect": r, "refs": [s["ref"]], "shape": "glyph", "cid": (s.get("data") or {}).get("data-content-id")})
        for line in self.m.lines:
            if line["text"].strip() and all(ch in SYMBOLS for ch in line["text"].replace(" ", "")) and len(line["text"].strip()) <= 2:
                out.append({"ref": line["ref"], "rect": line["ink"], "refs": [line["text_ref"]], "shape": "glyph"})
        segs = []
        for c in self.m.connectors:
            r = c["rect"]
            if any(c["markers"].values()) or G.width(r) > 1.5 or G.height(r) < 8:
                continue
            if (G.luminance(c.get("stroke")) or 0) > 0.6 or c.get("stroke_px", 1) < 0.75:
                continue
            segs.append(c)
        segs.sort(key=lambda c: (round(G.center(c["rect"])[0], 0), c["rect"][1]))
        rules: list[list[dict]] = []
        for c in segs:
            x = G.center(c["rect"])[0]
            for grp in rules:
                if abs(G.center(grp[0]["rect"])[0] - x) <= 1.0 and ((grp[0].get("data") or {}).get("data-content-id") == (c.get("data") or {}).get("data-content-id")):
                    grp.append(c)
                    break
            else:
                rules.append([c])
        for grp in rules:
            rect = G.union(c["rect"] for c in grp)
            if G.height(rect) >= 30:
                out.append({"ref": grp[0]["ref"], "rect": rect, "refs": [c["ref"] for c in grp], "shape": "rule",
                            "cid": (grp[0].get("data") or {}).get("data-content-id")})
        return out

    def semantic_and_timeline(self) -> None:
        items = self.cl.get("items", [])
        do_sem = "semantic" in self.checks
        do_tl = "timeline" in self.checks
        # 1. text presence for every item with text
        for it in items:
            if not it.get("text"):
                continue
            mapped = (self.mapping.get(it["id"]) or {}).get("label")
            cands = self.find_text(it)
            if mapped:
                mels = [e for e in self.m.resolve(mapped) if e["kind"] == "text"]
                mref = mels[0] if mels else None
                mrefs = {e["ref"] for e in mels}
                ok = mref is not None and any(set(u["refs"]) & mrefs and u["score"] >= self.threshold for u in cands)
                if not ok and do_sem:
                    self.rec.add("semantic", "failed", severity="major", targets=[it["id"], mapped],
                                 message=f"mapping names {mapped} for {it['id']} but that element does not carry the expected text"
                                 + (f" (it reads '{mref['text'][:60]}')" if mref and mref.get("text") else " (element not found)"))
                elif ok:
                    cands.sort(key=lambda u: (not (set(u["refs"]) & mrefs), -u["score"]))
            self.item_units[it["id"]] = cands
            good = [u for u in cands if u["score"] >= self.threshold]
            for u in good[:1]:
                role = it.get("role")
                if role:
                    for r in u["refs"]:
                        self.text_roles.setdefault(r, (role, it["id"]))
            if not do_sem:
                continue
            required = it.get("required", True)
            self.item_presence[it["id"]] = "present" if good else ("partial" if cands else "missing")
            if good:
                u = good[0]
                self.rec.add("semantic", "passed", targets=[it["id"], *u["refs"]], message=f"{it['id']} present ({u['match']})", measured={"score": u["score"], "found": u["text"][:90]},
                             expected=it["text"][:90], tolerance=self.threshold)
            elif cands:
                u = cands[0]
                self.rec.add("semantic", "failed", severity="blocker" if required else "minor", targets=[it["id"], *u["refs"]],
                             message=f"{it['id']} only partly present: missing {u['missing'][:8]} (truncated, abbreviated or reworded beyond the allowed paraphrases)",
                             measured={"score": u["score"], "found": u["text"][:90]}, expected=it["text"][:90], tolerance=self.threshold)
            else:
                self.rec.add("semantic", "failed", severity="blocker" if required else "minor", targets=[it["id"]], message=f"{it['id']} missing: '{it['text'][:60]}'",
                             expected=it["text"][:90])
        # 2. anchors: zones first (nodes are then looked for inside them), then nodes, lanes, texts
        used_units: set = set()
        node_candidates: dict[str, list] = {}
        for it in sorted(items, key=lambda i: 0 if i.get("kind") == "zone" else 1):
            good = [u for u in self.item_units.get(it["id"], []) if u["score"] >= self.threshold]
            mapped = self.mapping.get(it["id"]) or {}
            if it.get("kind") == "zone":
                self._zone_anchor(it, good, mapped)
                continue
            if it.get("kind") == "node" and good:
                node_candidates[it["id"]] = list(good)
                zone = self.item_anchor.get(it.get("inside") or "")
                if zone is not None and zone.get("how", "").startswith("zone"):
                    inside = [u for u in good if G.contains_point(G.inflate(zone["rect"], 2.0), G.center(u["rect"]))]
                    good = inside or good
                fresh = [u for u in good if u["ref"] not in used_units]
                good = fresh or good  # two nodes with the same words (one per region) take different labels
                used_units.add(good[0]["ref"])
            if it.get("kind") in ("node", "zone"):
                ref = mapped.get("node") or mapped.get("element") or it.get("element")
                if ref and self.m.rect_of(ref):
                    self.item_anchor[it["id"]] = {"ref": ref, "rect": self.m.rect_of(ref), "refs": [ref] + (good[0]["refs"] if good else []), "how": "mapping/element"}
                elif good:
                    cont = self.m.container_of(good[0]["rect"])
                    if cont is not None and G.area(cont["rect"]) > 20 * max(G.area(good[0]["rect"]), 1.0):
                        cont = None  # a zone or band around the label, not the node's own box
                    if cont is not None and it.get("kind") == "node":
                        self.item_anchor[it["id"]] = {"ref": cont["ref"], "rect": G.union([cont["rect"], good[0]["rect"]]), "refs": [cont["ref"], *good[0]["refs"]],
                                                      "how": "shape containing the label"}
                    else:
                        self.item_anchor[it["id"]] = {"ref": good[0]["ref"], "rect": good[0]["rect"], "refs": good[0]["refs"], "how": "label only (no enclosing shape)"}
            elif it.get("kind") in ("text", "lane", "legend", "annotation") and good:
                self.item_anchor[it["id"]] = {"ref": good[0]["ref"], "rect": good[0]["rect"], "refs": good[0]["refs"], "how": "label"}
        # 2b. a node drawn more than once (e.g. a tool shown as a read source and again as a write target): every further
        # well-matching label that no other item claimed is an alternate instance; relationships accept any instance.
        claimed = {r for a in self.item_anchor.values() for r in a.get("refs", [])}
        for item_id, units in node_candidates.items():
            primary = self.item_anchor.get(item_id)
            if primary is None:
                continue
            for u in units:
                if any(r in claimed for r in u["refs"]):
                    continue
                cont = self.m.container_of(u["rect"])
                if cont is not None and G.area(cont["rect"]) > 20 * max(G.area(u["rect"]), 1.0):
                    cont = None
                alt = ({"ref": cont["ref"], "rect": G.union([cont["rect"], u["rect"]]), "refs": [cont["ref"], *u["refs"]], "how": "alternate instance (shape containing the label)"}
                       if cont is not None else {"ref": u["ref"], "rect": u["rect"], "refs": u["refs"], "how": "alternate instance (label only)"})
                self.item_alternates.setdefault(item_id, []).append(alt)
                claimed.update(alt["refs"])
        # 3. timeline geometry
        bands = self._lane_bands() if any(it.get("kind") == "lane" for it in items) or (self.req.get("timeline") or {}).get("lane_bands") else {}
        timed = [it for it in items if it.get("kind") == "task" and "start" in it]
        dated = [it for it in items if it.get("kind") in ("milestone", "gate") and "date" in it]
        if (timed or dated) and self.scale is None:
            for it in timed + dated:
                self.rec.add("timeline", "unverified", targets=[it["id"]], reason="no declared time scale in the request (timeline.scale)", message=f"{it['id']} date position not checked")
        if self.scale is not None and (timed or dated):
            self._place_bars(timed, bands, do_tl)
            self._place_markers(dated, do_tl)
            self._ticks(do_tl)
        # 4. placement of labels
        if do_sem:
            for it in items:
                self._placement(it)
        # 5. relationships
        for it in items:
            if it.get("kind") in ("relationship", "dependency"):
                src, dst = self._resolve_refs(it.get("from")), self._resolve_refs(it.get("to"))
                if "connectors" in self.checks or do_sem:
                    self._relationship(it["id"], src, dst, directed=it.get("directed", True), style=it.get("style"), label=it.get("label"),
                                       element=(self.mapping.get(it["id"]) or {}).get("connector"), source="checklist", item=it)
            if it.get("kind") == "legend" and do_sem:
                self._legend(it)
            if it.get("kind") in ("node",) and it.get("inside") and do_sem:
                self._inside(it)

    def _column_candidates(self) -> list[dict]:
        """Tall filled or outlined columns across the lanes (a holiday window, a float week)."""
        left = self.scale["origin_x"] - 2 * self.scale["tolerance_px"]
        return [s for s in self.m.closed if G.height(s["rect"]) > 44 and s["rect"][0] >= left and not self.m.is_background(s)
                and G.width(s["rect"]) < 0.5 * self.m.W and s["tag"] in ("rect", "path", "polygon")]

    def _place_bars(self, timed: list[dict], bands: dict, record: bool) -> None:
        sc = self.scale
        cands = self._bar_candidates()
        columns = self._column_candidates()
        pairs = []
        for it in timed:
            ex0, ex1 = self.x_of(it["start"], "start"), self.x_of(it["end"], "end")
            mapped = self._mapped(it["id"], "bar")
            if mapped is not None:
                pairs.append((0.0, it, mapped, ex0, ex1, "mapping"))
                continue
            band = bands.get(it.get("lane")) if it.get("lane") else None
            for c in (cands if it.get("lane") else cands + columns):
                cy = G.center(c["rect"])[1]
                if band and not (band[0] <= cy <= band[1]):
                    continue
                if c["rect"][2] < ex0 - 4 * sc["tolerance_px"] or c["rect"][0] > ex1 + 4 * sc["tolerance_px"]:
                    continue
                score = abs(c["rect"][0] - ex0) + abs(c["rect"][2] - ex1)
                pairs.append((score, it, c, ex0, ex1, "geometry search in lane band" if band else "geometry search (no lane band)"))
        pairs.sort(key=lambda p: p[0])
        used_items, used_bars = set(), set()
        for score, it, c, ex0, ex1, how in pairs:
            if it["id"] in used_items or (how != "mapping" and c["ref"] in used_bars):
                continue
            used_items.add(it["id"])
            used_bars.add(c["ref"])
            self.item_anchor[it["id"]] = {"ref": c["ref"], "rect": c["rect"], "refs": [c["ref"]], "how": how}
            e0 = (c["rect"][0] - ex0) / sc["px_per_unit"]
            e1 = (c["rect"][2] - ex1) / sc["px_per_unit"]
            ok = abs(e0) <= sc["tolerance_units"] and abs(e1) <= sc["tolerance_units"]
            if record:
                self.rec.add("timeline", "passed" if ok else "failed", severity="blocker", targets=[it["id"], c["ref"]],
                             certainty="measured" if how == "mapping" else "measured; element chosen by geometry search",
                             measured={"x0": c["rect"][0], "x1": c["rect"][2], "start_error": e0, "end_error": e1}, expected={"x0": ex0, "x1": ex1},
                             tolerance=sc["tolerance_units"], units=sc["unit"] + "s", located_by=how,
                             message=f"{it['id']} bar {'matches' if ok else 'does not match'} its dates ({it['start']}..{it['end']}): start {e0:+.2f}, end {e1:+.2f} {sc['unit']}s")
        for it in timed:
            if it["id"] not in used_items and record:
                self.rec.add("timeline", "failed", severity="blocker", targets=[it["id"]], expected={"x0": self.x_of(it["start"], "start"), "x1": self.x_of(it["end"], "end")},
                             message=f"{it['id']}: no bar found at {it['start']}..{it['end']}" + (f" in lane {it.get('lane')}" if it.get("lane") else ""),
                             certainty="geometry search; a bar drawn far from its dates or outside its lane is reported here")

    def _place_markers(self, dated: list[dict], record: bool) -> None:
        sc = self.scale
        cands = self._marker_candidates()
        band = (self.req.get("timeline") or {}).get("marker_band")
        if band:
            cands = [c for c in cands if (c["shape"] == "glyph" and band[0] <= G.center(c["rect"])[1] <= band[1])
                     or (c["shape"] != "glyph" and c["rect"][1] <= band[1] and c["rect"][3] >= band[0])]
        pairs = []
        for it in dated:
            anchor = it.get("anchor", sc["milestone_anchor"])
            ex = self.x_of(it["date"], anchor)
            mapped = self._mapped(it["id"], "marker")
            if mapped is not None:
                pairs.append((0.0, it, mapped, ex, "mapping"))
                continue
            prefer = "rule" if it.get("kind") == "gate" else "glyph"  # a decision is usually a rule, an event a glyph
            for c in cands:
                d = abs(G.center(c["rect"])[0] - ex)
                pairs.append((d + (0.0 if c["shape"] == prefer else 0.25 * sc["tolerance_px"]), it, c, ex,
                              f"geometry search (nearest free {c['shape']})"))
        pairs.sort(key=lambda p: p[0])
        used_i, used_m = set(), set()
        for d, it, c, ex, how in pairs:
            if it["id"] in used_i or (how != "mapping" and c["ref"] in used_m):
                continue
            used_i.add(it["id"])
            used_m.add(c["ref"])
            rect, refs = c["rect"], list(c.get("refs", [c["ref"]]))
            if how != "mapping":
                # a glyph and the rule or tether it touches at the same x are one drawing of the event
                grown = True
                while grown:
                    grown = False
                    for o in cands:
                        if o["ref"] in refs or abs(G.center(o["rect"])[0] - G.center(rect)[0]) > 1.5:
                            continue
                        if c.get("cid") and o.get("cid") and c["cid"] != o["cid"]:
                            continue  # the author says these are different events that share a date
                        if max(o["rect"][1] - rect[3], rect[1] - o["rect"][3]) <= 10.0:
                            rect = G.union([rect, o["rect"]])
                            refs += [r for r in o.get("refs", [o["ref"]]) if r not in refs]
                            grown = True
            self.item_anchor[it["id"]] = {"ref": c["ref"], "rect": rect, "core": c["rect"], "refs": refs, "how": how}
            err = (G.center(c["rect"])[0] - ex) / sc["px_per_unit"]
            ok = abs(err) <= sc["tolerance_units"]
            window = it.get("accept_error_range")  # e.g. an event valid anywhere in its week: [-1.0, 0.5] units around `date`
            if isinstance(window, (list, tuple)) and len(window) == 2:
                ok = float(window[0]) - 1e-6 <= err <= float(window[1]) + 1e-6
            if record:
                self.rec.add("timeline", "passed" if ok else "failed", severity="blocker", targets=[it["id"], c["ref"]], located_by=how,
                             certainty="measured" if how == "mapping" else "measured; marker chosen by geometry search",
                             measured={"x": G.center(c["rect"])[0], "error": err}, expected={"x": ex}, tolerance=sc["tolerance_units"], units=sc["unit"] + "s",
                             message=f"{it['id']} marker {'at' if ok else 'not at'} {it['date']} ({err:+.2f} {sc['unit']}s)")
        for it in dated:
            if it["id"] not in used_i and record:
                self.rec.add("timeline", "failed", severity="blocker", targets=[it["id"]], message=f"{it['id']}: no marker found for {it['date']}")

    def _ticks(self, record: bool) -> None:
        spec = (self.req.get("timeline") or {}).get("ticks")
        if not spec or not record:
            return
        pat = re.compile(spec["pattern"])
        band = spec.get("band")
        anchor = spec.get("anchor", "start")
        n_ok = n = 0
        worst = None
        for line in self.m.lines:
            mm = pat.fullmatch(line["text"].strip())
            if not mm:
                continue
            if band and not (band[0] <= G.center(line["rect"])[1] <= band[1]):
                continue
            value = float(mm.group(1))
            ex = self.x_of(value, anchor)
            err = (G.center(line["rect"])[0] - ex) / self.scale["px_per_unit"]
            n += 1
            if abs(err) <= self.scale["tolerance_units"]:
                n_ok += 1
            if worst is None or abs(err) > abs(worst[1]):
                worst = (line["ref"], err, line["text"])
        if n == 0:
            self.rec.add("timeline", "unverified", targets=[], reason=f"no tick labels matched {spec['pattern']}", message="ruler ticks not found")
            return
        self.rec.add("timeline", "passed" if n_ok == n else "failed", severity="major", targets=[worst[0]] if worst else [],
                     measured={"ticks": n, "consistent": n_ok, "worst_error": worst[1] if worst else None, "worst_label": worst[2] if worst else None},
                     tolerance=self.scale["tolerance_units"], units=self.scale["unit"] + "s",
                     message=f"ruler tick labels {'agree' if n_ok == n else 'disagree'} with the declared scale ({n_ok}/{n} within tolerance, anchor {anchor})")

    def _placement(self, it: dict) -> None:
        kind = it.get("kind")
        good = [u for u in self.item_units.get(it["id"], []) if u["score"] >= self.threshold]
        if not good or it.get("placement") == "none":
            return
        if it.get("region"):
            x, y, w, h = it["region"]
            region = [x, y, x + w, y + h]
            inside = [u for u in good if G.contains_point(region, G.center(u["rect"]))]
            self.rec.add("semantic", "passed" if inside else "failed", severity="blocker", targets=[it["id"], *(inside or good)[0]["refs"]],
                         measured=(inside or good)[0]["rect"], expected={"region": region}, units="px",
                         message=f"{it['id']} {'in' if inside else 'outside'} its required region")
        if kind == "task":
            anchor = self.item_anchor.get(it["id"])
            if anchor is None:
                self.rec.add("semantic", "unverified", targets=[it["id"]], reason="its bar was not located", message=f"{it['id']} label placement not checked")
                return
            gap = float(it.get("max_gap_px", self.req.get("label_gap_px", 16.0)))
            # a tall column (a window spanning the lanes) is a backdrop, not a rival bar for other labels
            bars = [a for k, a in self.item_anchor.items() if self.items.get(k, {}).get("kind") == "task" and G.height(a["rect"]) <= 44]
            others = self._bar_candidates()
            best = None
            for u in good:
                d = G.dist_rect_rect(u["rect"], anchor["rect"])
                lead_used = False
                if d > gap:
                    lead = self._leader_gap(u["rect"], anchor["rect"], gap)
                    if lead is not None:
                        d, lead_used = lead, True
                own = _row_key(u["rect"], anchor["rect"])
                rivals = [a for a in bars if a is not anchor]
                rivals += [{"ref": c["ref"], "rect": c["rect"]} for c in others if c["ref"] != anchor["ref"] and all(c["ref"] != a["ref"] for a in bars)]
                nearest = min(rivals, key=lambda a: _row_key(u["rect"], a["rect"]), default=None)
                beaten = nearest is not None and _row_key(u["rect"], nearest["rect"]) < own - 0.5 and not _self_dated(u["text"], it)
                ok = (d <= gap or lead_used) and not beaten
                if best is None or (ok, -d) > (best[0], -best[1]):
                    best = (ok, d, u, nearest if beaten else anchor, lead_used)
            ok, d, u, nearest, lead_used = best
            msg = (f"{it['id']} label on or beside its bar ({d:.1f} px" + (", through a leader line)" if lead_used else ")") if ok else
                   f"{it['id']} label is {d:.0f} px from its bar" + ("" if nearest is anchor else f" and nearer to another bar ({nearest['ref']})") +
                   ": a name kept elsewhere (rail, key, legend) does not label the bar in place")
            self.rec.add("semantic", "passed" if ok else "failed", severity="blocker", targets=[it["id"], anchor["ref"], *u["refs"]], measured=d, tolerance=gap, units="px", message=msg)
        elif kind in ("milestone", "gate"):
            anchor = self.item_anchor.get(it["id"])
            if anchor is None:
                self.rec.add("semantic", "unverified", targets=[it["id"]], reason="its marker was not located", message=f"{it['id']} label placement not checked")
                return
            gap = float(it.get("max_gap_px", self.req.get("milestone_label_gap_px", 48.0)))
            markers = [a for k, a in self.item_anchor.items() if self.items.get(k, {}).get("kind") in ("milestone", "gate")]
            best = None
            def key(label, a):  # the marker glyph decides the row; its rule or tether may be nearer
                return min(_col_key(label, a.get("core", a["rect"])), _col_key(label, a["rect"]))
            for u in good:
                d = G.dist_rect_rect(u["rect"], anchor["rect"])
                nearest = min(markers, key=lambda a: key(u["rect"], a))
                own_key = key(u["rect"], anchor)
                ok = d <= gap and (nearest is anchor or _self_dated(u["text"], it) or key(u["rect"], nearest) >= own_key - 0.5)
                if best is None or (ok, -d) > (best[0], -best[1]):
                    best = (ok, d, u, nearest)
            ok, d, u, nearest = best
            self.rec.add("semantic", "passed" if ok else "failed", severity="blocker", targets=[it["id"], anchor["ref"], *u["refs"]], measured=d, tolerance=gap, units="px",
                         message=(f"{it['id']} name at its marker ({d:.1f} px)" if ok else f"{it['id']} name is {d:.0f} px from its marker" +
                                  ("" if nearest is anchor else f" and nearer to {nearest['ref']}")))
            if it.get("meaning"):
                mc = self.find_text(it, "meaning")
                mgood = [m for m in mc if m["score"] >= self.threshold]
                if not mgood:
                    part = mc[0] if mc else None
                    self.rec.add("semantic", "failed", severity="blocker", targets=[it["id"]] + (part["refs"] if part else []),
                                 message=f"{it['id']} meaning missing or truncated: '{it['meaning'][:60]}'" + (f" (best: '{part['text'][:50]}', missing {part['missing'][:6]})" if part else ""))
                else:
                    md = [(G.dist_rect_rect(m["rect"], anchor["rect"]), m) for m in mgood]
                    md.sort(key=lambda x: x[0])
                    d2, m2 = md[0]
                    same_block = any(set(m2["refs"]) & set(u2["refs"]) for u2 in good)
                    ok2 = d2 <= gap or same_block
                    self.rec.add("semantic", "passed" if ok2 else "failed", severity="blocker", targets=[it["id"], anchor["ref"], *m2["refs"]], measured=d2, tolerance=gap, units="px",
                                 message=(f"{it['id']} meaning at its marker" if ok2 else f"{it['id']} meaning is written {d2:.0f} px away from its marker (restated elsewhere, not at the time point)"))
        elif it.get("near"):
            anchor = self._resolve_refs(it["near"])
            if not anchor:
                self.rec.add("semantic", "unverified", targets=[it["id"], str(it["near"])], reason="anchor not located", message=f"{it['id']} placement not checked")
                return
            gap = float(it.get("max_gap_px", 12.0))
            d, u = min(((min(G.dist_rect_rect(u["rect"], a["rect"]) for a in anchor), u) for u in good), key=lambda x: x[0])
            leader = None
            if d > gap:  # a leader line from the note to (one of) its anchors attaches it as well
                reach = float(it.get("leader_reach_px", 12.0))
                for c in self.m.connectors:
                    ends = (c["points"][0], c["points"][-1])
                    for a_end, b_end in ((ends[0], ends[1]), (ends[1], ends[0])):
                        if any(G.dist_point_rect(a_end, g["rect"]) <= reach for g in good) and                                 any(G.dist_point_rect(b_end, a["rect"]) <= reach for a in anchor):
                            leader = c["ref"]
                            break
                    if leader:
                        break
            keyed = None
            if d > gap and leader is None:  # a numbered key: the same number beside the note and on (or beside) its anchor
                reach = float(it.get("key_reach_px", 16.0))
                numerals = [ln for ln in self.m.lines if re.fullmatch(r"\s*\(?\d{1,2}[.)]?\s*", ln.get("text") or "")]
                def digits(ln: dict) -> str:
                    return re.sub(r"\D", "", ln["text"])
                at_anchor = {digits(ln) for ln in numerals if any(G.dist_rect_rect(ln["rect"], a["rect"]) <= reach for a in anchor)}
                at_note = {digits(ln) for ln in numerals if any(G.dist_rect_rect(ln["rect"], g["rect"]) <= reach for g in good)}
                lead = {m.group(1) for g in good for m in [re.match(r"\s*\(?(\d{1,2})[.)]?\s", g.get("text") or "")] if m}
                common = at_anchor & (at_note | lead)
                if common:
                    keyed = sorted(common)[0]
            ok = d <= gap or leader is not None or keyed is not None
            self.rec.add("semantic", "passed" if ok else "failed", severity=it.get("placement_severity", "blocker"),
                         targets=[it["id"], *u["refs"], *[a["ref"] for a in anchor]], measured=d, tolerance=gap,
                         units="px", message=(f"{it['id']} joined to {it['near']} by leader {leader}" if leader else
                                              f"{it['id']} keyed to {it['near']} by number {keyed}" if keyed else
                                              f"{it['id']} {'beside' if d <= gap else 'away from'} {it['near']} ({d:.1f} px)"))

    def _legend(self, it: dict) -> None:
        good = [u for u in self.item_units.get(it["id"], []) if u["score"] >= self.threshold]
        if not good:
            return
        u = good[0]
        text_el = self.m.by_ref.get(u["refs"][0])
        swatch_color = swatch_ref = style = None
        how = None
        if text_el is not None:
            first_run = text_el["visible_runs"][0]
            lead = first_run["text"].lstrip()[:1]
            if lead in SYMBOLS:
                swatch_color, swatch_ref, how = first_run["fill"], text_el["ref"], f"leading glyph '{lead}' in the legend text"
        if swatch_color is None:
            r = u["rect"]
            best = None
            for s in self.m.shapes:
                sr = s["rect"]
                if sr[2] > r[0] + 2 or r[0] - sr[2] > 40:
                    continue
                if G.center(sr)[1] < r[1] - 4 or G.center(sr)[1] > r[3] + 4:
                    continue
                if G.area(sr) > 1600:
                    continue
                d = r[0] - sr[2]
                if best is None or d < best[0]:
                    best = (d, s)
            if best:
                s = best[1]
                swatch_color = s["fill"] or s["stroke"]
                swatch_ref = s["ref"]
                style = "dashed" if s.get("dashed") else "solid"
                how = f"nearest small shape left of the text ({best[0]:.1f} px)"
        if swatch_color is None:
            self.rec.add("semantic", "unverified", targets=[it["id"], *u["refs"]], reason="no swatch found (no leading glyph, no small shape within 40 px to the left)",
                         message=f"{it['id']} legend swatch not located")
            return
        if it.get("symbol_color"):
            dist = G.color_distance(swatch_color, it["symbol_color"])
            ok = dist is not None and dist <= float(it.get("color_tolerance", 60.0))
            self.rec.add("semantic", "passed" if ok else "failed", severity="major", targets=[it["id"], swatch_ref], located_by=how,
                         measured={"swatch": G.hex_of(swatch_color), "rgb_distance": dist}, expected=it["symbol_color"], tolerance=it.get("color_tolerance", 60.0),
                         units="RGB euclidean", message=f"{it['id']} legend swatch colour {G.hex_of(swatch_color)} {'agrees with' if ok else 'contradicts'} its stated meaning ({it['symbol_color']})")
        if it.get("symbol_style") and style is not None:
            ok = style == it["symbol_style"]
            self.rec.add("semantic", "passed" if ok else "failed", severity="major", targets=[it["id"], swatch_ref], measured=style, expected=it["symbol_style"],
                         message=f"{it['id']} legend line style {style}")
        for target in it.get("applies_to") or []:
            anchor = self._resolve_refs(target)
            el = self.m.by_ref.get(anchor[0]["ref"]) if anchor else None
            if el is None or el.get("kind") != "shape":
                self.rec.add("semantic", "unverified", targets=[it["id"], target], reason="styled element not located", message="legend-to-style agreement not checked")
                continue
            dist = G.color_distance(el.get("fill") or el.get("stroke"), it.get("symbol_color") or swatch_color)
            ok = dist is not None and dist <= float(it.get("color_tolerance", 60.0))
            self.rec.add("semantic", "passed" if ok else "failed", severity="major", targets=[it["id"], el["ref"]], measured={"element_colour": G.hex_of(el.get("fill") or el.get("stroke")), "rgb_distance": dist},
                         expected=it.get("symbol_color") or G.hex_of(swatch_color), units="RGB euclidean", message=f"{it['id']} legend {'agrees' if ok else 'disagrees'} with the style of {target}")

    def _zone_anchor(self, it: dict, good: list[dict], mapped: dict) -> None:
        """A zone's boundary: the declared or mapped element; else the author's group whose id or data-content-id
        names the zone; else the smallest closed shape that contains the zone's label with room for content.
        A zone whose boundary cannot be resolved gets no anchor, so its containment checks are unverified."""
        ref = mapped.get("node") or mapped.get("element") or it.get("element")
        if ref and self.m.rect_of(ref) is not None:
            self.item_anchor[it["id"]] = {"ref": ref, "rect": self.m.rect_of(ref), "refs": [ref], "how": "zone: mapping/element"}
            return
        label = good[0]["rect"] if good else None
        keys = {it["id"].casefold(), it["id"].split("-")[-1].casefold()}
        if it.get("text"):
            keys.add(re.sub(r"[^a-z0-9]+", "-", norm(it["text"])).strip("-"))
        for g in self.m.groups:
            names = {(g.get("id") or "").casefold(), ((g.get("data") or {}).get("data-content-id") or "").casefold()}
            if not (keys & names):
                continue
            inner = [s for s in self.m.closed if g["id"] in s.get("ancestors", ()) and (label is None or G.contains_rect(s["rect"], label, 2.0))]
            shape = max(inner, key=lambda s: G.area(s["rect"])) if inner else None
            self.item_anchor[it["id"]] = {"ref": shape["ref"] if shape else g["ref"], "rect": shape["rect"] if shape else g["rect"],
                                          "refs": [shape["ref"] if shape else g["ref"]], "how": "zone: author group " + g["id"]}
            return
        if label is None:
            return
        cands = [s for s in self.m.closed if G.contains_rect(s["rect"], label, 2.0) and not self.m.is_background(s)
                 and s["tag"] in ("rect", "path", "polygon") and G.area(s["rect"]) >= 3 * G.area(label)
                 and any(o is not s and G.contains_rect(s["rect"], o["rect"], 2.0) and G.area(o["rect"]) >= 200 for o in self.m.closed)]
        if cands:
            shape = min(cands, key=lambda s: G.area(s["rect"]))
            self.item_anchor[it["id"]] = {"ref": shape["ref"], "rect": shape["rect"], "refs": [shape["ref"], *good[0]["refs"]],
                                          "how": "zone: smallest boundary shape around its label"}

    def _inside(self, it: dict) -> None:
        node = self.item_anchor.get(it["id"])
        zone_item = self.item_anchor.get(it["inside"]) if isinstance(it["inside"], str) else None
        zone = [zone_item] if zone_item is not None else ([] if isinstance(it["inside"], str) and it["inside"] in self.items else self._resolve_refs(it["inside"]))
        if node is None or not zone:
            why = "node not located" if node is None else "zone boundary shape not resolved (no element, mapping, matching group or enclosing shape)"
            self.rec.add("semantic", "unverified", targets=[it["id"], str(it["inside"])], reason=why, message=f"{it['id']} containment not checked")
            return
        tol = float(self.req.get("containment_tolerance_px", 2.0))
        ov = G.overflow(zone[0]["rect"], node["rect"])
        ok = max(ov.values()) <= tol
        self.rec.add("semantic", "passed" if ok else "failed", severity="blocker", targets=[it["id"], node["ref"], zone[0]["ref"]], measured=ov, tolerance=tol, units="px",
                     located_by=zone[0].get("how"), message=f"{it['id']} {'inside' if ok else 'not inside'} {it['inside']}")
