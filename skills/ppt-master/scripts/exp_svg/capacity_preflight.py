#!/usr/bin/env python3
"""PPT Master - Candidate capacity preflight.

Measure a full page without emitting an SVG. Architecture readiness belongs to
compose_page.evaluate; this wrapper preserves its findings and coverage.
See scripts/docs/experimental-authoring-tools.md for the portable contract.

Usage: python capacity_preflight.py --family architecture --in request.json --out preflight.json --contract canvas.json
Examples: use --workspace /project to retain a host-owned path boundary.
Dependencies: Pillow and existing architecture/timeline helpers.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
for directory in (HERE, HERE.parent):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
from console_encoding import configure_utf8_stdio  # noqa: E402
from exp_svg.contracts import add_contract_arguments, check_paths, load_contract  # noqa: E402
from exp_svg.guided_build import normalized  # noqa: E402
from exp_svg.arch._common import sha256_json  # noqa: E402

def architecture(value: dict) -> dict:
    sys.path.insert(0, str(HERE / 'arch'))
    import compose_page as cp
    evaluated = cp.evaluate(value)
    geometry = evaluated['result']
    residuals = evaluated['residual_constraints']
    bindings = [r for r in residuals if r.get('kind') == 'capacity']
    return {'status': 'capacity_failure' if bindings else 'capacity_fit' if evaluated['ready'] else 'partial',
            'body': geometry['page']['region'], 'spacing_scale': geometry['spacing_scale'],
            'binding': bindings, 'page_text_residuals': geometry['page']['residuals'],
            'capacity_fit': evaluated['capacity_fit'], 'ready': evaluated['ready'],
            'delivery_state': evaluated['delivery_state'],
            'blocking_constraints': evaluated['blocking_constraints'], 'warnings': evaluated['warnings'],
            'unsatisfied_constraints': residuals, 'geometry': geometry,
            'content_ids': evaluated['content_ids'], 'scene_sha256': evaluated['scene_sha256'],
            'coverage': evaluated['coverage']}

def timeline(value: dict) -> dict:
    sys.path.insert(0,str(HERE/'timeline'))
    import build_timeline as bt
    import page_compose
    req=copy.deepcopy(value)
    page=req.pop('page')
    style=req.setdefault('style',{})
    font={'family':style.get('font_family','Segoe UI')}
    if page.get('font_files'): font['files']=page['font_files']
    layout=page_compose.compose(page,font)
    if req.get('bounds') in (None,'auto'): req['bounds']=dict(layout['region'])
    style.setdefault('header','compact')
    if 'timeline_rev:2' in os.environ.get('PPT_MASTER_EXP_ENGINES',''): style.setdefault('rev2',True)
    built=bt.build(req,'timeline','dense')
    return {'status':built['status'],'body':layout['region'],'capacity':built.get('capacity'),
            'binding':(built.get('capacity') or {}).get('binding',[]),
            'errors':built.get('errors',[]),'unsatisfied_constraints':built.get('unsatisfied_constraints',[]),
            'page_text_residuals':layout['residuals'], 'measurement':built.get('measurement'),
            'coverage':'Pinned dense timeline engine candidate capacity and its placement residuals; no slide file or native export, independent factual/date verification still required.'}

def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser=argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--family',choices=['architecture','timeline'],required=True)
    parser.add_argument('--in',dest='request',required=True)
    parser.add_argument('--out',required=True)
    add_contract_arguments(parser)
    args=parser.parse_args(argv)
    source=Path(args.request).resolve(); target=Path(args.out).resolve()
    try:
        check_paths(source, [target], None)
    except ValueError as exc:
        print(f'capacity preflight: {exc}', file=sys.stderr)
        return 2
    started=time.perf_counter()
    result={'schema':'capacity-preflight/v1','family':args.family,'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'scope':'Candidate-specific preflight, not a universal maximum node/task capacity and not acceptance.'}
    paths_safe = False
    try:
        canvas, contract_path, workspace = load_contract(args)
        fixture = contract_path.parent
        check_paths(source, [target], workspace, resources=[contract_path, Path(canvas.get('template', fixture / 'template/content.svg'))])
        paths_safe = True
        value=normalized(json.loads(source.read_text(encoding='utf-8')),canvas,args.family,fixture)
        result['contract_sha256'] = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        result['normalized_request_sha256'] = sha256_json(value)
        result.update(architecture(value) if args.family=='architecture' else timeline(value))
    except (ValueError,KeyError,OSError,RuntimeError) as exc:
        if not paths_safe:
            print(f'capacity preflight: {exc}', file=sys.stderr)
            return 2
        result.update(status='request_error',error=str(exc))
    result['elapsed_ms']=round((time.perf_counter()-started)*1000,1)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary(result, target),ensure_ascii=True))
    return 2 if result['status']=='request_error' else 4 if result['status']=='capacity_failure' else 0

def summary(result: dict, target: Path) -> dict:
    """Keep geometry on disk and deliver the decision without truncation."""
    keys = ('schema', 'family', 'source_sha256', 'status', 'ready', 'delivery_state',
            'capacity_fit', 'body', 'coverage', 'error', 'elapsed_ms')
    value = {k: result[k] for k in keys if k in result}
    value['full_receipt_path'] = str(target)
    for key in ('blocking_constraints', 'warnings', 'binding', 'errors',
                'unsatisfied_constraints', 'page_text_residuals'):
        if key in result:
            items = result[key]
            value[key] = items[:8]
            value[key + '_total'] = len(items)
    return value


if __name__=='__main__': raise SystemExit(main())
