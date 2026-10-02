#!/usr/bin/env python3
"""Future opt-in delivery refuses unmeasured or known-failed scene geometry."""
from exp_svg.guided_build import validate_source_layout_receipt

def _case_reject_known_or_unmeasured_failure(receipt):
    with _raises(ValueError):
        validate_source_layout_receipt(receipt, {'source_layout_preflight_required': True}, 'architecture')

def _case_raw_extension_does_not_claim_certificate():
    receipt = {'geometry': {}, 'capacity_fit': True, 'unsatisfied_constraints': [], 'ready': False, 'coverage': {'complete': False}}
    receipt['delivery_state'] = 'requires_external_geometry_audit'
    with _raises(ValueError, expected_regex='external geometry audit'):
        validate_source_layout_receipt(receipt, {'source_layout_preflight_required': True}, 'architecture')
    assert receipt['ready'] is False and receipt['coverage']['complete'] is False

def _case_authoritative_ready_allows_spacing_warning():
    receipt = {'geometry': {}, 'capacity_fit': True, 'ready': True, 'delivery_state': 'ready', 'blocking_constraints': [], 'unsatisfied_constraints': [{'kind': 'spacing_tightened'}]}
    validate_source_layout_receipt(receipt, {'source_layout_preflight_required': True}, 'architecture')

def _case_legacy_receipt_requires_new_evaluation():
    receipt = {'geometry': {}, 'capacity_fit': True, 'ready': True, 'unsatisfied_constraints': []}
    with _raises(ValueError, expected_regex='rerun preflight'):
        validate_source_layout_receipt(receipt, {'source_layout_preflight_required': True}, 'architecture')

def _case_prior_and_other_family_unchanged(family, canvas):
    validate_source_layout_receipt({}, canvas, family)

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
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
    def test_reject_known_or_unmeasured_failure(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            for parameters in [{}, {'geometry': {}, 'capacity_fit': False}, {'geometry': {}, 'capacity_fit': True, 'unsatisfied_constraints': [{'kind': 'node_overlap'}]}]:
                receipt = parameters
                with self.subTest(parameters=parameters):
                    _case_reject_known_or_unmeasured_failure(receipt)
    def test_raw_extension_does_not_claim_certificate(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_raw_extension_does_not_claim_certificate()
    def test_authoritative_ready_allows_spacing_warning(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_authoritative_ready_allows_spacing_warning()
    def test_legacy_receipt_requires_new_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_legacy_receipt_requires_new_evaluation()
    def test_prior_and_other_family_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            for parameters in [('timeline', {'source_layout_preflight_required': True}), ('architecture', {})]:
                family, canvas = parameters
                with self.subTest(parameters=parameters):
                    _case_prior_and_other_family_unchanged(family, canvas)
