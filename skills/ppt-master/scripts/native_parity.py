#!/usr/bin/env python3
"""The exporter's native Chart/Table gate on one page, as JSON on stdout.

    native_parity.py <page.svg>

`svg_to_pptx.py --native-charts-and-tables` refuses a deck when a table's or chart's visible SVG fallback carries text or styling that
its JSON payload does not project (`_native_object_projection_findings`). page_lint runs this in the background while a page renders,
so the author fixes a mismatch while drawing instead of in a repair round after the deck is exported. Prints
`[{"marker": ..., "finding": ...}, ...]` (empty when the page is clean or has no native object).

A page with a native table also gets native_table_wrap's prediction of where PowerPoint will wrap its cells differently from the
browser preview (F03 cycle 2); those items are page_lint findings already: `{"kind": "NATIVE_WORD_SPLIT", "severity", "hard",
"rect", "message", ...}`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    svg = Path(sys.argv[1])
    if "data-pptx-replace-with=" not in svg.read_text(encoding="utf-8", errors="replace"):
        print("[]")
        return 0
    from svg_to_pptx.pptx_package.cli import _native_object_projection_findings
    items: list[dict] = [{"marker": marker, "finding": finding} for _, marker, finding in _native_object_projection_findings([svg])]
    items.extend(table_wrap_findings(svg))
    print(json.dumps(items, ensure_ascii=False))
    return 0


def table_wrap_findings(svg: Path) -> list[dict]:
    """Where PowerPoint will wrap this page's native table cells differently from the preview; nothing when it cannot tell."""
    try:
        import native_table_wrap
        return native_table_wrap.predict(svg)
    except Exception:  # noqa: BLE001 - a prediction that fails must never block the page; pptx_parity still measures after export
        return []


if __name__ == "__main__":
    sys.exit(main())
