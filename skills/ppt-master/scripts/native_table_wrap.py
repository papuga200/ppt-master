#!/usr/bin/env python3
"""Where PowerPoint will wrap a native table's cells differently from the browser preview - predicted while the page is drawn.

    native_table_wrap.py <page.svg> [--json]

A table marked `data-pptx-replace-with="table"` is exported as a real PowerPoint table: the JSON payload's cells, laid out by
PowerPoint in the exporter's column widths less the cell margins it writes. The browser draws the fallback `<text>` instead,
which never wraps. So a header the author measured by eye (`Days`, `Hours`, `USD/h` in 57-65 px columns, 14 px bold Century
Gothic) sits on one line in the preview and on two in PowerPoint: `Day|s`, the row grows from 28 to 42 px and the table runs
into the boxes under it (campaign tests T2 and T7, 29 Sep 2026). pptx_parity.py sees it after export; this sees it before.

How: the exporter itself converts the table (svg_to_pptx `convert_native_object`, the same code the deck goes through), and the
emitted `<a:tbl>` gives the column widths (`a:gridCol`), planned row heights (`a:tr/@h`), cell margins (`a:tcPr/@marL..marB`,
PowerPoint's defaults 0.1 in / 0.05 in when absent) and every run's face, size and weight. Each paragraph is then broken the
way PowerPoint breaks it - greedy, at spaces and after hyphens, a word wider than the line broken between characters - with the
installed font's real advance widths; a line is 1.2 x its largest size (PowerPoint's single spacing, measured 20 Sep 2026) and a
row is the taller of its planned height and its tallest cell (lines plus top and bottom margins).

Findings (the page_lint shape: kind, severity, hard, rect, message):
  NATIVE_WORD_SPLIT  certain  one word is wider than its cell's text width: PowerPoint breaks it mid-word.
  NATIVE_WRAP_DRIFT  flagged  PowerPoint will set a cell on more lines than the SVG draws.
  NATIVE_ROW_GROWTH  flagged  a row will grow more than 2 px and the table's new bottom reaches the next shape below it
                              (a note when it grows into free space).
Calibrated against PowerPoint's own layout of 34 measured tables (1,002 cell paragraphs, 241 rows; F03C2_REPORT.md): every line
count and every row height predicted, rows to 0.0 px.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
SVG_NS = "http://www.w3.org/2000/svg"
EMU_PER_PX = 9525
# PowerPoint's own a:tcPr margins when the exporter writes none: 0.1 in left/right, 0.05 in top/bottom (ECMA-376 21.1.3.17).
DEFAULT_MARGINS_EMU = (91440, 91440, 45720, 45720)  # left, right, top, bottom
LINE_RATIO = 1.2         # PowerPoint single spacing: a line is 1.2 x the font size, whatever the font
GROWTH_TOLERANCE = 2.0   # px a row may grow before it is reported
FIT_SLACK = 0.25         # px a line may exceed the text width and still fit: PowerPoint kept a line 0.02 px over (kirkland2 s9) and broke
                         # every line that was 0.48 px or more over; any slack from 0.05 to 0.5 px predicts all 1,002 measured cell
                         # paragraphs right (F03C2_REPORT.md)
BREAK_AFTER = "-\u2010\u2013\u2014"  # PowerPoint also breaks after a hyphen or dash followed by a letter or digit (after a slash: the
                                     # measurements cannot tell - `USD/|h` breaks there either way - so a slash is not a break here)


def _q(tag: str, ns: str = A_NS) -> str:
    return f"{{{ns}}}{tag}"


# ------------------------------------------------------------------------------------------------------------------------------
# 1. The table as the exporter writes it
# ------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Run:
    text: str
    face: str
    px: float
    bold: bool = False
    italic: bool = False


@dataclass
class Paragraph:
    runs: list[Run]
    line_pct: float | None = None  # a:lnSpc/a:spcPct, 1.0 = single

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass
class Cell:
    row: int  # 0-based
    col: int
    paragraphs: list[Paragraph]
    margins: tuple[float, float, float, float]  # left, right, top, bottom, px
    span: int = 1
    row_span: int = 1
    covered: bool = False  # the continuation of a merged cell

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.paragraphs)


@dataclass
class Table:
    name: str
    x: float
    y: float
    width: float
    height: float
    cols: list[float]
    rows: list[float]
    cells: list[Cell] = field(default_factory=list)

    def column_left(self, col: int) -> float:
        return self.x + sum(self.cols[:col])

    def row_top(self, row: int) -> float:
        return self.y + sum(self.rows[:row])


def _emu(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_table_frame(frame: ET.Element, theme: dict | None = None, default_face: str = "Calibri", empty_hpt: int = 1800) -> Table | None:
    """A `p:graphicFrame` holding an `a:tbl`, in px on the 1280-px slide. `theme` maps +mn-lt/+mj-lt to faces. `empty_hpt`: the size
    PowerPoint gives an empty paragraph with no `a:endParaRPr` - the master's other-text size, not the empty run's (kirkland2 s11: an
    empty 9 pt cell took a 12 pt line under its template and an 18 pt line without it)."""
    tbl = frame.find(f".//{_q('tbl')}")
    if tbl is None:
        return None
    theme = theme or {}
    name_el = frame.find(f".//{_q('cNvPr', P_NS)}")
    off, ext = frame.find(f".//{_q('off')}"), frame.find(f".//{_q('ext')}")
    x = _emu(off.get("x") if off is not None else 0, 0) / EMU_PER_PX
    y = _emu(off.get("y") if off is not None else 0, 0) / EMU_PER_PX
    width = _emu(ext.get("cx") if ext is not None else 0, 0) / EMU_PER_PX
    height = _emu(ext.get("cy") if ext is not None else 0, 0) / EMU_PER_PX
    cols = [_emu(col.get("w"), 0) / EMU_PER_PX for col in tbl.findall(f"{_q('tblGrid')}/{_q('gridCol')}")]
    table = Table(name=(name_el.get("name") if name_el is not None else "") or "table", x=x, y=y, width=width, height=height, cols=cols, rows=[])
    for r, tr in enumerate(tbl.findall(_q("tr"))):
        table.rows.append(_emu(tr.get("h"), 0) / EMU_PER_PX)
        for c, tc in enumerate(tr.findall(_q("tc"))):
            covered = tc.get("hMerge") in ("1", "true") or tc.get("vMerge") in ("1", "true")
            pr = tc.find(_q("tcPr"))
            margins = tuple(_emu(pr.get(attr) if pr is not None else None, default) / EMU_PER_PX
                            for attr, default in zip(("marL", "marR", "marT", "marB"), DEFAULT_MARGINS_EMU))
            paragraphs = []
            for p in tc.findall(f"{_q('txBody')}/{_q('p')}"):
                pct = p.find(f"{_q('pPr')}/{_q('lnSpc')}/{_q('spcPct')}")
                runs = []
                for child in p:
                    if child.tag == _q("r"):
                        props = child.find(_q("rPr"))
                        t = child.find(_q("t"))
                        runs.append(_run((t.text or "") if t is not None else "", props, theme, default_face))
                    elif child.tag == _q("br"):
                        runs.append(_run("\n", child.find(_q("rPr")), theme, default_face))
                if not "".join(run.text for run in runs):  # an empty paragraph takes its line at its end-of-paragraph size
                    end = p.find(_q("endParaRPr"))
                    if end is None or not end.get("sz"):
                        end = ET.Element(_q("endParaRPr"), {"sz": str(empty_hpt)})
                    runs = [_run("", end, theme, default_face)]
                paragraphs.append(Paragraph(runs, _emu(pct.get("val"), 100000) / 100000 if pct is not None else None))
            table.cells.append(Cell(r, c, paragraphs, margins, span=_emu(tc.get("gridSpan"), 1), row_span=_emu(tc.get("rowSpan"), 1), covered=covered))
    return table


def _run(text: str, props, theme: dict, default_face: str) -> Run:
    size_hpt = _emu(props.get("sz") if props is not None else None, 1800)
    face = default_face
    latin = props.find(_q("latin")) if props is not None else None
    if latin is not None and latin.get("typeface"):
        face = latin.get("typeface")
    face = theme.get(face, face)
    if face.startswith("+"):
        face = theme.get("+mn-lt", default_face)
    return Run(text, face, size_hpt / 100 * 96 / 72, bold=props is not None and props.get("b") in ("1", "true"),
               italic=props is not None and props.get("i") in ("1", "true"))


def tables_in_slide_xml(xml: str | bytes, theme: dict | None = None, default_face: str = "Calibri", empty_hpt: int = 1800) -> list[Table]:
    root = ET.fromstring(xml if isinstance(xml, bytes) else xml.encode("utf-8"))
    tables = []
    for frame in root.iter(_q("graphicFrame", P_NS)):
        table = parse_table_frame(frame, theme, default_face, empty_hpt)
        if table is not None:
            tables.append(table)
    return tables


def _is_table_marker(elem: ET.Element) -> bool:
    return (elem.get("data-pptx-replace-with") or "").strip().lower() == "table"


def _trimmed_svg(root: ET.Element) -> ET.Element:
    """The page with only its native tables, their ancestors (transforms, inherited type) and definitions: the rest of the page
    cannot change a table's XML and may fail the exporter's checks for reasons of its own (a missing image)."""
    keep: set[int] = set()

    def mark(elem: ET.Element, path: list[ET.Element]) -> bool:
        if _is_table_marker(elem):
            keep.update(id(e) for e in path + [elem])
            for sub in elem.iter():
                keep.add(id(sub))
            return True
        found = False
        for child in elem:
            found |= mark(child, path + [elem])
        return found

    mark(root, [])
    clone = copy.deepcopy(root)
    originals = list(root.iter())
    copies = list(clone.iter())
    keep_copy = {id(c) for o, c in zip(originals, copies) if id(o) in keep}

    def prune(elem: ET.Element) -> None:
        for child in list(elem):
            local = child.tag.rsplit("}", 1)[-1]
            if id(child) in keep_copy:
                prune(child)
            elif local not in ("defs", "style"):
                elem.remove(child)
    prune(clone)
    return clone


def exporter_tables(svg: Path) -> list[Table]:
    """The page's native tables exactly as `svg_to_pptx --native-charts-and-tables` writes them."""
    root = ET.parse(str(svg)).getroot()
    if not any(_is_table_marker(e) for e in root.iter()):
        return []
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    from svg_to_pptx.native_objects.fallback_hash import stamp_native_fallback_baseline
    trimmed = _trimmed_svg(root)
    for marker in [e for e in trimmed.iter() if _is_table_marker(e)]:
        # the page may be mid-edit, its fallback not yet re-stamped: the exporter would refuse it, but the table's layout is what
        # matters here (the exporter's own parity gate reports a stale or missing stamp separately)
        stamp_native_fallback_baseline(marker, document_root=trimmed)
    ET.register_namespace("", SVG_NS)
    with tempfile.TemporaryDirectory(prefix="tblwrap-") as scratch:
        page = Path(scratch) / svg.name
        page.write_bytes(ET.tostring(trimmed, encoding="utf-8"))
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            xml = convert_svg_to_slide_shapes(page, resource_root=Path(scratch), native_objects=True)[0]
    return tables_in_slide_xml(xml, default_face=_page_font(root))


