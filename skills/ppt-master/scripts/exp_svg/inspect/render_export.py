#!/usr/bin/env python3
"""
PPT Master - exp_svg render_export (fixed export configuration)

Renders and exports ONE SVG slide with a fixed configuration, using the fork's own tools on a
temporary project folder, and reports what the conversion changed. Steps:

    1. SVG preview PNG in Chromium (Playwright, 1600 x 900, fonts loaded)
    2. svg_quality_checker.py --quick-generate --canonical-authoring --stage final --json (exporter gate)
    3. svg_to_pptx.py --quick-generate --no-animations [--native-charts-and-tables when the SVG carries
       data-pptx-replace-with markers]
    4. native object counts, text-token retention and arrowhead comparison from the PPTX XML
    5. pptx_render.py (Microsoft PowerPoint through COM) and pptx_parity.py
       - both serialized behind one machine-wide lock: PowerPoint is a single shared COM instance
    6. measured arrowhead width at each marker tip, SVG preview vs PowerPoint render

Every step records elapsed seconds, exit code and log files. Findings are attributed: the
exporter's contract gate (the SVG is outside the supported subset), conversion (the exporter or
PowerPoint changed something the SVG showed), or environment (a renderer is unavailable). A
conversion finding is never charged to the SVG author.

Usage:
    python3 render_export.py --svg slide.svg --out DIR [--native-charts-and-tables auto|on|off] [--no-powerpoint]

Examples:
    python3 render_export.py --svg page.svg --out runs/p1/render

Dependencies:
    playwright (Chromium), lxml, Pillow; Microsoft PowerPoint for steps 5-6 (else reported unverified)
"""

from __future__ import annotations

import argparse
import ctypes
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import common  # noqa: E402

common.ensure_scripts_path()

import checks as C  # noqa: E402
import geom as G  # noqa: E402

TOOL = "render_export"
PYTHON = Path(sys.executable)
SCRIPTS = common.SCRIPTS_DIR
EMU_PER_PX = 12192000 / 1280.0
PREVIEW_W = 1600
PML = "http://schemas.openxmlformats.org/presentationml/2006/main"
AML = "http://schemas.openxmlformats.org/drawingml/2006/main"
LOCK = Path(tempfile.gettempdir()) / "exp_svg_powerpoint.lock"
INK_LEVEL = 200  # grey level below which a pixel counts as ink (catches mid-grey arrowheads on white)


# ---------------------------------------------------------------------------------------------
# machine-wide PowerPoint lock
# ---------------------------------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


class PowerPointLock:
    """One PowerPoint user at a time on this machine. Waits without a deadline; a lock left by a
    process that no longer exists is taken over (and said so)."""

    def __init__(self, path: Path = LOCK):
        self.path = path
        self.waited_s = 0.0
        self.took_over: Optional[int] = None

    def __enter__(self) -> "PowerPointLock":
        started = time.perf_counter()
        announced = False
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                break
            except FileExistsError:
                try:
                    owner = int(self.path.read_text(encoding="ascii").strip() or "0")
                except (OSError, ValueError):
                    owner = 0
                if owner and not _pid_alive(owner):
                    self.took_over = owner
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                if not announced:
                    print(f"waiting for the PowerPoint lock held by pid {owner} ({self.path})", file=sys.stderr)
                    announced = True
                time.sleep(1.0)
        self.waited_s = time.perf_counter() - started
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.path.read_text(encoding="ascii").strip() == str(os.getpid()):
                self.path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------------------------
# steps
# ---------------------------------------------------------------------------------------------
def run_step(name: str, command: list[str], out: Path, cwd: Optional[Path] = None) -> dict:
    logs = out / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    with (logs / f"{name}.stdout.log").open("wb") as so, (logs / f"{name}.stderr.log").open("wb") as se:
        code = subprocess.run(command, stdout=so, stderr=se, cwd=str(cwd or SCRIPTS), env=env).returncode
    return {"name": name, "command": [str(c) for c in command], "exit_code": code, "elapsed_s": round(time.perf_counter() - started, 3),
            "stdout": str(logs / f"{name}.stdout.log"), "stderr": str(logs / f"{name}.stderr.log")}


