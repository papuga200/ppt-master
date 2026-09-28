#!/usr/bin/env python3
"""The legible type floor and the page geometry that plan and page share.

    type_floor.py <project> [--page NN]       # print the floors, the title box and the body zone this project resolves to

Used by page_lint.py (MIN_TYPE, TITLE_SHRUNK, DEAD_BAND) and by the deck runner's plan check (OVER_CAPACITY, TITLE_FIT), so
that the planner is held to the same page the author draws on.

Floors, in px on the 1280 x 720 canvas (quality_criteria.md D4), are minimums, never targets:
  body       16 px (12 pt)    running prose, list items, the key message
  secondary  14 px (10.5 pt)  table cells, diagram and chart labels, callouts, captions
  footnote   11 px (8 pt)     source lines, footnotes and running furniture (header, footer, folio, eyebrow)
A project may raise or lower them in spec_lock.md with an optional block:

    ## type_floor
    - body: 16
    - secondary: 14
    - footnote: 11
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TYPE_ROLES = ("title", "body", "secondary", "footnote", "furniture")
DEFAULT_FLOORS = {"body": 16.0, "secondary": 14.0, "footnote": 11.0}
SPARSE_ROLE = re.compile(r"(?i)\b(cover|section|divider|chapter|closing|ending|end|statement|agenda|contents|toc|thank|thanks|back|title[ _-]?page|breathing|anchor)\b")


def lock_sections(lock: str) -> dict[str, dict[str, str]]:
    """`## name` sections of a spec_lock.md with their `- key: value` lines (forgiving: no schema check)."""
    out: dict[str, dict[str, str]] = {}
    current = None
    for raw in (lock or "").splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", raw)
        if heading:
            current = out.setdefault(heading.group(1).strip().casefold(), {})
            continue
        item = re.match(r"^-\s*([^:]+?)\s*:\s*(.*?)\s*$", raw)
        if current is not None and item:
            current[item.group(1).strip()] = item.group(2).strip()
    return out


def _number(value) -> float | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def floors(lock: str | None) -> dict[str, float]:
    """The body / secondary / footnote floors: the lock's `## type_floor` block where it declares them, else 16 / 14 / 11."""
    out = dict(DEFAULT_FLOORS)
    for key, value in lock_sections(lock or "").get("type_floor", {}).items():
        number = _number(value)
        if key.strip().casefold() in out and number:
            out[key.strip().casefold()] = number
    out["furniture"] = out["footnote"]
    return out


def canvas(lock: str | None) -> tuple[float, float]:
    box = lock_sections(lock or "").get("canvas", {}).get("viewBox", "")
    numbers = [float(n) for n in re.findall(r"-?[\d.]+", box)]
    return (numbers[2], numbers[3]) if len(numbers) == 4 and numbers[2] > 0 and numbers[3] > 0 else (1280.0, 720.0)


def typography(lock: str | None) -> dict[str, str]:
    return lock_sections(lock or "").get("typography", {})


def page_number(stem: str) -> int | None:
    match = re.match(r"^[Pp]?(\d{1,3})(?:[_\-.]|$)", stem)
    return int(match.group(1)) if match else None


def record_block(spec: str | None, number: int | None) -> str:
    if not spec or number is None:
        return ""
    for block in re.split(r"\n(?=#### Slide )", spec)[1:]:
        match = re.match(r"#### Slide (\d+)", block)
        if match and int(match.group(1)) == number:
            return block
    return ""


def record_field(block: str, name: str) -> str:
    match = re.search(rf"- \*\*{re.escape(name)}\*\*(?: \([^)]*\))?:(.*?)(?=\n- \*\*[A-Z][^*]*\*\*|\n- [A-Z][a-z ]+:|\Z)", block, re.S)
    return match.group(1).strip() if match else ""


