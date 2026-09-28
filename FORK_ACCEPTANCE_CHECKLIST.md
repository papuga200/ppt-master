# Acceptance checklist — what the user asked for and approved (through 20 September 2026)

The gate before any end-to-end test is called ready. Each line: what was agreed, and how it is checked. `A` = checked automatically by `hosts/responses_api/acceptance.py` on the project and its exported deck; `C` = checked in configuration or code by the same script; `M` = needs eyes (mine, on the PowerPoint render, reported honestly).

## 1. Planning (the original goal: a richer plan, ProposalIQ-style)
- 1.0 `A` High-level request in, proposal out: the inputs are the client's documents, the firm's knowledge base and a request of a few lines; the tool works out the answer itself in a solution stage (`solution.md`: situation, win themes, solution with reasons, scope, plan, team, price built from the rate card and reconciling, proof, risks) - nobody pre-solves it.
- 1.1 `A` The plan runs Narrative → Structure → Slides: `design_spec.md` has a `### Narrative` block (audience decision, governing thought, arc, recurring messages, continuity rules) and one `#### Slide NN - name` record per page.
- 1.2 `A` Every record carries the agreed fields: Role, Author tier, Layout, Audience move, Story link, Relationships, Title, Core message, Hierarchy, Content, Visual scaffold, Fill, Avoid, Reference, Editor notes, data class — and NO `source_requirement_ids`.
- 1.3 `A` The planner classifies each slide `frontier` or `workhorse` (Author tier).
- 1.4 `A` Records point at reference-library slides by id with borrow / never (the planner looked at contact sheets; "look, don't search").
- 1.5 `M` Flexible scale: the same stages serve one slide, three slides or a deck; a stage runs only when its section is missing (premade structure is accepted as given).
- 1.6 `A` Proposal writing rule: the deck never enumerates the client's requirements or says which requirement a page addresses (no "Requirement 5", "REQ-", "as required in section 3.2", compliance-matrix pages); the requirements are answered through the story, the design and the diagrams.
- 1.8 `A` What the sources do not give is never invented: people, CVs, credentials, client references, logos and unproven results appear as marked placeholders `[To be provided: ...]` in a drawn slot of the final size, and are listed for the editor.
- 1.7 `M` The proposal is a genuinely good response to the RFP (solution, team, commercials, pilot, rollout), not only a good-looking one.

## 2. Template (default stage, no approval gate)
- 2.1 `A` A template is used when provided, otherwise created before any page is drawn (`templates/*.svg` + `templates/template.md`); no anchor page, no waiting.
- 2.2 `C` No approval or preview gate anywhere in the run: instructions in, deck out; changes afterwards on request.
- 2.3 `A` The exported deck has named slide layouts per template layout (cover, content, …) holding the repeated chrome once; the page number is a field; content layouts carry a title placeholder.
- 2.4 Not needed (user, 20 Sep 2026): templates with more than one master are out of scope. An independent review of the plan itself is also set aside for now.

## 3. Authoring: speed, cost, models
- 3.1 `C` One isolated conversation per page over a shared system prompt; pages authored in parallel.
- 3.2 `C` Routing by tier: workhorse = gpt-6-luna @ high (from 24 Sep 2026; was DeepSeek V4.1 Flash pinned to Modal → Together → Venice → GMICloud); frontier = gpt-6-sol @ high (from 23 Sep 2026; was gpt-5.6-sol @ medium).
- 3.2a `C` Premium option (user, 23 Sep 2026): `deck_runner.py --premium` gives the frontier pages to Claude Opus 5.5 @ medium instead of Sol, for a deck where the look matters more than the cost (about 3.5x Sol per frontier page, no faster). Sol stays the default.
- 3.3 `C` The reviewer is Grok 4.6 @ medium on every page and on the deck (user's decision; GPT-6 Sol @ medium was tried on 23 Sep 2026 and set aside: stricter, but its fixes did not read as improvements and they cost more).
- 3.4 `C` Export proceeds by default when the repair budget is spent; what is still open is written beside the deck.
- 3.5 `C` No wall-clock caps on model work; the host retries transport faults including a body cut off mid-read.

## 4. Review
- 4.1 `A` Every page is rendered, measured by the geometry lint (certain vs flagged; the reviewer rules on flagged items from zoomed crops) and reviewed by an independent call; `accepted` needs a PASS of the current revision.
- 4.2 `C` The lint stays common-sense: reliable in the great majority of cases, the rest left to the reviewer's judgement; it measures first lines of multi-line texts, line spacing, anonymous Gantt bars.
- 4.3 `A` A deck review reads the whole deck, and its findings are handed back to the pages' authors (deck-repair round).

- 4.4 `C` A repair never demotes a page that had passed: when the repaired revision's review finds no defect (polish only) the page stays accepted; when it finds defects, fails the lint or was never reviewed, the revision that had passed is restored and the failed attempt's review is kept (`deck_runner.keep_or_restore`, unit-tested). A change the user asked for is never rolled back.
- 4.5 `C` Revise from my comments: comments left on elements in the live-preview interface are read back (`deck_runner.py <project> --session NAME --revise`; `--dry-run` shows what would be sent and calls no model), each annotated page goes to its own author's conversation, the marks are cleared when done, and the deck is re-exported. No approval gates: changes come afterwards, on request.

## 5. Typesetting and density
- 5.1 `A` Line spacing: body and table text at 1.4–1.5 (never under 1.3), headings 1.2–1.3, titles 1.15–1.2 — measured on the SVGs (median per band).
- 5.2 `M` Paragraph, list-item and block gaps: inside a group tighter than between groups; padding 10–12 px; not squished.
- 5.3 `M` Packed consulting density (between Microsoft MCRA and BCG): the figure spans the content area, nothing floats in white space, dense in information and never in leading.
- 5.4 `A` Timelines and Gantts: every bar labelled on it or beside it; milestones, gates and windows named where they happen; a legend explains symbols only (lint `BAR_WITHOUT_LABEL` = 0 on the shipped pages).
- 5.5 `M` A multi-level Gantt with overlapping workstreams where the case has a plan.

## 6. The PowerPoint edits like a hand-built one
- 6.1 `A` Text lives inside the shape it sits on (share of texts inside shapes reported; floating boxes only for what no shape contains).
- 6.2 `A` Lines of one paragraph are one wrapping paragraph; heading-and-body blocks end at rules and headings; no over-merged rows.
- 6.3 `A` One real title placeholder per slide.
- 6.4 `A` Lists are native lists with the brand's typed marker; no drawn bullet squares beside text boxes; typed numbers become automatic numbering.
- 6.5 `A` Tables are native PowerPoint tables, styled per cell, text in the cells, wherever the plan marks `Native-ready`.
- 6.6 `A` Header, logo, rules, footer and page number live on slide layouts (edit once); the page number is a field.
- 6.7 `A` Objects are named after their text; pictures have alt text; hairlines are real lines.
- 6.8 `A` Straight arrows between boxes are glued connectors; authors are told to draw connector routes that can be glued (straight or one bend).
- 6.9 `A` Speaker notes on every slide from the plan (message, what the page must do, notes for the editor, data provenance).
- 6.10 `A` The export pass moves nothing: PowerPoint render before and after differs by no more than 1% of ink moved over 2 px on any slide.

## 7. Working agreements
- 7.1 `M` Every step's PPTX and PowerPoint renders are sent into the chat as they are verified.
- 7.2 `M` Results are reported faithfully: what failed, what it cost, what is still open.
- 7.3 `M` Nothing is committed unless asked.
