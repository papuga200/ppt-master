#!/usr/bin/env python3
"""Measure how PowerPoint itself lays out an exported deck, and name what differs from the SVG pages.

    pptx_parity.py <deck.pptx> [--project DIR] [--render DIR] [--out parity.json] [--md parity.md]
                   [--no-crops] [--timeout 300] [--measurements FILE]

Every in-loop check (lint, page review, deck review, final lint) judges the browser render of the
SVG. PowerPoint lays text out with its own metrics: a 1.2 x size line pitch, its own advance
widths, cell margins, table rows that grow to fit their text, bullets inherited from layouts. This
tool opens the .pptx in Microsoft PowerPoint through COM (read-only, invisible, closed and quit on
every path, bounded by --timeout) and reads PowerPoint's own layout: every text frame's bound box
and line count, every paragraph's bullet and automatic number, every table row's real height and
every cell's lines. It compares that with what the exporter planned (the frames, the planned row
heights in the file) and, with --project, with the SVG pages (line counts, typed list numbers,
text-anchor of table cells).

Findings, per slide, each {code, severity certain|flagged, slide, shape, message, bbox (1280x720 px)}:

    OVERFLOW         text leaves the slide, or runs out of the box it sits in
    TEXT_COLLISION   text that outgrew its frame now runs into another object (it did not before)
    ROW_GROWTH       a native table row is taller in PowerPoint than planned
    TABLE_OVERLAP    the grown table now reaches into the object below it (or off the slide)
    HEADER_SPLIT     PowerPoint breaks a word across two lines
    LINE_COUNT_DRIFT a paragraph has more lines in PowerPoint than in the SVG
    STRAY_BULLET     a bullet on a paragraph with no visible text (empty or zero-width)
    ACCIDENTAL_BULLET a wrapped "·" separator line became a bullet paragraph
    RENUMBERED       an automatic number differs from the number the SVG showed
    ALIGNMENT_DRIFT  a table cell's alignment differs from the SVG (numeric columns losing right alignment)

Certain findings are defects a reader sees; flagged ones are divergences to look at. With the
PowerPoint render (pptx_render.py output, found next to the deck or given with --render) each
finding gets a crop with its box outlined, saved under <render>/parity/ and printed as an
`IMAGE:` line. Exit 3 when PowerPoint is not available (nothing measured), else 0.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": A, "p": P}
SVG_NS = "http://www.w3.org/2000/svg"
EMU_PER_PT = 12700
BASIS_W = 1280.0
ZERO_WIDTH = "\u200b\u200c\u200d\u2060\ufeff\u00ad"
TOL_PX = 2.5  # below this a difference is anti-aliasing and rounding, not a defect

# ---------------------------------------------------------------------------------------------
# 1. PowerPoint measurement (COM through PowerShell: no Python package needed, as pptx_render.py)
# ---------------------------------------------------------------------------------------------
_MEASURE_PS = r"""
$ErrorActionPreference = 'Stop'
$out = '__OUT__'
function Num($v) { if ($null -eq $v) { return $null } try { return [math]::Round([double]$v, 3) } catch { return $null } }
function Para-Info($p) {
  $info = [ordered]@{}
  $info.text = [string]$p.Text
  try { $f = $p.ParagraphFormat; $info.align = [int]$f.Alignment
        $b = $f.Bullet; $info.bullet_visible = [int]$b.Visible; $info.bullet_type = [int]$b.Type
        if ($b.Type -eq 2) { try { $info.bullet_number = [int]$b.Number } catch {} ; try { $info.bullet_style = [int]$b.Style } catch {} }
        if ($b.Type -eq 1) { try { $info.bullet_char = [int]$b.Character } catch {} }
        if ($b.Visible -ne 0) { try { $info.bullet_text_color = [int]$b.UseTextColor } catch {}; try { $info.bullet_rgb = [int]$b.Font.Fill.ForeColor.RGB } catch {}
                                try { $info.text_rgb = [int]$p.Font.Fill.ForeColor.RGB } catch {}; try { $info.size = Num $p.Font.Size } catch {} }
  } catch { $info.error = 'format' }
  try { $info.bound = @((Num $p.BoundLeft), (Num $p.BoundTop), (Num $p.BoundWidth), (Num $p.BoundHeight)) } catch {}
  $lines = New-Object System.Collections.ArrayList
  try { $n = $p.Lines().Count; for ($j = 1; $j -le $n; $j++) { [void]$lines.Add([string]$p.Lines($j, 1).Text) } } catch {}
  $info.lines = $lines
  return $info
}
function Frame-Info($tf) {
  $info = [ordered]@{}
  $info.margins = @((Num $tf.MarginLeft), (Num $tf.MarginTop), (Num $tf.MarginRight), (Num $tf.MarginBottom))
  try { $info.wrap = [int]$tf.WordWrap } catch {}
  try { $info.autosize = [int]$tf.AutoSize } catch {}
  try { $info.anchor = [int]$tf.VerticalAnchor } catch {}
  $tr = $tf.TextRange
  $info.text = [string]$tr.Text
  try { $info.bound = @((Num $tr.BoundLeft), (Num $tr.BoundTop), (Num $tr.BoundWidth), (Num $tr.BoundHeight)) } catch {}
  try { $info.line_count = [int]$tr.Lines().Count } catch {}
  $paras = New-Object System.Collections.ArrayList
  $count = 0
  try { $count = $tr.Paragraphs().Count } catch {}
  for ($i = 1; $i -le $count; $i++) { [void]$paras.Add((Para-Info $tr.Paragraphs($i, 1))) }
  $info.paragraphs = $paras
  return $info
}
function Shape-Info($sh, $parent, $list) {
  $info = [ordered]@{}
  $info.z = $list.Count
  try { $info.id = [int]$sh.Id } catch {}
  $info.name = [string]$sh.Name
  $info.type = [int]$sh.Type
  $info.parent = $parent
  $info.box = @((Num $sh.Left), (Num $sh.Top), (Num $sh.Width), (Num $sh.Height))
  try { $info.rotation = Num $sh.Rotation } catch {}
  try { $info.visible = [int]$sh.Visible } catch {}
  try { $info.connector = [int]$sh.Connector } catch {}
  try { $info.shape_kind = [int]$sh.AutoShapeType } catch {}
  if ($sh.Type -eq 14) { try { $info.placeholder = [int]$sh.PlaceholderFormat.Type } catch {} }
  try { $info.fill = ([int]$sh.Fill.Visible -ne 0) -and ([double]$sh.Fill.Transparency -lt 0.95); if ($info.fill) { $info.fill_rgb = [int]$sh.Fill.ForeColor.RGB } } catch { $info.fill = $false }
  try { $info.line = ([int]$sh.Line.Visible -ne 0) -and ([double]$sh.Line.Transparency -lt 0.95) -and ([double]$sh.Line.Weight -gt 0); if ($info.line) { $info.line_rgb = [int]$sh.Line.ForeColor.RGB } } catch { $info.line = $false }
  [void]$list.Add($info)
  if ($sh.Type -eq 6) {
    foreach ($child in $sh.GroupItems) { try { Shape-Info $child $info.id $list } catch { [void]$list.Add([ordered]@{ name = [string]$child.Name; error = $_.Exception.Message }) } }
    return
  }
  try {
    if ($sh.HasTable) {
      $t = $sh.Table
      $rows = New-Object System.Collections.ArrayList
      for ($r = 1; $r -le $t.Rows.Count; $r++) { [void]$rows.Add((Num $t.Rows.Item($r).Height)) }
      $cols = New-Object System.Collections.ArrayList
      for ($c = 1; $c -le $t.Columns.Count; $c++) { [void]$cols.Add((Num $t.Columns.Item($c).Width)) }
      $cells = New-Object System.Collections.ArrayList
      for ($r = 1; $r -le $t.Rows.Count; $r++) { for ($c = 1; $c -le $t.Columns.Count; $c++) {
        try { $cell = $t.Cell($r, $c); $ci = Frame-Info $cell.Shape.TextFrame2; $ci.row = $r; $ci.col = $c
              try { $ci.merged = [int]$cell.Merged } catch {}
              [void]$cells.Add($ci) } catch {}
      } }
      $info.table = [ordered]@{ rows = $rows; cols = $cols; cells = $cells }
      return
    }
  } catch {}
  try { if ($sh.HasChart) { $info.chart = $true; return } } catch {}
  try { if ($sh.HasTextFrame -and $sh.TextFrame2.HasText) { $info.frame = Frame-Info $sh.TextFrame2 } } catch { $info.frame_error = $_.Exception.Message }
}
$app = New-Object -ComObject PowerPoint.Application
try {
  $deck = $app.Presentations.Open('__PPTX__', $true, $true, $false)
  try {
    $result = [ordered]@{ width = (Num $deck.PageSetup.SlideWidth); height = (Num $deck.PageSetup.SlideHeight); slides = (New-Object System.Collections.ArrayList) }
    foreach ($slide in $deck.Slides) {
      $list = New-Object System.Collections.ArrayList
      foreach ($sh in $slide.Shapes) { try { Shape-Info $sh $null $list } catch { [void]$list.Add([ordered]@{ name = [string]$sh.Name; error = $_.Exception.Message }) } }
      $bg = [ordered]@{}
      try { $bg.follow = [int]$slide.FollowMasterBackground; $bg.slide = [int]$slide.Background.Fill.ForeColor.RGB } catch {}
      try { $bg.layout_follow = [int]$slide.CustomLayout.FollowMasterBackground; $bg.layout = [int]$slide.CustomLayout.Background.Fill.ForeColor.RGB } catch {}
      try { $bg.master = [int]$slide.Master.Background.Fill.ForeColor.RGB } catch {}
      [void]$result.slides.Add([ordered]@{ index = [int]$slide.SlideIndex; background = $bg; shapes = $list })
    }
    $json = ConvertTo-Json $result -Depth 12 -Compress
    [System.IO.File]::WriteAllText($out, $json, (New-Object System.Text.UTF8Encoding $false))
  } finally { $deck.Close() }
} finally {
  if ($app.Presentations.Count -eq 0) { $app.Quit() }
  [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
"""


class ParityUnavailable(RuntimeError):
    """PowerPoint could not be driven here: nothing was measured."""


def _powerpoint_pids() -> set[int]:
    if sys.platform != "win32":
        return set()
    proc = subprocess.run(["tasklist", "/FI", "IMAGENAME eq POWERPNT.EXE", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace")
    return {int(m.group(1)) for m in re.finditer(r'"POWERPNT\.EXE","(\d+)"', proc.stdout)}


def measure_with_powerpoint(pptx: Path, timeout: float = 300.0) -> dict:
    """PowerPoint's own layout of every slide. Raises ParityUnavailable when PowerPoint cannot be driven.
    A PowerPoint process this call started is killed if the measurement overruns its time bound; one the user had open is never touched."""
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if sys.platform != "win32" or not shell:
        raise ParityUnavailable("PowerPoint measurement needs Windows with PowerShell and Microsoft PowerPoint")
    with tempfile.TemporaryDirectory(prefix="pptx_parity_") as scratch:
        out = Path(scratch) / "measure.json"
        script = Path(scratch) / "measure.ps1"
        body = _MEASURE_PS.replace("__PPTX__", str(pptx.resolve()).replace("'", "''")).replace("__OUT__", str(out).replace("'", "''"))
        script.write_text("﻿" + body, encoding="utf-8")  # BOM: Windows PowerShell 5.1 reads a BOM-less script in the ANSI code page
        before = _powerpoint_pids()
        try:
            proc = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            for pid in _powerpoint_pids() - before:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            raise ParityUnavailable(f"PowerPoint measurement exceeded {timeout:.0f} s and was stopped") from exc
        if proc.returncode != 0 or not out.is_file():
            raise ParityUnavailable(f"PowerPoint measurement failed: {(proc.stderr or proc.stdout).strip()[-600:]}")
        return json.loads(out.read_text(encoding="utf-8-sig"))


# ---------------------------------------------------------------------------------------------
# 2. What the exporter planned (read from the file) and what the SVG pages showed
# ---------------------------------------------------------------------------------------------
def read_plan(pptx: Path) -> dict:
    """Per slide number, per shape id: planned table row heights (pt), and per paragraph the explicit bullet settings in the XML."""
    from lxml import etree
    plan: dict[int, dict[int, dict]] = {}
    with zipfile.ZipFile(pptx) as archive:
        names = sorted((n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        order = _slide_order(archive)
        for name in names:
            number = order.get(name)
            if number is None:
                continue
            root = etree.fromstring(archive.read(name))
            shapes: dict[int, dict] = {}
            frames = {}
            tree = root.find("p:cSld/p:spTree", NS)
            if tree is not None:
                from pptx_text_in_shapes import walk
                for item in walk(tree):
                    props = item.el.find(".//p:cNvPr", NS)
                    if props is not None and (props.get("id") or "").isdigit():
                        frames[int(props.get("id"))] = [v / EMU_PER_PT for v in item.box]  # l, t, r, b as the exporter wrote them
            for props in root.iter(f"{{{P}}}cNvPr"):
                owner = props.getparent().getparent()
                try:
                    sid = int(props.get("id"))
                except (TypeError, ValueError):
                    continue
                entry: dict = {"name": props.get("name"), "frame": frames.get(sid)}
                table = owner.find(".//a:tbl", NS)
                if table is not None:
                    entry["rows"] = [int(tr.get("h") or 0) / EMU_PER_PT for tr in table.findall("a:tr", NS)]
                    cells = []
                    for r, tr in enumerate(table.findall("a:tr", NS), start=1):
                        for c, tc in enumerate(tr.findall("a:tc", NS), start=1):
                            algn = [p.find("a:pPr", NS).get("algn") if p.find("a:pPr", NS) is not None else None for p in tc.findall("a:txBody/a:p", NS)]
                            cells.append({"row": r, "col": c, "algn": algn})
                    entry["cells"] = cells
                body = owner.find("p:txBody", NS)
                if body is not None:
                    paras = []
                    for p in body.findall("a:p", NS):
                        ppr = p.find("a:pPr", NS)
                        kind = None
                        if ppr is not None:
                            kind = ("none" if ppr.find("a:buNone", NS) is not None else "char" if ppr.find("a:buChar", NS) is not None
                                    else "auto" if ppr.find("a:buAutoNum", NS) is not None else None)
                        paras.append({"bullet_xml": kind})
                    entry["paragraphs"] = paras
                    entry["placeholder"] = owner.find(".//p:nvPr/p:ph", NS) is not None
                shapes[sid] = entry
            plan[number] = shapes
    return plan


def _slide_order(archive: zipfile.ZipFile) -> dict[str, int]:
    """slide part name -> 1-based position in the presentation's slide list."""
    from lxml import etree
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    presentation = etree.fromstring(archive.read("ppt/presentation.xml"))
    rels = etree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
    target = {rel.get("Id"): rel.get("Target") for rel in rels}
    order = {}
    for position, node in enumerate(presentation.iter(f"{{{P}}}sldId"), start=1):
        part = target.get(node.get(f"{{{R}}}id"), "")
        order["ppt/" + part.lstrip("/").replace("../", "").removeprefix("ppt/")] = position
    return order


_MARKER = re.compile(r"^\s*(?:(?P<num>\d{1,2})(?P<sep>[.)])|(?P<bul>[\u00b7\u2022\u25cf\u25aa\u25a0\u2013\u2014-]))\s+")


def norm(text: str) -> str:
    """Compare text as words: no spaces, no zero-width characters, no separator dots, case kept."""
    return re.sub(rf"[\s{ZERO_WIDTH}·•]", "", text or "")


def _anchor(el, inherited: str) -> str:
    style = el.get("style") or ""
    found = re.search(r"text-anchor\s*:\s*(start|middle|end)", style)
    return found.group(1) if found else (el.get("text-anchor") or inherited)


def _num(value, default=0.0) -> float:
    found = re.match(r"\s*(-?[\d.]+(?:e-?\d+)?)", str(value or ""))
    return float(found.group(1)) if found else default


def _font_size(el, inherited: float) -> float:
    style = el.get("style") or ""
    found = re.search(r"font-size\s*:\s*([\d.]+)", style)
    return float(found.group(1)) if found else (_num(el.get("font-size"), inherited) if el.get("font-size") else inherited)


def _y_transform(el) -> tuple[float, float]:
    """(scale, offset) that the element's and its ancestors' transforms apply to a y coordinate (text is not expected to be rotated or skewed)."""
    scale, offset = 1.0, 0.0
    for node in [el, *el.iterancestors()]:
        for kind, args in re.findall(r"(translate|matrix|scale)\s*\(([^)]*)\)", node.get("transform") or "")[::-1]:
            values = [float(v) for v in re.findall(r"-?[\d.]+(?:e-?\d+)?", args)]
            sy, ty = 1.0, 0.0
            if kind == "translate":
                ty = values[1] if len(values) > 1 else 0.0
            elif kind == "scale" and values:
                sy = values[1] if len(values) > 1 else values[0]
            elif kind == "matrix" and len(values) == 6:
                sy, ty = values[3], values[5]
            scale, offset = sy * scale, sy * offset + ty
    return scale, offset


def svg_lines(svg: Path) -> list[dict]:
    """Every visual line of every <text> in paint order: its words, typed list marker, anchor, baseline (y, px), size and line pitch,
    and whether it continues a line above."""
    from lxml import etree
    try:
        root = etree.parse(str(svg)).getroot()
    except Exception:  # noqa: BLE001
        return []
    lines: list[dict] = []
    for element_index, text in enumerate(root.iter(f"{{{SVG_NS}}}text")):
        in_table = any((a.get("data-pptx-replace-with") or "").startswith("table") for a in text.iterancestors())
        anchor, size = "start", 16.0
        for ancestor in reversed(list(text.iterancestors())):
            anchor, size = _anchor(ancestor, anchor), _font_size(ancestor, size)
        anchor, size = _anchor(text, anchor), _font_size(text, size)
        scale, offset = _y_transform(text)
        y = _num((text.get("y") or "0").split()[0] if (text.get("y") or "").strip() else 0)
        current = {"parts": [text.text or ""], "anchor": anchor, "y": y, "size": size}
        found = [current]
        for tspan in text:
            if etree.QName(tspan).localname != "tspan":
                continue
            new_y = current["y"]
            if tspan.get("y") is not None:
                new_y = _num(tspan.get("y").split()[0] if tspan.get("y").strip() else new_y)
            if tspan.get("dy") is not None:
                new_y += _num(tspan.get("dy").split()[0] if tspan.get("dy").strip() else 0)
            span_size = _font_size(tspan, size)
            if abs(new_y - current["y"]) > 0.5 and ("".join(current["parts"]).strip() or len(found) > 1):
                current = {"parts": [], "anchor": _anchor(tspan, anchor), "y": new_y, "size": span_size}
                found.append(current)
            else:
                current["y"], current["size"] = new_y, max(current["size"], span_size) if "".join(current["parts"]).strip() else span_size
            current["parts"].append("".join(tspan.itertext()))
            if tspan.tail:
                current["parts"].append(tspan.tail)
        kept = [f for f in found if "".join(f["parts"]).strip()]
        for line_index, entry in enumerate(kept):
            raw = "".join(entry["parts"])
            marker = _MARKER.match(raw)
            previous = "".join(kept[line_index - 1]["parts"]) if line_index else ""
            if len(kept) > 1:
                pitch = abs(entry["y"] - kept[line_index - 1]["y"]) if line_index else abs(kept[1]["y"] - entry["y"])
            else:
                pitch = 1.2 * entry["size"]
            lines.append({"element": element_index, "line": line_index, "raw": raw.strip(), "norm": norm(raw),
                          "bare": norm(raw[marker.end():]) if marker else norm(raw), "number": int(marker.group("num")) if marker and marker.group("num") else None,
                          "marker": (marker.group("bul") or "") if marker else "", "anchor": entry["anchor"], "in_table": in_table,
                          "prev_marker": bool(line_index and _MARKER.match(previous)),
                          "baseline": entry["y"] * scale + offset, "size": entry["size"] * abs(scale), "pitch": (pitch or 1.2 * entry["size"]) * abs(scale)})
    return lines


def match_lines(text: str, lines: list[dict], used: set | None = None) -> list[dict] | None:
    """The consecutive SVG lines that together hold exactly this paragraph's words (the typed marker of the first may be absent)."""
    target = norm(text)
    if not target:
        return None
    for start, first in enumerate(lines):
        for key in ("norm", "bare"):
            head = first[key]
            if not head or not target.startswith(head) or (used is not None and start in used):
                continue
            taken, have = [first], head
            index = start + 1
            while have != target and index < len(lines) and target.startswith(have + lines[index]["norm"]) and lines[index]["norm"]:
                have += lines[index]["norm"]
                taken.append(lines[index])
                index += 1
            if have == target:
                if used is not None:
                    used.update(range(start, index))
                return taken
    return None


def svg_pages(project: Path | None, count: int) -> list[Path | None]:
    """The SVG page behind each slide, in export order (the exporter takes svg_final, else svg_output, sorted by name)."""
    if project is None:
        return [None] * count
    for folder in ("svg_final", "svg_output"):
        files = sorted((project / folder).glob("*.svg")) if (project / folder).is_dir() else []
        if len(files) == count:
            return list(files)
    return [None] * count


# ---------------------------------------------------------------------------------------------
# 3. Analysis
# ---------------------------------------------------------------------------------------------
def _rect(box) -> tuple[float, float, float, float]:
    left, top, width, height = (float(v or 0) for v in box)
    return (left, top, left + width, top + height)


def _inter(a, b) -> tuple[float, float]:
    return (min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1]))


