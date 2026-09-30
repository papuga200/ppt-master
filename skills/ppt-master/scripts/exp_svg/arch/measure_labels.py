#!/usr/bin/env python3
"""
PPT Master - measure_labels (experimental architecture helper)

Measure label text with the real font file the slide will use, wrap it to an
available width, and report width/height, the lines, the font evidence and
whether the requested size respects the type floor of its role. Optionally
verify every measured line in Chromium (the renderer the fork's page_lint.py
and page_review.py use) after document.fonts.ready.

Measurement is the sum of glyph advances read by FreeType (Pillow) from an
EXPLICIT font file, with legacy `kern` pairs only - no GPOS kerning or complex
shaping. It is therefore approximate until the browser check agrees; the
result says which backend produced each number. The DrawingML width estimate
the fork's checker uses is reported alongside as `checker_estimate_px`.
Nothing is shortened: a word wider than the width is reported, not cut.

Usage:
    python3 scripts/exp_svg/arch/measure_labels.py --in request.json --out result.json

Request:
    {"font": {"family": "Segoe UI", "files": {"normal": "C:/Windows/Fonts/segoeui.ttf",
                                              "bold": "C:/Windows/Fonts/segoeuib.ttf"}},
     "verify": "browser" | "none",
     "labels": [{"id": "n1", "text": "API gateway", "size_px": 16, "weight": "bold",
                 "role": "body" | "label", "max_width": 180}]}

Dependencies:
    Pillow; playwright (only for "verify": "browser")
"""

from __future__ import annotations

import sys
from pathlib import Path

_ARCH_DIR = Path(__file__).resolve().parent
if str(_ARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ARCH_DIR))

from _common import (  # noqa: E402
    FLOOR_BODY_PX,
    FLOOR_LABEL_PX,
    FLOOR_TOLERANCE,
    HelperError,
    run_cli,
)

TOOL = "exp_svg.arch.measure_labels"
LINE_PITCH = 1.3  # consulting-typesetting.md leading floor is 1.28 x for body text
MEASURE_PX = 256
BOLD_WEIGHTS = ("bold", "600", "700", "800", "900")
_FONT_CACHE: dict[tuple[str, int], object] = {}
_BROWSER_CACHE: dict[tuple[str, str, float, str], float] = {}


def role_floor(role: str) -> float:
    return FLOOR_BODY_PX if role == "body" else FLOOR_LABEL_PX


def is_bold(weight: str | int | None) -> bool:
    return str(weight or "normal").lower() in BOLD_WEIGHTS


def resolve_font(font: dict, weight: str | int | None) -> dict:
    """The font file used for a weight: explicit file first, then the fork's installed-font index."""
    family = str(font.get("family") or "Segoe UI")
    files = font.get("files") or {}
    key = "bold" if is_bold(weight) else "normal"
    explicit = files.get(key)
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise HelperError(f"font file for {family} {key} does not exist: {explicit}")
        return {"family": family, "weight": key, "file": str(path), "face": int(font.get("face") or 0),
                "source": "explicit_file", "backend": "freetype_advances"}
    try:
        import text_measure
        found = text_measure.installed_family(family, "bold" if key == "bold" else "normal")
    except ImportError:
        found = None
    if found:
        _name, (file, face) = found
        return {"family": family, "weight": key, "file": file, "face": face, "source": "installed_font_index",
                "backend": "freetype_advances"}
    return {"family": family, "weight": key, "file": None, "face": 0, "source": "none",
            "backend": "drawingml_estimator"}


def _pil_font(file: str, face: int):
    from PIL import ImageFont
    key = (file, face)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(file, size=MEASURE_PX, index=face)
    return _FONT_CACHE[key]


def checker_estimate(text: str, size: float, family: str, weight: str) -> float | None:
    try:
        import text_measure
        return text_measure.measure_text(text, size=size, family=family, weight=weight, include_headroom=False)
    except (ImportError, ValueError):
        return None


