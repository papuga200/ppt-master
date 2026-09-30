#!/usr/bin/env python3
"""
PPT Master - exp_svg inspection: deterministic synthetic validation cases

Writes small SVG slides with known, deliberately planted defects, each with its inspection
request, independent checklist and ground truth (expected.json). Used to validate
inspect_svg.py without model calls and by the offline tests.

Cases:
    S00 clean timeline (control)          S08 transforms and nested groups (+ one scaled-down text, one wrong mapping)
    S01 tiny text                         S09 arrowhead direction (marker-start orient=auto, fixed-angle marker)
    S02 clipped / overflowing text        S10 legend swatch contradicts its meaning
    S03 off-canvas content                S11 bar names kept in the left rail, not at the bars
    S04 colliding labels                  S12 milestone meaning restated in a strip; truncated milestone name
    S05 connector ends on the wrong box   S13 connector lands mid-way on another arrow (T-junction)
    S06 missing milestone label           S14 arrowhead pointing at empty space
    S07 mis-dated bar                     S15 unsupported geometry (filter, foreignObject): unverified, not failed
    S16 clean architecture (control)      S17 decision gate drawn as a vertical rule, named at its top (control)
    S18 the same gate named in a strip far from its rule

Usage:
    python3 synthetic.py --out DIR

Dependencies:
    None (only uses standard library)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

W, H = 1280, 720
X0, PPW = 300.0, 35.0          # week 1 starts at x=300, 35 px per week, inclusive end weeks
LANE_Y0, LANE_H = 170.0, 64.0
FONT = "Segoe UI, Arial, sans-serif"

LANES = [("L1", "Discovery and mobilisation"), ("L2", "Data platform build"), ("L3", "Reporting products"), ("L4", "Testing and rollout")]
TASKS = [  # id, lane, name, start, end, sub-row
    ("T1", "L1", "Charter and plan", 1, 3, 0), ("T2", "L1", "Source access", 3, 6, 1),
    ("T3", "L2", "Ingestion pipelines", 4, 12, 0), ("T4", "L2", "Data model", 8, 16, 1),
    ("T5", "L3", "Dashboards", 17, 21, 0), ("T6", "L3", "Report catalogue", 14, 19, 1),
    ("T7", "L4", "User testing", 20, 23, 0), ("T8", "L4", "Rollout waves", 22, 26, 1),
]
MILESTONES = [("M1", "Pilot start", 10, "tri"), ("M2", "Go-live", 24, "tri")]
GATES = [("G1", "Gate 1", 16, "decides rollout")]


def xs(week: float) -> float:
    return X0 + (week - 1) * PPW


def xe(week: float) -> float:
    return X0 + week * PPW


def bar_rect(task) -> tuple[float, float, float, float]:
    _, lane, _, s, e, sub = task
    li = [lid for lid, _ in LANES].index(lane)
    y = LANE_Y0 + li * LANE_H + 8 + sub * 28
    return xs(s), y, xe(e) - xs(s), 22.0


def _text_width(text: str, px: float) -> float:
    return len(text) * px * 0.56


def svg_open() -> list[str]:
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="{FONT}" lang="en-GB" data-pptx-page-role="content">',
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
            '<path d="M0 0 L10 5 L0 10 Z" fill="#333333"/></marker></defs>',
            f'<rect id="bg" x="0" y="0" width="{W}" height="{H}" fill="#FFFFFF"/>']


def timeline_svg(*, tiny: bool = False, clip: bool = False, offcanvas: bool = False, collide: bool = False, drop_label: Optional[str] = None,
                 misdate: Optional[tuple] = None, rail_labels: bool = False, strip_meaning: bool = False, truncate: Optional[str] = None,
                 transformed: bool = False, legend_wrong: bool = False, gate_rule: bool = False, gate_label_far: bool = False) -> str:
    out = svg_open()
    out.append('<text id="title" x="54" y="80" font-size="28" font-weight="600" fill="#1F1F1F">Twenty-six weeks from discovery to rollout</text>')
    # ruler
    for w in range(1, 27, 2):
        out.append(f'<text id="tick-{w}" x="{xs(w):.1f}" y="156" font-size="14" text-anchor="middle" fill="#5F6368">W{w}</text>')
    out.append(f'<line id="ruler" x1="{X0}" y1="162" x2="{xe(26)}" y2="162" stroke="#8C9096" stroke-width="1" data-role="axis"/>')
    # lanes
    for i, (lid, name) in enumerate(LANES):
        y = LANE_Y0 + i * LANE_H
        fill = "#F4F5F7" if i % 2 == 0 else "#FFFFFF"
        out.append(f'<rect id="lane-bg-{lid}" x="54" y="{y}" width="{xe(26) - 54:.1f}" height="{LANE_H}" fill="{fill}"/>')
        name_text = name
        out.append(f'<text id="lane-{lid}" x="62" y="{y + 26}" font-size="16" font-weight="600" fill="#1F1F1F">{name_text}</text>')
        if rail_labels:
            subs = " · ".join(t[2] for t in TASKS if t[1] == lid)
            out.append(f'<text id="rail-{lid}" x="62" y="{y + 48}" font-size="14" fill="#5F6368">{subs}</text>')
    # bars and labels
    bars = []
    for task in TASKS:
        tid, lane, name, s, e, sub = task
        if misdate and misdate[0] == tid:
            task = (tid, lane, name, misdate[1], misdate[2], sub)
        x, y, w, h = bar_rect(task)
        bars.append(f'<rect id="bar-{tid}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#4F6D8A"/>')
        if rail_labels:
            continue
        label = name
        px = 11.0 if (tiny and tid == "T3") else 14.0
        tw = _text_width(label, px)
        if clip and tid == "T4":
            bars.append(f'<clipPath id="clip-T4"><rect x="{x:.1f}" y="{y:.1f}" width="60" height="{h:.1f}"/></clipPath>')
            bars.append(f'<text id="lbl-{tid}" x="{x + 6:.1f}" y="{y + 16:.1f}" font-size="{px}" fill="#FFFFFF" clip-path="url(#clip-T4)">{label}</text>')
        elif clip and tid == "T6":
            # a label written inside its bar but longer than the bar
            long = "Report catalogue and certification of every metric"
            bars.append(f'<text id="lbl-{tid}" x="{x + 6:.1f}" y="{y + 16:.1f}" font-size="{px}" fill="#FFFFFF">{long}</text>')
        elif offcanvas and tid == "T8":
            bars.append(f'<text id="lbl-{tid}" x="{x + w + 6:.1f}" y="{y + 16:.1f}" font-size="{px}" fill="#1F1F1F">{label} to every unit</text>')
        elif tw + 12 <= w:
            bars.append(f'<text id="lbl-{tid}" x="{x + 6:.1f}" y="{y + 16:.1f}" font-size="{px}" fill="#FFFFFF">{label}</text>')
        else:
            bars.append(f'<text id="lbl-{tid}" x="{x + w + 6:.1f}" y="{y + 16:.1f}" font-size="{px}" fill="#1F1F1F">{label}</text>')
    if collide:
        # a second label written over T1's label
        x, y, w, h = bar_rect(TASKS[0])
        bars.append(f'<text id="lbl-extra" x="{x + w + 20:.1f}" y="{y + 18:.1f}" font-size="14" fill="#B4162E">Steering committee formed</text>')
    if transformed:
        # the same bars under nested transforms: coordinates written in a local frame
        inner = []
        for b in bars:
            inner.append(_to_local(b))
        out.append('<g id="bars-outer" transform="translate(300 170)"><g id="bars-inner" transform="scale(0.5)">')
        out.extend(inner)
        out.append('</g></g>')
        out.append('<g id="scaled-note" transform="translate(900 610) scale(0.5)"><text id="note-small" x="0" y="0" font-size="24" fill="#5F6368">Scaled note: 12 px on the slide</text></g>')
        out.append('<g id="rot" transform="translate(40 420) rotate(-90)"><text id="rot-label" x="0" y="0" font-size="16" fill="#5F6368">Workstreams</text></g>')
    else:
        out.extend(bars)
    # dependency T4 -> T5
    x4, y4, w4, h4 = bar_rect(TASKS[3])
    x5, y5, w5, h5 = bar_rect(TASKS[4])
    out.append(f'<path id="dep-T4-T5" d="M{x4 + w4:.1f} {y4 + h4 / 2:.1f} H{x4 + w4 + 14:.1f} V{y5 - 2:.1f}" fill="none" stroke="#333333" stroke-width="1.5" marker-end="url(#arrow)"/>')
    # milestones and gate
    for mid, name, date, _ in MILESTONES:
        x = xe(date)
        out.append(f'<path id="mk-{mid}" d="M{x - 8:.1f} 460 L{x:.1f} 446 L{x + 8:.1f} 460 Z" fill="#2B2F36"/>')
        if drop_label == mid:
            continue
        label = name
        if truncate == mid:
            label = name.split()[0]
        out.append(f'<text id="ml-{mid}" x="{x:.1f}" y="482" font-size="14" text-anchor="middle" fill="#1F1F1F">W{date} {label}</text>')
    for gid, name, date, meaning in GATES:
        x = xe(date)
        if gate_rule:
            # the decision drawn as a dashed vertical rule through the lanes, broken around one bar label, named at the top
            out.append(f'<line id="gr-{gid}-a" x1="{x:.1f}" y1="162" x2="{x:.1f}" y2="330" stroke="#B4162E" stroke-width="1.5" stroke-dasharray="5 3"/>')
            out.append(f'<line id="gr-{gid}-b" x1="{x:.1f}" y1="360" x2="{x:.1f}" y2="440" stroke="#B4162E" stroke-width="1.5" stroke-dasharray="5 3"/>')
            if gate_label_far:
                out.append(f'<text id="ml-{gid}" x="54" y="600" font-size="14" fill="#B4162E">W{date} {name}: {meaning}</text>')
            else:
                out.append(f'<text id="ml-{gid}" x="{x + 4:.1f}" y="134" font-size="14" fill="#B4162E">W{date} {name}: {meaning}</text>')
            continue
        out.append(f'<path id="mk-{gid}" d="M{x:.1f} 444 L{x + 9:.1f} 453 L{x:.1f} 462 L{x - 9:.1f} 453 Z" fill="#B4162E"/>')
        out.append(f'<text id="ml-{gid}" x="{x:.1f}" y="482" font-size="14" text-anchor="middle" fill="#B4162E">W{date} {name}</text>')
        if strip_meaning:
            out.append(f'<text id="strip-{gid}" x="54" y="600" font-size="14" fill="#1F1F1F">{name}: {meaning}; not met: pilot extended</text>')
        else:
            out.append(f'<text id="mm-{gid}" x="{x:.1f}" y="500" font-size="14" text-anchor="middle" fill="#1F1F1F">{meaning}</text>')
    # legend
    red = "#8C9096" if legend_wrong else "#B4162E"
    out.append(f'<path id="lg-gate-swatch" d="M60 650 L66 656 L60 662 L54 656 Z" fill="{red}"/>')
    out.append('<text id="lg-gate" x="72" y="661" font-size="14" fill="#5F6368">crimson diamond = decision gate</text>')
    out.append('<text id="source" x="54" y="700" font-size="14" fill="#5F6368">Source: synthetic validation case.</text>')
    out.append("</svg>")
    return "\n".join(out)


def _to_local(element: str) -> str:
    """Rewrite one absolute rect/text element into the frame translate(300 170) scale(0.5)."""
    import re

    def fx(v: str) -> str:
        return f"{(float(v) - 300) * 2:.1f}"

    def fy(v: str) -> str:
        return f"{(float(v) - 170) * 2:.1f}"

    def f2(v: str) -> str:
        return f"{float(v) * 2:.1f}"

    element = re.sub(r' x="([\d.]+)"', lambda m: f' x="{fx(m.group(1))}"', element)
    element = re.sub(r' y="([\d.]+)"', lambda m: f' y="{fy(m.group(1))}"', element)
    element = re.sub(r' width="([\d.]+)"', lambda m: f' width="{f2(m.group(1))}"', element)
    element = re.sub(r' height="([\d.]+)"', lambda m: f' height="{f2(m.group(1))}"', element)
    element = re.sub(r' font-size="([\d.]+)"', lambda m: f' font-size="{f2(m.group(1))}"', element)
    return element


def timeline_checklist() -> dict:
    items = [{"id": lid, "kind": "lane", "text": name, "role": "body"} for lid, name in LANES]
    for tid, lane, name, s, e, _ in TASKS:
        items.append({"id": tid, "kind": "task", "lane": lane, "text": name, "start": s, "end": e, "role": "label"})
    for mid, name, date, _ in MILESTONES:
        items.append({"id": mid, "kind": "milestone", "text": f"W{date} {name}", "date": date, "role": "label"})
    for gid, name, date, meaning in GATES:
        items.append({"id": gid, "kind": "gate", "text": f"W{date} {name}", "date": date, "meaning": meaning, "role": "label"})
    items.append({"id": "D1", "kind": "dependency", "from": "T4", "to": "T5", "directed": True})
    items.append({"id": "K1", "kind": "legend", "text": "crimson diamond = decision gate", "symbol_color": "#B4162E", "applies_to": ["G1"]})
    return {"schema": "exp_svg.checklist/v1", "fixture": "synthetic-timeline", "match_threshold": 0.8, "items": items}


def timeline_request(**extra) -> dict:
    req = {"canvas": [W, H], "type_floors_px": {"label": 13.333, "body": 16.0}, "checklist": "checklist.json",
           "roles": {"default": "label", "ids": {"title": "body"}},
           "timeline": {"scale": {"unit": "week", "origin": 1, "origin_x": X0, "px_per_unit": PPW, "end_convention": "inclusive",
                                  "milestone_anchor": "end", "tolerance_weeks": 0.5},
                        "marker_band": [440, 466], "ticks": {"pattern": r"W(\d+)", "anchor": "start", "band": [140, 160]}}}
    req.update(extra)
    return req


NODES = [  # id, label, x, y, w, h
    ("N1", "Customer portal", 120, 200, 200, 64), ("N2", "API gateway", 460, 200, 200, 64),
    ("N3", "Order service", 800, 140, 200, 64), ("N4", "Billing service", 800, 300, 200, 64),
    ("N5", "Data warehouse", 800, 470, 200, 64), ("N6", "Approval desk", 460, 470, 200, 64),
]
EDGES = [("E1", "N1", "N2"), ("E2", "N2", "N3"), ("E3", "N2", "N4"), ("E4", "N4", "N5"), ("E5", "N6", "N4")]


def _node(nid: str):
    return next(n for n in NODES if n[0] == nid)


def _edge_points(a: str, b: str) -> tuple[tuple[float, float], tuple[float, float]]:
    _, _, ax, ay, aw, ah = _node(a)
    _, _, bx, by, bw, bh = _node(b)
    acx, acy, bcx, bcy = ax + aw / 2, ay + ah / 2, bx + bw / 2, by + bh / 2
    if abs(bcx - acx) >= abs(bcy - acy) * 1.2:
        start = (ax + aw, acy) if bcx > acx else (ax, acy)
        end = (bx - 2, bcy) if bcx > acx else (bx + bw + 2, bcy)
    else:
        start = (acx, ay + ah) if bcy > acy else (acx, ay)
        end = (bcx, by - 2) if bcy > acy else (bcx, by + bh + 2)
    return start, end


def architecture_svg(*, wrong_target: bool = False, t_junction: bool = False, dangling: bool = False, legend_wrong: bool = False,
                     unsupported: bool = False, marker_bugs: bool = False) -> str:
    out = svg_open()
    shadow = '<filter id="shadow"><feDropShadow dx="2" dy="2" stdDeviation="2" flood-opacity="0.3"/></filter>' if unsupported else ""
    out.append('<defs><marker id="arrow-fixed" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="0">'
               f'<path d="M0 0 L10 5 L0 10 Z" fill="#333333"/></marker>{shadow}</defs>')
    out.append('<text id="title" x="54" y="80" font-size="28" font-weight="600" fill="#1F1F1F">Orders flow through one gateway inside region A</text>')
    out.append('<rect id="zone-A" x="420" y="120" width="620" height="440" fill="none" stroke="#8C9096" stroke-dasharray="6 4"/>')
    out.append('<text id="zone-A-label" x="430" y="142" font-size="14" fill="#5F6368">Cloud region A</text>')
    for nid, label, x, y, w, h in NODES:
        fill = "#B4162E" if nid == "N6" else "#FFFFFF"
        tfill = "#FFFFFF" if nid == "N6" else "#1F1F1F"
        filt = ' filter="url(#shadow)"' if (unsupported and nid == "N1") else ""
        out.append(f'<rect id="node-{nid}" x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#2B2F36" stroke-width="1.5"{filt}/>')
        out.append(f'<text id="label-{nid}" x="{x + w / 2}" y="{y + h / 2 + 6}" font-size="16" text-anchor="middle" fill="{tfill}">{label}</text>')
    for eid, a, b in EDGES:
        if wrong_target and eid == "E2":
            b = "N4"
        (sx, sy), (ex, ey) = _edge_points(a, b)
        if t_junction and eid == "E4":
            # the line from the billing service stops on the middle of the approval-desk->billing arrow
            (s5x, s5y), (e5x, e5y) = _edge_points("N6", "N4")
            ex, ey = (s5x + e5x) / 2, (s5y + e5y) / 2
            out.append(f'<path id="edge-{eid}" d="M900 364 V{ey:.1f} H{ex:.1f}" fill="none" stroke="#333333" stroke-width="1.5"/>')
            continue
        if marker_bugs and eid == "E5":
            out.append(f'<line id="edge-{eid}" x1="{ex}" y1="{ey}" x2="{sx}" y2="{sy}" stroke="#333333" stroke-width="1.5" marker-start="url(#arrow)"/>')
            continue
        if marker_bugs and eid == "E4":
            out.append(f'<line id="edge-{eid}" x1="{sx}" y1="{sy}" x2="{ex}" y2="{ey}" stroke="#333333" stroke-width="1.5" marker-end="url(#arrow-fixed)"/>')
            continue
        out.append(f'<line id="edge-{eid}" x1="{sx}" y1="{sy}" x2="{ex}" y2="{ey}" stroke="#333333" stroke-width="1.5" marker-end="url(#arrow)"/>')
    if dangling:
        out.append('<line id="edge-stray" x1="220" y1="264" x2="220" y2="380" stroke="#333333" stroke-width="1.5" marker-end="url(#arrow)"/>')
    if unsupported:
        out.append('<foreignObject id="fo-note" x="120" y="600" width="260" height="40"><div xmlns="http://www.w3.org/1999/xhtml" style="font-size:16px">HTML note</div></foreignObject>')
    swatch = "#8C9096" if legend_wrong else "#B4162E"
    out.append(f'<rect id="lg-swatch" x="54" y="652" width="12" height="12" fill="{swatch}"/>')
    out.append('<text id="lg-text" x="72" y="663" font-size="14" fill="#5F6368">crimson = human approval</text>')
    out.append('<line id="lg-line" x1="340" y1="658" x2="370" y2="658" stroke="#333333" stroke-width="1.5"/>')
    out.append('<text id="lg-line-text" x="378" y="663" font-size="14" fill="#5F6368">solid arrow = runtime call</text>')
    out.append("</svg>")
    return "\n".join(out)


def architecture_checklist() -> dict:
    items = [{"id": "Z1", "kind": "zone", "text": "Cloud region A", "element": "zone-A", "role": "label"}]
    for nid, label, *_ in NODES:
        item = {"id": nid, "kind": "node", "text": label, "role": "body"}
        if nid != "N1":
            item["inside"] = "Z1"
        items.append(item)
    for eid, a, b in EDGES:
        items.append({"id": eid, "kind": "relationship", "from": a, "to": b, "directed": True, "style": "solid"})
    items.append({"id": "K1", "kind": "legend", "text": "crimson = human approval", "symbol_color": "#B4162E", "applies_to": ["N6"]})
    return {"schema": "exp_svg.checklist/v1", "fixture": "synthetic-architecture", "match_threshold": 0.8, "items": items}


def architecture_request() -> dict:
    return {"canvas": [W, H], "checklist": "checklist.json", "roles": {"default": "label", "ids": {"title": "body"}}}


def cases() -> dict[str, dict]:
    tl_req = timeline_request()
    arch_req = architecture_request()
    tlc, arc = timeline_checklist(), architecture_checklist()
    D = lambda check, *targets, note="": {"check": check, "targets": list(targets), "note": note}  # noqa: E731
    mapping = {"T1": {"bar": "bar-T1", "label": "lbl-T1"}, "T2": {"bar": "bar-T2", "label": "lbl-T3"}, "M1": {"marker": "mk-M1", "label": "ml-M1"}}
    return {
        "S00_clean_timeline": {"svg": timeline_svg(), "request": tl_req, "checklist": tlc, "expected": []},
        "S01_tiny_text": {"svg": timeline_svg(tiny=True), "request": tl_req, "checklist": tlc,
                          "expected": [D("type_floor", "lbl-T3", note="11 px label")]},
        "S02_clipped_text": {"svg": timeline_svg(clip=True), "request": tl_req, "checklist": tlc,
                             "expected": [D("text_fit", "lbl-T4", note="clip-path cuts the label"), D("text_fit", "lbl-T6", note="label longer than its bar")]},
        "S03_off_canvas": {"svg": timeline_svg(offcanvas=True), "request": tl_req, "checklist": tlc,
                           "expected": [D("off_canvas", "lbl-T8", note="label runs past the right edge")]},
        "S04_colliding_labels": {"svg": timeline_svg(collide=True), "request": tl_req, "checklist": tlc,
                                 "expected": [D("overlap", "lbl-extra", "lbl-T1", note="two labels collide")]},
        "S05_wrong_target": {"svg": architecture_svg(wrong_target=True), "request": arch_req, "checklist": arc,
                             "expected": [D("connectors", "E2", note="gateway->order drawn to billing")]},
        "S06_missing_milestone_label": {"svg": timeline_svg(drop_label="M2"), "request": tl_req, "checklist": tlc,
                                        "expected": [D("semantic", "M2", note="milestone label missing")]},
        "S07_misdated_bar": {"svg": timeline_svg(misdate=("T3", 6, 14)), "request": tl_req, "checklist": tlc,
                             "expected": [D("timeline", "T3", note="bar drawn at W6-W14 instead of W4-W12")]},
        "S08_transforms": {"svg": timeline_svg(transformed=True), "request": timeline_request(mapping=mapping), "checklist": tlc,
                           "expected": [D("type_floor", "note-small", note="24 px under scale(0.5) = 12 px"),
                                        D("semantic", "T2", note="mapping names the wrong label element")]},
        "S09_marker_direction": {"svg": architecture_svg(marker_bugs=True), "request": arch_req, "checklist": arc,
                                 "expected": [D("markers", "edge-E5", note="marker-start with orient=auto points inward"),
                                              D("markers", "edge-E4", note="fixed orient=0 marker on a downward line")]},
        "S10_legend_mismatch": {"svg": architecture_svg(legend_wrong=True), "request": arch_req, "checklist": arc,
                                "expected": [D("semantic", "K1", note="grey swatch labelled crimson")]},
        "S11_rail_labels": {"svg": timeline_svg(rail_labels=True), "request": tl_req, "checklist": tlc,
                            "expected": [D("semantic", tid, note="bar name in the rail") for tid, *_ in TASKS]},
        "S12_strip_meaning": {"svg": timeline_svg(strip_meaning=True, truncate="M1"), "request": tl_req, "checklist": tlc,
                              "expected": [D("semantic", "G1", note="gate meaning in the bottom strip"), D("semantic", "M1", note="milestone name truncated")]},
        "S13_t_junction": {"svg": architecture_svg(t_junction=True), "request": arch_req, "checklist": arc,
                           "expected": [D("connectors", "edge-E4", note="lands mid-way on the approval->billing arrow"),
                                        D("connectors", "E4", note="billing->warehouse not drawn to the warehouse")]},
        "S14_dangling_arrow": {"svg": architecture_svg(dangling=True), "request": arch_req, "checklist": arc,
                               "expected": [D("connectors", "edge-stray", note="arrowhead points at empty space")]},
        "S15_unsupported": {"svg": architecture_svg(unsupported=True), "request": arch_req, "checklist": arc, "expected": [],
                            "expected_unverified_or_limits": ["filter", "foreignObject"]},
        "S16_clean_architecture": {"svg": architecture_svg(), "request": arch_req, "checklist": arc, "expected": []},
        "S17_clean_gate_rule": {"svg": timeline_svg(gate_rule=True), "request": tl_req, "checklist": tlc, "expected": []},
        "S18_gate_rule_label_far": {"svg": timeline_svg(gate_rule=True, gate_label_far=True), "request": tl_req, "checklist": tlc,
                                    "expected": [D("semantic", "G1", note="gate drawn as a rule, its name in a strip far from it")]},
    }


def write_cases(out: Path) -> list[Path]:
    written = []
    for name, case in cases().items():
        folder = out / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "slide.svg").write_text(case["svg"] + "\n", encoding="utf-8")
        (folder / "request.json").write_text(json.dumps(case["request"], indent=1) + "\n", encoding="utf-8")
        (folder / "checklist.json").write_text(json.dumps(case["checklist"], indent=1) + "\n", encoding="utf-8")
        exp = {"case": name, "expected_defects": case["expected"], "expected_unverified_or_limits": case.get("expected_unverified_or_limits", [])}
        (folder / "expected.json").write_text(json.dumps(exp, indent=1) + "\n", encoding="utf-8")
        written.append(folder)
    return written


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Write the synthetic inspect_svg validation cases.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    for folder in write_cases(args.out):
        print(folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
