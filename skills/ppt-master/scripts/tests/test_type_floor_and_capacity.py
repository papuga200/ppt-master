"""F02: the legible type floor (MIN_TYPE), title checks, body fill (DEAD_BAND / UNDERFILLED / HUDDLED) and the plan's capacity contract."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import page_lint  # noqa: E402
import type_floor  # noqa: E402

PAGE = {"floors": {"body": 16.0, "secondary": 14.0, "footnote": 11.0, "furniture": 11.0}, "title_size": 32.0, "sparse": False}
_ORDER = [100]


def text(label, x, y, size=16, width=None, lines=1, ctx=(), groups=(), tid=None, scale=1.0, family="Segoe UI", line_gap=1.4):
    """A text element as the browser measurement reports it: one part per line, each with its rendered font size."""
    width = width if width is not None else 0.5 * size * len(label.split("\n")[0])
    words = label.split("\n")
    parts = [{"rect": [x, y + i * size * line_gap, x + width, y + i * size * line_gap + size * 1.2], "text": words[i] if i < len(words) else label,
              "fill": "rgb(20, 20, 20)", "size": size * scale} for i in range(lines)]
    _ORDER[0] += 1
    return {"index": _ORDER[0], "order": _ORDER[0], "id": tid, "text": " ".join(words), "parts": parts, "fill": "rgb(20, 20, 20)", "size": size, "opacity": 1.0,
            "groups": list(groups), "waiver": None, "scale": scale, "ctx": list(ctx), "weight": "400", "family": family, "words": len(" ".join(words).split())}


def shape(x0, y0, x1, y1, fill="rgb(240, 240, 240)", ctx=(), order=1):
    return {"index": order, "order": order, "id": None, "tag": "rect", "rect": [x0, y0, x1, y1], "stroke": None, "width": 0, "dashed": False,
            "fill": fill, "opacity": 1.0, "groups": [], "waiver": None, "ctx": list(ctx), "framed": False}


def line(x0, y0, x1, y1, order=2):
    return {"index": order, "order": order, "id": None, "tag": "line", "rect": [min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], "stroke": "rgb(0,0,0)",
            "width": 1, "dashed": False, "fill": None, "opacity": 1.0, "groups": [], "waiver": None, "ctx": [], "pts": [[x0, y0], [x1, y1]]}


def title(label="A claim the page proves in one sentence", size=32):
    return text(label, 72, 60, size=size, width=800, ctx=["ph:title"], groups=["title-slot"])


def footer():
    return text("Deck line", 72, 686, size=11, width=300, ctx=["role:chrome"], groups=["chrome"])


def run(texts, shapes=(), lines=(), page=PAGE, images=()):
    geometry = {"canvas": [1280, 720], "texts": list(texts), "shapes": list(shapes), "lines": list(lines), "images": list(images)}
    return page_lint.analyse(geometry, None, None, page=page)


def kinds(findings):
    return sorted((f["kind"], f.get("role"), f.get("px")) for f in findings if f["kind"] in ("MIN_TYPE", "TEMPLATE_TYPE"))


def roles(texts, shapes=(), sparse=False):
    items = [{**t, "lines": page_lint.text_lines(t)} for t in texts]
    page_lint.classify_roles(items, list(shapes), 1280, 720, sparse=sparse)
    return [(t["text"][:24], t["role"]) for t in items]


# --- role classification --------------------------------------------------------------------------------------------------

def test_roles_come_from_the_markup_first_then_the_geometry():
    found = dict(roles([
        footer(),
        text("EYEBROW", 72, 30, size=12, width=90, groups=["page-title"]),
        text("The title of the page states a claim", 72, 60, size=32, width=800, groups=["page-title"]),
        text("Source: City RFP pp. 4-8", 72, 660, size=11, width=300),
        text("Cell text", 600, 300, size=12, width=80, ctx=["rw:table"], groups=["fees-table"]),
        text("A paragraph of running text that spans a wide column\nand wraps to a second line", 72, 200, size=16, width=700, lines=2),
        text("Node label", 510, 410, size=12, width=80),
        text("Declared", 900, 400, size=16, width=60, ctx=["tr:footnote"]),
        text("■ a list item that carries a real sentence of body copy", 72, 480, size=16, width=280),
        text("$ project_manager.py validate", 72, 560, size=15, width=260, family="Consolas, monospace"),
    ], shapes=[shape(500, 400, 620, 440)]))
    assert found["Deck line"] == "furniture"
    assert found["EYEBROW"] == "furniture"  # the small line above the title in the title group
    assert found["The title of the page st"] == "title"
    assert found["Source: City RFP pp. 4-8"] == "footnote"
    assert found["Cell text"] == "secondary"
    assert found["A paragraph of running t"] == "body"
    assert found["Node label"] == "secondary"  # inside a small shape: a diagram label
    assert found["Declared"] == "footnote"  # data-type-role wins
    assert found["■ a list item that carri"] == "body"
    assert found["$ project_manager.py val"] == "secondary"


def test_a_source_rail_in_a_diagram_is_not_a_source_line_and_callout_ids_are_secondary():
    found = dict(roles([text("Approved aggregate only", 300, 300, size=12, width=150, groups=["source-rail"]),
                        text("KEY TERM · a gloss in the margin that runs on\nfor two lines", 900, 200, size=15, width=350, lines=2, groups=["gloss-1-slot"])]))
    assert found["Approved aggregate only"] == "secondary"
    assert found["KEY TERM · a gloss in th"] == "secondary"


def test_a_cover_meta_line_is_furniture_on_a_sparse_page_only():
    meta = text("Version 1 · 28 Sep 2026 · base f0677c61", 72, 600, size=12, width=500)
    assert dict(roles([meta], sparse=True))["Version 1 · 28 Sep 2026 "] == "furniture"
    assert dict(roles([meta], sparse=False))["Version 1 · 28 Sep 2026 "] == "secondary"


# --- MIN_TYPE and title checks ----------------------------------------------------------------------------------------------

def test_min_type_is_certain_grouped_and_names_role_and_size():
    cells = [text(f"cell {i}", 600 + 90 * (i % 3), 300 + 30 * (i // 3), size=11, width=70, ctx=["rw:table"], groups=["reviewer-table"]) for i in range(9)]
    found = run([title(), footer(), *cells])
    assert kinds(found) == [("MIN_TYPE", "secondary", 11.0)]
    item = next(f for f in found if f["kind"] == "MIN_TYPE")
    assert item["hard"] and item["count"] == 9 and "reviewer-table" in item["message"] and "never shrink below the floor" in item["message"].lower()


def test_text_at_its_floor_is_clean_and_each_role_has_its_own_floor():
    clean = [title(), footer(), text("cell", 600, 300, size=14, width=60, ctx=["rw:table"]),
             text("Source: a line at the floor", 72, 660, size=11, width=300),
             text("A paragraph of running text across the page\nsecond line", 72, 200, size=16, width=700, lines=2)]
    assert kinds(run(clean)) == []
    small = [title(), text("A paragraph of running text across the page\nsecond line", 72, 200, size=15, width=700, lines=2),
             text("Deck line", 72, 686, size=10, width=300, ctx=["role:chrome"])]
    # chrome copied from the template is the template's to fix: a note, never a page blocker
    assert kinds(run(small)) == [("MIN_TYPE", "body", 15.0), ("TEMPLATE_TYPE", "furniture", 10.0)]


def test_a_scaled_group_is_measured_at_its_effective_size():
    shrunk = text("Label drawn at 16 in a group scaled to 0.75", 600, 300, size=16, width=300, scale=0.75, ctx=["rw:chart"])
    assert kinds(run([title(), footer(), shrunk])) == [("MIN_TYPE", "secondary", 12.0)]


def test_a_lone_marker_or_superscript_does_not_set_the_size():
    item = text("■ list item with enough words to be running body text", 72, 300, size=16, width=500)
    item["parts"].insert(0, {"rect": [60, 300, 68, 316], "text": "■", "fill": "rgb(180,20,40)", "size": 9})
    assert kinds(run([title(), footer(), item])) == []


def test_the_locks_type_floor_block_moves_the_floors():
    lock = "## canvas\n- viewBox: 0 0 1280 720\n\n## type_floor\n- body: 14\n- secondary: 12\n- footnote: 10\n"
    floors = type_floor.floors(lock)
    assert floors == {"body": 14.0, "secondary": 12.0, "footnote": 10.0, "furniture": 10.0}
    assert type_floor.floors("## typography\n- body: 18\n") == {"body": 16.0, "secondary": 14.0, "footnote": 11.0, "furniture": 11.0}
    page = {**PAGE, "floors": floors}
    assert kinds(run([title(), footer(), text("cell", 600, 300, size=12, width=60, ctx=["rw:table"])], page=page)) == []


def test_titles_shrunk_long_or_widowed_are_flagged_not_certain():
    shrunk = run([text("A title set smaller than its layout allows", 72, 60, size=28, width=800, ctx=["ph:title"]), footer()])
    assert [(f["kind"], f["hard"]) for f in shrunk if f["kind"].startswith("TITLE")] == [("TITLE_SHRUNK", False)]
    widow = text("The fork renders, measures and reviews\nevery", 72, 60, size=32, width=800, lines=2, ctx=["ph:title"])
    three = text("One\nTwo lines\nThree lines", 72, 60, size=32, width=800, lines=3, ctx=["ph:title"])
    assert "TITLE_WIDOW" in [f["kind"] for f in run([widow, footer()])]
    assert "TITLE_LINES" in [f["kind"] for f in run([three, footer()])]


def test_without_page_context_the_geometry_rules_are_unchanged():
    geometry = {"canvas": [1280, 720], "texts": [text("tiny", 100, 100, size=8, width=30)], "shapes": [], "lines": []}
    assert page_lint.analyse(geometry) == []


# --- DEAD_BAND / UNDERFILLED / HUDDLED ----------------------------------------------------------------------------------------

def _block(y, rows=3, size=16):
    return [text(f"Row of running content number {i} across the page", 72, y + i * 26, size=size, width=1100) for i in range(rows)]


def test_a_band_across_the_body_with_nothing_in_it_is_flagged():
    found = run([title(), footer(), *_block(140), *_block(520)])
    band = [f for f in found if f["kind"] == "DEAD_BAND"]
    assert len(band) == 1 and not band[0]["hard"] and band[0]["severity"] == "blocker"
    assert 200 < band[0]["rect"][1] < band[0]["rect"][3] <= 530


def test_content_that_stops_early_is_underfilled_and_a_dense_page_is_not():
    early = run([title(), footer(), *_block(140, rows=4)])
    assert [f["kind"] for f in early if f["kind"] in page_lint.FILL_KINDS] == ["UNDERFILLED"]
    dense = run([title(), footer(), *_block(140, rows=20)])
    assert [f for f in dense if f["kind"] in page_lint.FILL_KINDS] == []


def test_a_sparse_page_is_never_judged_for_fill():
    assert [f for f in run([title(), footer(), *_block(140, rows=2)], page={**PAGE, "sparse": True}) if f["kind"] in page_lint.FILL_KINDS] == []


def test_a_figure_squeezed_into_a_strip_is_huddled():
    boxes = [shape(100 + 200 * i, 300, 260 + 200 * i, 360, order=10 + i) for i in range(5)]
    arrows = [line(260 + 200 * i, 330, 300 + 200 * i, 330, order=20 + i) for i in range(4)]
    labels = [text(f"Step {i}", 110 + 200 * i, 320, size=14, width=60) for i in range(5)]
    found = run([title(), footer(), *_block(140, rows=1), *labels], shapes=boxes, lines=arrows)
    assert "HUDDLED" in [f["kind"] for f in found]


def test_chrome_lines_and_full_height_dividers_do_not_fill_the_body():
    divider = line(640, 120, 640, 670)
    master = {**shape(0, 100, 1280, 680, fill="rgb(250,250,250)"), "ctx": ["layer:master"]}
    found = run([title(), footer(), *_block(140), *_block(520)], shapes=[master], lines=[divider])
    assert "DEAD_BAND" in [f["kind"] for f in found]


# --- the plan's capacity contract ---------------------------------------------------------------------------------------------

def _runner():
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "hosts" / "responses_api"))
    import deck_runner
    return deck_runner


LOCK = ("## canvas\n- viewBox: 0 0 1280 720\n\n## typography\n- font_family: Arial\n- title_family: Arial\n- body_family: Arial\n- body: 18\n- title: 32\n\n"
        "## page_rhythm\n- P01: anchor\n- P02: dense\n")


def _record(content: str, title_text: str = "Plans that fit the page keep type legible", number: int = 2, role: str = "evidence") -> str:
    """A complete record, so that plan_lint's other checks stay quiet and only the capacity contract speaks."""
    fields = {"Role": role, "Author tier": "workhorse", "Layout": "content", "Audience question": "Does it fit?", "Audience move": "unsure to sure",
              "Story link": "follows the brief", "Relationships": "none", "Title": title_text, "Core message": "It fits", "Content": "\n" + content,
              "Sources": "sources/x.md", "Visual task": "read the claim", "Visual approach": "prose", "Composition": "one column", "Hierarchy": "claim first",
              "Avoid": "clutter", "Editor notes": "none"}
    return f"#### Slide {number:02d} - Example\n\n" + "\n".join(f"- **{k}**: {v}" for k, v in fields.items()) + "\n"