def _page_font(root: ET.Element) -> str:
    """A table with no face of its own is set in the theme's body font; on a page, the first family the page names."""
    for elem in root.iter():
        family = elem.get("font-family") or (re.search(r"font-family\s*:\s*([^;]+)", elem.get("style") or "") or [None, None])[1]
        if family:
            return family.split(",")[0].strip().strip("'\"")
    return "Calibri"


# ------------------------------------------------------------------------------------------------------------------------------
# 2. Font metrics
# ------------------------------------------------------------------------------------------------------------------------------
class Metrics:
    """Advance widths in px from the installed font files, character by character (PowerPoint applies no kerning to a run
    unless `kern` is set, and the exporter never sets it)."""

    UNITS = 1000  # measure at a large size so hinting does not round the advances

    def __init__(self) -> None:
        from pptx_text_in_shapes import Fonts
        Fonts._build_index()
        self.index = Fonts._index or {}
        self.fonts: dict = {}
        self.advances: dict = {}
        self.missing: set[str] = set()

    def _font(self, face: str, bold: bool, italic: bool):
        key = (face.lower(), bold, italic)
        if key not in self.fonts:
            found = (self.index.get((face.lower(), bold, italic)) or self.index.get((face.lower(), bold, False))
                     or self.index.get((face.lower(), False, False)))
            font = None
            if found:
                try:
                    from PIL import ImageFont
                    font = ImageFont.truetype(found[0], size=self.UNITS, index=found[1])
                except Exception:  # noqa: BLE001
                    font = None
            if font is None:
                self.missing.add(face)
            self.fonts[key] = font
        return self.fonts[key]

    def installed(self, face: str) -> bool:
        return self._font(face, False, False) is not None

    def char_width(self, char: str, run: Run) -> float:
        key = (run.face.lower(), run.bold, run.italic, char)
        if key not in self.advances:
            font = self._font(run.face, run.bold, run.italic)
            if font is not None:
                self.advances[key] = font.getlength(char) / self.UNITS
            else:
                from text_measure import measure_text
                self.advances[key] = measure_text(char, size=self.UNITS, family=run.face, weight="bold" if run.bold else "normal",
                                                  include_headroom=False) / self.UNITS
        return self.advances[key] * run.px

    def width(self, text: str, run: Run) -> float:
        return sum(self.char_width(ch, run) for ch in text)