def _contains(outer, inner, tol=0.0) -> bool:
    return outer[0] - tol <= inner[0] and outer[1] - tol <= inner[1] and outer[2] + tol >= inner[2] and outer[3] + tol >= inner[3]


def _visible_text(text: str) -> str:
    return re.sub(rf"[\s{ZERO_WIDTH}\x0b]", "", text or "")


def _px(rect, scale) -> list[int]:
    return [int(round(rect[0] * scale)), int(round(rect[1] * scale)), int(round((rect[2] - rect[0]) * scale)), int(round((rect[3] - rect[1]) * scale))]


def _short(text: str, n: int = 60) -> str:
    text = re.sub(r"\s+", " ", (text or "").replace("\x0b", " ")).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _is_line(shape: dict) -> bool:
    left, top, right, bottom = _rect(shape.get("box") or [0, 0, 0, 0])
    return shape.get("type") == 9 or shape.get("connector") == -1 or min(right - left, bottom - top) <= 1.5


def _rgb(value) -> tuple[int, int, int] | None:
    """COM colours are BGR integers; a negative value means mixed or undefined."""
    if value is None or int(value) < 0:
        return None
    value = int(value)
    return (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)


def _differs(a, b, threshold: int = 6) -> bool:
    """Two colours a reader tells apart (an unknown colour counts as different)."""
    if a is None or b is None:
        return True
    return max(abs(x - y) for x, y in zip(a, b)) > threshold


