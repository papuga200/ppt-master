#!/usr/bin/env python3
"""Put text inside the shapes it sits on, the way a person builds a slide.

The SVG exporter writes every label as its own non-wrapping text box laid over a rectangle. The
slide looks right and edits badly: a word changed does not reflow, a card moved leaves its text
behind, a three-line paragraph is three boxes. This pass runs on the exported .pptx and changes
structure only - nothing should move on the rendered slide:

    pptx_text_in_shapes.py <deck.pptx> [-o out.pptx | --in-place] [--report report.json]
    pptx_text_in_shapes.py --verify <before.render dir> <after.render dir>

1. Adoption. A text box goes into the smallest shape that contains it and is painted beneath it:
   its paragraphs move into that shape's own text frame, insets reproduce where the text sat,
   paragraph spacing reproduces the gaps, and word-wrap is on so an edit reflows inside the box.
2. Stacks. Text boxes left over that are one block (same edge, same alignment, stacked with
   ordinary gaps) become one multi-paragraph text box.
3. Hand-broken lines of one paragraph reflow as one wrapped paragraph when PowerPoint's own
   wrapping would break at the same words; otherwise the breaks stay.

Left alone, and counted in the report with the reason: text that no shape contains (titles, labels
on connectors, a bar label running past its bar), rotated or flipped objects, scaled groups,
shapes holding side-by-side columns of text (one frame cannot hold two columns), text with another
painted object between it and its shape, hyperlinked boxes, slides with animation timing, and
preset shapes whose text rectangle is not their bounds unless the text is centred in them.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

from lxml import etree

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": A, "p": P}
PX = 9525  # EMU per SVG pixel at 96 dpi
# Measured in PowerPoint (calibration deck, 20 Sep 2026; Segoe UI, Arial, Calibri, YaHei, Georgia, Times, Aptos, Verdana, Tahoma at 9-21 pt):
# a line at single spacing is 1.2 x the font size tall whatever the font, a line with exact spacing is that spacing tall, and lines stack.
# Within its line the top of the capitals sits 0.25 x size below the line top at single spacing, and 0.8 x spacing - 0.75 x size below it at
# exact spacing (the baseline is at 80% of an exact line). Paragraph spacing keeps whole points only, and an exact line spacing is drawn
# at the nearest whole point. So a paragraph keeps its place in a
# merged frame when its line top is kept, and a single line turned into an exact-spaced one keeps its glyphs when its line top moves to
# top + size - 0.8 x spacing.
LINE_RATIO = 1.2
EXACT_BOUNDS_PRESETS = {"rect"}  # text rectangle == bounds, so insets are exact
# presets whose text area is symmetric about the shape's centre: a label centred on the shape is centred in the text area too
CENTRED_ONLY_PRESETS = {"roundRect", "ellipse", "round2SameRect", "round2DiagRect", "snip2SameRect", "flowChartProcess", "flowChartAlternateProcess",
                        "chevron", "hexagon", "octagon", "diamond", "parallelogram", "plaque", "flowChartTerminator", "flowChartDecision"}


class Fonts:
    """Real advance widths from the installed font files. The exporter's own width estimates run up to a quarter too wide (bold Segoe UI),
    which is harmless for a box that never wraps and useless for predicting where PowerPoint will break a line."""

    _index: dict | None = None

    def __init__(self, archive: zipfile.ZipFile):
        self.minor = self.major = "Arial"
        try:
            theme = etree.fromstring(archive.read("ppt/theme/theme1.xml"))
            self.minor = theme.find(".//a:fontScheme/a:minorFont/a:latin", NS).get("typeface") or self.minor
            self.major = theme.find(".//a:fontScheme/a:majorFont/a:latin", NS).get("typeface") or self.major
        except Exception:  # noqa: BLE001
            pass
        self.cache: dict = {}
        self.ok = self._build_index()

    @classmethod
    def _build_index(cls) -> bool:
        if cls._index is not None:
            return bool(cls._index)
        cls._index = {}
        try:
            from PIL import ImageFont
        except Exception:  # noqa: BLE001
            return False
        import os
        folders = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts", Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
                   Path("/usr/share/fonts"), Path("/Library/Fonts"), Path("/System/Library/Fonts")]
        for folder in folders:
            if not folder.is_dir():
                continue
            for file in folder.rglob("*"):
                if file.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                    continue
                for face in range(4 if file.suffix.lower() == ".ttc" else 1):
                    try:
                        family, style = ImageFont.truetype(str(file), 10, index=face).getname()
                    except Exception:  # noqa: BLE001
                        break
                    style = (style or "Regular").lower()
                    cls._index.setdefault((family.lower(), "bold" in style and "semi" not in style, "italic" in style or "oblique" in style), (str(file), face))
                    cls._index.setdefault((f"{family} {style}".lower(), False, False), (str(file), face))
        return bool(cls._index)

    def _font(self, face: str, bold: bool, italic: bool, px: float):
        from PIL import ImageFont
        key = (face.lower(), bold, italic, round(px * 4))
        if key not in self.cache:
            found = (self._index.get((face.lower(), bold, italic)) or self._index.get((face.lower(), bold, False))
                     or self._index.get((face.lower(), False, False)))
            self.cache[key] = ImageFont.truetype(found[0], size=64, index=found[1]) if found else None
        return self.cache[key]

    def width(self, run) -> float | None:
        """Advance width of one run in EMU, or None when its font is not installed here."""
        props = run.find("a:rPr", NS)
        text = "".join(run.find("a:t", NS).itertext()) if run.find("a:t", NS) is not None else ""
        if props is None or not text:
            return 0.0 if not text else None
        latin = props.find("a:latin", NS)
        face = latin.get("typeface") if latin is not None else "+mn-lt"
        face = {"+mn-lt": self.minor, "+mj-lt": self.major}.get(face, face)
        px = int(props.get("sz") or 1800) / 100 * 96 / 72
        font = self._font(face, props.get("b") == "1", props.get("i") == "1", px) if self.ok else None
        if font is None:
            return None
        spacing = int(props.get("spc") or 0) / 100 * 96 / 72 * len(text)
        return (font.getlength(text) * px / 64 + spacing) * PX


def q(tag: str) -> str:
    prefix, name = tag.split(":")
    return f"{{{NS[prefix]}}}{name}"


class Item:
    def __init__(self, el, parent, z, box, scaled):
        self.el, self.parent, self.z, self.box, self.scaled = el, parent, z, box, scaled  # box: l, t, r, b in absolute EMU
        self.tag = etree.QName(el).localname
        self.is_text = self.tag == "sp" and el.find("p:nvSpPr/p:cNvSpPr", NS) is not None and el.find("p:nvSpPr/p:cNvSpPr", NS).get("txBox") == "1"
        xfrm = el.find("p:spPr/a:xfrm", NS)
        self.turned = xfrm is not None and any(xfrm.get(k) not in (None, "0") for k in ("rot", "flipH", "flipV"))

    @property
    def area(self):
        return max(0, self.box[2] - self.box[0]) * max(0, self.box[3] - self.box[1])


def walk(tree, transform=(1.0, 0.0, 1.0, 0.0), scaled=False, out=None, parent=None):
    """Every drawable under spTree in paint order, with absolute boxes through the group transforms."""
    out = [] if out is None else out
    parent = tree if parent is None else parent
    sx, ox, sy, oy = transform
    for el in parent:
        name = etree.QName(el).localname
        if name == "grpSp":
            xfrm = el.find("p:grpSpPr/a:xfrm", NS)
            child, turned = transform, scaled
            if xfrm is not None and xfrm.find("a:chExt", NS) is not None:
                off, ext, choff, chext = (xfrm.find(f"a:{k}", NS) for k in ("off", "ext", "chOff", "chExt"))
                gx = int(ext.get("cx")) / max(int(chext.get("cx")), 1)
                gy = int(ext.get("cy")) / max(int(chext.get("cy")), 1)
                child = (sx * gx, ox + sx * (int(off.get("x")) - gx * int(choff.get("x"))), sy * gy, oy + sy * (int(off.get("y")) - gy * int(choff.get("y"))))
                turned = scaled or abs(gx - 1) > 0.002 or abs(gy - 1) > 0.002 or any(xfrm.get(k) not in (None, "0") for k in ("rot", "flipH", "flipV"))
            walk(tree, child, turned, out, el)
        elif name in ("sp", "pic", "cxnSp", "graphicFrame"):
            xfrm = el.find(".//a:xfrm", NS) if name != "graphicFrame" else el.find("p:xfrm", NS)
            if xfrm is None or xfrm.find("a:off", NS) is None:
                continue
            off, ext = xfrm.find("a:off", NS), xfrm.find("a:ext", NS)
            left, top = ox + sx * int(off.get("x")), oy + sy * int(off.get("y"))
            out.append(Item(el, parent, len(out), (left, top, left + sx * int(ext.get("cx")), top + sy * int(ext.get("cy"))), scaled))
    return out


def painted(item: Item) -> bool:
    if item.tag != "sp":
        return True
    sppr = item.el.find("p:spPr", NS)
    fill = sppr.find("a:noFill", NS) is None and any(sppr.find(f"a:{k}", NS) is not None for k in ("solidFill", "gradFill", "pattFill", "blipFill"))
    line = sppr.find("a:ln", NS)
    stroked = line is not None and line.find("a:noFill", NS) is None and any(line.find(f"a:{k}", NS) is not None for k in ("solidFill", "gradFill"))
    return fill or stroked


def host_kind(item: Item, slide_area: float) -> str | None:
    """'exact' when insets from the bounds are exact, 'centred' when only centred text may go in, None when not a host."""
    if item.tag != "sp" or item.is_text or item.turned or item.scaled or not painted(item):
        return None
    width, height = item.box[2] - item.box[0], item.box[3] - item.box[1]
    if width < 18 * PX or height < 9 * PX or item.area > 0.30 * slide_area:
        return None
    body = item.el.find("p:txBody", NS)
    if body is not None and "".join(body.itertext()).strip():
        return None
    if item.el.find("p:nvSpPr/p:nvPr/p:ph", NS) is not None:
        return None
    preset = item.el.find("p:spPr/a:prstGeom", NS)
    if preset is not None:
        name = preset.get("prst")
        return "exact" if name in EXACT_BOUNDS_PRESETS else "centred" if name in CENTRED_ONLY_PRESETS else None
    custom = item.el.find("p:spPr/a:custGeom", NS)
    if custom is not None:
        rect = custom.find("a:rect", NS)
        full = rect is not None and (rect.get("l"), rect.get("t"), rect.get("r"), rect.get("b")) == ("l", "t", "r", "b")
        return "exact" if full else None  # the exporter declares a drawn shape's text area as its bounds, so insets from the bounds are exact
    return None


class Para:
    def __init__(self, el, ratio):
        self.el = el
        sizes = [int(r.get("sz")) for r in el.iter(q("a:rPr")) if r.get("sz")] or [1800]
        self.size = max(sizes) * 127  # EMU
        self.lines = len(el.findall("a:br", NS)) + 1
        exact = el.find("a:pPr/a:lnSpc/a:spcPts", NS)
        # PowerPoint sets an exact line spacing to the NEAREST WHOLE POINT (12.75 pt is drawn as 13, 12.4 as 12 - measured over ten-line spans)
        self.pitch = float(int(int(exact.get("val")) / 100 + 0.5) * 12700) if exact is not None else self.size * ratio
        self.height = self.pitch * self.lines
        ppr = el.find("a:pPr", NS)
        self.align = (ppr.get("algn") if ppr is not None else None) or "l"
        self.chars = [len(part) for part in self._line_texts()]
        self.joins: list[tuple] = []  # (br element, width at which PowerPoint would pull the next line's first word up)
        self.real_width = None  # widest line, measured from the font file

    def prepare_breaks(self, fonts) -> None:
        """Measure every line; for each break, the width a frame must stay under for that break to fall where the author put it."""
        self.joins, self.real_width = [], None
        if fonts is None or not fonts.ok:
            return
        lines, current = [], []
        for node in self.el:
            name = etree.QName(node).localname
            if name == "br":
                lines.append((current, node))
                current = []
            elif name in ("r", "fld"):
                current.append(node)
        lines.append((current, None))
        widths = []
        for runs, _ in lines:
            parts = [fonts.width(run) for run in runs]
            if any(part is None for part in parts):
                return
            widths.append(sum(parts))
        self.real_width = max(widths) if widths else None
        for index, (runs, br) in enumerate(lines[:-1]):
            following = lines[index + 1][0]
            if not following:
                continue
            head = following[0]
            text = "".join(head.find("a:t", NS).itertext()) if head.find("a:t", NS) is not None else ""
            word = re.split(r"(?<=[-–—/])|\s+", text.lstrip())[0]  # PowerPoint also breaks after a hyphen, a dash or a slash
            whole = fonts.width(head)
            share = (len(word) + 1) / max(len(text), 1)
            self.joins.append((br, widths[index] + (whole or 0) * min(1.0, share)))

    def signature(self):
        run = self.el.find("a:r/a:rPr", NS)
        if run is None:
            return None
        fill = run.find("a:solidFill", NS)
        return (run.get("sz"), run.get("b") or "0", run.get("i") or "0", etree.tostring(fill) if fill is not None else b"")

    def text(self) -> str:
        return "".join(self.el.itertext()).strip()

    def settle_joins(self, frame_width) -> int:
        """A joined line break becomes a space where PowerPoint's own wrapping at this width breaks at the same word; else the break stays."""
        freed = 0
        for br, need in self.joins:
            if frame_width is None or need * 0.97 <= frame_width:
                continue  # the next line's first word would be pulled up: keep the author's break
            previous = br.getprevious()
            node = previous.find("a:t", NS) if previous is not None else None
            if node is not None and node.text and not node.text.endswith((" ", "-", "\u2013", "/")):
                node.text += " "
            self.el.remove(br)
            freed += 1
        self.joins = []
        return freed

    def _line_texts(self):
        lines, current = [], ""
        for node in self.el:
            name = etree.QName(node).localname
            if name == "br":
                lines.append(current)
                current = ""
            elif name in ("r", "fld"):
                current += "".join(node.find("a:t", NS).itertext()) if node.find("a:t", NS) is not None else ""
        return lines + [current]

    def ppr(self):
        found = self.el.find("a:pPr", NS)
        if found is None:
            found = etree.SubElement(self.el, q("a:pPr"))
            self.el.insert(0, found)
        return found

    def space_before(self, emu: float) -> float:
        """Set the gap above this paragraph; returns the gap actually written (PowerPoint keeps whole points only - measured)."""
        if emu < -0.4 * PX and self.lines == 1 and self.el.find("a:pPr/a:lnSpc", NS) is None:
            # tighter than single spacing: an exact, shorter line starting at the cursor puts the glyphs where they were
            exact = max(0.6 * self.size, (emu + self.size) / 0.8)
            ppr = self.ppr()
            node = etree.Element(q("a:lnSpc"))
            points = max(1, int(exact / 12700 + 0.5))
            etree.SubElement(node, q("a:spcPts")).set("val", str(points * 100))
            ppr.insert(0, node)
            self.pitch = self.height = float(points * 12700)
            return 0.0
        points = int(round(emu / 12700))
        if points <= 0:
            return 0.0
        ppr = self.ppr()
        for old in ppr.findall("a:spcBef", NS):
            ppr.remove(old)
        node = etree.Element(q("a:spcBef"))
        etree.SubElement(node, q("a:spcPts")).set("val", str(points * 100))
        ppr.insert(1 if ppr.find("a:lnSpc", NS) is not None else 0, node)
        return points * 12700.0

    def margins(self, left: float = 0.0, right: float = 0.0) -> None:
        ppr = self.ppr()
        if left > 0.4 * PX:
            ppr.set("marL", str(int(round(left + int(ppr.get("marL") or 0)))))
        if right > 0.4 * PX:
            ppr.set("marR", str(int(round(right))))


