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

Load [`consulting-review.md`](../../references/consulting-review.md) once, in the Step 6 reference batch.

## 2. Reference slides the author actually sees

```bash
python3 ${SKILL_DIR}/scripts/reference_library.py match --form <form> --need "<relationships this page must show>" [--density high] --project <project_path> --page <page>
```

Match on the communication problem: `--form` is the page's job (`architecture`, `timeline`, `comparison`, `process`, `recommendation`, `matrix`, `capability_map`, `table`, `chart`, `cover`; `forms` lists what the library holds) and `--need` names the relationships in a few words. The result carries the slide's id, the problem it solves, a few observations and an `IMAGE:` line. **A reference on disk is not a reference seen**: the host attaches the image to the tool result; when it does not, open that path with the host's image tool before drawing. Delivery is recorded in `quality-run.json`.

- Ask for one reference for a page whose form is difficult or unfamiliar; ask for another (`--exclude <id>`) only when a different treatment is needed. Covers, simple statements and pages with no useful precedent need none.
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
3. Judge the image against the page's §IX brief, the locked visual language and any reference, using the four questions in [`consulting-review.md`](../../references/consulting-review.md) §1. Text that overlaps, clips or crowds is always fixed.
4. **Accept** a page that works, at once. Otherwise make the one highest-impact change - a local edit for a local defect, a redraw of the figure for a wrong composition - preserve what works, render again and check that the change did what it was meant to.
5. Record the outcome:
   ```bash
   python3 ${SKILL_DIR}/scripts/page_review.py note <project_path> <page> --outcome accepted|unresolved --text "Preserve: ... Main weakness: ... Change made: ... Result: ..."
   ```

**Budget**: one first draft plus at most three revisions per page (`revision_budget` in `quality-run.json`); a redraw and a local patch both count, and changing tools does not reset it. The budget is a ceiling, not a target. When two successive revisions leave the same major problem, change the approach instead of repeating the edit. When a revision is worse, `page_review.py restore <project_path> <page> --rev N` brings back the better one. On exhaustion keep the best usable revision and record `unresolved` with the issue named - never call a page accepted because the counter ran out, and never discard the deck because one page stays weak. A page that does not render is a technical defect: repair it before judging its look.

An edit after a page's outcome was recorded invalidates that look (`page_review.py status` shows it): render the page again.

**Optional mockup** (only when the run enables image generation for it, and never by default): for an important page whose composition survives repeated direct revisions and no reference resolves, one generated mockup may serve as a design target. Save it under `<project_path>/analysis/design-mockups/`, never under `images/`; rebuild text, shapes and diagrams natively from the §IX brief, taking no wording or number from the mockup; never place it as a slide background. It counts against the page's revision budget.

## 4. Deck review

After the final quality gate passes and before Step 7:

```bash
python3 ${SKILL_DIR}/scripts/page_review.py contact-sheet <project_path>
```

Look at the contact sheet and read the titles in order, open full-size renders of the dense and critical pages, and apply [`consulting-review.md`](../../references/consulting-review.md) §4. Write the prioritised change list to `<project_path>/.review/deck_review.md`. Apply changes to the affected pages only (each through §3's render-and-look, within its remaining budget); a plan-level change edits the owning §IX entry first, a change to a recurring decision is made once at its owner and every affected page is rendered again. Rerun the final checker once after the edits, then look at the contact sheet once more to verify. One review plus one verification is the normal amount.

## 5. Inspect the PowerPoint the user will receive

After Step 7.3 exports:

```bash
python3 ${SKILL_DIR}/scripts/pptx_render.py <project_path>/exports/<file>.pptx --project <project_path>
```

Look at the contact sheet, then at each full-size slide image it lists. Compare with the SVG renders for missing assets, changed wrapping, font substitution, clipping and moved geometry. Repair a difference in the page SVG (never in the PPTX), render that page, rerun the final checker, export again and re-inspect the changed slides. Exit 3 means no renderer is available: report the deck as visually checked in SVG but unverified in PowerPoint.

## 6. Finish

Report: the export path; per page, accepted or unresolved with the named issue; references delivered; whether the PowerPoint was inspected; anything in the material that was missing or ambiguous. `quality-run.json` and `.review/` are the record; they hold no claims, sources or node inventories.