def line_width(text: str, size: float, resolved: dict) -> float:
    if resolved["file"]:
        return _pil_font(resolved["file"], resolved["face"]).getlength(text) * size / MEASURE_PX
    estimate = checker_estimate(text, size, resolved["family"], "bold" if resolved["weight"] == "bold" else "normal")
    if estimate is None:
        raise HelperError("no font file and no estimator available: pass font.files with explicit paths")
    return estimate


def wrap(text: str, size: float, max_width: float | None, resolved: dict) -> tuple[list[str], list[float], list[dict]]:
    """Greedy word wrap; explicit newlines are kept. Returns lines, widths, oversized words (never cut)."""
    lines: list[str] = []
    widths: list[float] = []
    oversized: list[dict] = []
    for paragraph in str(text).split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            widths.append(0.0)
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if max_width is None or line_width(candidate, size, resolved) <= max_width:
                current = candidate
            else:
                lines.append(current)
                widths.append(line_width(current, size, resolved))
                current = word
        lines.append(current)
        widths.append(line_width(current, size, resolved))
    if max_width is not None:
        for line, width in zip(lines, widths):
            if width > max_width + 0.01 and " " not in line:
                oversized.append({"word": line, "width_px": round(width, 2), "max_width_px": round(max_width, 2)})
    return lines, widths, oversized


def measure_label(label: dict, font: dict) -> dict:
    """Measure one label request; never alters its text."""
    text = label.get("text")
    if text is None or str(text) == "":
        raise HelperError(f"label {label.get('id')!r} has no text")
    size = float(label.get("size_px") or 0)
    if size <= 0:
        raise HelperError(f"label {label.get('id')!r} needs size_px")
    role = str(label.get("role") or "label")
    weight = str(label.get("weight") or "normal")
    resolved = resolve_font(font, weight)
    max_width = label.get("max_width")
    max_width = float(max_width) if max_width else None
    lines, widths, oversized = wrap(str(text), size, max_width, resolved)
    pitch = float(label.get("line_pitch") or LINE_PITCH) * size
    floor = role_floor(role)
    estimate = max((checker_estimate(line, size, resolved["family"], weight) or 0.0) for line in lines)
    return {
        "id": label.get("id"),
        "text": str(text),
        "lines": lines,
        "line_widths_px": [round(w, 2) for w in widths],
        "width_px": round(max(widths) if widths else 0.0, 2),
        "height_px": round(pitch * (len(lines) - 1) + 1.2 * size, 2),
        "line_pitch_px": round(pitch, 2),
        "size_px": size,
        "weight": weight,
        "role": role,
        "floor": {"min_px": floor, "ok": size + FLOOR_TOLERANCE >= floor},
        "font": resolved,
        "measurement": "approximate" if resolved["file"] else "estimate",
        "checker_estimate_px": round(estimate, 2) if estimate else None,
        "oversized_words": oversized,
    }


_BROWSER_JS = r"""
async (items) => {
  await document.fonts.ready;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.querySelector('svg');
  const out = [];
  for (const it of items) {
    const measureWith = (family) => {
      const t = document.createElementNS(ns, 'text');
      t.setAttribute('x', 0); t.setAttribute('y', 100);
      t.setAttribute('font-family', family);
      t.setAttribute('font-size', it.size);
      t.setAttribute('font-weight', it.weight);
      t.textContent = it.text;
      svg.appendChild(t);
      const w = t.getComputedTextLength();
      svg.removeChild(t);
      return w;
    };
    const real = measureWith(`"${it.family}", monospace`);
    const fallback = measureWith('monospace');
    out.push({width: real, font_present: Math.abs(real - fallback) > 0.01 || it.text.length === 0});
  }
  return out;
}
"""


def browser_widths(items: list[dict]) -> list[dict]:
    """Chromium getComputedTextLength per (text, family, size, weight) after fonts load."""
    todo = [it for it in items if (it["text"], it["family"], it["size"], it["weight"]) not in _BROWSER_CACHE]
    presence: dict[tuple, bool] = {}
    if todo:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                page.set_content('<html><body><svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"></svg></body></html>')
                found = page.evaluate(_BROWSER_JS, todo)
            finally:
                browser.close()
        for it, got in zip(todo, found):
            key = (it["text"], it["family"], it["size"], it["weight"])
            _BROWSER_CACHE[key] = got["width"]
            presence[key] = got["font_present"]
    return [{"width": _BROWSER_CACHE[(it["text"], it["family"], it["size"], it["weight"])],
             "font_present": presence.get((it["text"], it["family"], it["size"], it["weight"]), True)} for it in items]