def slide_background(slide: dict):
    bg = slide.get("background") or {}
    if bg.get("follow") in (-1, 1):
        return _rgb(bg.get("layout") if bg.get("layout_follow") == 0 else bg.get("master"))
    return _rgb(bg.get("slide"))


def _painted(shape: dict, background) -> bool:
    """Fill or outline a reader can see against the slide background (a panel filled with the background colour is not a panel)."""
    fill = shape.get("fill") and _differs(_rgb(shape.get("fill_rgb")), background)
    line = shape.get("line") and _differs(_rgb(shape.get("line_rgb")), background)
    return bool(fill or line)


def _obstacles(shapes: list[dict], background=None) -> list[dict]:
    """Objects text may not run into: painted shapes, lines, pictures, tables, charts - with the rectangle they occupy."""
    out = []
    for shape in shapes:
        if shape.get("error") or shape.get("type") == 6 or shape.get("visible") == 0:
            continue
        rect = _rect(shape["box"])
        painted = _painted(shape, background)
        if shape.get("frame") and not painted:
            continue  # a text box's own text is compared as text
        line = _is_line(shape) and (shape.get("line") and _differs(_rgb(shape.get("line_rgb")), background))
        if painted or shape.get("type") in (13, 3) or shape.get("table") or shape.get("chart") or line:
            out.append({"shape": shape, "rect": rect, "line": bool(_is_line(shape))})
    return out


