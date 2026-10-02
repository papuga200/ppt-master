---
description: Consulting-quality profile of Default Generate - the author renders and inspects every page while drawing it, sees matched reference slides, reviews the whole deck, and inspects the exported PowerPoint.
---

# Consulting-Quality Profile

> Fork addition, not upstream. A profile of [`generate-pptx.md`](../generate-pptx.md): Steps 1-7, the Strategist, `design_spec.md`, `spec_lock.md`, the canonical SVG contract, the checker gates and the exporter are unchanged and remain the authority. This file states only what differs. It never combines with `quick-generate`, `image-to-pptx` or `beautify-pptx`.

**Activate** only on explicit intent: the user names the profile ("consulting-quality", "consulting quality profile") or asks for a consulting-grade deck that is rendered, inspected and revised page by page. Deck size, model capability or a consulting topic alone never activates it.

**Objective**: a deck the user judges visually and communicatively ready with little redesign. Passing checks is necessary and is not the goal.

**Standing instruction on content**: work from the supplied material. Preserve its meaning, numbers, names, caveats and material relationships. Do not invent evidence, results, quotations or client facts to improve a slide. When something important is missing or ambiguous, surface it instead of pretending it is known. This profile performs no fact verification and requires no claim-level citation records; a visually accepted deck is not a fact-checked deck.

## 1. What differs from Default

| Default instruction | Under this profile |
|---|---|
| Step 6 authors every page, then gates; nothing is rendered while drawing | After writing each page, run the **authoring preview loop** (§3) on it before starting the next page. The loop renders and looks; it never runs the checker, so the checker cadence (early gate, final gate, consolidated repair) is unchanged. |
| `visual-review` stage is opt-in, after the final gate, position-and-spacing fixes only | That stage stays as it is and stays opt-in. The authoring preview loop is a different thing: it belongs to the author, happens during authoring, and may recompose the page in hand. Do not run both by default. |
| References are whatever the template workspace carries | Before drawing an unfamiliar or difficult page, ask for one matched reference slide (§2). |
| Step 7 ends at export | After export, render the PPTX itself and inspect it (§5). |
| No deck-level design pass | After the final gate and before Step 7, run one deck review (§4). |

Everything else - roster authority, lock re-reads, calibration, width estimation, native shapes, image acquisition, confirmations and their delegation - is Default's. Under explicit delegation the two Strategist stages are decided by the agent as [`generate-pptx.md`](../generate-pptx.md) Step 4 already allows; this profile adds no per-slide confirmation.

Load [`consulting-review.md`](../../references/consulting-review.md), [`diagram-clarity.md`](../../references/diagram-clarity.md) and the compact [`svg-creation-tools.md`](../../references/svg-creation-tools.md) catalog in the Step 6 reference batch. Load [`diagram-planning.md`](../../references/diagram-planning.md) when planning or realizing a diagram or dense timeline; load the catalog's complete recipe and tool contracts at their stated triggers.

**Author-owned scene compilation**: The author may choose a measured native scene as the page's creation source and compile it to the canonical SVG. The author retains the approved semantics, style, composition, operands, paint and z-order. [`svg-creation-tools.md`](../../references/svg-creation-tools.md) §2 governs source/compiler correspondence. The resulting SVG still contains every visible element and passes the ordinary final checker, native export and PowerPoint parity gates.

## 2. Reference slides the author actually sees

```bash
python3 ${SKILL_DIR}/scripts/reference_library.py sheet --form <form> --project <project_path> --page <page>
python3 ${SKILL_DIR}/scripts/reference_library.py show <id> [<id>] --project <project_path> --page <page>
python3 ${SKILL_DIR}/scripts/reference_library.py companion <id> --kind annotations --project <project_path> --page <page>
```

Look, then pick. `--form` is the page's job (`architecture`, `timeline`, `comparison`, `process`, `recommendation`, `matrix`, `capability_map`, `table`, `chart`, `cover`; `forms` lists what the library holds). `sheet` returns one contact sheet of every slide of that form with its id stamped; look at it, choose the one or two whose structure solves this page's communication problem, and `show` them full size. Each result ends in an `IMAGE:` line. **A reference on disk is not a reference seen**: the host attaches the image to the tool result; when it does not, open that path with the host's image tool before drawing. Delivery is recorded in `quality-run.json`. When a form's sheet is too large to judge, `match --form <form> --need "<relationships this page must show>"` shortlists by keyword instead.

**Decks the user supplies for this run** are built into the library first: `build <deck.pdf|.pptx>` renders and indexes every page as `unlabelled`; `sheet --form unlabelled` shows them; `label <id> ... --form <form>` files each page's form (a few ids per call, by what the page does, not what it is about). Then use them like any other reference. The library lives outside the repository (`PPT_MASTER_REFERENCE_LIBRARY`) and no reference is ever packaged into a deck.

