#!/usr/bin/env python3
"""The exporter's native Chart/Table gate on one page, as JSON on stdout.

    native_parity.py <page.svg>

`svg_to_pptx.py --native-charts-and-tables` refuses a deck when a table's or chart's visible SVG fallback carries text or styling that
its JSON payload does not project (`_native_object_projection_findings`). page_lint runs this in the background while a page renders,
so the author fixes a mismatch while drawing instead of in a repair round after the deck is exported. Prints
`[{"marker": ..., "finding": ...}, ...]` (empty when the page is clean or has no native object).
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
    print(json.dumps([{"marker": marker, "finding": finding} for _, marker, finding in _native_object_projection_findings([svg])]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
