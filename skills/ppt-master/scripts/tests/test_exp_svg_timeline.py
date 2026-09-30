"""exp_svg/timeline/build_timeline.py (SVG helpers experiment, 2026-09-30): the JSON-in/JSON-out timeline adapter over
timeline_layout.py. Offline; no model or network call. Run: cd skills/ppt-master/scripts && python -m unittest tests.test_exp_svg_timeline
(pytest also collects it)."""

import copy
import json
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / "exp_svg" / "timeline"))

import build_timeline as bt  # noqa: E402
import timeline_layout  # noqa: E402
from timeline_fonts import FontMetrics  # noqa: E402

R1 = "timeline_layout"  # round-1 engine; the classes below marked Dense test the v0.2.0 default engine

BASE = {
    "schema": "exp_svg.build_timeline.request.v1",
    "calendar": {"start": "2026-07-27", "end": "2026-10-25", "prefix": "W"},
    "lanes": [{"id": "L1", "name": "Mobilise"}, {"id": "L2", "name": "Build"}],
    "tasks": [
        {"id": "t1", "name": "Kick-off", "lane": "L1", "start": "2026-07-27", "end": "2026-07-29"},
        {"id": "t2", "name": "Charter and plan", "lane": "L1", "start": "2026-07-30", "end": "2026-08-14"},
        {"id": "t3", "name": "Build the platform", "lane": "L2", "start": "2026-08-19", "end": "2026-10-25"},
    ],
    "milestones": [
        {"id": "m1", "name": "Mobilised", "date": "2026-07-31"},
        {"id": "g1", "name": "Design gate", "date": "2026-08-14", "kind": "gate"},
    ],
    "dependencies": [{"id": "d1", "from": "t2", "to": "t3"}],
    "style": {"font_family": "Segoe UI"},
    "bounds": {"x": 60, "y": 150, "w": 1160, "h": 300},
}


def request(**changes):
    r = copy.deepcopy(BASE)
    r.update(changes)
    return r


def days(iso):
    return (date.fromisoformat(iso) - date(2026, 7, 27)).days


class CalendarMappingTest(unittest.TestCase):
    def test_bars_follow_independent_day_arithmetic(self):
        built = bt.build(request(), engine=R1)
        self.assertEqual(built["status"], "ok", built.get("unsatisfied_constraints"))
        scale = built["scene"]["scale"]
        x0, per_day = scale["x_of_calendar_start"], scale["px_per_day"]
        for task in built["scene"]["tasks"]:
            self.assertAlmostEqual(task["x0"], x0 + days(task["start"]) * per_day, delta=0.05)
            self.assertAlmostEqual(task["x1"], x0 + (days(task["end"]) + 1) * per_day, delta=0.05)

    def test_sub_week_task_is_accepted_and_keeps_its_length(self):
        built = bt.build(request(), engine=R1)
        kickoff = next(t for t in built["scene"]["tasks"] if t["id"] == "t1")
        self.assertAlmostEqual(kickoff["x1"] - kickoff["x0"], 3 * built["scene"]["scale"]["px_per_day"], delta=0.05)

    def test_milestone_anchor_end_and_start_of_day(self):
        per_day_end = bt.build(request(), engine=R1)
        start_cal = dict(BASE["calendar"], milestone_anchor="start_of_day")
        per_day_start = bt.build(request(calendar=start_cal), engine=R1)
        m_end = next(m for m in per_day_end["scene"]["milestones"] if m["id"] == "m1")
        m_start = next(m for m in per_day_start["scene"]["milestones"] if m["id"] == "m1")
        s = per_day_end["scene"]["scale"]
        self.assertAlmostEqual(m_end["x"], s["x_of_calendar_start"] + (days("2026-07-31") + 1) * s["px_per_day"], delta=0.05)
        self.assertAlmostEqual(m_start["x"], s["x_of_calendar_start"] + days("2026-07-31") * s["px_per_day"], delta=0.05)

    def test_bar_end_shim_compares_by_drawn_edge(self):
        end = bt.BarEnd(1.2857 - 1)  # a 2-day task starting at unit 1: end + 1 > start
        self.assertFalse(end < 1.0)
        self.assertTrue(bt.BarEnd(0.0) < 1.0)  # no length at all
        self.assertTrue(end > 0.0)


