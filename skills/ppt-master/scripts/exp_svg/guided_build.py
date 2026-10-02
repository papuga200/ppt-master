#!/usr/bin/env python3
"""PPT Master - Contract-guided whole-page creation.

Validate an explicit page contract before calling the architecture or timeline creator.
See scripts/docs/experimental-authoring-tools.md for the portable contract.

Usage: python guided_build.py --family architecture --in request.json --out receipt.json --page page.svg --contract canvas.json
Examples: pass --preflight-receipt preflight.json when the contract requires measured source geometry.
Dependencies: Pillow and the existing whole-page creators.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import copy
import hashlib
import json
import math
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from console_encoding import configure_utf8_stdio  # noqa: E402
from exp_svg.contracts import (  # noqa: E402
    add_contract_arguments,
    check_paths,
    load_contract,
    validate_preflight_fingerprints,
)

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def validate_source_layout_receipt(preflight: dict, canvas: dict, family: str) -> None:
    """Consume the evaluator's architecture decision; never reclassify residuals."""
    if family != 'architecture' or not canvas.get('source_layout_preflight_required'):
        return
    if not isinstance(preflight.get('geometry'), dict) or preflight.get('capacity_fit') is not True:
        raise ValueError('Measured whole-page source geometry is required before the first architecture write.')
    state = preflight.get('delivery_state')
    if state == 'requires_external_geometry_audit':
        raise ValueError('Source evaluator requires an external geometry audit; raw SVG is not certified. Use measured helper geometry or a separately audited creation route.')
    if state != 'ready' or preflight.get('ready') is not True:
        raise ValueError('Source evaluator has not marked this layout ready; resolve its blocking_constraints or rerun preflight for a legacy receipt before first write.')

def _validate_timeline_bounds(bounds, canonical):
    """Keep an explicit chart rectangle inside the immutable full page body."""
    if bounds is None or bounds == 'auto':
        return
    if not isinstance(bounds, dict):
        raise ValueError('bounds must be an object with x, y, w, h, or null/"auto"; omit it to use page.body')
    coordinates = {}
    for key in ('x', 'y', 'w', 'h'):
        number = bounds.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise ValueError(f'bounds.{key} must be a finite number')
        try:
            finite = math.isfinite(number)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f'bounds.{key} must be a finite number')
        if key in ('w', 'h') and number <= 0:
            raise ValueError(f'bounds.{key} must be positive')
        coordinates[key] = number
    if (coordinates['x'] < canonical['x'] or coordinates['y'] < canonical['y']
            or coordinates['x'] + coordinates['w'] > canonical['x'] + canonical['w']
            or coordinates['y'] + coordinates['h'] > canonical['y'] + canonical['h']):
        raise ValueError(f'bounds must lie entirely inside immutable page.body {canonical}; '
                         'keep page.body unchanged and reallocate the chart bounds')

def normalized(request: dict, canvas: dict, family: str, fixture: Path) -> dict:
    value = copy.deepcopy(request)
    page = value.get('page', {})
    canonical = canvas['body_zone']
    if any(float(page.get('body', {}).get(key, -1)) != float(canonical[key]) for key in ('x', 'y', 'w', 'h')) or page.get('body', {}).get('fit'):
        raise ValueError(f'page.body must exactly match immutable fixture {canonical}; no between_texts override')
    template = Path(page.get('template', '')).resolve()
    expected = Path(canvas['template']).resolve() if canvas.get('template') else (fixture / 'template/content.svg').resolve()
    if template != expected:
        raise ValueError('page.template must point to the contract template (or legacy fixture template/content.svg)')
    floors = canvas['type_floors']
    if family == 'architecture':
        if canvas.get('native_editability_required'):
            value.setdefault('style', {})['native_text_ownership'] = True
            value['style']['node_text'] = 'combined'
        typ = value.setdefault('type', {})
        for key in ('node_px', 'sub_px', 'edge_label_px', 'zone_label_px', 'legend_px'):
            if key in typ and float(typ[key]) < floors['label_px_min'] - .01:
                raise ValueError(f'{key} falls below fixture label floor')
            typ.setdefault(key, max(16.0 if key == 'node_px' else 13.333, floors['label_px_min']))
        body_floor = floors.get('body_px_min', 16)
        if 'annotation_px' in typ and float(typ['annotation_px']) < body_floor - .01:
            raise ValueError('annotation_px falls below contract body floor')
        typ.setdefault('annotation_px', max(16.0, body_floor))
        for node in value.get('nodes', []):
            node['min_h'] = max(float(node.get('min_h', 0)), 44)
    else:
        _validate_timeline_bounds(value.get('bounds'), canonical)
        if canvas.get('native_editability_required'):
            value.setdefault('style', {})['native_text_ownership'] = True
        floor = floors.get('timeline_chart_label_px_min', floors['label_px_min'])
        if float(value.get('floors', {}).get('label_px', floor)) < floor - .01:
            raise ValueError('timeline chart label floor below immutable fixture')
        value.setdefault('floors', {})['label_px'] = floor
        body_floor = floors.get('body_px_min', 16)
        if float(value['floors'].get('body_px', body_floor)) < body_floor - .01:
            raise ValueError('timeline body_px floor below immutable contract; fixed 16 px note cards cannot satisfy a higher floor')
        value['floors'].setdefault('body_px', body_floor)
        style = value.setdefault('style', {})
        style.setdefault('bar_mode', 'labelled')
        constraints = canvas.get('layout_constraints') or {}
        key = 'labelled_bar_padding_y_min_px'
        if key in constraints:
            padding_floor = constraints[key]
            if (isinstance(padding_floor, bool) or not isinstance(padding_floor, (int, float))
                    or not math.isfinite(padding_floor) or padding_floor < 0):
                raise ValueError(f'layout_constraints.{key} must be a finite non-negative number')
            if style['bar_mode'] != 'thin':
                requested_floor = style.get('bar_pad_y_min', padding_floor)
                if (isinstance(requested_floor, bool) or not isinstance(requested_floor, (int, float))
                        or not math.isfinite(requested_floor) or requested_floor < 0):
                    raise ValueError('style.bar_pad_y_min must be a finite non-negative number')
                style['bar_pad_y_min'] = max(padding_floor, requested_floor)
        if style['bar_mode'] == 'thin' and float(style.get('bar_h_thin', 10)) < 8:
            raise ValueError('thin bars below experiment visible-bar minimum 8px; revise label/lane allocation')
    return value

