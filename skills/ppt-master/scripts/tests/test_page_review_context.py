"""Verify reviewer input retains declared constraints without importing the whole plan."""
import argparse
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import page_review


SPEC = """# Example
## I. Project Information
| Item | Value |
| --- | --- |
| Target Audience | Executive decision makers |
| Communication Intent | Decide on a bounded pilot |
| Delivery Context | Presented, then read without the presenter |
| Artifact Afterlife | Proposal of record |
| Reading Mode | text |
| AI Image Acquisition Path | private-unrelated-resource |
## II. Canvas Specification
| Dimensions | 1280 × 720 |
| Body content area | x=52..1228, y=158..666 |
## III. Visual Theme
Unrelated theme prose.
## IV. Typography System
### Font Plan
Segoe UI.
### Font Size Hierarchy
| Annotation / diagram label / table cell | 14 |
Body never below 16 px; labels never below 14 px.
## V. Layout Principles
Unrelated composition prose.
## IX. Content Outline
#### Slide 01 - Example
Audience question: What is funded?
#### Slide 02 - Other page
Other-page private content.
"""


class ReviewContextTests(unittest.TestCase):
    def test_context_retains_reader_canvas_and_type_without_other_plan_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "design_spec.md").write_text(SPEC, encoding="utf-8")
            context = page_review._deck_review_context(project)
            for value in ("Reading Mode | text", "Executive decision makers", "1280 × 720",
                          "y=158..666", "Segoe UI", "labels never below 14 px"):
                self.assertIn(value, context)
            for value in ("private-unrelated-resource", "Unrelated theme", "Unrelated composition",
                          "Other-page private content", "Audience question"):
                self.assertNotIn(value, context)

    def test_missing_spec_does_not_invent_constraints(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(page_review._deck_review_context(Path(directory)), "")

    def test_missing_type_section_does_not_capture_neighboring_content(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "design_spec.md").write_text(
                "## II. Canvas Specification\n1280 × 720\n## V. Layout Principles\nprivate layout\n",
                encoding="utf-8")
            self.assertEqual(page_review._deck_review_context(project),
                             "## II. Canvas Specification\n1280 × 720")

    def test_review_payload_delivers_context_and_preserves_current_image_verdict(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "svg_output").mkdir()
            (project / ".preview").mkdir()
            svg = project / "svg_output" / "01_example.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
            (project / ".preview" / "01_example.png").write_bytes(b"stub-image")
            (project / "design_spec.md").write_text(SPEC, encoding="utf-8")
            digest = hashlib.sha256(svg.read_bytes()).hexdigest()
            journal = page_review.load_journal(project)
            journal["pages"][svg.stem] = {"renders": 1, "last_sha": digest,
                                           "backups": [{"rev": 0}], "revisions": 0}
            page_review.save_journal(project, journal)
            with patch.object(page_review, "_review_call", return_value=(
                    "VERDICT: EXECUTION_REPAIR\nBLOCKERS: 1", {})) as call:
                self.assertEqual(page_review.cmd_review(argparse.Namespace(
                    project=str(project), page=svg.stem)), 0)
            payload = call.call_args.args[0]
            supplied = "\n".join(item.get("text", "") for item in payload["input"][0]["content"])
            self.assertIn("DECLARED DECK CONTEXT", supplied)
            self.assertIn("Reading Mode | text", supplied)
            self.assertIn("Audience question: What is funded?", supplied)
            self.assertNotIn("Other-page private content", supplied)
            review = page_review.load_journal(project)["pages"][svg.stem]["review"]
            self.assertEqual(review["sha"], digest)
            self.assertEqual((review["verdict"], review["blockers"]), ("EXECUTION_REPAIR", 1))
            with self.assertRaises(SystemExit):
                page_review.cmd_note(argparse.Namespace(project=str(project), page=svg.stem,
                    outcome="accepted", text="Do not bypass the defect", no_review=False))
