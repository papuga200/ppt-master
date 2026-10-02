#!/usr/bin/env python3
"""PPT Master - Declared Architecture Peer Sizing Tests

Check measured peer heights, preserved widths and cross-parent wrap stabilization.

Usage:
    python3 -m unittest tests.test_arch_peer_sets

Examples:
    python3 -m unittest tests.test_arch_peer_sets

Dependencies:
    Pillow and standard library unittest
"""

import copy
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS / "exp_svg" / "arch"))

import arrange  # noqa: E402
import scene as sc  # noqa: E402
from _common import HelperError  # noqa: E402


class PeerSetsTests(unittest.TestCase):
    def request(self):
        return {
            "font": {"family": "Segoe UI"},
            "nodes": [{"id": "a", "label": "A", "max_w": 200},
                      {"id": "b", "label": "Long label with multiple meaningful words", "max_w": 130}],
            "peer_sets": [{"ids": ["a", "b"], "equal_height": True,
                           "axis": "horizontal", "align": "centerline"}],
        }

    def test_measured_height_widths_labels_and_input_preserved(self):
        request = self.request()
        request["nodes"][0]["min_h"] = 65
        request["nodes"][0]["min_w"] = 34
        original = copy.deepcopy(request)
        independent = sc.normalize({k: v for k, v in request.items() if k != "peer_sets"})
        for node in independent["nodes"]:
            sc.size_node(independent, node)
        scene = sc.normalize(request)
        for node in scene["nodes"]:
            sc.size_node(scene, node)
        a, b = scene["nodes"]
        self.assertEqual(a["box"]["h"], b["box"]["h"])
        self.assertEqual(a["box"]["h"], max(n["box"]["h"] for n in independent["nodes"]))
        self.assertNotEqual(a["box"]["w"], b["box"]["w"])
        self.assertEqual([n["box"]["w"] for n in scene["nodes"]],
                         [n["box"]["w"] for n in independent["nodes"]])
        self.assertGreater(len(b["measure"]["title_lines"]), 1)
        self.assertEqual(scene["type"], independent["type"])
        self.assertEqual([n["label"] for n in scene["nodes"]], [n["label"] for n in request["nodes"]])
        self.assertEqual(request, original)

    def test_tighter_wrap_refreshes_peer_metrics_and_can_reset(self):
        scene = sc.normalize(self.request())
        a, b = scene["nodes"]
        sc.size_node(scene, a)
        original_h = a["box"]["h"]
        sc.size_node(scene, b, 0.6)
        self.assertGreater(b["box"]["h"], original_h)
        self.assertEqual(a["box"]["h"], b["box"]["h"])
        self.assertEqual(a["measure"]["frame_height_px"], a["box"]["h"])
        self.assertAlmostEqual(a["measure"]["inner_height_px"], a["box"]["h"] - 2 * sc.PAD_Y)
        b["label"] = "B"
        sc.size_node(scene, b)
        self.assertEqual(b["measure"]["title_lines"], ["B"])
        self.assertLess(b["box"]["h"], original_h)

    def test_cross_parent_selected_wrap_updates_earlier_extent(self):
        request = self.request()
        request["nodes"][1]["max_w"] = 240
        request["nodes"][0]["zone"] = "left"
        request["nodes"][1]["zone"] = "right"
        request["zones"] = [
            {"id": "left", "kind": "group", "pad": 0, "at": {"x": 40, "y": 150},
             "layout": {"type": "rows", "rows": [["a"]]}},
            {"id": "right", "kind": "group", "pad": 0,
             "frame": {"x": 400, "y": 150, "w": 160, "h": 200},
             "layout": {"type": "rows", "rows": [["b"]]}},
        ]
        original = copy.deepcopy(request)
        _, result, _ = arrange.arrange(request)
        a, b = result["nodes"]
        left, right = result["zones"]
        self.assertLess(right["wrap_scale"], 1)
        self.assertEqual(a["box"]["h"], b["box"]["h"])
        self.assertEqual(left["box"]["h"], a["box"]["h"])
        self.assertGreaterEqual(left["box"]["h"], b["measure"]["need_h"])
        self.assertEqual(request, original)
        self.assertNotIn("_height_floor_px", result["peer_sets"][0])
        _, repeated, _ = arrange.arrange(result)
        self.assertEqual([n["box"] for n in repeated["nodes"]], [n["box"] for n in result["nodes"]])

    def test_no_peers_unchanged_and_original_floor_survives_wider_wrap(self):
        request = self.request()
        plain = sc.normalize({k: v for k, v in request.items() if k != "peer_sets"})
        for node in plain["nodes"]:
            sc.size_node(plain, node)
        self.assertNotEqual(plain["nodes"][0]["box"]["h"], plain["nodes"][1]["box"]["h"])
        scene = sc.normalize(request)
        for node in scene["nodes"]:
            sc.size_node(scene, node, 2.0)
        self.assertEqual(scene["nodes"][0]["box"]["h"], max(n["box"]["h"] for n in plain["nodes"]))

    def test_only_declared_peers_and_no_cross_zone_repositioning(self):
        request = self.request()
        request["nodes"].append({"id": "c", "label": "Unrelated", "min_h": 300})
        request["nodes"][0]["box"] = {"x": 50, "y": 100, "w": 1, "h": 1}
        request["nodes"][1]["box"] = {"x": 400, "y": 160, "w": 1, "h": 1}
        scene = sc.normalize(request)
        for node in scene["nodes"]:
            sc.size_node(scene, node)
        a, b, c = scene["nodes"]
        self.assertLess(a["box"]["h"], c["box"]["h"])
        self.assertEqual(a["box"]["h"], b["box"]["h"])
        self.assertEqual((a["box"]["x"], a["box"]["y"]), (50, 100))
        self.assertEqual((b["box"]["x"], b["box"]["y"]), (400, 160))

    def test_invalid_declarations(self):
        variants = [None, {}, [None], [{"ids": ["a"]}],
                    [{"ids": ["a", "a"]}], [{"ids": ["a", "unknown"]}],
                    [{"ids": ["a", {}]}]]
        valid = self.request()["peer_sets"][0]
        variants += [[{**valid, "axis": "vertical"}], [{**valid, "align": "top"}],
                     [{**valid, "equal_height": 1}], [valid, copy.deepcopy(valid)]]
        for peers in variants:
            with self.subTest(peers=peers), self.assertRaisesRegex(HelperError, "peer_sets"):
                sc.normalize({**self.request(), "peer_sets": peers})

    def test_elk_rejects_unsupported_peers(self):
        with self.assertRaisesRegex(HelperError, "primitive"):
            arrange.arrange(self.request(), "elk")
