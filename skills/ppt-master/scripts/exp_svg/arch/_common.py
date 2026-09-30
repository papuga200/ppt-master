#!/usr/bin/env python3
"""
PPT Master - experimental architecture helpers: shared receipt and I/O layer

Every exp_svg/arch tool reads one JSON request and writes one JSON result that
carries the helper-contract receipt: tool/version, input hash, output hash,
elapsed time, status (ok / partial / capacity_failure / error), residual
constraints and stable content IDs. This module owns that envelope so the four
tools report it identically.

Usage:
    Library module; imported by measure_labels.py, arrange.py, move_group.py
    and route_connections.py in this folder.

Dependencies:
    None (only uses standard library)
"""

from __future__ import annotations

import copy
import json
import hashlib
import sys
import time
from pathlib import Path
from typing import Any, Callable

ARCH_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = ARCH_DIR.parent.parent
for _path in (str(SCRIPTS_DIR), str(ARCH_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

HELPER_VERSION = "0.1.0-exp20260930"
STATUSES = ("ok", "partial", "capacity_failure", "error")
CANVAS_W, CANVAS_H = 1280.0, 720.0
# user-confirmed floors for this experiment (manifest.json type_floors): 12 pt body, 10 pt labels at 1 px = 0.75 pt
FLOOR_BODY_PX = 16.0
FLOOR_LABEL_PX = 13.333
FLOOR_TOLERANCE = 0.01


class HelperError(ValueError):
    """A request the tool cannot act on: reported as status `error`, nothing half-written."""


def check_engine(kind: str, engine: str) -> None:
    """Experiment packages pin their engines (orchestrator decision D020): when PPT_MASTER_EXP_ENGINES is set
    (e.g. "placement:primitive;routing:orthogonal"), any other engine is refused rather than silently used."""
    import os
    spec = os.environ.get("PPT_MASTER_EXP_ENGINES")
    if not spec:
        return
    allowed: dict[str, set] = {}
    for part in spec.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            allowed.setdefault(k.strip(), set()).update(x.strip() for x in v.split(",") if x.strip())
    if kind in allowed and engine not in allowed[kind]:
        raise HelperError(f"{kind} engine {engine!r} is not part of this package (allowed: {sorted(allowed[kind])})")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def load_request(path: str) -> tuple[dict, str]:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HelperError(f"request {path} is not JSON: {exc}") from exc
    if not isinstance(request, dict):
        raise HelperError("the request must be a JSON object")
    return request, sha256_json(request)


def envelope(tool: str, *, input_hash: str, started: float, status: str, result: dict,
             residuals: list[dict], content_ids: list[str], extra: dict | None = None) -> dict:
    """Wrap a tool result in the helper-contract receipt."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status}")
    body = {"result": result, "residual_constraints": residuals, "content_ids": sorted(set(content_ids))}
    if extra:
        body.update(extra)
    output_hash = sha256_json(body)
    return {
        "tool": tool,
        "version": HELPER_VERSION,
        "status": status,
        "input_sha256": input_hash,
        "output_sha256": output_hash,
        "elapsed_s": round(time.perf_counter() - started, 4),
        **body,
    }


def error_envelope(tool: str, input_hash: str, started: float, message: str) -> dict:
    return envelope(tool, input_hash=input_hash, started=started, status="error", result={"error": message},
                    residuals=[{"kind": "request_error", "message": message}], content_ids=[])


def write_json(path: str | None, payload: dict) -> None:
    text = json.dumps(payload, indent=1, ensure_ascii=False)
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")


def run_cli(tool: str, argv: list[str] | None, work: Callable[[dict, Any], tuple[str, dict, list, list, dict | None]],
            add_arguments: Callable | None = None, description: str = "") -> int:
    """Shared CLI: --in request.json --out result.json [--svg out.svg]. Exit 0 ok, 3 partial, 4 capacity, 2 error."""
    import argparse

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="request", required=True, help="request JSON file")
    parser.add_argument("--out", dest="out", default=None, help="result JSON file (default: stdout)")
    parser.add_argument("--svg", dest="svg", default=None, help="also write a previewable 1280x720 SVG of the result")
    if add_arguments:
        add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        from console_encoding import configure_utf8_stdio
        configure_utf8_stdio()
    except ImportError:
        pass
    started = time.perf_counter()
    input_hash = ""
    try:
        request, input_hash = load_request(args.request)
        status, result, residuals, ids, extra = work(copy.deepcopy(request), args)
        payload = envelope(tool, input_hash=input_hash, started=started, status=status, result=result,
                           residuals=residuals, content_ids=ids, extra=extra)
    except HelperError as exc:
        payload = error_envelope(tool, input_hash, started, str(exc))
    write_json(args.out, payload)
    for item in payload["residual_constraints"][:20]:
        print(f"{tool}: {payload['status']}: {item.get('kind')}: {item.get('message', '')}", file=sys.stderr)
    return {"ok": 0, "partial": 3, "capacity_failure": 4, "error": 2}[payload["status"]]
