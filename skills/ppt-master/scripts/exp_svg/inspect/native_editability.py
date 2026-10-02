#!/usr/bin/env python3
"""PPT Master - Bounded native editability audit.

This is structural evidence, not complete semantic detection or visual parity.
PPTX evidence is optional and must be a one-slide export of the supplied SVG.
See scripts/docs/experimental-authoring-tools.md for the verification boundary.
Usage: python native_editability.py --svg slide.svg --pptx slide.pptx --out audit.json
Examples: omit --pptx for source ownership evidence only.
Dependencies: existing converter dependencies for native table payload validation.
"""
from __future__ import annotations

import copy
import argparse
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

S = "{http://www.w3.org/2000/svg}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
GEOMETRY = {"rect", "circle", "ellipse", "line", "path", "polygon", "polyline"}


def _tag(e: ET.Element) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _frame(value: str | None) -> bool:
    try:
        values = [float(v) for v in (value or "").split()]
        return len(values) == 4 and all(math.isfinite(v) for v in values) and min(values[2:]) > 0
    except ValueError:
        return False


def _normalize(value: str) -> str:
    return " ".join(value.split())


def _join_wrap(left: str, right: str) -> str:
    """Match the exporter's Latin-space/CJK-continuation policy."""
    scripts = str(Path(__file__).resolve().parents[2])
    added = scripts not in sys.path
    if added:
        sys.path.insert(0, scripts)
    try:
        from svg_to_pptx.drawingml.utils import is_cjk_char
    finally:
        if added:
            sys.path.remove(scripts)
    separator = "" if not left or not right or left[-1].isspace() or right[0].isspace() or is_cjk_char(left[-1]) or is_cjk_char(right[0]) else " "
    return left + separator + right


def _svg_text(text: ET.Element) -> str:
    value = text.text or ""
    for child in text:
        content = "".join(child.itertext())
        # Positioned visual lines and explicit paragraphs need a word boundary;
        # inline formatting tspans keep their authored adjacency.
        line = (text.get("data-paragraph-line-height") is not None
                or child.get("y") is not None or child.get("dy") not in {None, "0", "0.0"})
        if child.get("data-paragraph-soft-break") == "1":
            value = _join_wrap(value, content)
        else:
            value = value + (" " if line and value else "") + content
        value += child.tail or ""
    return _normalize(value)


def _native_text(body: ET.Element) -> str:
    paragraphs = [_native_paragraph_text(paragraph) for paragraph in body.findall(A + "p")]
    return _normalize(" ".join(paragraphs))


def _native_paragraph_text(paragraph: ET.Element) -> str:
    """Normalize native continuation rows with the source's wrap rules."""
    value = ""
    continuation = False
    for node in paragraph.iter():
        if node.tag == A + "br":
            continuation = True
        elif node.tag == A + "t":
            content = node.text or ""
            value = _join_wrap(value, content) if continuation else value + content
            if content:
                continuation = False
    return _normalize(value)


def _table_payload(element: ET.Element) -> tuple[dict, int, int, list[list[str]]]:
    metadata = [e for e in element if _tag(e) == "metadata" and e.get("type") == "application/json"]
    if len(metadata) != 1:
        raise ValueError("Table requires one direct application/json metadata child")
    payload = json.loads(metadata[0].text or "")
    if not isinstance(payload, dict) or payload.get("schema") != "ppt-master.semantic-table.v2":
        raise ValueError("Table requires ppt-master.semantic-table.v2 metadata")
    for key in ("x", "y", "width", "height"):
        if key in payload:
            value = payload[key]
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or (key in {"width", "height"} and value <= 0)):
                raise ValueError(f"Table {key} must be finite numeric bounds with positive dimensions")
    # Reuse the exporter's closed payload validation, including merges and styles.
    scripts = str(Path(__file__).resolve().parents[2])
    added = scripts not in sys.path
    if added:
        sys.path.insert(0, scripts)
    try:
        from svg_to_pptx.native_objects.table import _validate_table_payload, _table_cell_text_parts
        _, rows, columns, _ = _validate_table_payload(copy.deepcopy(payload))
        cells = [[_normalize(" ".join(_table_cell_text_parts(cell))) for cell in row] for row in rows]
    finally:
        if added:
            sys.path.remove(scripts)
    return payload, len(rows), columns, cells