def test_planned_copy_reads_keyed_prose_rows_and_sources():
    runner = _runner()
    copy = runner.planned_copy(_record(
        "  - Running head: `§01 · Skip me`\n  - Key message: `One governing claim in eight plain words here.`\n"
        "  - Headers: `Limit` · `Where` · `Fix`\n  - Row 1: `Small type` · `Several decks` · `A floor check`\n"
        "  - Row 2: `Wrong folio` · `Four decks` · `Folio check`\n  - Source: `Run log, 23 Sep 2026.`"))
    assert copy["body"] == 8 and copy["footnote"] == 5
    assert copy["table"]["header"] == ["Limit", "Where", "Fix"] and copy["table"]["rows"][1] == ["Wrong folio", "Four decks", "Folio check"]
    kirkland = runner.planned_copy(_record("    row 1 label: `START`\n    row 1 proof: `The proof sentence.`\n    row 2 label: `CLOSE`\n    row 2 proof: `Another.`"))
    assert kirkland["table"]["rows"] == [["START", "The proof sentence."], ["CLOSE", "Another."]]


def test_a_record_over_capacity_at_the_floors_is_refused_and_a_spare_one_is_not():
    runner = _runner()
    heavy = _record("  - Body: `" + " ".join(["evidence"] * 700) + "`")
    spare = _record("  - Body: `" + " ".join(["evidence"] * 60) + "`")
    report: list = []
    found = runner.plan_lint("# spec\n\n" + heavy, lock=LOCK, report=report)
    issues = " | ".join(found["Slide 02 - Example"])
    assert "OVER_CAPACITY: slide 02 plans ~700 words" in issues and "the body holds ~" in issues
    assert report and report[0]["ratio"] > 1.1
    assert runner.plan_lint("# spec\n\n" + spare, lock=LOCK) == {}
    assert runner.plan_lint("# spec\n\n" + heavy) .get("Slide 02 - Example") is None  # without the lock the contract is not applied


