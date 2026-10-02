#!/usr/bin/env python3
"""PPT Master - Contract-guided font measurement.

Measure labels with contract-owned role floors and retain concise geometry and font evidence.
See scripts/docs/experimental-authoring-tools.md for the portable contract.

Usage: python guided_measure.py --in labels.json --out measured.json --contract canvas.json
Examples: use measure_labels.py directly when no page contract floors are required.
Dependencies: Pillow through the architecture measurement helper.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
for directory in (HERE/'arch', HERE.parent):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
import measure_labels as measure  # noqa: E402
from console_encoding import configure_utf8_stdio  # noqa: E402
from exp_svg.contracts import add_contract_arguments, check_paths, load_contract  # noqa: E402

def label_summary(label: dict) -> dict:
    """Keep geometry and measurement provenance together in the concise result."""
    fields = ('id', 'role', 'size_px', 'weight', 'lines', 'line_widths_px', 'width_px', 'height_px',
              'text_band_height_px', 'layout_height_px', 'line_pitch_px', 'max_width', 'floor',
              'font', 'measurement', 'verification', 'browser_line_widths_px', 'browser_delta_px',
              'browser_font_present', 'warnings')
    return {key: label[key] for key in fields if key in label}

def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser=argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--in',dest='request',required=True)
    parser.add_argument('--out',required=True)
    add_contract_arguments(parser)
    args=parser.parse_args(argv)
    source=Path(args.request).resolve();target=Path(args.out).resolve()
    canvas, contract_path, workspace = load_contract(args)
    check_paths(source, [target, target.with_suffix('.summary.json')], workspace, resources=[contract_path])
    floors=canvas['type_floors']
    def role_floor(role):
        if role=='body':return float(floors['body_px_min'])
        if role=='furniture':return float(floors['label_px_min'])
        return float(floors.get('timeline_chart_label_px_min',floors['label_px_min']))
    started=time.perf_counter()
    request = json.loads(source.read_text(encoding='utf-8'))
    measure.validate_guided_request(request)
    previous_floor = measure.role_floor
    try:
        measure.role_floor=role_floor
        labels,residuals=measure.measure_request(request)
    finally:
        measure.role_floor = previous_floor
    value={'schema':'guided-measure/v1','status':'partial' if residuals else 'ok',
           'request_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'fixture_floors':floors,
           'labels':labels,'residuals':residuals,'elapsed_ms':round((time.perf_counter()-started)*1000,1)}
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={'schema':'guided-measure-summary/v1','status':value['status'],
             'labels':[label_summary(label) for label in labels],
             'residuals':residuals,'full_result':str(target),'elapsed_ms':value['elapsed_ms']}
    summary_path=target.with_suffix('.summary.json')
    summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=True))
    return 3 if residuals else 0

if __name__=='__main__':raise SystemExit(main())
