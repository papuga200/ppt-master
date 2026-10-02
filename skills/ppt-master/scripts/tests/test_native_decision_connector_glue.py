"""Decision vertices must remain attached when a human moves the PowerPoint gate."""
import sys
import unittest
from pathlib import Path
from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pptx_text_in_shapes as tis

NS = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'

def shape(identifier, preset, x, y, w, h, line=False):
    flips = ''
    if line:
        if w < 0:
            x, w, flips = x + w, -w, ' flipH="1"'
        if h < 0:
            y, h, flips = y + h, -h, flips + ' flipV="1"'
    paint = '<a:noFill/><a:ln><a:solidFill><a:srgbClr val="000000"/></a:solidFill><a:tailEnd type="triangle"/></a:ln>' if line else '<a:solidFill><a:srgbClr val="EEEEEE"/></a:solidFill>'
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{identifier}" name="Shape {identifier}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm{flips}><a:off x="{x*tis.PX}" y="{y*tis.PX}"/><a:ext cx="{max(1,w*tis.PX)}" cy="{max(1,h*tis.PX)}"/></a:xfrm>'
        f'<a:prstGeom prst="{preset}"><a:avLst/></a:prstGeom>{paint}</p:spPr></p:sp>')

def convert(endpoint, preset='flowChartDecision'):
    # Box right edge (80,100) connects to a 100-square gate centered at (150,100).
    xml = f'<p:spTree {NS}>' + shape(2, 'rect', 0, 75, 80, 50) + shape(3, preset, 100, 50, 100, 100)
    xml += shape(4, 'line', 80, 100, endpoint[0]-80, endpoint[1]-100, True) + '</p:spTree>'
    tree = etree.fromstring(xml)
    before = etree.tostring(tree[-1].find('p:spPr/a:xfrm', tis.NS))
    tis.glue_connectors(tree, {'glued': 0})
    connector = tree.find('p:cxnSp', tis.NS)
    return tree, connector, before

class DecisionConnectionTest(unittest.TestCase):
    def test_four_vertices_use_the_native_preset_site_order(self):
        # Site order verified against the retained presetShapeDefinitions.xml.
        for endpoint, index in (((150,50),0), ((100,100),1), ((150,150),2), ((200,100),3)):
            with self.subTest(endpoint=endpoint):
                _, connector, before = convert(endpoint)
                self.assertEqual(connector.find('p:nvCxnSpPr/p:cNvCxnSpPr/a:endCxn', tis.NS).attrib, {'id':'3','idx':str(index)})
                self.assertEqual(etree.tostring(connector.find('p:spPr/a:xfrm', tis.NS)), before)

    def test_real_left_vertex_attaches_both_ends_without_geometry_change(self):
        for preset in ('diamond', 'flowChartDecision'):
            with self.subTest(preset=preset):
                _, connector, before = convert((100,100), preset)
                links = connector.find('p:nvCxnSpPr/p:cNvCxnSpPr', tis.NS)
                self.assertEqual(links.find('a:stCxn', tis.NS).attrib, {'id':'2','idx':'3'})
                self.assertEqual(links.find('a:endCxn', tis.NS).attrib, {'id':'3','idx':'1'})
                self.assertEqual(etree.tostring(connector.find('p:spPr/a:xfrm', tis.NS)), before)

    def test_bounding_corner_is_not_a_diamond_site(self):
        _, connector, _ = convert((200,150))
        self.assertIsNone(connector.find('p:nvCxnSpPr/p:cNvCxnSpPr/a:endCxn', tis.NS))

    def test_sloping_edge_is_not_a_diamond_site(self):
        _, connector, _ = convert((175,125))
        self.assertIsNone(connector.find('p:nvCxnSpPr/p:cNvCxnSpPr/a:endCxn', tis.NS))

    def test_other_presets_are_not_given_invented_sites(self):
        _, connector, _ = convert((100,100), 'chevron')
        self.assertIsNone(connector.find('p:nvCxnSpPr/p:cNvCxnSpPr/a:endCxn', tis.NS))

    def test_rectangular_attachment_still_works(self):
        _, connector, _ = convert((100,100), 'rect')
        self.assertEqual(connector.find('p:nvCxnSpPr/p:cNvCxnSpPr/a:endCxn', tis.NS).attrib, {'id':'3','idx':'1'})

if __name__ == '__main__':
    unittest.main()