def audit(svg: Path, pptx: Path | None = None) -> dict:
    """Return status (passed/failed), findings, counts and explicit scope limits."""
    findings: list[dict] = []
    counts = {"shapes": 0, "lists": 0, "tables": 0, "detected_nodes": 0, "pptx_objects_verified": 0}
    result = {
        "status": "passed", "findings": findings, "counts": counts,
        "svg": str(svg), "pptx": str(pptx) if pptx is not None else None,
        "limitations": [
            "Checks declared shapes, lists, tables and data-arch-role=node groups only; unmarked semantic objects are not exhaustively detected.",
            "Visual parity, geometry accuracy and text fitting are outside this audit.",
            "PPTX ownership requires a one-slide export and stable unique cNvPr names." if pptx is not None else "PPTX native ownership is unverified without an exported PPTX.",
        ],
    }

    def fail(code: str, e: ET.Element | None, message: str) -> None:
        findings.append({"code": code, "status": "failed", "severity": "blocker", "element_id": e.get("id") if e is not None else None, "message": message})
        result["status"] = "failed"

    try:
        root = ET.parse(svg).getroot()
        if root.tag != S + "svg":
            raise ValueError("Expected an SVG namespace root")
    except (OSError, ET.ParseError, ValueError) as exc:
        fail("invalid_svg", None, str(exc))
        return result

    expected: list[dict] = []
    names: set[str] = set()
    for e in root.iter():
        semantic = e.get("data-pptx-semantic-object")
        editable = e.get("data-editable-kind")
        node = e.get("data-arch-role") == "node"
        shape = semantic == "shape" or editable == "shape"
        table = editable == "table" or semantic == "table" or e.get("data-pptx-replace-with") == "table"
        listing = editable == "list"
        if (_tag(e) == "g" and not listing and not table
                and editable not in {"gantt", "legend", "timeline", "chart"}
                and e.get("data-arch-role") not in {"legend", "timeline", "gantt"}
                and e.get("data-pptx-replace-with") != "chart"):
            sibling_bullets = ["".join(t.itertext()).lstrip() for t in e if _tag(t) == "text"]
            sibling_bullets = [v for v in sibling_bullets if len(v) > 1 and v[0] in "·•●▪■◆◇◦‣" and v[1:].strip()]
            if len(sibling_bullets) >= 2:
                fail("probable_fragmented_list", e, "Multiple bullet-prefixed sibling text frames indicate a probable fragmented list")
        if not (shape or table or listing or node):
            continue
        before = len(findings)
        texts = [t for t in e.iter() if _tag(t) == "text"]
        if node:
            counts["detected_nodes"] += 1
            if not shape and texts and any(_tag(t) == "rect" for t in e.iter()):
                fail("fragmented_node", e, "Architecture node rectangle and label need one semantic shape owner")
        kind = "table" if table else "list" if listing else "shape" if shape else None
        if kind is None:
            continue
        counts[{"shape": "shapes", "list": "lists", "table": "tables"}[kind]] += 1
        if sum((shape, table, listing)) > 1 and not (shape and listing and not table):
            fail("conflicting_semantics", e, "Object has conflicting native semantics")
        record = {"element": e, "kind": kind, "shape": shape}
        if shape:
            carriers = [c for c in e if c.get("data-pptx-part") == "geometry"]
            direct_texts = [c for c in e if _tag(c) == "text"]
            if _tag(e) != "g" or semantic != "shape" or len(carriers) != 1 or _tag(carriers[0]) not in GEOMETRY:
                fail("invalid_shape_geometry", e, "Shape needs a semantic group with exactly one direct geometry carrier")
            if len(direct_texts) != 1 or texts != direct_texts:
                fail("fragmented_shape_text", e, "Shape needs exactly one direct text component and no nested loose text")
            elif direct_texts:
                record["shape_content"] = _svg_text(direct_texts[0])
            if not _frame(e.get("data-pptx-frame")):
                fail("invalid_shape_frame", e, "Shape owner needs finite x y width height with positive dimensions")
            extras = [c for c in e if _tag(c) not in {"metadata", "title", "desc", "text"} and c not in carriers]
            if extras:
                fail("extra_shape_components", e, "Additional visible shape components would not share the native owner")
        if listing:
            if len(texts) != 1 or (texts and texts[0] is not e and texts[0] not in list(e)):
                fail("fragmented_list", e, "List needs one direct text frame")
            else:
                text = texts[0]
                try:
                    height = float(text.get("data-paragraph-line-height", "nan"))
                    if not math.isfinite(height) or height <= 0:
                        raise ValueError()
                except ValueError:
                    fail("invalid_list_spacing", e, "List needs positive finite data-paragraph-line-height")
                paragraphs = [c for c in text if _tag(c) == "tspan" and "".join(c.itertext()).strip()]
                if not paragraphs or (text.text or "").strip() or any((c.tail or "").strip() for c in text):
                    fail("invalid_list_paragraphs", e, "List content must reside in paragraph tspans")
                items: list[str] = []
                for paragraph in paragraphs:
                    value = "".join(paragraph.itertext()).lstrip()
                    continuation = paragraph.get("data-paragraph-soft-break") == "1"
                    if paragraph.get("data-paragraph-line-break") == "1":
                        fail("invalid_list_paragraphs", e, "List wrapping uses soft-break continuation tspans")
                    if continuation:
                        if not items:
                            fail("invalid_list_paragraphs", e, "First list tspan cannot be a continuation")
                        elif value and value[0] in "·•●▪■◆◇◦‣":
                            fail("invalid_list_paragraphs", e, "A continuation cannot introduce another bullet")
                        else:
                            items[-1] = _join_wrap(items[-1], value)
                    elif len(value) < 2 or value[0] not in "·•●▪■◆◇◦‣" or not value[1:].strip():
                        fail("invalid_list_bullets", e, "Each declared list item needs a supported leading bullet and content")
                    else:
                        items.append(value[1:].strip())
                record["paragraphs"] = len(items)
                record["text"] = text
                record["content"] = [_normalize(item) for item in items]
        if table:
            if _tag(e) != "g" or e.get("data-pptx-replace-with") != "table":
                fail("missing_table_marker", e, "Declared table requires data-pptx-replace-with=table on its group")
            try:
                payload, rows, columns, cells = _table_payload(e)
                record.update(payload=payload, rows=rows, columns=columns, cells=cells)
            except (ValueError, TypeError, RuntimeError, KeyError, AttributeError, ImportError) as exc:
                fail("invalid_table_payload", e, str(exc))
        name_source = record.get("text", e) if listing and not shape else e
        name = (record.get("payload", {}).get("name") or e.get("id")) if table else (
            name_source.get("data-pptx-shape-name") or name_source.get("data-name") or name_source.get("id")
        )
        if pptx is not None and not name:
            fail("missing_owner_name", e, "Native verification needs a stable exported object name")
        if name and name in names:
            fail("duplicate_owner_name", e, f"Duplicate native object name: {name}")
        if name:
            names.add(name)
        record["name"] = name
        if len(findings) == before:
            expected.append(record)

    if pptx is None:
        return result
    try:
        with zipfile.ZipFile(pptx) as package:
            slides = [n for n in package.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml") and "/_rels/" not in n]
            if len(slides) != 1:
                raise ValueError("Native audit requires exactly one slide for exact SVG ownership")
            slide = ET.fromstring(package.read(slides[0]))
        owners: dict[str, list[ET.Element]] = {}
        for owner in slide.iter():
            if owner.tag not in {P + "sp", P + "graphicFrame", P + "pic", P + "cxnSp", P + "grpSp"}:
                continue
            props = next((c for c in owner if _tag(c).startswith("nv")), None)
            nv = props.find(P + "cNvPr") if props is not None else None
            if nv is not None:
                owners.setdefault(nv.get("name", ""), []).append(owner)
        for record in expected:
            e = record["element"]
            matches = owners.get(record["name"], [])
            if len(matches) != 1:
                fail("native_owner_mismatch", e, f"Expected one exact native owner {record['name']!r}; found {len(matches)}")
                continue
            owner = matches[0]
            before = len(findings)
            if record["kind"] == "table":
                tables = owner.findall(".//" + A + "tbl")
                if owner.tag != P + "graphicFrame" or len(tables) != 1:
                    fail("native_table_mismatch", e, "Declared table did not export to one real a:tbl graphicFrame")
                elif len(tables[0].findall(A + "tr")) != record["rows"] or len(tables[0].findall(A + "tblGrid/" + A + "gridCol")) != record["columns"]:
                    fail("native_table_grid_mismatch", e, "Native table dimensions differ from declared payload")
                else:
                    cells = []
                    for row in tables[0].findall(A + "tr"):
                        contents = []
                        for cell in row.findall(A + "tc"):
                            body = cell.find(A + "txBody")
                            contents.append(_native_text(body) if body is not None else "")
                        cells.append(contents)
                    if cells != record["cells"]:
                        fail("native_table_content_mismatch", e, "Native cell text differs from the validated payload grid")
            else:
                bodies = owner.findall(P + "txBody")
                if owner.tag != P + "sp" or len(bodies) != 1:
                    fail("native_shape_mismatch", e, "Text and geometry must share one p:sp with one p:txBody")
                elif not any((t.text or "").strip() for t in bodies[0].iter(A + "t")):
                    fail("native_empty_text", e, "Native owner text body has no editable text content")
                else:
                    if record["shape"]:
                        geometry = owner.find(P + "spPr")
                        shape_props = owner.find(P + "nvSpPr/" + P + "cNvSpPr")
                        if (shape_props is None or shape_props.get("txBox") in {"1", "true"}
                                or geometry is None or not any(c.tag in {A + "prstGeom", A + "custGeom"} for c in geometry)):
                            fail("native_shape_geometry_mismatch", e, "Semantic shape owner must carry preset/custom geometry and must not be a textbox")
                        if not record["kind"] == "list" and _native_text(bodies[0]) != record["shape_content"]:
                            fail("native_shape_content_mismatch", e, "Native shape text differs from normalized source content")
                if owner.tag == P + "sp" and len(bodies) == 1 and record["kind"] == "list":
                    paragraphs = bodies[0].findall(A + "p")
                    contents = [_native_paragraph_text(p) for p in paragraphs]
                    if len(paragraphs) != record["paragraphs"] or any(p.find(A + "pPr/" + A + "buChar") is None for p in paragraphs) or contents != record["content"]:
                        fail("native_list_mismatch", e, "List needs matching native paragraphs with editable bullets in one frame")
            if len(findings) == before:
                counts["pptx_objects_verified"] += 1
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as exc:
        fail("invalid_pptx", None, str(exc))
    return result


def main(argv: list[str] | None = None) -> int:
    """Write bounded ownership evidence for one source SVG and optional exported slide."""
    scripts = str(Path(__file__).resolve().parents[2])
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from console_encoding import configure_utf8_stdio
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--pptx", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if any(args.out.resolve() == path.resolve() for path in (args.svg, args.pptx) if path):
        parser.error("Output must not replace an input")
    result = audit(args.svg, args.pptx)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "counts": result["counts"], "out": str(args.out)}))
    return 0 if result["status"] == "passed" else 4


if __name__ == "__main__":
    raise SystemExit(main())
