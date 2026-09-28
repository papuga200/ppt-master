"""Storyline, fact-register, canonical-term and exhibit checks on a planner's design_spec.md (families F07/F08)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "hosts" / "responses_api"))
from plan_checks import fact_register, storyline_titles, story_lint  # noqa: E402


def record(n, name, *, role="body", exhibit="bar-comparison - options on one measure", title="Option B halves setup cost for the same coverage",
           content="Setup cost: A USD 42,000; B USD 21,000."):
    return (f"\n#### Slide {n:02d} - {name}\n- **Role**: {role}\n- **Exhibit**: {exhibit}\n- **Title**: {title}\n"
            f"- **Core message**: B is cheaper.\n- **Content**: {content}\n")


def deck(records, storyline=None, register="- F01 | USD 42,000 | option A setup cost | sources/costs.md\n- F02 | USD 21,000 | option B setup cost | sources/costs.md\n",
         terms="- Option B - the four-team pilot\n"):
    titles = storyline if storyline is not None else [r.split("- **Title**: ")[1].split("\n")[0] for r in records]
    story = "".join(f"{i}. {t}\n" for i, t in enumerate(titles, 1))
    return (f"## IX. Content\n\n### Storyline\n{story}\n### Fact register\n{register}\n### Canonical terms\n{terms}\n" + "".join(records))


GOOD = [
    record(1, "Cover", role="cover", exhibit="cover - title", title="Pilot choice"),
    record(2, "Summary", exhibit="summary - situation, answer, ask", title="Fund option B: the same coverage for half the setup cost"),
    record(3, "Cost", title="Option B halves setup cost for the same four-team coverage"),
    record(4, "Next", role="closing", exhibit="closing - decision", title="Approve option B this month"),
]


def test_clean_plan_has_no_findings():
    assert story_lint(deck(GOOD)) == {}


def test_missing_lists_are_reported_at_deck_level():
    spec = "".join(GOOD)
    found = story_lint(spec)
    text = " ".join(found["Deck"])
    assert "Storyline" in text and "Canonical terms" in text and "Fact register" in text


def test_unregistered_figure_is_reported_but_format_variants_match():
    recs = GOOD[:2] + [record(3, "Cost", content="Setup cost: A USD 42k; B USD 21,000; C USD 55,000.")] + GOOD[3:]
    found = story_lint(deck(recs))
    issue = " ".join(found["Slide 03 - Cost"])
    assert "USD 55,000" in issue and "42k" not in issue


def test_small_counts_years_and_step_numbers_are_not_figures():
    recs = GOOD[:2] + [record(3, "Cost", content="3 options in 2026; step 2 of 4; USD 42,000 and USD 21,000.")] + GOOD[3:]
    assert "Slide 03 - Cost" not in story_lint(deck(recs))


def test_topic_label_and_long_titles():
    recs = GOOD[:2] + [record(3, "Approach", title="Our approach"),
                       record(4, "Long", title=" ".join(["word"] * 16))] + GOOD[3:]
    recs[-1] = recs[-1].replace("Slide 04", "Slide 05")
    found = story_lint(deck(recs))
    assert any("topic label" in i for i in found["Slide 03 - Approach"])
    assert any("16 words" in i for i in found["Slide 04 - Long"])


def test_storyline_must_match_records():
    found = story_lint(deck(GOOD, storyline=["Pilot choice", "Something else", GOOD[2].split("- **Title**: ")[1].split("\n")[0], "Approve option B this month"]))
    assert any("differs from its Storyline" in i for i in found["Slide 02 - Summary"])


def test_exhibit_vocabulary_runs_and_table_share():
    body = [record(i, f"T{i}", exhibit="table - look-up", title="Option B halves setup cost for the same coverage") for i in range(3, 9)]
    recs = GOOD[:2] + body + [GOOD[3].replace("Slide 04", "Slide 09")]
    found = story_lint(deck(recs))
    assert any("third body page in a row" in i for i in found["Slide 05 - T5"])
    assert any("are tables" in i for i in found["Deck"])
    bad = GOOD[:2] + [record(3, "Cost", exhibit="infographic - pretty")] + GOOD[3:]
    assert any("not in the vocabulary" in i for i in story_lint(deck(bad))["Slide 03 - Cost"])


def test_opening_and_closing_are_required():
    recs = [GOOD[0], GOOD[2].replace("Slide 03", "Slide 02"), record(3, "More", title="Option B also starts within the current quarter")]
    found = story_lint(deck(recs))
    text = " ".join(found["Deck"])
    assert "opening answer" in text and "decision or next steps" in text


def test_helpers():
    spec = deck(GOOD)
    assert storyline_titles(spec)[1].startswith("Fund option B")
    assert "42000" in fact_register(spec)


def test_a_requirements_coverage_page_is_flagged():
    recs = GOOD[:2] + [record(3, "Coverage", exhibit="table - look-up of each request item",
                              title="Every objective, scope item and deliverable in the City's request has an owning task")] + GOOD[3:]
    recs[-1] = recs[-1].replace("Slide 04", "Slide 04")
    found = story_lint(deck(recs, storyline=[r.split("- **Title**: ")[1].split("\n")[0] for r in recs]))
    assert any("maps the client's requirements back" in i for i in found["Slide 03 - Coverage"])
