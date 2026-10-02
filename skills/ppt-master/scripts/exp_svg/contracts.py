#!/usr/bin/env python3
"""PPT Master - Experimental authoring contracts.

Resolve explicit portable page contracts and optional host workspace boundaries.

Usage:
    Import through exp_svg guided entry points.
Examples:
    capacity_preflight.py --contract canvas.json --workspace /project ...
Dependencies:
    None (only uses standard library).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from exp_svg.arch._common import sha256_json

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def add_contract_arguments(parser) -> None:
    """Add a portable contract and an optional host-owned workspace boundary."""
    parser.add_argument("--contract", type=Path, help="Page contract JSON; relative template paths resolve beside it")
    parser.add_argument("--workspace", type=Path, help="Optional absolute workspace; otherwise PPT_MASTER_PROJECT_PATH")


def load_contract(args) -> tuple[dict, Path, Path | None]:
    """Load a contract, retaining the historical host fixture location as a fallback."""
    root = args.workspace or os.environ.get("PPT_MASTER_PROJECT_PATH")
    workspace = (REPOSITORY_ROOT / root).resolve() if root else None
    if args.contract is None and workspace is None:
        raise ValueError("Pass --contract canvas.json or --workspace PROJECT with inputs/fixture/canvas.json")
    path = args.contract.resolve() if args.contract else workspace / "inputs/fixture/canvas.json"
    canvas = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(canvas, dict):
        raise ValueError("Page contract must be a JSON object")
    for field in ("body_zone", "type_floors"):
        if not isinstance(canvas.get(field), dict):
            raise ValueError(f"Page contract needs {field}")
    for key in ("x", "y", "w", "h"):
        number = canvas["body_zone"].get(key)
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or key in {"w", "h"} and number <= 0):
            raise ValueError(f"body_zone.{key} must be finite numeric; dimensions must be positive")
    for key, number in canvas["type_floors"].items():
        if (isinstance(number, bool) or not isinstance(number, (int, float))
                or not math.isfinite(number) or number <= 0):
            raise ValueError(f"type_floors.{key} must be finite positive numeric")
    if "label_px_min" not in canvas["type_floors"]:
        raise ValueError("type_floors.label_px_min is required")
    if canvas.get("template"):
        canvas["template"] = str((path.parent / canvas["template"]).resolve())
    return canvas, path, workspace


def check_paths(source: Path, outputs: list[Path], workspace: Path | None,
                *, resources: list[Path] | None = None) -> None:
    """Keep outputs distinct from inputs and inside an explicitly selected workspace."""
    source = source.resolve()
    resolved = [path.resolve() for path in outputs]
    protected = {source, *(path.resolve() for path in resources or [])}
    if len(resolved) != len(set(resolved)) or any(path in protected for path in resolved):
        raise ValueError("Outputs must be distinct and must not replace the request or an input resource")
    if workspace is not None:
        source.relative_to(workspace)
        for path in resolved:
            path.relative_to(workspace)


def validate_preflight_fingerprints(receipt: dict, request: dict, contract_path: Path,
                                   *, required: bool = False) -> None:
    """Reject stale normalization when contract or geometry defaults changed."""
    import hashlib
    actual = {"contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
              "normalized_request_sha256": sha256_json(request)}
    for key, digest in actual.items():
        if required and key not in receipt:
            raise ValueError(f"Preflight is missing {key}; rerun preflight with the current explicit contract")
        if key in receipt and receipt[key] != digest:
            raise ValueError(f"Preflight {key} is stale; rerun preflight for the current contract and request")
