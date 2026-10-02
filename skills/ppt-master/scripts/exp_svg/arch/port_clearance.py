#!/usr/bin/env python3
"""Explain occupied connector exits from an existing receipt; never reroute or write SVG.

See scripts/docs/experimental-authoring-tools.md for tool contracts.
Usage: python port_clearance.py --help
Examples: use current measured JSON; no slide is written.
Dependencies: standard library and Pillow through architecture evaluation.
"""
from __future__ import annotations

from pathlib import Path
import argparse, copy, hashlib, json, sys

S = Path(__file__).resolve().parents[2]
for folder in (S, S/'exp_svg/arch'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
from console_encoding import configure_utf8_stdio  # noqa: E402
import route_connections as rc  # noqa: E402
import scene as sc
from _common import sha256_json


def analyze(request: dict, receipt: dict, edge_ids: list[str] | None = None) -> dict:
    """Capacity of endpoint exits only; original findings/readiness remain authoritative."""
    result = receipt.get('result', receipt.get('geometry'))
    if not isinstance(result, dict):
        raise ValueError('Measured architecture geometry is required')
    objects = result['objects']
    node_ids = {n['id'] for n in request['nodes']}
    zone_ids = {z['id'] for z in request.get('zones', [])}
    note_ids = {n['id'] for n in request.get('annotations', [])}
    # Invisible layout groups have already been stripped by the evaluator.
    scene = {'nodes': [copy.deepcopy(objects[n]) for n in node_ids if n in objects],
             'zones': [copy.deepcopy(objects[z]) for z in zone_ids if z in objects],
             'annotations': [copy.deepcopy(objects[n]) for n in note_ids if n in objects],
             'edges': [copy.deepcopy(e) for e in request.get('edges', [])
                       if e['source'] in node_ids and e['target'] in node_ids]}
    legend = request.get('legend') or {}
    if legend.get('id') in objects:
        scene['legend'] = copy.deepcopy(objects[legend['id']])
    ports = rc.assign_ports(scene)
    blocks = rc.obstacles(scene)
    nodes = {n['id']: n for n in scene['nodes']}
    bounds = result['page']['region']
    selected = set(edge_ids or [f.get('id') for f in receipt.get('blocking_constraints', [])])
    output = []
    for edge in scene['edges']:
        if edge['id'] not in selected:
            continue
        ends = {}
        for end in ('source', 'target'):
            node = nodes[edge[end]]
            candidates = []
            for side in rc.SIDES:
                port = rc.free_port(ports, node['box'], edge[end], side,
                                    {(edge['id'], 'source'), (edge['id'], 'target')})
                if port is None:
                    candidates.append({'side': side, 'clear': False, 'reason': 'no free port slot'})
                    continue
                stub = rc._stub(port)
                hits = [b['id'] for b in blocks if b['id'] not in (edge['source'], edge['target'])
                        and (sc.segment_hits_rect(port['point'], stub, b['rect'])
                             or b['rect'][0] < stub[0] < b['rect'][2]
                             and b['rect'][1] < stub[1] < b['rect'][3])]
                off = not (bounds['x'] <= stub[0] <= bounds['x']+bounds['w']
                           and bounds['y'] <= stub[1] <= bounds['y']+bounds['h'])
                candidates.append({'side': side, 'point': list(port['point']), 'stub': list(stub),
                                   'blocking_objects': hits, 'stub_outside_body': off,
                                   'clear': not hits and not off})
            ends[end] = {'node': edge[end], 'box': node['box'], 'candidate_exits': candidates}
        output.append({'edge': edge['id'], **ends})
    return {'scope': 'Endpoint exit clearance only, from the existing measured receipt. A clear exit does not prove a complete route. No objects, ports, facts, readiness or SVG are changed.',
            'router_constants_px': {'node_clearance': rc.MARGIN, 'outward_stub': rc.STUB,
                                    'port_spacing': rc.PORT_SPACING, 'caption_clearance': 4},
            'original_ready': receipt.get('ready'),
            'original_blocking_constraints': receipt.get('blocking_constraints', []),
            'body': bounds, 'edges': output}


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--request', type=Path, required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--edge', action='append')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    rb, eb = a.request.read_bytes(), a.receipt.read_bytes()
    request = json.loads(rb.decode('utf-8-sig'))
    receipt = json.loads(eb.decode('utf-8-sig'))
    report = analyze(request, receipt, a.edge)
    report['request_sha256'] = hashlib.sha256(rb).hexdigest()
    report['receipt_sha256'] = hashlib.sha256(eb).hexdigest()
    recorded = receipt.get('input_sha256')
    report['request_canonical_sha256'] = sha256_json(request)
    raw_recorded = receipt.get('source_sha256')
    report['receipt_matches_request'] = (raw_recorded == report['request_sha256'] if raw_recorded
                                         else recorded == report['request_canonical_sha256'] if recorded else None)
    if report['receipt_matches_request'] is False:
        raise SystemExit('Receipt is stale for this request; evaluate the current request first.')
    if a.out.resolve() in {a.request.resolve(), a.receipt.resolve()}:
        p.error('Output must not replace an input')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'out': str(a.out), 'edges': len(report['edges']),
                      'original_ready': report['original_ready']}))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