def _covered(point, shapes: list[dict], above_z: int) -> dict | None:
    """The opaque object painted after `above_z` that hides a point (a table, picture, chart or filled shape), if any."""
    for shape in shapes:
        if shape.get("z", 0) <= above_z or shape.get("type") == 6 or shape.get("visible") == 0:
            continue
        opaque = shape.get("table") or shape.get("chart") or shape.get("type") == 13 or shape.get("fill")
        left, top, right, bottom = _rect(shape["box"])
        if opaque and left <= point[0] <= right and top <= point[1] <= bottom:
            return shape
    return None


def _colour_under(point, shapes: list[dict], below_z: int, background):
    """The colour a reader sees behind a point: the topmost filled shape painted before `below_z` that covers it, else the background."""
    for shape in sorted((s for s in shapes if s.get("z", 0) < below_z and s.get("fill") and s.get("type") != 6), key=lambda s: -s.get("z", 0)):
        left, top, right, bottom = _rect(shape["box"])
        if left <= point[0] <= right and top <= point[1] <= bottom and _rgb(shape.get("fill_rgb")) is not None:
            return _rgb(shape.get("fill_rgb"))
    return background


def analyse(measure: dict, plan: dict | None = None, svgs: list[Path | None] | None = None) -> list[dict]:
    width = float(measure.get("width") or 960)
    height = float(measure.get("height") or 540)
    scale = BASIS_W / width  # points -> px on the 1280 basis
    tol = TOL_PX / scale
    findings: list[dict] = []
    plan = plan or {}
    for slide in measure.get("slides") or []:
        number = int(slide["index"])
        shapes = [s for s in slide.get("shapes") or [] if not s.get("error")]
        svg = (svgs or [None] * number)[number - 1] if svgs and number - 1 < len(svgs) else None
        lines = svg_lines(svg) if svg else []
        used: set = set()
        planned = plan.get(number) or {}
        background = slide_background(slide)
        obstacles = _obstacles(shapes, background)
        texts = [s for s in shapes if s.get("frame") and s.get("visible") != 0 and not (s.get("rotation") or 0) % 360]

        def add(code, severity, shape, message, rect, focus=None, **extra):
            entry = {"code": code, "severity": severity, "slide": number, "svg": svg.stem if svg else None,
                     "shape": (shape or {}).get("name"), "message": message, "bbox": _px(rect, scale), **extra}
            if focus is not None:
                entry["focus"] = _px(focus, scale)
            findings.append(entry)

        # -- text frames ----------------------------------------------------------------------
        text_rects = []
        svg_plan: dict = {}
        for shape in texts:
            frame = shape["frame"]
            box = _rect(shape["box"])
            bound = frame.get("bound")
            if not bound or not _visible_text(frame.get("text", "")):
                text_rects.append((shape, None, box))
            else:
                text_rects.append((shape, _rect(bound), box))
            xml = (planned.get(shape.get("id")) or {}).get("paragraphs") or []
            paragraphs = frame.get("paragraphs") or []
            for index, para in enumerate(paragraphs):
                visible = _visible_text(para.get("text", ""))
                bullet_on = para.get("bullet_visible") not in (0, None) and para.get("bullet_type") in (1, 2, 3)
                prect = _rect(para["bound"]) if para.get("bound") else box
                if bullet_on and not visible:
                    inherited = index < len(xml) and xml[index].get("bullet_xml") is None
                    colour = _rgb(para.get("text_rgb") if para.get("bullet_text_color") not in (0, None) else para.get("bullet_rgb"))
                    point = (box[0] + 2, (prect[1] + prect[3]) / 2)
                    under = _colour_under(point, shapes, shape.get("z", 0), background)
                    cover = _covered(point, shapes, shape.get("z", 0))
                    seen = _differs(colour, under) and cover is None
                    add("STRAY_BULLET", "certain" if seen else "flagged", shape,
                        f"PowerPoint draws a bullet on an empty paragraph of `{shape['name']}` (its text is {'a zero-width character' if para.get('text') else 'empty'}"
                        f"{'; the bullet is inherited from the layout placeholder' if inherited else ''}): "
                        + ("a stray dot or number shows on the slide. " if seen else
                           (f"`{cover.get('name')}` hides it now" if cover is not None else "it is painted in the colour behind it, so it is invisible now")
                           + ", but an editor who types there gets a bullet. ")
                        + "Fix: remove the empty paragraph or the carrier's zero-width text, or set no bullet.", box if prect[2] - prect[0] < 1 else prect, visible=seen)
            # SVG comparisons: line counts, accidental bullets, renumbering
            if lines:
                spans, complete = [], True
                for index, para in enumerate(paragraphs):
                    if not _visible_text(para.get("text", "")):
                        continue
                    found = match_lines(para["text"], lines, used)
                    if not found:
                        complete = False
                        continue
                    spans.extend(found)
                    ppt_lines = len([l for l in para.get("lines") or [] if _visible_text(l)]) or 1
                    prect = _rect(para["bound"]) if para.get("bound") else _rect(shape["box"])
                    if ppt_lines > len(found):
                        add("LINE_COUNT_DRIFT", "flagged", shape,
                            f"`{_short(para['text'])}` is {len(found)} line(s) in the SVG and {ppt_lines} in PowerPoint (PowerPoint's wider metrics wrap it earlier).",
                            prect, svg_lines=len(found), ppt_lines=ppt_lines)
                    first = found[0]
                    bullet_on = para.get("bullet_visible") not in (0, None) and para.get("bullet_type") == 1
                    if bullet_on and first["marker"] == "·" and first["line"] > 0 and not first["prev_marker"]:
                        add("ACCIDENTAL_BULLET", "certain", shape,
                            f"`{_short(para['text'])}`: in the SVG this line continues the line above after a '·' separator; PowerPoint shows it as a bullet point.",
                            prect)
                    elif (para.get("bullet_visible") not in (0, None) and para.get("bullet_type") in (1, 2) and not first["marker"] and first["number"] is None
                          and index < len(xml) and xml[index].get("bullet_xml") is None):
                        add("STRAY_BULLET", "certain", shape,
                            f"`{_short(para['text'])}` carries a bullet it inherits from the layout placeholder; the SVG shows none. "
                            "Fix: set no bullet on the paragraph (the exporter's placeholder carrier).", prect)
                    if para.get("bullet_type") == 2 and para.get("bullet_number") is not None and first["number"] is not None \
                            and int(para["bullet_number"]) != first["number"]:
                        add("RENUMBERED", "certain", shape,
                            f"`{_short(para['text'])}` is item {first['number']} in the SVG; PowerPoint numbers it {para['bullet_number']}.", prect,
                            svg_number=first["number"], ppt_number=para["bullet_number"])
                if spans and complete:  # where the SVG put this text's lines: the plan PowerPoint's layout is measured against (px -> pt)
                    top = min(l["baseline"] - 0.8 * l["pitch"] for l in spans) / scale
                    bottom = max(l["baseline"] + 0.2 * l["pitch"] for l in spans) / scale
                    svg_plan[id(shape)] = (top, bottom)
            # accidental bullet without SVG evidence: a lone bulleted line after a line that uses '·' as a separator
            for index, para in enumerate(paragraphs):
                if index and para.get("bullet_type") == 1 and para.get("bullet_char") in (183, 8226) and not lines:
                    previous = paragraphs[index - 1]
                    if previous.get("bullet_type") in (0, None) and "·" in previous.get("text", ""):
                        add("ACCIDENTAL_BULLET", "flagged", shape,
                            f"`{_short(para['text'])}` is the only bulleted line after a line that uses '·' as a separator: probably a wrapped separator line.",
                            _rect(para["bound"]) if para.get("bound") else _rect(shape["box"]))
            # words broken across lines
            for para in paragraphs:
                split = _mid_word_break(para.get("lines") or [])
                if split:
                    add("HEADER_SPLIT", "certain", shape, f"PowerPoint breaks the word `{split}` across two lines in `{_short(para['text'])}`. Fix: widen the box, shorten the word or allow a smaller size.",
                        _rect(para["bound"]) if para.get("bound") else _rect(shape["box"]))

        # -- renumbering without SVG evidence: one visible list numbered 1, 2, 1 ----------------
        if not lines:
            _list_sequence_check(texts, add)

        # -- overflow and collisions ----------------------------------------------------------
        # The exporter's frame (from the file, before PowerPoint grows an auto-fit box) is what the SVG promised; only
        # text PowerPoint lays out beyond that frame can create a clip or a collision the browser render did not show.
        slide_rect = (0.0, 0.0, width, height)

        def planned_rect(shape: dict):
            frame = (planned.get(shape.get("id")) or {}).get("frame")
            return tuple(frame) if frame else _rect(shape["box"])

        edge = 0.5 / scale  # a line box this far past an edge already cuts descenders (measured: kirkland2 s6, selfdoc run 3 s8)
        growth_min = 1.0 / scale
        touch = 1.0 / scale  # PowerPoint sets text 2-4 px lower than Chromium: a 1 px overlap where the SVG had a gap is a visible collision

        pairs: set = set()

        def spill(inner, outer) -> float:
            return max(outer[0] - inner[0], outer[1] - inner[1], inner[2] - outer[2], inner[3] - outer[3])

        for shape, trect, _box in text_rects:
            if trect is None:
                continue
            frame = shape["frame"]
            name = shape["name"]
            box = planned_rect(shape)
            if not _contains(slide_rect, trect, tol):
                add("OVERFLOW", "certain", shape, f"`{_short(frame.get('text'))}` runs off the slide in PowerPoint.", trect)
                continue
            from_svg = id(shape) in svg_plan
            plan_text = (box[0], svg_plan[id(shape)][0], box[2], svg_plan[id(shape)][1]) if from_svg else box
            over = {"below where the SVG ends it": trect[3] - plan_text[3], "above where the SVG starts it": plan_text[1] - trect[1],
                    "past its frame's left edge": box[0] - trect[0], "past its frame's right edge": trect[2] - box[2]}
            how, amount = max(over.items(), key=lambda pair: pair[1])
            if amount <= (growth_min if from_svg else tol):
                continue  # PowerPoint keeps the text where the SVG had it: nothing new can collide
            margins = frame.get("margins") or [0, 0, 0, 0]
            line_count = frame.get("line_count") or 0
            hit = None
            if _painted(shape, background):
                now, before = spill(trect, box), spill(plan_text, box)
                if now > (edge if from_svg else tol) and now - max(before, 0.0) > growth_min:
                    hit = ("OVERFLOW", f"In PowerPoint the text of `{name}` (`{_short(frame.get('text'))}`) runs out of its box by {now * scale:.0f} px "
                                       f"(PowerPoint sets it {amount * scale:.0f} px {how}): its {line_count} line(s) take {(trect[3] - trect[1]) * scale:.0f} x {(trect[2] - trect[0]) * scale:.0f} px, "
                                       f"the box offers {(box[3] - box[1] - (margins[1] or 0) - (margins[3] or 0)) * scale:.0f} x {(box[2] - box[0] - (margins[0] or 0) - (margins[2] or 0)) * scale:.0f} px "
                                       "inside its insets. Fix: shorten the copy or give the box more room (height, width or inner padding); do not shrink the type below the floor.",
                           (min(trect[0], box[0]), min(trect[1], box[1]), max(trect[2], box[2]), max(trect[3], box[3])))
            if hit is None:
                for obstacle in obstacles:
                    other = obstacle["shape"]
                    if other is shape or other.get("id") == shape.get("id") or _is_ancestor(other, shape, shapes):
                        continue
                    orect, oplan = obstacle["rect"], planned_rect(other)
                    if not obstacle["line"] and _contains(oplan, plan_text, tol):  # the panel the text sits on: running out of it is an overflow
                        now, before = spill(trect, oplan), spill(plan_text, oplan)
                        if now > (edge if from_svg else tol) and now - max(before, 0.0) > growth_min:
                            hit = ("OVERFLOW", f"In PowerPoint `{_short(frame.get('text'))}` ({line_count} line(s)) sits {amount * scale:.0f} px {how} and runs out of the panel "
                                               f"`{other.get('name')}` it sits on by {now * scale:.0f} px (the SVG kept it {max(-before, 0.0) * scale:.0f} px inside). "
                                               "Fix: shorten the copy or give the panel more room below/around the text.",
                                   (min(trect[0], oplan[0]), min(trect[1], oplan[1]), max(trect[2], oplan[2]), max(trect[3], oplan[3])) if now < 12 / scale else trect)
                            break
                        continue
                    now, before = _inter(trect, orect), _inter(plan_text, oplan)
                    if obstacle["line"]:
                        touching = min(now) >= -0.01 and max(now) > tol
                        was = min(before) >= -0.01 and max(before) > 0
                    else:
                        touching = min(now) > (touch if from_svg else tol) and max(now) > tol
                        was = min(before) > -0.01
                    if touching and not was:
                        hit = ("TEXT_COLLISION", f"In PowerPoint `{_short(frame.get('text'))}` sits {amount * scale:.0f} px {how} and runs into "
                                                 f"`{other.get('name')}` ({max(now[0], 0) * scale:.0f} x {max(now[1], 0) * scale:.0f} px; in the SVG they did not touch). "
                                                 "Fix: shorten the copy, or move/resize so the text clears it with room to spare.",
                               (max(trect[0], orect[0]), max(trect[1], orect[1]), min(trect[2], orect[2]), min(trect[3], orect[3])))
                        break
            if hit is None:  # text against text: two texts that did not overlap in the plan now do
                for other, orect_text, _obox in text_rects:
                    if other is shape or orect_text is None or (id(other), id(shape)) in pairs:
                        continue
                    oplan = planned_rect(other)
                    if id(other) in svg_plan:
                        oplan = (oplan[0], svg_plan[id(other)][0], oplan[2], svg_plan[id(other)][1])
                    now, before = _inter(trect, orect_text), _inter(plan_text, oplan)
                    if min(now) > tol and not min(before) > 0:
                        pairs.add((id(shape), id(other)))
                        hit = ("TEXT_COLLISION", f"In PowerPoint `{_short(frame.get('text'))}` sits {amount * scale:.0f} px {how} and overlaps the text "
                                                 f"`{_short(other['frame'].get('text'), 40)}` ({now[0] * scale:.0f} x {now[1] * scale:.0f} px). Fix: shorten or reflow the copy so it clears its neighbour.",
                               (max(trect[0], orect_text[0]), max(trect[1], orect_text[1]), min(trect[2], orect_text[2]), min(trect[3], orect_text[3])))
                        break
            if hit:
                add(hit[0], "certain", shape, hit[1], hit[2], focus=trect, moved_px=round(amount * scale, 1), lines=line_count, measured_against="svg" if from_svg else "frame")

        # -- tables ---------------------------------------------------------------------------
        for shape in shapes:
            table = shape.get("table")
            if not table:
                continue
            _check_table(shape, table, planned.get(shape.get("id")) or {}, shapes, obstacles, text_rects, lines, slide_rect, tol, scale, add)
    return _dedupe(findings)


