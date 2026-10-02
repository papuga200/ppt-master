#!/usr/bin/env python3
"""PPT Master - Architecture candidate receipt helpers.

Preserve the composer readiness authority while ranking bounded optional trials.
Usage: Import from architecture candidate entry points.
Examples: summarize an evaluator receipt without revising its findings.
Dependencies: None (only uses standard library).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


def ready(receipt: dict) -> bool:
    """Consume the evaluator's decision without reclassifying findings."""
    return receipt.get("ready") is True and receipt.get("delivery_state") == "ready"


def score(receipt: dict) -> tuple:
    """Prefer retained routes, fewer blockers, then cleaner complete routes."""
    blockers = receipt.get("blocking_constraints", [])
    routes = receipt.get("result", receipt.get("geometry", {})).get("routes", {})
    absent = sum(item.get("kind") in {"unrouted", "edge_label_missing", "bus_branch_blocked"}
                 for item in blockers)
    return (absent, len(blockers),
            sum(len(item.get("stats", {}).get("crosses", [])) for item in routes.values()),
            sum(item.get("stats", {}).get("bends", 0) for item in routes.values()),
            sum(item.get("stats", {}).get("length_px", 0) for item in routes.values()))


def evaluate_copy(request: dict, evaluator) -> dict:
    """Protect the caller's immutable request from an evaluator mutation."""
    candidate = copy.deepcopy(request)
    receipt = evaluator(candidate)
    if candidate != request:
        raise RuntimeError("Evaluator mutated its request")
    return receipt


def write_search(source: Path, output: Path, selected: dict, receipt: dict,
                 summary: dict, trials: list[dict]) -> None:
    """Retain a search in a new directory without replacing input resources."""
    if output.exists():
        raise ValueError("Use a new output directory; previous candidates are retained")
    protected = {source.resolve()}
    template = selected.get("page", {}).get("template")
    if template:
        protected.add(Path(template).resolve())
    for config in (selected.get("font", {}), selected.get("page", {})):
        protected.update(Path(path).resolve() for path in
                         (config.get("files") or config.get("font_files") or {}).values())
    values = {"selected-request.json": selected, "selected-receipt.json": receipt,
              "summary.json": summary, "trials-full.json": trials}
    if any((output / name).resolve() in protected for name in values):
        raise ValueError("Search output must not overwrite an input resource")
    output.mkdir(parents=True)
    for name, value in values.items():
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                             allow_nan=False) + "\n", encoding="utf-8")
