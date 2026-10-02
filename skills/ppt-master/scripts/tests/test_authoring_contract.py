#!/usr/bin/env python3
"""Verify production authoring contracts project actual template geometry and lock floors.

Run: python -m unittest tests.test_authoring_contract
Dependencies: standard library and the canonical host helper.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT / "hosts" / "responses_api"))
from authoring_contract import prepare_contract  # noqa: E402


class AuthoringContractTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.project = Path(self.scratch.name)
        (self.project / "templates").mkdir()
        self.template = self.project / "templates" / "content.svg"
        self.template.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
            '<g id="sample"><rect id="body-zone" x="54" y="170" width="1172" height="450"/></g>'
            '</svg>', encoding="utf-8")
        self.lock = self.project / "spec_lock.md"
        self.lock.write_text("## canvas\n- viewBox: 0 0 1280 720\n"
            "## type_floor\n- body: 18\n- secondary: 15\n", encoding="utf-8")
        self.page = {"stem": "03_architecture", "layout": "content"}
        self.addCleanup(self.scratch.cleanup)

    def test_projects_authoritative_geometry_and_custom_floors(self):
        path, error = prepare_contract(self.project, self.page)
        self.assertFalse(error)
        contract = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(contract["body_zone"], {"x": 54, "y": 170, "w": 1172, "h": 450})
        self.assertEqual(contract["template"], str(self.template.resolve()))
        self.assertEqual(contract["type_floors"], {"body_px_min": 18, "label_px_min": 15,
                                                 "timeline_chart_label_px_min": 15})
        self.assertTrue(contract["native_editability_required"])
        self.assertTrue(contract["source_layout_preflight_required"])
        self.assertNotIn("first_draft_only", contract)
        stamp = path.stat().st_mtime_ns
        self.assertEqual(prepare_contract(self.project, self.page)[0].stat().st_mtime_ns, stamp)

    def test_missing_geometry_uses_ordinary_authoring_without_invented_contract(self):
        self.template.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        path, error = prepare_contract(self.project, self.page)
        self.assertIsNone(path)
        self.assertIn("No selected template body-zone", error)
        self.assertFalse((self.project / "analysis").exists())

    def test_nonstandard_canvas_does_not_invoke_fixed_canvas_creator(self):
        self.lock.write_text("## canvas\n- viewBox: 0 0 1080 1080\n", encoding="utf-8")
        path, error = prepare_contract(self.project, self.page)
        self.assertIsNone(path)
        self.assertIn("currently use 1280 x 720", error)