def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--family', required=True, choices=['architecture', 'timeline'])
    parser.add_argument('--in', dest='request', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--page', required=True)
    parser.add_argument('--preflight-receipt', help='matching capacity receipt, required by first-draft-only fixtures')
    add_contract_arguments(parser)
    args = parser.parse_args(argv)
    request = Path(args.request).resolve()
    output = Path(args.out).resolve()
    receipt_path = output.with_suffix('.contract.json')
    paths_safe = False
    try:
        canvas, canvas_path, workspace = load_contract(args)
        fixture = canvas_path.parent
        check_paths(request, [output, Path(args.page), receipt_path, output.with_suffix('.request.json')],
                    workspace, resources=[canvas_path, Path(canvas.get('template', fixture / 'template/content.svg'))])
        paths_safe = True
        output.parent.mkdir(parents=True, exist_ok=True)
        req = normalized(json.loads(request.read_text(encoding='utf-8')), canvas, args.family, fixture)
        if canvas.get('first_draft_only'):
            if Path(args.page).exists():
                raise ValueError('First slide already exists and is frozen; no regeneration or repair.')
        requires_receipt = canvas.get('first_draft_only') or (args.family == 'architecture' and canvas.get('source_layout_preflight_required'))
        if requires_receipt:
            if not args.preflight_receipt:
                raise ValueError('Run capacity_preflight.py on this exact candidate before first-draft creation; pass --preflight-receipt.')
            preflight = json.loads(Path(args.preflight_receipt).read_text(encoding='utf-8'))
            if preflight.get('source_sha256') != sha(request) or preflight.get('family') != args.family:
                raise ValueError('Preflight receipt does not describe this exact request and family.')
            validate_preflight_fingerprints(preflight, req, canvas_path, required=bool(args.contract))
            if args.family == 'architecture' and canvas.get('source_layout_preflight_required'):
                validate_source_layout_receipt(preflight, canvas, args.family)
            elif preflight.get('status') not in ('capacity_fit', 'ok', 'partial') or preflight.get('binding') or preflight.get('errors') or preflight.get('page_text_residuals'):
                # Preserve the narrower timeline and historical fixture policies.
                raise ValueError('Preflight has unresolved capacity or page-text findings; reallocate before emitting the first SVG.')
    except (OSError, ValueError, KeyError) as exc:
        if paths_safe:
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps({'status': 'contract_failure', 'error': str(exc)}) + '\n', encoding='utf-8')
        print(f'CONTRACT FAILURE: {exc}; receipt={receipt_path}', file=sys.stderr)
        return 2
    resolved = output.with_suffix('.request.json')
    resolved.write_text(json.dumps(req, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    receipt = {'status': 'contract_match', 'fixture_sha256': sha(canvas_path), 'original_request_sha256': sha(request),
               'resolved_request_sha256': sha(resolved), 'resolved_request': str(resolved),
               'body': canvas['body_zone'], 'declared_shape_policy': 'architecture node min44px; timeline thin bar min8px, labelled default'}
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    target = Path(__file__).parent / ('arch/compose_page.py' if args.family == 'architecture' else 'timeline/build_timeline.py')
    return subprocess.call([sys.executable, str(target), '--in', str(resolved), '--out', str(output), '--page', str(Path(args.page).resolve())])

if __name__ == '__main__':
    raise SystemExit(main())
