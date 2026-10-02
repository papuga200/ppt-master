#!/usr/bin/env python3
"""Verify the reference library's complete companion delivery through its CLI entry.

Run: python -m unittest tests.test_reference_companions
Dependencies: standard library and Pillow for curated images.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import reference_library


class ReferenceCompanionTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.library = self.root / "library"
        self.library.mkdir()
        (self.library / "preview.png").write_bytes(b"image fixture")
        self.content = '<svg>\n' + ('<text>Full source and mapping</text>\n' * 900) + '</svg>\n'
        (self.library / "source.svg").write_text(self.content, encoding="utf-8")
        self.entry = {"id": "example.good", "image": "preview.png", "verdict": "good",
                      "labels": {"communication_form": "architecture"},
                      "companions": {"source_svg": "source.svg"}}
        reference_library.save(self.library, [self.entry])
        self.addCleanup(self.scratch.cleanup)

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = reference_library.main([*args, "--library", str(self.library)])
        return code, output.getvalue()

    def test_show_exposes_source_and_companion_returns_complete_text(self):
        code, shown = self.run_cli("show", "example.good")
        self.assertEqual(code, 0)
        self.assertIn("companion example.good --kind source_svg", shown)
        code, delivered = self.run_cli("companion", "example.good", "--kind", "source_svg")
        self.assertEqual(code, 0)
        self.assertTrue(delivered.endswith(self.content))

    def test_legacy_entry_and_missing_companion_remain_nonfatal(self):
        self.entry.pop("companions")
        reference_library.save(self.library, [self.entry])
        self.assertEqual(self.run_cli("show", "example.good")[0], 0)
        code, delivered = self.run_cli("companion", "example.good", "--kind", "plan")
        self.assertEqual(code, 3)
        self.assertIn("available: none", delivered)

    def test_outside_library_paths_are_not_delivered(self):
        (self.root / "outside.md").write_text("unrelated source", encoding="utf-8")
        self.entry["companions"] = {"plan": "../outside.md"}
        reference_library.save(self.library, [self.entry])
        code, delivered = self.run_cli("companion", "example.good", "--kind", "plan")
        self.assertEqual(code, 3)
        self.assertNotIn("unrelated source", delivered)

    def test_curate_copies_complete_companions_to_external_library(self):
        from PIL import Image
        image = self.root / "teacher.png"
        Image.new("RGB", (8, 8), "white").save(image)
        source = self.root / "teacher.svg"
        source.write_text(self.content, encoding="utf-8")
        spec = self.root / "curation.json"
        spec.write_text(json.dumps({"entries": [{"id": "curated.one", "form": "architecture",
            "image_source": str(image), "companion_sources": {"source_svg": source.name}}]}), encoding="utf-8")
        code, _ = self.run_cli("curate", str(spec))
        self.assertEqual(code, 0)
        code, delivered = self.run_cli("companion", "curated.one", "--kind", "source_svg")
        self.assertEqual(code, 0)
        self.assertTrue(delivered.endswith(self.content))

    def test_rejected_companion_retains_counterexample_reason(self):
        self.entry.update(verdict="rejected", reason="Too much secondary detail")
        reference_library.save(self.library, [self.entry])
        code, delivered = self.run_cli("companion", "example.good", "--kind", "source_svg")
        self.assertEqual(code, 0)
        self.assertIn("COUNTEREXAMPLE (do not imitate): Too much secondary detail", delivered)
