#!/usr/bin/env python3
"""Timeline labelled-bar padding constraints and capacity regressions.

Usage: python -m unittest tests.test_exp_timeline_padding_floor
Examples: run from scripts with the repository Python environment.
Dependencies: repository timeline converter dependencies.
"""

import copy
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

SCRIPTS = Path(__file__).resolve().parents[1]
for directory in (SCRIPTS, SCRIPTS / "exp_svg", SCRIPTS / "exp_svg" / "timeline"):
    sys.path.insert(0, str(directory))

from build_timeline import build  # noqa: E402
from dense_build import normalise  # noqa: E402
from guided_build import normalized  # noqa: E402
from capacity_preflight import timeline  # noqa: E402


def candidate():
    return {
        "calendar": {"start": "2026-01-01", "horizon_weeks": 4},
        "lanes": [{"id": f"l{i}", "name": f"Lane {i}"} for i in range(8)],
        "tasks": [
            {"id": f"t{i}", "name": f"Task {i}", "lane": f"l{i}", "weeks": [1, 4]}
            for i in range(8)
        ],
        "style": {"header": "compact", "label_px": 14, "bar_pad_y": 8},
        "floors": {"label_px": 14},
        "bounds": {"x": 60, "y": 150, "w": 1160, "h": 280},
    }


class TimelinePaddingFloorTests(unittest.TestCase):
    def test_capacity_failure_at_floor_retains_legacy_fit_without_floor(self):
        request = candidate()
        old = build(request)
        self.assertEqual(old["status"], "ok")
        self.assertLess(old["capacity"]["density"]["bar_pad_y"], 8)
        request["style"]["bar_pad_y_min"] = 8
        constrained = build(request)
        self.assertEqual(constrained["status"], "capacity_failure")
        self.assertEqual(constrained["capacity"]["density"]["bar_pad_y"], 8)
        self.assertGreater(constrained["capacity"]["needs_h"], 280)
        self.assertTrue(constrained["capacity"]["binding"])
        self.assertEqual(len(constrained["scene"]["tasks"]), 8)

    def test_lower_requested_padding_raised_with_receipt(self):
        request = candidate()
        request["style"].update(bar_pad_y=2, bar_pad_y_min=8)
        spec, errors, notes = normalise(request)
        self.assertEqual(errors, [])
        self.assertEqual(spec["bar_pad_y"], 8)
        self.assertEqual(spec["bar_pad_y_min"], 8)
        self.assertTrue(any("style.bar_pad_y 2 px raised" in n["detail"] for n in notes))
        request["bounds"]["h"] = 400
        built = build(request)
        self.assertEqual(built["status"], "ok")
        self.assertGreaterEqual(built["scene"]["density"]["bar_pad_y"], 8)

    def test_invalid_floors_are_request_errors(self):
        for floor in (-1, True, None, "8", float("nan"), float("inf")):
            with self.subTest(floor=floor):
                request = candidate()
                request["style"]["bar_pad_y_min"] = floor
                built = build(request)
                self.assertEqual(built["status"], "error")
                self.assertTrue(any("bar_pad_y_min" in e for e in built["errors"]))

    def test_thin_bars_remain_visible_with_external_labels(self):
        request = candidate()
        request["style"].update(bar_mode="thin", bar_h_thin=8, bar_pad_y=2)
        legacy = build(request)
        request["style"]["bar_pad_y_min"] = 8
        constrained = build(request)
        self.assertEqual(constrained["status"], legacy["status"])
        self.assertEqual(constrained["scene"], legacy["scene"])
        self.assertEqual(constrained["scene"]["density"]["bar_h"], 8)
        for task in constrained["scene"]["tasks"]:
            self.assertNotEqual(task["label"]["where"], "inside")

    def test_immutable_floor_applies_to_capacity_and_not_native_flag_alone(self):
        with TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            template = fixture / "template" / "content.svg"
            template.parent.mkdir()
            template.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720">'
                '<g id="chrome"></g></svg>', encoding="utf-8",
            )
            request = candidate()
            request["page"] = {"template": str(template), "body": copy.deepcopy(request["bounds"])}
            canvas = {"body_zone": request["bounds"], "type_floors": {"label_px_min": 14},
                      "native_editability_required": True}
            legacy = normalized(request, canvas, "timeline", fixture)
            self.assertNotIn("bar_pad_y_min", legacy["style"])
            self.assertEqual(timeline(legacy)["status"], "ok")
            canvas["layout_constraints"] = {"labelled_bar_padding_y_min_px": 8}
            request["style"]["bar_pad_y_min"] = 1
            guarded = normalized(request, canvas, "timeline", fixture)
            self.assertEqual(guarded["style"]["bar_pad_y_min"], 8)
            receipt = timeline(guarded)
            self.assertEqual(receipt["status"], "capacity_failure")
            self.assertEqual(receipt["capacity"]["density"]["bar_pad_y"], 8)
            request["style"].update(bar_mode="thin", bar_h_thin=8)
            thin = normalized(request, canvas, "timeline", fixture)
            self.assertEqual(thin["style"]["bar_pad_y_min"], 1)
            for floor in (-1, True, "8", float("nan")):
                canvas["layout_constraints"]["labelled_bar_padding_y_min_px"] = floor
                with self.subTest(floor=floor), self.assertRaisesRegex(ValueError, "layout_constraints"):
                    normalized(request, canvas, "timeline", fixture)
