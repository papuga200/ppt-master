"""Deterministic storyline, grounding and exhibit checks on a planner's design_spec.md (failure families F07 and F08).

The planner writes three deck-level lists in section IX before its slide records - a Storyline (the titles alone, in order),
a Fact register (every figure the deck states, with unit, scope and source) and Canonical terms (one name and one plain
definition per named thing) - and every slide record carries an `Exhibit` line. These checks read those lists and the
records; they never judge taste, only what can be measured: a title that is a topic label or too long, a figure in visible
copy that the register does not hold, a storyline that disagrees with the records, an exhibit outside the vocabulary, runs
of the same exhibit, a deck whose body is mostly tables, and a deck without an opening answer or a closing ask.
"""
from __future__ import annotations

import re

EXHIBITS = {
    # quantitative comparisons (Zelazny's five plus a figure band)
    "bar-comparison": "items compared on one measure (ranking, before/after, option A vs B)",
    "time-series": "a measure over time (column or line)",
    "part-to-whole": "shares of a total (stacked bar, 100% bar, waterfall)",
    "distribution": "how many items fall in each range",
    "correlation": "whether two measures move together (scatter, paired bars)",
    "key-figures": "three to five headline numbers with their meaning",
    # structure and relationships
    "process-flow": "an ordered sequence of steps, with decisions and outputs",
    "loop": "a cycle with its entry, return path and exit",
    "architecture": "a system with its boundary, components and the connections that matter",
    "hub-and-spoke": "one centre and the parts it connects",
    "hierarchy": "a tree, organisation or decomposition",
    "matrix": "items placed against two criteria (2x2 or criteria grid)",
    "timeline": "a plan or chronology on a time scale (Gantt, roadmap, milestones)",
    # reference and evidence
    "table": "a look-up of several attributes per item where exact values matter",
    "comparison-table": "options compared on the same criteria, with a recommendation",
    "annotated-example": "a real artefact (screenshot, page, document) with callouts",
    "text-argument": "a short structured argument: claim, reasons, evidence in parallel bullets",
    "team": "people or roles with responsibilities",
    # deck furniture
    "cover": "title page",
    "section-divider": "section opener",
    "summary": "executive summary: situation, answer, what is asked",
    "closing": "decision, next steps or contact",
}
FURNITURE = {"cover", "section-divider", "closing"}
TABULAR = {"table", "comparison-table"}
TITLE_MAX_WORDS = 15
# internal codes: UPPER_SNAKE or snake_case identifiers (verdict codes, field names) that a reader cannot decode
CODE = re.compile(r"\b(?:[A-Z][A-Z0-9]+_[A-Z0-9_]+|[a-z]+_[a-z0-9_]+)\b")
# a page that maps the client's requirements back to them (the user's standing rule: needs are answered through the story)
ECHO = re.compile(r"(?i)\b(?:(?:RFP|request|brief|tender|scope)\W+(?:\w+\W+){0,6}?(?:requirements?|objectives?|scope items?|deliverables?)\b.{0,80}\b(?:owning|owned|mapped|covered|addressed|answered)\b"
                  r"|requirements?\s+(?:coverage|compliance|traceability)|compliance\s+matrix|(?:RFP|request)\s+(?:section|§)\s*\d)")
_FIELD = r"- \*\*{name}\*\*(?: \([^)]*\))?:(.*?)(?=\n- \*\*[A-Z][^*]*\*\*|\n#{{2,4}} |\Z)"
# figures a reader would check: money, percentages, durations, counts with a unit, and plain numbers of 3+ digits
FIGURE = re.compile(r"(?<![\w.])(?:[A-Z]{3}\s?|[$€£¥])?\d[\d,]*(?:\.\d+)?\s?(?:%|[kKmMbB]n?\b|x\b|h\b|min\b|hours?\b|days?\b|weeks?\b|months?\b|pt\b|px\b)?")


def _field(block: str, name: str) -> str:
    m = re.search(_FIELD.format(name=re.escape(name)), block, re.S)
    return m.group(1).strip() if m else ""


def _section(spec: str, heading: str) -> str:
    """The body of a `### <heading>` (or ####) list inside section IX, up to the next heading."""
    m = re.search(rf"(?im)^#{{2,4}}\s*{heading}\b[^\n]*\n(.*?)(?=^#{{2,4}}\s|\Z)", spec, re.S | re.M)
    return m.group(1) if m else ""


