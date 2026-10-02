#!/usr/bin/env python3
"""
PPT Master - Architecture Group Space Regression Tests

Check the read-only capacity ledger on temporary full compose requests.

Usage:
    python3 -m unittest tests.test_arch_group_space_budget

Examples:
    python3 -m unittest tests.test_arch_group_space_budget

Dependencies:
    Pillow and standard library unittest
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
for _path in (SCRIPTS, SCRIPTS / "exp_svg" / "arch"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import measure_groups  # noqa: E402
import route_connections  # noqa: E402
from _common import HelperError  # noqa: E402


class GroupSpaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.template = self.folder / "template.svg"
        self.template.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
            'viewBox="0 0 1280 720"><g id="chrome"></g></svg>', encoding="utf-8")

    def request(self, label="Heading"):
        return {
            "page": {"template": str(self.template), "texts": [],
                     "body": {"x": 40, "y": 100, "w": 1200, "h": 590}},
            "font": {"family": "Arial"}, "type": {"zone_label_px": 14},
            "zones": [{"id": "g", "label": label, "pad": 12,
                       "frame": {"x": 40, "y": 100, "w": 400, "h": 90},
                       "layout": {"type": "rows", "rows": [["a"]]}}],
            "nodes": [{"id": "a", "zone": "g", "label": "Node", "sublabel": "Details"}],
        }

    def group(self, request, item_id="g"):
        return next(g for g in measure_groups.measure_groups(request)["groups"] if g["id"] == item_id)

    def test_one_line_heading_exposes_actual_shortfall(self):
        group = self.group(self.request())
        self.assertEqual(group["frame_source"], "supplied_fixed")
        self.assertEqual(group["inner"]["h"], 39.8)
        self.assertEqual(group["content"]["h"], 58.13)
        self.assertEqual(group["minimum_outer"]["h"], 108.33)
        self.assertEqual(group["deficit"]["h"], 18.33)
        self.assertEqual(group["culprit_child_ids"]["h"], ["a"])

    def test_wrapped_heading_consumes_another_line_band(self):
        request = self.request("First\nSecond")
        group = self.group(request)
        self.assertEqual(group["heading"]["lines"], ["First", "Second"])
        self.assertEqual(group["heading"]["h"], 36.4)
        self.assertEqual(group["inner"]["h"], 21.6)
        request["zones"][0]["label"] = "Alpha Beta Gamma Delta"
        request["zones"][0]["caption_max_w"] = 70
        group = self.group(request)
        self.assertGreater(len(group["heading"]["lines"]), 1)
        self.assertEqual(" ".join(group["heading"]["lines"]), "Alpha Beta Gamma Delta")

    def test_fixed_width_shortfall_names_the_overflowing_child(self):
        request = self.request("")
        request["nodes"][0]["min_w"] = 500
        group = self.group(request)
        self.assertEqual(group["inner"]["w"], 376)
        self.assertEqual(group["content"]["w"], 500)
        self.assertEqual(group["minimum_outer"]["w"], 524)
        self.assertEqual(group["deficit"]["w"], 124)
        self.assertEqual(group["culprit_child_ids"]["w"], ["a"])

    def test_empty_heading_has_no_caption_gap_and_zero_padding_is_preserved(self):
        request = self.request("")
        group = self.group(request)
        self.assertEqual(group["heading"]["gap"], 0)
        self.assertEqual(group["inner"]["h"], 66)
        request["zones"][0]["pad"] = 0
        request["caption_gap"] = 19
        group = self.group(request)
        self.assertEqual(group["inner"]["h"], 90)
        self.assertEqual(group["padding"]["top"], 0)
        self.assertEqual(group["heading"]["gap"], 0)

    def test_padding_and_caption_gap_overrides(self):
        request = self.request()
        request["zones"][0]["pad"] = 7
        request["caption_gap"] = 3
        group = self.group(request)
        self.assertEqual(group["inner"]["h"], 54.8)
        self.assertEqual(group["heading"]["gap"], 3)
        self.assertEqual(group["padding"], {"left": 7, "top": 7, "right": 7, "bottom": 7})

    def test_nested_content_sized_groups_and_root_keep_their_budgets(self):
        request = self.request()
        child = request["zones"][0]
        del child["frame"]
        child["parent"] = "outer"
        child["kind"] = "group"
        request["zones"].append({"id": "outer", "kind": "group", "pad": 9,
                                 "layout": {"type": "rows", "rows": [["g"]]}})
        request["root"] = {"layout": {"type": "rows", "rows": [["outer"]]}}
        groups = {g["id"]: g for g in measure_groups.measure_groups(request)["groups"]}
        self.assertEqual(groups["g"]["frame_source"], "content_sized")
        self.assertEqual(groups["g"]["heading"]["lines"], [])
        self.assertEqual(groups["outer"]["content"]["h"], groups["g"]["outer"]["h"])
        self.assertEqual(groups["outer"]["outer"]["h"], groups["g"]["outer"]["h"] + 18)
        self.assertEqual(groups["root"]["frame_source"], "page_body")
        self.assertTrue(all(g["deficit"] == {"w": 0, "h": 0} for g in groups.values()))

    def test_input_resources_are_unchanged_and_router_is_not_called(self):
        request = self.request()
        before = copy.deepcopy(request)
        template_before = self.template.read_bytes()
        with patch.object(route_connections, "route", side_effect=AssertionError("routing called")):
            first = measure_groups.measure_groups(request)
            self.assertEqual(first, measure_groups.measure_groups(request))
        self.assertEqual(request, before)
        self.assertEqual(self.template.read_bytes(), template_before)
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ["template.svg"])

    def test_cli_writes_only_utf8_ledger_and_preserves_request(self):
        request = self.request("Résumé")
        input_path, output_path = self.folder / "request.json", self.folder / "ledger.json"
        input_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        before = input_path.read_bytes()
        self.assertEqual(measure_groups.main(["--in", str(input_path), "--out", str(output_path)]), 0)
        self.assertEqual(input_path.read_bytes(), before)
        self.assertIn("Résumé", output_path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()),
                         ["ledger.json", "request.json", "template.svg"])
        self.assertEqual(measure_groups.main(["--in", str(input_path), "--out", str(input_path)]), 1)
        self.assertEqual(input_path.read_bytes(), before)

    def test_parent_cycle_fails_instead_of_hanging(self):
        request = self.request()
        request["zones"][0]["parent"] = "g"
        with self.assertRaisesRegex(HelperError, "cycle"):
            measure_groups.measure_groups(request)

    def test_wide_singleton_does_not_span_an_aligned_grid(self):
        request = self.request("")
        request["zones"][0]["frame"] = {"x": 40, "y": 100, "w": 500, "h": 500}
        request["zones"][0]["layout"] = {"type": "rows", "rows": [["a", "b"], ["wide"]],
                                         "align_columns": True, "gap_x": 32, "gap_y": 28}
        request["nodes"] = [
            {"id": "a", "zone": "g", "label": "A", "min_w": 220, "max_w": 220},
            {"id": "b", "zone": "g", "label": "B", "min_w": 220, "max_w": 220},
            {"id": "wide", "zone": "g", "label": "Wide note", "min_w": 472, "max_w": 472},
        ]
        before = copy.deepcopy(request)
        group = self.group(request)
        self.assertEqual(group["content"]["w"], 724)
        self.assertEqual(group["alignment_diagnostic"]["without_column_alignment"]["w"], 472)
        self.assertEqual(group["alignment_diagnostic"]["alignment_extra"]["w"], 252)
        self.assertEqual(request, before)
        request["zones"][0]["layout"]["align_columns"] = False
        row_group = self.group(request)
        self.assertEqual(row_group["content"]["w"], 472)
        self.assertIsNone(row_group["alignment_diagnostic"])

    def test_column_layout_reports_height_expansion_without_changing_geometry(self):
        request = self.request("")
        request["zones"][0]["frame"] = {"x": 40, "y": 100, "w": 600, "h": 590}
        request["zones"][0]["layout"] = {"type": "columns", "columns": [["a", "b"], ["tall"]],
                                         "align_columns": True, "gap_y": 28}
        request["nodes"] = [
            {"id": "a", "zone": "g", "label": "A", "min_w": 100, "max_w": 100},
            {"id": "b", "zone": "g", "label": "B", "min_w": 100, "max_w": 100},
            {"id": "tall", "zone": "g", "label": "Tall\n" * 5 + "end", "min_w": 100, "max_w": 100},
        ]
        group = self.group(request)
        diagnostic = group["alignment_diagnostic"]
        self.assertGreater(diagnostic["alignment_extra"]["h"], 0)
        self.assertEqual(diagnostic["alignment_extra"]["w"], 0)
        self.assertGreater(group["content"]["h"], diagnostic["without_column_alignment"]["h"])