def _is_ancestor(candidate: dict, shape: dict, shapes: list[dict]) -> bool:
    parent = shape.get("parent")
    by_id = {s.get("id"): s for s in shapes}
    while parent is not None:
        if parent == candidate.get("id"):
            return True
        parent = (by_id.get(parent) or {}).get("parent")
    return False


def _mid_word_break(lines: list[str]) -> str | None:
    """The word PowerPoint broke across two lines of one paragraph (an automatic break inside a word), if any."""
    for first, second in zip(lines, lines[1:]):
        if not first or not second or first.endswith(("\x0b", "\r", "\n", " ", "-", "–", "—", "/", "­")):
            continue
        tail, head = re.search(r"(\w+)$", first), re.match(r"^(\w+)", second)
        if tail and head and not first[-1].isdigit():
            return tail.group(1) + "|" + head.group(1)
    return None


def _list_sequence_check(texts: list[dict], add) -> None:
    """Visible list numbers on one slide, typed or automatic, read in order down one column: 1, 2, 1 or 1, 1, 2 is a renumbered list."""
    items = []
    for shape in texts:
        for para in shape["frame"].get("paragraphs") or []:
            text = para.get("text", "")
            if para.get("bullet_type") == 2 and para.get("bullet_number") is not None:
                number = int(para["bullet_number"])
            else:
                typed = re.match(r"^\s*(\d{1,2})[.)]\s", text)
                if not typed:
                    continue
                number = int(typed.group(1))
            bound = para.get("bound") or shape["box"]
            items.append((round(float(bound[0]) / 6), float(bound[1]), number, shape, para, bound))
    columns: dict = {}
    for item in items:
        columns.setdefault(item[0], []).append(item)
    for column in columns.values():
        column.sort(key=lambda i: i[1])
        numbers = [i[2] for i in column]
        if len(numbers) >= 2 and numbers[0] == 1 and any(b != a + 1 for a, b in zip(numbers, numbers[1:])):
            last = column[-1]
            add("RENUMBERED", "flagged", last[3], f"The visible list numbers read {', '.join(map(str, numbers))} down this column in PowerPoint.", _rect(last[5]), numbers=numbers)