def layout_name(lock: str | None, block: str, number: int | None) -> str | None:
    """The template layout a page is drawn in: the lock's page_layouts row, else the record's `Layout` (or a layout named in `Composition`)."""
    if number is not None:
        for key, value in lock_sections(lock or "").get("page_layouts", {}).items():
            if page_number(key) == number and value:
                return value.strip()
    layout = record_field(block, "Layout").strip().strip("`").split()[0] if record_field(block, "Layout").strip() else ""
    if layout:
        return layout
    named = re.search(r"`([0-9A-Za-z_.-]+)`", record_field(block, "Composition"))
    return named.group(1) if named else None


def _bounds(tag: str):
    match = re.search(r'data-pptx-bounds="\s*([\d.-]+)[ ,]+([\d.-]+)[ ,]+([\d.]+)[ ,]+([\d.]+)', tag)
    return tuple(float(match.group(i)) for i in range(1, 5)) if match else None


def _attr(tag: str, name: str) -> str | None:
    match = re.search(rf'\s{name}="([^"]*)"', tag)
    return match.group(1) if match else None


def layout_geometry(project: Path | None, lock: str | None, layout: str | None) -> dict:
    """What a layout template says about a page: the title box (x, y, width, size, family, weight) and the body slots
    (placeholders a page fills with content, or the `body-zone` guide rect). Missing items stay None: the caller falls back."""
    result: dict = {"title": None, "slots": [], "body_zone": None, "source": None}
    if project is None or not layout:
        return result
    candidates = [project / "templates" / f"{layout}.svg"]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        return result
    svg = path.read_text(encoding="utf-8", errors="replace")
    result["source"] = str(path)
    for group in re.finditer(r"<g\b[^>]*data-pptx-placeholder=\"([^\"]+)\"[^>]*>", svg):
        kind, bounds = group.group(1).casefold(), _bounds(group.group(0))
        if bounds is None:
            continue
        gid = _attr(group.group(0), "id") or ""
        if kind in ("title", "ctrtitle", "center-title"):
            text = re.search(r"<text\b[^>]*>", svg[group.end():group.end() + 4000])
            size = _number(_attr(text.group(0), "font-size")) if text else None
            result["title"] = {"x": bounds[0], "y": bounds[1], "width": bounds[2], "height": bounds[3], "size": size,
                               "family": _attr(text.group(0), "font-family") if text else None, "weight": (_attr(text.group(0), "font-weight") if text else None) or "normal"}
        elif kind in ("body", "object", "picture", "table", "chart", "media") and not re.search(r"(?i)running|kicker|folio|footer|header|source", gid):
            result["slots"].append({"id": gid, "kind": kind, "x": bounds[0], "y": bounds[1], "width": bounds[2], "height": bounds[3]})
    zone = re.search(r"<rect\b[^>]*id=\"body-zone\"[^>]*>", svg)
    if zone:
        values = [_number(_attr(zone.group(0), k)) or 0.0 for k in ("x", "y", "width", "height")]
        if values[2] and values[3]:
            result["body_zone"] = {"x": values[0], "y": values[1], "width": values[2], "height": values[3]}
    if result["title"] is None:
        text = re.search(r"<text\b[^>]*id=\"sample-title\"[^>]*>", svg)
        if text:
            x = _number(_attr(text.group(0), "x")) or 60.0
            width = result["body_zone"]["width"] if result["body_zone"] and abs(result["body_zone"]["x"] - x) < 24 else None
            result["title"] = {"x": x, "y": _number(_attr(text.group(0), "y")), "width": width, "height": None,
                               "size": _number(_attr(text.group(0), "font-size")), "family": _attr(text.group(0), "font-family"),
                               "weight": _attr(text.group(0), "font-weight") or "normal"}
    return result