def _log_tail(path: str, n: int = 12) -> list[str]:
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [ln for ln in lines if ln.strip()][-n:]


def prepare_project(svg: Path, project: Path) -> tuple[Path, list[dict]]:
    """Copy the SVG into <project>/svg_output and the local files it references, keeping their relative paths."""
    if project.exists():
        shutil.rmtree(project)
    (project / "svg_output").mkdir(parents=True)
    target = project / "svg_output" / (re.sub(r"[^A-Za-z0-9_.-]", "_", svg.stem) + ".svg")
    shutil.copy2(svg, target)
    notes = []
    text = svg.read_text(encoding="utf-8-sig")
    for href in sorted(set(re.findall(r'(?:xlink:)?href="([^"#][^"]*)"', text))):
        if re.match(r"^(data|https?):", href):
            continue
        src = (svg.parent / href).resolve()
        dst = (target.parent / href).resolve()
        if not str(dst).startswith(str(project.resolve())):
            notes.append({"href": href, "copied": False, "why": "path leaves the temporary project"})
            continue
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            notes.append({"href": href, "copied": True})
        else:
            notes.append({"href": href, "copied": False, "why": "file not found next to the SVG"})
    return target, notes


def normalise_root_bounds(page: Path) -> list[str]:
    """The fork's exporter requires every visible root-level <g> to declare a `data-pptx-bounds` zone, and ordinary root zones
    must not overlap. Creators in the experiment are not told this exporter-dialect rule, so the fixed export stage wraps the
    page's root content outside the template chrome into ONE body group that declares the full canvas - in the temporary copy
    only; the authored SVG is unchanged. Returns the ids of the root groups it wrapped (empty when nothing was needed)."""
    import os
    import stat
    text = page.read_text(encoding="utf-8-sig")
    root = re.search(r"<svg\b[^>]*>", text)
    close = text.rfind("</svg>")
    if not root or close < 0:
        return []
    view = re.search(r'viewBox="\s*([\d.\-]+)[ ,]+([\d.\-]+)[ ,]+([\d.\-]+)[ ,]+([\d.\-]+)', root.group(0))
    bounds = " ".join(view.groups()) if view else "0 0 1280 720"
    body = text[root.end():close]
    spans, depth, start_at, first = [], 0, None, None   # root-level element spans: (start, end, name, attrs)
    for m in re.finditer(r"<(/?)([A-Za-z][\w:.-]*)((?:[^<>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>", body):
        closing, name, attrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
        if closing:
            depth -= 1
            if depth == 0 and first is not None:
                spans.append((start_at, m.end(), first[0], first[1]))
                first = None
        else:
            if depth == 0:
                if selfclose:
                    spans.append((m.start(), m.end(), name, attrs))
                else:
                    start_at, first = m.start(), (name, attrs)
            if not selfclose:
                depth += 1
    keep_out = {"defs", "style", "title", "desc", "metadata"}
    def is_chrome(name: str, attrs: str) -> bool:
        return name == "g" and ('data-pptx-role="chrome"' in attrs or re.search(r'\bid="(chrome|template-chrome)"', attrs) is not None)
    loose = [s for s in spans if s[2] not in keep_out and not is_chrome(s[2], s[3])]
    needs = [s for s in loose if s[2] == "g" and "data-pptx-bounds" not in s[3]]
    if not needs:
        return []
    touched = [(re.search(r'\bid="([^"]*)"', s[3]).group(1) if re.search(r'\bid="([^"]*)"', s[3]) else "(no id)") for s in needs]
    first_start, last_end = loose[0][0], loose[-1][1]
    inner = body[first_start:last_end]
    # chrome or defs that sit between body elements stay where they are: only wrap when the body elements are contiguous
    between = [s for s in spans if first_start <= s[0] < last_end and s not in loose]
    if between:
        parts, cursor = [], first_start
        for s in between:
            parts.append(body[cursor:s[0]])
            cursor = s[1]
        parts.append(body[cursor:last_end])
        inner = "".join(parts)
        moved = "".join(body[s[0]:s[1]] for s in between)
    else:
        moved = ""
    wrapped = (body[:first_start] + moved + f'<g id="export-body" data-pptx-bounds="{bounds}">' + inner + "</g>" + body[last_end:])
    os.chmod(page, stat.S_IWRITE | stat.S_IREAD)  # the copy of a locked (read-only) draft
    page.write_text(text[:root.end()] + wrapped + text[close:], encoding="utf-8")
    return touched