def _check_table(shape, table, planned, shapes, obstacles, text_rects, lines, slide_rect, tol, scale, add) -> None:
    rows = [float(r or 0) for r in table.get("rows") or []]
    plan_rows = planned.get("rows") or []
    box = _rect(shape["box"])
    cols = [float(c or 0) for c in table.get("cols") or []]

    def cell_rect(cell):
        """The cell's rectangle on the slide, from PowerPoint's own column widths and row heights (a cell's text bound is cell-relative)."""
        r, c = int(cell.get("row") or 1), int(cell.get("col") or 1)
        if not cols or c > len(cols) or r > len(rows):
            return box
        left, top = box[0] + sum(cols[: c - 1]), box[1] + sum(rows[: r - 1])
        return (left, top, left + cols[c - 1], top + rows[r - 1])

    def column_rect(col):
        if not cols or col > len(cols):
            return box
        left = box[0] + sum(cols[: col - 1])
        return (left, box[1] + (rows[0] if rows else 0), left + cols[col - 1], box[1] + sum(rows))

    cell_box = cell_rect
    left, top = box[0], box[1]
    actual_bottom = top + sum(rows)
    planned_bottom = top + sum(plan_rows) if plan_rows else box[3]
    grown = [(i + 1, plan_rows[i], rows[i]) for i in range(min(len(rows), len(plan_rows))) if rows[i] - plan_rows[i] > tol]
    cells = table.get("cells") or []
    if grown:
        detail = []
        for row, before, after in grown[:6]:
            tallest = max((c for c in cells if c.get("row") == row), key=lambda c: c.get("line_count") or 0, default=None)
            why = f" (cell {tallest.get('col')}: `{_short(tallest.get('text'), 40)}` takes {tallest.get('line_count')} line(s))" if tallest else ""
            detail.append(f"row {row}: planned {before * scale:.0f} px, PowerPoint {after * scale:.0f} px{why}")
        growth = (actual_bottom - planned_bottom) * scale
        rect = (left, top + sum(plan_rows[: grown[0][0] - 1]), box[2], actual_bottom)
        add("ROW_GROWTH", "flagged", shape, f"Table `{shape['name']}` grows by {growth:.0f} px in PowerPoint: " + "; ".join(detail) + ".", rect,
            growth_px=round(growth, 1), rows=[{"row": r, "planned_px": round(b * scale, 1), "ppt_px": round(a * scale, 1)} for r, b, a in grown])
        # does the grown table now reach something it cleared before?
        grown_rect = (box[0], box[1], box[2], actual_bottom)
        planned_rect = (box[0], box[1], box[2], planned_bottom)
        hit = None
        if actual_bottom > slide_rect[3] + tol:
            hit = ("the bottom of the slide", (box[0], slide_rect[3], box[2], actual_bottom))
        for obstacle in obstacles + [{"shape": s, "rect": t or b, "line": False} for s, t, b in text_rects]:
            other = obstacle["shape"]
            if hit or other is shape or other.get("id") == shape.get("id"):
                continue
            orect = obstacle["rect"]
            if _contains(orect, planned_rect, tol):
                if not _contains(orect, grown_rect, tol) and orect[3] < actual_bottom - tol:
                    hit = (f"the edge of `{other.get('name')}` it sits on", (box[0], orect[3], box[2], actual_bottom))
                continue
            now, before = _inter(grown_rect, orect), _inter(planned_rect, orect)
            if min(now) > tol and not min(before) > -0.01:
                hit = (f"`{other.get('name')}`", (max(box[0], orect[0]), orect[1], min(box[2], orect[2]), min(actual_bottom, orect[3])))
        if hit:
            hidden = [r for r, _, _ in grown] if grown else []
            add("TABLE_OVERLAP", "certain", shape,
                f"Table `{shape['name']}` is {growth:.0f} px taller in PowerPoint than planned and now runs into {hit[0]}: the bottom row(s) slide under it. "
                + "; ".join(detail) + ". Fix: shorten the cells that wrap, widen those columns, or reserve the growth below the table; do not shrink the type below the floor.",
                hit[1], growth_px=round(growth, 1), rows_grown=hidden)
    # words broken across lines inside cells
    for cell in cells:
        for para in cell.get("paragraphs") or []:
            split = _mid_word_break(para.get("lines") or [])
            if split:
                bound = cell_box(cell)
                add("HEADER_SPLIT", "certain", shape, f"Table `{shape['name']}` row {cell.get('row')} column {cell.get('col')}: PowerPoint breaks `{split}` mid-word. "
                    "Fix: widen the column, shorten the header or break it by hand at a word boundary.", bound)
                break
    # cells PowerPoint wraps onto more lines than the SVG drew (what makes a row grow, and splits a header awkwardly)
    cell_lines = [l for l in lines if l.get("in_table")] if lines else []
    if cell_lines:
        used: set = set()
        for cell in cells:
            for para in cell.get("paragraphs") or []:
                if not _visible_text(para.get("text", "")):
                    continue
                found = match_lines(para["text"], cell_lines, used)
                ppt = len([l for l in para.get("lines") or [] if _visible_text(l)]) or 1
                if found and ppt > len(found):
                    add("LINE_COUNT_DRIFT", "flagged", shape,
                        f"Table `{shape['name']}` row {cell.get('row')} column {cell.get('col')}: `{_short(para['text'], 50)}` is {len(found)} line(s) in the SVG and {ppt} in "
                        f"PowerPoint (`{' | '.join(_short(l, 24) for l in para.get('lines') or [])}`)."
                        + (" A header cell that wraps differently reads as an awkward split: widen the column or break it by hand." if cell.get("row") == 1 else ""),
                        cell_rect(cell), svg_lines=len(found), ppt_lines=ppt, row=cell.get("row"), col=cell.get("col"))
    # cell alignment against the SVG fallback
    align_names = {1: "left", 2: "centre", 3: "right", 4: "justified"}
    wanted = {"start": 1, "middle": 2, "end": 3}
    table_lines = [l for l in lines if l.get("in_table")] if lines else []
    drift_cols: dict = {}
    for cell in cells:
        text = cell.get("text", "")
        if not _visible_text(text) or cell.get("row") == 1:
            continue
        paragraph = (cell.get("paragraphs") or [{}])[0]
        align = paragraph.get("align")
        if table_lines:
            found = match_lines(text, table_lines) or match_lines((cell.get("paragraphs") or [{}])[0].get("text", ""), table_lines)
            if found and wanted.get(found[0]["anchor"]) and align and wanted[found[0]["anchor"]] != align:
                drift_cols.setdefault(cell["col"], []).append((cell, found[0]["anchor"], align))
    for col, items in drift_cols.items():
        cell, anchor, align = items[0]
        numeric = all(re.fullmatch(r"[\s$€£%()+\-–−.,0-9kKmMbBxX~]*\d[\s$€£%()+\-–−.,0-9kKmMbBxX~]*", c.get("text", "").strip()) for c, _, _ in items)
        add("ALIGNMENT_DRIFT", "certain" if numeric else "flagged", shape,
            f"Table `{shape['name']}` column {col}: the SVG sets {len(items)} body cell(s) `{anchor}`-anchored ({'right' if anchor == 'end' else anchor}); PowerPoint aligns them "
            f"{align_names.get(align, align)} (e.g. `{_short(cell.get('text'), 30)}`). Fix: give the column's cells `\"align\": \"{ {'end': 'r', 'middle': 'c', 'start': 'l'}[anchor] }\"` in the table JSON.",
            column_rect(col), column=col)
    if not table_lines:  # no SVG evidence: a numeric body column that PowerPoint left-aligns
        by_col: dict = {}
        for cell in cells:
            if cell.get("row") != 1 and _visible_text(cell.get("text", "")):
                by_col.setdefault(cell["col"], []).append(cell)
        for col, items in by_col.items():
            numeric = len(items) >= 2 and all(re.fullmatch(r"[\s$€£%()+\-–−.,0-9]*\d[\s$€£%()+\-–−.,0-9]*", c.get("text", "").strip()) for c in items)
            if numeric and all(((c.get("paragraphs") or [{}])[0].get("align") == 1) for c in items):
                add("ALIGNMENT_DRIFT", "flagged", shape, f"Table `{shape['name']}` column {col} holds numbers and PowerPoint left-aligns them; numbers read right-aligned.",
                    column_rect(col), column=col)


