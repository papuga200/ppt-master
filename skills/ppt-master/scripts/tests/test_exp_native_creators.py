#!/usr/bin/env python3
"""Real creator -> DrawingML checks for native object ownership, without inference."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS / 'exp_svg' / 'arch'))
sys.path.insert(0, str(SCRIPTS / 'exp_svg' / 'timeline'))
import arrange
import scene as sc
import build_timeline as bt


def small_scene():
    return {'region': {'x':40, 'y':100, 'w':1200, 'h':590}, 'font':{'family':'Arial'},
            'nodes':[{'id':'a','label':'Gateway','at':{'x':80,'y':200}},
                     {'id':'b','label':'Service','at':{'x':400,'y':200}}], 'edges':[]}


PLAN = {'calendar':{'start':'2026-01-01','horizon_weeks':4},
        'lanes':[{'id':'a','name':'Delivery'}],
        'tasks':[{'id':'t','name':'Release','lane':'a','weeks':[1,4]}],
        'style':{'font_family':'Segoe UI','label_px':14},
        'bounds':{'x':54,'y':140,'w':1172,'h':476}}
from svg_to_pptx import convert_svg_to_slide_shapes

NS = {'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
      's':'http://www.w3.org/2000/svg'}

def convert(content):
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp)/'slide.svg'
        page.write_text(content,encoding='utf-8')
        xml,*_ = convert_svg_to_slide_shapes(page,resource_root=page.parent)
        return ET.fromstring(xml)

class NativeCreatorTests(unittest.TestCase):
    def test_architecture_label_and_sublabel_live_in_the_actual_shape(self):
        request = small_scene()
        request['style'] = {'native_text_ownership':True}
        request['nodes'][1]['sublabel'] = 'Boundary entry'
        _,scene,_ = arrange.arrange(request,'primitive')
        svg = sc.render_svg(scene)
        root = ET.fromstring(svg)
        owners = root.findall('.//s:g[@data-pptx-semantic-object="shape"]',NS)
        self.assertEqual(len(owners),len(scene['nodes']))
        self.assertTrue(all(len(o.findall('s:text',NS)) == 1 for o in owners))
        native = convert(svg)
        for node in scene['nodes']:
            shape = next(sp for sp in native.findall('.//p:sp',NS)
                         if sp.find('p:nvSpPr/p:cNvPr',NS).get('name') == 'arch-node-'+node['id'])
            self.assertIsNotNone(shape.find('p:txBody',NS))
            self.assertNotEqual(shape.find('p:nvSpPr/p:cNvSpPr',NS).get('txBox'),'1')
            self.assertIn(node['label'],''.join(shape.itertext()))

    def test_inside_timeline_labels_are_owned_but_external_labels_remain_external(self):
        request = copy.deepcopy(PLAN)
        request['style']['native_text_ownership'] = True
        built = bt.build(request)
        svg = bt.standalone_svg(built['group'])
        root = ET.fromstring(svg)
        owners = root.findall('.//s:g[@data-pptx-semantic-object="shape"]',NS)
        inside = [t for t in built['scene']['tasks'] if t['label']['where'] == 'inside']
        self.assertGreater(len(inside),0)
        self.assertEqual(len(owners),len(inside))
        native = convert(svg)
        for task in inside:
            shape = next(sp for sp in native.findall('.//p:sp',NS)
                         if sp.find('p:nvSpPr/p:cNvPr',NS).get('name') == 'timeline-task-'+task['id'])
            self.assertIsNotNone(shape.find('p:txBody',NS))
            self.assertNotEqual(shape.find('p:nvSpPr/p:cNvSpPr',NS).get('txBox'),'1')

    def test_one_list_text_produces_one_owner_with_real_native_bullet_paragraphs(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" font-family="Arial"><text id="notes" x="40" y="100" font-size="20" data-paragraph-line-height="28"><tspan x="40" dy="0">• First item</tspan><tspan x="40" dy="28">• Second item</tspan></text></svg>'
        native = convert(svg)
        shapes = [sp for sp in native.findall('.//p:sp',NS) if sp.find('p:txBody',NS) is not None]
        self.assertEqual(len(shapes),1)
        self.assertEqual(len(shapes[0].findall('p:txBody/a:p',NS)),2)
        self.assertEqual(len(shapes[0].findall('.//a:buChar',NS)),2)