def test_a_wide_table_is_counted_at_its_wrapped_height():
    runner = _runner()
    rows = "\n".join(f"  - Row {i}: `" + "` · `".join([" ".join(["cell"] * 14)] * 6) + "`" for i in range(1, 13))
    found = runner.plan_lint("# spec\n\n" + _record(rows), lock=LOCK)
    assert any("OVER_CAPACITY" in i and "table" in i for i in found["Slide 02 - Example"])


def test_title_fit_counts_lines_at_the_locked_size_and_words():
    runner = _runner()
    long_title = "Kirkland already has an ITS, cloud estate and public Wi-Fi; the missing asset is a City-wide way to choose and fund what comes next"
    issues = " | ".join(runner.plan_lint("# spec\n\n" + _record("  - Body: `short`", title_text=long_title), lock=LOCK)["Slide 02 - Example"])
    assert "TITLE_FIT: the title has 24 words" in issues
    narrow = LOCK.replace("- title: 32", "- title: 72")
    issues = " | ".join(runner.plan_lint("# spec\n\n" + _record("  - Body: `short`", title_text="A separate reviewer sees every defect that the page author missed in review"), lock=narrow)["Slide 02 - Example"])
    assert "TITLE_FIT: the title needs 3 lines at the locked 72 px" in issues
    assert runner.plan_lint("# spec\n\n" + _record("  - Body: `short`"), lock=LOCK) == {}