def _norm_number(token: str) -> str:
    """'HKD 7,507,000' / 'HKD 7.507m' / '7,507,000' all normalise to the same digits; '12%' keeps its unit."""
    t = token.strip()
    unit = "%" if t.endswith("%") else ""
    digits = re.sub(r"[^\d.]", "", t.replace(",", ""))
    if not digits or digits == ".":
        return ""
    try:
        value = float(digits)
    except ValueError:
        return ""
    low = t.lower()
    if re.search(r"\d\s?(?:m|mn)\b", low):
        value *= 1_000_000
    elif re.search(r"\d\s?(?:b|bn)\b", low):
        value *= 1_000_000_000
    elif re.search(r"\d\s?k\b", low):
        value *= 1_000
    return f"{value:.6g}{unit}"


def _checkable(token: str, context: str) -> bool:
    """Numbers a reader would compare or check. Skips list numbering, years, slide/page/step numbers, week codes,
    and small bare counts in running prose."""
    t = token.strip()
    bare = re.fullmatch(r"\d{1,2}", t)
    if re.fullmatch(r"(?:19|20)\d{2}", t):
        return False
    if bare:
        return False  # "3 options", "step 2": counts under 100 without a unit are too common to register
    if re.search(rf"(?i)(?:slide|page|step|phase|wave|option|gate|stage|section|week|w|p)\s*{re.escape(t)}\b", context):
        return False
    return bool(re.search(r"\d", t))


def storyline_titles(spec: str) -> list[str]:
    body = _section(spec, r"Storyline")
    titles = []
    for line in body.splitlines():
        m = re.match(r"\s*(?:\d+[.)]|[-*])\s*(?:Slide\s*\d+\s*[-–—:]\s*)?(.+)", line)
        if m and m.group(1).strip():
            titles.append(m.group(1).strip().strip("`*\""))
    return titles


def fact_register(spec: str) -> set[str]:
    body = _section(spec, r"Fact register")
    values: set[str] = set()
    for token in FIGURE.findall(body):
        n = _norm_number(token)
        if n:
            values.add(n)
    return values


