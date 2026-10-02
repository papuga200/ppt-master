#!/usr/bin/env python3
"""Read-only correspondence check for an author's logical plan and measured scene.

This proves declared memberships and reading order, not semantic appropriateness
or visual quality. It neither changes layout nor adds a second readiness gate.


See scripts/docs/experimental-authoring-tools.md for tool contracts.
Usage: python organization_check.py --help
Examples: use current measured JSON; no slide is written.
Dependencies: standard library and Pillow through architecture evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import sys
_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from console_encoding import configure_utf8_stdio  # noqa: E402


def check(plan: dict, request: dict, receipt: dict | None = None) -> dict:
    errors, warnings = [], []
    zones = {z['id']: z for z in request.get('zones', [])}
    nodes = {n['id']: n for n in request.get('nodes', [])}
    groups = plan.get('groups', [])
    ids = [g['id'] for g in groups]
    direction = plan.get('reading_direction', 'nonlinear')
    if not plan.get('page_job'):
        warnings.append('Declare a page job when checking semantic correspondence.')
    if direction not in {'left-to-right', 'right-to-left', 'top-to-bottom', 'bottom-to-top', 'parallel', 'nonlinear'}:
        errors.append('reading_direction must be left-to-right, right-to-left, top-to-bottom, bottom-to-top, parallel or nonlinear.')
    if len(ids) != len(set(ids)):
        errors.append('Logical group IDs must be unique.')
    owners = {}
    for g in groups:
        gid = g['id']
        z = zones.get(gid)
        if not z:
            errors.append(f'Planned group {gid} is missing from scene.zones.')
            continue
        if (g.get('parent') or None) != (z.get('parent') or None):
            errors.append(f'Parent mismatch for {gid}.')
        if g.get('visible', True) and (z.get('kind') == 'group' or not z.get('label')):
            errors.append(f'{gid} promises a visible captioned boundary but is invisible/unlabelled.')
        if not g.get('role'):
            warnings.append(f'{gid} has no declared functional role.')
        for nid in g.get('members', []):
            if nid in owners:
                errors.append(f'{nid} has multiple direct group owners.')
            owners[nid] = gid
            if nid not in nodes or nodes[nid].get('zone') != gid:
                errors.append(f'Node {nid} does not belong to planned group {gid} in scene.')
        seen, parent = {gid}, g.get('parent')
        while parent:
            if parent in seen:
                errors.append(f'Parent cycle involving {gid}.')
                break
            seen.add(parent)
            target = next((x for x in groups if x['id'] == parent), None)
            if target is None:
                errors.append(f'Undeclared parent {parent} for {gid}.')
                break
            parent = target.get('parent')
    ungrouped = plan.get('ungrouped_nodes', [])
    for nid in ungrouped:
        if nid in owners:
            errors.append(f'{nid} is both grouped and declared ungrouped.')
        elif nid not in nodes:
            errors.append(f'Unknown ungrouped node {nid}.')
        elif nodes[nid].get('zone'):
            errors.append(f'Node {nid} is declared ungrouped but belongs to scene zone {nodes[nid]["zone"]}.')
    for nid in nodes:
        if nid not in owners and nid not in ungrouped:
            warnings.append(f'Node {nid} has no declared correspondence mapping.')
    stages = plan.get('primary_stages', [])
    if not isinstance(stages, list) or any(not isinstance(s, list) or not s for s in stages):
        errors.append('primary_stages, when supplied, must contain non-empty ID arrays.')
        stages = []
    all_ids = set(nodes) | set(zones)
    for stage in stages:
        if isinstance(stage, list):
            for i in stage:
                if i not in all_ids:
                    errors.append(f'Primary stage references unknown item {i}.')
    measured = []
    if receipt:
        boxes = receipt.get('result', receipt.get('geometry', {})).get('boxes', {})
        for stage in stages:
            values = []
            for i in stage:
                b = boxes.get(i)
                if not b:
                    warnings.append(f'No measured box for primary item {i}.')
                    continue
                axis = 'y' if direction in {'top-to-bottom', 'bottom-to-top'} else 'x'
                size = 'h' if axis == 'y' else 'w'
                values.append(b[axis] + b[size] / 2)
            measured.append(sum(values) / len(values) if values else None)
        for a, b in zip(measured, measured[1:]):
            reverse = direction in {'right-to-left', 'bottom-to-top'}
            if (direction not in {'parallel', 'nonlinear'} and a is not None and b is not None
                    and (b > a + 2 if reverse else b < a - 2)):
                warnings.append(f'A declared stage moves backwards in the measured {direction} path.')
    return {'status': 'mismatch' if errors else 'matched', 'errors': errors,
            'warnings': warnings, 'declared_groups': len(groups),
            'declared_nodes': len(owners), 'scene_nodes': len(nodes),
            'primary_stage_centres': measured, 'reading_direction': direction,
            'scope': 'Correspondence diagnostics only. No layout mutations, readiness decision, semantic/aesthetic acceptance, or native-export proof.'}


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--plan', type=Path, required=True)
    ap.add_argument('--request', type=Path, required=True)
    ap.add_argument('--receipt', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args(argv)
    inputs = [p for p in (a.plan, a.request, a.receipt) if p]
    if any(a.out.resolve() == p.resolve() for p in inputs):
        ap.error('Output must not replace an input.')
    data = [json.loads(p.read_text(encoding='utf-8-sig')) for p in inputs]
    result = check(*data)
    result['input_hashes'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
