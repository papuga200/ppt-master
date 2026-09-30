#!/usr/bin/env python3
"""
PPT Master - Experimental timeline font metrics

Measure label widths from the real font file (FreeType through Pillow) instead of the
character-class estimator in text_measure.py, which ignores the font family. Advances are read
unhinted (the face is loaded at 1000 px and scaled), which matched Chromium's
getComputedTextLength within 0.05 px on Segoe UI and Century Gothic samples; Pillow's basic
layout applies no GPOS kerning, so kerned pairs measure slightly WIDER than a browser draws
them (the safe side for fit decisions).

Usage:
    from timeline_fonts import FontMetrics
    metrics = FontMetrics("Segoe UI")
    metrics.width("Anchor feeds and model", 14)

Dependencies:
    Pillow (optional: without it, or without a matching font file, `FontMetrics.method` is
    "estimator" and widths come from text_measure.py)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    from PIL import ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

_UNITS = 1000.0  # load the face at this pixel size; advances scale linearly (unhinted)
# family (lower case) -> (regular file, bold file); Windows font directory names
_FONT_FILES = {
    "segoe ui": ("segoeui.ttf", "segoeuib.ttf"),
    "century gothic": ("GOTHIC.TTF", "GOTHICB.TTF"),
    "arial": ("arial.ttf", "arialbd.ttf"),
    "calibri": ("calibri.ttf", "calibrib.ttf"),
    "georgia": ("georgia.ttf", "georgiab.ttf"),
    "verdana": ("verdana.ttf", "verdanab.ttf"),
    "tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "candara": ("Candara.ttf", "Candarab.ttf"),
    "corbel": ("corbel.ttf", "corbelb.ttf"),
    "arial narrow": ("ARIALN.TTF", "ARIALNB.TTF"),
}


def font_dirs() -> list[Path]:
    dirs = []
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        dirs.append(Path(windir) / "Fonts")
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    extra = os.environ.get("EXP_SVG_FONT_DIR")
    if extra:
        dirs.insert(0, Path(extra))
    return [d for d in dirs if d.is_dir()]


def families(stack: str) -> list[str]:
    """CSS font-family stack -> family names in order, unquoted."""
    return [part.strip().strip("'\"") for part in stack.split(",") if part.strip()]


def resolve_font_file(stack: str, bold: bool = False) -> tuple[str, Path] | None:
    """The first family of the stack that has a font file on this machine."""
    for family in families(stack):
        names = _FONT_FILES.get(family.lower())
        if not names:
            continue
        name = names[1 if bold else 0]
        for folder in font_dirs():
            path = folder / name
            if path.is_file():
                return family, path
            # case-insensitive match (font folders mix case)
            for candidate in folder.glob("*"):
                if candidate.name.lower() == name.lower():
                    return family, candidate
    return None


class FontMetrics:
    """Widths of text in one font stack, at any size, regular or bold."""

    def __init__(self, stack: str) -> None:
        self.stack = stack
        self._faces: dict[bool, object] = {}
        self.files: dict[str, str] = {}
        self.family: str | None = None
        self.method = "estimator"
        if HAS_PIL:
            for bold in (False, True):
                found = resolve_font_file(stack, bold)
                if found:
                    family, path = found
                    self._faces[bold] = ImageFont.truetype(str(path), int(_UNITS))
                    self.files["bold" if bold else "regular"] = str(path)
                    self.family = self.family or family
        if False in self._faces:
            self.method = "freetype-unhinted"

    def width(self, text: str, size: float, weight: str = "normal") -> float:
        if not text:
            return 0.0
        bold = str(weight).lower() in ("bold", "600", "700", "800", "900")
        face = self._faces.get(bold) or self._faces.get(False)
        if face is None:
            import text_measure
            return float(text_measure.measure_text(text, size=size, family=self.stack, weight=weight))
        return float(face.getlength(text)) * size / _UNITS

    def wrap(self, text: str, size: float, max_width: float, weight: str = "normal") -> tuple[list[str], float]:
        """Greedy word wrap; a single word wider than the line stays whole on its own line (never cut)."""
        words = text.split()
        if not words:
            return [], 0.0
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if self.width(trial, size, weight) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines, max(self.width(line, size, weight) for line in lines)

    def describe(self) -> dict:
        return {"stack": self.stack, "family": self.family, "method": self.method, "files": self.files}
