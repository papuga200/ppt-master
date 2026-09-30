"""exp_svg/timeline v0.2.0 dense engine (SVG helpers experiment, round 2): the 13.33 px floor, the week convention, windows,
lane events, dependencies between any items, leader-safe stacked names, gate lines interrupted at labels, and explicit
capacity failure with the binding constraint. Offline; no model or network call.
Run: cd skills/ppt-master/scripts && python -m unittest tests.test_exp_svg_timeline_dense (pytest also collects it)."""

import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "exp_svg" / "timeline"))

import build_timeline as bt  # noqa: E402
import timeline_layout  # noqa: E402
from dense_layout import Box  # noqa: E402

PLAN = {
    "schema": "exp_svg.build_timeline.request.v2",
    "calendar": {"start": "2026-07-27", "horizon_weeks": 12, "prefix": "W"},
    "ruler": {"edge_labels": ["27 Jul 2026", "16 Oct 2026"]},
    "lanes": [{"id": "a", "name": "Data platform"}, {"id": "b", "name": "Reporting"}, {"id": "c", "name": "Governance"}],
    "tasks": [
        {"id": "t1", "name": "Anchor feeds", "lane": "a", "weeks": [1, 4]},
        {"id": "t2", "name": "Pattern feeds", "lane": "a", "weeks": [3, 7]},
        {"id": "t3", "name": "Model", "lane": "b", "weeks": [4, 8]},
        {"id": "t4", "name": "User acceptance testing", "lane": "b", "weeks": [9, 11]},
        {"id": "t5", "name": "Weekly workshops", "lane": "c", "weeks": [1, 12]},
    ],
    "milestones": [
        {"id": "s1", "name": "Steering update", "week": 4, "placement": "lane", "lane": "c"},
        {"id": "s2", "name": "Steering update", "week": 9, "placement": "lane", "lane": "c"},
        {"id": "D1", "name": "D1: design approved", "week": 4, "kind": "gate"},
        {"id": "D2", "name": "D2: go-live decision", "week": 10, "kind": "gate"},
        {"id": "M1", "name": "Go-live", "week": 11, "focal": True, "payment": True},
    ],
    "windows": [{"id": "hol", "name": "Holiday window", "weeks": [10, 10]},
                {"id": "float", "name": "Float (unplanned)", "weeks": [13, 13], "style": "dashed"}],
    "dependencies": [{"id": "k1", "from": "t2", "to": "D1"}, {"id": "k2", "from": "t3", "to": "t4"}, {"id": "k3", "from": "D2", "to": "M1"}],
    "legend": [{"symbol": "payment", "text": "Payment milestone"}],
    "style": {"font_family": "Segoe UI", "label_px": 14},
    "bounds": {"x": 54, "y": 140, "w": 1172, "h": 476},
}


def drawn_texts(group: str) -> list:
    """Every <text> as one string, its tspans (wrapped lines) joined by a space."""
    out = []
    for body in re.findall(r"<text(?:\s[^>]*)?>(.*?)</text>", group, flags=re.S):
        spans = re.findall(r"<tspan(?:\s[^>]*)?>(.*?)</tspan>", body, flags=re.S)
        out.append(" ".join(spans) if spans else re.sub(r"<[^>]+>", "", body))
    return out


def plan(**changes):
    r = copy.deepcopy(PLAN)
    r.update(changes)
    return r