For curated examples with source, map and annotation companions, use [`svg-creation-tools.md`](../../references/svg-creation-tools.md) §3. Inspect the example's actual diagram and transfer the declared technique within this deck's locked style.

- Ask for one reference for a page whose form is difficult or unfamiliar; take a second from the same sheet only when a different treatment is needed. Covers, simple statements and pages with no useful precedent need none.
- A reference lends structure and devices, never facts, wording, counts, colours or branding. When the match is weak or the content does not fit it, reject it and say so in the page note.
- A slide the user rejected never returns as a positive match; `counterexamples` returns those deliberately, with the reason.
- No library configured (exit 3): continue without references and say so in the final summary.

## 3. The authoring preview loop

For each page, in roster order:

1. Decide the relationship and hierarchy the reader must see, then write the page SVG under the normal contract.
2. Render it and look at the image:
   ```bash
   python3 ${SKILL_DIR}/scripts/page_review.py render <project_path> <page>
   ```
   The tool keeps a numbered copy of every changed revision under `.review/backup/`, counts revisions in `quality-run.json` and prints `IMAGE: <path>`. For a closer look at one region of the same render add `--crop X,Y,W,H` (canvas pixels); a crop is not a revision.

   Every render is also **measured**: `page_lint.py` lays the page out in a browser and reads the real rectangles of every line of text, stroke and shape. Its result comes back with the render, with an overlay image that boxes each finding. `CERTAIN` findings (text on text, text off the canvas or invisible on its background, an export-contract error) are measurements: fix every one; the reviewer refuses a render that still has one. `FLAGGED` findings (a line through text, text leaving its shape, a shape over text) are probable defects: fix the mistakes; one drawn on purpose that reads cleanly may stay, and the reviewer rules on it from a zoomed crop. A page with a native table also gets PowerPoint's own wrapping of its cells predicted: `NATIVE_WORD_SPLIT` (certain: PowerPoint breaks a word the preview keeps whole), `NATIVE_WRAP_DRIFT` and `NATIVE_ROW_GROWTH` (flagged: a cell on more lines than drawn, a table grown into what is below it); each names the column width it needs - widen the column or shorten the text, never shrink the type below the floor. The lint does not try to know every failure; what a ruler cannot know is left to your eyes and the reviewer's. Up to four renders that only fix lint findings do not count as revisions.
3. Judge the image against the page's §IX brief, the locked visual language and any reference, using the four questions in [`consulting-review.md`](../../references/consulting-review.md) §1. Text that overlaps, clips or crowds is always fixed.
4. **Ask the independent reviewer** before deciding the page is done:
   ```bash
   python3 ${SKILL_DIR}/scripts/page_review.py review <project_path> <page>
   ```
   It is a separate model call that has not seen your drawing process, and by preference a model of another family than the author (`PPT_MASTER_REVIEW_MODEL`, `_EFFORT`, `_API_BASE`, `_KEY_VAR`, `_PROVIDER`): it receives the render, the §IX record, the review language, the Diagram contract of `diagram-clarity.md`, the references delivered for the page and the lint's flagged places with a zoomed crop of each; it rules on each flagged place (`DEFECT` or `ACCEPTABLE`), lists what a ruler cannot know (a leftover, unused canvas, unreadable text), checks the concept, and returns `VERDICT: PASS | EXECUTION_REPAIR | CONCEPT_REPLAN` with the highest-impact change. Read the inventory as fact: an author does not see collisions in its own page (cq-brief1), a fresh call does. `EXECUTION_REPAIR` → fix every listed item in the SVG, render, review again. `CONCEPT_REPLAN` → revise the page's §IX record first (Hierarchy, Visual scaffold), redraw, render, review again. A review is not a revision. Ask only after you have looked yourself and fixed what you saw; do not ask on a draft you already know is wrong.
5. **Accept** only a revision whose review returned `PASS`; otherwise make the one highest-impact change - a local edit for a local defect, a redraw of the figure for a wrong composition - preserve what works, render again and check that the change did what it was meant to.
6. Record the outcome:
   ```bash
   python3 ${SKILL_DIR}/scripts/page_review.py note <project_path> <page> --outcome accepted|unresolved --text "Preserve: ... Main weakness: ... Change made: ... Result: ..."
   ```
   `accepted` is refused while the current revision has no `PASS` review; `unresolved` needs none. `--no-review` is an explicit, recorded exception for a page whose reviewer is unavailable (no key, no network), never a way past a verdict.

