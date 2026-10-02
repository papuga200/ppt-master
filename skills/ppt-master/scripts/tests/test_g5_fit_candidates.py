#!/usr/bin/env python3
import copy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'exp_svg'))
from fit_candidates import candidates, fit
import fit_candidates
import json
import hashlib

def seed():
    return {'root': {'layout': {'rows': [['a', 'b']], 'gap_x': 100}}, 'nodes': [{'id': 'a', 'label': 'Required fact', 'max_w': 100, 'min_w': 80}], 'edges': [{'id': 'ab', 'source': 'a', 'target': 'b', 'source_side': 'east'}]}

def _case_default_does_not_change_anything():
    value = seed()
    assert [r for _, r in candidates(value)] == [value]

def _case_search_preserves_semantics_and_input():
    value = seed()
    original = copy.deepcopy(value)
    variants = list(candidates(value, allow_gaps=True, allow_node_widths=True))
    assert len(variants) == 27
    for _, request in variants:
        assert request['edges'] == value['edges']
        assert request['nodes'][0]['label'] == 'Required fact'
        assert request['root']['layout']['rows'] == [['a', 'b']]
    assert value == original

def _case_stops_on_ready_and_keeps_failed_result_honest():

    def evaluate(request):
        ready = request['root']['layout']['gap_x'] < 90
        return {'ready': ready, 'capacity_fit': True, 'delivery_state': 'ready' if ready else 'blocked', 'blocking_constraints': [] if ready else [{'kind': 'label_conflict'}]}
    result = fit(seed(), allow_gaps=True, evaluate=evaluate)
    assert result['ready'] and len(result['attempts']) == 2
    result = fit(seed(), evaluate=evaluate)
    assert not result['ready'] and len(result['attempts']) == 1

def _case_cli_writes_hash_bound_request_and_no_svg(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / 'inputs/fixture'
    (fixture / 'template').mkdir(parents=True)
    template = fixture / 'template/content.svg'
    template.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720"><g id="chrome"/></svg>')
    body = {'x': 64, 'y': 208, 'w': 1152, 'h': 460}
    (fixture / 'canvas.json').write_text(json.dumps({'body_zone': body, 'type_floors': {'label_px_min': 13.333}, 'native_editability_required': True}))
    request = {'page': {'template': str(template), 'body': body}, 'nodes': [{'id': 'a', 'label': 'Source'}, {'id': 'b', 'label': 'Target'}], 'root': {'layout': {'rows': [['a', 'b']], 'gap_x': 140}}, 'edges': [{'id': 'ab', 'source': 'a', 'target': 'b'}]}
    source = tmp_path / 'seed.json'
    source.write_text(json.dumps(request))
    output = tmp_path / 'work/fit'
    monkeypatch.setenv('PPT_MASTER_PROJECT_PATH', str(tmp_path))
    monkeypatch.setattr(sys, 'argv', ['fit_candidates.py', '--in', str(source), '--out-dir', str(output), '--allow-gaps'])
    assert fit_candidates.main() == 0
    receipt = json.loads((output / 'preflight.json').read_text())
    assert receipt['source_sha256'] == hashlib.sha256((output / 'selected-request.json').read_bytes()).hexdigest()
    assert receipt['ready'] is True
    assert list(tmp_path.rglob('*.svg')) == [template]
    assert json.loads(capsys.readouterr().out)['ready'] is True
    with _raises(ValueError, expected_regex='previous candidates'):
        fit_candidates.main()

import contextlib
import io
import os
import re
import tempfile
import unittest
from unittest.mock import patch


def _raises(exception, expected_regex=None):
    case = unittest.TestCase()
    return case.assertRaisesRegex(exception, expected_regex) if expected_regex else case.assertRaises(exception)


class _Approx:
    def __init__(self, expected, abs=1e-6):
        self.expected, self.tolerance = expected, abs

    def __eq__(self, actual):
        if isinstance(self.expected, (tuple, list)):
            return len(actual) == len(self.expected) and all(_Approx(e, self.tolerance) == a for a, e in zip(actual, self.expected))
        return __import__('math').isclose(actual, self.expected, abs_tol=self.tolerance)


def _approx(expected, abs=1e-6):
    return _Approx(expected, abs)


class _Patches:
    def __init__(self, stack):
        self.stack = stack

    def setenv(self, name, value):
        self.stack.enter_context(patch.dict(os.environ, {name: value}))

    def setattr(self, owner, name, value):
        self.stack.enter_context(patch.object(owner, name, value))


class _Captured:
    def __init__(self, stream):
        self.stream = stream

    def readouterr(self):
        return __import__('types').SimpleNamespace(out=self.stream.getvalue())


class PromotedToolTests(unittest.TestCase):
    def test_default_does_not_change_anything(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_default_does_not_change_anything()
    def test_search_preserves_semantics_and_input(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_search_preserves_semantics_and_input()
    def test_stops_on_ready_and_keeps_failed_result_honest(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_stops_on_ready_and_keeps_failed_result_honest()
    def test_cli_writes_hash_bound_request_and_no_svg(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            captured = io.StringIO()
            stack.enter_context(contextlib.redirect_stdout(captured))
            capsys = _Captured(captured)
            _case_cli_writes_hash_bound_request_and_no_svg(tmp_path, monkeypatch, capsys)
