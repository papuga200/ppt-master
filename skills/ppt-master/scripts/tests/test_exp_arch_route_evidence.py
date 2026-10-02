#!/usr/bin/env python3
"""Composer geometry evidence agrees with its emitted page, including failures."""
import copy
from pathlib import Path
from types import SimpleNamespace
import sys
import xml.etree.ElementTree as ET
SCRIPTS = Path(__file__).resolve().parents[1]
for path in (SCRIPTS, SCRIPTS / 'exp_svg', SCRIPTS / 'exp_svg' / 'arch'):
    sys.path.insert(0, str(path))
import compose_page as cp
SVG = '{http://www.w3.org/2000/svg}'

def candidate(tmp_path, monkeypatch):
    monkeypatch.setenv('PPT_MASTER_EXP_ENGINES', 'placement:primitive;routing:orthogonal;compose:page')
    template = tmp_path / 'template.svg'
    template.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><g id="chrome"><text x="50" y="50">Example</text></g></svg>', encoding='utf-8')
    return {'page': {'template': str(template), 'texts': [], 'body': {'x': 64, 'y': 208, 'w': 1152, 'h': 460}}, 'font': {'family': 'Segoe UI'}, 'nodes': [{'id': 'a', 'label': 'Gateway', 'at': {'x': 100, 'y': 300}}, {'id': 'b', 'label': 'Service', 'at': {'x': 450, 'y': 300}}], 'edges': [{'id': 'flow', 'source': 'a', 'target': 'b', 'kind': 'sync', 'label': 'Requests'}]}

def build(candidate, tmp_path):
    page = tmp_path / 'page.svg'
    status, result, residuals, ids, extra = cp._work(copy.deepcopy(candidate), SimpleNamespace(page=str(page), svg=None))
    return (status, result, residuals, ET.parse(page).getroot())

def _case_returned_routes_match_emitted_path_endpoints_and_label(candidate, tmp_path):
    status, result, residuals, root = build(candidate, tmp_path)
    assert status == 'ok', residuals
    route = result['routes']['flow']
    path = next((e for e in root.iter(SVG + 'path') if e.get('id') == 'arch-edge-flow'))
    assert path.get('d') == cp.sc.path_d(route['points'])
    assert (route['source'], route['target']) == (path.get('data-arch-source'), path.get('data-arch-target'))
    for end, point in (('source', route['points'][0]), ('target', route['points'][-1])):
        assert result['bindings']['flow'][end]['point'] == point
        assert cp.sc.point_on_rect_edge(point, cp.sc.rect(result['boxes'][route[end]])) == result['bindings']['flow'][end]['side']
    label = route['label']
    text = next((e for e in root.iter(SVG + 'text') if e.get('data-arch-text') == 'flow:label'))
    assert [''.join(span.itertext()) for span in text] == label['lines']
    assert float(text.get('x')) == _approx(label['box']['x'] + label['box']['w'] / 2, abs=0.01)
    size = float(text.get('font-size'))
    assert float(text.get('y')) == _approx(label['box']['y'] + (cp.sc.PITCH / 2 + 0.35) * size, abs=0.01)
    assert set(result['boxes']) == {'a', 'b'}
    assert route['binding']['source'] == result['bindings']['flow']['source']

def _case_no_edges_has_empty_routes_and_preserves_boxes(candidate, tmp_path):
    candidate['edges'] = []
    _, result, _, root = build(candidate, tmp_path)
    assert result['routes'] == result['bindings'] == result['buses'] == {}
    assert set(result['boxes']) == {'a', 'b'}
    assert not any((e.get('data-arch-role') == 'edge' for e in root.iter()))

def _case_failed_route_is_not_reported_as_successful_geometry(candidate, tmp_path, monkeypatch):

    def unroutable(scene, ports, only=None):
        return ({}, {'flow': 'No clear corridor'})
    monkeypatch.setattr(cp.route_connections, 'route_orthogonal', unroutable)
    status, result, residuals, root = build(candidate, tmp_path)
    assert status == 'partial'
    assert result['routes']['flow']['points'] is None
    assert result['routes']['flow']['label'] is None
    assert result['routes']['flow']['failure'] == 'No clear corridor'
    assert result['bindings']['flow']['source'] is None
    assert any((r['kind'] == 'unrouted' and r['id'] == 'flow' for r in residuals))
    assert not any((e.get('id') == 'arch-edge-flow' for e in root.iter()))

def _case_bus_paths_retained_and_match_emitted_branches(candidate, tmp_path):
    candidate['root'] = {'layout': {'type': 'rows', 'rows': [['a', 'bus', 'b']], 'gap_x': 100}}
    candidate['buses'] = [{'id': 'bus', 'kind': 'sync'}]
    candidate['edges'] = [{'id': 'in', 'source': 'a', 'target': 'bus', 'kind': 'sync'}, {'id': 'out', 'source': 'bus', 'target': 'b', 'kind': 'sync'}]
    _, result, _, root = build(candidate, tmp_path)
    bus = result['buses']['bus']
    assert len(bus['paths']) == len(bus['branches']) == 2
    emitted = {e.get('id'): e.get('d') for e in root.iter(SVG + 'path')}
    for branch, points in zip(bus['branches'], bus['paths']):
        drawn = points if branch['flow'] == 'in' else list(reversed(points))
        assert emitted['arch-edge-' + branch['flow']] == cp.sc.path_d(drawn)
    assert result['routes'] == {}

def _case_fixed_frames_without_root_preserve_requested_frames(candidate, tmp_path):
    candidate['zones'] = [{'id': 'left', 'label': 'Plant', 'kind': 'region', 'frame': {'x': 80, 'y': 240, 'w': 380, 'h': 320}, 'layout': {'type': 'rows', 'rows': [['a']]}}, {'id': 'right', 'label': 'Cloud', 'kind': 'region', 'frame': {'x': 760, 'y': 240, 'w': 380, 'h': 320}, 'layout': {'type': 'rows', 'rows': [['b']]}}]
    for node, zone in zip(candidate['nodes'], ('left', 'right')):
        node.pop('at')
        node['zone'] = zone
    status, result, residuals, _ = build(candidate, tmp_path)
    assert status == 'ok', residuals
    for zone in candidate['zones']:
        assert result['boxes'][zone['id']] == zone['frame']
    assert result['routes']['flow']['points']

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
    def test_returned_routes_match_emitted_path_endpoints_and_label(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            request = candidate(tmp_path, monkeypatch)
            _case_returned_routes_match_emitted_path_endpoints_and_label(request, tmp_path)
    def test_no_edges_has_empty_routes_and_preserves_boxes(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            request = candidate(tmp_path, monkeypatch)
            _case_no_edges_has_empty_routes_and_preserves_boxes(request, tmp_path)
    def test_failed_route_is_not_reported_as_successful_geometry(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            request = candidate(tmp_path, monkeypatch)
            _case_failed_route_is_not_reported_as_successful_geometry(request, tmp_path, monkeypatch)
    def test_bus_paths_retained_and_match_emitted_branches(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            request = candidate(tmp_path, monkeypatch)
            _case_bus_paths_retained_and_match_emitted_branches(request, tmp_path)
    def test_fixed_frames_without_root_preserve_requested_frames(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            request = candidate(tmp_path, monkeypatch)
            _case_fixed_frames_without_root_preserve_requested_frames(request, tmp_path)