_METRICS: list = [None]


def metrics() -> Metrics:
    if _METRICS[0] is None:
        _METRICS[0] = Metrics()
    return _METRICS[0]


# ------------------------------------------------------------------------------------------------------------------------------
# 3. PowerPoint's line breaking
# ------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Line:
    text: str
    px: float  # the largest size on the line
    split: bool = False  # ends inside a word (PowerPoint had no break opportunity that fits)
    word: str = ""  # the word it breaks, when split
    word_px: float = 0.0  # that word's width


def _chars(paragraph: Paragraph, m: Metrics) -> list[tuple[str, float, float]]:
    """(character, advance px, size px) for each character of the paragraph."""
    out = []
    for run in paragraph.runs:
        for ch in run.text:
            out.append((ch, 0.0 if ch == "\n" else m.char_width(ch, run), run.px))
    return out


def _segments(chars: list[tuple[str, float, float]]) -> list[tuple[int, int]]:
    """Unbreakable pieces [start, end): a piece carries its trailing spaces; a break is allowed after spaces, after a hyphen, dash
    or slash followed by a letter or digit, and at a hard line break."""
    pieces, start, i, n = [], 0, 0, len(chars)
    while i < n:
        ch = chars[i][0]
        if ch == "\n":
            if i > start:
                pieces.append((start, i))
            pieces.append((i, i + 1))
            start = i = i + 1
            continue
        if ch.isspace():
            while i < n and chars[i][0].isspace() and chars[i][0] != "\n":
                i += 1
            pieces.append((start, i))
            start = i
            continue
        if ch in BREAK_AFTER and i > start and i + 1 < n and chars[i + 1][0].isalnum():
            pieces.append((start, i + 1))
            start = i = i + 1
            continue
        i += 1
    if start < n:
        pieces.append((start, n))
    return pieces


