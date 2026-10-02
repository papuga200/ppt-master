#!/usr/bin/env python3
"""
PPT Master - Page Authoring Contract

Project the locked type floors and the selected template's declared body zone
into the portable measured creator contract. This adds no content or style decisions.

Usage:
    Called by deck_runner.page_task after the template exists.

Examples:
    prepare_contract(project, page)

Dependencies:
    Standard library; the installed type_floor helper.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import type_floor


def prepare_contract(project: Path, page: dict) -> tuple[Path | None, str]:
    """Write the measured creator input from existing authoritative geometry."""
    lock_path = project / "spec_lock.md"
    lock = lock_path.read_text(encoding="utf-8") if lock_path.is_file() else ""
    layout = page.get("layout") or "content"
    geometry = type_floor.layout_geometry(project, lock, layout)
    template = project / "templates" / f"{layout}.svg"
    if not template.is_file() or not geometry.get("body_zone"):
        return None, "No selected template body-zone is declared; use the ordinary SVG authoring route."
    if type_floor.canvas(lock) != (1280.0, 720.0):
        return None, "Whole-page measured creators currently use 1280 x 720; use ordinary SVG authoring for this canvas."
    zone = geometry["body_zone"]
    body = {"x": zone["x"], "y": zone["y"], "w": zone["width"], "h": zone["height"]}
    if any(not math.isfinite(value) for value in body.values()) or body["w"] <= 0 or body["h"] <= 0:
        raise ValueError(f"invalid body-zone in {template}")
    floors = type_floor.floors(lock)
    contract = {
        "schema": "ppt-master.authoring-contract.v1",
        "template": str(template.resolve()),
        "body_zone": body,
        "type_floors": {"body_px_min": floors["body"], "label_px_min": floors["secondary"],
                        "timeline_chart_label_px_min": floors["secondary"]},
        "native_editability_required": True,
        "source_layout_preflight_required": True,
        "authority": {"lock": str(lock_path.resolve()), "template": str(template.resolve()),
                      "lock_sha256": hashlib.sha256(lock.encode("utf-8")).hexdigest(),
                      "template_sha256": hashlib.sha256(template.read_bytes()).hexdigest()},
    }
    workspace = project / "analysis" / "authoring" / page["stem"]
    workspace.mkdir(parents=True, exist_ok=True)
    target = workspace / "contract.json"
    text = json.dumps(contract, indent=2, ensure_ascii=False) + "\n"
    if not target.is_file() or target.read_text(encoding="utf-8") != text:
        target.write_text(text, encoding="utf-8")
    return target, ""
