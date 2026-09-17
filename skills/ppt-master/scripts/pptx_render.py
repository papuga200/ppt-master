#!/usr/bin/env python3
"""Render an exported PPTX to one PNG per slide, so the file the user receives can be looked at.

    pptx_render.py <file.pptx> [--out DIR] [--width 1600] [--project PROJECT]

A browser render of a page SVG is evidence of the SVG, not of the PowerPoint. This tool renders
the PPTX itself with a renderer found on the machine, in this order:

    1. Microsoft PowerPoint through COM (Windows), driven by PowerShell - no Python package needed
    2. LibreOffice (`soffice`) to PDF, then PyMuPDF to PNG when both are available

It prints one `slide N: <path>` line per slide and an `IMAGE: <contact sheet>` line. With
`--project` the inspection is recorded in that project's quality-run.json. When no renderer is
available it exits 3 and says so: the deck is then visually checked in SVG only, and must be
reported as unverified in PowerPoint.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

_POWERSHELL = r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
try {
  $deck = $app.Presentations.Open('__PPTX__', $true, $true, $false)
  try {
    $ratio = $deck.PageSetup.SlideHeight / $deck.PageSetup.SlideWidth
    $height = [int]([math]::Round(__WIDTH__ * $ratio))
    foreach ($slide in $deck.Slides) {
      $target = Join-Path '__OUT__' ('slide-{0:d3}.png' -f $slide.SlideIndex)
      $slide.Export($target, 'PNG', __WIDTH__, $height)
    }
  } finally { $deck.Close() }
} finally {
  if ($app.Presentations.Count -eq 0) { $app.Quit() }
}
"""


def render_with_powerpoint(pptx: Path, out: Path, width: int) -> bool:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    if not shell or sys.platform != "win32":
        return False
    script = (_POWERSHELL.replace("__PPTX__", str(pptx).replace("'", "''"))
              .replace("__OUT__", str(out).replace("'", "''")).replace("__WIDTH__", str(width)))
    proc = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    if proc.returncode != 0:
        print(f"PowerPoint renderer unavailable or failed: {proc.stderr.strip()[-400:]}", file=sys.stderr)
        return False
    return True


def render_with_libreoffice(pptx: Path, out: Path, width: int) -> bool:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return False
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return False
    proc = subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", str(out), str(pptx)],
                          capture_output=True, text=True, timeout=900)
    pdf = out / f"{pptx.stem}.pdf"
    if proc.returncode != 0 or not pdf.is_file():
        return False
    with fitz.open(pdf) as document:
        for index, page in enumerate(document, start=1):
            zoom = width / page.rect.width
            page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(out / f"slide-{index:03d}.png")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pptx")
    parser.add_argument("--out")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--project", help="record the inspection in this project's quality-run.json")
    args = parser.parse_args()
    pptx = Path(args.pptx).resolve()
    if not pptx.is_file():
        raise SystemExit(f"no such file: {pptx}")
    out = Path(args.out).resolve() if args.out else pptx.parent / f"{pptx.stem}.render"
    if out.exists():
        for old in out.glob("slide-*.png"):
            old.unlink()
    out.mkdir(parents=True, exist_ok=True)
    renderer = None
    if render_with_powerpoint(pptx, out, args.width):
        renderer = "powerpoint"
    elif render_with_libreoffice(pptx, out, args.width):
        renderer = "libreoffice"
    slides = sorted(out.glob("slide-*.png"))
    if not renderer or not slides:
        print("no PowerPoint renderer is available on this machine: report the deck as visually checked in SVG "
              "but unverified in PowerPoint")
        return 3
    print(f"rendered {len(slides)} slide(s) with {renderer}")
    for index, slide in enumerate(slides, start=1):
        print(f"slide {index}: {slide}")
    from page_review import build_contact_sheet, load_journal, save_journal
    sheet = build_contact_sheet(slides, out / "contact_sheet.png")
    if args.project:
        project = Path(args.project).resolve()
        journal = load_journal(project)
        journal.setdefault("pptx_inspection", []).append(
            {"pptx": str(pptx), "renderer": renderer, "slides": len(slides), "out": str(out), "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        save_journal(project, journal)
    print(f"IMAGE: {sheet}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
