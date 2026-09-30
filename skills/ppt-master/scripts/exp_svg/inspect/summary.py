#!/usr/bin/env python3
"""
PPT Master - exp_svg inspection: reviewer summary

Renders a concise, budgeted text view of a full inspect_svg report for a reviewer or an
author: coverage counts, unresolved (unverified) checks and the highest-severity findings with
their check ids and element ids. The full report stays on disk. A blocker is never dropped to
fit the budget: when the blockers do not fit, an explicit overflow index lists every blocker id
that was not shown in full, and names the command for a targeted view. Token counts are an
estimate (characters / 3.6), not a tokenizer measurement.

Usage:
    Imported by inspect_svg.py (``--summary``); not a command.

Dependencies:
    None (only uses standard library)
"""

from __future__ import annotations

import collections
import math
import re
import sys
from typing import Optional

if __name__ == "__main__" and any(arg in {"-h", "--help", "help"} for arg in sys.argv[1:]):
    print(__doc__)
    raise SystemExit(0)

CHARS_PER_TOKEN = 3.6
SEVERITIES = ("blocker", "major", "minor", "info")
FAMILY_ORDER = {"semantic": 0, "connectors": 1, "timeline": 2, "text_fit": 3, "overlap": 4, "off_canvas": 5, "markers": 6,
                "resources": 7, "unsupported": 8, "type_floor": 9}
COLLAPSE_AT = 6
COLLAPSIBLE = {"type_floor", "off_canvas", "overlap", "text_fit"}  # measurement families; meaning findings stay one per line


def _num(check_id: str) -> int:
    digits = check_id[len(check_id.rstrip("0123456789")):]
    return int(digits or 0)


def _groupby(recs: list[dict]) -> list[tuple[str, list[dict]]]:
    out: list[tuple[str, list[dict]]] = []
    for rec in recs:
        if out and out[-1][0] == rec["check"]:
            out[-1][1].append(rec)
        else:
            out.append((rec["check"], [rec]))
    return out


def _collapsed_line(check: str, group: list[dict]) -> str:
    """One line for many findings of one family; every id is listed."""
    sizes = [r["measured"] for r in group if isinstance(r.get("measured"), (int, float))]
    span = f"; measured {min(sizes):.2f}-{max(sizes):.2f} {group[0].get('units', '').split(' ')[0]}" if sizes else ""
    msgs = collections.Counter(re.sub(r"[-+]?\d+(\.\d+)?", "#", r["message"]) for r in group).most_common(2)
    pattern = " / ".join(_short(m, 90) for m, _ in msgs)
    return f"  [{check} x{len(group)}] {pattern}{span} | ids {_index([r['check_id'] for r in group])}"


def estimate_tokens(text: str) -> int:
    return int(math.ceil(len(text) / CHARS_PER_TOKEN))


def _short(value, n: int = 70) -> str:
    text = str(value)
    return text if len(text) <= n else text[: n - 1] + "…"


def finding_line(rec: dict) -> str:
    targets = ", ".join(_short(t, 48) for t in rec.get("targets", [])[:3])
    more = len(rec.get("targets", [])) - 3
    if more > 0:
        targets += f" +{more}"
    cert = rec.get("certainty", "")
    cert = "" if cert == "measured" else f" ({_short(cert, 50)})"
    return f"[{rec['check_id']}] {rec['check']} | {targets} | {_short(rec['message'], 170)}{cert}"


def _index(ids: list[str]) -> str:
    fam: dict[str, list[str]] = collections.OrderedDict()
    for cid in ids:
        prefix = cid.rstrip("0123456789")
        fam.setdefault(prefix, []).append(cid[len(prefix):])
    return "; ".join(f"{p}: " + ",".join(nums) for p, nums in fam.items())