def test_a_cover_is_not_held_to_body_capacity():
    runner = _runner()
    cover = _record("  - Body: `" + " ".join(["word"] * 900) + "`", number=1, role="cover")
    assert runner.plan_lint("# spec\n\n" + cover, lock=LOCK) == {}


def test_layout_geometry_reads_placeholders_and_the_body_zone(tmp_path):
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "evidence.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
        '<g id="title-slot" data-pptx-placeholder="title" data-pptx-bounds="72 56 440 200"><text x="72" y="88" font-family="Georgia" font-size="34" font-weight="bold">T</text></g>'
        '<g id="running-head-slot" data-pptx-placeholder="body" data-pptx-bounds="72 20 440 22"><text>h</text></g>'
        '<g id="points-slot" data-pptx-placeholder="body" data-pptx-bounds="72 280 440 280"><text>p</text></g>'
        '<g id="exhibit-slot" data-pptx-placeholder="object" data-pptx-bounds="568 56 640 540"><text>e</text></g></svg>', encoding="utf-8")
    box = type_floor.title_box(tmp_path, LOCK, "evidence")
    assert (box["width"], box["size"], box["weight"]) == (440.0, 34.0, "bold")
    area = type_floor.body_area(tmp_path, LOCK, "evidence")
    assert area["area"] == 440 * 280 + 640 * 540 and area["width"] == 640  # the running head is not content
    context = type_floor.page_context(tmp_path, "P01")
    assert context["floors"]["body"] == 16.0


