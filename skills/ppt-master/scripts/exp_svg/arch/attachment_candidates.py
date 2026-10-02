#!/usr/bin/env python3
"""PPT Master - Optional architecture attachment candidates.

Search at most 18 side pairs for one caller-authorized edge. No facts or SVG
change; brief-required sides stay pinned. See scripts/docs/experimental-authoring-tools.md.
Usage: python attachment_candidates.py --in request.json --edge flow --out new-dir --allow-adapt-sides
Examples: omit sides initially so the router selects its default sides.
Dependencies: Pillow through architecture evaluation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
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


def run_candidates(request: dict, edge_id: str, *, allow_adapt_sides: bool = False,
                   evaluate=None) -> tuple[dict, dict, dict, list[dict]]:
    """Vary only a selected edge's optional source_side/target_side fields."""
    if not allow_adapt_sides:
        raise ValueError("Explicit --allow-adapt-sides authorization is required; keep semantic sides pinned")
    matches = [i for i, edge in enumerate(request.get("edges", [])) if edge.get("id") == edge_id]
    if len(matches) != 1:
        raise ValueError(f"Edge {edge_id!r} must match exactly one declared edge")
    index = matches[0]
    edge = request["edges"][index]
    choices = [(edge.get("source_side"), edge.get("target_side")), (None, None)]
    choices += list(itertools.product("NESW", repeat=2))
    trials, best, seen = [], None, set()
    evaluator = cp.evaluate if evaluate is None else evaluate
    for source_side, target_side in choices:
        if (source_side, target_side) in seen:
            continue
        seen.add((source_side, target_side))
        candidate = copy.deepcopy(request)
        for key, side in (("source_side", source_side), ("target_side", target_side)):
            if side is None:
                candidate["edges"][index].pop(key, None)
            else:
                candidate["edges"][index][key] = side
        receipt = evaluate_copy(candidate, evaluator)
        trial = {"source_side": source_side, "target_side": target_side,
                 "score": list(score(receipt)), "ready": ready(receipt),
                 "blocking_constraints": receipt.get("blocking_constraints", []),
                 "warnings": receipt.get("warnings", [])}
        trials.append(trial)
        rank = (not ready(receipt), score(receipt))
        if best is None or rank < best[0]:
            best = rank, candidate, receipt, trial
    _, selected, receipt, trial = best
    summary = {"schema": "exp_svg.arch.attachment_candidates.v1", "edge": edge_id,
               "selected_sides": [trial["source_side"], trial["target_side"]],
               "candidate_count": len(trials), "before_score": trials[0]["score"],
               "after_score": trial["score"], "ready": ready(receipt),
               "scope": "Only selected optional edge sides change. Composer readiness is authoritative; facts, visual judgment and native export remain unverified."}
    return selected, receipt, summary, trials


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="source", type=Path, required=True)
    parser.add_argument("--edge", required=True)
    parser.add_argument("--out", type=Path, required=True, help="New directory with complete search receipts")
    parser.add_argument("--allow-adapt-sides", action="store_true")
    args = parser.parse_args(argv)
    try:
        raw = args.source.read_bytes()
        selected, receipt, summary, trials = run_candidates(json.loads(raw.decode("utf-8-sig")), args.edge,
                                                           allow_adapt_sides=args.allow_adapt_sides)
        summary["input_sha256"] = hashlib.sha256(raw).hexdigest()
        write_search(args.source, args.out, selected, receipt, summary, trials)
    except (OSError, ValueError, cp.HelperError) as exc:
        print(f"attachment candidates: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(dict(summary, out=str(args.out))))
    return 0 if summary["ready"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
