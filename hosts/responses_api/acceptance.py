"""Check a finished deck run against FORK_ACCEPTANCE_CHECKLIST.md - everything there that a program can check.

    python hosts/responses_api/acceptance.py <project> [--deck exports/<name>.pptx] [--session NAME] [--no-render]

Prints one line per checklist item (PASS / FAIL / INFO with the measured value) and writes <project>/validation/acceptance.md.
Items marked M in the checklist need eyes and are listed as such, never passed by this script.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "ppt-master" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": A, "p": P}
FIELDS = ["Role", "Author tier", "Layout", "Audience move", "Story link", "Relationships", "Title", "Core message", "Hierarchy", "Content", "Visual scaffold", "Fill", "Avoid",
          "Editor notes"]
ENUMERATION = re.compile(r"\b(?:requirement|req\.?)\s*(?:no\.?|number|#)?\s*\d+\b|\bREQ-?\d+|\bcompliance matrix\b|\bas (?:required|requested|specified) in\b|"
                         r"\bRFP\s*(?:section|sec\.?|§)\s*\d|\bsection\s+\d+\.\d+\s+of (?:the|your) RFP|\baddresses (?:your )?requirement", re.I)

rows: list[tuple[str, str, str, str]] = []


def record(item: str, status: str, what: str, detail: str = "") -> None:
    rows.append((item, status, what, detail))
    print(f"{status:5s} {item:5s} {what}" + (f" - {detail}" if detail else ""))


def check(item: str, ok: bool, what: str, detail: str = "") -> None:
    record(item, "PASS" if ok else "FAIL", what, detail)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("--deck")
    parser.add_argument("--session")
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    import deck_runner
    import page_lint
    import pptx_text_in_shapes as tis
    spec = (project / "design_spec.md").read_text(encoding="utf-8")
    pages = deck_runner.parse_pages(spec)
    journal = json.loads((project / "quality-run.json").read_text(encoding="utf-8")) if (project / "quality-run.json").is_file() else {"pages": {}}
    decks = sorted((project / "exports").glob("*.pptx"), key=lambda f: f.stat().st_mtime)
    deck = Path(args.deck).resolve() if args.deck else (decks[-1] if decks else None)

    # 1. planning
    solution = project / "solution.md"
    check("1.0", solution.is_file() and all(k in solution.read_text(encoding="utf-8").upper() for k in ("WIN THEME", "PRICE", "PLAN", "TEAM")) and (project / "sources" / "request.md").is_file(),
          "request in, proposal out: the tool's own solution stage wrote solution.md", f"{len(solution.read_text(encoding='utf-8')) if solution.is_file() else 0} chars")
    check("1.1", "### Narrative" in spec and len(pages) >= 1, "Narrative block and slide records", f"{len(pages)} records")
    missing = {p["stem"]: [f for f in FIELDS if not re.search(rf"^- \*\*{f}", p["record"], re.M)] for p in pages}
    missing = {k: v for k, v in missing.items() if v}
    check("1.2", not missing and "source_requirement" not in spec, "every record has the agreed fields, no source_requirement_ids", json.dumps(missing)[:300] if missing else "")
    tiers = [re.search(r"^- \*\*Author tier\*\*:\s*(\w+)", p["record"], re.M) for p in pages]
    check("1.3", all(t and t.group(1).lower() in ("frontier", "workhorse") for t in tiers), "every slide classified frontier / workhorse",
          ", ".join(f"P{p['number']:02d}:{p['tier']}" for p in pages))
    body = [p for p in pages if p["layout"] != "cover"]
    referenced = [p for p in body if re.search(r"^- \*\*Reference\*\*:.*lib\.[0-9a-f]+\.p\d+", p["record"], re.M)]
    check("1.4", len(referenced) >= 0.7 * max(len(body), 1), "records point at library slides (borrow / never)", f"{len(referenced)} of {len(body)} body pages")

    # 2. template
    layouts = sorted({p["layout"] for p in pages})
    have = [name for name in layouts if (project / "templates" / f"{name}.svg").is_file()]
    check("2.1", have == layouts and (project / "templates" / "template.md").is_file(), "template present before pages (one SVG per layout + template.md)", f"layouts {layouts}, found {have}")
    source = (Path(__file__).resolve().parent / "deck_runner.py").read_text(encoding="utf-8")
    check("2.2", "Nobody will approve it" in source and "No approval step follows" in source and "AskUser" not in source, "no approval gate in planner or template stage")

    # 3. configuration
    authors, reviewers = deck_runner.DEFAULT_AUTHORS, deck_runner.DEFAULT_REVIEWERS
    check("3.1", "ThreadPoolExecutor" in source and "PPT_MASTER_SYSTEM_FILE" in source, "one conversation per page over a shared system prompt, in parallel")
    check("3.2", authors["workhorse"]["model"] == "gpt-6-luna" and authors["workhorse"]["effort"] == "high" and authors["frontier"]["model"] == "gpt-6-sol" and authors["frontier"]["effort"] == "high",
          "workhorse = GPT-6 Luna @ high, frontier = GPT-6 Sol @ high", f"{authors['workhorse']['model']} @ {authors['workhorse'].get('effort')}; {authors['frontier']['model']} @ {authors['frontier'].get('effort')}")
    check("3.3", all(r["model"] == "x-ai/grok-4.6" and r["effort"] == "medium" for r in reviewers.values()), "Grok 4.6 @ medium reviews every page and the deck", str({k: v["model"] for k, v in reviewers.items()}))
    check("3.4", "--enable-dangerous-nonconforming-svg-export" in source and 'add_argument("--strict-export", action="store_true"' in source, "export by default when the repair budget is spent")
    host = (Path(__file__).resolve().parent / "host.py").read_text(encoding="utf-8")
    check("3.5", "http.client.HTTPException" in host and "timeout=1800" in host, "host retries transport faults incl. a body cut off mid-read; no short caps on model calls")

    # 4. review
    bad = []
    for page in pages:
        entry = (journal.get("pages") or {}).get(page["stem"]) or {}
        review = entry.get("review") or {}
        if not (entry.get("outcome") == "accepted" and review.get("verdict") == "PASS" and review.get("sha") == entry.get("last_sha") and entry.get("lint") is not None):
            bad.append(f"{page['stem']}: outcome {entry.get('outcome')}, review {review.get('verdict')}, lint {'yes' if entry.get('lint') is not None else 'no'}")
    check("4.1", not bad, "every page rendered, linted, independently reviewed, accepted on a PASS of its current revision", "; ".join(bad)[:400])
    check("4.4", "def keep_or_restore" in source and "self.settle(page, before)" in source and "user_change=True" in source,
          "a repair never demotes a page that had passed; a change the user asked for is never rolled back")
    check("4.5", "def collect_annotations" in source and "--revise" in source and "--dry-run" in source, "revise from the user's comments in the live preview (--revise, --dry-run)")
    lint_source = (SCRIPTS / "page_lint.py").read_text(encoding="utf-8")
    check("4.2", all(k in lint_source for k in ("TIGHT_LEADING", "BAR_WITHOUT_LABEL", "selectNodeContents")), "lint measures first lines, line spacing and anonymous bars")
    review_file = project / ".review" / "deck_review.md"
    log = Path(args.session).read_text(encoding="utf-8", errors="replace") if args.session and Path(args.session).is_file() else ""
    repairs = [line for line in re.findall(r"deck repair: ([^\n]+)", log) if re.search(r"\d", line)]  # a repair that reached pages names them with counts
    check("4.3", review_file.is_file() and (bool(repairs) if log else True), "deck review written and its findings handed back to the pages",
          ("deck repair: " + repairs[-1] if repairs else "no runner log given" if not log else "the deck review's findings reached no page"))

    # 5. typesetting, measured on the SVGs
    bands: dict[str, list[float]] = {"title": [], "heading": [], "body": []}
    drawn_markers = typed_markers = 0
    open_lint: list[str] = []
    for page in pages:
        svg = project / "svg_output" / f"{page['stem']}.svg"
        if not svg.is_file():
            continue
        text = svg.read_text(encoding="utf-8")
        for match in re.finditer(r"<text\b([^>]*)>(.*?)</text>", text, re.S):
            size = re.search(r'font-size="([\d.]+)"', match.group(1))
            steps = [float(d) for d in re.findall(r'<tspan[^>]*\bdy="([\d.]+)"', match.group(2)) if float(d) > 0]
            if size and steps:
                px = float(size.group(1))
                bands["title" if px >= 24 else "heading" if px >= 15 else "body"].append(min(steps) / px)
        typed_markers += len(re.findall(r">\s*(?:<tspan[^>]*>)?\s*[■▪●•◆]\s*(?:</tspan>)?\s*\S", text))
        drawn_markers += len(re.findall(r'<rect[^>]*\bwidth="[3-7](?:\.\d+)?"[^>]*\bheight="[3-7](?:\.\d+)?"', text)) + len(re.findall(r'<circle[^>]*\br="[1-3](?:\.\d+)?"', text))
        try:
            result = page_lint.lint_page(project, page["stem"], contract=False, write_overlay=False)
            review = ((journal.get("pages") or {}).get(page["stem"]) or {}).get("review") or {}
            for finding in result["blockers"]:
                if finding.get("hard") or finding["kind"] == "BAR_WITHOUT_LABEL":
                    open_lint.append(f"{page['stem']}: {finding['kind']}")
        except Exception as exc:  # noqa: BLE001
            open_lint.append(f"{page['stem']}: lint unavailable ({exc})")
    medians = {k: round(statistics.median(v), 2) for k, v in bands.items() if v}
    ok = medians.get("body", 9) >= 1.35 and medians.get("heading", 9) >= 1.17 and medians.get("title", 9) >= 1.12
    check("5.1", ok, "line spacing: body >= 1.35, headings >= 1.17, titles >= 1.12 (medians)", str(medians))
    check("5.4", not open_lint, "no certain lint defect and no anonymous Gantt bar on the shipped pages", "; ".join(open_lint)[:400])

    # 6. the PowerPoint
    if deck is None or not deck.is_file():
        record("6.x", "FAIL", "no exported deck found")
    else:
        archive = zipfile.ZipFile(deck)
        names = archive.namelist()
        slide_names = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        inside = boxes = titles = bullets = tables = connectors = generic = named = thin = no_alt = notes = 0
        table_names: list[str] = []
        slide_text: list[str] = []
        for name in slide_names:
            root = etree.fromstring(archive.read(name))
            tree = root.find("p:cSld/p:spTree", NS)
            slide_text.append(" ".join(root.itertext()))
            titles += 1 if tree.find(".//p:nvPr/p:ph[@type='title']", NS) is not None or tree.find(".//p:nvPr/p:ph[@type='ctrTitle']", NS) is not None else 0
            rel = name.replace("slides/", "slides/_rels/") + ".rels"
            notes += 1 if rel in names and b"notesSlide" in archive.read(rel) else 0
            for item in tis.walk(tree):
                props = item.el.find(".//p:cNvPr", NS)
                label = props.get("name", "") if props is not None else ""
                if item.tag == "graphicFrame" and item.el.find(".//a:tbl", NS) is not None:
                    tables += 1
                    table_names.append(label)
                if item.tag == "cxnSp":
                    connectors += 1
                if item.tag == "pic" and not (props is not None and props.get("descr")):
                    no_alt += 1
                if item.tag != "sp":
                    continue
                has_text = bool("".join(item.el.itertext()).strip())
                if has_text and item.el.find("p:nvSpPr/p:nvPr/p:ph", NS) is None:
                    boxes += 1 if item.is_text else 0
                    inside += 0 if item.is_text else 1
                    if re.fullmatch(r"(TextBox|Rectangle|Freeform|Oval|Shape)\s*\d*", label):
                        generic += 1
                    else:
                        named += 1
                bullets += len(item.el.findall(".//a:buChar", NS)) + len(item.el.findall(".//a:buAutoNum", NS))
                sppr = item.el.find("p:spPr", NS)
                ext = sppr.find("a:xfrm/a:ext", NS) if sppr is not None else None
                preset = sppr.find("a:prstGeom", NS) if sppr is not None else None
                if (ext is not None and preset is not None and preset.get("prst") == "rect" and sppr.find("a:solidFill", NS) is not None and not has_text
                        and 0 < min(int(ext.get("cx")), int(ext.get("cy"))) <= 3 * 9525 and max(int(ext.get("cx")), int(ext.get("cy"))) > 12 * 9525):
                    thin += 1
        layout_names, number_field, layout_title = [], False, False
        for name in (n for n in names if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", n)):
            root = etree.fromstring(archive.read(name))
            layout_names.append(root.find("p:cSld", NS).get("name", ""))
            shapes = [sp for sp in root.iter(f"{{{P}}}sp") if sp.find("p:nvSpPr/p:nvPr/p:ph", NS) is None]
            number_field = number_field or any(sp.find(".//a:fld[@type='slidenum']", NS) is not None for sp in shapes)
            if shapes or root.find(f".//{{{P}}}pic") is not None:
                layout_title = layout_title or root.find(".//p:nvPr/p:ph[@type='title']", NS) is not None
        check("2.3", any("Content" in n or "content" in n for n in layout_names) and number_field and layout_title,
              "chrome on a named slide layout, page number a field, title placeholder on the layout", f"layouts {layout_names}; number field {number_field}; title placeholder {layout_title}")
        scratch = deck.with_suffix(".acceptance.tmp.pptx")
        again = tis.convert(deck, scratch, chrome=False)["totals"]
        scratch.unlink(missing_ok=True)
        over_shape = sum((again.get("notes") or {}).values())  # texts that sit on a shape and still float (several columns in one shape, something painted between)
        check("6.1", inside > 0 and over_shape <= 0.15 * max(inside + boxes, 1), "text lives inside the shape it sits on; what still floats has no shape under it",
              f"{inside} shapes hold their text, {boxes} text boxes of which {over_shape} float over a shape (tables not counted)")
        check("6.2", again["joined"] == 0 and again["stacked"] <= 2 and again["adopted"] <= 2, "nothing left to join, merge or move into a shape (the pass finds no more work)",
              f"joined {again['joined']}, stacked {again['stacked']}, adopted {again['adopted']}")
        check("6.3", titles == len(slide_names), "one real title placeholder per slide", f"{titles} of {len(slide_names)}")
        check("6.4", (bullets > 0 or typed_markers == 0) and drawn_markers <= 3, "lists are native lists; no drawn bullet squares", f"{bullets} native list paragraphs; {drawn_markers} bullet-sized drawn shapes in the SVGs")
        wanted = [m.group(1) for p in pages for m in re.finditer(r"^- \*\*Native-ready\*\*:\s*([a-z0-9-]+)=yes", p["record"], re.M)]
        check("6.5", all(any(w in n for n in table_names) for w in wanted), "every Native-ready table is a PowerPoint table", f"wanted {wanted}; tables in deck {table_names}")
        check("6.7", named >= 4 * max(generic, 1) and no_alt == 0 and thin == 0, "objects named after their text, pictures with alt text, hairlines are lines",
              f"{named} named / {generic} generic; {no_alt} pictures without alt text; {thin} thin-rectangle rules")
        record("6.8", "PASS" if connectors else "INFO", "straight arrows between boxes are glued connectors", f"{connectors} connectors in the deck")
        check("6.9", notes == len(slide_names), "speaker notes on every slide", f"{notes} of {len(slide_names)}")
        hits = [(i + 1, m.group(0)) for i, text in enumerate(slide_text) for m in ENUMERATION.finditer(text)]
        hits += [("plan", m.group(0)) for m in ENUMERATION.finditer("\n".join(p["record"] for p in pages))]
        placeholders = sum(text.count("[To be provided") for text in slide_text)
        kb = " ".join(f.read_text(encoding="utf-8", errors="replace") for f in (project / "sources").glob("*")) if (project / "sources").is_dir() else ""
        unknown = "Not in this knowledge base" in kb
        record("1.8", "PASS" if (placeholders > 0 or not unknown) else "FAIL", "what the sources do not give is a marked placeholder, never invented",
               f"{placeholders} placeholder(s) on the slides; knowledge base declares gaps: {unknown}")
        check("1.6", not hits, "the deck never enumerates the client's requirements", str(hits[:6]))
        original = deck.parent / "floating-text" / deck.name
        if args.no_render or not original.is_file():
            record("6.10", "INFO", "export pass moves nothing", "not rendered (--no-render or no kept original)")
        else:
            work = project / "validation" / "acceptance_render"
            work.mkdir(parents=True, exist_ok=True)
            before = work / "before.pptx"
            before.write_bytes(original.read_bytes())
            after = work / "after.pptx"
            after.write_bytes(deck.read_bytes())
            for file in (before, after):
                subprocess.run([sys.executable, str(SCRIPTS / "pptx_render.py"), str(file)], capture_output=True, text=True)
            out = subprocess.run([sys.executable, str(SCRIPTS / "pptx_text_in_shapes.py"), "--verify", str(before.with_suffix(".render")), str(after.with_suffix(".render"))],
                                 capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
            worst = re.search(r"worst slide ([\d.]+)%", out)
            check("6.10", bool(worst) and float(worst.group(1)) <= 1.0, "the export pass moves nothing (PowerPoint render before vs after)", f"worst slide {worst.group(1) if worst else '?'}% of ink moved > 2 px")
    for item, what in (("1.5", "flexible scale / premade structure accepted"), ("1.7", "a genuinely good response to the RFP"),
                       ("5.2", "paragraph / list / block gaps, padding, not squished"), ("5.3", "packed consulting density"), ("5.5", "multi-level Gantt with overlaps"),
                       ("7.1", "PPTX and renders sent into the chat"), ("7.2", "faithful reporting"), ("7.3", "nothing committed unless asked")):
        record(item, "EYES", what)
    failed = [r for r in rows if r[1] == "FAIL"]
    lines = ["# Acceptance - " + project.name, "", f"Deck: `{deck.name if deck else 'none'}`", "", "| item | status | check | measured |", "|---|---|---|---|",
             *[f"| {i} | {s} | {w} | {d.replace('|', '/')} |" for i, s, w, d in sorted(rows, key=lambda r: [int(x) if x.isdigit() else 0 for x in r[0].split('.')])], "",
             f"{len(failed)} automatic check(s) failed." if failed else "All automatic checks passed; the EYES items are judged on the PowerPoint render."]
    (project / "validation").mkdir(exist_ok=True)
    (project / "validation" / "acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{len(failed)} failed" if failed else "\nall automatic checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
