#!/usr/bin/env python3
"""Exercise measurement contracts with real fonts and preserved node geometry.

Run: python -m unittest tests.test_g5_measurement_contracts
Dependencies: Pillow; Segoe UI for the historical DB reproduction.
"""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
for directory in (SCRIPTS, SCRIPTS / "exp_svg", SCRIPTS / "exp_svg" / "arch"):
    sys.path.insert(0, str(directory))

import guided_measure
import measure_labels as measure
import scene
from _common import HelperError


class MeasurementContractsTests(unittest.TestCase):
    font = {"family": "Segoe UI", "files": {"normal": "C:/Windows/Fonts/segoeui.ttf",
                                          "bold": "C:/Windows/Fonts/segoeuib.ttf"}}

    def label(self, **kwargs):
        return {"id": "DB", "text": "Primary timetable DB", "size_px": 14,
                "weight": "bold", "role": "label", **kwargs}

    def test_invalid_widths_conflicts_pitch_roles_and_verify(self):
        # Validation occurs before font access and cannot silently remove a constraint.
        for key in ("max_width", "max_w", "line_pitch", "line_pitch_px"):
            for bad in (0, -1, float("nan"), float("inf"), True, "124", None):
                with self.subTest(key=key, bad=bad), self.assertRaises(HelperError):
                    measure.validate_guided_request({"labels": [self.label(**{key: bad})]})
        for kwargs in ({"max_width": 124, "max_w": 125},
                       {"line_pitch": 1.3, "line_pitch_px": 25}, {"line_pitch": 18.2},
                       {"role": "typo"}, {"role": ""}):
            with self.subTest(kwargs=kwargs), self.assertRaises(HelperError):
                measure.measure_label(self.label(**kwargs), self.font)
        for verify in ("Browser", "off", "", None, True):
            with self.subTest(verify=verify), self.assertRaises(HelperError):
                measure.measure_request({"verify": verify, "labels": [self.label()]})

    def test_guided_unknown_fields_report_pointer(self):
        for extra, pointer in (({"max_width_px": 120}, "/labels/0/max_width_px"),
                               ({"line_pich_px": 18}, "/labels/0/line_pich_px")):
            with self.assertRaisesRegex(HelperError, pointer):
                measure.validate_guided_request({"labels": [self.label(**extra)]})
        with self.assertRaisesRegex(HelperError, "/verfy"):
            measure.validate_guided_request({"labels": [self.label()], "verfy": "browser"})

    @unittest.skipUnless(Path("C:/Windows/Fonts/segoeuib.ttf").is_file(), "historical Segoe UI font unavailable")
    def test_alias_reproduces_correct_db_wrap_without_input_mutation(self):
        original = {"font": self.font, "verify": "none", "labels": [self.label(max_w=124)]}
        before = copy.deepcopy(original)
        got, residuals = measure.measure_request(original)
        self.assertEqual(original, before)
        db = got[0]
        self.assertEqual(db["lines"], ["Primary timetable", "DB"])
        self.assertAlmostEqual(db["width_px"], 118.79, places=2)
        self.assertEqual(db["height_px"], 35.0)
        self.assertEqual(db["warnings"][0]["canonical_field"], "max_width")
        canonical = measure.measure_label(self.label(max_width=124), self.font)
        self.assertEqual(db["lines"], canonical["lines"])
        self.assertEqual(db["line_widths_px"], canonical["line_widths_px"])
        self.assertFalse(canonical["warnings"])
        self.assertEqual(residuals, [])
        unwrapped = measure.measure_label(self.label(), self.font)
        self.assertEqual(len(unwrapped["lines"]), 1)
        self.assertAlmostEqual(unwrapped["width_px"], 141.98, places=2)

    @unittest.skipUnless(Path("C:/Windows/Fonts/segoeuib.ttf").is_file(), "Segoe UI font unavailable")
    def test_pixel_pitch_extents_and_provenance_survive_summary(self):
        got = measure.measure_label(self.label(max_width=124, line_pitch_px=21), self.font)
        self.assertEqual(got["height_px"], 37.8)
        self.assertEqual(got["text_band_height_px"], 37.8)
        self.assertEqual(got["layout_height_px"], 42)
        same = measure.measure_label(self.label(max_width=124, line_pitch=1.5, line_pitch_px=21), self.font)
        self.assertEqual(same["height_px"], got["height_px"])
        summary = guided_measure.label_summary(got)
        self.assertEqual(summary["line_pitch_px"], 21)
        self.assertEqual(summary["font"]["source"], "explicit_file")
        self.assertEqual(summary["font"]["backend"], "freetype_advances")
        self.assertEqual(summary["measurement"], "approximate")
        self.assertEqual(summary["verification"]["status"], "not_requested")
        with patch.object(measure, "browser_widths", return_value=[
                {"width": width, "font_present": True} for width in got["line_widths_px"]]):
            self.assertEqual(measure.verify_in_browser([got]), [])
        summary = guided_measure.label_summary(got)
        self.assertEqual(summary["measurement"], "browser_verified")
        self.assertEqual(summary["verification"]["status"], "verified")
        self.assertIn("browser_line_widths_px", summary)

    @unittest.skipUnless(Path("C:/Windows/Fonts/segoeuib.ttf").is_file(), "Segoe UI font unavailable")
    def test_node_inner_outer_budgets_and_legacy_frame_geometry(self):
        sc = {"font": self.font, "type": {"node_px": 14, "sub_px": 13.333}}
        legacy = {"id": "DB", "label": "Primary timetable DB", "max_w": 148,
                  "box": {"x": 20, "y": 30}}
        explicit = {"id": "DB", "label": legacy["label"], "wrap_width_px": 124,
                    "box": {"x": 20, "y": 30}}
        scene.size_node(sc, legacy)
        scene.size_node(sc, explicit)
        self.assertEqual(legacy["box"], {"x": 20, "y": 30, "w": 142.79, "h": 52.4})
        self.assertEqual(explicit["box"], legacy["box"])
        self.assertEqual(explicit["measure"]["title_lines"], ["Primary timetable", "DB"])
        self.assertEqual(explicit["measure"]["text_wrap_width_px"], 124)
        self.assertEqual(explicit["measure"]["title_text_band_height_px"], 35.0)
        self.assertEqual(explicit["measure"]["layout_height_px"], 36.4)
        self.assertEqual(explicit["measure"]["frame_height_px"], 52.4)
        self.assertEqual(explicit["measure"]["padding_x_px"], 12)
        self.assertEqual(explicit["measure"]["inner_width_px"], 118.79)
        for node in ({"id": "DB", "label": legacy["label"]},
                     {"id": "DB", "label": legacy["label"], "wrap_width_px": 148}):
            scene.size_node(sc, node)
            self.assertEqual(len(node["measure"]["title_lines"]), 1)
            self.assertEqual(node["box"]["h"], 34.2)
            self.assertEqual(node["box"]["w"], 165.98)
        with self.assertRaises(HelperError):
            scene.size_node(sc, {"id": "DB", "max_w": 148, "wrap_width_px": 124})

    @unittest.skipUnless(Path("C:/Windows/Fonts/segoeuib.ttf").is_file(), "Segoe UI font unavailable")
    def test_oversized_word_and_minimum_frame_are_honest(self):
        sc = {"font": self.font, "type": {"node_px": 14, "sub_px": 13.333}}
        node = {"id": "N", "label": "UnbreakableDatastoreName", "wrap_width_px": 40, "min_h": 70}
        scene.size_node(sc, node)
        got = node["measure"]
        self.assertTrue(got["oversized_words"])
        self.assertGreater(got["inner_width_px"], got["text_wrap_width_px"])
        self.assertEqual(got["frame_height_px"], 70)
        self.assertEqual(got["inner_height_px"], 54)
