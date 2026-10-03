"""Exercise page/repair scheduling without starting models or rendering slides."""

import contextlib
import io
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_ROOT / "hosts" / "responses_api"))
import deck_runner  # noqa: E402
from page_review import load_journal, update_journal  # noqa: E402


class ParallelRunnerTests(unittest.TestCase):
    def runner(self, limit=0):
        runner = deck_runner.Runner.__new__(deck_runner.Runner)
        runner.args = SimpleNamespace(max_parallel=limit)
        return runner

    def starts_before_release(self, limit, count, expected):
        condition = threading.Condition()
        release = threading.Event()
        started = []
        failures = []

        def job(number):
            with condition:
                started.append(number)
                condition.notify_all()
            release.wait()

        def run():
            try:
                self.runner(limit).fan_out([lambda n=n: job(n) for n in range(count)])
            except BaseException as exc:
                failures.append(exc)

        worker = threading.Thread(target=run)
        worker.start()
        try:
            with condition:
                self.assertTrue(condition.wait_for(lambda: len(started) >= expected, timeout=5))
                self.assertEqual(len(started), expected)
        finally:
            release.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(failures)
        self.assertEqual(set(started), set(range(count)))

    def test_all_ready_jobs_start_without_waiting_for_a_page_to_finish(self):
        self.starts_before_release(0, 26, 26)

    def test_explicit_cap_queues_the_remaining_jobs(self):
        self.starts_before_release(3, 8, 3)

    def test_empty_round_needs_no_executor(self):
        with patch.object(deck_runner.concurrent.futures, "ThreadPoolExecutor") as pool:
            self.runner().fan_out([])
            pool.assert_not_called()

    def test_worker_failure_is_propagated_and_other_jobs_finish(self):
        done = []

        def fail():
            raise RuntimeError("page failed")

        with self.assertRaisesRegex(RuntimeError, "page failed"):
            self.runner().fan_out([fail, lambda: done.append("other page")])
        self.assertEqual(done, ["other page"])

    def test_all_jobs_keep_their_shared_journal_updates(self):
        with tempfile.TemporaryDirectory() as scratch:
            project = Path(scratch)

            def write(number):
                def change(journal):
                    journal["pages"][str(number)] = {"outcome": "accepted"}
                update_journal(project, change)

            self.runner().fan_out([lambda n=n: write(n) for n in range(26)])
            journal = load_journal(project)
            self.assertEqual(len(journal["pages"]), 26)
            self.assertTrue(all(p["outcome"] == "accepted" for p in journal["pages"].values()))

    def test_cli_defaults_to_all_ready_jobs(self):
        with patch.object(sys, "argv", ["deck_runner.py", "project", "--session", "test"]):
            with patch.object(deck_runner, "Runner") as constructor:
                constructor.return_value.run.return_value = 0
                self.assertEqual(deck_runner.main(), 0)
                self.assertEqual(constructor.call_args.args[0].max_parallel, 0)

    def test_cli_rejects_negative_cap_before_starting_a_runner(self):
        with patch.object(sys, "argv", ["deck_runner.py", "project", "--session", "test",
                                        "--max-parallel", "-1"]):
            with patch.object(deck_runner, "Runner") as constructor, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    deck_runner.main()
                self.assertEqual(caught.exception.code, 2)
                constructor.assert_not_called()
