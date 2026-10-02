#!/usr/bin/env python3
"""PPT Master - Bounded architecture fitting within a chosen composition.

No SVG is emitted. Text, facts, topology, membership, fonts and pinned ports
are immutable. Only caller-authorized gaps and outer node widths may vary.

Usage: python fit_candidates.py --in request.json --out-dir fit --contract canvas.json --allow-gaps
Examples: permit --allow-node-widths only when the authored wrapping budget is flexible.
Dependencies: Pillow through architecture evaluation.
"""
from __future__ import annotations
import copy
import itertools
import time
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from console_encoding import configure_utf8_stdio  # noqa: E402
from exp_svg.capacity_preflight import architecture, summary  # noqa: E402
from exp_svg.contracts import add_contract_arguments, check_paths, load_contract  # noqa: E402
from exp_svg.guided_build import normalized  # noqa: E402
from exp_svg.arch._common import sha256_json  # noqa: E402


def candidates(seed: dict, *, allow_gaps: bool = False, allow_node_widths: bool = False):
    """Yield seed first, then at most 26 reproducible geometry alternatives."""
    gaps = (1.0, 0.8, 1.2) if allow_gaps else (1.0,)
    widths = (1.0, 0.85, 1.15) if allow_node_widths else (1.0,)
    for gx, gy, width in itertools.product(gaps, gaps, widths):
        value = copy.deepcopy(seed)
        layouts = [value.get('root', {}).get('layout', {})]
        layouts.extend(z.get('layout', {}) for z in value.get('zones', []))
        for layout in layouts:
            for key, scale in (('gap_x', gx), ('gap_y', gy)):
                if key in layout:
                    layout[key] = round(layout[key] * scale, 3)
        for node in value.get('nodes', []):
            # Explicit inner widths and framed nodes require a separate policy.
            if 'max_w' in node and 'wrap_width_px' not in node and 'box' not in node:
                node['max_w'] = round(node['max_w'] * width, 3)
                # Keep the original minimum readable frame size.
                node['max_w'] = max(node['max_w'], node.get('min_w', 0))
        yield {'gap_x_scale': gx, 'gap_y_scale': gy, 'node_width_scale': width}, value


def fit(seed: dict, *, allow_gaps: bool = False, allow_node_widths: bool = False, evaluate=architecture) -> dict:
    """Return a ready candidate or the least-blocked candidate, never a fake pass."""
    started = time.perf_counter()
    attempts, best, seen = [], None, set()
    import json
    for changes, request in candidates(seed, allow_gaps=allow_gaps,
                                       allow_node_widths=allow_node_widths):
        key = json.dumps(request, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        receipt = evaluate(request)
        blockers = receipt.get('blocking_constraints', receipt.get('unsatisfied_constraints', []))
        ready = receipt.get('ready') is True and receipt.get('delivery_state') == 'ready'
        rank = (not ready, not receipt.get('capacity_fit', False), len(blockers))
        attempts.append({'changes': changes, 'ready': ready,
                         'capacity_fit': receipt.get('capacity_fit'),
                         'blocking_count': len(blockers)})
        if best is None or rank < best[0]:
            best = (rank, request, receipt, changes)
        if ready:
            break
    return {'schema': 'bounded-layout-fit/v1', 'ready': not best[0][0],
            'request': best[1], 'evaluation': best[2], 'changes': best[3],
            'attempts': attempts, 'elapsed_ms': round((time.perf_counter()-started)*1000, 1)}


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--in', dest='source', required=True)
    parser.add_argument('--out-dir', required=True)
    parser.add_argument('--allow-gaps', action='store_true')
    parser.add_argument('--allow-node-widths', action='store_true')
    add_contract_arguments(parser)
    args = parser.parse_args(argv)
    canvas, contract_path, workspace = load_contract(args)
    source, output = Path(args.source).resolve(), Path(args.out_dir).resolve()
    check_paths(source, [output], workspace, resources=[contract_path])
    if output.exists():
        raise ValueError('Use a new output directory; previous candidates are retained')
    fixture = contract_path.parent
    seed = normalized(json.loads(source.read_text(encoding='utf-8')), canvas, 'architecture', fixture)
    result = fit(seed, allow_gaps=args.allow_gaps, allow_node_widths=args.allow_node_widths)
    output.mkdir(parents=True)
    request_path = output / 'selected-request.json'
    request_path.write_text(json.dumps(result['request'], ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    receipt = dict(result['evaluation'], schema='capacity-preflight/v1', family='architecture',
                   source_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest(),
                   contract_sha256=hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                   normalized_request_sha256=sha256_json(result['request']))
    receipt_path = output / 'preflight.json'
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (output / 'search.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'ready': result['ready'], 'selected_request': str(request_path),
                      'receipt': summary(receipt, receipt_path), 'attempt_count': len(result['attempts']),
                      'elapsed_ms': result['elapsed_ms'], 'changes': result['changes']}))
    return 0 if result['ready'] else 4


if __name__ == '__main__':
    raise SystemExit(main())
