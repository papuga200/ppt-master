#!/usr/bin/env python3
"""
PPT Master - exp_svg inspection: validation runner (no model calls)

Runs inspect_svg over (a) the deterministic synthetic cases of synthetic.py and (b) historical
fixtures with owner-adjudicated defects, each case folder holding slide.svg (or a pointer to the
historical SVG), request.json, checklist.json and expected.json. Scores detection against the
planted / adjudicated defects:

    recall     = expected defects with at least one matching failed check / expected defects
    precision  = failed checks matching an expected defect / failed checks that are not excluded

A failed check matches an expected defect when its check family is the expected one and one of
its targets equals (or is a line of) an expected target. Three precisions are reported:
    precision_strict                    TP / all failed checks
    precision_excluding_measured_facts  TP / failed checks other than expected.json "measured_facts"
                                        (e.g. type-floor failures under the 2026-09-30 floors on
                                        historical slides, a logo missing from the fixture package)
    precision                           TP / (TP + failed checks not classified by the validator as
                                        true_unadjudicated or uncertain in expected.json "reviewed")
The "reviewed" classifications are the validator's own judgement, not owner adjudication.

Usage:
    python3 run_validation.py --cases DIR [--cases DIR ...] --out validation.json [--synthetic-into DIR]

Dependencies:
    playwright (Chromium) from the fork's venv
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import common  # noqa: E402

common.ensure_scripts_path()

import inspect_svg as I  # noqa: E402
import summary as S  # noqa: E402
import synthetic  # noqa: E402
from svg_geometry import Browser  # noqa: E402


def _target_match(targets: list[str], wanted: list[str]) -> bool:
    for t in targets:
        base = t.split(":line")[0]
        for w in wanted:
            if t == w or base == w or t == "#" + w:
                return True
    return False


def _review_of(r: dict, reviewed: list[dict]) -> Optional[dict]:
    """Validator classification of a failed check: matched by family, targets and message text."""
    for rv in reviewed:
        if rv.get("check") != r["check"]:
            continue
        if rv.get("targets") and not all(_target_match(r["targets"], [t]) for t in rv["targets"]):
            continue
        if rv.get("message_contains") and rv["message_contains"] not in r["message"]:
            continue
        return rv
    return None


def score_case(report: dict, expected: dict) -> dict:
    """Recall on expected defects; precision three ways (see module docstring and README)."""
    failed = [r for r in report.get("checks", []) if r["status"] == "failed"]
    exp = expected.get("expected_defects", [])
    facts = expected.get("measured_facts", [])
    reviewed = expected.get("reviewed", [])
    detected, missed = [], []
    tp_ids = set()
    for d in exp:
        hits = [r for r in failed if r["check"] == d["check"] and _target_match(r["targets"], d["targets"])]
        (detected if hits else missed).append({**d, "hits": [r["check_id"] for r in hits]})
        tp_ids.update(r["check_id"] for r in hits)
    # repaired items (owner says fixed): a failure naming them is a false alarm
    absent_total = absent_clean = 0
    alarm_ids = set()
    for d in expected.get("expected_absent", []):
        for target in d["targets"]:
            absent_total += 1
            hits = [r for r in failed if r["check"] == d["check"] and _target_match(r["targets"], [target])
                    and (not d.get("message_contains") or d["message_contains"] in r["message"])]
            if hits:
                alarm_ids.update(r["check_id"] for r in hits)
            else:
                absent_clean += 1
    fact_ids, classified, fp = [], [], []
    for r in failed:
        if r["check_id"] in tp_ids:
            continue
        if r["check_id"] in alarm_ids:
            fp.append({"check_id": r["check_id"], "check": r["check"], "severity": r["severity"], "targets": r["targets"][:3],
                       "message": r["message"][:200], "class": "false_alarm_on_repaired_item", "note": "owner says this item was repaired"})
            continue
        fact = next((f for f in facts if f.get("check") == r["check"] and (not f.get("targets") or _target_match(r["targets"], f["targets"]))), None)
        if fact:
            fact_ids.append(r["check_id"])
            continue
        rv = _review_of(r, reviewed)
        row = {"check_id": r["check_id"], "check": r["check"], "severity": r["severity"], "targets": r["targets"][:3], "message": r["message"][:200]}
        if rv and rv.get("class") in ("true_unadjudicated", "uncertain"):
            classified.append({**row, "class": rv["class"], "note": rv.get("note")})
        else:
            fp.append({**row, "class": (rv or {}).get("class", "unreviewed"), "note": (rv or {}).get("note")})
    tp = len(tp_ids)

    def ratio(den: int) -> Optional[float]:
        return tp / den if den else None

    classes = {}
    for row in classified + fp:
        classes[row["class"]] = classes.get(row["class"], 0) + 1
    return {"expected": len(exp), "detected": len(detected), "missed": missed, "detected_detail": detected,
            "failed_checks": len(failed), "true_positive_checks": tp, "measured_fact_checks": len(fact_ids),
            "validator_classified": classified, "false_positive_checks": fp, "other_classes": classes,
            "recall": (len(detected) / len(exp)) if exp else None,
            "repaired_items": absent_total, "repaired_items_clean": absent_clean,
            "specificity_on_repaired": (absent_clean / absent_total) if absent_total else None,
            "precision_strict": ratio(len(failed)),
            "precision_excluding_measured_facts": ratio(len(failed) - len(fact_ids)),
            "precision": ratio(tp + len(fp)),
            "unverified": report.get("result", {}).get("unverified"), "status": report.get("status"),
            "elapsed_s": report.get("elapsed_s"), "timings_s": report.get("timings_s")}


def run_cases(folders: list[Path], browser: Browser, generic_only: bool = False, tag: str = "") -> list[dict]:
    rows = []
    for folder in folders:
        exp = common.read_json(folder / "expected.json")
        svg = Path(exp["svg"]) if exp.get("svg") else folder / "slide.svg"
        request, rhash, base = I.load_request(folder / "request.json")
        checklist, chash, csrc = I.load_checklist(request, base, None)
        if generic_only:
            request = {k: v for k, v in request.items() if k not in ("checklist", "mapping", "connectors", "containment")}
            checklist = chash = csrc = None
        started = time.perf_counter()
        report = I.inspect_file(svg, request, checklist, browser=browser, png=folder / f"render{tag}.png", request_hash=rhash,
                                checklist_hash=chash, checklist_src=csrc)
        wall = time.perf_counter() - started
        common.write_json(folder / f"report{tag}.json", report)
        text = S.render(report, 2000, str(folder / f"report{tag}.json"))
        (folder / f"summary{tag}.txt").write_text(text, encoding="utf-8")
        row = {"case": folder.name, "svg": str(svg), "svg_sha256": report.get("artifact", {}).get("sha256"), "wall_s": round(wall, 3),
               "summary_tokens_est": S.estimate_tokens(text), **score_case(report, exp)}
        if exp.get("expected_unverified_or_limits"):
            blob = json.dumps(report.get("limits", {}).get("present_on_this_slide", [])) + json.dumps([r for r in report.get("checks", []) if r["status"] == "unverified"])
            row["limits_listed"] = {k: (k.lower() in blob.lower()) for k in exp["expected_unverified_or_limits"]}
        rows.append(row)
        print(f"{folder.name}: recall {row['recall']} precision {row['precision']} fp {len(row['false_positive_checks'])} "
              f"missed {[m['note'] or m['targets'] for m in row['missed']]} ({wall:.2f} s)", file=sys.stderr)
    return rows


def aggregate(rows: list[dict]) -> dict:
    exp = sum(r["expected"] for r in rows)
    det = sum(r["detected"] for r in rows)
    tp = sum(r["true_positive_checks"] for r in rows)
    fp = sum(len(r["false_positive_checks"]) for r in rows)
    failed = sum(r["failed_checks"] for r in rows)
    facts = sum(r["measured_fact_checks"] for r in rows)
    cls = {}
    for r in rows:
        for k, v in r["other_classes"].items():
            cls[k] = cls.get(k, 0) + v
    walls = sorted(r["wall_s"] for r in rows)
    rep = sum(r["repaired_items"] for r in rows)
    rep_clean = sum(r["repaired_items_clean"] for r in rows)
    return {"cases": len(rows), "expected_defects": exp, "detected_defects": det, "recall": det / exp if exp else None,
            "repaired_items": rep, "repaired_items_clean": rep_clean, "specificity_on_repaired": rep_clean / rep if rep else None,
            "failed_checks": failed, "true_positive_checks": tp, "measured_fact_checks": facts, "classified_checks": cls,
            "false_positive_checks": fp,
            "precision_strict": tp / failed if failed else None,
            "precision_excluding_measured_facts": tp / (failed - facts) if (failed - facts) else None,
            "precision": tp / (tp + fp) if (tp + fp) else None,
            "clean_controls_with_false_positives": [r["case"] for r in rows if r["expected"] == 0 and r["false_positive_checks"]],
            "wall_s_per_slide": {"min": walls[0], "median": walls[len(walls) // 2], "max": walls[-1]} if walls else None}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate inspect_svg on synthetic and historical cases.")
    parser.add_argument("--cases", type=Path, action="append", default=[], help="folder containing case folders")
    parser.add_argument("--synthetic-into", type=Path, help="(re)write the synthetic cases into this folder first and include them")
    parser.add_argument("--generic", type=Path, action="append", default=[],
                        help="folder of cases to run WITHOUT their checklist (generic checks only); outputs report.generic.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    from console_encoding import configure_utf8_stdio
    configure_utf8_stdio()
    groups = []
    if args.synthetic_into:
        synthetic.write_cases(args.synthetic_into)
        groups.append(("synthetic", args.synthetic_into, False))
    for folder in args.cases:
        groups.append((folder.name, folder, False))
    for folder in args.generic:
        groups.append((folder.name + "-generic-only", folder, True))
    started = time.perf_counter()
    result = {"tool": "run_validation", "version": common.TOOLKIT_VERSION, "at": common.utc_now(), "groups": {}}
    with Browser() as browser:
        result["browser"] = {"engine": "chromium", "version": browser.chromium_version}
        for name, folder, generic in groups:
            cases = sorted(p for p in folder.iterdir() if p.is_dir() and (p / "expected.json").is_file())
            rows = run_cases(cases, browser, generic_only=generic, tag=".generic" if generic else "")
            result["groups"][name] = {"folder": str(folder), "aggregate": aggregate(rows), "cases": rows}
    result["elapsed_s"] = round(time.perf_counter() - started, 3)
    common.write_json(args.out, result)
    for name, g in result["groups"].items():
        a = g["aggregate"]
        print(f"{name}: recall {a['recall']} precision {a['precision']} ({a['detected_defects']}/{a['expected_defects']} defects; "
              f"{a['false_positive_checks']} false-positive checks) per-slide {a['wall_s_per_slide']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