class DenseContractTest(unittest.TestCase):
    def test_default_engine_is_dense_and_everything_is_drawn(self):
        built = bt.build(plan())
        self.assertEqual(built["engine"], "exp_svg.dense_layout")
        self.assertEqual(built["status"], "ok", built["unsatisfied_constraints"])
        group = built["group"]
        for t in PLAN["tasks"]:
            self.assertIn(f'data-content-id="task:{t["id"]}" data-role="bar"', group)
        for m in PLAN["milestones"]:
            self.assertIn(f'data-content-id="milestone:{m["id"]}"', group)
        for w in PLAN["windows"]:
            self.assertIn(f'data-content-id="window:{w["id"]}" data-role="window"', group)
        for d in PLAN["dependencies"]:
            self.assertIn(f'data-content-id="dependency:{d["id"]}"', group)
        self.assertEqual(group.count(">Steering update<"), 2)  # repeated names are each drawn

    def test_week_convention_by_independent_arithmetic(self):
        scene = bt.build(plan())["scene"]
        x0, per_day = scene["scale"]["x_of_calendar_start"], scene["scale"]["px_per_day"]
        for t in scene["tasks"]:
            weeks = next(p["weeks"] for p in PLAN["tasks"] if p["id"] == t["id"])
            self.assertAlmostEqual(t["x0"], x0 + 7 * (weeks[0] - 1) * per_day, delta=0.05)
            self.assertAlmostEqual(t["x1"], x0 + 7 * weeks[1] * per_day, delta=0.05)
        gate = next(m for m in scene["milestones"] if m["id"] == "D2")
        self.assertAlmostEqual(gate["x"], x0 + 70 * per_day, delta=0.05)  # end of week 10
        fl = next(w for w in scene["windows"] if w["id"] == "float")
        self.assertAlmostEqual(fl["x1"], x0 + 91 * per_day, delta=0.05)  # week 13 lies beyond the 12-week horizon

    def test_group_digest_is_lint_consistent_and_deterministic(self):
        a, b = bt.build(plan())["group"], bt.build(plan())["group"]
        self.assertEqual(a, b)
        found = timeline_layout.find_groups(a, group_id="timeline")[0]
        self.assertEqual(timeline_layout.group_digest(found["inner"]), found["attrs"]["data-output-sha"])

    def test_dependencies_attach_to_gates_and_milestones(self):
        scene = bt.build(plan())["scene"]
        marks = {m["id"]: m for m in scene["milestones"]}
        k1 = next(d for d in scene["dependencies"] if d["id"] == "k1")
        self.assertAlmostEqual(k1["points"][-1][0], marks["D1"]["x"], delta=0.5)  # ends on the D1 line
        k3 = next(d for d in scene["dependencies"] if d["id"] == "k3")
        self.assertAlmostEqual(k3["points"][0][0], marks["D2"]["x"], delta=0.5)  # leaves from the D2 line
        end = k3["points"][-1]
        self.assertTrue(4.0 <= marks["M1"]["x"] - end[0] <= 10.0)  # arrives at the go-live marker's left point (ring included, round 3)


class FloorTest(unittest.TestCase):
    def test_never_below_the_confirmed_floor(self):
        built = bt.build(plan(style={"font_family": "Segoe UI", "label_px": 12}))
        self.assertGreaterEqual(built["scene"]["font"]["label_px"], 13.33)
        self.assertTrue(any(n["kind"] == "style_raised" for n in built["notes"]))
        low = bt.build(plan(floors={"label_px": 12}))  # allowed since D015: timeline-chart labels may go to 10.667 px
        self.assertNotEqual(low["status"], "error")
        bad = bt.build(plan(floors={"label_px": 10}))
        self.assertEqual(bad["status"], "error")

    def test_drops_to_the_floor_only_when_needed(self):
        roomy = bt.build(plan())
        self.assertEqual(roomy["scene"]["font"]["label_px"], 14)


