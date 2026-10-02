#!/usr/bin/env python3
"""PPT Master - Portable measured authoring regressions.

Exercise explicit contracts, bounded searches and measured peer correspondence.
Usage: python -m unittest tests.test_exp_portable_authoring_tools
Examples: all resources are built in a temporary project by this module.
Dependencies: repository converter dependencies; no external fixtures or models.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from exp_svg import capacity_preflight, guided_build, guided_measure  # noqa: E402
from exp_svg.arch import attachment_candidates, local_frame_candidates, route_order_candidates  # noqa: E402
from exp_svg.arch.organization_check import check  # noqa: E402
from exp_svg.arch.receipt_summary import compact  # noqa: E402
from exp_svg.timeline.prepare_note_cards import prepare  # noqa: E402
from exp_svg.contracts import validate_preflight_fingerprints  # noqa: E402
from exp_svg.arch._common import sha256_json  # noqa: E402


def receipt(request: dict) -> dict:
    return {"ready": True, "delivery_state": "ready", "capacity_fit": True,
            "blocking_constraints": [], "residual_constraints": [{"kind": "spacing_tightened"}],
            "warnings": [{"kind": "spacing_tightened"}], "coverage": {"complete": True},
            "result": {"routes": {edge["id"]: {"stats": {"bends": 1, "length_px": 20}}
                                  for edge in request.get("edges", [])}}}


class PortableAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.template = self.directory / "content.svg"
        self.template.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" '
            'viewBox="0 0 1280 720" lang="en-US"><g id="chrome"></g></svg>', encoding="utf-8")
        self.body = {"x": 64, "y": 208, "w": 1152, "h": 440}
        self.contract = self.directory / "contract.json"
        self.contract.write_text(json.dumps({
            "template": "content.svg", "body_zone": self.body,
            "type_floors": {"label_px_min": 14, "body_px_min": 16},
            "native_editability_required": True, "source_layout_preflight_required": True,
        }), encoding="utf-8")
        self.request = {"page": {"template": str(self.template), "body": self.body},
                        "font": {"family": "Arial"},
                        "nodes": [{"id": "a", "label": "Source"}, {"id": "b", "label": "Target"}],
                        "root": {"layout": {"rows": [["a", "b"]], "gap_x": 140}},
                        "edges": [{"id": "flow", "source": "a", "target": "b", "label": "Call"}]}
        self.source = self.directory / "request.json"
        self.source.write_text(json.dumps(self.request), encoding="utf-8")
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in {"PPT_MASTER_PROJECT_PATH", "PPT_MASTER_EXP_ENGINES"}}

    def command(self, tool: str, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / tool), *map(str, arguments)],
                              cwd=self.directory, env=self.environment, capture_output=True,
                              text=True, encoding="utf-8")

    def test_explicit_contract_and_real_build_work_from_unrelated_directory(self):
        preflight = self.directory / "preflight.json"
        run = self.command("exp_svg/capacity_preflight.py", "--family", "architecture", "--in", self.source,
                           "--out", preflight, "--contract", self.contract)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        decision = json.loads(preflight.read_text(encoding="utf-8"))
        self.assertTrue(decision["ready"], decision)
        output, page = self.directory / "build.json", self.directory / "page.svg"
        run = self.command("exp_svg/guided_build.py", "--family", "architecture", "--in", self.source,
                           "--out", output, "--page", page, "--preflight-receipt", preflight,
                           "--contract", self.contract)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        resolved = json.loads(output.with_suffix(".request.json").read_text(encoding="utf-8"))
        self.assertEqual(resolved["type"]["edge_label_px"], 14)
        self.assertTrue(resolved["style"]["native_text_ownership"])
        self.assertIn('data-pptx-semantic-object="shape"', page.read_text(encoding="utf-8"))
        self.assertFalse((self.directory / "inputs").exists())

    def test_path_failure_preserves_source_for_both_wrappers(self):
        before = self.source.read_bytes()
        with patch.dict(os.environ, self.environment, clear=True):
            self.assertEqual(capacity_preflight.main(["--family", "architecture", "--in", str(self.source),
                             "--out", str(self.source), "--contract", str(self.contract)]), 2)
            # The diagnostic receipt would name the source itself if not guarded.
            source = self.directory / "result.contract.json"
            source.write_bytes(before)
            self.assertEqual(guided_build.main(["--family", "architecture", "--in", str(source),
                             "--out", str(self.directory / "result.json"), "--page", str(self.directory / "page.svg"),
                             "--contract", str(self.contract)]), 2)
            self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), before)

    def test_measure_contract_preserves_provenance_without_fixture(self):
        self.source.write_text(json.dumps({"font": {"family": "Arial"}, "labels": [
            {"id": "label", "text": "Two measured words", "role": "label", "size_px": 14,
             "max_width": 120}]}), encoding="utf-8")
        output = self.directory / "measured.json"
        with patch.dict(os.environ, self.environment, clear=True):
            self.assertEqual(guided_measure.main(["--in", str(self.source), "--out", str(output),
                                                 "--contract", str(self.contract)]), 0)
        result = json.loads(output.with_suffix(".summary.json").read_text(encoding="utf-8"))
        self.assertIn("font", result["labels"][0])
        self.assertIn("measurement", result["labels"][0])

    def test_each_promoted_entry_point_has_side_effect_free_help(self):
        before = set(self.directory.iterdir())
        for tool in ("guided_measure", "capacity_preflight", "guided_build", "fit_candidates",
                     "arch/local_frame_candidates", "arch/attachment_candidates",
                     "arch/route_order_candidates", "arch/port_clearance", "arch/receipt_summary",
                     "arch/organization_check", "inspect/native_editability", "timeline/prepare_note_cards"):
            with self.subTest(tool=tool):
                run = self.command("exp_svg/" + tool + ".py", "--help")
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                self.assertIn("usage:", run.stdout.lower())
        self.assertEqual(set(self.directory.iterdir()), before)

    def test_candidate_sets_are_bounded_and_preserve_semantics(self):
        original = copy.deepcopy(self.request)
        selected, result, summary, trials = attachment_candidates.run_candidates(
            self.request, "flow", allow_adapt_sides=True, evaluate=receipt)
        self.assertLessEqual(len(trials), 18)
        self.assertTrue(summary["ready"])
        self.assertEqual(selected["nodes"], original["nodes"])
        with self.assertRaises(ValueError):
            attachment_candidates.run_candidates(self.request, "flow", evaluate=receipt)
        selected, result, summary, trials = route_order_candidates.run_candidates(self.request, evaluate=receipt)
        self.assertLessEqual(len(trials), 6)
        self.assertEqual(selected, original)
        self.request["zones"] = [{"id": "z", "frame": {"x": 100, "y": 200, "w": 200, "h": 200}}]
        frozen = copy.deepcopy(self.request)
        selected, result, summary, trials = local_frame_candidates.run_candidates(
            self.request, ["z"], allow_adapt_frames=True, evaluate=receipt)
        self.assertEqual(len(trials), 5)
        self.assertEqual(self.request, frozen)
        self.assertEqual(original["edges"], self.request["edges"])

    def test_read_only_views_do_not_reclassify_readiness(self):
        decision = receipt(self.request)
        before = copy.deepcopy(decision)
        view = compact(decision)
        self.assertEqual(view["warnings"], decision["warnings"])
        self.assertEqual(view["ready"], decision["ready"])
        result = check({"page_job": "Compare peers", "reading_direction": "parallel",
                        "ungrouped_nodes": ["a", "b"]}, self.request)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["errors"], [])
        self.assertEqual(decision, before)

    def test_measured_peer_centerline_is_a_real_composer_finding(self):
        request = copy.deepcopy(self.request)
        request.pop("root")
        request["edges"] = []
        request["nodes"][0]["at"] = {"x": 100, "y": 300}
        request["nodes"][1]["at"] = {"x": 500, "y": 340}
        request["peer_sets"] = [{"ids": ["a", "b"], "equal_height": True,
                                 "axis": "horizontal", "align": "centerline"}]
        result = capacity_preflight.architecture(request)
        self.assertFalse(result["ready"])
        self.assertIn("peer_centerline_mismatch", {item["kind"] for item in result["blocking_constraints"]})
        request["nodes"][1]["at"]["y"] = 300
        self.assertTrue(capacity_preflight.architecture(request)["ready"])

    def test_raised_contract_floors_survive_defaults_and_reject_fixed_cards(self):
        canvas = {"template": str(self.template), "body_zone": self.body,
                  "type_floors": {"label_px_min": 15, "body_px_min": 18}}
        result = guided_build.normalized(self.request, canvas, "architecture", self.directory)
        self.assertEqual(result["type"]["sub_px"], 15)
        self.assertEqual(result["type"]["annotation_px"], 18)
        request = copy.deepcopy(self.request)
        request["type"] = {"annotation_px": 16}
        with self.assertRaisesRegex(ValueError, "annotation_px"):
            guided_build.normalized(request, canvas, "architecture", self.directory)
        request = {"page": {"body": self.body, "note_cards": {
            "strip": {"x": 64, "y": 560, "w": 1152, "h": 80}, "cards": [{}, {}, {}]}},
            "bounds": {"x": 64, "y": 208, "w": 1152, "h": 300}}
        with self.assertRaisesRegex(ValueError, "higher body floor"):
            prepare(request, body_px_min=18)

    def test_preflight_binds_contract_and_normalized_geometry(self):
        import hashlib
        decision = {"contract_sha256": hashlib.sha256(self.contract.read_bytes()).hexdigest(),
                    "normalized_request_sha256": sha256_json(self.request)}
        validate_preflight_fingerprints(decision, self.request, self.contract, required=True)
        changed = copy.deepcopy(self.request)
        changed["type"] = {"node_px": 20}
        with self.assertRaisesRegex(ValueError, "normalized_request_sha256 is stale"):
            validate_preflight_fingerprints(decision, changed, self.contract, required=True)
        self.contract.write_text(self.contract.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "contract_sha256 is stale"):
            validate_preflight_fingerprints(decision, self.request, self.contract, required=True)
        with self.assertRaisesRegex(ValueError, "missing contract_sha256"):
            validate_preflight_fingerprints({}, self.request, self.contract, required=True)
