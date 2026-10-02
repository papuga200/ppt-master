#!/usr/bin/env python3
"""Contract checks for bounded semantic SVG/native PPTX ownership."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / 'exp_svg' / 'inspect'))
from native_editability import audit
from native_editability import P, A
SHAPE = '<g id="node" data-pptx-semantic-object="shape" data-pptx-frame="10 10 100 50"><rect x="10" y="10" width="100" height="50" data-pptx-part="geometry"/><text x="20" y="35" font-size="14">Node</text></g>'
LIST = '<text id="items" x="20" y="40" font-size="14" data-editable-kind="list" data-paragraph-line-height="25"><tspan x="20" dy="0">• Alpha</tspan><tspan x="20" dy="25">• Beta</tspan></text>'
TABLE = '<g id="grid" data-editable-kind="table" data-pptx-replace-with="table"><metadata type="application/json">{"schema":"ppt-master.semantic-table.v2","name":"grid","x":10,"y":10,"width":100,"height":60,"columns":["A","B"],"rows":[["1","2"]]}</metadata><rect x="10" y="10" width="100" height="60"/><text x="15" y="30">A</text></g>'

def svg(tmp_path, body):
    path = tmp_path / 'page.svg'
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">' + body + '</svg>', encoding='utf-8')
    return path

def package(tmp_path, xml):
    path = tmp_path / 'page.pptx'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('ppt/slides/slide1.xml', xml)
    return path

def codes(result):
    return {f['code'] for f in result['findings']}

def _case_valid_shape_and_fragmentation(tmp_path):
    assert audit(svg(tmp_path, SHAPE))['status'] == 'passed'
    assert 'fragmented_node' in codes(audit(svg(tmp_path, '<g id="n" data-arch-role="node"><rect/><text>Node</text></g>')))
    assert 'fragmented_shape_text' in codes(audit(svg(tmp_path, SHAPE.replace('</g>', '<text>Loose</text></g>'))))

def _case_malformed_shape_fails_closed(tmp_path, frame):
    assert 'invalid_shape_frame' in codes(audit(svg(tmp_path, SHAPE.replace('10 10 100 50', frame))))

def _case_invalid_xml_fails_closed(tmp_path):
    assert 'invalid_svg' in codes(audit(svg(tmp_path, '<g>')))

def _case_list_contract_and_probable_fragmentation(tmp_path):
    assert audit(svg(tmp_path, LIST))['status'] == 'passed'
    assert 'invalid_list_spacing' in codes(audit(svg(tmp_path, LIST.replace('data-paragraph-line-height="25"', ''))))
    assert 'invalid_list_paragraphs' in codes(audit(svg(tmp_path, LIST.replace('dy="25"', 'dy="25" data-paragraph-soft-break="1"'))))
    assert 'probable_fragmented_list' in codes(audit(svg(tmp_path, '<g><text>• Alpha</text><text>• Beta</text></g>')))

def _case_table_payload_and_drawing_grid_mismatch(tmp_path):
    source = svg(tmp_path, TABLE)
    assert audit(source)['status'] == 'passed'
    xml = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:grpSp><p:nvGrpSpPr><p:cNvPr id="2" name="grid"/></p:nvGrpSpPr></p:grpSp></p:spTree></p:cSld></p:sld>'
    assert 'native_table_mismatch' in codes(audit(source, package(tmp_path, xml)))
    assert 'invalid_table_payload' in codes(audit(svg(tmp_path, TABLE.replace('"rows":[["1","2"]]', '"rows":"bad"'))))
    assert 'invalid_table_payload' in codes(audit(svg(tmp_path, TABLE.replace('semantic-table.v2', 'semantic-table.v0'))))

def _case_gantt_zones_and_legends_not_inferred_as_tables(tmp_path):
    body = '<g data-editable-kind="gantt"><rect/><text>Phase</text><rect/><text>Team</text></g><g data-arch-role="legend"><rect/><text>● Live</text><rect/><text>● Paused</text></g>'
    result = audit(svg(tmp_path, body))
    assert result['status'] == 'passed'
    assert result['counts']['tables'] == 0
    assert result['limitations']

def _case_exact_owner_names_and_wrong_text_owner(tmp_path):
    source = svg(tmp_path, SHAPE)
    xml = '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sp><p:nvSpPr><p:cNvPr name="node-extra"/></p:nvSpPr><p:txBody/></p:sp></p:sld>'
    assert 'native_owner_mismatch' in codes(audit(source, package(tmp_path, xml)))
    xml = xml.replace('node-extra', 'node').replace('<p:txBody/>', '')
    assert 'native_shape_mismatch' in codes(audit(source, package(tmp_path, xml)))

def _case_actual_low_level_conversion_owns_shape_and_bullet_list(tmp_path):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    source = svg(tmp_path, SHAPE + LIST)
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path, text_flow='preserve')[0]
    result = audit(source, package(tmp_path, xml))
    assert result['status'] == 'passed', result
    assert result['counts']['pptx_objects_verified'] == 2

def _case_native_list_bullets_and_paragraphs_required(tmp_path):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    source = svg(tmp_path, LIST)
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path, text_flow='preserve')[0]
    import re
    xml = re.sub('<a:buChar[^>]*/>', '', xml)
    assert 'native_list_mismatch' in codes(audit(source, package(tmp_path, xml)))

def _case_actual_native_table_conversion(tmp_path):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    source = svg(tmp_path, TABLE.replace('id="grid"', 'id="grid" data-pptx-native-authority="json"'))
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path, native_objects=True)[0]
    result = audit(source, package(tmp_path, xml))
    assert result['status'] == 'passed', result
    assert result['counts']['pptx_objects_verified'] == 1

def _case_malformed_pptx_fails_closed(tmp_path):
    bad = tmp_path / 'bad.pptx'
    bad.write_bytes(b'not a zip')
    assert 'invalid_pptx' in codes(audit(svg(tmp_path, SHAPE), bad))

def _case_named_textbox_cannot_impersonate_semantic_shape(tmp_path):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    source = svg(tmp_path, SHAPE)
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path)[0]
    root = ET.fromstring(xml)
    owner = next((e for e in root.iter(P + 'sp') if e.find(P + 'nvSpPr/' + P + 'cNvPr').get('name') == 'node'))
    owner.find(P + 'nvSpPr/' + P + 'cNvSpPr').set('txBox', '1')
    assert 'native_shape_geometry_mismatch' in codes(audit(source, package(tmp_path, ET.tostring(root, encoding='unicode'))))

def _case_stripped_shape_content_detected(tmp_path):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    source = svg(tmp_path, SHAPE.replace('>Node</text>', '>Node content</text>'))
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path)[0]
    root = ET.fromstring(xml)
    next(root.iter(A + 't')).text = 'Node'
    assert 'native_shape_content_mismatch' in codes(audit(source, package(tmp_path, ET.tostring(root, encoding='unicode'))))

def _case_wrapped_shape_source_text_normalized(tmp_path):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    body = SHAPE.replace('>Node</text>', ' data-paragraph-line-height="18"><tspan x="20" dy="0">Node</tspan><tspan x="20" dy="18">content</tspan></text>')
    source = svg(tmp_path, body)
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path, text_flow='preserve')[0]
    result = audit(source, package(tmp_path, xml))
    assert result['status'] == 'passed', result

def _case_valid_wrapped_list_continuation(tmp_path, first, continuation):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    body = LIST.replace('Alpha</tspan>', first + '</tspan><tspan x="20" dy="25" data-paragraph-soft-break="1">' + continuation + '</tspan>')
    source = svg(tmp_path, body)
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path, text_flow='preserve')[0]
    result = audit(source, package(tmp_path, xml))
    assert result['status'] == 'passed', result
    assert result['counts']['pptx_objects_verified'] == 1

def _case_native_list_break_content_and_paragraphs_checked(tmp_path, first, continuation):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    body = LIST.replace('Alpha</tspan>', first + '</tspan><tspan x="20" dy="25" data-paragraph-soft-break="1">' + continuation + '</tspan>')
    source = svg(tmp_path, body)
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path, text_flow='preserve')[0]
    root = ET.fromstring(xml)
    paragraphs = root.findall('.//' + P + 'txBody/' + A + 'p')
    assert len(paragraphs) == 2
    assert len(paragraphs[0].findall(A + 'br')) == 1
    assert len(root.findall('.//' + A + 'buChar')) == 2
    assert audit(source, package(tmp_path, xml))['status'] == 'passed'
    continuation_text = next((t for t in paragraphs[0].iter(A + 't') if t.text == continuation))
    continuation_text.text = 'Changed content'
    assert 'native_list_mismatch' in codes(audit(source, package(tmp_path, ET.tostring(root, encoding='unicode'))))

def _case_native_shape_continuation_content_checked(tmp_path, first, continuation):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    body = SHAPE.replace('>Node</text>', '><tspan x="20" dy="0">' + first + '</tspan><tspan x="20" dy="18" data-paragraph-soft-break="1">' + continuation + '</tspan><tspan x="20" dy="18" data-paragraph-soft-break="0">End</tspan></text>')
    source = svg(tmp_path, body)
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path, text_flow='preserve')[0]
    root = ET.fromstring(xml)
    paragraphs = root.findall('.//' + P + 'txBody/' + A + 'p')
    assert len(paragraphs) == 2
    assert len(paragraphs[0].findall(A + 'br')) == 1
    result = audit(source, package(tmp_path, xml))
    assert result['status'] == 'passed', result
    assert result['counts']['pptx_objects_verified'] == 1
    continuation_text = next((t for t in paragraphs[0].iter(A + 't') if t.text == continuation))
    continuation_text.text = 'Changed content'
    assert 'native_shape_content_mismatch' in codes(audit(source, package(tmp_path, ET.tostring(root, encoding='unicode'))))

def _case_first_list_continuation_invalid(tmp_path):
    body = LIST.replace('dy="0"', 'dy="0" data-paragraph-soft-break="1"')
    assert 'invalid_list_paragraphs' in codes(audit(svg(tmp_path, body)))

def _case_native_table_stripped_cell_content_detected(tmp_path):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    source = svg(tmp_path, TABLE.replace('id="grid"', 'id="grid" data-pptx-native-authority="json"'))
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path, native_objects=True)[0]
    root = ET.fromstring(xml)
    next(root.iter(A + 't')).text = 'Wrong header'
    assert 'native_table_content_mismatch' in codes(audit(source, package(tmp_path, ET.tostring(root, encoding='unicode'))))

def _case_native_table_rich_cell_paragraphs_and_runs(tmp_path):
    from svg_to_pptx.drawingml.converter import convert_svg_to_slide_shapes
    body = TABLE.replace('id="grid"', 'id="grid" data-pptx-native-authority="json"').replace('["1","2"]', '[{"paragraphs":[{"runs":[{"text":"Rich "},{"text":"value","bold":true}]},"Second paragraph"]},"2"]')
    source = svg(tmp_path, body)
    xml = convert_svg_to_slide_shapes(source, resource_root=tmp_path, native_objects=True)[0]
    result = audit(source, package(tmp_path, xml))
    assert result['status'] == 'passed', result

def _case_public_cli_preserves_explicit_list_owner_name(tmp_path):
    """Exercise canonical normalization and the real packaged CLI export."""
    import subprocess
    project = tmp_path / 'project'
    source_dir = project / 'svg_output'
    source_dir.mkdir(parents=True)
    body = LIST.replace('id="items"', 'id="items-text" data-name="items" data-pptx-shape-name="items"')
    source = svg(tmp_path, '<g id="body" data-pptx-bounds="0 0 1280 720">' + body + '</g>')
    source = source.replace(source_dir / '01_page.svg')
    quality = subprocess.run([sys.executable, str(SCRIPTS / 'svg_quality_checker.py'), str(project), '--quick-generate', '--canonical-authoring', '--stage', 'final', '--json'], capture_output=True, text=True, encoding='utf-8')
    assert quality.returncode == 0, quality.stdout + quality.stderr
    output = tmp_path / 'public.pptx'
    exported = subprocess.run([sys.executable, str(SCRIPTS / 'svg_to_pptx.py'), str(project), '-o', str(output), '--quick-generate', '--no-animations'], capture_output=True, text=True, encoding='utf-8')
    assert exported.returncode == 0, exported.stdout + exported.stderr
    result = audit(source, output)
    assert result['status'] == 'passed', result
    assert result['counts']['pptx_objects_verified'] == 1

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
    def test_valid_shape_and_fragmentation(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_valid_shape_and_fragmentation(tmp_path)
    def test_malformed_shape_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            for parameters in ['nan 1 4 4', '1 2 -3 4', '1 2 3', 'a b c d']:
                frame = parameters
                with self.subTest(parameters=parameters):
                    _case_malformed_shape_fails_closed(tmp_path, frame)
    def test_invalid_xml_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_invalid_xml_fails_closed(tmp_path)
    def test_list_contract_and_probable_fragmentation(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_list_contract_and_probable_fragmentation(tmp_path)
    def test_table_payload_and_drawing_grid_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_table_payload_and_drawing_grid_mismatch(tmp_path)
    def test_gantt_zones_and_legends_not_inferred_as_tables(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_gantt_zones_and_legends_not_inferred_as_tables(tmp_path)
    def test_exact_owner_names_and_wrong_text_owner(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_exact_owner_names_and_wrong_text_owner(tmp_path)
    def test_actual_low_level_conversion_owns_shape_and_bullet_list(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_actual_low_level_conversion_owns_shape_and_bullet_list(tmp_path)
    def test_native_list_bullets_and_paragraphs_required(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_native_list_bullets_and_paragraphs_required(tmp_path)
    def test_actual_native_table_conversion(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_actual_native_table_conversion(tmp_path)
    def test_malformed_pptx_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_malformed_pptx_fails_closed(tmp_path)
    def test_named_textbox_cannot_impersonate_semantic_shape(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_named_textbox_cannot_impersonate_semantic_shape(tmp_path)
    def test_stripped_shape_content_detected(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_stripped_shape_content_detected(tmp_path)
    def test_wrapped_shape_source_text_normalized(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_wrapped_shape_source_text_normalized(tmp_path)
    def test_valid_wrapped_list_continuation(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            for parameters in [('Alpha', 'continuation'), ('第一', '续行')]:
                first, continuation = parameters
                with self.subTest(parameters=parameters):
                    _case_valid_wrapped_list_continuation(tmp_path, first, continuation)
    def test_native_list_break_content_and_paragraphs_checked(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            for parameters in [('Alpha', 'continuation'), ('第一', '续行')]:
                first, continuation = parameters
                with self.subTest(parameters=parameters):
                    _case_native_list_break_content_and_paragraphs_checked(tmp_path, first, continuation)
    def test_native_shape_continuation_content_checked(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            for parameters in [('Collected', 'locally'), ('本地', '采集')]:
                first, continuation = parameters
                with self.subTest(parameters=parameters):
                    _case_native_shape_continuation_content_checked(tmp_path, first, continuation)
    def test_first_list_continuation_invalid(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_first_list_continuation_invalid(tmp_path)
    def test_native_table_stripped_cell_content_detected(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_native_table_stripped_cell_content_detected(tmp_path)
    def test_native_table_rich_cell_paragraphs_and_runs(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_native_table_rich_cell_paragraphs_and_runs(tmp_path)
    def test_public_cli_preserves_explicit_list_owner_name(self):
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            tmp_path = Path(temporary)
            monkeypatch = _Patches(stack)
            _case_public_cli_preserves_explicit_list_owner_name(tmp_path)