def _dedupe(findings: list[dict]) -> list[dict]:
    seen, out = set(), []
    for finding in findings:
        key = (finding["slide"], finding["code"], finding["shape"], tuple(finding["bbox"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


# ---------------------------------------------------------------------------------------------
# 4. Evidence: crops of the PowerPoint render, JSON and Markdown
# ---------------------------------------------------------------------------------------------
def crop_findings(findings: list[dict], render: Path, margin: int = 36, min_w: int = 360, min_h: int = 110) -> list[Path]:
    """One crop per finding, cut from the PowerPoint render: the text involved outlined in orange, the defect in red."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return []
    out_dir = render / "parity"
    if out_dir.exists():
        for old in out_dir.glob("*.png"):
            old.unlink()
    made = []
    for index, finding in enumerate(findings, start=1):
        slide_png = render / f"slide-{finding['slide']:03d}.png"
        if not slide_png.is_file():
            continue
        with Image.open(slide_png) as image:
            image = image.convert("RGB")
            factor = image.width / BASIS_W
            rects = [finding["bbox"]] + ([finding["focus"]] if finding.get("focus") else [])
            left = min(r[0] for r in rects)
            top = min(r[1] for r in rects)
            right = max(r[0] + max(r[2], 2) for r in rects)
            bottom = max(r[1] + max(r[3], 2) for r in rects)
            grow_w, grow_h = max(0, min_w - (right - left)) / 2, max(0, min_h - (bottom - top)) / 2
            area = [left - margin - grow_w, top - margin - grow_h, right + margin + grow_w, bottom + margin + grow_h]
            area = (max(0, int(area[0] * factor)), max(0, int(area[1] * factor)), min(image.width, int(area[2] * factor)), min(image.height, int(area[3] * factor)))
            draw = ImageDraw.Draw(image)
            if finding.get("focus"):
                x, y, w, h = finding["focus"]
                draw.rectangle([x * factor - 2, y * factor - 2, (x + w) * factor + 2, (y + h) * factor + 2], outline=(255, 150, 0), width=max(1, int(1.5 * factor)))
            x, y, w, h = finding["bbox"]
            draw.rectangle([x * factor - 1, y * factor - 1, (x + max(w, 2)) * factor + 1, (y + max(h, 2)) * factor + 1], outline=(230, 0, 0), width=max(2, int(2 * factor)))
            crop = image.crop(area)
            target = out_dir / f"slide-{finding['slide']:03d}-{index:02d}-{finding['code'].lower()}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            crop.save(target)
            finding["crop"] = str(target)
            made.append(target)
    return made


# What a page author can change in the SVG; the other codes are the exporter's to fix (they are reported, not sent to a page).
AUTHOR_CODES = ("OVERFLOW", "TEXT_COLLISION", "TABLE_OVERLAP", "HEADER_SPLIT", "ACCIDENTAL_BULLET", "RENUMBERED", "ALIGNMENT_DRIFT")
_FIX_DIRECTION = {
    "OVERFLOW": "text in a box, band or chip: leave at least 6 px between the last line and the edge it now crosses (PowerPoint sets text 1-4 px lower than "
                "the browser and its lines 1.2 x the size apart) - shorten the copy or give the box room; never shrink the type below the deck's floor",
    "TEXT_COLLISION": "text above a rule, box or neighbouring text: keep at least 6 px clear of it - move or shorten the text, or move the object",
    "TABLE_OVERLAP": "native table: a PowerPoint row is at least lines x 1.2 x size + the cell padding tall and never shrinks - shorten the cells that wrap, "
                     "widen their columns, or reserve the growth so the table ends at least 8 px above what is below it",
    "HEADER_SPLIT": "a word broken mid-word: widen the column or box, shorten the word, or break the line by hand at a word boundary",
    "ACCIDENTAL_BULLET": "do not start a wrapped line with the '·' separator: end the line above with it, or break before the next word",
    "RENUMBERED": "keep a numbered list in one text block, or write the numbers as labels (\"STEP 01\") so nothing renumbers them",
    "ALIGNMENT_DRIFT": "set the table JSON's `align` for those cells (\"r\" for numbers) to what the drawn table shows",
}


def repair_briefs(report: dict, author_codes: tuple = AUTHOR_CODES) -> dict[str, str]:
    """One repair message per SVG page with certain findings a page author can fix: what PowerPoint did, the measured numbers,
    the crop to look at, and the fix direction. Keyed by the SVG stem."""
    by_page: dict[str, list[dict]] = {}
    for finding in report.get("findings") or []:
        if finding["severity"] == "certain" and finding["code"] in author_codes and finding.get("svg"):
            by_page.setdefault(finding["svg"], []).append(finding)
    briefs = {}
    for stem, items in by_page.items():
        lines = [f"POWERPOINT PARITY - your page `{stem}.svg` is slide {items[0]['slide']} of the exported deck. The browser render you and the reviewer "
                 "looked at is not what the user receives: this was measured in Microsoft PowerPoint itself, which sets text with its own metrics "
                 "(lines 1.2 x the size apart, slightly wider glyphs, text 1-4 px lower than the browser, table rows that grow to fit their cells).", "",
                 "Measured in PowerPoint (px on the 1280 x 720 page; box = x, y, width, height):"]
        for number, finding in enumerate(items, start=1):
            crop = f" Look at the crop: `{finding['crop']}` (open it with read_image)." if finding.get("crop") else ""
            lines.append(f"{number}. {finding['code']} at {finding['bbox']}: {finding['message']}{crop}")
        lines += ["", "Fix direction:"]
        lines += [f"- {code}: {_FIX_DIRECTION[code]}." for code in dict.fromkeys(f["code"] for f in items) if code in _FIX_DIRECTION]
        lines += ["", "Change only what these items need, so the page holds in PowerPoint as well as in the browser; keep every word that carries the message. "
                  "The deck is re-exported and measured in PowerPoint once more after this round."]
        briefs[stem] = "\n".join(lines)
    return briefs


def summarise(findings: list[dict], slides: int) -> dict:
    certain = [f for f in findings if f["severity"] == "certain"]
    by_code: dict = {}
    for finding in findings:
        by_code.setdefault(finding["code"], {"certain": 0, "flagged": 0})[finding["severity"]] += 1
    return {"slides": slides, "certain": len(certain), "flagged": len(findings) - len(certain), "by_code": by_code,
            "slides_with_certain": sorted({f["slide"] for f in certain})}


def to_markdown(report: dict) -> str:
    lines = [f"# PowerPoint parity - {Path(report['pptx']).name}", "",
             f"Measured in {report.get('renderer', 'PowerPoint')} at {report['at']}: {report['summary']['slides']} slides, "
             f"{report['summary']['certain']} certain and {report['summary']['flagged']} flagged finding(s). Coordinates are px on a 1280 x 720 slide.", ""]
    if not report["findings"]:
        lines.append("Nothing differs from the plan in a way a reader would see.")
    for slide in sorted({f["slide"] for f in report["findings"]}):
        items = [f for f in report["findings"] if f["slide"] == slide]
        lines += [f"## Slide {slide}" + (f" - `{items[0]['svg']}`" if items[0].get("svg") else ""), ""]
        for f in sorted(items, key=lambda f: (f["severity"] != "certain", f["code"])):
            lines.append(f"- **{f['severity'].upper()} {f['code']}** `{f['shape']}` at {f['bbox']}: {f['message']}" + (f" Crop: `{f['crop']}`" if f.get("crop") else ""))
        lines.append("")
    return "\n".join(lines)


def run(pptx: Path, project: Path | None = None, render: Path | None = None, out: Path | None = None, md: Path | None = None,
        crops: bool = True, timeout: float = 300.0, measurements: Path | None = None) -> dict:
    started = time.time()
    if measurements and measurements.is_file():
        measure = json.loads(measurements.read_text(encoding="utf-8-sig"))
    else:
        measure = measure_with_powerpoint(pptx, timeout)
        if measurements:
            measurements.write_text(json.dumps(measure, ensure_ascii=False), encoding="utf-8")
    plan = read_plan(pptx)
    svgs = svg_pages(project, len(measure.get("slides") or []))
    findings = analyse(measure, plan, svgs)
    render = render or pptx.with_suffix(".render")
    if crops and render.is_dir():
        crop_findings([f for f in findings if f["severity"] == "certain"] or findings[:12], render)
    report = {"pptx": str(pptx), "renderer": "powerpoint", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - started, 1),
              "svg_pages": [p.name if p else None for p in svgs], "summary": summarise(findings, len(measure.get("slides") or [])), "findings": findings}
    out = out or pptx.with_suffix(".parity.json")
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    (md or pptx.with_suffix(".parity.md")).write_text(to_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pptx")
    parser.add_argument("--project", help="project directory: compare with its SVG pages and record the result in its quality-run.json")
    parser.add_argument("--render", help="pptx_render.py output folder (default <deck>.render)")
    parser.add_argument("--out", help="JSON report (default <deck>.parity.json)")
    parser.add_argument("--md", help="Markdown report (default <deck>.parity.md)")
    parser.add_argument("--no-crops", action="store_true")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds PowerPoint may take to open and measure the deck")
    parser.add_argument("--measurements", help="cache of PowerPoint's raw measurements: read when present, else written")
    args = parser.parse_args()
    pptx = Path(args.pptx).resolve()
    if not pptx.is_file():
        raise SystemExit(f"no such file: {pptx}")
    project = Path(args.project).resolve() if args.project else None
    try:
        report = run(pptx, project, Path(args.render).resolve() if args.render else None, Path(args.out).resolve() if args.out else None,
                     Path(args.md).resolve() if args.md else None, not args.no_crops, args.timeout, Path(args.measurements).resolve() if args.measurements else None)
    except ParityUnavailable as exc:
        print(f"PowerPoint parity not measured: {exc}. Report the deck as unverified in PowerPoint.")
        return 3
    summary = report["summary"]
    print(f"PowerPoint parity: {summary['certain']} certain, {summary['flagged']} flagged finding(s) on {summary['slides']} slides "
          f"({report['seconds']} s); " + ", ".join(f"{code} {v['certain']}+{v['flagged']}" for code, v in sorted(summary["by_code"].items())))
    for finding in report["findings"]:
        print(f"  slide {finding['slide']:2d} {finding['severity']:7s} {finding['code']:17s} {finding['message'][:220]}")
    for finding in report["findings"]:
        if finding.get("crop"):
            print(f"IMAGE: {finding['crop']}")
    if project:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from page_review import update_journal

        def record(journal: dict) -> None:
            journal.setdefault("pptx_inspection", []).append({"pptx": str(pptx), "parity": {**summary, "report": str(pptx.with_suffix('.parity.json') if not args.out else args.out)},
                                                              "at": report["at"]})
        update_journal(project, record)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