class StackingTest(unittest.TestCase):
    def test_no_leader_or_gate_line_passes_through_a_name(self):
        ms = [{"id": f"m{i}", "name": n, "date": d} for i, (n, d) in enumerate((
            ("Sponsor sign-off", "2027-02-19"), ("Scope baselined", "2027-02-19"), ("Tender issued", "2027-02-16"),
            ("Permit submitted", "2027-03-01"), ("Bids received", "2027-03-05")))]
        gates = [{"id": "g1", "name": "Budget approved", "date": "2027-02-17", "kind": "gate"},
                 {"id": "g2", "name": "Award decision with a longer name", "date": "2027-02-24", "kind": "gate"}]
        req = {"schema": "exp_svg.build_timeline.request.v2", "calendar": {"start": "2027-02-01", "end": "2027-05-23"},
               "lanes": [{"id": "p", "name": "Planning"}],
               "tasks": [{"id": "t", "name": "Scope", "lane": "p", "start": "2027-02-01", "end": "2027-02-19"}],
               "milestones": ms + gates, "style": {"font_family": "Segoe UI"}, "bounds": {"x": 60, "y": 150, "w": 1160, "h": 500}}
        built = bt.build(req)
        self.assertEqual(built["status"], "ok", built["unsatisfied_constraints"])
        scene = built["scene"]
        names = [(m["id"], Box(*m["label"]["rect"])) for m in scene["milestones"]]
        strip = [m for m in scene["milestones"] if m["kind"] == "milestone"]
        for m in strip:
            rect = Box(*m["label"]["rect"])
            if rect.x0 - 1 <= m["x"] <= rect.x1 + 1:
                continue  # its own leader enters its own name
            below_first = rect.y0 > min(s["label"]["rect"][1] for s in strip) + 1
            self.assertFalse(below_first, f"{m['id']} hangs below the first level without a leader into its name")
        for m in strip:
            top = min(Box(*s["label"]["rect"]).y0 for s in strip)
            own = Box(*m["label"]["rect"])
            if own.y0 <= top + 1:
                continue
            for other_id, other in names:
                if other_id != m["id"] and other.y1 <= own.y0 and other.y0 >= m["y"] and other.x0 - 1 < m["x"] < other.x1 + 1:
                    self.fail(f"leader of {m['id']} crosses {other_id}")

    def test_gate_line_is_interrupted_at_a_label_it_would_cross(self):
        built = bt.build(plan())
        gate = next(m for m in built["scene"]["milestones"] if m["id"] == "D1")
        labels = [Box(*t["label"]["rect"]) for t in built["scene"]["tasks"] if t["label"]["where"] != "inside"]
        for y0, y1 in gate["line_segments"]:
            for b in labels:
                if b.x0 - 1 <= gate["x"] <= b.x1 + 1:
                    self.assertFalse(y0 < b.y1 - 1 and b.y0 + 1 < y1, "a gate line segment runs through a label")


class CapacityTest(unittest.TestCase):
    def test_over_capacity_names_the_binding_constraint_and_drops_nothing(self):
        lanes = [{"id": f"L{i}", "name": f"Workstream {i}"} for i in range(16)]
        tasks = [{"id": f"t{i}_{j}", "name": f"Workstream {i} phase {j} with a descriptive name", "lane": f"L{i}",
                  "weeks": [1 + 4 * j, 3 + 4 * j]} for i in range(16) for j in range(3)]
        built = bt.build(plan(lanes=lanes, tasks=tasks, milestones=[], windows=[], dependencies=[], legend=[],
                              bounds={"x": 54, "y": 140, "w": 1172, "h": 300}))
        self.assertEqual(built["status"], "capacity_failure")
        height = next(b for b in built["capacity"]["binding"] if b["constraint"] == "height")
        self.assertGreater(height["needs_px"], height["available_px"])
        self.assertIn("rows", height["detail"])
        texts = drawn_texts(built["group"])
        for t in tasks:
            self.assertIn(t["name"], texts)
        self.assertGreaterEqual(built["scene"]["font"]["label_px"], 13.33)

    def test_cli_exit_code_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "r.json", Path(tmp) / "o.json"
            src.write_text(json.dumps(plan()), encoding="utf-8")
            self.assertEqual(bt.main(["--in", str(src), "--out", str(out)]), 0)
            receipt = json.loads(out.read_text(encoding="utf-8"))["receipt"]
            self.assertEqual(receipt["tool_version"], bt.TOOL_VERSION)
            self.assertEqual(receipt["engine"], "exp_svg.dense_layout")
            self.assertIn("dense_layout.py", receipt["adapter_files_sha256"])
            self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", receipt["output_sha256"]))


if __name__ == "__main__":
    unittest.main()
