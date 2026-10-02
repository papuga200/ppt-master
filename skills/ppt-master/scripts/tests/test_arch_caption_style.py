#!/usr/bin/env python3
"""PPT Master - Architecture Caption Style

Verify independently readable caption colors without changing legacy rendering.

Usage:
    python -m unittest tests.test_arch_caption_style

Dependencies:
    Standard library and the architecture renderer.
"""

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS / 'exp_svg' / 'arch'))
import scene as sc


class CaptionStyleTests(unittest.TestCase):
    def render(self, text_color=None):
        value = {'font': {'family': 'Segoe UI'}, 'zones': [], 'nodes': [],
                 'edges': [], 'annotations': [], 'type': {'zone_label_px': 15},
                 'style': {'zone_kinds': {'agent': {'fill': '#102C46',
                            'stroke': '#34516B', 'width': 1.2}}}}
        if text_color:
            value['style']['zone_kinds']['agent']['text'] = text_color
        value['zones'] = [{'id': 'agent', 'kind': 'agent',
                          'box': {'x': 20, 'y': 30, 'w': 200, 'h': 100},
                          'caption': {'lines': ['Agent workflow'],
                          'box': {'x': 36, 'y': 40, 'w': 160, 'h': 18}}}]
        return ET.fromstring(sc.render_group(value))

    def test_explicit_caption_color_does_not_recolor_outline(self):
        output = self.render('#E8F4FC')
        self.assertEqual(output.find('.//rect').get('stroke'), '#34516B')
        self.assertEqual(output.find('.//text').get('fill'), '#E8F4FC')

    def test_legacy_caption_uses_outline_color(self):
        output = self.render()
        self.assertEqual(output.find('.//text').get('fill'), '#34516B')