**Budget**: one first draft plus at most three revisions per page (`revision_budget` in `quality-run.json`); a redraw and a local patch both count, and changing tools does not reset it. The budget is a ceiling, not a target. When two successive revisions leave the same major problem, change the approach instead of repeating the edit. When a revision is worse, `page_review.py restore <project_path> <page> --rev N` brings back the better one. On exhaustion keep the best usable revision and record `unresolved` with the issue named - never call a page accepted because the counter ran out, and never discard the deck because one page stays weak. A page that does not render is a technical defect: repair it before judging its look.

An edit after a page's outcome was recorded invalidates that look (`page_review.py status` shows it): render the page again.

**Optional mockup** (only when the run enables image generation for it, and never by default): for an important page whose composition survives repeated direct revisions and no reference resolves, one generated mockup may serve as a design target. Save it under `<project_path>/analysis/design-mockups/`, never under `images/`; rebuild text, shapes and diagrams natively from the §IX brief, taking no wording or number from the mockup; never place it as a slide background. It counts against the page's revision budget.

## 4. Deck review

After the final quality gate passes and before Step 7:

```bash
python3 ${SKILL_DIR}/scripts/deck_consistency.py <project_path>
python3 ${SKILL_DIR}/scripts/page_review.py contact-sheet <project_path>
```

`deck_consistency.py` compares the pages' drawn text and writes `.review/consistency.md`: one figure with two values on two pages and a missing or out-of-sequence chrome element are CERTAIN (fix them); a value written two ways, a name spelled two ways, chrome styled differently and one label keyed by different marker colours are FLAGGED (confirm each on the pages). A `## Glossary` section in `design_spec.md` (`- Term: definition` lines) makes its terms the canonical spelling. Run it again after the edits below.

Look at the contact sheet and read the titles in order, open full-size renders of the dense and critical pages, and apply [`consulting-review.md`](../../references/consulting-review.md) §4. Write the prioritised change list to `<project_path>/.review/deck_review.md`. Apply changes to the affected pages only (each through §3's render-and-look, within its remaining budget); a plan-level change edits the owning §IX entry first, a change to a recurring decision is made once at its owner and every affected page is rendered again. Rerun the final checker once after the edits, then look at the contact sheet once more to verify. One review plus one verification is the normal amount.

## 5. Inspect the PowerPoint the user will receive

Before the inspection, make the deck edit the way a hand-built one does:

```bash
python3 ${SKILL_DIR}/scripts/pptx_text_in_shapes.py <exported.pptx> --in-place --report <exported>.text-in-shapes.json
```

Text is set by [`consulting-typesetting.md`](../../references/consulting-typesetting.md) (line and paragraph spacing, native lists, native tables); a page with a `Native-ready: <key>=yes` table is exported with `--native-charts-and-tables`, and the deck runner writes speaker notes from each record (message, what the page must do, notes for the editor, data provenance) unless `notes/<page>.md` already exists. The exporter writes every label as its own non-wrapping text box over a rectangle. This pass moves each text into the shape it sits on (the shape's own text frame, word-wrap on, insets reproducing the position), merges the stacked lines of one block into one multi-paragraph text box, leaves alone what no shape contains (labels on connectors), marks the slide's title as its title placeholder, names objects after their text, turns thin rectangles into real lines, gives pictures alt text, and moves the header, footer, logo and page number that repeat on the content slides to one slide layout (the page number becomes a field). Nothing moves on the rendered slide; `--verify <before.render> <after.render>` checks that against the two PowerPoint renders. The exporter's original is kept under `exports/floating-text/`. Authors make it effective by drawing one shape per box with its text fully inside, one column of text per shape (a table is a grid of cell rectangles), and one `<text>` per paragraph.

After Step 7.3 exports:

```bash
python3 ${SKILL_DIR}/scripts/pptx_render.py <project_path>/exports/<file>.pptx --project <project_path>
```

Then measure the deck in PowerPoint itself:

```bash
python3 ${SKILL_DIR}/scripts/pptx_parity.py <project_path>/exports/<file>.pptx --project <project_path>
```

It reports what PowerPoint lays out differently from the SVG (text set lower or wider running out of its box or into a neighbour, table rows that grow, words broken mid-word, stray or accidental bullets, renumbered lists, numeric columns that lost their alignment), each with a crop of the PowerPoint render. Fix every certain finding in the page SVG. Look at the contact sheet, then at each full-size slide image it lists. Compare with the SVG renders for missing assets, changed wrapping, font substitution, clipping and moved geometry. Repair a difference in the page SVG (never in the PPTX), render that page, rerun the final checker, export again and re-inspect the changed slides. Exit 3 means no renderer is available: report the deck as visually checked in SVG but unverified in PowerPoint.

## 6. Finish

Report: the export path; per page, accepted or unresolved with the named issue; references delivered; whether the PowerPoint was inspected; anything in the material that was missing or ambiguous. `quality-run.json` and `.review/` are the record; they hold no claims, sources or node inventories.
