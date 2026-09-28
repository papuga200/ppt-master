"""F03 cycle 2: PowerPoint's wrapping of native table cells, predicted while the page is drawn (native_table_wrap.py).

The layout tests use a fixed-advance font so they run anywhere. The page tests build small SVG pages with a native table, run
them through the exporter's own table conversion and need the named font installed (Arial; Century Gothic for the T7 header row);
they skip themselves where it is not.
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

import native_table_wrap as ntw  # noqa: E402
import page_lint  # noqa: E402

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


class FixedMetrics(ntw.Metrics):
    """Every character is 0.5 em wide, a space 0.25 em: widths are arithmetic."""

    def __init__(self) -> None:  # no font index
        self.missing = set()

    def char_width(self, char: str, run: ntw.Run) -> float:
        return run.px * (0.25 if char == " " else 0.5)


FM = FixedMetrics()


def _para(text: str, px: float = 10.0, bold: bool = False) -> ntw.Paragraph:
    return ntw.Paragraph([ntw.Run(text, "Fixed", px, bold)])


# --------------------------------------------------------------------------------------------------------------------
# line breaking
# --------------------------------------------------------------------------------------------------------------------
def test_greedy_wrap_breaks_at_spaces_and_trailing_space_does_not_count():
    # "aaaa" = 20 px, space 2.5 px: "aaaa aaaa" = 42.5 px
    lines = ntw.break_paragraph(_para("aaaa aaaa aaaa"), 42.5, FM, slack=0)
    assert [line.text for line in lines] == ["aaaa aaaa", "aaaa"]
    assert not any(line.split for line in lines)
    assert [line.text for line in ntw.break_paragraph(_para("aaaa aaaa aaaa"), 42.4, FM, slack=0)] == ["aaaa", "aaaa", "aaaa"]


def test_slack_lets_a_line_a_hair_over_the_width_fit():
    # PowerPoint kept `... annual operating` on one line 0.02 px over its 355 px (kirkland2 s9)
    assert len(ntw.break_paragraph(_para("aaaa aaaa"), 42.4, FM, slack=0)) == 2
    assert len(ntw.break_paragraph(_para("aaaa aaaa"), 42.4, FM, slack=0.25)) == 1


def test_a_word_wider_than_the_cell_is_broken_between_characters():
    # "Hours" = 25 px in a 21 px cell: PowerPoint sets `Hour|s`
    lines = ntw.break_paragraph(_para("Hours"), 21.0, FM, slack=0)
    assert [line.text for line in lines] == ["Hour", "s"]
    assert lines[0].split and lines[0].word == "Hours" and lines[0].word_px == pytest.approx(25.0)


def test_break_after_a_hyphen_but_not_after_a_slash():
    assert [line.text for line in ntw.break_paragraph(_para("aaaa-bbbb"), 30.0, FM, slack=0)] == ["aaaa-", "bbbb"]
    slashed = ntw.break_paragraph(_para("aaaa/bbbb"), 30.0, FM, slack=0)
    assert slashed[0].split and slashed[0].word == "aaaa/bbbb"


def test_hard_line_break_and_empty_paragraph():
    lines = ntw.break_paragraph(ntw.Paragraph([ntw.Run("ab", "Fixed", 10), ntw.Run("\n", "Fixed", 10), ntw.Run("cd", "Fixed", 10)]), 100, FM)
    assert [line.text for line in lines] == ["ab", "cd"]
    assert len(ntw.break_paragraph(_para(""), 100, FM)) == 1


# --------------------------------------------------------------------------------------------------------------------
# the table XML the exporter writes
# --------------------------------------------------------------------------------------------------------------------
def _frame(cells_xml: str, cols=(100, 50), rows=(28,), extra_tc="") -> ET.Element:
    grid = "".join(f'<a:gridCol w="{c * 9525}"/>' for c in cols)
    trs = "".join(f'<a:tr h="{h * 9525}">{cells_xml}</a:tr>' for h in rows)
    xml = (f'<p:graphicFrame xmlns:p="{P}" xmlns:a="{A}"><p:nvGraphicFramePr><p:cNvPr id="3" name="fees"/></p:nvGraphicFramePr>'
           f'<p:xfrm><a:off x="{10 * 9525}" y="{20 * 9525}"/><a:ext cx="{sum(cols) * 9525}" cy="{sum(rows) * 9525}"/></p:xfrm>'
           f'<a:graphic><a:graphicData><a:tbl><a:tblGrid>{grid}</a:tblGrid>{trs}</a:tbl></a:graphicData></a:graphic></p:graphicFrame>')
    return ET.fromstring(xml)


def _tc(text: str, sz: int = 1050, bold: bool = True, margins: str = "", end: str = "") -> str:
    return (f'<a:tc><a:txBody><a:bodyPr/><a:p><a:r><a:rPr sz="{sz}" b="{int(bold)}"><a:latin typeface="Fixed"/></a:rPr><a:t>{text}</a:t></a:r>{end}</a:p>'
            f'</a:txBody><a:tcPr{margins}/></a:tc>')


def test_default_cell_margins_are_powerpoints_tenth_and_twentieth_of_an_inch():
    table = ntw.parse_table_frame(_frame(_tc("Days") + _tc("Hours", margins=' marL="76200" marR="76200" marT="47625" marB="47625"')))
    assert table.name == "fees" and (table.x, table.y) == (10, 20) and table.cols == [100, 50] and table.rows == [28]
    assert table.cells[0].margins == pytest.approx((9.6, 9.6, 4.8, 4.8))
    assert table.cells[1].margins == pytest.approx((8, 8, 5, 5))
    run = table.cells[0].paragraphs[0].runs[0]
    assert run.px == pytest.approx(14.0) and run.bold and run.face == "Fixed"


def test_an_empty_cell_takes_its_end_of_paragraph_size_or_the_masters():
    table = ntw.parse_table_frame(_frame(_tc("", sz=900) + _tc("", sz=900, end='<a:endParaRPr sz="900"/>')), empty_hpt=1800)
    assert table.cells[0].paragraphs[0].runs[0].px == pytest.approx(24.0)  # the empty 9 pt run is ignored: 18 pt master size
    assert table.cells[1].paragraphs[0].runs[0].px == pytest.approx(12.0)


def test_row_height_is_lines_times_1_2_plus_margins_never_below_the_planned_height():
    # 14 px bold "Hours" = 35 px; a 50 px column less 16 px margins leaves 34 px: two lines, 2 x 16.8 + 10 = 43.6 px
    table = ntw.parse_table_frame(_frame(_tc("Role") + _tc("Hours", margins=' marL="76200" marR="76200" marT="47625" marB="47625"'), rows=(31, 31)))
    layout = ntw.layout_table(table, FM)
    assert layout.rows == pytest.approx([43.6, 43.6])
    assert layout.growth == pytest.approx(25.2)
    short = ntw.parse_table_frame(_frame(_tc("Role") + _tc("Hr"), rows=(31,)))
    assert ntw.layout_table(short, FM).rows == [31]


def test_merged_cell_spans_its_columns():
    xml = (f'<a:tc gridSpan="2"><a:txBody><a:bodyPr/><a:p><a:r><a:rPr sz="1050"/><a:t>{"a" * 20}</a:t></a:r></a:p></a:txBody><a:tcPr/></a:tc>'
           '<a:tc hMerge="1"><a:txBody><a:bodyPr/><a:p/></a:txBody><a:tcPr/></a:tc>')
    table = ntw.parse_table_frame(_frame(xml))
    layout = ntw.layout_table(table, FM)
    assert len(layout.cells) == 1 and layout.cells[0].available == pytest.approx(150 - 19.2)
    # one 140 px word (20 x 7 px) in 130.8 px: split across two lines
    assert layout.cells[0].line_count == 2 and layout.cells[0].lines[0][0].split


# --------------------------------------------------------------------------------------------------------------------
# pages: the exporter's own table, the SVG's lines and what is below
# --------------------------------------------------------------------------------------------------------------------
def _font_installed(face: str) -> bool:
    return ntw.metrics().installed(face)


def _page(tmp_path: Path, headers, widths, *, font="Arial", size=14, padding=(8, 8, 5, 5), row_h=31, box_gap=6, body=None, name="fees-table") -> Path:
    x, y = 58, 251
    body = body or [["x"] * len(headers)]
    rows = [headers] + body
    cell = lambda text, bold, align: {"text": text, "bold": bold, "font_size": size, "align": align, "valign": "middle", "fill": "#FFFFFF",
                                      "color": "#000000", "padding": {"left": padding[0], "right": padding[1], "top": padding[2], "bottom": padding[3]}}
    payload = {"schema": "ppt-master.semantic-table.v2", "name": name, "x": x, "y": y, "width": sum(widths), "height": row_h * len(rows),
               "style": {"font_family": font, "font_size": size, "band_row": False}, "column_widths": list(widths), "row_heights": [row_h] * len(rows),
               "header_rows": 1, "columns": [cell(h, True, "l") for h in headers], "rows": [[cell(t, False, "l") for t in r] for r in body]}
    parts = []
    for r, row in enumerate(rows):
        left = x
        for c, text in enumerate(row):
            top = y + r * row_h
            parts.append(f'<rect x="{left}" y="{top}" width="{widths[c]}" height="{row_h}" fill="#FFFFFF"/>')
            weight = "bold" if r == 0 else "normal"
            parts.append(f'<text x="{left + padding[0]}" y="{top + row_h * 0.66:.2f}" text-anchor="start" font-size="{size}" font-weight="{weight}" fill="#000000">{text}</text>')
            left += widths[c]
    bottom = y + row_h * len(rows)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" font-family="{font}">'
           f'<g id="{name}" data-pptx-replace-with="table" data-pptx-bounds="{x} {y} {sum(widths)} {row_h * len(rows)}">'
           f'<metadata type="application/json">{json.dumps(payload)}</metadata>{"".join(parts)}</g>'
           f'<g id="controls"><rect x="{x}" y="{bottom + box_gap}" width="{sum(widths)}" height="60" fill="#E8E8E8"/></g></svg>')
    page = tmp_path / "11_fees.svg"
    page.write_text(svg, encoding="utf-8")
    return page


def test_exporter_tables_reads_the_exporters_widths_and_margins(tmp_path):
    page = _page(tmp_path, ["Role / grade", "Days"], [305, 57])
    tables = ntw.exporter_tables(page)
    assert len(tables) == 1
    table = tables[0]
    assert table.name == "fees-table" and table.cols == pytest.approx([305, 57], abs=0.01) and table.rows == pytest.approx([31, 31], abs=0.01)
    assert table.cells[1].margins == pytest.approx((8, 8, 5, 5), abs=0.01)
    assert table.cells[1].paragraphs[0].runs[0].bold and table.cells[1].paragraphs[0].runs[0].px == pytest.approx(14, abs=0.01)


@pytest.mark.skipif(not ntw.metrics().installed("Century Gothic"), reason="Century Gothic is not installed")
def test_t7_header_row_is_predicted_as_powerpoint_measured_it(tmp_path):
    """Campaign test T7 final export (29 Sep 2026): PowerPoint set `USD/ | h` and `Fee | USD`, row 1 grew from 31 to 44 px into the boxes below."""
    page = _page(tmp_path, ["Role / grade", "Days", "Hours", "USD/h", "Fee USD"], [305, 57, 65, 56, 69], font="Century Gothic",
                 body=[["Partner", "2", "16", "325", "5,200"]])
    found = {f["kind"]: f for f in ntw.predict(page)}
    split = found["NATIVE_WORD_SPLIT"]
    assert split["hard"] and split["col"] == 4 and "`USD/h`" in split["message"] and "USD/ | h" in split["message"]
    assert "needs 57 px" in split["message"] and "it is 56 px" in split["message"] and "widen it by at least 1 px" in split["message"]
    drift = found["NATIVE_WRAP_DRIFT"]
    assert not drift["hard"] and drift["col"] == 5 and drift["svg_lines"] == 1 and drift["ppt_lines"] == 2
    growth = found["NATIVE_ROW_GROWTH"]
    assert growth["severity"] == "blocker" and not growth["hard"]
    assert growth["rows"][0] == {"row": 1, "drawn_px": 31.0, "ppt_px": 43.6}
    assert "`controls`" in growth["message"]


@pytest.mark.skipif(not ntw.metrics().installed("Arial"), reason="Arial is not installed")
def test_wide_enough_columns_give_no_finding_and_free_space_is_a_note(tmp_path):
    assert ntw.predict(_page(tmp_path, ["Role", "Days"], [305, 80])) == []
    # a two-line body cell the SVG draws on one line grows its row; with 60 px of room below it is only a note
    page = _page(tmp_path, ["Role", "Days"], [120, 80], body=[["a rather long description here", "2"]], box_gap=60)
    kinds = {(f["kind"], f["severity"]) for f in ntw.predict(page)}
    assert ("NATIVE_WRAP_DRIFT", "blocker") in kinds and ("NATIVE_ROW_GROWTH", "note") in kinds


@pytest.mark.skipif(not ntw.metrics().installed("Arial"), reason="Arial is not installed")
def test_a_stale_or_missing_fallback_stamp_does_not_stop_the_prediction(tmp_path):
    page = _page(tmp_path, ["Role", "Hours"], [305, 30])
    text = page.read_text(encoding="utf-8").replace('data-pptx-bounds=', 'data-pptx-fallback-sha256="' + "0" * 64 + '" data-pptx-bounds=', 1)
    page.write_text(text, encoding="utf-8")
    assert any(f["kind"] == "NATIVE_WORD_SPLIT" for f in ntw.predict(page))


def test_exporter_writes_the_cell_size_on_an_empty_paragraph(tmp_path):
    """Measured in PowerPoint (29 Sep 2026): without `a:endParaRPr` an empty 9 pt cell took an 18 pt line and its 28 px row grew to 38 px."""
    page = _page(tmp_path, ["Role", "Fee"], [200, 80], body=[["Total", ""]], size=12, row_h=28)
    table = ntw.exporter_tables(page)[0]
    empty = table.cells[3].paragraphs[0].runs[0]
    assert empty.text == "" and empty.px == pytest.approx(12, abs=0.01)
    from svg_to_pptx.native_objects.table import _table_empty_paragraph_end
    assert _table_empty_paragraph_end("", font_size=900, bold=True, language="en-US") == '<a:endParaRPr lang="en-US" sz="900" b="1"/>'
    assert _table_empty_paragraph_end("x", font_size=900, bold=True, language="en-US") == ""


# --------------------------------------------------------------------------------------------------------------------
# page_lint
# --------------------------------------------------------------------------------------------------------------------
def test_page_lint_passes_wrap_predictions_through_with_their_severity():
    class Done:
        def __init__(self, out):
            self.out = out

        def communicate(self, timeout=None):
            return self.out, ""

        def kill(self):
            pass
    items = [{"marker": "fees-table", "finding": "colour not projected"},
             {"kind": "NATIVE_WORD_SPLIT", "severity": "blocker", "hard": True, "rect": [1, 2, 3, 4], "message": "breaks `Days`", "col": 2},
             {"kind": "NATIVE_ROW_GROWTH", "severity": "note", "hard": False, "rect": [1, 2, 3, 4], "message": "into free space"}]
    found = page_lint._native_findings(Done(json.dumps(items)))
    assert [f["kind"] for f in found] == ["NATIVE", "NATIVE_WORD_SPLIT", "NATIVE_ROW_GROWTH"]
    assert found[0]["hard"] and found[1]["hard"] and found[1]["rect"] == [1, 2, 3, 4] and found[1]["col"] == 2
    assert found[2]["severity"] == "note" and not found[2]["hard"]


@pytest.mark.skipif(not ntw.metrics().installed("Arial"), reason="Arial is not installed")
def test_a_split_predicted_without_the_real_font_is_flagged_not_certain(tmp_path):
    page = _page(tmp_path, ["Role", "Hours"], [305, 30], font="No Such Face Sans")
    splits = [f for f in ntw.predict(page) if f["kind"] == "NATIVE_WORD_SPLIT"]
    assert splits and not splits[0]["hard"] and "not installed here" in splits[0]["message"]