class OutputContractTest(unittest.TestCase):
    def test_every_item_has_a_stable_content_id_and_its_name(self):
        built = bt.build(request(), engine=R1)
        group = built["group"]
        for task in BASE["tasks"]:
            self.assertIn(f'data-content-id="task:{task["id"]}" data-role="bar"', group)
            self.assertIn(task["name"], group)
        for ms in BASE["milestones"]:
            self.assertIn(f'data-content-id="milestone:{ms["id"]}"', group)
            self.assertIn(ms["name"], group)
        self.assertIn('data-content-id="dependency:d1"', group)

    def test_group_digest_matches_so_the_lint_sees_no_hand_edit(self):
        built = bt.build(request(), engine=R1)
        found = timeline_layout.find_groups(built["group"], group_id="timeline")[0]
        self.assertEqual(timeline_layout.group_digest(found["inner"]), found["attrs"]["data-output-sha"])

    def test_deterministic(self):
        self.assertEqual(bt.build(request(), engine=R1)["group"], bt.build(request(), engine=R1)["group"])

    def test_small_type_is_raised_never_shrunk(self):
        built = bt.build(request(style={"font_family": "Segoe UI", "label_px": 12}), engine=R1)
        self.assertGreaterEqual(built["scene"]["font"]["label_px"], 14)
        self.assertTrue(any(n["kind"] == "style_raised" for n in built["notes"]))


class CapacityTest(unittest.TestCase):
    def test_over_capacity_fails_explicitly_and_drops_nothing(self):
        lanes = [{"id": f"L{i}", "name": f"Workstream {i}"} for i in range(14)]
        tasks = [{"id": f"t{i}_{j}", "name": f"Workstream {i} phase {j} with a long descriptive name", "lane": f"L{i}",
                  "start": f"2026-{8 + j:02d}-03", "end": f"2026-{8 + j:02d}-21"} for i in range(14) for j in range(3)]
        built = bt.build(request(lanes=lanes, tasks=tasks, milestones=[], dependencies=[]), engine=R1)
        self.assertEqual(built["status"], "capacity_failure")
        self.assertTrue(built["capacity"]["binding"])
        for task in tasks:
            self.assertIn(f'data-content-id="task:{task["id"]}" data-role="bar-label"', built["group"])
            self.assertIn(task["name"], built["group"])

    def test_crossing_leader_makes_the_status_partial(self):
        # the clustered-milestone case of the qualification (t03, milestones only): the engine reports no check, yet the
        # leaders of names dropped to lower rows cut through 'Tender issued' and 'Permit submitted'
        lanes = [{"id": i, "name": n} for i, n in (("plan", "Planning"), ("proc", "Procurement"), ("site", "Site works"),
                                                   ("sys", "Systems"), ("ops", "Operations readiness"))]
        tasks = [{"id": i, "name": f"Task {i}", "lane": lane, "start": s, "end": e} for i, lane, s, e in (
            ("p1", "plan", "2027-02-01", "2027-02-19"), ("p2", "plan", "2027-02-15", "2027-03-19"), ("q1", "proc", "2027-02-08", "2027-03-05"),
            ("q2", "proc", "2027-03-08", "2027-03-26"), ("s1", "site", "2027-03-22", "2027-04-16"), ("s2", "site", "2027-04-12", "2027-05-21"),
            ("y1", "sys", "2027-02-22", "2027-03-19"), ("y2", "sys", "2027-04-19", "2027-05-14"), ("o1", "ops", "2027-03-01", "2027-03-26"),
            ("o2", "ops", "2027-05-03", "2027-05-21"))]
        milestones = [{"id": f"c{k}", "name": n, "date": d} for k, (n, d) in enumerate((
            ("Sponsor sign-off", "2027-02-19"), ("Scope baselined", "2027-02-19"), ("Tender issued", "2027-02-16"),
            ("Permit submitted", "2027-03-01"), ("Bids received", "2027-03-05"), ("Contract signed", "2027-03-26"),
            ("Permit granted", "2027-03-19"), ("Site handover", "2027-04-16"), ("Systems live", "2027-05-14")))]
        built = bt.build(request(calendar={"start": "2027-02-01", "end": "2027-05-23", "prefix": "W"}, lanes=lanes, tasks=tasks,
                                 milestones=milestones, dependencies=[],
                                 style={"font_family": "Segoe UI", "lane_label_w": 170},
                                 bounds={"x": 60, "y": 150, "w": 1160, "h": 500}), engine=R1)
        self.assertEqual(timeline_layout.checks(built["placed"]), [])  # the engine alone would call this clean
        self.assertTrue(bt.leader_crossings(built["placed"]))
        self.assertEqual(built["status"], "partial")
        self.assertTrue(any("leader" in u["detail"] for u in built["unsatisfied_constraints"]))