def test_page_context_marks_covers_and_breathing_pages_sparse(tmp_path):
    (tmp_path / "spec_lock.md").write_text(LOCK + "- P03: breathing\n", encoding="utf-8")
    (tmp_path / "design_spec.md").write_text("## IX\n#### Slide 04 - Close\n- **Role**: closing\n", encoding="utf-8")
    assert type_floor.page_context(tmp_path, "01_cover")["sparse"]
    assert type_floor.page_context(tmp_path, "P03")["sparse"]
    assert type_floor.page_context(tmp_path, "04_close")["sparse"]
    assert not type_floor.page_context(tmp_path, "P02")["sparse"]


def test_real_font_metrics_wrap_a_title():
    import text_measure
    lines = text_measure.wrap_real("A separate reviewer sees what the author missed", size=32, max_width=300, family="NoSuchFont, Arial")
    assert len(lines) >= 2 and " ".join(lines) == "A separate reviewer sees what the author missed"
    assert text_measure.measure_real("abc", size=20, family="NoSuchFontAtAll") > 0  # falls back to the estimator


# --- the browser measurement feeds effective sizes and roles ------------------------------------------------------------------

def test_the_browser_reports_effective_size_under_a_scaled_group(tmp_path):
    pytest.importorskip("playwright")
    svg = tmp_path / "svg_output" / "P02.svg"
    svg.parent.mkdir()
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720">'
                   '<g id="chrome" data-pptx-role="chrome"><text x="72" y="700" font-size="11">Deck line</text></g>'
                   '<text id="title" x="72" y="90" font-size="32">A claim the page proves</text>'
                   '<g transform="translate(600 300) scale(0.75)" data-pptx-replace-with="chart"><text x="0" y="0" font-size="16">Scaled chart label</text></g>'
                   '</svg>', encoding="utf-8")
    try:
        result = page_lint.lint_page(tmp_path, "P02", contract=False, write_overlay=False)
    except Exception as exc:  # noqa: BLE001 - no browser installed here
        pytest.skip(f"browser unavailable: {exc}")
    certain = [f for f in result["blockers"] if f["kind"] == "MIN_TYPE"]
    assert [(f["role"], f["px"]) for f in certain] == [("secondary", 12.0)]


def test_template_owned_chrome_text_is_a_note_not_a_blocker():
    import page_lint
    base = {"rect": [1000, 690, 1170, 703], "lines": [{"rect": [1000, 690, 1170, 703], "size": 10}], "size": 10, "text": "Firm · Client",
            "groups": ["chrome"], "role": "furniture", "role_why": "chrome, running header or footer", "px": 10.0}
    owned = dict(base, template_owned=True)
    authored = dict(base, template_owned=False, groups=["footer"])
    kinds = [f["kind"] for f in page_lint.type_findings([owned], {}, 1280, 720)]
    assert kinds == ["TEMPLATE_TYPE"]
    finding = page_lint.type_findings([authored], {}, 1280, 720)[0]
    assert finding["kind"] == "MIN_TYPE" and finding["hard"]