def break_paragraph(paragraph: Paragraph, available: float, m: Metrics | None = None, slack: float | None = None) -> list[Line]:
    m = m or metrics()
    slack = FIT_SLACK if slack is None else slack
    limit = available + slack
    chars = _chars(paragraph, m)
    base_px = max((run.px for run in paragraph.runs), default=18 * 96 / 72)
    if not chars:
        return [Line("", base_px)]
    lines: list[Line] = []
    current: list[int] = []  # indices of the characters on the line
    width = 0.0  # width of the line without its trailing spaces
    pending = 0.0  # trailing spaces of the line so far

    def flush(split: bool = False, word: str = "", word_px: float = 0.0) -> None:
        nonlocal current, width, pending
        text = "".join(chars[i][0] for i in current).rstrip(" ")
        sizes = [chars[i][2] for i in current] or [base_px]
        lines.append(Line(text, max(sizes), split, word, word_px))
        current, width, pending = [], 0.0, 0.0

    for start, end in _segments(chars):
        if chars[start][0] == "\n":
            flush()
            continue
        body_end = end
        while body_end > start and chars[body_end - 1][0].isspace():
            body_end -= 1
        body = sum(chars[i][1] for i in range(start, body_end))
        tail = sum(chars[i][1] for i in range(body_end, end))
        if current and width + pending + body <= limit:
            current.extend(range(start, end))
            width, pending = width + pending + body, tail
            continue
        if current:
            flush()
        if body <= limit:
            current.extend(range(start, end))
            width, pending = body, tail
            continue
        # a word wider than the line: PowerPoint fills the line character by character
        i = start
        while i < body_end:
            taken, used = [], 0.0
            while i < body_end and (not taken or used + chars[i][1] <= limit):
                used += chars[i][1]
                taken.append(i)
                i += 1
            current.extend(taken)
            width = used
            if i < body_end:
                flush(True, "".join(chars[k][0] for k in range(start, body_end)), body)
        current.extend(range(body_end, end))
        pending = tail
    if current or not lines:
        flush()
    return lines


