#!/usr/bin/env python3
"""Whole-page source evaluation shares writer geometry without emitting SVG.

Usage: python -m unittest tests.test_arch_source_evaluation
Examples: run from scripts with the repository Python environment.
Dependencies: repository architecture helper dependencies.
"""

import copy
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
for directory in (SCRIPTS, SCRIPTS / "exp_svg", SCRIPTS / "exp_svg" / "arch"):
    sys.path.insert(0, str(directory))

import compose_page as cp  # noqa: E402
import capacity_preflight as preflight  # noqa: E402


def candidate(directory):
    template = directory / "template.svg"
    template.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
        '<g id="chrome"></g></svg>', encoding="utf-8",
    )
    return {
        "page": {"template": str(template), "body": {"x": 64, "y": 208, "w": 1152, "h": 440}},
        "font": {"family": "Segoe UI"},
        "root": {"layout": {"rows": [["a", "trunk", "b"]], "gap_x": 140}},
        "nodes": [{"id": "a", "label": "Source", "sublabel": "Local records"},
                  {"id": "b", "label": "Target"}],
        "buses": [{"id": "trunk"}],
        "edges": [{"id": "ab", "source": "a", "target": "b", "label": "Call"},
                  {"id": "in", "source": "a", "target": "trunk", "label": "Upload"},
                  {"id": "out", "source": "trunk", "target": "b", "label": "Pull"}],
        "density_ladder": True,
    }


class ArchitectureSourceEvaluationTests(unittest.TestCase):
    def test_no_render_write_or_request_mutation(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request = candidate(directory)
            original = copy.deepcopy(request)
            before = set(directory.iterdir())
            with patch.object(cp.sc, "render_group", side_effect=AssertionError("render")), \
                    patch.object(cp.sc, "render_svg", side_effect=AssertionError("render")), \
                    patch.object(cp.page_compose, "assemble", side_effect=AssertionError("serialize")), \
                    patch.object(Path, "write_text", side_effect=AssertionError("write")):
                evaluated = cp.evaluate(request)
                receipt = preflight.architecture(request)
            self.assertEqual(request, original)
            self.assertEqual(set(directory.iterdir()), before)
            self.assertTrue(receipt["coverage"]["routing_checked"])
            geometry = evaluated["result"]
            self.assertIn("ab", geometry["routes"])
            self.assertIn("a:title", geometry["label_boxes"])
            self.assertIn("in", geometry["buses"]["trunk"]["flows"])
            self.assertIsNotNone(geometry["buses"]["trunk"]["flows"]["in"]["label"]["box"])
            self.assertNotIn("<svg", json.dumps(evaluated))
            self.assertNotIn("path", geometry["page"])

    def test_writer_and_evaluator_geometry_equal_for_roots_buses_and_failure(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for fail in (False, True):
                with self.subTest(fail=fail):
                    request = candidate(directory)
                    if fail:
                        request["page"]["body"]["w"] = 120
                    evaluated = cp.evaluate(request)
                    page = directory / f"written-{fail}.svg"
                    writer = cp._work(request, SimpleNamespace(page=str(page), svg=None, evaluate_only=False))
                    summary = writer[1]
                    summary["page"].pop("path")
                    self.assertEqual(summary, evaluated["result"])
                    self.assertEqual(writer[2], evaluated["residual_constraints"])
                    self.assertEqual(writer[4]["scene_sha256"], evaluated["scene_sha256"])
                    self.assertTrue(page.is_file())
                    if fail:
                        self.assertFalse(evaluated["capacity_fit"])
                        self.assertFalse(evaluated["ready"])

    def test_captured_frame_failures_are_reported_before_svg(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request = candidate(directory)
            request.pop("root")
            request.pop("buses")
            request["edges"] = []
            request["zones"] = [
                {"id": "H1", "frame": {"x": 84, "y": 408, "w": 824, "h": 76}, "pad": 12},
            ]
            request["nodes"] = [
                {"id": "REG", "label": "Study registry", "at": {"x": 328, "y": 304},
                 "min_w": 128, "min_h": 44, "max_w": 108},
                {"id": "IDP", "label": "Research identity", "at": {"x": 400, "y": 352},
                 "min_w": 148, "min_h": 44, "max_w": 128},
                {"id": "NG", "label": "North disclosure gate", "zone": "H1",
                 "at": {"x": 720, "y": 432}, "min_w": 176, "min_h": 44, "max_w": 156},
            ]
            receipt = preflight.architecture(request)
            self.assertTrue(receipt["capacity_fit"])
            self.assertFalse(receipt["ready"])
            self.assertEqual(receipt["status"], "partial")
            conflicts = receipt["unsatisfied_constraints"]
            self.assertTrue(any(r["kind"] == "node_overlap" and set(r["ids"]) == {"REG", "IDP"}
                                for r in conflicts))
            self.assertTrue(any(r["kind"] in ("containment_violation", "zone_padding")
                                and r.get("id") == "NG" for r in conflicts))
            writer = cp._work(request, SimpleNamespace(page=str(directory / "failed.svg"), svg=None))
            summary = writer[1]
            summary["page"].pop("path")
            self.assertEqual(summary, receipt["geometry"])

    def test_raw_extensions_have_incomplete_coverage(self):
        with TemporaryDirectory() as temporary:
            request = candidate(Path(temporary))
            request["page"]["extra_svg"] = '<rect x="100" y="200" width="20" height="20"/>'
            receipt = preflight.architecture(request)
            self.assertFalse(receipt["coverage"]["complete"])
            self.assertFalse(receipt["ready"])
            self.assertEqual(receipt["coverage"]["exclusions"][0]["field"], "page.extra_svg")
            self.assertNotEqual(receipt["status"], "capacity_fit")

    def test_evaluation_cli_forbids_svg_outputs(self):
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            request = candidate(directory)
            for page, svg in (("slide.svg", None), (None, "preview.svg")):
                with self.subTest(page=page, svg=svg), self.assertRaisesRegex(cp.HelperError, "forbids"):
                    cp._work(request, SimpleNamespace(evaluate_only=True, page=page, svg=svg))
            evaluated = cp._work(request, SimpleNamespace(evaluate_only=True, page=None, svg=None))
            self.assertIn("ready", evaluated[4])