def render(report: dict, max_tokens: int = 2000, report_path: Optional[str] = None) -> str:
    budget = max_tokens * CHARS_PER_TOKEN
    recs = report.get("checks", [])
    failed = [r for r in recs if r["status"] == "failed"]
    by_sev = {s: [r for r in failed if r.get("severity") == s] for s in SEVERITIES}
    unverified = [r for r in recs if r["status"] == "unverified"]
    art = report.get("artifact", {})
    cov = report.get("coverage", {})
    head = [f"INSPECTION SUMMARY (inspect_svg {report.get('version', '?')}; full report: {report_path or 'on disk'})",
            f"artifact sha256 {art.get('sha256', '?')} | status {report.get('status')} | units: slide px (1280x720; 1 px = 0.75 pt)",
            f"failed: {len(by_sev['blocker'])} blocker, {len(by_sev['major'])} major, {len(by_sev['minor'])} minor | unverified: {len(unverified)}",
            "coverage (checked = passed + failed; unverified and waived listed separately):"]
    for check, c in (cov.get("by_check") or {}).items():
        head.append(f"  {check}: {c['passed'] + c['failed']} checked ({c['passed']} pass, {c['failed']} fail), {c['unverified']} unverified, {c['waived']} waived")
    cl = cov.get("checklist")
    if cl:
        head.append(f"  checklist: {cl['items']} items, {cl['present']} present, {cl['partial']} partial/truncated, {cl['missing']} missing")
    el = cov.get("elements") or {}
    if el:
        head.append(f"  measured: {el.get('texts')} texts / {el.get('text_lines')} lines, {el.get('shapes')} shapes, {el.get('connectors')} open strokes; "
                    f"unsupported: {el.get('unsupported_count', 0)}")
    tail = ["NOTE: a clean overlap check does not prove relationships; 'passed' means one measurement is within tolerance, "
            "'unverified' means unknown (not pass, not fail)."]
    lim = report.get("limits") or {}
    dyn = lim.get("present_on_this_slide") or []
    tail.append("NOT MEASURED: " + "; ".join(m["property"] for m in lim.get("never_measured", [])) + (" | on this slide: " + "; ".join(_short(d, 80) for d in dyn[:6]) if dyn else ""))
    used = sum(len(x) + 1 for x in head + tail)
    body: list[str] = []

    def room(text: str) -> bool:
        return used + sum(len(x) + 1 for x in body) + len(text) + 1 <= budget

    # blockers: meaning before measurement; a family with many identical findings becomes one line
    # that still names every id; what does not fit goes to an explicit overflow index, never dropped
    blockers = sorted(by_sev["blocker"], key=lambda r: (FAMILY_ORDER.get(r["check"], 99), _num(r["check_id"])))
    body.append(f"BLOCKERS ({len(blockers)}):" if blockers else "BLOCKERS: none")
    units: list[tuple[str, list[dict]]] = []
    for check, group in _groupby(blockers):
        if len(group) > COLLAPSE_AT and check in COLLAPSIBLE:
            units.append((_collapsed_line(check, group), group))
        else:
            units.extend(("  " + finding_line(rec), [rec]) for rec in group)
    shown: list[dict] = []
    for i, (line, recs) in enumerate(units):
        rest_ids = [r["check_id"] for _, rs in units[i:] for r in rs]
        reserve = len(_index(rest_ids)) + 200 if i + 1 < len(units) else 0
        if used + sum(len(x) + 1 for x in body) + len(line) + reserve > budget:
            break
        body.append(line)
        shown.extend(recs)
    if len(shown) < len(blockers):
        shown_ids = {r["check_id"] for r in shown}
        rest = [r["check_id"] for r in blockers if r["check_id"] not in shown_ids]
        idx = "  OVERFLOW INDEX: " + f"{len(rest)} more blockers not shown in full (ids: {_index(rest)}). "
        idx += "Targeted view: inspect_svg.py --summary <report> --only blocker --offset " + str(len(shown))
        if not room(idx):
            fam = collections.Counter(c.rstrip("0123456789") for c in rest)
            idx = ("  OVERFLOW INDEX: " + f"{len(rest)} more blockers not shown ({', '.join(f'{k}: {v}' for k, v in fam.items())}); "
                   "ids too many for this budget - targeted view: inspect_svg.py --summary <report> --only blocker --offset " + str(len(shown)))
        body.append(idx)
    for sev in ("major",):
        recs_s = by_sev[sev]
        if not recs_s:
            continue
        body.append(f"{sev.upper()} ({len(recs_s)}):")
        n = 0
        for rec in recs_s:
            line = "  " + finding_line(rec)
            if not room(line + " " * 160):
                break
            body.append(line)
            n += 1
        if n < len(recs_s):
            rest = [r["check_id"] for r in recs_s[n:]]
            line = f"  ... {len(rest)} more {sev} (ids: {_index(rest)})"
            body.append(line if room(line) else f"  ... {len(rest)} more {sev} (see report; --only {sev})")
    if unverified:
        groups = collections.OrderedDict()
        for rec in unverified:
            groups.setdefault(rec.get("reason", "?"), []).append(rec)
        body.append(f"UNVERIFIED ({len(unverified)}), by reason:")
        for reason, rs in groups.items():
            ids = ", ".join(f"{r['check_id']}:{_short((r.get('targets') or ['-'])[0], 36)}" for r in rs[:6])
            line = f"  - {_short(reason, 110)} x{len(rs)}: {ids}" + (" …" if len(rs) > 6 else "")
            if not room(line):
                body.append(f"  - {len(unverified)} unverified in total; remaining reasons in the report (--only unverified)")
                break
            body.append(line)
    if by_sev["minor"]:
        body.append(f"MINOR: {len(by_sev['minor'])} (flagged; ids {_short(_index([r['check_id'] for r in by_sev['minor']]), 300)})")
    return "\n".join(head + body + tail) + "\n"


def targeted(report: dict, only: str, offset: int = 0, limit: int = 60, family: Optional[str] = None) -> str:
    recs = report.get("checks", [])
    if only == "unverified":
        sel = [r for r in recs if r["status"] == "unverified"]
    elif only == "failed":
        sel = [r for r in recs if r["status"] == "failed"]
    else:
        sel = [r for r in recs if r["status"] == "failed" and r.get("severity") == only]
    if family:
        sel = [r for r in sel if r["check"] == family or r["check_id"].startswith(family)]
    sel.sort(key=lambda r: (FAMILY_ORDER.get(r["check"], 99), _num(r["check_id"])))
    out = [f"{only} findings {offset + 1}..{min(len(sel), offset + limit)} of {len(sel)} (artifact {report.get('artifact', {}).get('sha256', '?')[:16]})"]
    for rec in sel[offset: offset + limit]:
        out.append("  " + finding_line(rec) + (f" | reason: {rec['reason']}" if rec.get("reason") else ""))
    return "\n".join(out) + "\n"