@dataclass
class CellLayout:
    cell: Cell
    available: float  # text width, px
    lines: list[list[Line]]  # per paragraph
    text_height: float
    height: float  # text plus top and bottom margins

    @property
    def line_count(self) -> int:
        return sum(len(p) for p in self.lines)


def layout_cell(table: Table, cell: Cell, m: Metrics | None = None, slack: float | None = None) -> CellLayout:
    m = m or metrics()
    column = sum(table.cols[cell.col: cell.col + max(1, cell.span)])
    available = max(1.0, column - cell.margins[0] - cell.margins[1])
    per_paragraph, height = [], 0.0
    for paragraph in cell.paragraphs:
        lines = break_paragraph(paragraph, available, m, slack)
        per_paragraph.append(lines)
        height += sum(line.px * LINE_RATIO * (paragraph.line_pct or 1.0) for line in lines)
    return CellLayout(cell, available, per_paragraph, height, height + cell.margins[2] + cell.margins[3])


@dataclass
class TableLayout:
    table: Table
    cells: list[CellLayout]
    rows: list[float]  # PowerPoint's row heights, px

    @property
    def growth(self) -> float:
        return sum(self.rows) - sum(self.table.rows)


def layout_table(table: Table, m: Metrics | None = None, slack: float | None = None) -> TableLayout:
    m = m or metrics()
    cells = [layout_cell(table, cell, m, slack) for cell in table.cells if not cell.covered]
    rows = list(table.rows)
    for layout in cells:
        if layout.cell.row_span <= 1 and layout.cell.row < len(rows):
            rows[layout.cell.row] = max(rows[layout.cell.row], layout.height)
    for layout in cells:  # a merged cell that needs more than its rows grows its last row
        cell = layout.cell
        if cell.row_span > 1:
            last = min(len(rows), cell.row + cell.row_span) - 1
            short = layout.height - sum(rows[cell.row: last + 1])
            if short > 0:
                rows[last] += short
    return TableLayout(table, cells, rows)


# ------------------------------------------------------------------------------------------------------------------------------
# 4. The page around the table: what the SVG draws in each cell, and what sits below the table
# ------------------------------------------------------------------------------------------------------------------------------
def _obstacles(root: ET.Element) -> list[tuple[str, tuple[float, float, float, float], bool]]:
    """(label, bounds, is_text) of every painted shape and text on the page outside its native tables, in px."""
    from svg_to_pptx.drawingml.context import IDENTITY_MATRIX
    from svg_to_pptx.drawingml.utils import matrix_multiply, parse_transform_matrix
    from svg_to_pptx.native_objects.marker_common import _fallback_shape_records
    clone = copy.deepcopy(root)

    def strip(elem: ET.Element) -> None:
        for child in list(elem):
            if _is_table_marker(child) or (child.get("data-pptx-replace-with") or "").strip():
                elem.remove(child)
            else:
                strip(child)
    strip(clone)
    out = []
    for record in _fallback_shape_records(clone):
        out.append((record.labels[-1] if record.labels else record.tag, tuple(record.bounds), False))
    m = metrics()

    def texts(elem: ET.Element, matrix, size: float, family: str, weight: str, anchor: str, label: str) -> None:
        local = elem.tag.rsplit("}", 1)[-1]
        if local in ("defs", "metadata", "clipPath", "mask", "style") or elem.get("display") == "none":
            return
        if elem.get("transform"):
            matrix = matrix_multiply(matrix, parse_transform_matrix(elem.get("transform")))
        style = elem.get("style") or ""

        def attr(name: str, inherited: str) -> str:
            found = re.search(rf"(?:^|;)\s*{name}\s*:\s*([^;]+)", style)
            return (found.group(1) if found else elem.get(name) or inherited).strip()
        size = _float(attr("font-size", str(size)), size)
        family, weight, anchor = attr("font-family", family), attr("font-weight", weight), attr("text-anchor", anchor)
        label = elem.get("id") or label
        if local == "text":
            lines = _text_lines(elem)
            if not lines:
                return
            run = Run("", family.split(",")[0].strip().strip("'\""), size, bold=weight in ("bold", "600", "700", "800", "900"))
            for x, y, content in lines:
                w = m.width(content, run)
                x0 = x - (w if anchor == "end" else w / 2 if anchor == "middle" else 0)
                a, b, c, d, e, f = matrix
                corners = [(a * px + c * py + e, b * px + d * py + f) for px, py in ((x0, y - 0.8 * size), (x0 + w, y + 0.25 * size))]
                xs, ys = [p[0] for p in corners], [p[1] for p in corners]
                out.append((f"`{content.strip()[:40]}`", (min(xs), min(ys), max(xs), max(ys)), True))
            return
        for child in elem:
            texts(child, matrix, size, family, weight, anchor, label)
    texts(clone, IDENTITY_MATRIX, 16.0, "Calibri", "normal", "start", "")
    return out


