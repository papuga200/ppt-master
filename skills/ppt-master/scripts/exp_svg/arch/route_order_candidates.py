#!/usr/bin/env python3
"""PPT Master - Architecture connector processing orders.

Try at most six deterministic edge orders while retaining every exact edge.
See scripts/docs/experimental-authoring-tools.md; no SVG is emitted.
Usage: python route_order_candidates.py --in request.json --out new-directory
Examples: evaluate a retained scene with congested optional route processing.
Dependencies: Pillow through architecture evaluation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

_ARCH_DIR = Path(__file__).resolve().parent
for directory in (_ARCH_DIR, _ARCH_DIR.parents[1]):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
import compose_page as cp  # noqa: E402
from candidate_common import evaluate_copy, ready, score, write_search  # noqa: E402
from console_encoding import configure_utf8_stdio  # noqa: E402


def orders(edges: list[dict]):
    """Yield no more than six distinct deterministic routing orders."""
    variants = [("original", edges), ("reverse", list(reversed(edges))),
                ("labelled-first", sorted(edges, key=lambda edge: not bool(edge.get("label")))),
                ("labelled-last", sorted(edges, key=lambda edge: bool(edge.get("label")))),
                ("kind-grouped", sorted(edges, key=lambda edge: (edge.get("kind", ""), edge["id"]))),
                ("kind-reversed", sorted(edges, key=lambda edge: (edge.get("kind", ""), edge["id"]), reverse=True))]
    seen = set()
    for name, items in variants:
        key = tuple(edge["id"] for edge in items)
        if key not in seen:
            seen.add(key)
            yield name, items


def run_candidates(request: dict, *, evaluate=None) -> tuple[dict, dict, dict, list[dict]]:
    """Select routing orders without altering relationships or attachment sides."""
    evaluator = cp.evaluate if evaluate is None else evaluate
    trials, best = [], None
    for name, edges in orders(request.get("edges", [])):
        candidate = copy.deepcopy(request)
        candidate["edges"] = copy.deepcopy(edges)
        receipt = evaluate_copy(candidate, evaluator)
        trial = {"order": name, "score": list(score(receipt)), "ready": ready(receipt),
                 "capacity_fit": receipt.get("capacity_fit"),
                 "blocking_constraints": receipt.get("blocking_constraints", []),
                 "warnings": receipt.get("warnings", [])}
        trials.append(trial)
        rank = (not ready(receipt), score(receipt))
        if best is None or rank < best[0]:
            best = rank, name, candidate, receipt
    _, name, selected, receipt = best
    summary = {"schema": "exp_svg.arch.route_order_candidates.v1", "selected_order": name,
               "candidate_count": len(trials), "ready": ready(receipt), "trials": trials,
               "scope": "Only edge array processing order changes. Composer readiness is authoritative; facts, visual judgment and native export remain unverified."}
    return selected, receipt, summary, trials


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New directory with complete search receipts")
    args = parser.parse_args(argv)
    try:
        raw = args.source.read_bytes()
        selected, receipt, summary, trials = run_candidates(json.loads(raw.decode("utf-8-sig")))
        summary["input_sha256"] = hashlib.sha256(raw).hexdigest()
        write_search(args.source, args.out, selected, receipt, summary, trials)
    except (OSError, ValueError, cp.HelperError) as exc:
        print(f"route order candidates: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"selected_order": summary["selected_order"], "ready": summary["ready"],
                      "candidate_count": len(trials), "out": str(args.out)}))
    return 0 if summary["ready"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
