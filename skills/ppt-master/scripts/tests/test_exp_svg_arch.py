"""Offline tests for the experimental architecture helpers under scripts/exp_svg/arch/.

Run from skills/ppt-master/scripts:  python -m unittest tests.test_exp_svg_arch
No network, no browser, no model; the ELK case needs Node.js and is skipped without it, the libavoid engine is not
exercised here (its package is not vendored).
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
ARCH = SCRIPTS / "exp_svg" / "arch"
for path in (str(SCRIPTS), str(ARCH)):
    if path not in sys.path:
        sys.path.insert(0, path)

import arrange  # noqa: E402
import measure_labels  # noqa: E402
import move_group  # noqa: E402
import route_connections  # noqa: E402
import scene as sc  # noqa: E402
from _common import HelperError  # noqa: E402


def small_scene() -> dict:
    """Two regional zones, six nodes, five flows (two cross-boundary), one annotation, a legend."""
    return {
        "region": {"x": 40, "y": 100, "w": 1200, "h": 590},
        "font": {"family": "Arial"},
        "zones": [
            {"id": "left", "label": "Region A", "kind": "region", "frame": {"x": 200, "y": 110, "w": 460, "h": 460},
             "layout": {"type": "rows", "rows": [["a1", "a2"], ["a3"]], "gap_x": 40, "gap_y": 60}},
            {"id": "right", "label": "Region B", "kind": "trust", "frame": {"x": 760, "y": 110, "w": 460, "h": 460},
             "layout": {"type": "columns", "columns": [["b1", "b2"]], "gap_y": 80}},
        ],
        "nodes": [
            {"id": "ext", "label": "External caller", "kind": "external"},
            {"id": "a1", "label": "Gateway", "zone": "left"},
            {"id": "a2", "label": "Orders", "zone": "left"},
            {"id": "a3", "label": "Database", "zone": "left", "kind": "datastore"},
            {"id": "b1", "label": "Analytics", "zone": "right"},
            {"id": "b2", "label": "Reporting", "zone": "right"},
        ],
        "edges": [
            {"id": "e1", "source": "ext", "target": "a1", "label": "requests", "kind": "sync"},
            {"id": "e2", "source": "a1", "target": "a2", "label": "order calls", "kind": "sync"},
            {"id": "e3", "source": "a2", "target": "a3", "label": "writes", "kind": "sync"},
            {"id": "e4", "source": "a2", "target": "b1", "label": "events", "kind": "async"},
            {"id": "e5", "source": "b1", "target": "b2", "kind": "async"},
        ],
        "annotations": [{"id": "n1", "text": "Data stays in region A", "attach": {"to": "a3", "side": "S", "gap": 8},
                         "role": "label"}],
        "legend": {"dock": "bottom", "items": [{"kind": "sync", "text": "Synchronous call"},
                                               {"kind": "async", "text": "Asynchronous event"}]},
        "constraints": [{"op": "place", "id": "ext", "x": 40, "y": 200}, {"op": "align", "ids": ["ext", "a1"], "edge": "cy", "to": "a1"}],
    }


class MeasureLabelsTests(unittest.TestCase):
    def test_wrap_keeps_every_word_and_reports_floor(self):
        measured, residuals = measure_labels.measure_request({
            "font": {"family": "Arial"},
            "labels": [{"id": "x", "text": "Replicates encrypted order events every night", "size_px": 13.333,
                        "role": "label", "max_width": 120},
                       {"id": "y", "text": "Tiny", "size_px": 12, "role": "label"}]})
        first = measured[0]
        self.assertGreater(len(first["lines"]), 1)
        self.assertEqual(" ".join(first["lines"]).split(), "Replicates encrypted order events every night".split())
        self.assertTrue(all(w <= 120.01 for w in first["line_widths_px"]))
        self.assertEqual([r["kind"] for r in residuals if r["id"] == "y"], ["below_type_floor"])

    def test_missing_explicit_font_file_is_an_error(self):
        with self.assertRaises(HelperError):
            measure_labels.measure_request({"font": {"family": "X", "files": {"normal": "Z:/no/such/font.ttf"}},
                                            "labels": [{"id": "a", "text": "abc", "size_px": 16}]})


class ArrangeTests(unittest.TestCase):
    def test_feasible_scene_places_everything_inside_its_zone(self):
        status, scene, residuals = arrange.arrange(small_scene())
        self.assertEqual(status, "ok", residuals)
        zones = {z["id"]: sc.rect(z["box"]) for z in scene["zones"]}
        for node in scene["nodes"]:
            if node.get("zone"):
                self.assertTrue(sc.contains(zones[node["zone"]], sc.rect(node["box"])), node["id"])
            self.assertGreaterEqual(node["box"]["w"], node["measure"]["need_w"] - 0.01)
        a1, a2 = (next(n for n in scene["nodes"] if n["id"] == i)["box"] for i in ("a1", "a2"))
        label_gap = scene["zones"][0]["layout"]["label_gaps"]["a1|a2"]
        self.assertGreaterEqual(a2["x"] - (a1["x"] + a1["w"]), label_gap - 0.01)  # room reserved for "order calls"

    def test_type_below_the_floor_is_refused(self):
        scene = small_scene()
        scene["type"] = {"edge_label_px": 12}
        with self.assertRaises(HelperError):
            arrange.arrange(scene)

    def test_over_capacity_fails_explicitly_and_keeps_every_item(self):
        scene = small_scene()
        scene["zones"][1]["frame"] = {"x": 760, "y": 110, "w": 120, "h": 120}
        status, arranged, residuals = arrange.arrange(scene)
        self.assertEqual(status, "capacity_failure")
        capacity = [r for r in residuals if r["kind"] == "capacity"]
        self.assertEqual(capacity[0]["zone"], "right")
        self.assertGreater(capacity[0]["needs"]["h"], capacity[0]["has"]["h"])
        self.assertEqual({n["id"] for n in arranged["nodes"]}, {n["id"] for n in small_scene()["nodes"]})
        self.assertEqual([n["label"] for n in arranged["nodes"]], [n["label"] for n in small_scene()["nodes"]])

    def test_unplaced_node_is_an_error(self):
        scene = small_scene()
        scene["constraints"] = []
        with self.assertRaises(HelperError):
            arrange.arrange(scene)

    def test_relative_ops(self):
        scene = {"nodes": [{"id": "p", "label": "Primary"}, {"id": "q", "label": "Second node"}, {"id": "r", "label": "R"}],
                 "constraints": [{"op": "place", "id": "p", "x": 100, "y": 200},
                                 {"op": "right_of", "id": "q", "of": "p", "gap": 50, "align": "center"},
                                 {"op": "below", "id": "r", "of": "p", "gap": 30, "align": "left"}]}
        status, out, residuals = arrange.arrange(scene)
        self.assertEqual(status, "ok", residuals)
        boxes = {n["id"]: n["box"] for n in out["nodes"]}
        self.assertAlmostEqual(boxes["q"]["x"], boxes["p"]["x"] + boxes["p"]["w"] + 50, places=1)
        self.assertAlmostEqual(boxes["q"]["y"] + boxes["q"]["h"] / 2, boxes["p"]["y"] + boxes["p"]["h"] / 2, places=1)
        self.assertAlmostEqual(boxes["r"]["y"], boxes["p"]["y"] + boxes["p"]["h"] + 30, places=1)
        self.assertAlmostEqual(boxes["r"]["x"], boxes["p"]["x"], places=1)


class RouteTests(unittest.TestCase):
    def setUp(self):
        _status, self.arranged, _ = arrange.arrange(small_scene())

    def test_routes_bind_to_the_intended_nodes(self):
        status, routed, residuals = route_connections.route(copy.deepcopy(self.arranged))
        kinds = {r["kind"] for r in residuals}
        self.assertNotIn("endpoint_unbound", kinds)
        self.assertNotIn("route_through_node", kinds)
        for edge in routed["edges"]:
            binding = edge["route"]["binding"]
            self.assertEqual(binding["source"]["id"], edge["source"])
            self.assertEqual(binding["target"]["id"], edge["target"])
            self.assertTrue(binding["source"]["bound"] and binding["target"]["bound"])
            self.assertTrue(binding["head_points_into_target"])
            for a, b in zip(edge["route"]["points"], edge["route"]["points"][1:]):
                self.assertTrue(abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01, "orthogonal segments only")

    def test_route_avoids_a_box_in_the_way(self):
        scene = {"nodes": [{"id": "s", "label": "Source"}, {"id": "m", "label": "Middle box"}, {"id": "t", "label": "Target"}],
                 "edges": [{"id": "x", "source": "s", "target": "t"}],
                 "constraints": [{"op": "place", "id": "s", "x": 100, "y": 300},
                                 {"op": "right_of", "id": "m", "of": "s", "gap": 80},
                                 {"op": "right_of", "id": "t", "of": "m", "gap": 80}]}
        _s, arranged, _r = arrange.arrange(scene)
        status, routed, residuals = route_connections.route(arranged)
        middle = sc.rect(next(n for n in routed["nodes"] if n["id"] == "m")["box"])
        points = routed["edges"][0]["route"]["points"]
        self.assertFalse(any(sc.segment_hits_rect(a, b, middle) for a, b in zip(points, points[1:])))
        self.assertTrue(routed["edges"][0]["route"]["binding"]["target"]["bound"])

    def test_glue_prediction_uses_the_exporters_elbow_rule(self):
        binding = {"source": {"bound": True}, "target": {"bound": True}}
        self.assertTrue(route_connections.predict_glue([[0, 0], [50, 0], [50, 80], [120, 80]], binding, False)["expected"])
        u_turn = [[100, 50], [130, 50], [130, 200], [100, 200]]
        self.assertFalse(route_connections.predict_glue(u_turn, binding, False)["expected"])
        five = [[0, 0], [10, 0], [10, 10], [20, 10], [20, 20], [30, 20]]
        self.assertFalse(route_connections.predict_glue(five, binding, False)["expected"])

    def test_unroutable_flow_is_kept_with_a_residual(self):
        scene = {"nodes": [{"id": "s", "label": "Source"}, {"id": "t", "label": "Target"}],
                 "edges": [{"id": "x", "source": "s", "target": "t", "source_side": "W", "target_side": "E"}],
                 "constraints": [{"op": "place", "id": "s", "x": 2, "y": 300},
                                 {"op": "right_of", "id": "t", "of": "s", "gap": 60}]}
        _s, arranged, _r = arrange.arrange(scene)
        status, routed, residuals = route_connections.route(arranged)
        self.assertEqual(status, "partial")
        self.assertEqual(len(routed["edges"]), 1)
        self.assertIsNone(routed["edges"][0]["route"]["points"])
        self.assertIn("unrouted", {r["kind"] for r in residuals})


class MoveGroupTests(unittest.TestCase):
    def setUp(self):
        _s, arranged, _r = arrange.arrange(small_scene())
        _s, self.routed, _r = route_connections.route(arranged)

    def test_zone_move_is_atomic_and_keeps_bindings(self):
        before = {n["id"]: dict(n["box"]) for n in self.routed["nodes"]}
        status, moved, residuals, changes = move_group.move(self.routed, "right", {"dx": 0, "dy": 40}, None)
        self.assertTrue(changes["bindings_preserved"])
        self.assertEqual(sorted(changes["moved_nodes"]), ["b1", "b2"])
        self.assertIn("e5", changes["translated_edges"])
        self.assertIn("e4", changes["rerouted_edges"])
        after = {n["id"]: n["box"] for n in moved["nodes"]}
        for node_id in ("b1", "b2"):
            self.assertAlmostEqual(after[node_id]["y"], before[node_id]["y"] + 40, places=1)
        for node_id in ("a1", "a2", "a3", "ext"):
            self.assertEqual(after[node_id], before[node_id])
        e4 = next(e for e in moved["edges"] if e["id"] == "e4")
        self.assertEqual(e4["route"]["binding"]["target"]["id"], "b1")
        self.assertTrue(e4["route"]["binding"]["target"]["bound"])
        # the input scene is untouched (atomic: the move works on a copy)
        self.assertEqual({n["id"]: n["box"] for n in self.routed["nodes"]}, before)

    def test_zero_move_changes_nothing(self):
        _status, moved, _res, changes = move_group.move(self.routed, "left", {"dx": 0, "dy": 0}, None)
        self.assertEqual(changes["rerouted_edges"], [])
        self.assertEqual([e["route"]["points"] for e in moved["edges"]], [e["route"]["points"] for e in self.routed["edges"]])

    def test_unknown_group_is_an_error(self):
        with self.assertRaises(HelperError):
            move_group.move(self.routed, "nope", {"dx": 1, "dy": 0}, None)


class RenderAndCliTests(unittest.TestCase):
    def test_svg_contract(self):
        _s, arranged, _r = arrange.arrange(small_scene())
        _s, routed, _r = route_connections.route(arranged)
        svg = sc.render_svg(routed)
        self.assertIn('markerUnits="userSpaceOnUse"', svg)
        self.assertIn('markerWidth="8"', svg)
        first_label = svg.find('data-arch-text="e1:label"')
        first_edge = svg.find('id="arch-edge-')
        self.assertTrue(0 < first_label < first_edge, "flow labels are painted beneath the flows")
        for node in routed["nodes"]:
            self.assertIn(f'id="arch-node-{node["id"]}"', svg)

    def test_cli_receipt(self):
        work = Path(tempfile.mkdtemp())
        try:
            request = work / "scene.json"
            request.write_text(json.dumps(small_scene()), encoding="utf-8")
            out = work / "arranged.json"
            code = arrange.main(["--in", str(request), "--out", str(out), "--svg", str(work / "p.svg")])
            self.assertEqual(code, 0)
            result = json.loads(out.read_text(encoding="utf-8"))
            for key in ("tool", "version", "status", "input_sha256", "output_sha256", "elapsed_s", "residual_constraints",
                        "content_ids"):
                self.assertIn(key, result)
            self.assertIn("e4", result["content_ids"])
            self.assertTrue((work / "p.svg").is_file())
            routed = work / "routed.json"
            code = route_connections.main(["--in", str(out), "--out", str(routed)])
            self.assertIn(code, (0, 3))
            self.assertIn("bindings", json.loads(routed.read_text(encoding="utf-8")))
            bad = work / "bad.json"
            bad.write_text("{\"nodes\": []", encoding="utf-8")
            self.assertEqual(arrange.main(["--in", str(bad), "--out", str(work / "bad_out.json")]), 2)
            self.assertEqual(json.loads((work / "bad_out.json").read_text(encoding="utf-8"))["status"], "error")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not on PATH")
    def test_elk_engine_reports_capacity_honestly(self):
        status, scene, residuals = arrange.arrange(small_scene(), "elk")
        self.assertIn(status, ("ok", "partial", "capacity_failure"))
        self.assertEqual(len(scene["nodes"]), 6)
        if status == "capacity_failure":
            self.assertTrue(any(r["kind"] == "capacity" for r in residuals))


if __name__ == "__main__":
    unittest.main()