def _float(value, default: float) -> float:
    found = re.match(r"\s*(-?[\d.]+)", str(value or ""))
    return float(found.group(1)) if found else default


def _text_lines(text: ET.Element) -> list[tuple[float, float, str]]:
    """(x, baseline y, content) of each visual line of an SVG `<text>`."""
    x, y = _float((text.get("x") or "0").split()[0] if (text.get("x") or "").strip() else 0, 0), _float((text.get("y") or "0").split()[0] if (text.get("y") or "").strip() else 0, 0)
    lines = [[x, y, text.text or ""]]
    for tspan in text:
        if tspan.tag.rsplit("}", 1)[-1] != "tspan":
            continue
        new_x, new_y = lines[-1][0], lines[-1][1]
        if tspan.get("x") is not None:
            new_x = _float(tspan.get("x").split()[0], new_x)
        if tspan.get("y") is not None:
            new_y = _float(tspan.get("y").split()[0], new_y)
        if tspan.get("dy") is not None:
            new_y += _float(tspan.get("dy").split()[0], 0)
        content = "".join(tspan.itertext())
        if abs(new_y - lines[-1][1]) > 0.5 and lines[-1][2].strip():
            lines.append([new_x, new_y, content])
        else:
            lines[-1][1] = new_y
            lines[-1][2] += content
        if tspan.tail:
            lines[-1][2] += tspan.tail
    return [(lx, ly, content) for lx, ly, content in lines if content.strip()]


def svg_cell_lines(svg: Path, table: Table) -> dict[tuple[int, int], int]:
    """How many lines the SVG draws in each cell of the table (only cells whose text is found in the drawn fallback)."""
    from pptx_parity import match_lines, svg_lines
    lines = [line for line in svg_lines(svg) if line.get("in_table")]
    top, bottom = table.y - 2, table.y + sum(table.rows) + 2
    lines = [line for line in lines if top <= line["baseline"] <= bottom]  # this table's lines (a page may hold two)
    out: dict[tuple[int, int], int] = {}
    used: set = set()
    for cell in table.cells:
        if cell.covered:
            continue
        count, found_all = 0, True
        for paragraph in cell.paragraphs:
            if not paragraph.text.strip():
                continue
            found = match_lines(paragraph.text, lines, used)
            if not found:
                found_all = False
                break
            count += len(found)
        if found_all and count:
            out[(cell.row, cell.col)] = count
    return out


# ------------------------------------------------------------------------------------------------------------------------------
# 5. Findings
# ------------------------------------------------------------------------------------------------------------------------------
def _describe(run: Run) -> str:
    return f"{round(run.px, 1):g} px{' bold' if run.bold else ''}{' italic' if run.italic else ''} {run.face}"


def _first_run(cell: Cell) -> Run:
    return next((run for p in cell.paragraphs for run in p.runs if run.text.strip()), cell.paragraphs[0].runs[0])