def story_lint(spec: str) -> dict[str, list[str]]:
    """Findings keyed like plan_lint: `Slide NN - Name` or `Deck`."""
    found: dict[str, list[str]] = {}
    blocks = re.split(r"\n(?=#### Slide )", spec)[1:]
    records = []
    for block in blocks:
        head = block.splitlines()[0].replace("#### ", "").strip()
        records.append((head, block))

    register = fact_register(spec)
    has_register = bool(_section(spec, r"Fact register").strip())
    storyline = storyline_titles(spec)
    if not storyline:
        found.setdefault("Deck", []).append(
            "no `### Storyline` list in section IX: write the titles alone, in order, before the records; read them as the argument "
            "(opening answer, signposted middle, closing ask) and repair the ones that do not carry it")
    if not _section(spec, r"Canonical terms").strip():
        found.setdefault("Deck", []).append(
            "no `### Canonical terms` list in section IX: give every named component, step, role and programme one name and a "
            "one-line plain definition; every page uses exactly these names")

    exhibits: list[tuple[str, str]] = []
    tiers: list[tuple[str, bool, str]] = []
    record_titles: list[str] = []
    missing_figures: dict[str, list[str]] = {}
    for head, block in records:
        issues: list[str] = []
        title = _field(block, "Title")
        record_titles.append(title)
        exhibit_raw = _field(block, "Exhibit")
        exhibit = re.split(r"[\s—–:(;,]", exhibit_raw.strip().strip("`").lower(), maxsplit=1)[0] if exhibit_raw else ""
        role = _field(block, "Role").lower()
        furniture = exhibit in FURNITURE or bool(re.search(r"\b(cover|title page|section|divider|closing|contact|back cover)\b", role + " " + head.lower()))
        if not exhibit_raw:
            issues.append("missing field `Exhibit`: name one form from the exhibit vocabulary and why it fits the claim")
        elif exhibit not in EXHIBITS:
            issues.append(f"`Exhibit` `{exhibit_raw[:40]}` is not in the vocabulary ({', '.join(sorted(EXHIBITS))})")
        exhibits.append((head, "furniture" if furniture else exhibit))
        if title and not furniture:
            words = len(re.findall(r"[\w'’-]+", title))
            if words > TITLE_MAX_WORDS:
                issues.append(f"title has {words} words; an action title states the takeaway in at most {TITLE_MAX_WORDS} words")
            elif words <= 4 and not re.search(r"\b(is|are|was|were|will|can|must|should|has|have|needs?|makes?|takes?|cuts?|gives?|shows?)\b", title, re.I):
                issues.append(f"title `{title}` reads as a topic label: state what the reader should conclude from this page")
        copy = " ".join(_field(block, n) for n in ("Title", "Core message", "Content"))
        copy = re.sub(r"\[To be provided:[^\]]*\]", " ", copy)
        if ECHO.search(" ".join(_field(block, n) for n in ("Title", "Core message", "Exhibit", "Visual task"))):
            issues.append("the page maps the client's requirements back to them (a coverage or compliance view): keep that check as your "
                          "working and answer the needs through the story, design and diagrams instead")
        plain = re.sub(r"\S+\.(?:md|py|json|svg|pptx|png)\b", " ", copy)  # file names are what a user types, not codes
        codes = sorted({m.group(0) for m in CODE.finditer(plain)
                        if not re.match(r"\s*(?:/|\\|\(|=|:\s*[a-z]|\s[-–—]\s)", plain[m.end():m.end() + 4])})  # a folder, or a code explained in place
        if codes:
            issues.append("internal codes a reader cannot read in visible copy (" + ", ".join(codes[:6]) + "): say what each means in plain words "
                          "(e.g. `EXECUTION_REPAIR` -> `fix the drawing`)")
        tiers.append((head, furniture, _field(block, "Author tier").strip().lower()))
        if has_register:
            for m in FIGURE.finditer(copy):
                token = m.group(0)
                context = copy[max(0, m.start() - 12):m.end() + 2]
                if not _checkable(token, context):
                    continue
                n = _norm_number(token)
                if n and n not in register:
                    missing_figures.setdefault(head, []).append(token.strip())
        if issues:
            found.setdefault(head, []).extend(issues)

    any_figures = any(FIGURE.search(re.sub(r"\[To be provided:[^\]]*\]", " ", _field(b, "Content"))) for _, b in records)
    if any_figures and not has_register:
        found.setdefault("Deck", []).append(
            "no `### Fact register` in section IX: list every figure the deck states (value, unit, scope, source) so every page "
            "uses the same number with the same scope")
    for head, tokens in missing_figures.items():
        uniq = list(dict.fromkeys(tokens))
        found.setdefault(head, []).append(
            "figures in visible copy that the Fact register does not hold (add them with unit, scope and source, or correct the "
            "copy to the registered value): " + ", ".join(uniq[:8]))

    if storyline and record_titles:
        norm = lambda s: re.sub(r"\W+", " ", s.lower()).strip()  # noqa: E731
        if len(storyline) != len(record_titles):
            found.setdefault("Deck", []).append(
                f"the Storyline lists {len(storyline)} titles but there are {len(record_titles)} slide records: keep them in step")
        else:
            for (head, _), s_title, r_title in zip(records, storyline, record_titles):
                if r_title and norm(s_title) != norm(r_title):
                    found.setdefault(head, []).append("record Title differs from its Storyline entry: the storyline is the argument, keep them identical")

    body = [(h, e) for h, e in exhibits if e not in ("furniture", "")]
    run_head, run_len, prev = None, 0, None
    for head, exhibit in body:
        run_len = run_len + 1 if exhibit == prev else 1
        prev = exhibit
        if run_len == 3:
            run_head = head
            found.setdefault(head, []).append(
                f"third body page in a row drawn as `{exhibit}`: vary the exhibit to the claim (a chart for a comparison, a flow for a sequence, "
                "an annotated example for proof) or merge the pages")
    body_tiers = [t for _, furniture, t in tiers if not furniture]
    frontier = sum(1 for t in body_tiers if t.startswith("frontier"))
    if len(body_tiers) >= 4 and frontier > max(2, (len(body_tiers) + 1) // 2):
        found.setdefault("Deck", []).append(
            f"{frontier} of {len(body_tiers)} body pages are marked frontier: keep frontier for pages whose figure needs complex visual judgement "
            "(architecture, loop, hub-and-spoke, timeline, matrix, multi-series chart) and mark summaries, text arguments, tables, key figures, "
            "teams and single-series charts workhorse")
    tables = sum(1 for _, e in body if e in TABULAR)
    if len(body) >= 5 and tables / len(body) > 0.4:
        found.setdefault("Deck", []).append(
            f"{tables} of {len(body)} body pages are tables: a comparison, trend or share is read faster as a chart; keep tables for look-up detail")
    kinds = [e for _, e in exhibits]
    first_body = next((e for e in kinds if e != "furniture"), None)
    if records and first_body not in ("summary", "key-figures", "text-argument", None):
        found.setdefault("Deck", []).append(
            "the first body page is not an opening answer: open with a summary page that states the situation, the answer and what is asked")
    last_role = _field(records[-1][1], "Role").lower() if records else ""
    if records and not re.search(r"(clos|next step|decision|ask|recommend|summary|call to action|way forward)", last_role + " " + (kinds[-1] if kinds else "")):
        found.setdefault("Deck", []).append(
            "the deck does not end on a decision or next steps: close with what the reader should decide or do")
    return found