def verify_in_browser(measured: list[dict], tolerance_px: float = 1.0) -> list[dict]:
    """Attach browser widths to measured labels; returns residuals for disagreements or missing fonts."""
    items = []
    owners = []
    for index, label in enumerate(measured):
        for line_index, line in enumerate(label["lines"]):
            items.append({"text": line, "family": label["font"]["family"], "size": label["size_px"],
                          "weight": "bold" if label["font"]["weight"] == "bold" else "normal"})
            owners.append((index, line_index))
    residuals = []
    if not items:
        return residuals
    widths = browser_widths(items)
    for (index, line_index), got in zip(owners, widths):
        label = measured[index]
        label.setdefault("browser_line_widths_px", [None] * len(label["lines"]))
        label["browser_line_widths_px"][line_index] = round(got["width"], 2)
        if not got["font_present"]:
            label["browser_font_present"] = False
    for label in measured:
        browser = label.get("browser_line_widths_px") or []
        deltas = [round(b - a, 2) for a, b in zip(label["line_widths_px"], browser) if b is not None]
        label["browser_delta_px"] = max(deltas, key=abs) if deltas else None
        present = label.get("browser_font_present", True)
        label["browser_font_present"] = present
        if not present:
            residuals.append({"kind": "font_missing_in_browser", "id": label["id"],
                              "message": f"Chromium does not have {label['font']['family']}: widths unverified"})
        elif label["browser_delta_px"] is not None and abs(label["browser_delta_px"]) > tolerance_px:
            residuals.append({"kind": "browser_disagrees", "id": label["id"], "delta_px": label["browser_delta_px"],
                              "message": f"browser width differs from the font-file measurement by {label['browser_delta_px']} px"})
        else:
            label["measurement"] = "browser_verified"
    return residuals


def measure_request(request: dict) -> tuple[list[dict], list[dict]]:
    font = request.get("font") or {"family": "Segoe UI"}
    labels = request.get("labels")
    if not isinstance(labels, list) or not labels:
        raise HelperError("request.labels must be a non-empty list")
    ids = [label.get("id") for label in labels]
    if any(not i for i in ids) or len(set(ids)) != len(ids):
        raise HelperError("every label needs a unique id")
    measured = [measure_label(label, font) for label in labels]
    residuals: list[dict] = []
    for label in measured:
        if not label["floor"]["ok"]:
            residuals.append({"kind": "below_type_floor", "id": label["id"], "size_px": label["size_px"],
                              "floor_px": label["floor"]["min_px"],
                              "message": f"{label['role']} text at {label['size_px']} px is under the {label['floor']['min_px']} px floor"})
        for word in label["oversized_words"]:
            residuals.append({"kind": "word_wider_than_width", "id": label["id"], **word,
                              "message": f"'{word['word']}' is {word['width_px']} px, wider than {word['max_width_px']} px"})
        if label["font"]["file"] is None:
            residuals.append({"kind": "no_font_file", "id": label["id"],
                              "message": f"{label['font']['family']} has no font file here: width is the DrawingML estimate"})
    if str(request.get("verify") or "none") == "browser":
        residuals += verify_in_browser(measured, float(request.get("browser_tolerance_px") or 1.0))
    return measured, residuals


def _work(request: dict, _args) -> tuple[str, dict, list, list, None]:
    measured, residuals = measure_request(request)
    status = "ok" if not residuals else "partial"
    return status, {"labels": measured, "units": "svg px (1 px = 0.75 pt on a 13.333 in slide)"}, residuals, \
        [m["id"] for m in measured], None


def main(argv: list[str] | None = None) -> int:
    return run_cli(TOOL, argv, _work, description=__doc__)


if __name__ == "__main__":
    raise SystemExit(main())
