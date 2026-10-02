#!/usr/bin/env python3
"""PPT Master - fixed timeline note-card contract regressions.

Usage: python -m unittest tests.test_g6_note_cards
Examples: run from scripts with the repository Python environment.
Dependencies: repository converter dependencies; font measurement is mocked.
"""

import copy
import json
import sys
import textwrap
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
for directory in (SCRIPTS, SCRIPTS / "exp_svg" / "timeline"):
    sys.path.insert(0, str(directory))

import prepare_note_cards as cards  # noqa: E402
from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes  # noqa: E402


def measurement(label, font):
    lines = textwrap.wrap(label["text"], width=40, break_long_words=False)
    return {"lines": lines, "line_widths_px": [len(line) * 8 for line in lines],
            "font": {"file": "mocked-real-font", "source": "mock"}, "oversized_words": []}


class NoteCardTests(unittest.TestCase):
    def setUp(self):
        self.request = {
            "page": {"body": {"x": 54, "y": 176, "w": 1172, "h": 492},
                     "note_cards": {"strip": {"x": 54, "y": 536, "w": 1172, "h": 132},
                                    "cards": [{"id": f"card-{i}", "heading": f"Heading {i}",
                                               "text": "Preserve this complete business requirement."}
                                              for i in range(3)]}},
            "bounds": {"x": 54, "y": 176, "w": 1172, "h": 342},
            "style": {"font_family": "Segoe UI"}, "floors": {"body_px": 16},
        }
        self.mock = patch.object(cards.measure_labels, "measure_label", measurement)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_success_preserves_caller_and_full_content_with_three_shapes(self):
        original = copy.deepcopy(self.request)
        prepared = cards.prepare(self.request)
        self.assertEqual(self.request, original)
        self.assertEqual(prepared["status"], "prepared")
        self.assertEqual(prepared["request"]["page"]["body"], original["page"]["body"])
        self.assertEqual(prepared["request"]["bounds"], original["bounds"])
        root = ET.fromstring("<svg>" + prepared["request"]["page"]["extra_svg"] + "</svg>")
        self.assertEqual(len(root), 3)
        for owner, source in zip(root, original["page"]["note_cards"]["cards"]):
            self.assertEqual(owner.get("data-pptx-semantic-object"), "shape")
            self.assertEqual(len(owner.findall("text")), 1)
            content = " ".join("".join(part.itertext()) for part in owner.find("text"))
            self.assertEqual(content, source["heading"] + " " + source["text"])

    def test_rejects_chart_overlap_and_outside_body(self):
        for change in ({"y": 500}, {"y": 660}, {"x": 53}, {"w": 1173}):
            with self.subTest(change=change):
                request = copy.deepcopy(self.request)
                request["page"]["note_cards"]["strip"].update(change)
                with self.assertRaises(ValueError):
                    cards.prepare(request)

    def test_rejects_overflow_without_truncation_or_font_shrink(self):
        self.request["page"]["note_cards"]["cards"][0]["text"] = "Required business condition. " * 30
        original = copy.deepcopy(self.request)
        with self.assertRaisesRegex(ValueError, "enlarge the strip"):
            cards.prepare(self.request)
        self.assertEqual(self.request, original)

    def test_rejects_duplicate_ids_and_existing_extra_svg(self):
        self.request["page"]["note_cards"]["cards"][1]["id"] = "card-0"
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            cards.prepare(self.request)
        self.request["page"]["extra_svg"] = "<rect/>"
        with self.assertRaisesRegex(ValueError, "not overwritten"):
            cards.prepare(self.request)

    def test_rejects_bad_geometry_and_wrong_card_count(self):
        for value in (True, float("nan"), float("inf"), "1172"):
            with self.subTest(value=value):
                request = copy.deepcopy(self.request)
                request["bounds"]["w"] = value
                with self.assertRaisesRegex(ValueError, "bounds.w"):
                    cards.prepare(request)
        self.request["page"]["note_cards"]["cards"].pop()
        with self.assertRaisesRegex(ValueError, "exactly three"):
            cards.prepare(self.request)

    def test_dy_paragraphs_export_to_three_shape_owned_text_bodies(self):
        prepared = cards.prepare(self.request)
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            svg = folder / "cards.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
                           'viewBox="0 0 1280 720" font-family="Segoe UI">'
                           + prepared["request"]["page"]["extra_svg"] + '</svg>', encoding="utf-8")
            result = convert_svg_to_slide_shapes(svg, resource_root=folder, text_flow="preserve")
            root = ET.fromstring(result[0])
            ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                  "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            owners = root.findall(".//p:sp", ns)
            self.assertEqual(len(owners), 3)
            for owner, original in zip(owners, self.request["page"]["note_cards"]["cards"]):
                self.assertIsNotNone(owner.find("p:spPr/a:prstGeom", ns))
                body = owner.find("p:txBody", ns)
                self.assertIsNotNone(body)
                content = " ".join(t.text or "" for t in body.findall(".//a:t", ns))
                self.assertEqual(content, original["heading"] + " " + original["text"])
                self.assertEqual(owner.find("p:nvSpPr/p:cNvPr", ns).get("name"), "note-" + original["id"])

    def test_cli_outputs_prepared_json_and_geometry_only(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source, output, receipt = (folder / name for name in ("source.json", "prepared.json", "cards.json"))
            source.write_text(json.dumps(self.request), encoding="utf-8")
            self.assertEqual(cards.main(["--in", str(source), "--out", str(output),
                                         "--receipt", str(receipt)]), 0)
            prepared = json.loads(output.read_text(encoding="utf-8"))
            evidence = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertIn("extra_svg", prepared["page"])
            self.assertNotIn("<svg", prepared["page"]["extra_svg"])
            self.assertNotIn("request", evidence)
            self.assertEqual(len(evidence["geometry"]), 3)
            self.assertEqual(sorted(p.suffix for p in folder.iterdir()), [".json"] * 3)
