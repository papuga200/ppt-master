"""F03: the exported deck measured in PowerPoint (pptx_parity.py) and the exporter-side fixes for what it found.

The detector tests feed synthetic PowerPoint measurements (the JSON the COM script writes) and small SVG pages, so they run
anywhere. The exporter tests build small decks with python-pptx or convert small SVGs. The last two tests drive
Microsoft PowerPoint through COM and skip themselves where it is not installed.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pptx_parity  # noqa: E402
import pptx_text_in_shapes  # noqa: E402

PT = 0.75  # px on the 1280 x 720 basis -> points on a 960 x 540 slide
ZWSP = "\u200b"


# --------------------------------------------------------------------------------------------------------------------
# synthetic measurements
# --------------------------------------------------------------------------------------------------------------------
def _para(text, bound=None, lines=None, bullet=0, number=None, char=None, align=1, **extra):
    para = {"text": text, "align": align, "bullet_visible": -1 if bullet else 0, "bullet_type": bullet, "lines": lines if lines is not None else [text]}
    if bound:
        para["bound"] = [v * PT for v in bound]
    if number is not None:
        para["bullet_number"] = number
    if char is not None:
        para["bullet_char"] = char
    para.update(extra)
    return para


def _text(sid, name, box, bound, paragraphs, z, fill=False, line=False, **extra):
    return {"z": z, "id": sid, "name": name, "type": 17 if not (fill or line) else 1, "parent": None, "box": [v * PT for v in box],
            "fill": fill, "line": line, "fill_rgb": extra.pop("fill_rgb", 0x223344) if fill else None,
            "frame": {"margins": [0, 0, 0, 0], "wrap": -1, "autosize": 0, "anchor": 1, "text": "\r".join(p["text"] for p in paragraphs),
                      "bound": [v * PT for v in bound], "line_count": sum(len(p["lines"]) for p in paragraphs), "paragraphs": paragraphs}, **extra}


def _rect(sid, name, box, z, fill_rgb=0x6B4A1B, line=False):
    return {"z": z, "id": sid, "name": name, "type": 1, "parent": None, "box": [v * PT for v in box], "fill": True, "fill_rgb": fill_rgb, "line": line}


def _measure(*slides, background=0xEDF2F4):
    return {"width": 960, "height": 540, "slides": [{"index": i, "background": {"follow": 0, "slide": background}, "shapes": list(shapes)}
                                                     for i, shapes in enumerate(slides, start=1)]}


def _svg(tmp_path, name, body):
    path = tmp_path / f"{name}.svg"
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">{body}</svg>', encoding="utf-8")
    return path


def _codes(findings, severity=None):
    return sorted((f["code"], f["severity"]) for f in findings if severity is None or f["severity"] == severity)


# --------------------------------------------------------------------------------------------------------------------
# detector
# --------------------------------------------------------------------------------------------------------------------
def test_a_bullet_on_a_zero_width_paragraph_is_a_certain_stray_bullet_unless_nothing_shows_it():
    carrier = _text(10, "content-slot Placeholder Carrier", [71, 207, 12, 28], [107, 207, 5, 22],
                    [_para(ZWSP, bound=[107, 207, 5, 22], bullet=1, char=8226, bullet_text_color=-1, text_rgb=0x5B616C)], z=1)
    assert _codes(pptx_parity.analyse(_measure([carrier]))) == [("STRAY_BULLET", "certain")]
    hidden = json.loads(json.dumps(carrier))
    hidden["frame"]["paragraphs"][0]["text_rgb"] = 0xEDF2F4  # painted in the slide's own background colour
    assert _codes(pptx_parity.analyse(_measure([hidden]))) == [("STRAY_BULLET", "flagged")]
    table_above = {"z": 2, "id": 11, "name": "evidence-table", "type": 19, "parent": None, "box": [60 * PT, 200 * PT, 600 * PT, 200 * PT],
                   "fill": False, "line": False, "table": {"rows": [], "cols": [], "cells": []}}
    assert _codes(pptx_parity.analyse(_measure([carrier, table_above]))) == [("STRAY_BULLET", "flagged")]


def test_text_that_powerpoint_sets_lower_runs_out_of_its_panel_and_into_the_rule_below(tmp_path):
    svg = _svg(tmp_path, "08_checks", '<rect x="80" y="544" width="1117" height="35" fill="#182B59"/>'
               '<text x="94" y="558" font-size="12" fill="#FFFFFF">Outside the automated gates: a person checks<tspan x="94" dy="16.8">what is left before release.</tspan></text>'
               '<line x1="98" y1="584" x2="1196" y2="584" stroke="#C0C0C0"/>')
    band = _rect(24, "Rectangle 24", [80, 544, 1117, 35], z=1, fill_rgb=0x592B18)
    text = _text(25, "Text: Outside", [93.5, 547.8, 707.6, 35.3], [93.5, 547.8, 685.3, 38.9],
                 [_para("Outside the automated gates: a person checks\x0bwhat is left before release.", bound=[93.5, 547.8, 685.3, 38.9],
                        lines=["Outside the automated gates: a person checks\x0b", "what is left before release."])], z=2)
    findings = pptx_parity.analyse(_measure([band, text]), {1: {25: {"frame": [93.5 * PT, 547.8 * PT, 801.1 * PT, 583.1 * PT]}}}, [svg])
    assert ("OVERFLOW", "certain") in _codes(findings)
    overflow = next(f for f in findings if f["code"] == "OVERFLOW")
    assert "Rectangle 24" in overflow["message"] and overflow["measured_against"] == "svg" and overflow["focus"]


def test_the_same_text_kept_inside_its_panel_raises_nothing(tmp_path):
    svg = _svg(tmp_path, "08_checks", '<rect x="80" y="544" width="1117" height="45" fill="#182B59"/>'
               '<text x="94" y="558" font-size="12" fill="#FFFFFF">Outside the automated gates: a person checks<tspan x="94" dy="16.8">what is left before release.</tspan></text>')
    band = _rect(24, "Rectangle 24", [80, 544, 1117, 45], z=1, fill_rgb=0x592B18)
    text = _text(25, "Text: Outside", [93.5, 547.8, 707.6, 35.3], [93.5, 546.0, 685.3, 34.0],
                 [_para("Outside the automated gates: a person checks\x0bwhat is left before release.", bound=[93.5, 546.0, 685.3, 34.0],
                        lines=["Outside the automated gates: a person checks\x0b", "what is left before release."])], z=2)
    assert pptx_parity.analyse(_measure([band, text]), {}, [svg]) == []


def test_text_that_grows_down_into_the_box_below_is_a_collision(tmp_path):
    svg = _svg(tmp_path, "04_route", '<text x="345" y="264" font-size="12">Start with a topic, a brief or documents; an existing deck can be source'
               '<tspan x="345" dy="17">when its story and page order may change.</tspan></text><rect x="345" y="286" width="560" height="90" fill="#E8EDF2"/>')
    text = _text(42, "Text: Start with a topic", [344.5, 253.8, 439.6, 35.5], [344.5, 253.8, 425.3, 33.1],
                 [_para("Start with a topic, a brief or documents; an existing deck can be source\x0bwhen its story and page order may change.",
                        bound=[344.5, 253.8, 425.3, 33.1], lines=["Start with a topic ", "when its story"])], z=1)
    box = _rect(43, "Box: Default Generate", [345, 285, 560, 90], z=2, fill_rgb=0xF2EDE8)
    findings = pptx_parity.analyse(_measure([text, box]), {}, [svg])
    assert _codes(findings) == [("TEXT_COLLISION", "certain")] and "Box: Default Generate" in findings[0]["message"]


def test_a_table_that_grows_under_the_box_below_it_is_a_certain_overlap_and_names_the_rows():
    table = {"z": 1, "id": 19, "name": "inventory-table", "type": 19, "parent": None, "box": [v * PT for v in (58, 180, 1160, 276)],
             "fill": False, "line": False, "table": {"rows": [v * PT for v in (32, 49, 49, 49, 49, 49)], "cols": [],
                                                      "cells": [{"row": 2, "col": 3, "text": "Which count exports exist?", "line_count": 2, "bound": [0, 0, 100, 30],
                                                                 "paragraphs": [_para("Which count exports exist?", lines=["Which count ", "exports exist?"])]}]}}
    below = _rect(30, "Box: PROPOSED REPRESENTATIVE COVERAGE", [58, 440, 700, 90], z=2, fill_rgb=0xE0E0E0)
    plan = {1: {19: {"rows": [v * PT for v in (32, 41, 41, 41, 41, 41)], "frame": [58 * PT, 180 * PT, 1218 * PT, 419 * PT]}}}
    findings = pptx_parity.analyse(_measure([table, below]), plan)
    assert ("ROW_GROWTH", "flagged") in _codes(findings) and ("TABLE_OVERLAP", "certain") in _codes(findings)
    overlap = next(f for f in findings if f["code"] == "TABLE_OVERLAP")
    assert "PROPOSED REPRESENTATIVE COVERAGE" in overlap["message"] and overlap["growth_px"] == pytest.approx(40, abs=1)


def test_a_word_broken_across_two_lines_is_a_header_split_but_a_break_at_a_space_is_not():
    assert pptx_parity._mid_word_break(["strategy/governan", "ce"]) == "governan|ce"
    assert pptx_parity._mid_word_break(["strategy and ", "governance"]) is None
    assert pptx_parity._mid_word_break(["first line\x0b", "second"]) is None
    assert pptx_parity._mid_word_break(["cost-", "benefit"]) is None


def test_a_wrapped_middle_dot_line_shown_as_a_bullet_is_an_accidental_bullet(tmp_path):
    svg = _svg(tmp_path, "03_weights", '<text x="879" y="313" font-size="12">Value 25% · equity 25% · feasibility 20%'
               '<tspan x="879" dy="17">· cost 15% · readiness 15%. Provisional</tspan></text>')
    text = _text(56, "Text: Value", [879, 300, 300, 40], [879, 300, 290, 36],
                 [_para("Value 25% · equity 25% · feasibility 20%", bound=[879, 300, 290, 17]),
                  _para("cost 15% · readiness 15%. Provisional", bound=[879, 317, 290, 17], bullet=1, char=8226)], z=1)
    assert _codes(pptx_parity.analyse(_measure([text]), {}, [svg])) == [("ACCIDENTAL_BULLET", "certain")]


def test_an_automatic_number_that_differs_from_the_svg_is_renumbered(tmp_path):
    svg = _svg(tmp_path, "12_ask", '<text x="444" y="567" font-size="12">1. Confirm sponsorship.</text>'
               '<text x="444" y="588" font-size="12">2. Agree five windows.</text><text x="444" y="609" font-size="12">3. Protect the date.</text>')
    text = _text(9, "Box: ask", [444, 575, 500, 45], [444, 575, 480, 40],
                 [_para("Agree five windows.", bound=[444, 575, 480, 17], bullet=2, number=2),
                  _para("Protect the date.", bound=[444, 596, 480, 17], bullet=2, number=1)], z=1)
    lone = _text(8, "Text: 1.", [444, 555, 500, 18], [444, 555, 480, 16], [_para("1. Confirm sponsorship.", bound=[444, 555, 480, 16])], z=2)
    findings = pptx_parity.analyse(_measure([lone, text]), {}, [svg])
    assert _codes(findings) == [("RENUMBERED", "certain")] and findings[0]["ppt_number"] == 1 and findings[0]["svg_number"] == 3
    # without the SVG, the visible numbers down one column still read 1, 2, 1
    assert ("RENUMBERED", "flagged") in _codes(pptx_parity.analyse(_measure([lone, text])))


def test_a_numeric_column_the_svg_right_aligns_but_powerpoint_left_aligns_is_alignment_drift(tmp_path):
    svg = _svg(tmp_path, "11_fees", '<g data-pptx-replace-with="table"><text x="358" y="288" text-anchor="end">Days</text>'
               '<text x="358" y="317" text-anchor="end">2</text><text x="358" y="346" text-anchor="end">16</text></g>')
    cells = [{"row": 1, "col": 2, "text": "Days", "paragraphs": [_para("Days", align=3)]},
             {"row": 2, "col": 2, "text": "2", "bound": [300, 300, 10, 10], "paragraphs": [_para("2", align=1)]},
             {"row": 3, "col": 2, "text": "16", "bound": [300, 330, 10, 10], "paragraphs": [_para("16", align=1)]}]
    table = {"z": 1, "id": 5, "name": "grade-fees-table", "type": 19, "parent": None, "box": [v * PT for v in (58, 268, 526, 90)],
             "fill": False, "line": False, "table": {"rows": [v * PT for v in (29, 29, 29)], "cols": [], "cells": cells}}
    findings = pptx_parity.analyse(_measure([table]), {1: {5: {"rows": [v * PT for v in (29, 29, 29)]}}}, [svg])
    assert _codes(findings) == [("ALIGNMENT_DRIFT", "certain")] and findings[0]["column"] == 2


def test_svg_lines_follow_tspans_transforms_and_typed_markers(tmp_path):
    svg = _svg(tmp_path, "p", '<g transform="translate(0,100)"><text x="10" y="20" font-size="10">1. First item<tspan x="10" dy="15">wrapped</tspan>'
               '<tspan font-weight="bold"> still line two</tspan></text></g><text x="0" y="50" style="font-size:20px">· Lone</text>')
    lines = pptx_parity.svg_lines(svg)
    assert [(l["raw"], l["number"], l["line"]) for l in lines] == [("1. First item", 1, 0), ("wrapped still line two", None, 1), ("· Lone", None, 0)]
    assert lines[0]["baseline"] == 120 and lines[1]["baseline"] == 135 and lines[1]["pitch"] == 15 and lines[2]["size"] == 20
    assert pptx_parity.match_lines("First item wrapped still line two", lines) == lines[:2]


def test_repair_briefs_go_only_to_pages_an_author_can_fix_and_carry_numbers_crop_and_direction():
    report = {"findings": [
        {"code": "OVERFLOW", "severity": "certain", "slide": 8, "svg": "08_checks", "shape": "Text", "bbox": [94, 548, 686, 33],
         "message": "runs out of the panel by 2 px", "crop": "C:/r/parity/slide-008-01-overflow.png"},
        {"code": "STRAY_BULLET", "severity": "certain", "slide": 2, "svg": "02_summary", "shape": "Carrier", "bbox": [71, 207, 12, 28], "message": "dot"},
        {"code": "ROW_GROWTH", "severity": "flagged", "slide": 8, "svg": "08_checks", "shape": "t", "bbox": [0, 0, 1, 1], "message": "grows"}]}
    briefs = pptx_parity.repair_briefs(report)
    assert list(briefs) == ["08_checks"]
    text = briefs["08_checks"]
    assert "slide 8" in text and "by 2 px" in text and "slide-008-01-overflow.png" in text and "read_image" in text and "at least 6 px" in text


def test_the_plan_is_read_from_the_file_the_exporter_wrote(tmp_path):
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Emu(100 * 9525), Emu(200 * 9525), Emu(300 * 9525), Emu(40 * 9525))
    box.text_frame.text = "Planned"
    table = slide.shapes.add_table(3, 2, Emu(50 * 9525), Emu(400 * 9525), Emu(600 * 9525), Emu(90 * 9525))
    path = tmp_path / "plan.pptx"
    prs.save(path)
    plan = pptx_parity.read_plan(path)[1]
    frame = plan[box.shape_id]["frame"]
    assert [round(v / PT) for v in frame] == [100, 200, 400, 240]
    assert len(plan[table.shape_id]["rows"]) == 3 and sum(plan[table.shape_id]["rows"]) == pytest.approx(90 * PT, abs=0.5)


def test_crops_outline_the_finding_on_the_powerpoint_render(tmp_path):
    from PIL import Image
    render = tmp_path / "deck.render"
    render.mkdir()
    Image.new("RGB", (1600, 900), "white").save(render / "slide-001.png")
    findings = [{"code": "OVERFLOW", "severity": "certain", "slide": 1, "bbox": [100, 100, 200, 30], "focus": [90, 80, 240, 60]}]
    made = pptx_parity.crop_findings(findings, render)
    assert made and made[0].is_file() and findings[0]["crop"] == str(made[0])
    with Image.open(made[0]) as crop:
        assert crop.width >= 360 and (230, 0, 0) in {crop.getpixel((x, y)) for x in range(crop.width) for y in range(0, crop.height, 3)}


# --------------------------------------------------------------------------------------------------------------------
# exporter-side fixes
# --------------------------------------------------------------------------------------------------------------------
def _placeholder_deck(path: Path, body_text: str = ZWSP) -> None:
    from pptx import Presentation
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])  # Title and Content: its body placeholder is bulleted
    slide.shapes.title.text = "A slide title"
    slide.placeholders[1].text_frame.text = body_text
    prs.save(path)


def _bullets(path: Path) -> list[tuple[str, str | None]]:
    import zipfile
    from lxml import etree
    root = etree.fromstring(zipfile.ZipFile(path).read("ppt/slides/slide1.xml"))
    ns = pptx_text_in_shapes.NS
    out = []
    for para in root.iter(f"{{{ns['a']}}}p"):
        ppr = para.find("a:pPr", ns)
        kind = next((k for k in ("buNone", "buChar", "buAutoNum") if ppr is not None and ppr.find(f"a:{k}", ns) is not None), None)
        out.append(("".join(para.itertext()), kind))
    return out


def test_an_empty_placeholder_carrier_gets_no_bullet(tmp_path):
    source, target = tmp_path / "in.pptx", tmp_path / "out.pptx"
    _placeholder_deck(source)
    assert (ZWSP, None) in _bullets(source)  # inherits the layout's bullet: the stray dot of selfdoc P02/P08/P14/P19
    totals = pptx_text_in_shapes.convert(source, target)["totals"]
    assert (ZWSP, "buNone") in _bullets(target) and totals["bullets_cleared"] >= 1


def test_an_empty_paragraph_keeps_no_explicit_bullet_and_schema_order_holds(tmp_path):
    from lxml import etree
    para = etree.fromstring(f'<a:p xmlns:a="{pptx_text_in_shapes.A}"><a:pPr marL="10"><a:lnSpc><a:spcPct val="100000"/></a:lnSpc>'
                            '<a:buClr><a:srgbClr val="000000"/></a:buClr><a:buChar char="&#8226;"/><a:defRPr/></a:pPr><a:r><a:t> </a:t></a:r></a:p>')
    assert pptx_text_in_shapes.no_bullet(para) is True
    assert [etree.QName(c).localname for c in para.find("a:pPr", pptx_text_in_shapes.NS)] == ["lnSpc", "buNone", "defRPr"]
    assert pptx_text_in_shapes.no_bullet(para) is False


def _stacked_numbers_deck(path: Path, numbers=(2, 3, 4)) -> None:
    from pptx import Presentation
    from pptx.util import Emu, Pt
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    for index, number in enumerate(numbers):
        box = slide.shapes.add_textbox(Emu(200 * 9525), Emu((300 + 22 * index) * 9525), Emu(500 * 9525), Emu(18 * 9525))
        frame = box.text_frame
        frame.word_wrap = False
        for side in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
            setattr(frame, side, 0)
        run = frame.paragraphs[0].add_run()
        run.text = f"{number}. Item number {number} of the list"
        run.font.size = Pt(12)
    prs.save(path)


def test_typed_numbers_become_one_list_that_keeps_the_svg_numbers(tmp_path):
    import zipfile
    source, target = tmp_path / "in.pptx", tmp_path / "out.pptx"
    _stacked_numbers_deck(source)
    pptx_text_in_shapes.convert(source, target, chrome=False)
    xml = zipfile.ZipFile(target).read("ppt/slides/slide1.xml").decode("utf-8")
    starts = [chunk.split('"')[0] for chunk in xml.split('startAt="')[1:]]
    assert xml.count("buAutoNum") == 3 and starts == ["2", "2", "2"]  # identical numbering on every item: PowerPoint counts 2, 3, 4


def test_a_wrapped_middle_dot_separator_stays_text_while_a_dotted_list_stays_a_list():
    from svg_to_pptx.drawingml.context import ConvertContext
    from svg_to_pptx.drawingml.converter import convert_element
    from svg_to_pptx.tspan_flattener import flatten_positional_tspans
    root = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
                         '<text x="879" y="313" font-size="12" fill="#0E2841">Value 25% · equity 25% · feasibility 20%'
                         '<tspan x="879" dy="17">· cost 15% · readiness 15%. Provisional</tspan><tspan x="879" dy="17">workshop weights</tspan></text>'
                         '<text x="100" y="400" font-size="12" fill="#0E2841"><tspan x="100">· First point</tspan><tspan x="100" dy="17">· Second point</tspan></text></svg>')
    flatten_positional_tspans(ET.ElementTree(root), merge_paragraphs=True, preserve_line_breaks=True)
    separator, listing = [convert_element(t, ConvertContext(trace_events=[])).xml for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert "buChar" not in separator and ("·" in separator or "&#183;" in separator)
    assert separator.count("<a:p>") + separator.count("<a:p ") >= 2
    assert listing.count("buChar") == 2


def test_a_right_aligned_numeric_column_in_the_fallback_stays_right_aligned_in_the_native_table():
    from svg_to_pptx.drawingml.context import ConvertContext
    from svg_to_pptx.native_objects.table import _build_native_table
    payload = {"schema": "ppt-master.semantic-table.v2", "x": 100, "y": 100, "width": 300, "height": 90, "column_widths": [200, 100], "row_heights": [30, 30, 30],
               "columns": [{"text": "Role", "align": "l"}, {"text": "Days", "align": "r"}],
               "rows": [["Partner", "2"], ["Director", "16"]]}
    group = ET.fromstring(
        '<g xmlns="http://www.w3.org/2000/svg" id="fees" data-pptx-replace-with="table" data-pptx-bounds="100 100 300 90">'
        '<rect x="100" y="100" width="300" height="30" fill="#3B43D7"/><rect x="100" y="130" width="300" height="30" fill="#FFFFFF"/>'
        '<rect x="100" y="160" width="300" height="30" fill="#E8E8E8"/>'
        '<text x="110" y="120" fill="#FFFFFF">Role</text><text x="390" y="120" text-anchor="end" fill="#FFFFFF">Days</text>'
        '<text x="110" y="150">Partner</text><text x="390" y="150" text-anchor="end">2</text>'
        '<text x="110" y="180">Director</text><text x="390" y="180" text-anchor="end">16</text></g>')
    xml = _build_native_table(group, ConvertContext(native_objects_enabled=True, trace_events=[]), payload).xml
    import re
    rows = re.findall(r"<a:tr[ >].*?</a:tr>", xml, re.S)
    for row in rows[1:]:  # body rows: the number column right, the name column as the payload says
        cells = re.findall(r"<a:tc[ >].*?</a:tc>", row, re.S)
        assert 'algn="r"' in cells[1] and 'algn="r"' not in cells[0]


def test_a_carrier_holding_only_a_zero_width_character_is_not_stacked_with_real_text(tmp_path):
    from pptx import Presentation
    from pptx.util import Emu, Pt
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    for index, text in enumerate([ZWSP, "2. Read the postflight status and every warning."]):
        box = slide.shapes.add_textbox(Emu(200 * 9525), Emu((300 + 20 * index) * 9525), Emu(500 * 9525), Emu(18 * 9525))
        run = box.text_frame.paragraphs[0].add_run()
        run.text = text
        run.font.size = Pt(12)
    source, target = tmp_path / "in.pptx", tmp_path / "out.pptx"
    prs.save(source)
    pptx_text_in_shapes.convert(source, target, chrome=False)
    texts = [shape.text_frame.text for shape in Presentation(target).slides[0].shapes if shape.has_text_frame]
    assert ZWSP in texts and "2. Read the postflight status and every warning." in texts


# --------------------------------------------------------------------------------------------------------------------
# PowerPoint itself (COM); skipped where it is not installed
# --------------------------------------------------------------------------------------------------------------------
def _powerpoint_or_skip(path: Path) -> dict:
    if sys.platform != "win32":
        pytest.skip("PowerPoint measurement needs Windows")
    try:
        return pptx_parity.measure_with_powerpoint(path, timeout=240)
    except pptx_parity.ParityUnavailable as exc:
        pytest.skip(f"PowerPoint not available: {exc}")


def test_powerpoint_shows_the_stray_bullet_before_the_fix_and_none_after(tmp_path):
    source, target = tmp_path / "in.pptx", tmp_path / "out.pptx"
    _placeholder_deck(source)
    before = pptx_parity.analyse(_powerpoint_or_skip(source), pptx_parity.read_plan(source))
    assert ("STRAY_BULLET", "certain") in _codes(before)
    pptx_text_in_shapes.convert(source, target)
    assert [f for f in pptx_parity.analyse(_powerpoint_or_skip(target), pptx_parity.read_plan(target)) if f["code"] == "STRAY_BULLET"] == []


def test_powerpoint_numbers_the_converted_list_as_the_svg_did(tmp_path):
    source, target = tmp_path / "in.pptx", tmp_path / "out.pptx"
    _stacked_numbers_deck(source, (2, 3, 4))
    pptx_text_in_shapes.convert(source, target, chrome=False)
    measured = _powerpoint_or_skip(target)
    numbers = [p.get("bullet_number") for s in measured["slides"][0]["shapes"] for p in (s.get("frame") or {}).get("paragraphs", []) if p.get("bullet_type") == 2]
    assert numbers == [2, 3, 4]


# --------------------------------------------------------------------------------------------------------------------
# runner: one bounded repair round on what PowerPoint drew (no model is called: repair and export are stand-ins)
# --------------------------------------------------------------------------------------------------------------------
def _runner_module():
    import importlib
    host_dir = Path(__file__).resolve().parents[4] / "hosts" / "responses_api"
    if str(host_dir) not in sys.path:
        sys.path.insert(0, str(host_dir))
    return importlib.import_module("deck_runner")


def _finding(slide, svg, code="OVERFLOW", severity="certain"):
    return {"code": code, "severity": severity, "slide": slide, "svg": svg, "shape": "Text", "bbox": [1, 2, 3, 4], "message": f"{code} on {svg}"}


def test_the_runner_sends_one_parity_round_to_the_pages_then_re_exports_once_and_lists_what_remains(tmp_path):
    import argparse
    runner = _runner_module()
    bare = object.__new__(runner.Runner)
    bare.args = argparse.Namespace(repair_rounds=2, max_parallel=4, no_parity_repair=False)
    bare.project = tmp_path
    bare.page_sessions = {"02_a": ["s.02_a"], "03_b": ["s.03_b"]}
    bare.parity_rounds, bare.outstanding, said = [], {}, []
    bare.say = said.append
    deck2 = tmp_path / "exports" / "deck2.pptx"
    deck2.parent.mkdir()
    bare.parity = {"pptx": str(tmp_path / "exports" / "deck1.pptx"), "summary": {"certain": 3, "flagged": 0, "slides_with_certain": [2, 3, 5]},
                   "findings": [_finding(2, "02_a"), _finding(3, "03_b", "TEXT_COLLISION"), _finding(5, "05_c", "STRAY_BULLET")]}
    repaired, exports = [], []
    bare.repair = lambda page, issues, hint="": repaired.append((page["stem"], issues, hint))
    bare.checker = lambda: {}

    def export(outstanding=None):
        exports.append(outstanding)
        bare.parity = {"pptx": str(deck2), "summary": {"certain": 1, "flagged": 0, "slides_with_certain": [3]}, "findings": [_finding(3, "03_b", "TEXT_COLLISION")]}
        return deck2

    bare.export = export
    pages = [{"stem": s, "number": n} for n, s in ((2, "02_a"), (3, "03_b"), (5, "05_c"))]
    result = bare.parity_repair(pages, tmp_path / "exports" / "deck1.pptx")
    assert result == deck2 and exports == [None]  # exactly one re-export
    assert sorted(stem for stem, _, _ in repaired) == ["02_a", "03_b"]  # a stray bullet is the exporter's, not an author's
    assert all("POWERPOINT PARITY" in hint for _, _, hint in repaired)
    assert bare.parity_rounds == [{**bare.parity_rounds[0], "before": 3, "after": 1, "pages": ["02_a", "03_b"]}]
    assert "03_b" in deck2.with_suffix(".outstanding.md").read_text(encoding="utf-8")
    journal = json.loads((tmp_path / "quality-run.json").read_text(encoding="utf-8"))
    assert journal["parity_repair"][0]["after"] == 1


def test_the_runner_records_parity_when_measured_and_says_unverified_when_powerpoint_is_absent(tmp_path):
    import argparse
    import subprocess
    runner = _runner_module()
    bare = object.__new__(runner.Runner)
    bare.args = argparse.Namespace()
    bare.project = tmp_path
    said = []
    bare.say = said.append
    deck = tmp_path / "deck.pptx"
    bare.script = lambda name, *args, check=False: subprocess.CompletedProcess([name], 3, "PowerPoint parity not measured: no PowerPoint", "")
    assert bare.powerpoint_parity(deck) is None and "not measured" in said[-1]
    deck.with_suffix(".parity.json").write_text(json.dumps({"pptx": str(deck), "summary": {"certain": 2, "flagged": 1, "slides_with_certain": [4]},
                                                            "findings": []}), encoding="utf-8")
    bare.script = lambda name, *args, check=False: subprocess.CompletedProcess([name], 0, "", "")
    assert bare.powerpoint_parity(deck)["summary"]["certain"] == 2 and "2 certain" in said[-1]
