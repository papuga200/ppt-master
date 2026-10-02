#!/usr/bin/env python3
"""Guard timeline chart allocation inside the immutable whole-page body.

Usage: python -m unittest tests.test_g6_chart_bounds
Examples: run from scripts with the repository Python environment.
Dependencies: standard library and repository timeline dependencies.
"""

import copy
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS / "exp_svg"))

import guided_build  # noqa: E402
import capacity_preflight  # noqa: E402


class ChartBoundsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.fixture = self.workspace / "inputs" / "fixture"
        template = self.fixture / "template" / "content.svg"
        template.parent.mkdir(parents=True)
        template.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
            '<g id="chrome"></g></svg>', encoding="utf-8",
        )
        self.body = {"x": 60, "y": 150, "w": 1160, "h": 460}
        self.canvas = {
            "body_zone": self.body, "type_floors": {"label_px_min": 14},
            "native_editability_required": True,
            "layout_constraints": {"labelled_bar_padding_y_min_px": 8},
        }
        self.request = {
            "page": {"template": str(template), "body": copy.deepcopy(self.body)},
            "calendar": {"start": "2026-01-01", "horizon_weeks": 4},
            "lanes": [{"id": "delivery", "name": "Delivery"}],
            "tasks": [{"id": "ship", "name": "Ship", "lane": "delivery", "weeks": [1, 4]}],
            "bounds": {"x": 80, "y": 200, "w": 1000, "h": 350},
        }

    def normalize(self, request=None):
        return guided_build.normalized(
            self.request if request is None else request, self.canvas, "timeline", self.fixture,
        )

    def test_subset_and_full_body_preserve_request_and_guards(self):
        for bounds in (self.request["bounds"], self.body):
            with self.subTest(bounds=bounds):
                self.request["bounds"] = copy.deepcopy(bounds)
                original = copy.deepcopy(self.request)
                value = self.normalize()
                self.assertEqual(value["bounds"], bounds)
                self.assertEqual(value["page"]["body"], self.body)
                self.assertEqual(value["tasks"], original["tasks"])
                self.assertEqual(value["floors"]["label_px"], 14)
                self.assertEqual(value["style"]["bar_pad_y_min"], 8)
                self.assertTrue(value["style"]["native_text_ownership"])
                self.assertEqual(self.request, original)
                self.assertEqual(capacity_preflight.timeline(value)["status"], "ok")

    def test_omitted_null_and_auto_continue_to_use_body(self):
        for mode in ("omitted", None, "auto"):
            with self.subTest(mode=mode):
                request = copy.deepcopy(self.request)
                if mode == "omitted":
                    del request["bounds"]
                else:
                    request["bounds"] = mode
                original = copy.deepcopy(request)
                value = self.normalize(request)
                self.assertEqual(value.get("bounds"), original.get("bounds"))
                receipt = capacity_preflight.timeline(value)
                self.assertEqual(receipt["status"], "ok")
                self.assertEqual(receipt["body"], self.body)
                self.assertEqual(request, original)

    def test_malformed_bounds_fail_with_actionable_errors(self):
        for bounds in ({}, [], "body", False, 1, {"x": 80, "y": 200, "w": 1000}):
            with self.subTest(bounds=bounds):
                self.request["bounds"] = bounds
                with self.assertRaisesRegex(ValueError, "bounds"):
                    self.normalize()

    def test_nonfinite_boolean_and_nonnumeric_coordinates_fail(self):
        for key in ("x", "y", "w", "h"):
            for value in (True, False, None, "80", float("nan"), float("inf"), -float("inf"), 10**400):
                with self.subTest(key=key, value=value):
                    request = copy.deepcopy(self.request)
                    request["bounds"][key] = value
                    with self.assertRaisesRegex(ValueError, "bounds." + key):
                        self.normalize(request)

    def test_nonpositive_and_outside_body_fail(self):
        changes = (
            {"w": 0}, {"h": 0}, {"w": -1}, {"h": -1},
            {"x": -1}, {"y": -1}, {"x": 59}, {"y": 149},
            {"w": 1141}, {"h": 411},
        )
        for change in changes:
            with self.subTest(change=change):
                request = copy.deepcopy(self.request)
                request["bounds"].update(change)
                with self.assertRaisesRegex(ValueError, "bounds"):
                    self.normalize(request)

    def test_chart_subset_does_not_allow_page_body_override_or_fit(self):
        for body in (self.request["bounds"], {**self.body, "fit": "between_texts"}):
            with self.subTest(body=body):
                request = copy.deepcopy(self.request)
                request["page"]["body"] = body
                with self.assertRaisesRegex(ValueError, "page.body must exactly match"):
                    self.normalize(request)

    def test_guided_cli_rejects_before_svg_subprocess(self):
        self.request["bounds"]["w"] = 2000
        canvas_path = self.fixture / "canvas.json"
        canvas_path.write_text(json.dumps(self.canvas), encoding="utf-8")
        request_path = self.workspace / "request.json"
        request_path.write_text(json.dumps(self.request), encoding="utf-8")
        output = self.workspace / "work" / "result.json"
        page = self.workspace / "slide.svg"
        arguments = ["guided_build.py", "--family", "timeline", "--in", str(request_path),
                     "--out", str(output), "--page", str(page)]
        with patch.dict(os.environ, PPT_MASTER_PROJECT_PATH=str(self.workspace)), \
                patch.object(sys, "argv", arguments), \
                patch.object(guided_build.subprocess, "call") as child:
            self.assertEqual(guided_build.main(), 2)
        child.assert_not_called()
        self.assertFalse(page.exists())
        self.assertFalse(output.with_suffix(".request.json").exists())
        receipt = json.loads(output.with_suffix(".contract.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "contract_failure")
        self.assertIn("inside immutable page.body", receipt["error"])

    def test_preflight_cli_reports_bad_bounds_before_measuring(self):
        self.request["bounds"] = []
        (self.fixture / "canvas.json").write_text(json.dumps(self.canvas), encoding="utf-8")
        request_path = self.workspace / "request.json"
        request_path.write_text(json.dumps(self.request), encoding="utf-8")
        output = self.workspace / "work" / "capacity.json"
        arguments = ["capacity_preflight.py", "--family", "timeline", "--in", str(request_path),
                     "--out", str(output)]
        with patch.dict(os.environ, PPT_MASTER_PROJECT_PATH=str(self.workspace)), \
                patch.object(sys, "argv", arguments), \
                patch.object(capacity_preflight, "timeline") as evaluate:
            self.assertEqual(capacity_preflight.main(), 2)
        evaluate.assert_not_called()
        receipt = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "request_error")
        self.assertIn("bounds must be an object", receipt["error"])
