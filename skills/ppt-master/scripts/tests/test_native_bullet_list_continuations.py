"""Native list ownership and isolation of separately authored continuations."""
import importlib.util
import unittest
from pathlib import Path
from lxml import etree

spec = importlib.util.spec_from_file_location('candidate', Path(__file__).resolve().parents[1] / 'pptx_text_in_shapes.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def box(parent, text, x, y, width=240, bullet=False, bold=False, size=1200):
    shape = etree.SubElement(parent, m.q('p:sp'))
    nv = etree.SubElement(shape, m.q('p:nvSpPr'))
    etree.SubElement(nv, m.q('p:cNvSpPr'), txBox='1')
    props = etree.SubElement(shape, m.q('p:spPr'))
    transform = etree.SubElement(props, m.q('a:xfrm'))
    etree.SubElement(transform, m.q('a:off'), x=str(int(x*m.PX)), y=str(int(y*m.PX)))
    etree.SubElement(transform, m.q('a:ext'), cx=str(int(width*m.PX)), cy=str(int(20*m.PX)))
    etree.SubElement(props, m.q('a:noFill'))
    body = etree.SubElement(shape, m.q('p:txBody'))
    etree.SubElement(body, m.q('a:bodyPr'), wrap='none')
    para = etree.SubElement(body, m.q('a:p'))
    ppr = etree.SubElement(para, m.q('a:pPr'), algn='l')
    if bullet:
        ppr.set('marL', str(int(13.6*m.PX)))
        ppr.set('indent', str(-int(13.6*m.PX)))
        etree.SubElement(ppr, m.q('a:buChar'), char='■')
    run = etree.SubElement(para, m.q('a:r'))
    rpr = etree.SubElement(run, m.q('a:rPr'), sz=str(size), b='1' if bold else '0')
    fill = etree.SubElement(rpr, m.q('a:solidFill'))
    etree.SubElement(fill, m.q('a:srgbClr'), val='123456')
    etree.SubElement(run, m.q('a:t')).text = text
    item = m.Item(shape, parent, len(parent), (x*m.PX, y*m.PX, (x+width)*m.PX, (y+20)*m.PX), False)
    return m.TextBox(item, m.LINE_RATIO)


def stats():
    return dict(joined=0, paragraphs=0, reflowed=0, stacked=0, stacks=0, numbered=0)


class NativeListTests(unittest.TestCase):
    def setUp(self):
        self.root = etree.Element(m.q('p:spTree'), nsmap=m.NS)

    def join(self, boxes, extras=()):
        return m.join_lines(boxes, [b.item for b in boxes] + list(extras), stats())

    def test_wrapped_bullet_keeps_marker_indent_break_and_mixed_emphasis(self):
        first = box(self.root, 'Item begins', 100, 100, bullet=True)
        continuation = box(self.root, 'Important continuation', 117, 122.4, bold=True)
        result = self.join([first, continuation])
        self.assertEqual(len(result), 1)
        p = result[0].paras[0].el
        self.assertEqual(len(p.findall('a:br', m.NS)), 1)
        self.assertEqual(p.find('a:pPr', m.NS).get('marL'), str(int(13.6*m.PX)))
        self.assertEqual(p.find('a:pPr/a:tabLst/a:tab', m.NS).get('pos'), str(17*m.PX))
        self.assertEqual(p.findall('a:r', m.NS)[-1].find('a:rPr', m.NS).get('b'), '1')
        self.assertEqual(len(p.findall('a:pPr/a:buChar', m.NS)), 1)
        self.assertFalse(result[0].paras[0].joins)

    def test_separate_items_merge_as_two_native_paragraphs(self):
        boxes = [box(self.root, 'First', 100, 100, bullet=True), box(self.root, 'Second', 100, 130.4, bullet=True)]
        result = self.join(boxes)
        self.assertEqual(len(result), 2)
        st = stats()
        m.merge_stacks(result, [b.item for b in boxes], st)
        body = boxes[0].item.el.find('p:txBody', m.NS)
        self.assertEqual(len(body.findall('a:p/a:pPr/a:buChar', m.NS)), 2)
        self.assertEqual(st['stacks'], 1)

    def test_intervening_native_item_stops_continuation(self):
        boxes = [box(self.root, 'First', 100, 100, bullet=True), box(self.root, 'Second', 100, 122.4, bullet=True),
                 box(self.root, 'Second continuation', 117, 144.8)]
        result = self.join(boxes)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].paras[0]._line_texts(), ['First'])
        self.assertEqual(result[1].paras[0]._line_texts(), ['Second', '\tSecond continuation'])

    def test_adjacent_column_is_not_a_continuation(self):
        boxes = [box(self.root, 'First', 100, 100, bullet=True), box(self.root, 'Other column', 400, 122.4)]
        self.assertEqual(len(self.join(boxes)), 2)

    def test_larger_heading_is_not_a_continuation(self):
        boxes = [box(self.root, 'First', 100, 100, bullet=True), box(self.root, 'Heading', 117, 122.4, size=1500, bold=True)]
        self.assertEqual(len(self.join(boxes)), 2)

    def test_row_separator_blocks_join(self):
        boxes = [box(self.root, 'First', 100, 100, bullet=True), box(self.root, 'Continuation', 117, 122.4)]
        line = etree.SubElement(self.root, m.q('p:sp'))
        props = etree.SubElement(line, m.q('p:spPr'))
        fill = etree.SubElement(props, m.q('a:solidFill'))
        etree.SubElement(fill, m.q('a:srgbClr'), val='123456')
        separator = m.Item(line, self.root, 99, (100*m.PX, 120*m.PX, 340*m.PX, 121*m.PX), False)
        self.assertEqual(len(self.join(boxes, [separator])), 2)

    def test_typed_bullet_is_not_a_continuation(self):
        boxes = [box(self.root, 'First', 100, 100, bullet=True), box(self.root, '• New item', 117, 122.4)]
        self.assertEqual(len(self.join(boxes)), 2)

    def test_rejected_line_without_paragraph_properties_is_not_mutated(self):
        first = box(self.root, 'First', 100, 100, bullet=True)
        other = box(self.root, '• Separate item', 117, 122.4)
        paragraph = other.paras[0].el
        paragraph.remove(paragraph.find('a:pPr', m.NS))
        original = etree.tostring(other.item.el)
        self.assertEqual(len(self.join([first, other])), 2)
        self.assertEqual(etree.tostring(other.item.el), original)


if __name__ == '__main__':
    unittest.main()
