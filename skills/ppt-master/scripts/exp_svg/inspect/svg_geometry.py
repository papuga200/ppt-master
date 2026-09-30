#!/usr/bin/env python3
"""
PPT Master - exp_svg inspection: browser geometry extraction

Loads one SVG in headless Chromium (Playwright) exactly once per call, waits for
``document.fonts.ready``, and returns what the browser actually laid out: every text run's box
and effective font size, every shape's transformed box, every open stroke's sampled centre line,
end points and end tangents, marker references, clip-path chains, filters and masks. All
coordinates are slide pixels (1280 x 720 by default): element-local geometry is mapped through
the element's full CTM relative to the root SVG user space, then through the viewBox.

This is an independent measurement, not the author's self-report and not page_lint.py (which
the authors see during construction). It records what it cannot measure instead of guessing:
filter extents, mask effects, foreignObject content, stroke outlines and glyph ink are not
measured (see UNMEASURED in inspect_svg.py).

Usage:
    Imported by inspect_svg.py and render_export.py; not a command.

Dependencies:
    playwright (with its Chromium) from the fork's venv
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterator, Optional

if __name__ == "__main__" and any(arg in {"-h", "--help", "help"} for arg in sys.argv[1:]):
    print(__doc__)
    raise SystemExit(0)

EXTRACT_JS = r"""
async (opts) => {
  if (document.fonts && document.fonts.ready) { await document.fonts.ready; }
  const svg = document.querySelector('svg');
  if (!svg) return {error: 'no <svg> root element'};
  const W = opts.canvasW, H = opts.canvasH;
  const vbBase = svg.viewBox && svg.viewBox.baseVal;
  const vb = (vbBase && vbBase.width > 0 && vbBase.height > 0)
    ? {x: vbBase.x, y: vbBase.y, w: vbBase.width, h: vbBase.height, declared: true}
    : {x: 0, y: 0, w: (svg.width && svg.width.baseVal.value) || W, h: (svg.height && svg.height.baseVal.value) || H, declared: false};
  const KX = W / vb.w, KY = H / vb.h;
  const rootCTM = svg.getScreenCTM();
  const rootInv = rootCTM.inverse();
  const SKIP = 'defs,clipPath,mask,marker,pattern,symbol,linearGradient,radialGradient,filter,title,desc,metadata,style,script';
  const inDefs = el => { for (let n = el; n && n !== svg; n = n.parentElement) { if (n.matches && n.matches(SKIP)) return true; } return false; };
  const rel = el => { const m = el.getScreenCTM ? el.getScreenCTM() : null; return m ? rootInv.multiply(m) : null; };
  const mat = m => m ? [m.a, m.b, m.c, m.d, m.e, m.f] : null;
  const P = (m, x, y) => [(m.a * x + m.c * y + m.e - vb.x) * KX, (m.b * x + m.d * y + m.f - vb.y) * KY];
  const S2S = (x, y) => { const p = new DOMPoint(x, y).matrixTransform(rootInv); return [(p.x - vb.x) * KX, (p.y - vb.y) * KY]; };
  const scaleOf = m => Math.sqrt(Math.abs(m.a * m.d - m.b * m.c)) * Math.sqrt(KX * KY);
  const aabb = pts => { const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]); return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]; };
  const boxOf = (m, b) => aabb([P(m, b.x, b.y), P(m, b.x + b.width, b.y), P(m, b.x, b.y + b.height), P(m, b.x + b.width, b.y + b.height)]);
  const clientBox = r => aabb([S2S(r.left, r.top), S2S(r.right, r.top), S2S(r.left, r.bottom), S2S(r.right, r.bottom)]);
  const order = new Map(); [...svg.querySelectorAll('*')].forEach((el, i) => order.set(el, i));
  const pathOf = el => {
    const parts = [];
    for (let n = el; n && n !== svg; n = n.parentElement) {
      if (n.id) { parts.unshift('#' + n.id); return parts.join('/'); }
      const same = [...n.parentElement.children].filter(c => c.tagName === n.tagName);
      parts.unshift(n.localName + '[' + (same.indexOf(n) + 1) + ']');
    }
    return '/' + parts.join('/');
  };
  const ancestorsIds = el => { const ids = []; for (let n = el.parentElement; n && n !== svg; n = n.parentElement) if (n.id) ids.push(n.id); return ids; };
  const DATA = ['data-content-id', 'data-role', 'data-type-role', 'data-text-role', 'data-pptx-role', 'data-kind', 'data-lint-ok', 'data-pptx-replace-with', 'data-from', 'data-to'];
  const dataOf = el => { const out = {}; for (let n = el; n && n !== svg; n = n.parentElement) { DATA.forEach(a => { const v = n.getAttribute(a); if (v !== null && !(a in out)) out[a] = v; }); } return out; };
  const vis = el => {
    let o = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (cs.display === 'none') return 0;
      o *= parseFloat(cs.opacity || '1');
      if (n === svg) break;
    }
    if (getComputedStyle(el).visibility === 'hidden') return 0;
    return o;
  };
  const chains = el => {
    const clips = [], filters = [], masks = [];
    for (let n = el; n && n !== svg.parentElement; n = n.parentElement) {
      const cs = getComputedStyle(n);
      const idOf = v => { const m = /url\(["']?#([^"')]+)["']?\)/.exec(v || ''); return m ? m[1] : null; };
      if (cs.clipPath && cs.clipPath !== 'none') {
        const m = rel(n); let bb = null; try { const b = n.getBBox(); bb = [b.x, b.y, b.width, b.height]; } catch (e) {}
        clips.push({id: idOf(cs.clipPath), raw: cs.clipPath, on: n.id || pathOf(n), m: mat(m), bbox_local: bb});
      }
      if (cs.filter && cs.filter !== 'none') filters.push({value: cs.filter, on: n.id || pathOf(n)});
      if (cs.mask && cs.mask !== 'none') masks.push({value: cs.mask, on: n.id || pathOf(n)});
      if (n === svg) break;
    }
    return {clips, filters, masks};
  };
  const idRef = v => { const m = /url\(["']?#([^"')]+)["']?\)/.exec(v || ''); return m ? m[1] : null; };
  const out = {canvas: [W, H], viewBox: vb, scale: [KX, KY], texts: [], shapes: [], groups: [], unsupported: [], fonts: {}};

  // ---- text ----
  const stacks = new Set();
  svg.querySelectorAll('text').forEach(t => {
    if (inDefs(t)) return;
    const o = vis(t);
    const m = rel(t);
    const cs = getComputedStyle(t);
    const runs = [];
    const walker = document.createTreeWalker(t, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const raw = node.textContent;
      if (!raw || !raw.trim()) continue;
      const pe = node.parentElement;
      if (pe.closest('textPath')) { out.unsupported.push({kind: 'textPath', ref: t.id || pathOf(t)}); }
      const pcs = getComputedStyle(pe);
      if (pcs.display === 'none' || pcs.visibility === 'hidden') continue;
      const pm = rel(pe) || m;
      const range = document.createRange(); range.selectNodeContents(node);
      const rects = [...range.getClientRects()].filter(r => r.width > 0.05 && r.height > 0.05).map(clientBox);
      if (!rects.length) continue;
      stacks.add(pcs.fontFamily);
      runs.push({text: raw.replace(/\s+/g, ' ').trim(), rects, ws_before: /^\s/.test(raw), ws_after: /\s$/.test(raw),
                 font_size_local: parseFloat(pcs.fontSize), font_px: parseFloat(pcs.fontSize) * scaleOf(pm),
                 family: pcs.fontFamily, weight: pcs.fontWeight, style: pcs.fontStyle,
                 fill: pcs.fill, fill_opacity: parseFloat(pcs.fillOpacity || '1'), stroke: pcs.stroke,
                 element: pe === t ? null : (pe.id || pathOf(pe)), text_length_attr: pe.hasAttribute('textLength')});
    }
    let ctl = null; try { ctl = t.getComputedTextLength() * scaleOf(m); } catch (e) {}
    let bb = null; try { bb = boxOf(m, t.getBBox()); } catch (e) {}
    out.texts.push({ref: t.id || pathOf(t), id: t.id || null, path: pathOf(t), order: order.get(t), ancestors: ancestorsIds(t), data: dataOf(t),
                    text: (t.textContent || '').replace(/\s+/g, ' ').trim(), runs, bbox: bb, opacity: o, anchor: cs.textAnchor,
                    rotated: !!m && (Math.abs(m.b) > 1e-6 || Math.abs(m.c) > 1e-6), m: mat(m), computed_length_px: ctl,
                    text_length_attr: t.hasAttribute('textLength') || runs.some(r => r.text_length_attr), ...chains(t)});
  });

  // ---- shapes and strokes ----
  const TAGS = 'rect,circle,ellipse,line,polyline,polygon,path,image,use,foreignObject';
  svg.querySelectorAll(TAGS).forEach(el => {
    if (inDefs(el)) return;
    const tag = el.localName;
    const o = vis(el);
    const m = rel(el);
    if (!m) return;
    let b; try { b = el.getBBox(); } catch (e) { out.unsupported.push({kind: 'no-bbox', ref: el.id || pathOf(el), tag}); return; }
    const cs = getComputedStyle(el);
    const fillPainted = tag !== 'line' && cs.fill && cs.fill !== 'none' && parseFloat(cs.fillOpacity || '1') > 0.02 && !/rgba\(\s*[\d.]+,\s*[\d.]+,\s*[\d.]+,\s*0\s*\)/.test(cs.fill);
    const sw = parseFloat(cs.strokeWidth || '0');
    const strokePainted = cs.stroke && cs.stroke !== 'none' && sw > 0 && parseFloat(cs.strokeOpacity || '1') > 0.02;
    const sc = scaleOf(m);
    let closed = ['rect', 'circle', 'ellipse', 'polygon'].includes(tag);
    let subpaths = 1;
    if (tag === 'path') {
      const d = el.getAttribute('d') || '';
      closed = /[zZ]\s*$/.test(d.trim());
      subpaths = (d.match(/[mM]/g) || []).length;
    }
    const item = {ref: el.id || pathOf(el), id: el.id || null, path: pathOf(el), tag, order: order.get(el), ancestors: ancestorsIds(el), data: dataOf(el),
                  bbox: boxOf(m, b), opacity: o, m: mat(m), scale: sc,
                  fill: fillPainted ? cs.fill : null, fill_opacity: parseFloat(cs.fillOpacity || '1'),
                  stroke: strokePainted ? cs.stroke : null, stroke_px: strokePainted ? sw * sc : 0,
                  dashed: !!(cs.strokeDasharray && cs.strokeDasharray !== 'none'),
                  markers: {start: idRef(cs.markerStart), mid: idRef(cs.markerMid), end: idRef(cs.markerEnd)},
                  closed, subpaths, ...chains(el)};
    const rotated = Math.abs(m.b) > 1e-6 || Math.abs(m.c) > 1e-6;
    if (closed && (tag !== 'rect' || rotated) && el.getTotalLength) {
      let len = 0; try { len = el.getTotalLength(); } catch (e) { len = 0; }
      if (len > 0) { const n = 64; const ol = []; for (let i = 0; i < n; i++) { const p = el.getPointAtLength(len * i / n); ol.push(P(m, p.x, p.y)); } item.outline = ol; }
    }
    if (tag === 'image') item.href = el.getAttribute('href') || el.getAttribute('xlink:href');
    if (tag === 'use') item.href = el.getAttribute('href') || el.getAttribute('xlink:href');
    if (tag === 'foreignObject' || tag === 'use') out.unsupported.push({kind: tag, ref: item.ref});
    if (!closed && strokePainted && ['line', 'polyline', 'path'].includes(tag)) {
      let pts = [];
      if (tag === 'line') {
        pts = [P(m, el.x1.baseVal.value, el.y1.baseVal.value), P(m, el.x2.baseVal.value, el.y2.baseVal.value)];
      } else {
        let len = 0; try { len = el.getTotalLength(); } catch (e) { len = 0; }
        const n = Math.max(2, Math.min(240, Math.ceil(len / 3)));
        for (let i = 0; i <= n; i++) { const p = el.getPointAtLength(len * i / n); pts.push(P(m, p.x, p.y)); }
      }
      item.points = pts;
      if (tag === 'polyline' && el.points) { const v = []; for (let i = 0; i < el.points.numberOfItems; i++) { const p = el.points.getItem(i); v.push(P(m, p.x, p.y)); } item.vertices = v; }
    }
    out.shapes.push(item);
  });
  svg.querySelectorAll('g[id], svg[id], a[id]').forEach(g => {
    if (inDefs(g) || g === svg) return;
    const m = rel(g); if (!m) return;
    let b; try { b = g.getBBox(); } catch (e) { return; }
    if (!b || (b.width === 0 && b.height === 0)) return;
    out.groups.push({ref: g.id, id: g.id, path: pathOf(g), order: order.get(g), ancestors: ancestorsIds(g), data: dataOf(g), bbox: boxOf(m, b), opacity: vis(g)});
  });
  svg.querySelectorAll('svg').forEach(s => { if (s !== svg && !inDefs(s)) out.unsupported.push({kind: 'nested-svg', ref: s.id || pathOf(s)}); });
  svg.querySelectorAll('switch').forEach(s => { if (!inDefs(s)) out.unsupported.push({kind: 'switch', ref: s.id || pathOf(s)}); });

  // ---- fonts: which family of each stack the browser can actually use ----
  const ctx = document.createElement('canvas').getContext('2d');
  const GENERIC = new Set(['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui']);
  const sample = 'mmmmmmmmmmlliWWQ@#0123456789';
  const available = fam => {
    if (GENERIC.has(fam.toLowerCase())) return true;
    return ['monospace', 'serif'].some(base => { ctx.font = '72px ' + base; const w0 = ctx.measureText(sample).width; ctx.font = '72px "' + fam + '", ' + base; return Math.abs(ctx.measureText(sample).width - w0) > 0.01; });
  };
  stacks.forEach(stack => {
    const fams = stack.split(',').map(s => s.trim().replace(/^["']|["']$/g, '')).filter(Boolean);
    const checks = fams.map(f => ({family: f, available: available(f)}));
    const used = checks.find(c => c.available);
    out.fonts[stack] = {families: checks, resolved: used ? used.family : null};
  });
  return out;
}
"""

HTML_WRAPPER = (
    "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><base href=\"{base}\">"
    "<style>html,body{{margin:0;padding:0;background:#FFFFFF;overflow:hidden}}"
    "svg{{display:block;width:{w}px;height:{h}px}}</style></head><body>{svg}</body></html>"
)
_XML_DECL_RE = re.compile(r"^\s*(<\?xml[^>]*\?>\s*)?(<!DOCTYPE[^>]*>\s*)?", re.IGNORECASE)


def _svg_markup(svg: Path) -> str:
    text = svg.read_text(encoding="utf-8-sig")
    return _XML_DECL_RE.sub("", text, count=1)


class Browser:
    """One Chromium for many SVGs. Use as a context manager."""

    def __init__(self, canvas: tuple[float, float] = (1280.0, 720.0), device_scale: float = 1.0):
        self.canvas = canvas
        self.device_scale = device_scale
        self._pw = None
        self._browser = None
        self._context = None
        self._tmp = None
        self.chromium_version: Optional[str] = None

    def __enter__(self) -> "Browser":
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(channel=os.environ.get("PPT_MASTER_BROWSER_CHANNEL") or None)
        self.chromium_version = self._browser.version
        self._context = self._browser.new_context(
            viewport={"width": int(self.canvas[0]), "height": int(self.canvas[1])},
            device_scale_factor=self.device_scale,
        )
        self._tmp = tempfile.TemporaryDirectory(prefix="exp_svg_inspect_")
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._context is not None:
                self._context.close()
            if self._browser is not None:
                self._browser.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            if self._tmp is not None:
                self._tmp.cleanup()

    def measure(self, svg: Path, screenshot: Optional[Path] = None) -> dict:
        """Geometry of one SVG in slide pixels; optionally save the rendered PNG."""
        svg = Path(svg).resolve()
        base = svg.parent.as_uri() + "/"
        html = HTML_WRAPPER.format(base=base, w=int(self.canvas[0]), h=int(self.canvas[1]), svg=_svg_markup(svg))
        wrapper = Path(self._tmp.name) / f"page_{abs(hash(str(svg)))}.html"
        wrapper.write_text(html, encoding="utf-8")
        page = self._context.new_page()
        console: list[str] = []
        page.on("console", lambda msg: console.append(f"{msg.type}: {msg.text}"[:300]))
        failed: list[str] = []
        page.on("requestfailed", lambda req: failed.append(req.url[:300]))
        try:
            page.goto(wrapper.as_uri(), wait_until="load")
            geometry = page.evaluate(EXTRACT_JS, {"canvasW": self.canvas[0], "canvasH": self.canvas[1]})
            if screenshot is not None:
                Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot), type="png", full_page=False)
        finally:
            page.close()
        geometry["browser"] = {"engine": "chromium", "version": self.chromium_version, "device_scale": self.device_scale,
                               "console": console[:20], "failed_requests": failed[:20]}
        return geometry


def measure_many(svgs: list[Path], canvas: tuple[float, float] = (1280.0, 720.0)) -> Iterator[tuple[Path, dict]]:
    with Browser(canvas) as browser:
        for svg in svgs:
            yield svg, browser.measure(svg)