class ValidationAndCliTest(unittest.TestCase):
    def run_cli(self, req):
        with tempfile.TemporaryDirectory() as tmp:
            src, out, svg = Path(tmp) / "r.json", Path(tmp) / "o.json", Path(tmp) / "p.svg"
            src.write_text(json.dumps(req), encoding="utf-8")
            code = bt.main(["--in", str(src), "--out", str(out), "--svg", str(svg), "--engine", R1])
            return code, json.loads(out.read_text(encoding="utf-8")), (svg.read_text(encoding="utf-8") if svg.is_file() else None)

    def test_cli_ok_writes_receipt_and_preview(self):
        code, result, svg = self.run_cli(request())
        self.assertEqual(code, 0)
        receipt = result["receipt"]
        for key in ("tool", "tool_version", "engine_sha256", "input_sha256", "output_sha256", "elapsed_ms", "status"):
            self.assertIn(key, receipt)
        self.assertTrue(svg.startswith("<svg") and 'data-layout="timeline_layout"' in svg)

    def test_invalid_requests_return_error_with_reasons(self):
        bad = request()
        bad["tasks"][0]["lane"] = "nope"
        bad["tasks"][1]["end"] = "2026-13-01"
        bad["dependencies"] = [{"id": "d1", "from": "t1", "to": "ghost"}]
        code, result, svg = self.run_cli(bad)
        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "error")
        joined = " ".join(result["errors"])
        self.assertIn("is not a lane", joined)
        self.assertIn("not an ISO date", joined)
        self.assertIn("ghost", joined)
        self.assertIsNone(svg)

    def test_into_inserts_then_replaces_one_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = Path(tmp) / "svg_output" / "07_plan.svg"
            page.parent.mkdir()
            page.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><text x="60" y="80">Title</text></svg>',
                            encoding="utf-8")
            src, out = Path(tmp) / "r.json", Path(tmp) / "o.json"
            src.write_text(json.dumps(request()), encoding="utf-8")
            self.assertEqual(bt.main(["--in", str(src), "--out", str(out), "--into", str(page), "--engine", R1]), 0)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["svg"]["action"], "inserted")
            self.assertEqual(bt.main(["--in", str(src), "--out", str(out), "--into", str(page), "--engine", R1]), 0)
            text = page.read_text(encoding="utf-8")
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["svg"]["action"], "replaced")
            self.assertEqual(len(re.findall(r'<g id="timeline"', text)), 1)
            self.assertIn("Title", text)
            self.assertTrue((page.parent / "07_plan.timeline.request.json").is_file())


class FontMetricsTest(unittest.TestCase):
    def test_real_metrics_distinguish_families_when_fonts_exist(self):
        segoe, gothic = FontMetrics("Segoe UI"), FontMetrics("'Century Gothic', Arial")
        if segoe.method == "estimator" or gothic.method == "estimator":
            self.skipTest("Windows font files not available")
        self.assertGreater(gothic.width("Anchor feeds and model", 14), segoe.width("Anchor feeds and model", 14) + 10)

    def test_wrap_never_cuts_a_word(self):
        metrics = FontMetrics("Segoe UI")
        lines, _ = metrics.wrap("Extraordinarilylongword and more", 14, 40)
        self.assertEqual(" ".join(lines), "Extraordinarilylongword and more")


if __name__ == "__main__":
    unittest.main()