def _width_for_lines(table: Table, cell: Cell, lines: int, m: Metrics, slack: float | None) -> float:
    """The narrowest text width at which PowerPoint sets the cell on at most `lines` lines (px, to 0.5 px)."""
    def count(width: float) -> int:
        return sum(len(break_paragraph(p, width, m, slack)) for p in cell.paragraphs)
    low = max(1.0, sum(table.cols[cell.col: cell.col + cell.span]) - cell.margins[0] - cell.margins[1])
    high = max([sum(m.width(r.text, r) for r in p.runs) for p in cell.paragraphs] + [low]) + 1.0
    if count(high) > lines:
        return high
    while high - low > 0.5:
        middle = (low + high) / 2
        low, high = (low, middle) if count(middle) <= lines else (middle, high)
    return high


def predict(svg: Path, m: Metrics | None = None, slack: float | None = None) -> list[dict]:
    """The findings for one page, in page_lint's shape."""
    m = m or metrics()
    tables = exporter_tables(svg)
    if not tables:
        return []
    root = ET.parse(str(svg)).getroot()
    obstacles = None
    findings: list[dict] = []
    for table in tables:
        layout = layout_table(table, m, slack)
        drawn = svg_cell_lines(svg, table)
        split_cells = set()
        for cl in layout.cells:
            cell = cl.cell
            left, top = table.column_left(cell.col), table.row_top(cell.row)
            rect = [round(left, 1), round(top, 1), round(left + sum(table.cols[cell.col: cell.col + cell.span]), 1),
                    round(top + table.rows[cell.row], 1)]
            column = sum(table.cols[cell.col: cell.col + cell.span])
            margins = cell.margins[0] + cell.margins[1]
            where = f"table `{table.name}` row {cell.row + 1} column {cell.col + 1}"
            split = [line for lines in cl.lines for line in lines if line.split]
            shown = " | ".join(_short(line.text, 30) for lines in cl.lines for line in lines)
            if split:
                word, need = split[0].word, split[0].word_px
                wider = max(1, math.ceil(need - cl.available))
                measured = m.installed(_first_run(cell).face)  # certain only with the real font's widths
                findings.append({
                    "kind": "NATIVE_WORD_SPLIT", "severity": "blocker", "hard": measured, "rect": rect,
                    "message": (f"{where}: PowerPoint will break `{word}` mid-word (`{shown}`); the browser preview does not wrap it. "
                                f"Column {cell.col + 1} needs {need + margins:.0f} px for `{word}` at {_describe(_first_run(cell))} plus "
                                f"{margins:.0f} px margins; it is {column:.0f} px: widen it by at least {wider} px (take the width from a wider column) "
                                "or shorten the text; never shrink the type below the floor"
                                + ("" if measured else f" (estimated: {_first_run(cell).face} is not installed here)")),
                    "table": table.name, "row": cell.row + 1, "col": cell.col + 1, "need_px": round(need + margins, 1), "column_px": round(column, 1)})
                split_cells.add((cell.row, cell.col))
            svg_count = drawn.get((cell.row, cell.col))
            if svg_count is not None and cl.line_count > svg_count and (cell.row, cell.col) not in split_cells:
                need = _width_for_lines(table, cell, svg_count, m, slack)
                wider = max(1, math.ceil(need - cl.available))
                findings.append({
                    "kind": "NATIVE_WRAP_DRIFT", "severity": "blocker", "hard": False, "rect": rect,
                    "message": (f"{where}: `{_short(cell.text)}` is {svg_count} line(s) in the SVG and PowerPoint will set it on {cl.line_count} "
                                f"(`{shown}`). At {_describe(_first_run(cell))} it needs {need:.0f} px of text width for {svg_count} line(s); the "
                                f"cell gives {cl.available:.0f} px ({column:.0f} px column less {margins:.0f} px margins). Widen column {cell.col + 1} by at least "
                                f"{wider} px, shorten the text, or draw PowerPoint's break in the SVG and give the row the height of "
                                f"{cl.line_count} lines ({cl.height:.0f} px); never shrink the type below the floor"),
                    "table": table.name, "row": cell.row + 1, "col": cell.col + 1, "svg_lines": svg_count, "ppt_lines": cl.line_count})
        grown = [(r, table.rows[r], layout.rows[r]) for r in range(len(table.rows)) if layout.rows[r] - table.rows[r] > GROWTH_TOLERANCE]
        if not grown:
            continue
        drawn_bottom = table.y + sum(table.rows)
        new_bottom = table.y + sum(layout.rows)
        if obstacles is None:
            obstacles = _obstacles(root)
        hit = _first_hit(table, drawn_bottom, new_bottom, obstacles)
        detail = []
        for r, before, after in grown[:4]:
            tallest = max((cl for cl in layout.cells if cl.cell.row == r), key=lambda cl: cl.height)
            detail.append(f"row {r + 1}: drawn {before:.0f} px, PowerPoint {after:.0f} px (column {tallest.cell.col + 1}: `{_short(tallest.cell.text, 30)}` "
                          f"takes {tallest.line_count} line(s) = {tallest.text_height:.0f} px + {tallest.cell.margins[2] + tallest.cell.margins[3]:.0f} px margins)")
        growth = new_bottom - drawn_bottom
        entry = {"kind": "NATIVE_ROW_GROWTH", "table": table.name, "growth_px": round(growth, 1),
                 "rect": [round(table.x, 1), round(table.y + sum(table.rows[: grown[0][0]]), 1), round(table.x + table.width, 1), round(new_bottom, 1)],
                 "rows": [{"row": r + 1, "drawn_px": round(b, 1), "ppt_px": round(a, 1)} for r, b, a in grown]}
        if hit is None:  # the table grows into free space: worth knowing, not a defect
            findings.append({**entry, "severity": "note", "hard": False,
                             "message": (f"table `{table.name}` will be {growth:.0f} px taller in PowerPoint than drawn - " + "; ".join(detail)
                                         + f" - its bottom moves from y={drawn_bottom:.0f} to y={new_bottom:.0f}, into free space")})
            continue
        label, bounds = hit
        findings.append({**entry, "severity": "blocker", "hard": False,
                         "message": (f"table `{table.name}` will be {growth:.0f} px taller in PowerPoint than drawn - " + "; ".join(detail)
                                     + f" - and its bottom moves from y={drawn_bottom:.0f} to y={new_bottom:.0f}, into {label} (top y={bounds[1]:.0f}). "
                                     "Fix: widen the columns that wrap, shorten their text, or draw the rows at the height PowerPoint needs and move "
                                     "what is below; never shrink the type below the floor")})
    return findings


