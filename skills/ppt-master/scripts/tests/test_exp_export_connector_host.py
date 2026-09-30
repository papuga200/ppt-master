"""svg-helpers experiment (D013): an arrow or open unfilled path must never host moved text in pptx_text_in_shapes."""
import sys
import unittest
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pptx_text_in_shapes as tis  # noqa: E402

NS = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'


class _Item:
    def __init__(self, xml: str):
        self.el = etree.fromstring(xml)


def shape(sppr: str) -> _Item:
    return _Item(f'<p:sp {NS}><p:nvSpPr><p:cNvPr id="2" name="s"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr>{sppr}</p:spPr></p:sp>')


class ConnectorHostTest(unittest.TestCase):
    def test_arrowhead_line_is_connector_like(self):
        item = shape('<a:prstGeom prst="rect"/><a:noFill/><a:ln w="12700"><a:solidFill><a:srgbClr val="000000"/></a:solidFill><a:tailEnd type="triangle"/></a:ln>')
        self.assertTrue(tis.is_connector_like(item))

    def test_open_unfilled_custom_path_is_connector_like(self):
        item = shape('<a:custGeom><a:pathLst><a:path w="10" h="10"><a:moveTo><a:pt x="0" y="0"/></a:moveTo><a:lnTo><a:pt x="10" y="10"/></a:lnTo></a:path></a:pathLst></a:custGeom><a:noFill/><a:ln><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>')
        self.assertTrue(tis.is_connector_like(item))

    def test_filled_closed_box_is_not_connector_like(self):
        item = shape('<a:custGeom><a:pathLst><a:path w="10" h="10"><a:moveTo><a:pt x="0" y="0"/></a:moveTo><a:lnTo><a:pt x="10" y="0"/></a:lnTo><a:close/></a:path></a:pathLst></a:custGeom><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill>')
        self.assertFalse(tis.is_connector_like(item))

    def test_plain_rect_with_stroke_is_not_connector_like(self):
        item = shape('<a:prstGeom prst="rect"/><a:solidFill><a:srgbClr val="EEEEEE"/></a:solidFill><a:ln><a:solidFill><a:srgbClr val="000000"/></a:solidFill></a:ln>')
        self.assertFalse(tis.is_connector_like(item))


if __name__ == "__main__":
    unittest.main()
