#!/usr/bin/env python3
"""
PPT Master - exp_svg inspection: shared helpers

Result envelope, hashing and JSON I/O shared by inspect_svg.py, render_export.py and
submit_check.py (SVG helpers experiment, 2026-09-30). Every tool result carries the tool name
and version, the input hash, the output hash, the elapsed time and a status of ok / partial /
capacity_failure / error (PROMPTS.md "Proposed shared helper contract").

Usage:
    Imported by the sibling scripts; not a command.

Dependencies:
    None (only uses standard library)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

if __name__ == "__main__" and any(arg in {"-h", "--help", "help"} for arg in sys.argv[1:]):
    print(__doc__)
    raise SystemExit(0)

INSPECT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = INSPECT_DIR.parent.parent
TOOLKIT_VERSION = "exp_svg.inspect/0.1.0"
STATUSES = ("ok", "partial", "capacity_failure", "error")
CANVAS_W = 1280.0
CANVAS_H = 720.0
LABEL_FLOOR_PX = 13.333  # 10 pt at 1280 px = 13.333 in (user-confirmed 2026-09-30)
BODY_FLOOR_PX = 16.0     # 12 pt


def ensure_scripts_path() -> None:
    """Put scripts/ and this folder on sys.path (the scripts tree is not a package)."""
    for folder in (SCRIPTS_DIR, INSPECT_DIR):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> str:
    """Write JSON (UTF-8, LF) atomically and return the sha256 of the bytes written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, indent=1, ensure_ascii=False) + "\n").encode("utf-8")
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return sha256_bytes(data)


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def envelope(tool: str, *, input_hash: Optional[str], status: str, started: float, **extra: Any) -> dict:
    """Common result header; the caller adds the output hash after writing."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return {
        "tool": tool,
        "version": TOOLKIT_VERSION,
        "input_sha256": input_hash,
        "output_sha256": None,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "status": status,
        "at": utc_now(),
        **extra,
    }


def file_fact(path: Path) -> dict:
    path = Path(path)
    if not path.is_file():
        return {"path": str(path), "exists": False}
    return {"path": str(path), "exists": True, "bytes": path.stat().st_size, "sha256": sha256_file(path)}
