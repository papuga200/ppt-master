#!/usr/bin/env python3
"""Planning-stage recovery preserves a pending CLI conversation and usage.

Run: python -m unittest tests.test_runner_stage_resume
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT / "hosts" / "responses_api"))
from deck_runner import Runner  # noqa: E402


class StageResumeTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.runner = Runner.__new__(Runner)
        self.runner.args = SimpleNamespace(session="delivery")
        self.runner.deck_dir = self.root
        self.runner.sessions = self.root
        self.runner.authors = {"frontier": {"model": "gpt-6.1-sol", "effort": "high"}}
        self.runner.session_tier = {}
        self.runner.page_sessions = {}
        self.runner.say = lambda message: None
        self.calls = []

    def state(self, pending):
        path = self.root / "delivery.planner" / "state.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"cli_session_id": "retained-id",
            "pending_input": [{"cli_continue": True}] if pending else [],
            "last_run": {"at_ceiling": pending}, "usage_total": {"calls": 33}}), encoding="utf-8")

    def host(self, session, tier, extra, *, stage):
        self.calls.append((session, extra, self.runner.authors[tier]["effort"]))
        self.state(False)
        return 0

    def test_existing_pending_stage_resumes_without_starting_new_task(self):
        self.state(True)
        self.runner.host = self.host
        self.assertEqual(self.runner.stage_host("planner", "Original task", effort="xhigh"), 0)
        self.assertEqual(self.calls, [("delivery.planner", ["--resume-pending"], "xhigh")])
        self.assertEqual(self.runner.authors["frontier"]["effort"], "high")
        saved = json.loads((self.root / "delivery.planner" / "state.json").read_text())
        self.assertEqual(saved["usage_total"]["calls"], 33)

    def test_new_stage_continues_after_a_ceiling(self):
        def capped_host(session, tier, extra, *, stage):
            self.calls.append(extra)
            self.state(len(self.calls) == 1)
            return 0
        self.runner.host = capped_host
        self.runner.stage_host("planner", "Original task")
        self.assertEqual(self.calls, [["--task-file", str(self.root / "planner.task.txt")],
                                     ["--resume-pending"]])

    def test_failure_does_not_retry_or_hide_pending_state(self):
        self.state(True)
        def failed_host(session, tier, extra, *, stage):
            self.calls.append(extra)
            return 1
        self.runner.host = failed_host
        self.assertEqual(self.runner.stage_host("planner", "Original task", effort="xhigh"), 1)
        self.assertEqual(self.calls, [["--resume-pending"]])
        self.assertTrue(self.runner.stage_pending("delivery.planner"))
        self.assertEqual(self.runner.authors["frontier"]["effort"], "high")

    def test_nonpending_session_starts_the_supplied_task(self):
        self.state(False)
        self.runner.host = self.host
        self.runner.stage_host("planner", "Original task")
        self.assertEqual(self.calls[0][1], ["--task-file", str(self.root / "planner.task.txt")])