def pptx_inventory(pptx: Path) -> dict:
    from lxml import etree
    with zipfile.ZipFile(pptx) as archive:
        bad = archive.testzip()
        names = sorted(n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
        media = [n for n in archive.namelist() if n.startswith("ppt/media/")]
        slides = []
        for name in names:
            root = etree.fromstring(archive.read(name))
            ns = {"p": PML, "a": AML}
            sps = root.findall(".//p:sp", ns)
            pics = root.findall(".//p:pic", ns)
            cxn = root.findall(".//p:cxnSp", ns)
            frames = root.findall(".//p:graphicFrame", ns)
            grps = root.findall(".//p:grpSp", ns)
            texts = [t.text for t in root.iter(f"{{{AML}}}t") if t.text]
            text_shapes = sum(1 for sp in sps if any((t.text or "").strip() for t in sp.iter(f"{{{AML}}}t")))
            big_pics = []
            for pic in pics:
                ext = pic.find(".//a:xfrm/a:ext", ns)
                if ext is not None:
                    w, h = int(ext.get("cx")) / EMU_PER_PX, int(ext.get("cy")) / EMU_PER_PX
                    if w * h >= 0.25 * 1280 * 720:
                        big_pics.append({"w_px": round(w), "h_px": round(h)})
            slides.append({"part": name, "shapes": len(sps), "text_shapes": text_shapes, "pictures": len(pics), "connectors": len(cxn),
                           "graphic_frames": len(frames), "tables": len(root.findall(".//a:tbl", ns)), "groups": len(grps),
                           "text_runs": len(texts), "large_pictures": big_pics, "texts": texts, "lines": _line_ends(root)})
    return {"zip_ok": bad is None, "slides": slides, "media": media}


def _line_ends(root) -> list[dict]:
    """Every PPTX shape with a line end (arrowhead): name, end points in slide px, head/tail spec, line width."""
    ns = {"p": PML, "a": AML}
    out = []
    for sp in list(root.iter(f"{{{PML}}}sp")) + list(root.iter(f"{{{PML}}}cxnSp")):
        ln = sp.find(".//p:spPr/a:ln", ns)
        if ln is None:
            continue
        head, tail = ln.find("a:headEnd", ns), ln.find("a:tailEnd", ns)
        if head is None and tail is None:
            continue
        xfrm = sp.find(".//p:spPr/a:xfrm", ns)
        if xfrm is None:
            continue
        off, ext = xfrm.find("a:off", ns), xfrm.find("a:ext", ns)
        x, y = int(off.get("x")) / EMU_PER_PX, int(off.get("y")) / EMU_PER_PX
        w, h = int(ext.get("cx")) / EMU_PER_PX, int(ext.get("cy")) / EMU_PER_PX
        flip_h, flip_v = xfrm.get("flipH") == "1", xfrm.get("flipV") == "1"
        rot = int(xfrm.get("rot") or 0) / 60000.0
        path = sp.find(".//a:custGeom/a:pathLst/a:path", ns)
        if path is not None:
            pw, ph = float(path.get("w") or 1), float(path.get("h") or 1)
            pts = [(float(pt.get("x")), float(pt.get("y"))) for pt in path.iter(f"{{{AML}}}pt")]
            local = [(px / pw * w if pw else 0.0, py / ph * h if ph else 0.0) for px, py in pts]
            start, end = local[0], local[-1]
        else:
            start, end = (0.0, 0.0), (w, h)
        def place(p):
            px, py = p
            if flip_h:
                px = w - px
            if flip_v:
                py = h - py
            if rot:
                cx, cy = w / 2, h / 2
                a = math.radians(rot)
                px, py = cx + (px - cx) * math.cos(a) - (py - cy) * math.sin(a), cy + (px - cx) * math.sin(a) + (py - cy) * math.cos(a)
            return [x + px, y + py]
        name = (sp.find(".//p:cNvPr", ns).get("name") if sp.find(".//p:cNvPr", ns) is not None else None)
        width_px = int(ln.get("w") or 12700) / EMU_PER_PX
        spec = lambda e: None if e is None else {"type": e.get("type"), "w": e.get("w") or "med", "len": e.get("len") or "med"}  # noqa: E731
        out.append({"name": name, "start": place(start), "end": place(end), "head": spec(head), "tail": spec(tail), "line_px": round(width_px, 3)})
    return out


def _svg_arrows(svg: Path, geometry: dict) -> list[dict]:
    """SVG connectors with markers: tips, marker length in px, orient."""
    defs = C.parse_defs(svg.read_bytes())["markers"]
    out = []
    for s in geometry["shapes"]:
        if not s.get("points"):
            continue
        for which in ("start", "end"):
            mid = s["markers"].get(which)
            if not mid:
                continue
            spec = defs.get(mid) or {}
            tip = s["points"][0] if which == "start" else s["points"][-1]
            length = None
            if spec.get("points"):
                xs = [p[0] for p in spec["points"]]
                span = max(xs) - min(xs)
                vbw = (spec.get("viewBox") or [0, 0, spec.get("markerWidth", 3.0), 0])[2] or spec.get("markerWidth", 3.0)
                units = s["stroke_px"] if spec.get("markerUnits", "strokeWidth") != "userSpaceOnUse" else s["scale"]
                length = span / vbw * spec.get("markerWidth", 3.0) * units
            v = G.direction(s["points"], at_end=(which == "end"))
            if v is not None and which == "start":
                v = (-v[0], -v[1])
            out.append({"ref": s["ref"], "id": s.get("id"), "which": which, "tip": tip, "dir": v, "marker": mid, "orient": spec.get("orient"),
                        "curved_marker": spec.get("curved"), "marker_len_px": length, "stroke_px": s["stroke_px"]})
    return out


def arrow_findings(svg_arrows: list[dict], pptx_lines: list[dict]) -> list[dict]:
    findings = []
    for a in svg_arrows:
        best, best_d, end_key = None, 1e9, None
        for ln in pptx_lines:
            for key, pt in (("head", ln["start"]), ("tail", ln["end"])):
                d = math.hypot(pt[0] - a["tip"][0], pt[1] - a["tip"][1])
                if a.get("id") and ln.get("name") == a["id"]:
                    d -= 0.001
                if d < best_d:
                    best, best_d, end_key = ln, d, key
        row = {"svg_ref": a["ref"], "svg_end": a["which"], "tip_px": [round(v, 1) for v in a["tip"]], "svg_marker_len_px": a["marker_len_px"],
               "svg_orient": a["orient"], "attribution": "conversion"}
        if best is None or best_d > 4.0:
            row.update(code="ARROWHEAD_DROPPED", severity="major", message="no PPTX line end found at this SVG arrow tip: the arrowhead (or the line) was not converted")
            findings.append(row)
            continue
        spec = best.get(end_key)
        row.update(pptx_shape=best.get("name"), pptx_end=end_key, match_distance_px=round(best_d, 2))
        if spec is None:
            other = "tail" if end_key == "head" else "head"
            row.update(code="ARROWHEAD_DROPPED" if best.get(other) is None else "ARROWHEAD_MOVED", severity="major",
                       message=f"the PPTX line has no line end at this tip (it has one at the {other} end)" if best.get(other) else "the PPTX line has no line end here")
            findings.append(row)
            continue
        row.update(pptx_line_end=spec, pptx_line_px=best["line_px"], dir=a.get("dir"))
        notes = []
        if a["orient"] not in (None, "auto", "auto-start-reverse"):
            notes.append(f"SVG marker has a fixed orient={a['orient']}; DrawingML line ends always follow the line, so the arrow direction may change")
        if a["which"] == "start" and a["orient"] == "auto":
            notes.append("SVG marker-start with orient=auto points into the line; the PPTX head end points outward: direction changes")
        if a.get("curved_marker"):
            notes.append("SVG marker is drawn with curves: its shape is approximated by a preset line end")
        if notes:
            row.update(code="ARROWHEAD_CHANGED", severity="minor", message="; ".join(notes))
        else:
            row.update(code="ARROWHEAD_KEPT", severity="info", message="line end present at the same tip")
        findings.append(row)
    return findings


def _head_width(img, tip, v, k: float) -> float:
    """Widest dark span across the line within 14 px behind the tip (slide px): the arrowhead's width."""
    if v is None:
        return 0.0
    px, py = -v[1], v[0]
    best = 0.0
    for back in [i * 0.5 for i in range(1, 29)]:
        cx, cy = tip[0] - v[0] * back, tip[1] - v[1] * back
        span, run = 0.0, 0.0
        for j in range(-40, 41):
            t = j * 0.5
            x, y = int(round((cx + px * t) * k)), int(round((cy + py * t) * k))
            if 0 <= x < img.size[0] and 0 <= y < img.size[1] and img.getpixel((x, y)) < INK_LEVEL:
                run += 0.5
                span = max(span, run)
            else:
                run = 0.0
        best = max(best, span)
    return best


def ink_ratio(svg_png: Path, pptx_png: Path, tips: list[dict]) -> list[dict]:
    """Measured arrowhead width (widest dark span across the line near the tip), SVG preview vs PowerPoint render."""
    from PIL import Image
    a = Image.open(svg_png).convert("L")
    b = Image.open(pptx_png).convert("L")
    if b.size != a.size:
        b = b.resize(a.size)
    k = a.size[0] / 1280.0
    out = []
    for t in tips:
        wa, wb = _head_width(a, t["tip_px"], t.get("dir"), k), _head_width(b, t["tip_px"], t.get("dir"), k)
        out.append({"svg_ref": t["svg_ref"], "svg_end": t["svg_end"], "head_width_svg_px": wa, "head_width_pptx_px": wb,
                    "ratio_pptx_to_svg": round(wb / wa, 2) if wa else None,
                    "method": f"widest run of ink pixels (grey < {INK_LEVEL}) across the line, 0-14 px behind the tip, in slide px"})
    return out


def token_retention(svg_texts: list[str], pptx_texts: list[str]) -> dict:
    import collections
    src = collections.Counter(t for s in svg_texts for t in C.tokens(s))
    dst = collections.Counter(t for s in pptx_texts for t in C.tokens(s))
    missing, extra = src - dst, dst - src
    return {"method": "NFKC case-folded word tokens (stop words dropped), multiset", "svg_tokens": sum(src.values()), "pptx_tokens": sum(dst.values()),
            "missing_in_pptx": dict(missing), "extra_in_pptx": dict(extra), "equal": not missing and not extra}


def render_export(svg: Path, out: Path, *, native: str = "auto", powerpoint: bool = True) -> dict:
    started = time.perf_counter()
    svg = Path(svg).resolve()
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    data = svg.read_bytes()
    art = {"path": str(svg), "sha256": common.sha256_bytes(data), "bytes": len(data)}
    steps, findings = [], []
    result = {"artifact": art, "config": {"exporter": "svg_to_pptx.py --quick-generate --no-animations", "native_charts_and_tables": native,
                                         "preview_width_px": PREVIEW_W, "powerpoint": powerpoint}}
    # 1. SVG preview + geometry
    from svg_geometry import Browser
    t0 = time.perf_counter()
    preview = out / "svg_preview.png"
    with Browser(device_scale=PREVIEW_W / 1280.0) as browser:
        geometry = browser.measure(svg, preview)
    steps.append({"name": "svg_preview", "exit_code": 0, "elapsed_s": round(time.perf_counter() - t0, 3), "output": common.file_fact(preview),
                  "renderer": f"chromium {geometry.get('browser', {}).get('version')}"})
    # 2-3. temporary project, gate, export
    project = out / "_project"
    page, copies = prepare_project(svg, project)
    result["project"] = {"path": str(project), "page": str(page), "referenced_files": copies}
    normalised = normalise_root_bounds(page)  # experiment decision D030: the export stage declares root bounds, not the author
    if normalised:
        findings.append({"attribution": "exporter_contract", "code": "ROOT_BOUNDS_DECLARED_BY_EXPORT_STAGE", "severity": "info",
                                   "message": f"{len(normalised)} root-level <g> without data-pptx-bounds: the page body outside the template chrome was wrapped in one "
                                              f"export-body group declaring the full canvas, in the export copy only (the authored SVG is unchanged): {', '.join(normalised)}"})
    use_native = native == "on" or (native == "auto" and b"data-pptx-replace-with" in data)
    gate = run_step("quality_gate", [str(PYTHON), str(SCRIPTS / "svg_quality_checker.py"), str(project), "--quick-generate",
                                     "--canonical-authoring", "--stage", "final", "--json"], out)
    steps.append(gate)
    pptx = out / "slide.pptx"
    if gate["exit_code"] != 0:
        errs = [ln.strip() for ln in _log_tail(gate["stdout"], 80) if "[ERROR]" in ln and "With errors" not in ln and " - Failed" not in ln]
        findings.append({"code": "EXPORT_GATE_REFUSED", "severity": "blocker", "attribution": "exporter_contract",
                         "message": "the fork's SVG contract gate refused the page, so no native PPTX was produced", "details": errs[:20]})
    else:
        cmd = [str(PYTHON), str(SCRIPTS / "svg_to_pptx.py"), str(project), "-o", str(pptx), "--quick-generate", "--no-animations"]
        if use_native:
            cmd.append("--native-charts-and-tables")
        exp = run_step("export", cmd, out)
        steps.append(exp)
        if exp["exit_code"] != 0 or not pptx.is_file():
            findings.append({"code": "CONVERSION_FAILED", "severity": "blocker", "attribution": "conversion",
                             "message": "svg_to_pptx.py failed on a page its gate accepted", "details": _log_tail(exp["stderr"]) + _log_tail(exp["stdout"])})
    # 4. native inventory, text retention, arrowheads (XML)
    if pptx.is_file():
        inv = pptx_inventory(pptx)
        slide = inv["slides"][0] if inv["slides"] else {}
        model = C.Model(geometry, C.parse_defs(data))
        svg_texts = [t["text"] for t in model.texts]  # visible text, lines joined with spaces (not raw textContent)
        result["pptx"] = {**common.file_fact(pptx), "zip_ok": inv["zip_ok"], "slides": len(inv["slides"]), "media_parts": len(inv["media"]),
                          "native": {k: slide.get(k) for k in ("shapes", "text_shapes", "pictures", "connectors", "graphic_frames", "tables", "groups", "text_runs")},
                          "large_pictures": slide.get("large_pictures", [])}
        result["text_retention"] = token_retention(svg_texts, slide.get("texts", []))
        if not result["text_retention"]["equal"]:
            findings.append({"code": "TEXT_TOKENS_CHANGED", "severity": "major", "attribution": "conversion",
                             "message": "words differ between the SVG and the PPTX text", "details": {k: result["text_retention"][k] for k in ("missing_in_pptx", "extra_in_pptx")}})
        if slide.get("large_pictures"):
            findings.append({"code": "LARGE_PICTURE", "severity": "major", "attribution": "conversion_or_author",
                             "message": "a picture covers a quarter of the slide or more: content may be rasterized (check the SVG for an <image>)", "details": slide["large_pictures"]})
        if len(inv["slides"]) != 1:
            findings.append({"code": "SLIDE_COUNT", "severity": "blocker", "attribution": "conversion", "message": f"{len(inv['slides'])} slides exported, expected 1"})
        arrows = arrow_findings(_svg_arrows(svg, geometry), slide.get("lines", []))
        result["arrowheads"] = arrows
        findings += [dict(a, message=a["message"]) for a in arrows if a["severity"] in ("major", "minor")]
    # 5. PowerPoint render + parity (serialized)
    render_dir = out / "pptx_render"
    if pptx.is_file() and powerpoint:
        with PowerPointLock() as lock:
            result["powerpoint_lock"] = {"path": str(LOCK), "waited_s": round(lock.waited_s, 3), "took_over_stale_pid": lock.took_over}
            ren = run_step("pptx_render", [str(PYTHON), str(SCRIPTS / "pptx_render.py"), str(pptx), "--out", str(render_dir), "--width", str(PREVIEW_W)], out)
            steps.append(ren)
            par = run_step("pptx_parity", [str(PYTHON), str(SCRIPTS / "pptx_parity.py"), str(pptx), "--project", str(project), "--render", str(render_dir),
                                           "--out", str(out / "parity.json"), "--md", str(out / "parity.md")], out)
            steps.append(par)
        pngs = sorted(render_dir.glob("slide-*.png"))
        if ren["exit_code"] != 0 or not pngs:
            findings.append({"code": "POWERPOINT_RENDER_UNAVAILABLE", "severity": "info", "attribution": "environment",
                             "message": "PowerPoint render not produced: the PPTX is unverified in PowerPoint", "details": _log_tail(ren["stdout"]) + _log_tail(ren["stderr"])})
        else:
            result["pptx_render"] = [common.file_fact(p) for p in pngs]
            tips = [a for a in result.get("arrowheads", []) if "tip_px" in a]
            if tips:
                result["arrowhead_ink"] = ink_ratio(preview, pngs[0], tips)
                for row, t in zip(result["arrowhead_ink"], tips):
                    shared = [o["svg_ref"] for o in tips if o is not t and math.hypot(o["tip_px"][0] - t["tip_px"][0], o["tip_px"][1] - t["tip_px"][1]) <= 3.0]
                    if shared:
                        row["shared_tip_with"] = shared
                        row["note"] = "several arrow tips coincide here: the widths include every head at this point"
                    nominal = next((a.get("svg_marker_len_px") for a in result.get("arrowheads", []) if a["svg_ref"] == t["svg_ref"] and a.get("svg_end") == t.get("svg_end")), None)
                    if nominal and row["head_width_svg_px"] > 2.5 * nominal:
                        row["contaminated"] = True
                        row["note"] = "the tip touches other ink (a filled shape or line): the width is not the arrowhead's alone"
                for row in result["arrowhead_ink"]:
                    r = row["ratio_pptx_to_svg"]
                    if row.get("shared_tip_with") or row.get("contaminated"):
                        continue  # measurement not attributable to one arrowhead; kept in arrowhead_ink with its note
                    if r is not None and (r < 0.75 or r > 1.33):
                        findings.append({"code": "ARROWHEAD_SIZE_CHANGED", "severity": "minor", "attribution": "conversion", "svg_ref": row["svg_ref"],
                                         "message": (f"arrowhead width changes x{r} ({row['head_width_svg_px']:.1f} px in the SVG preview, "
                                                     f"{row['head_width_pptx_px']:.1f} px in the PowerPoint render)"), "details": row})
        if par["exit_code"] == 0 and (out / "parity.json").is_file():
            parity = common.read_json(out / "parity.json")
            result["parity"] = {"summary": parity.get("summary"), "report": str(out / "parity.json")}
            for f in parity.get("findings", []):
                findings.append({"code": f"PARITY_{f['code']}", "severity": "major" if f["severity"] == "certain" else "minor", "attribution": "conversion",
                                 "message": f["message"][:300], "details": {"shape": f.get("shape"), "bbox_px": f.get("bbox")}})
        elif par["exit_code"] == 3:
            findings.append({"code": "PARITY_UNAVAILABLE", "severity": "info", "attribution": "environment", "message": "pptx_parity.py could not drive PowerPoint"})
        else:
            findings.append({"code": "PARITY_FAILED", "severity": "info", "attribution": "environment", "message": "pptx_parity.py failed", "details": _log_tail(par["stderr"])})
    elif pptx.is_file():
        findings.append({"code": "POWERPOINT_SKIPPED", "severity": "info", "attribution": "environment", "message": "PowerPoint steps skipped by request: unverified in PowerPoint"})
    exported = pptx.is_file()
    rendered = bool(result.get("pptx_render"))
    status = "ok" if exported and (rendered or not powerpoint) and not any(f["code"] in ("PARITY_FAILED", "PARITY_UNAVAILABLE") for f in findings) else ("partial" if exported else "error")
    env = common.envelope(TOOL, input_hash=art["sha256"], status=status, started=started)
    env.update(result)
    env["steps"] = steps
    env["findings"] = findings
    env["attribution_note"] = ("conversion findings describe what the exporter or PowerPoint changed; they are not author defects. "
                               "exporter_contract findings mean the SVG is outside the exporter's supported subset.")
    outputs = [p for p in (preview, pptx, *sorted(render_dir.glob("slide-*.png"))) if p.is_file()]
    env["output_sha256"] = common.sha256_bytes("".join(common.sha256_file(p) for p in outputs).encode("ascii")) if outputs else None
    env["outputs"] = [common.file_fact(p) for p in outputs]
    env["elapsed_s"] = round(time.perf_counter() - started, 3)
    return env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fixed-configuration SVG preview, native PPTX export, PowerPoint render and parity for one slide.",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--in", dest="request", type=Path, default=None, help="harness request file (accepted and recorded; the export configuration is fixed)")
    parser.add_argument("--native-charts-and-tables", choices=["auto", "on", "off"], default="auto")
    parser.add_argument("--no-powerpoint", action="store_true", help="skip the PowerPoint render and parity (reported as unverified)")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    from console_encoding import configure_utf8_stdio
    configure_utf8_stdio()
    if not args.svg.is_file():
        print(f"error: no such SVG: {args.svg}", file=sys.stderr)
        return 1
    # harness call shape (orchestrator integration): `--in request.json --out <file>.json` -> artifacts go to a folder beside the
    # result file and the result is ALSO written to that file, so the harness finds what it expects
    result_file = None
    if str(args.out).lower().endswith(".json"):
        result_file = Path(args.out)
        args.out = result_file.parent / "artifacts"
    result = render_export(args.svg, args.out, native=args.native_charts_and_tables, powerpoint=not args.no_powerpoint)
    path = Path(args.out) / "render_export.json"
    digest = common.write_json(path, result)
    if result_file is not None:
        common.write_json(result_file, result)
    counts = {}
    for f in result["findings"]:
        counts[f["attribution"]] = counts.get(f["attribution"], 0) + 1
    print(f"{TOOL}: status {result['status']} | findings by attribution {counts} | {path} (sha256 {digest[:16]}) | {result['elapsed_s']} s")
    for step in result["steps"]:
        print(f"  {step['name']}: exit {step['exit_code']} in {step['elapsed_s']} s")
    if (Path(args.out) / "svg_preview.png").is_file():
        print(f"IMAGE: {Path(args.out).resolve() / 'svg_preview.png'}")
    for p in result.get("pptx_render", []):
        print(f"IMAGE: {p['path']}")
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