def _first_hit(table: Table, drawn_bottom: float, new_bottom: float, obstacles) -> tuple[str, tuple] | None:
    """The first thing below the table that its new bottom reaches: a shape or text under it, the bottom edge of a panel it sits
    on, or the bottom of the slide."""
    left, right = table.x, table.x + table.width
    best = None
    for label, (x0, y0, x1, y1), is_text in obstacles:
        if min(right, x1) - max(left, x0) <= 1:
            continue
        if x0 <= left + 1 and x1 >= right - 1 and y0 <= table.y + 1 and y1 >= drawn_bottom - 1:
            if new_bottom > y1 + 0.5:  # a panel the table sits on: the table now runs past its lower edge
                candidate = (f"the lower edge of `{label}` it sits on", (x0, y1, x1, y1))
                if best is None or y1 < best[1][1]:
                    best = candidate
            continue
        if y0 >= drawn_bottom - 1 and y0 < new_bottom - 0.5:
            name = label if is_text else f"`{label}`"
            if not is_text:  # a box: name it by the first text it holds, as a reader would
                inside = [(ty0, tl) for tl, (tx0, ty0, tx1, ty1), t in obstacles
                          if t and x0 - 1 <= (tx0 + tx1) / 2 <= x1 + 1 and y0 - 1 <= (ty0 + ty1) / 2 <= y1 + 1]
                if inside:
                    name += f" (the box holding {min(inside)[1]})"
            candidate = (name, (x0, y0, x1, y1))
            if best is None or y0 < best[1][1]:
                best = candidate
    if best is None and new_bottom > 720 + 0.5:
        best = ("the bottom of the slide", (left, 720.0, right, 720.0))
    return best


def _short(text: str, n: int = 40) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("svg", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    for name in args.svg:
        findings = predict(Path(name))
        if args.json:
            print(json.dumps({"svg": name, "findings": findings}, ensure_ascii=False))
            continue
        print(f"{Path(name).name}: {len(findings)} finding(s)")
        for finding in findings:
            print(f"  {'CERTAIN' if finding['hard'] else 'FLAGGED'} {finding['kind']}: {finding['message']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