def title_box(project: Path | None, lock: str | None, layout: str | None) -> dict:
    """The title's box and type for a layout: the template's title placeholder or sample title, else the lock's title
    size and family on the canvas width less the margins."""
    width, height = canvas(lock)
    geometry = layout_geometry(project, lock, layout)
    found = geometry["title"] or {}
    fonts = typography(lock)
    size = found.get("size") or _number(fonts.get("title")) or 32.0
    family = found.get("family") or fonts.get("title_family") or fonts.get("font_family") or "Segoe UI"
    x = found.get("x") or 60.0
    box_width = found.get("width") or (width - 2 * x)
    return {"x": x, "width": box_width, "size": size, "family": family, "weight": found.get("weight") or "normal",
            "source": geometry["source"] if found else "lock"}


def body_area(project: Path | None, lock: str | None, layout: str | None) -> dict:
    """The area a page's content may fill: the layout's content slots (their summed area; the widest is the exhibit), else the
    template's body-zone guide, else the canvas less a title band (22%) and a footer band (8%) and 54 px side margins."""
    width, height = canvas(lock)
    geometry = layout_geometry(project, lock, layout)
    slots = [s for s in geometry["slots"] if s["width"] * s["height"] >= 0.01 * width * height]
    if slots:
        area = sum(s["width"] * s["height"] for s in slots)
        widest = max(slots, key=lambda s: s["width"] * s["height"])
        return {"area": area, "width": widest["width"], "height": widest["height"], "source": f"{len(slots)} content slot(s) of {geometry['source']}"}
    if geometry["body_zone"]:
        zone = geometry["body_zone"]
        return {"area": zone["width"] * zone["height"], "width": zone["width"], "height": zone["height"], "source": f"body-zone of {geometry['source']}"}
    zone_w, zone_h = width - 108, height * (1 - 0.22 - 0.08)
    return {"area": zone_w * zone_h, "width": zone_w, "height": zone_h, "source": "canvas less title and footer bands"}


def page_context(project: Path | None, stem: str, page_role: str | None = None) -> dict:
    """Everything the lint needs about one page beyond its geometry: floors, the title size it must not shrink below, and
    whether it is a sparse page (cover, divider, statement, closing) where empty canvas is intended."""
    lock = spec = ""
    if project is not None:
        if (project / "spec_lock.md").is_file():
            lock = (project / "spec_lock.md").read_text(encoding="utf-8", errors="replace")
        if (project / "design_spec.md").is_file():
            spec = (project / "design_spec.md").read_text(encoding="utf-8", errors="replace")
    number = page_number(stem)
    block = record_block(spec, number)
    rhythm = next((v for k, v in lock_sections(lock).get("page_rhythm", {}).items() if page_number(k) == number), "") if number is not None else ""
    role = record_field(block, "Role")
    reasons = [r for r in (f"rhythm {rhythm}" if rhythm in ("anchor", "breathing") else "", f"role {role}" if SPARSE_ROLE.search(role or "") else "",
                           f"page role {page_role}" if page_role and SPARSE_ROLE.search(page_role) else "",
                           "file name" if SPARSE_ROLE.search(re.sub(r"[_-]", " ", stem)) else "") if r]
    layout = layout_name(lock, block, number)
    title_size, title_source = None, None
    if lock or layout:
        geometry = layout_geometry(project, lock, layout)
        title_size, title_source = (geometry["title"] or {}).get("size"), "template"
        if not title_size:
            title_size, title_source = _number(typography(lock).get("title")), "lock"
    if reasons and title_source == "lock":
        title_size = None  # a cover or divider sets its own display title; the body pages' locked title size does not bind it
    return {"floors": floors(lock), "title_size": title_size, "title_source": title_source, "sparse": bool(reasons),
            "sparse_reason": ", ".join(reasons), "layout": layout}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("--page", default="02")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    lock = (project / "spec_lock.md").read_text(encoding="utf-8") if (project / "spec_lock.md").is_file() else ""
    context = page_context(project, args.page)
    layout = context["layout"]
    print(json.dumps({"context": context, "title_box": title_box(project, lock, layout), "body_area": body_area(project, lock, layout)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
