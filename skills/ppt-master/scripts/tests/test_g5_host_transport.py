#!/usr/bin/env python3
"""Verify bounded host transport without model, provider, or subprocess calls.

Usage: python -m unittest tests.test_g5_host_transport
Dependencies: standard library only.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HOST_PATH = Path(__file__).resolve().parents[4] / "hosts/responses_api/host.py"
SPEC = importlib.util.spec_from_file_location("g5_transport_host", HOST_PATH)
HOST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOST)


class HostTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.scripts = self.root / "skills/ppt-master/scripts"
        self.scripts.mkdir(parents=True)
        (self.scripts / "allowed.py").write_text("", encoding="utf-8")
        self.addCleanup(patch.stopall)
        patch.object(HOST, "ROOT", self.root).start()
        patch.object(HOST, "SCRIPTS", self.scripts).start()
        patch.object(HOST, "READ_DENY", ["skills/ppt-master/scripts/*.py"]).start()
        patch.dict(os.environ, {
            "PPT_MASTER_READ_ROOTS": "project;skills/ppt-master/scripts",
            "PPT_MASTER_WRITE_ROOTS": "project/svg_output",
            "PPT_MASTER_SCRIPT_ALLOWLIST": "allowed.py",
            "PPT_MASTER_PROJECT_PATH": "project",
        }).start()
        patch.object(HOST, "_env_for_scripts", return_value={}).start()

    def write(self, text, name="data.json"):
        target = self.workspace / name
        target.write_bytes(text.encode("utf-8"))
        return target.relative_to(self.root).as_posix()

    def reconstruct(self, path, initial=None):
        pages = []
        offset = 0
        while True:
            raw = initial if initial is not None else HOST.tool_read_file(path, offset=offset, limit=30000)
            initial = None
            self.assertLessEqual(len(raw), HOST.MAX_TOOL_OUTPUT)
            page = json.loads(raw)
            self.assertEqual(page["type"], "text_page")
            self.assertEqual(page["offset"], offset)
            self.assertEqual(page["length"], len(page["content"]))
            pages.append(page["content"])
            if page["complete"]:
                self.assertIsNone(page["next_offset"])
                break
            self.assertGreater(page["next_offset"], offset)
            offset = page["next_offset"]
        text = "".join(pages)
        self.assertEqual(len(text), page["total_chars"])
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), page["sha256"])
        return text

    def test_short_legacy_read_and_line_range(self):
        path = self.write('{"ok": true}\n')
        self.assertEqual(json.loads(HOST.tool_read_file(path)), {"ok": True})
        path = self.write("first\r\nsecond\r\n")
        self.assertEqual(HOST.tool_read_file(path, start=2, end=2), "second")
        self.assertEqual(self.reconstruct(path), "first\r\nsecond\r\n")

    def test_large_unicode_json_round_trip(self):
        text = json.dumps({"items": "汉字🙂" * 30000}, ensure_ascii=False)
        path = self.write(text)
        initial = HOST.tool_read_file(path)
        self.assertFalse(json.loads(initial)["complete"])
        self.assertEqual(json.loads(self.reconstruct(path, initial)), json.loads(text))

    def test_serialized_escaping_stays_bounded(self):
        text = "\x00\n\\\"" * 30000
        path = self.write(text)
        self.assertEqual(self.reconstruct(path), text)
        self.assertEqual(json.loads(HOST.tool_read_file(path, offset=len(text)))["content"], "")

    def test_invalid_selectors_and_unexpected_fields(self):
        path = self.write("text")
        for kwargs in ({"start": 1, "offset": 0}, {"end": 1, "limit": 2},
                       {"offset": -1}, {"offset": 5}, {"limit": 0}, {"offset": True}):
            with self.assertRaises(ValueError):
                HOST.tool_read_file(path, **kwargs)
        with self.assertRaises(TypeError):
            HOST.tool_read_file(path, unexpected=True)

    def test_read_guards_and_write_guards_remain(self):
        with self.assertRaises(ValueError):
            HOST.tool_read_file("../outside.txt", offset=0)
        blocked = self.root / "other.txt"
        blocked.write_text("secret", encoding="utf-8")
        with self.assertRaises(ValueError):
            HOST.tool_read_file("other.txt", offset=0)
        self.assertIn("not readable", HOST.tool_read_file("skills/ppt-master/scripts/allowed.py", offset=0))
        with self.assertRaises(ValueError):
            HOST.tool_write_file("project/work/tool-results/author.txt", "forbidden")

    def test_script_short_behavior_and_error_streams(self):
        proc = subprocess.CompletedProcess([], 7, '{"ok":false}\n', "failure\n")
        with patch.object(HOST.subprocess, "run", return_value=proc) as run:
            result = HOST.tool_run_script("allowed.py")
        self.assertIn("exit 7", result)
        self.assertIn('--- stdout ---\n{"ok":false}\n', result)
        self.assertIn("--- stderr ---\nfailure\n", result)
        self.assertEqual(run.call_count, 1)

    def test_legacy_wait_argument_does_not_kill_nested_model_work(self):
        proc = subprocess.CompletedProcess([], 0, "review complete", "")
        with patch.object(HOST.subprocess, "run", return_value=proc) as run:
            HOST.tool_run_script("allowed.py", timeout_s=120)
        self.assertIsNone(run.call_args.kwargs["timeout"])

    def test_script_large_output_retained_and_json_parseable(self):
        text = json.dumps({"data": "汉🙂" * 40000}, ensure_ascii=False)
        err = "error\r\n" * 12000
        proc = subprocess.CompletedProcess([], 9, text, err)
        with patch.object(HOST.subprocess, "run", return_value=proc):
            raw = HOST.tool_run_script("allowed.py", ["project/data.json"])
        self.assertLess(len(raw), HOST.MAX_TOOL_OUTPUT)
        ref = json.loads(raw)
        self.assertEqual(ref["type"], "script_output_reference")
        self.assertEqual(ref["exit_code"], 9)
        for name, expected in (("stdout", text), ("stderr", err)):
            stream = ref[name]
            self.assertTrue(stream["path"].startswith("project/work/tool-results/"))
            self.assertEqual(stream["bytes"], len(expected.encode("utf-8")))
            self.assertEqual(self.reconstruct(stream["path"]), expected)
        self.assertEqual(json.loads(self.reconstruct(ref["stdout"]["path"])), json.loads(text))

    def test_script_guards_before_execution(self):
        with patch.object(HOST.subprocess, "run") as run:
            for script, args in (("other.py", []), ("../outside.py", []),
                                 ("allowed.py", ["../outside.json"]),
                                 ("allowed.py", ["--input=other/file.json"])):
                with self.assertRaises(ValueError):
                    HOST.tool_run_script(script, args)
            run.assert_not_called()

    def test_tool_schema_exposes_paging(self):
        tool = next(tool for tool in HOST.TOOLS if tool["name"] == "read_file")
        self.assertTrue({"offset", "limit"}.issubset(tool["parameters"]["properties"]))
        self.assertIn("next_offset", tool["description"])

    def test_first_draft_guard_remains(self):
        page = self.workspace / "svg_output/01.svg"
        page.parent.mkdir()
        page.write_text("first", encoding="utf-8")
        fixture = self.workspace / "inputs/fixture/canvas.json"
        fixture.parent.mkdir(parents=True)
        fixture.write_text('{"first_draft_only":true}', encoding="utf-8")
        with patch.dict(os.environ, {"PPT_MASTER_PAGE_FILE": "project/svg_output/01.svg"}):
            with self.assertRaises(ValueError):
                HOST.tool_write_file("project/svg_output/01.svg", "second")
            with self.assertRaises(ValueError):
                HOST.tool_edit_file("project/svg_output/01.svg", "first", "second")
        self.assertEqual(page.read_text(encoding="utf-8"), "first")

    def test_artifact_location_cannot_escape_read_roots(self):
        proc = subprocess.CompletedProcess([], 1, "x" * 70000, "")
        with patch.dict(os.environ, {"PPT_MASTER_PROJECT_PATH": "other"}), \
                patch.object(HOST.subprocess, "run", return_value=proc):
            with self.assertRaises(ValueError):
                HOST.tool_run_script("allowed.py")
        self.assertFalse((self.root / "other").exists())

    def test_oversized_line_range_is_explicit_error(self):
        path = self.write("x" * 70000 + "\nsecond")
        with self.assertRaisesRegex(ValueError, "character"):
            HOST.tool_read_file(path, start=1, end=1)
