#!/usr/bin/env python3
"""Regression checks for native visual wraps inside one paragraph.

Usage: python -m unittest tests.test_native_soft_break_preserve
Examples: run from the scripts directory with the repository Python environment.
Dependencies: repository converter dependencies.
"""

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes  # noqa: E402

NS = {
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
}


class NativeSoftBreakPreserveTests(unittest.TestCase):
    def test_visual_rows_keep_native_paragraph_ownership(self):
        for first, continuation in (("Collected", "locally"), ("本地", "采集")):
            for mode in ("preserve", "reflow"):
                with self.subTest(first=first, mode=mode), TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / "page.svg"
                    source.write_text(
                        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" '
                        'height="720" viewBox="0 0 1280 720">'
                        '<g id="node" data-pptx-shape-name="node" '
                        'data-pptx-semantic-object="shape" data-pptx-frame="10 10 180 100">'
                        '<rect x="10" y="10" width="180" height="100" '
                        'data-pptx-part="geometry" fill="#FFFFFF"/>'
                        '<text x="100" y="32" font-size="14" text-anchor="middle">'
                        '<tspan x="100" dy="0" font-weight="bold">Title</tspan>'
                        f'<tspan x="100" dy="28" fill="#5F5A53">{first}</tspan>'
                        '<tspan x="100" dy="20" fill="#5F5A53" '
                        f'data-paragraph-soft-break="1">{continuation}</tspan>'
                        '<tspan x="100" dy="20" data-paragraph-soft-break="0">End</tspan>'
                        '</text></g>'
                        '<text id="items" data-pptx-shape-name="items" x="220" y="40" '
                        'font-size="14" data-editable-kind="list" data-paragraph-line-height="20">'
                        f'<tspan x="220" dy="0">• {first}</tspan>'
                        '<tspan x="220" dy="20" data-paragraph-soft-break="1">'
                        f'{continuation}</tspan><tspan x="220" dy="20" '
                        'data-paragraph-soft-break="0">• Second</tspan></text>'
                        '<text id="edge" data-pptx-shape-name="edge" x="420" y="40" '
                        f'font-size="14"><tspan x="420" dy="0">{first}</tspan>'
                        '<tspan x="420" dy="20" data-paragraph-soft-break="1">'
                        f'{continuation}</tspan></text></svg>',
                        encoding="utf-8",
                    )
                    xml = convert_svg_to_slide_shapes(
                        source, resource_root=root, text_flow=mode,
                    )[0]
                    slide = ET.fromstring(xml)
                    shapes = slide.findall(".//p:sp", NS)
                    self.assertEqual(len(shapes), 3)
                    owners = {
                        shape.find("p:nvSpPr/p:cNvPr", NS).get("name"): shape
                        for shape in shapes
                    }
                    self.assertEqual(set(owners), {"node", "items", "edge"})
                    for name, paragraphs in (("node", 3), ("items", 2), ("edge", 1)):
                        body = owners[name].find("p:txBody", NS)
                        self.assertEqual(len(body.findall("a:p", NS)), paragraphs)
                        self.assertEqual(
                            len(body.findall(".//a:br", NS)), 1 if mode == "preserve" else 0,
                        )
                        self.assertEqual(
                            body.find("a:bodyPr", NS).get("wrap"),
                            "none" if mode == "preserve" else "square",
                        )
                        content = "".join(t.text or "" for t in body.findall(".//a:t", NS))
                        self.assertIn(first, content)
                        self.assertIn(continuation, content)
                        if mode == "reflow":
                            joined = first + (" " if first == "Collected" else "") + continuation
                            self.assertIn(joined, content)
                    node = owners["node"]
                    frame = node.find("p:spPr/a:xfrm/a:ext", NS)
                    self.assertEqual(frame.attrib, {"cx": str(180 * 9525), "cy": str(100 * 9525)})
                    body = node.find("p:txBody", NS)
                    self.assertIsNotNone(body.find("a:bodyPr/a:noAutofit", NS))
                    title_run = body.find("a:p/a:r/a:rPr", NS)
                    self.assertEqual(title_run.get("b"), "1")
                    colors = body.findall("a:p[2]/a:r/a:rPr/a:solidFill/a:srgbClr", NS)
                    self.assertTrue(colors)
                    self.assertTrue(all(color.get("val") == "5F5A53" for color in colors))
                    self.assertEqual(len(body.findall(".//a:buChar", NS)), 0)
                    list_body = owners["items"].find("p:txBody", NS)
                    self.assertEqual(len(list_body.findall("a:p/a:pPr/a:buChar", NS)), 2)
                    for paragraph in list_body.findall("a:p", NS):
                        self.assertEqual(len(paragraph.findall("a:pPr/a:buChar", NS)), 1)
