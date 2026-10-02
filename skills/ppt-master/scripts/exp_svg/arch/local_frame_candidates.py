#!/usr/bin/env python3
"""Opt-in, measured single-coordinate frame candidates. Never writes SVG.

See scripts/docs/experimental-authoring-tools.md for tool contracts.
Usage: python local_frame_candidates.py --help
Examples: use current measured JSON; no slide is written.
Dependencies: standard library and Pillow through architecture evaluation.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path

import sys
_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from console_encoding import configure_utf8_stdio  # noqa: E402

from exp_svg.arch.attachment_candidates import cp  # noqa: E402
from exp_svg.arch.candidate_common import ready, score, write_search  # noqa: E402

SCORE_ORDER = ['missing_routes_or_labels', 'all_blockers', 'crossings', 'bends', 'length_px']


def numeric(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def changed_paths(before, after, prefix: str = '') -> list[str]:
    """JSON Pointer paths; additions/removals count as changes too."""
    if type(before) is not type(after):
        return [prefix or '/']
    if isinstance(before, dict):
        paths = []
        for key in sorted(before.keys() | after.keys()):
            path = prefix + '/' + key.replace('~', '~0').replace('/', '~1')
            paths += ([path] if key not in before or key not in after else
                      changed_paths(before[key], after[key], path))
        return paths
    if isinstance(before, list):
        if len(before) != len(after):
            return [prefix or '/']
        return [p for i, (a, b) in enumerate(zip(before, after))
                for p in changed_paths(a, b, prefix + '/' + str(i))]
    return [] if before == after else [prefix or '/']


def capacity_defects(receipt: dict) -> Counter:
    # Compare full findings, so a changed/worsened defect is conservatively new.
    groups = [Counter(json.dumps(f, sort_keys=True) for f in receipt.get(key, [])
                      if f.get('kind') == 'capacity')
              for key in ('residual_constraints', 'blocking_constraints')]
    # A finding appears in both evaluator lists; avoid counting that as two.
    return groups[0] | groups[1]


def findings(receipt: dict) -> dict:
    return {key: copy.deepcopy(receipt.get(key)) for key in
            ('status', 'ready', 'delivery_state', 'capacity_fit', 'coverage',
             'blocking_constraints', 'residual_constraints', 'warnings')}


def full_ready(receipt: dict) -> bool:
    return ready(receipt)


def run_candidates(request: dict, zones: list[str], step_px: float = 4,
                   *, allow_adapt_frames: bool = False, evaluate=None) -> tuple:
    if not allow_adapt_frames:
        raise ValueError('Explicit --allow-adapt-frames authorization is required.')
    if not numeric(step_px) or step_px <= 0:
        raise ValueError('step_px must be a finite positive number.')
    if not zones:
        raise ValueError('Select at least one zone.')
    original = copy.deepcopy(request)
    indices = []
    for zone_id in dict.fromkeys(zones):
        matches = [i for i, z in enumerate(request.get('zones', [])) if z.get('id') == zone_id]
        if len(matches) != 1:
            raise ValueError(f'Zone {zone_id!r} must match exactly one declared zone.')
        index = matches[0]
        frame = request['zones'][index].get('frame')
        if not isinstance(frame, dict) or not all(numeric(frame.get(k)) for k in ('x', 'y')):
            raise ValueError(f'Zone {zone_id!r} needs explicit finite numeric frame x and y.')
        if not all(numeric(frame[k] + d) and frame[k] + d != frame[k]
                   for k in ('x', 'y') for d in (-step_px, step_px)):
            raise ValueError(f'Zone {zone_id!r} cannot represent the requested offsets.')
        indices.append(index)
    evaluator = cp.evaluate if evaluate is None else evaluate
    started = time.perf_counter()
    trials = []
    candidates = [(None, None, 0)] + [(i, axis, delta) for i in indices
                                               for axis in ('x', 'y')
                                               for delta in (-step_px, step_px)]
    best_score = None
    baseline = None
    best = None
    for number, (index, axis, delta) in enumerate(candidates):
        candidate = copy.deepcopy(original)
        expected_paths = []
        if index is not None:
            candidate['zones'][index]['frame'][axis] += delta
            expected_paths = [f'/zones/{index}/frame/{axis}']
        paths = changed_paths(original, candidate)
        assert paths == expected_paths, 'Candidate exceeded its coordinate-only scope.'
        frozen = copy.deepcopy(candidate)
        trial_start = time.perf_counter()
        try:
            receipt = evaluator(candidate)
        except Exception as error:
            assert candidate == frozen, 'Evaluator mutated its request.'
            assert request == original, 'Input request was mutated.'
            if number == 0:
                raise
            trials.append({'candidate': number, 'changed_paths': paths,
                           'zone': original['zones'][index]['id'], 'axis': axis, 'delta_px': delta,
                           'elapsed_s': time.perf_counter() - trial_start,
                           'accepted': False, 'rejection_reasons': ['evaluation_error'],
                           'error': f'{type(error).__name__}: {error}', 'request': frozen})
            continue
        elapsed = time.perf_counter() - trial_start
        assert candidate == frozen, 'Evaluator mutated its request.'
        assert request == original, 'Input request was mutated.'
        current_score = score(receipt)
        if number == 0:
            baseline = copy.deepcopy(receipt)
        reasons = []
        if current_score[0] > score(baseline)[0]:
            reasons.append('missing_routes_or_labels_regressed')
        if capacity_defects(receipt) - capacity_defects(baseline):
            reasons.append('new_capacity_defect')
        if baseline.get('capacity_fit') and not receipt.get('capacity_fit'):
            reasons.append('capacity_fit_regressed')
        trial = {'candidate': number, 'changed_paths': paths,
                 'zone': None if index is None else original['zones'][index]['id'],
                 'axis': axis, 'delta_px': delta, 'elapsed_s': elapsed,
                 'score': list(current_score), 'ready': full_ready(receipt),
                 'accepted': not reasons, 'rejection_reasons': reasons,
                 'request': frozen, 'receipt': copy.deepcopy(receipt)}
        trials.append(trial)
        rank = (not full_ready(receipt), current_score)
        if not reasons and (best is None or rank < (not best['ready'], best_score)):
            best_score, best = current_score, trial
    assert request == original, 'Input request was mutated.'
    compact = [{k: v for k, v in t.items() if k not in ('request', 'receipt')} |
               {'blocker_kinds': [b.get('kind') for b in t.get('receipt', {}).get('blocking_constraints', [])]}
               for t in trials]
    summary = {'selected_zones': [original['zones'][i]['id'] for i in indices],
               'step_px': step_px, 'candidate_count': len(candidates),
               'evaluate_calls': len(trials), 'selected_candidate': best['candidate'],
               'changed_paths': best['changed_paths'], 'score_order': SCORE_ORDER,
               'before_score': list(score(baseline)), 'after_score': list(best_score),
               'before_ready': full_ready(baseline), 'after_ready': best['ready'],
               'before_findings': findings(baseline), 'after_findings': findings(best['receipt']),
               'elapsed_s': time.perf_counter() - started,
               'evaluation_elapsed_s': sum(t['elapsed_s'] for t in trials),
               'trials': compact,
               'scope': 'Only one selected zone frame x or y may change. No SVG written. '
                        'Full evaluator readiness remains required; native export, facts and visual judgment '
                        'remain outside evaluator coverage.'}
    return copy.deepcopy(best['request']), copy.deepcopy(best['receipt']), summary, trials


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--in', dest='source', type=Path, required=True)
    ap.add_argument('--zone', action='append', required=True)
    ap.add_argument('--step-px', type=float, default=4)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--allow-adapt-frames', action='store_true')
    args = ap.parse_args(argv)
    if not args.allow_adapt_frames:
        ap.error('Explicit --allow-adapt-frames authorization is required.')
    raw = args.source.read_bytes()
    request = json.loads(raw.decode('utf-8-sig'))
    try:
        selected, receipt, summary, trials = run_candidates(
            request, args.zone, args.step_px, allow_adapt_frames=args.allow_adapt_frames)
    except ValueError as error:
        ap.error(str(error))
    assert args.source.read_bytes() == raw, 'Source request file was mutated.'
    summary['input_sha256'] = hashlib.sha256(raw).hexdigest()
    try:
        write_search(args.source, args.out, selected, receipt, summary, trials)
    except (OSError, ValueError) as error:
        ap.error(str(error))
    assert args.source.read_bytes() == raw, 'Source request file was mutated.'
    print(json.dumps({k: summary[k] for k in ('selected_candidate', 'changed_paths',
                                             'before_score', 'after_score', 'after_ready', 'elapsed_s')}))
    return 0 if summary['after_ready'] else 4


if __name__ == '__main__':
    raise SystemExit(main())