class TextBox:
    def __init__(self, item: Item, ratio: float, fonts=None):
        self.item = item
        self.fonts = fonts
        self.paras = [Para(p, ratio) for p in item.el.findall("p:txBody/a:p", NS)]
        for para in self.paras:
            para.prepare_breaks(fonts)
        self.left, self.top, self.right = item.box[0], item.box[1], item.box[2]
        self.bottom = self.top + sum(p.height for p in self.paras)  # where the glyph lines end, not the exporter's taller frame
        self.align = self.paras[0].align if self.paras else "l"
        self.width = self.right - self.left

    @property
    def natural(self):
        return (self.left, self.top, self.right, self.bottom)

    @property
    def needs(self) -> float:
        """Width a wrapping frame must offer so that no authored line breaks early: measured when the fonts are here, else the exporter's estimate."""
        def hang(para) -> int:  # a bullet's hanging indent is part of the line
            ppr = para.el.find("a:pPr", NS)
            return int(ppr.get("marL") or 0) if ppr is not None else 0
        real = [None if p.real_width is None else p.real_width + hang(p) for p in self.paras]
        return max(real) * 1.03 + 2 * PX if real and all(r is not None for r in real) else self.width * 1.03

    def move_top(self, new_top: float) -> None:
        off = self.item.el.find("p:spPr/a:xfrm/a:off", NS)
        off.set("y", str(int(round(int(off.get("y")) + (new_top - self.top)))))
        self.top = new_top

    def set_width(self, width: float) -> None:
        off, ext = self.item.el.find("p:spPr/a:xfrm/a:off", NS), self.item.el.find("p:spPr/a:xfrm/a:ext", NS)
        grow = int(round(width)) - int(ext.get("cx"))
        if self.align == "ctr":
            off.set("x", str(int(off.get("x")) - grow // 2))
        elif self.align == "r":
            off.set("x", str(int(off.get("x")) - grow))
        ext.set("cx", str(int(round(width))))


LIST_MARK = re.compile(r"^\s*(?:[\u2022\u00b7\u25cf\u25aa\u25a0\u25c6\u2013\u2014-]\s|\d{1,2}[.)]\s)")


def edge_offset(first: "TextBox", other: "TextBox") -> float:
    if first.align == "l":
        return abs(other.left - first.left)
    if first.align == "r":
        return abs(other.right - first.right)
    return abs((other.left + other.right) - (first.left + first.right)) / 2


def gap_is_clear(first: "TextBox", other: "TextBox", items: list) -> bool:
    """Nothing painted lies between two stacked boxes (a hairline between rows), nor over either of them between their paint positions."""
    low, high = sorted((first.item.z, other.item.z))
    gap = (min(first.left, other.left), min(first.bottom, other.bottom) - PX, max(first.right, other.right), max(first.top, other.top) + PX)
    for item in items:
        if item.is_text or not painted(item):
            continue
        if low < item.z < high and (overlap(item.box, other.natural, PX) or overlap(item.box, first.natural, PX)):
            return False
        thin = (item.box[3] - item.box[1]) <= 3 * PX
        if thin and gap[3] > gap[1] and overlap(item.box, gap, 0) and item.box[1] >= first.top and item.box[3] <= other.bottom:
            return False
    return True


def has_marker(box, items: list) -> bool:
    """A small painted shape just left of the line, level with it: a hand-drawn bullet, a tick, a numbered badge."""
    size = box.paras[0].size
    for item in items:
        if item.is_text or not painted(item):
            continue
        width, height = item.box[2] - item.box[0], item.box[3] - item.box[1]
        if width > 1.3 * size or height > 1.3 * size or width < PX or height < PX:
            continue
        level = box.top - 0.2 * size <= (item.box[1] + item.box[3]) / 2 <= box.top + 1.3 * size
        if level and box.left - 2.4 * size <= item.box[2] <= box.left + PX:
            return True
    return False


def join_lines(texts: list, items: list, stats: dict) -> list:
    """Lines of one paragraph that the author drew as separate one-line texts become one paragraph in one box."""
    order = sorted(texts, key=lambda b: (round(b.left / (2 * PX)), b.top))
    gone: set = set()

    def single(box) -> bool:
        return not (box.item.turned or box.item.scaled) and len(box.paras) == 1 and box.paras[0].lines == 1

    for index, first in enumerate(order):
        if id(first) in gone or not single(first) or first.paras[0].signature() is None:
            continue
        group, pitch, size = [first], None, first.paras[0].size
        for other in order[index + 1:]:
            last = group[-1]
            if id(other) in gone or not single(other) or other.align != first.align or other.paras[0].signature() != first.paras[0].signature():
                continue
            step = other.top - last.top
            if edge_offset(first, other) > 1.5 * PX or not (0.9 * size <= step <= 1.75 * size) or (pitch is not None and abs(step - pitch) > 0.75 * PX):
                continue
            widest = max(b.width for b in group)
            bulleted = other.paras[0].el.find("a:pPr/a:buChar", NS) is not None or other.paras[0].el.find("a:pPr/a:buAutoNum", NS) is not None
            if (last.width < 0.72 * max(widest, other.width) or bulleted or LIST_MARK.match(other.paras[0].text()) or has_marker(other, items)
                    or not gap_is_clear(last, other, items)):
                break  # a short line ends a paragraph; a typed or drawn marker starts a list item; a rule separates rows
            pitch = step if pitch is None else pitch
            group.append(other)
        if len(group) < 2:
            continue
        para = first.paras[0]
        for position, other in enumerate(group[1:], start=1):
            etree.SubElement(para.el, q("a:br"))
            for node in list(other.paras[0].el):
                if etree.QName(node).localname in ("r", "fld"):
                    para.el.append(node)
            other.item.parent.remove(other.item.el)
            gone.add(id(other))
        ppr = para.ppr()
        for old in ppr.findall("a:lnSpc", NS):
            ppr.remove(old)
        node = etree.Element(q("a:lnSpc"))
        points = max(1, int(pitch / 12700 + 0.5))
        etree.SubElement(node, q("a:spcPts")).set("val", str(points * 100))
        ppr.insert(0, node)
        para.pitch, para.lines = float(points * 12700), len(group)
        para.height = para.pitch * para.lines
        first.move_top(first.top + para.size - 0.8 * para.pitch)  # single-spaced line -> exact-spaced line with the glyphs where they were
        if first.align == "l":
            first.right = max(b.right for b in group)
        first.width = max(b.width for b in group)
        first.set_width(first.width)
        if first.align != "l":
            first.left, first.right = first.item.box[0], first.item.box[2]
        first.bottom = first.top + para.height
        para.prepare_breaks(first.fonts)
        ext = first.item.el.find("p:spPr/a:xfrm/a:ext", NS)
        ext.set("cy", str(int(round(para.height))))
        stats["joined"] += len(group)
        stats["paragraphs"] += 1
    return [b for b in texts if id(b) not in gone]


def number_lists(body) -> int:
    """Paragraphs typed as '1. ...', '2. ...' become a native numbered list."""
    made, run_of = 0, []
    for para in body.findall("a:p", NS) + [None]:
        text = "".join(para.itertext()) if para is not None else ""
        match = re.match(r"^\s*(\d{1,2})([.)])\s+", text) if para is not None else None
        if match and (not run_of or int(match.group(1)) == run_of[-1][1] + 1):
            run_of.append((para, int(match.group(1)), match))
            continue
        if len(run_of) >= 2:
            for item, number, found in run_of:
                node = item.find("a:r/a:t", NS)
                marker = found.group(1) + found.group(2)
                if node is None or not node.text or not node.text.lstrip().startswith(marker):
                    continue
                colour = None
                if node.text.strip() == marker and len(item.findall("a:r", NS)) > 1:  # the number is its own run: its colour and weight are the list's
                    own = item.find("a:r", NS)
                    fill = own.find("a:rPr/a:solidFill", NS)
                    colour = etree.fromstring(etree.tostring(fill)) if fill is not None else None
                    item.remove(own)
                    node = item.find("a:r/a:t", NS)
                    node.text = (node.text or "").lstrip()
                    marker = ""
                size = max([int(r.get("sz")) for r in item.iter(q("a:rPr")) if r.get("sz")] or [1200]) * 127
                hang = int(round(size * 0.55 * (len(found.group(1) + found.group(2)) + 1)))
                node.text = node.text.lstrip()[len(marker):].lstrip()
                ppr = item.find("a:pPr", NS)
                if ppr is None:
                    ppr = etree.Element(q("a:pPr"))
                    item.insert(0, ppr)
                ppr.set("marL", str(int(ppr.get("marL") or 0) + hang))
                ppr.set("indent", str(-hang))
                if colour is not None:
                    holder = etree.SubElement(ppr, q("a:buClr"))
                    for child in colour:
                        holder.append(child)
                auto = etree.SubElement(ppr, q("a:buAutoNum"))
                auto.set("type", "arabicPeriod" if found.group(2) == "." else "arabicParenR")
                if run_of[0][1] != 1:
                    # every item carries the list's start: PowerPoint counts a paragraph on from the one above only when their
                    # numbering is identical, so a start set on the first item alone restarts the second at 1 (kirkland2 s12: 1, 2, 1)
                    auto.set("startAt", str(run_of[0][1]))
                made += 1
        run_of = [(para, int(match.group(1)), match)] if match else []
    return made


ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff"
BULLET_KINDS = ("buNone", "buAutoNum", "buChar", "buBlip")
BULLET_LOOK = ("buClrTx", "buClr", "buSzTx", "buSzPct", "buSzPts", "buFontTx", "buFont")
PPR_ORDER = ("lnSpc", "spcBef", "spcAft", *BULLET_LOOK, *BULLET_KINDS, "tabLst", "defRPr", "extLst")


def no_bullet(para) -> bool:
    """Set `buNone` on a paragraph (dropping any bullet it had) in schema order. True when something changed."""
    ppr = para.find("a:pPr", NS)
    if ppr is None:
        ppr = etree.Element(q("a:pPr"))
        para.insert(0, ppr)
    if ppr.find("a:buNone", NS) is not None and not any(ppr.find(f"a:{k}", NS) is not None for k in BULLET_KINDS[1:]):
        return False
    for child in list(ppr):
        if etree.QName(child).localname in BULLET_KINDS + BULLET_LOOK:
            ppr.remove(child)
    node = etree.Element(q("a:buNone"))
    later = [i for i, child in enumerate(ppr) if etree.QName(child).localname in PPR_ORDER[PPR_ORDER.index("buNone") + 1:]]
    ppr.insert(later[0] if later else len(ppr), node)
    return True


def clear_stray_bullets(tree, stats: dict) -> None:
    """No bullet where the SVG shows none (F03). An empty placeholder the exporter keeps as a carrier holds a zero-width character and
    inherits its layout's bullet, so PowerPoint drew a dot on the slide (selfdoc 28 Sep P02, P08, P14, P19; on P14 it sat on a '1.').
    Every paragraph of a placeholder without a bullet of its own, and every paragraph without visible text, gets `buNone`."""
    for shape in tree.iter(q("p:sp")):
        body = shape.find("p:txBody", NS)
        if body is None:
            continue
        placeholder = shape.find("p:nvSpPr/p:nvPr/p:ph", NS) is not None
        for para in body.findall("a:p", NS):
            text = "".join(t.text or "" for t in para.iter(q("a:t")))
            empty = not re.sub(rf"[\s{ZERO_WIDTH}]", "", text)
            ppr = para.find("a:pPr", NS)
            own = ppr is not None and any(ppr.find(f"a:{k}", NS) is not None for k in BULLET_KINDS)
            if (empty and (placeholder or own)) or (placeholder and not own):
                if no_bullet(para):
                    stats["bullets_cleared"] = stats.get("bullets_cleared", 0) + 1


def overlap(a, b, shrink=0.0):
    return min(a[2], b[2]) - max(a[0], b[0]) > shrink and min(a[3], b[3]) - max(a[1], b[1]) > shrink


def contains(outer, inner, tolerance=2 * PX):
    return outer[0] - tolerance <= inner[0] and outer[1] - tolerance <= inner[1] and outer[2] + tolerance >= inner[2] and outer[3] + tolerance >= inner[3]


def side_by_side(boxes: list[TextBox]) -> bool:
    for i, first in enumerate(boxes):
        for second in boxes[i + 1:]:
            shared = min(first.bottom, second.bottom) - max(first.top, second.top)
            if shared > 0.30 * min(first.bottom - first.top, second.bottom - second.top):
                return True
    return False


def set_body(host_el, boxes: list[TextBox], host_box, kind: str, stats: dict) -> bool:
    boxes = sorted(boxes, key=lambda b: b.top)
    left, top, right, bottom = host_box
    block_top, block_bottom = boxes[0].top, boxes[-1].bottom
    # a single label sitting in the middle of its shape is anchored to the middle, so it stays there when the shape is resized
    centred_v = len(boxes) == 1 and abs((block_top + block_bottom) / 2 - (top + bottom) / 2) <= 1.5 * PX
    aligns = {p.align for b in boxes for p in b.paras}
    centred_h = aligns == {"ctr"} and all(abs((b.left + b.right) / 2 - (left + right) / 2) <= 1.5 * PX for b in boxes)
    near_middle = (len(boxes) == 1 and aligns == {"ctr"} and abs((block_top + block_bottom) / 2 - (top + bottom) / 2) <= 4 * PX
                   and abs((boxes[0].left + boxes[0].right) / 2 - (left + right) / 2) <= 4 * PX)
    if kind == "centred" and near_middle:  # a chevron or pill label: dead centre is what the author meant
        centred_v = centred_h = True
    if kind == "centred" and not (centred_v and centred_h):
        return False
    pad = 4 * PX
    lefts = [b.left for b in boxes if b.align == "l"]
    l_ins = max(0.0, min(lefts) - left) if lefts else min(pad, (right - left) / 10)
    r_ins = min(pad, max(0.0, right - max(b.right for b in boxes)))
    if centred_h:
        l_ins = r_ins = min(pad, max(0.0, min(b.left for b in boxes) - left))
    inner_left, inner_right = left + l_ins, right - r_ins
    wrap = "square"
    for box in boxes:
        room = inner_right - (box.left if box.align == "l" else inner_left)
        if box.align == "ctr":
            room = 2 * min((box.left + box.right) / 2 - inner_left, inner_right - (box.left + box.right) / 2)
        elif box.align == "r":
            room = box.right - inner_left
        if box.needs > room:
            wrap = "none"  # no slack for PowerPoint's own metrics: the text lives in the shape but keeps its lines
    if kind == "centred":
        wrap = "none"  # the preset's own text area is narrower than its bounds: a label must not be re-broken by it
    body = host_el.find("p:txBody", NS)
    if body is not None:
        host_el.remove(body)
    body = etree.SubElement(host_el, q("p:txBody"))
    ext = host_el.find("p:extLst", NS)
    if ext is not None:  # txBody precedes extLst
        host_el.remove(ext)
        host_el.append(ext)
    body_pr = etree.SubElement(body, q("a:bodyPr"))
    t_ins = b_ins = 0.0
    if centred_v:  # anchored to the middle; what the block was off the exact middle by goes into an inset (twice, since the middle moves by half)
        off_middle = (block_top + block_bottom) / 2 - (top + bottom) / 2
        t_ins, b_ins = max(0.0, 2 * off_middle), max(0.0, -2 * off_middle)
    else:
        t_ins = max(0.0, block_top - top)
    for key, value in (("wrap", wrap), ("lIns", int(round(l_ins))), ("tIns", int(round(t_ins))), ("rIns", int(round(r_ins))), ("bIns", int(round(b_ins))),
                       ("anchor", "ctr" if centred_v else "t"), ("anchorCtr", "0"), ("rtlCol", "0")):
        body_pr.set(key, str(value))
    etree.SubElement(body_pr, q("a:noAutofit"))
    etree.SubElement(body, q("a:lstStyle"))
    cursor = block_top
    for box in boxes:
        for index, para in enumerate(box.paras):
            if index == 0:
                cursor += para.space_before(box.top - cursor)
            if para.align == "l":
                para.margins(left=box.left - inner_left)
            elif para.align == "r":
                para.margins(right=inner_right - box.right)
            elif not centred_h:
                centre, frame = (box.left + box.right) / 2, (inner_left + inner_right) / 2
                para.margins(left=max(0.0, 2 * (centre - frame)), right=max(0.0, 2 * (frame - centre)))
            if para.joins:
                stats["reflowed"] += 1 if para.settle_joins(inner_right - box.left if wrap == "square" and para.align == "l" else None) else 0
            body.append(para.el)
            cursor += para.height
    stats["numbered"] += number_lists(body)
    return True


def merge_stacks(loose: list, items: list, stats: dict) -> None:
    """Left-over boxes that are one block of text (a heading and what stands under it) become one box with paragraphs."""
    order = sorted(loose, key=lambda b: (round(b.left / (2 * PX)), b.top))
    used: set = set()
    for index, first in enumerate(order):
        if id(first) in used or first.item.turned or first.item.scaled:
            continue
        stack = [first]
        for other in order[index + 1:]:
            last = stack[-1]
            if id(other) in used or other.item.turned or other.item.scaled:
                continue
            if other.align != first.align or edge_offset(first, other) > 1.5 * PX or other.top <= last.top:
                continue
            gap = other.top - last.bottom
            heading_starts = other.paras[0].size > 1.12 * last.paras[-1].size  # larger type after smaller: a new block begins
            tight_ok = gap >= -1.5 * PX or (other.paras[0].lines == 1 and gap >= -0.5 * other.paras[0].size)
            if heading_starts or not tight_ok or gap > 0.9 * max(other.paras[0].size, last.paras[-1].size) or not gap_is_clear(last, other, items):
                break  # only neighbours merge: the first box that does not belong ends the block
            stack.append(other)
        frame = max(b.needs for b in stack)
        for member in stack:
            for para in member.paras:
                if para.joins:
                    stats["reflowed"] += 1 if para.settle_joins(frame if member.align == "l" else None) else 0
        body = first.item.el.find("p:txBody", NS)
        if len(stack) < 2:
            if first.paras and first.paras[0].lines > 1 and first.align == "l":
                first.set_width(frame)
                body.find("a:bodyPr", NS).set("wrap", "square")
            continue
        cursor = first.bottom
        for other in stack[1:]:
            for position, para in enumerate(other.paras):
                if position == 0:
                    cursor += para.space_before(other.top - cursor)
                body.append(para.el)
                cursor += para.height
            other.item.parent.remove(other.item.el)
            used.add(id(other))
        used.add(id(first))
        first.set_width(frame)
        first.item.el.find("p:spPr/a:xfrm/a:ext", NS).set("cy", str(int(round(cursor - first.top))))
        body.find("a:bodyPr", NS).set("wrap", "square")
        stats["numbered"] += number_lists(body)
        stats["stacked"] += len(stack)
        stats["stacks"] += 1


def mark_title(tree, slide_size, stats: dict):
    """The slide's title becomes its title placeholder, so PowerPoint knows it: outline view, navigation, accessibility, reuse.
    Its own position and formatting stay explicit, so nothing is inherited that would move or restyle it."""
    if tree.find(".//p:nvPr/p:ph[@type='title']", NS) is not None or tree.find(".//p:nvPr/p:ph[@type='ctrTitle']", NS) is not None:
        return
    candidates = []
    for item in walk(tree):
        if item.tag != "sp":
            continue
        sizes = [int(r.get("sz")) for r in item.el.iter(q("a:rPr")) if r.get("sz")]
        if sizes and max(sizes) >= 1800 and "".join(item.el.itertext()).strip():
            candidates.append(((-max(sizes), item.box[1]), item))  # the largest type in the upper part of the slide; the highest of equals
    if not candidates:
        return
    upper = [pair for pair in candidates if pair[1].box[1] <= 0.45 * slide_size[1]]
    overall = min(candidates, key=lambda pair: pair[0])
    chosen = min(upper, key=lambda pair: pair[0]) if upper else overall
    if -overall[0][0] >= 1.4 * -chosen[0][0]:
        chosen = overall  # a cover: the title is far larger than anything in the header and may sit lower on the slide
    chosen = chosen[1]
    if not chosen.is_text or chosen.turned or chosen.scaled:
        return  # the largest type sits inside a shape (a cover panel): no title is claimed rather than the wrong one
    title = chosen.el
    if chosen.parent is not tree:  # a placeholder cannot live inside a group: the title moves to the slide itself (group transforms here are identity)
        chosen.parent.remove(title)
        tree.append(title)
        prune_empty_groups(tree)
    props = title.find("p:nvSpPr/p:cNvSpPr", NS)
    props.attrib.pop("txBox", None)
    name = title.find("p:nvSpPr/p:cNvPr", NS)
    name.set("name", "Title " + name.get("id", ""))
    holder = title.find("p:nvSpPr/p:nvPr", NS)
    etree.SubElement(holder, q("p:ph")).set("type", "title")
    for para in title.findall("p:txBody/a:p", NS):
        ppr = para.find("a:pPr", NS)
        if ppr is None:
            ppr = etree.Element(q("a:pPr"))
            para.insert(0, ppr)
        ppr.set("algn", ppr.get("algn") or "l")
        if ppr.find("a:lnSpc", NS) is None:
            node = etree.Element(q("a:lnSpc"))
            etree.SubElement(node, q("a:spcPct")).set("val", "100000")
            ppr.insert(0, node)
        if ppr.find("a:spcBef", NS) is None:
            node = etree.Element(q("a:spcBef"))
            etree.SubElement(node, q("a:spcPts")).set("val", "0")
            ppr.insert(1, node)
        for run in para.iter(q("a:rPr")):
            run.set("b", run.get("b") or "0")
            run.set("i", run.get("i") or "0")
    stats["titles"] += 1
    return title


def rules_to_lines(tree, stats: dict) -> None:
    """A hairline drawn as a thin filled rectangle becomes a real line: it then resizes, restyles and snaps like one."""
    for item in walk(tree):
        if item.tag != "sp" or item.is_text or item.turned or item.scaled or "".join(item.el.itertext()).strip():
            continue
        sppr = item.el.find("p:spPr", NS)
        preset, fill, ext, off = sppr.find("a:prstGeom", NS), sppr.find("a:solidFill", NS), sppr.find("a:xfrm/a:ext", NS), sppr.find("a:xfrm/a:off", NS)
        if preset is None or preset.get("prst") != "rect" or fill is None or ext is None:
            continue
        line = sppr.find("a:ln", NS)
        if line is not None and line.find("a:noFill", NS) is None and len(line):
            continue  # it has an outline of its own: a real (if thin) box
        cx, cy = int(ext.get("cx")), int(ext.get("cy"))
        thick, long = min(cx, cy), max(cx, cy)
        if thick > 3 * PX or long < 12 * PX or thick <= 0:
            continue
        if cx >= cy:
            off.set("y", str(int(off.get("y")) + cy // 2))
            ext.set("cy", "0")
        else:
            off.set("x", str(int(off.get("x")) + cx // 2))
            ext.set("cx", "0")
        preset.set("prst", "line")
        sppr.remove(fill)
        if line is not None:
            sppr.remove(line)
        new = etree.Element(q("a:ln"))
        new.set("w", str(thick))
        new.set("cap", "flat")
        new.append(fill)
        preset.addnext(new)
        stats["rules"] += 1


def glue_connectors(tree, stats: dict) -> None:
    """A straight line that runs from the edge of one box to the edge of another becomes a real connector glued to both: move a box and
    the arrow follows. Geometry and paint are kept, so nothing moves now. Only rectangles offer the four edge sites this relies on; a line
    with a free end is glued at the end that touches. A freeform of one straight segment, or of two or three horizontal and vertical
    segments (an L or a Z: what `M x y H .. V .. H ..` exports as), becomes a straight, bentConnector2 or bentConnector3 connector through
    the same corners (elbow_connector). Routes of four or more segments, and U-shaped returns whose two ends sit level, stay drawings:
    PowerPoint's elbow presets cannot hold them exactly."""
    items = walk(tree)
    boxes = []
    for item in items:
        if item.tag != "sp" or item.is_text or item.turned or item.scaled or not painted(item):
            continue
        preset = item.el.find("p:spPr/a:prstGeom", NS)
        width, height = item.box[2] - item.box[0], item.box[3] - item.box[1]
        if preset is None or preset.get("prst") not in ("rect", "roundRect") or width < 16 * PX or height < 10 * PX:
            continue
        boxes.append(item)

    def site(point):
        """(shape id, site index) of the smallest box whose edge this point lies on: 0 top, 1 left, 2 bottom, 3 right."""
        x, y = point
        best = None
        for box in boxes:
            left, top, right, bottom = box.box
            reach = 4 * PX
            if not (left - reach <= x <= right + reach and top - reach <= y <= bottom + reach):
                continue
            distances = [(abs(y - top), 0), (abs(x - left), 1), (abs(y - bottom), 2), (abs(x - right), 3)]
            distance, index = min(distances)
            if distance > reach:
                continue  # inside the box, not on its edge
            if best is None or box.area < best[0]:
                best = (box.area, box.el.find("p:nvSpPr/p:cNvPr", NS).get("id"), index)
        return best[1:] if best else None

    for item in items:
        if item.tag != "sp" or item.scaled or "".join(item.el.itertext()).strip():
            continue
        sppr = item.el.find("p:spPr", NS)
        preset, xfrm = sppr.find("a:prstGeom", NS), sppr.find("a:xfrm", NS)
        if preset is None or preset.get("prst") != "line" or xfrm is None or xfrm.get("rot") not in (None, "0"):
            continue
        left, top, right, bottom = item.box
        start = (right if xfrm.get("flipH") == "1" else left, bottom if xfrm.get("flipV") == "1" else top)
        end = (left if xfrm.get("flipH") == "1" else right, top if xfrm.get("flipV") == "1" else bottom)
        begin, finish = site(start), site(end)
        if begin is None and finish is None or (begin and finish and begin[0] == finish[0]):
            continue
        connector = etree.Element(q("p:cxnSp"))
        non_visual = etree.SubElement(connector, q("p:nvCxnSpPr"))
        props = etree.fromstring(etree.tostring(item.el.find("p:nvSpPr/p:cNvPr", NS)))
        if re.fullmatch(r"(Line|Straight Connector|Shape)\s*\d*", props.get("name", "")):
            props.set("name", "Connector " + props.get("id", ""))
        non_visual.append(props)
        links = etree.SubElement(non_visual, q("p:cNvCxnSpPr"))
        for tag, found in (("a:stCxn", begin), ("a:endCxn", finish)):
            if found:
                node = etree.SubElement(links, q(tag))
                node.set("id", found[0])
                node.set("idx", str(found[1]))
        etree.SubElement(non_visual, q("p:nvPr"))
        preset.set("prst", "straightConnector1")
        connector.append(sppr)
        style = item.el.find("p:style", NS)
        if style is not None:
            connector.append(style)
        item.parent.replace(item.el, connector)
        stats["glued"] += 1

    for item in walk(tree):
        if item.tag != "sp" or item.scaled or item.is_text or "".join(item.el.itertext()).strip():
            continue
        points = freeform_route(item)
        if points is None:
            continue
        found = elbow_connector(points)
        if found is None:
            continue
        begin, finish = site(points[0]), site(points[-1])
        if begin is None and finish is None or (begin and finish and begin[0] == finish[0]):
            continue
        prst, off, ext, rot, flip_h, flip_v, adj = found
        sppr = item.el.find("p:spPr", NS)
        xfrm = sppr.find("a:xfrm", NS)
        old_off = xfrm.find("a:off", NS)
        shift_x, shift_y = item.box[0] - int(old_off.get("x")), item.box[1] - int(old_off.get("y"))  # absolute minus the parent frame
        for key in ("rot", "flipH", "flipV"):
            xfrm.attrib.pop(key, None)
        if rot:
            xfrm.set("rot", str(rot))
        if flip_h:
            xfrm.set("flipH", "1")
        if flip_v:
            xfrm.set("flipV", "1")
        old_off.set("x", str(int(round(off[0] - shift_x))))
        old_off.set("y", str(int(round(off[1] - shift_y))))
        xfrm.find("a:ext", NS).set("cx", str(max(1, int(round(ext[0])))))
        xfrm.find("a:ext", NS).set("cy", str(max(1, int(round(ext[1])))))
        preset = etree.Element(q("a:prstGeom"))
        preset.set("prst", prst)
        av = etree.SubElement(preset, q("a:avLst"))
        if adj is not None:
            gd = etree.SubElement(av, q("a:gd"))
            gd.set("name", "adj1")
            gd.set("fmla", f"val {adj}")
        sppr.replace(sppr.find("a:custGeom", NS), preset)
        connector = etree.Element(q("p:cxnSp"))
        non_visual = etree.SubElement(connector, q("p:nvCxnSpPr"))
        props = etree.fromstring(etree.tostring(item.el.find("p:nvSpPr/p:cNvPr", NS)))
        if re.fullmatch(r"(Freeform|Shape)\s*\d*", props.get("name", "")):
            props.set("name", "Connector " + props.get("id", ""))
        non_visual.append(props)
        links = etree.SubElement(non_visual, q("p:cNvCxnSpPr"))
        for tag, hit in (("a:stCxn", begin), ("a:endCxn", finish)):
            if hit:
                node = etree.SubElement(links, q(tag))
                node.set("id", hit[0])
                node.set("idx", str(hit[1]))
        etree.SubElement(non_visual, q("p:nvPr"))
        connector.append(sppr)
        style = item.el.find("p:style", NS)
        if style is not None:
            connector.append(style)
        item.parent.replace(item.el, connector)
        stats["glued"] += 1
        stats["elbows"] = stats.get("elbows", 0) + 1


def freeform_route(item: Item) -> list | None:
    """The corners of an unfilled, stroked custom-geometry path of one open subpath (moveTo then lineTo only), in absolute EMU."""
    sppr = item.el.find("p:spPr", NS)
    geometry, xfrm = sppr.find("a:custGeom", NS), sppr.find("a:xfrm", NS)
    if geometry is None or xfrm is None or item.turned or sppr.find("a:noFill", NS) is None:
        return None
    line = sppr.find("a:ln", NS)
    if line is None or line.find("a:noFill", NS) is not None:
        return None
    if not any(end is not None and end.get("type") not in (None, "none") for end in (line.find("a:headEnd", NS), line.find("a:tailEnd", NS))):
        return None  # only arrows are connectors: a rule, a gate line or a leader stays a line
    paths = geometry.findall("a:pathLst/a:path", NS)
    if len(paths) != 1:
        return None
    steps = list(paths[0])
    if len(steps) < 2 or etree.QName(steps[0]).localname != "moveTo" or any(etree.QName(s).localname != "lnTo" for s in steps[1:]):
        return None
    ext = xfrm.find("a:ext", NS)
    width, height = int(paths[0].get("w") or ext.get("cx")), int(paths[0].get("h") or ext.get("cy"))
    sx = (item.box[2] - item.box[0]) / width if width else 1.0
    sy = (item.box[3] - item.box[1]) / height if height else 1.0
    points = []
    for step in steps:
        pt = step.find("a:pt", NS)
        points.append((item.box[0] + int(pt.get("x")) * sx, item.box[1] + int(pt.get("y")) * sy))
    return points if len(points) <= 4 else None


def _preset_route(prst: str, w: float, h: float, adj) -> list:
    """The corners of a connector preset in its own frame (presetShapeDefinitions.xml)."""
    if prst == "straightConnector1":
        return [(0.0, 0.0), (w, h)]
    if prst == "bentConnector2":
        return [(0.0, 0.0), (w, 0.0), (w, h)]
    x1 = w * (adj if adj is not None else 50000) / 100000
    return [(0.0, 0.0), (x1, 0.0), (x1, h), (w, h)]


def elbow_connector(points: list, tolerance: float = 1.5 * PX):
    """The connector preset, frame and adjust value that draw exactly these corners (start first), or None.
    Returns (prst, (off x, off y), (ext cx, ext cy), rot, flipH, flipV, adj1 or None). Every orientation is one of a quarter turn
    or none, times the two flips; the adjust value places the middle leg of a Z."""
    corners = [points[0]]
    for here, after in zip(points[1:], points[2:] + [None]):  # a point on a straight run is not a corner
        if after is not None and ((abs(corners[-1][0] - here[0]) <= tolerance and abs(here[0] - after[0]) <= tolerance)
                                  or (abs(corners[-1][1] - here[1]) <= tolerance and abs(here[1] - after[1]) <= tolerance)):
            continue
        corners.append(here)
    points = corners
    n = len(points)
    if n == 2:
        prst = "straightConnector1"
    elif n in (3, 4):
        if any(abs(a[0] - b[0]) > tolerance and abs(a[1] - b[1]) > tolerance for a, b in zip(points, points[1:])):
            return None  # a diagonal segment: not an elbow
        prst = "bentConnector2" if n == 3 else "bentConnector3"
    else:
        return None
    (x0, y0), (x1, y1) = points[0], points[-1]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    span_x, span_y = abs(x1 - x0), abs(y1 - y0)
    for rot in (0, 5400000):
        w, h = (span_x, span_y) if rot == 0 else (span_y, span_x)
        if prst == "bentConnector3" and w < 2 * PX:
            continue  # the ends are level along the first leg (a U-turn): no finite adjust value draws it
        for flip_h in (False, True):
            for flip_v in (False, True):
                def to_local(p, rot=rot, w=w, h=h, flip_h=flip_h, flip_v=flip_v):
                    dx, dy = p[0] - cx, p[1] - cy
                    if rot:
                        dx, dy = dy, -dx  # undo a quarter turn clockwise
                    lx, ly = dx + w / 2, dy + h / 2
                    return (w - lx if flip_h else lx, h - ly if flip_v else ly)
                local = [to_local(p) for p in points]
                adj = int(round(local[1][0] / w * 100000)) if prst == "bentConnector3" else None
                expected = _preset_route(prst, w, h, adj)
                if all(abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance for a, b in zip(local, expected)):
                    return prst, (cx - w / 2, cy - h / 2), (w, h), rot, flip_h, flip_v, adj
    return None


def name_objects(tree, stats: dict) -> None:
    """The Selection Pane lists what things are, not 'Rectangle 70': an object that holds text is named after its first words."""
    seen: dict = {}
    for item in walk(tree):
        if item.tag != "sp":
            continue
        props = item.el.find("p:nvSpPr/p:cNvPr", NS)
        if props is None or not re.fullmatch(r"(TextBox|Rectangle|Freeform|Oval|Shape|Rounded Rectangle|Title)\s*\d*", props.get("name", "")):
            continue  # the author's own id stays
        first = next((t for t in ("".join(p.itertext()).strip() for p in item.el.findall("p:txBody/a:p", NS)) if t), "")
        if not first:
            continue
        words = re.sub(r"\s+", " ", first.replace("\v", " "))[:34].strip()
        kind = "Title" if item.el.find("p:nvSpPr/p:nvPr/p:ph", NS) is not None else "Text" if item.is_text else "Box"
        label = f"{kind}: {words}"
        seen[label] = seen.get(label, 0) + 1
        props.set("name", label if seen[label] == 1 else f"{label} ({seen[label]})")
        stats["named"] += 1


def describe_pictures(tree, rels: dict, stats: dict) -> None:
    """Alt text for every picture that has none, from its file name."""
    for pic in tree.iter(q("p:pic")):
        props = pic.find("p:nvPicPr/p:cNvPr", NS)
        blip = pic.find("p:blipFill/a:blip", NS)
        if props is None or props.get("descr") or blip is None:
            continue
        target = rels.get(blip.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"), "")
        words = re.sub(r"[_\-]+", " ", Path(target).stem).strip()
        if words:
            props.set("descr", words)
            stats["described"] += 1


def prune_empty_groups(tree) -> None:
    changed = True
    while changed:
        changed = False
        for group in tree.iter(q("p:grpSp")):
            if not any(etree.QName(c).localname in ("sp", "pic", "cxnSp", "grpSp", "graphicFrame") for c in group):
                group.getparent().remove(group)
                changed = True
                break


def process_slide(xml: bytes, slide_size, ratio: float, fonts=None, rels: dict | None = None) -> tuple[bytes, dict]:
    root = etree.fromstring(xml)
    stats = {"texts": 0, "adopted": 0, "hosts": 0, "stacked": 0, "stacks": 0, "reflowed": 0, "joined": 0, "paragraphs": 0, "numbered": 0, "titles": 0, "rules": 0, "named": 0, "described": 0, "glued": 0, "left": {}}
    tree = root.find("p:cSld/p:spTree", NS)
    if tree is None:
        return xml, stats
    clear_stray_bullets(tree, stats)
    items = walk(tree)
    # a carrier holding only a zero-width character is not text a reader sees: it is neither adopted nor stacked (F03, selfdoc P14)
    texts = [TextBox(i, ratio, fonts) for i in items if i.is_text and re.sub(rf"[\s{ZERO_WIDTH}]", "", "".join(i.el.itertext()))]
    stats["texts"] = len(texts)

    def leave(reason: str, count: int = 1) -> None:
        stats["left"][reason] = stats["left"].get(reason, 0) + count

    if root.find("p:timing", NS) is not None:
        leave("slide has animation timing", len(texts))
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True), stats
    slide_area = slide_size[0] * slide_size[1]
    texts = join_lines(texts, items, stats)
    hosts = [(i, host_kind(i, slide_area)) for i in items]
    hosts = [(i, k) for i, k in hosts if k]
    covered = columns = 0
    chosen: dict[int, list[TextBox]] = {}
    host_of: dict[int, tuple[Item, str]] = {}
    loose: list[TextBox] = []
    for text in texts:
        if text.item.turned or text.item.scaled:
            leave("rotated, flipped or in a scaled group")
            continue
        if text.item.el.find("p:nvSpPr/p:cNvPr/a:hlinkClick", NS) is not None or not text.paras:
            leave("hyperlinked box")
            continue
        under = [(h, k) for h, k in hosts if h.z < text.item.z and contains(h.box, text.natural)]
        if not under:
            loose.append(text)
            continue
        host, kind = min(under, key=lambda pair: pair[0].area)
        between = [i for i in items if host.z < i.z < text.item.z and not i.is_text and painted(i) and overlap(i.box, text.natural, shrink=1 * PX)]
        if between:
            covered += 1
            loose.append(text)
            continue
        chosen.setdefault(id(host), []).append(text)
        host_of[id(host)] = (host, kind)
    for key, boxes in chosen.items():
        host, kind = host_of[key]
        if side_by_side(boxes):  # one frame cannot hold two columns: each column becomes one text box instead
            columns += len(boxes)
            loose.extend(boxes)
            continue
        if not set_body(host.el, boxes, host.box, kind, stats):
            leave("not centred in a shape whose text area is not its bounds", len(boxes))
            loose.extend(boxes)
            continue
        for box in boxes:
            box.item.parent.remove(box.item.el)
        stats["adopted"] += len(boxes)
        stats["hosts"] += 1
    title = mark_title(tree, slide_size, stats)  # before blocks form: the title stays a box of its own, its subtitle another
    if title is not None:
        for box in [b for b in loose if b.item.el is title]:
            for para in box.paras:
                para.settle_joins(box.needs)
            if any(p.lines > 1 for p in box.paras) and box.align == "l":
                box.set_width(box.needs)
                title.find("p:txBody/a:bodyPr", NS).set("wrap", "square")
        loose = [b for b in loose if b.item.el is not title]
        stats["single"] = 1
    before = stats["stacked"]
    merge_stacks(loose, items, stats)
    stats["single"] = stats.get("single", 0) + len(loose) - (stats["stacked"] - before)
    stats["notes"] = {"in a shape that holds several columns of text (merged per column where they stack)": columns,
                      "another object painted between the text and its shape": covered}
    prune_empty_groups(tree)
    rules_to_lines(tree, stats)
    glue_connectors(tree, stats)
    describe_pictures(tree, rels or {}, stats)
    name_objects(tree, stats)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True), stats


R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
IMAGE_REL = R_NS + "/image"
LAYOUT_REL = R_NS + "/slideLayout"


def _signature(item: Item, rels: dict, slide_number: int):
    """What makes an object 'the same thing' on another slide: its kind, place, words, paint and picture. None for what can never be chrome."""
    el = item.el
    if item.tag not in ("sp", "pic") or item.scaled or item.turned or el.find(".//p:nvPr/p:ph", NS) is not None:
        return None
    box = tuple(int(round(v / (2 * PX))) for v in item.box)
    text = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
    if item.tag == "pic":
        blip = el.find("p:blipFill/a:blip", NS)
        return ("pic", box, rels.get(blip.get(f"{{{R_NS}}}embed"), "") if blip is not None else "")
    if text and text == str(slide_number):
        return ("sldnum", box[2] // 100, box[1] // 2, box[3] // 2)  # the width differs with the digits and so does the left edge of a right-aligned folio; the line does not
    paint = b"".join(etree.tostring(node) for node in el.find("p:spPr", NS) if etree.QName(node).localname != "xfrm")
    runs = b"".join(etree.tostring(node) for node in el.iter(q("a:rPr")))
    return ("sp", box, text, paint, runs)


def promote_chrome(slides: dict, slide_rels: dict, package: dict, report: dict, layout_name: str = "Content - header and footer") -> None:
    """The header, the footer, the logo, the rules and the page number that repeat on every content slide move to ONE slide layout:
    edited once, they change everywhere, and the page number becomes a real field. Slides that do not carry them (a cover) keep their layout."""
    order = sorted(slides, key=lambda name: int(re.search(r"(\d+)", name.rsplit("/", 1)[1]).group(1)))
    if len(order) < 4:
        return
    trees = {name: etree.fromstring(slides[name]) for name in order}
    found: dict = {}
    for position, name in enumerate(order, start=1):
        tree = trees[name].find("p:cSld/p:spTree", NS)
        items = walk(tree)
        keyed = [(item, _signature(item, slide_rels.get(name, {}), position)) for item in items]
        for item, key in keyed:
            if key is not None:
                found.setdefault(key, {})[name] = (item, keyed)
    need = max(3, int(0.7 * len(order)))
    repeated = {key for key, where in found.items() if len(where) >= need}

    def covered(item, keyed) -> bool:
        """Painted over something that stays on the slide: on the layout it would fall behind it. What is itself chrome (a page field) moves along."""
        return any(o.z < item.z and o is not item and k not in repeated and painted(o) and not o.is_text and overlap(o.box, item.box, PX) for o, k in keyed)

    chrome = {key: {name: (item, False) for name, (item, keyed) in where.items()} for key, where in found.items()
              if key in repeated and not any(covered(item, keyed) for item, keyed in where.values())}
    if not chrome:
        return
    members = [name for name in order if sum(1 for where in chrome.values() if name in where) >= 0.6 * len(chrome)]
    chrome = {key: where for key, where in chrome.items() if all(name in where for name in members)}
    if len(members) < 3 or not chrome:
        return
    layout_targets = {name: next((t for t, kind in slide_rels[name + "#types"].items() if kind == LAYOUT_REL), None) for name in members}
    base_target = layout_targets[members[0]]
    if base_target is None or len(set(layout_targets.values())) != 1:
        return
    base_layout = "ppt/slideLayouts/" + base_target.rsplit("/", 1)[1]
    numbers = [int(m.group(1)) for m in (re.fullmatch(r"ppt/slideLayouts/slideLayout(\d+)\.xml", n) for n in package) if m]
    new_name = f"ppt/slideLayouts/slideLayout{max(numbers) + 1}.xml"
    layout = etree.fromstring(package[base_layout])
    layout.find("p:cSld", NS).set("name", layout_name)
    layout_tree = layout.find("p:cSld/p:spTree", NS)
    layout_rels = etree.fromstring(package[base_layout.replace("slideLayouts/", "slideLayouts/_rels/") + ".rels"])
    first = members[0]
    taken = {int(node.get("id")) for node in layout_tree.iter(q("p:cNvPr")) if (node.get("id") or "").isdigit()}
    for key, where in sorted(chrome.items(), key=lambda pair: pair[1][first][0].z):
        item = where[first][0]
        clone = etree.fromstring(etree.tostring(item.el))
        if key[0] == "pic":
            blip = clone.find("p:blipFill/a:blip", NS)
            rid = f"rIdChrome{len(layout_rels) + 1}"
            rel = etree.SubElement(layout_rels, f"{{{REL_NS}}}Relationship")
            rel.set("Id", rid)
            rel.set("Type", IMAGE_REL)
            rel.set("Target", key[2])
            blip.set(f"{{{R_NS}}}embed", rid)
        if key[0] == "sldnum":
            para = clone.find("p:txBody/a:p", NS)
            run = para.find("a:r", NS)
            field = etree.Element(q("a:fld"))
            field.set("id", "{B6F15528-21DE-4FAA-801E-634DDDAF4B2B}")
            field.set("type", "slidenum")
            props = run.find("a:rPr", NS)
            if props is not None:
                field.append(props)
            etree.SubElement(field, q("a:t")).text = "‹#›"
            para.replace(run, field)
            for extra in para.findall("a:r", NS):
                para.remove(extra)
            clone.find("p:nvSpPr/p:cNvPr", NS).set("name", "Slide number")
        props = clone.find(".//p:cNvPr", NS)
        new_id = max(taken | {1}) + 1
        taken.add(new_id)
        props.set("id", str(new_id))
        layout_tree.append(clone)
        for name in members:
            element, _ = where[name]
            element.parent.remove(element.el)
    # a title placeholder on the layout, set like the slides' titles: a slide the user adds on this layout starts with the right title
    model = trees[first].find("p:cSld/p:spTree", NS).find(".//p:sp/p:nvSpPr/p:nvPr/p:ph[@type='title']", NS)
    if model is not None and layout_tree.find(".//p:nvPr/p:ph[@type='title']", NS) is None:
        holder = etree.fromstring(etree.tostring(model.getparent().getparent().getparent()))
        body = holder.find("p:txBody", NS)
        paragraphs = body.findall("a:p", NS)
        for extra in paragraphs[1:]:
            body.remove(extra)
        runs = [node for node in paragraphs[0] if etree.QName(node).localname in ("r", "br", "fld")]
        for extra in runs[1:]:
            paragraphs[0].remove(extra)
        if runs and runs[0].find("a:t", NS) is not None:
            runs[0].find("a:t", NS).text = "Click to add the slide's finding as a full sentence"
        props = holder.find("p:nvSpPr/p:cNvPr", NS)
        new_id = max(taken | {1}) + 1
        taken.add(new_id)
        props.set("id", str(new_id))
        props.set("name", "Title Placeholder")
        layout_tree.append(holder)
        report["layout_title_placeholder"] = True
    for name in members:
        prune_empty_groups(trees[name].find("p:cSld/p:spTree", NS))
        slides[name] = etree.tostring(trees[name], xml_declaration=True, encoding="UTF-8", standalone=True)
        rels_name = name.replace("slides/", "slides/_rels/") + ".rels"
        rels = etree.fromstring(package[rels_name])
        for rel in rels:
            if rel.get("Type") == LAYOUT_REL:
                rel.set("Target", "../slideLayouts/" + new_name.rsplit("/", 1)[1])
        package[rels_name] = etree.tostring(rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    package[new_name] = etree.tostring(layout, xml_declaration=True, encoding="UTF-8", standalone=True)
    package[new_name.replace("slideLayouts/", "slideLayouts/_rels/") + ".rels"] = etree.tostring(layout_rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    # register the layout with its master and the package
    master_rel = next(rel for rel in layout_rels if rel.get("Type").endswith("/slideMaster"))
    master_name = "ppt/slideMasters/" + master_rel.get("Target").rsplit("/", 1)[1]
    master_rels_name = master_name.replace("slideMasters/", "slideMasters/_rels/") + ".rels"
    master_rels = etree.fromstring(package[master_rels_name])
    rid = f"rIdLayout{len(master_rels) + 1}"
    rel = etree.SubElement(master_rels, f"{{{REL_NS}}}Relationship")
    rel.set("Id", rid)
    rel.set("Type", LAYOUT_REL)
    rel.set("Target", "../slideLayouts/" + new_name.rsplit("/", 1)[1])
    package[master_rels_name] = etree.tostring(master_rels, xml_declaration=True, encoding="UTF-8", standalone=True)
    master = etree.fromstring(package[master_name])
    id_list = master.find("p:sldLayoutIdLst", NS)
    presentation = etree.fromstring(package["ppt/presentation.xml"])
    used = [int(node.get("id")) for node in list(id_list) + list(presentation.iter(q("p:sldMasterId")))]
    entry = etree.SubElement(id_list, q("p:sldLayoutId"))
    entry.set("id", str(max(used + [2147483648]) + 1))
    entry.set(f"{{{R_NS}}}id", rid)
    package[master_name] = etree.tostring(master, xml_declaration=True, encoding="UTF-8", standalone=True)
    types = etree.fromstring(package["[Content_Types].xml"])
    override = etree.SubElement(types, "{http://schemas.openxmlformats.org/package/2006/content-types}Override")
    override.set("PartName", "/" + new_name)
    override.set("ContentType", "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml")
    package["[Content_Types].xml"] = etree.tostring(types, xml_declaration=True, encoding="UTF-8", standalone=True)
    report["chrome"] = {"objects": len(chrome), "slides": len(members), "page_number_field": any(key[0] == "sldnum" for key in chrome)}


def convert(source: Path, target: Path, chrome: bool = True) -> dict:
    report = {"source": str(source), "slides": {}}
    with zipfile.ZipFile(source) as archive:
        ratio = LINE_RATIO
        fonts = Fonts(archive)
        presentation = etree.fromstring(archive.read("ppt/presentation.xml"))
        size = presentation.find("p:sldSz", NS)
        slide_size = (int(size.get("cx")), int(size.get("cy")))
        scratch = target.with_suffix(".tmp")
        package = {info.filename: archive.read(info.filename) for info in archive.infolist()}
        infos = {info.filename: info for info in archive.infolist()}
    slides, slide_rels = {}, {}
    for name in [n for n in package if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]:
        rels, kinds = {}, {}
        rel_name = name.replace("slides/", "slides/_rels/") + ".rels"
        if rel_name in package:
            for rel in etree.fromstring(package[rel_name]):
                rels[rel.get("Id")] = rel.get("Target", "")
                kinds[rel.get("Target", "")] = rel.get("Type")
        slides[name], stats = process_slide(package[name], slide_size, ratio, fonts, rels)
        slide_rels[name], slide_rels[name + "#types"] = rels, kinds
        report["slides"][name.rsplit("/", 1)[1]] = stats
    if chrome:
        try:
            promote_chrome(slides, slide_rels, package, report)
        except Exception as exc:  # noqa: BLE001 - the deck is still right without it
            report["chrome"] = {"error": f"{type(exc).__name__}: {exc}"}
    package.update(slides)
    with zipfile.ZipFile(scratch, "w", zipfile.ZIP_DEFLATED) as out:
        for name, data in package.items():
            out.writestr(infos.get(name, name), data)
    scratch.replace(target)
    totals = {k: sum(s.get(k, 0) for s in report["slides"].values())
              for k in ("texts", "adopted", "hosts", "stacked", "stacks", "reflowed", "single", "joined", "paragraphs", "numbered", "titles", "rules", "named", "described", "glued",
                        "bullets_cleared")}
    notes: dict[str, int] = {}
    for stats in report["slides"].values():
        for reason, count in (stats.get("notes") or {}).items():
            notes[reason] = notes.get(reason, 0) + count
    left: dict[str, int] = {}
    for stats in report["slides"].values():
        for reason, count in stats["left"].items():
            left[reason] = left.get(reason, 0) + count
    report["totals"] = {**totals, "left": left, "notes": notes, "chrome": report.get("chrome")}
    return report


def verify(before: Path, after: Path) -> int:
    from PIL import Image, ImageChops, ImageFilter
    worst = 0.0
    for first in sorted(before.glob("slide-*.png")):
        second = after / first.name
        if not second.is_file():
            print(f"{first.name}: missing after")
            continue
        a, b = Image.open(first).convert("L"), Image.open(second).convert("L")
        if a.size != b.size:
            b = b.resize(a.size)
        dark_a, dark_b = (img.point(lambda v: 255 if v < 150 else 0) for img in (a, b))
        near_a, near_b = (img.filter(ImageFilter.MaxFilter(5)) for img in (dark_a, dark_b))
        diff = ImageChops.lighter(ImageChops.subtract(dark_a, near_b), ImageChops.subtract(dark_b, near_a))
        ink = max(1, sum(dark_a.histogram()[255:]))
        share = sum(diff.histogram()[255:]) / ink
        worst = max(worst, share)
        print(f"{first.name}: {share * 100:.2f}% of the ink moved by more than 2 px; region {diff.getbbox()}")
    print(f"worst slide {worst * 100:.2f}%")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("deck", nargs="?")
    parser.add_argument("-o", "--output")
    parser.add_argument("--in-place", action="store_true", help="replace the deck; the exporter's original is kept under <exports>/floating-text/")
    parser.add_argument("--report")
    parser.add_argument("--keep-chrome-on-slides", action="store_true", help="do not move the repeated header and footer objects to a slide layout")
    parser.add_argument("--verify", nargs=2, metavar=("BEFORE_DIR", "AFTER_DIR"))
    args = parser.parse_args()
    if args.verify:
        return verify(Path(args.verify[0]), Path(args.verify[1]))
    if not args.deck:
        parser.error("a deck is required")
    source = Path(args.deck).resolve()
    if args.in_place:
        keep = source.parent / "floating-text"
        keep.mkdir(exist_ok=True)
        shutil.copy2(source, keep / source.name)
        target = source
    else:
        target = Path(args.output).resolve() if args.output else source.with_name(source.stem + ".text-in-shapes.pptx")
    report = convert(source, target, chrome=not args.keep_chrome_on_slides)
    totals = report["totals"]
    inside = totals["adopted"] + totals["stacked"]
    print(f"{target.name}: {totals['texts']} text boxes -> {totals['hosts'] + totals['stacks'] + totals['single']} text objects: {totals['joined']} one-line texts joined into "
          f"{totals['paragraphs']} paragraphs ({totals['reflowed']} paragraphs now wrap), {totals['adopted']} texts inside {totals['hosts']} shapes, {totals['stacked']} in "
          f"{totals['stacks']} heading-and-body blocks, {totals['titles']} real slide titles, {totals['numbered']} numbered-list items; {totals['single']} single boxes; {totals['named']} objects named after their text, "
          f"{totals['rules']} hairlines made real lines, {totals['glued']} straight arrows glued to their boxes as connectors, {totals['described']} pictures given alt text"
          + (f", {totals['bullets_cleared']} paragraphs kept free of an inherited or empty bullet" if totals.get("bullets_cleared") else ""))
    moved = totals.get("chrome") or {}
    if moved.get("objects"):
        print(f"  header and footer: {moved['objects']} repeated objects moved from {moved['slides']} slides to one layout"
              + ("; the page number is a real field" if moved.get("page_number_field") else ""))
    elif moved.get("error"):
        print(f"  header and footer left on the slides: {moved['error']}")
    for reason, count in totals["notes"].items():
        print(f"  note: {count:4d}  {reason}")
    for reason, count in sorted(totals["left"].items(), key=lambda pair: -pair[1]):
        print(f"  left: {count:4d}  {reason}")
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
