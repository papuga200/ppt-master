# Deck brief: rich slide planning before SVG

**Status:** §9 steps 1–3 done; results in `FORK_RUN_LOG.md` (cq-brief1: the plan lever is real; cq-brief2: the independent reviewer works as a detector, six small fixes listed). **Date:** 19 September 2026. **Branch:** `consulting-quality`.

## 1. The hypothesis

ProposalIQ's HTML mockups are stronger than this fork's SVG pages on information design: hierarchy, slide complexity, consulting readiness. The candidate cause is the plan each renderer receives. ProposalIQ's Stage 3 hands its renderer a complete slide record — copy written, layout sketched in prose, editor notes separated — and starves the renderer of everything else. This fork's §IX block is rich on *relationships* and *copy* and silent on *hierarchy* and *spatial arrangement*.

The cq-test1 architecture page shows the gap. Its §IX said "five wave-one sites and four conditional wave-two sites connect to the central monitoring hub". The render (`projects/harrowgate-cq_20260918/.preview/03_architecture.png`) is three stacked tiers — Sites, Hub, Data — with no connection drawn between sites and hub. The relationship was in the plan; the picture that carries it was never decided before the SVG was written.

The confound: HTML gives the model a layout engine, SVG does not. Some of ProposalIQ's complexity may be affordable *because* CSS does the fitting. §9 is the test that separates the two.

## 2. What stays

Everything in `FORK_CHANGES.md`: Strategist, Design Spec, lock, SVG contract, checker, exporter, the authoring preview loop, `reference_library.py`, `pptx_render.py`. No semantic document model, no layout solver, no fact verification. The plan stays text; the Executor keeps geometry.

## 3. The deck brief

One object with three sections, each a file section the next stage reads:

| Section | Owns | ProposalIQ equivalent | Where it lives today |
|---|---|---|---|
| **Narrative** | audience, the decision they are making, governing thought, argument arc, recurring messages | Stage 1 (three variants) | Strategist Stage 1 confirmations + `design_spec.md §I` communication contract, scattered |
| **Structure** | ordered sections → ordered slide roles; `page_rhythm` | Stage 2 (fixed seven-section spine) | `design_spec.md §IX` roster ids/order/titles |
| **Slides** | one complete record per slide (§5) | Stage 3 (`SlideContent`) | `design_spec.md §IX` blocks, at `brief` or `complete` depth |

**Scale rule — a stage runs only when its section is missing.** This is the whole flexibility mechanism; there is no mode switch.

- Whole deck from sources: all three run.
- Three slides into an existing deck: Narrative is read from the existing spec; Structure inserts three rows and renumbers; Slides runs for the three.
- One slide: Narrative is three lines (who reads it, what they decide, the one point); Structure is one row; Slides runs once. Nothing is skipped, it is short.
- The user may hand in any section written by hand (a storyline, a fixed page list, a finished slide record) and the pipeline starts after it.

**Structure has two sources.** *Premade*: a deck template under `templates/decks/` carries an ordered page sequence today (`bcg-proposal`); ProposalIQ's seven-section proposal spine becomes one more deck template with its per-section creative scope (full / scoped / template-led) recorded. *Planned*: the Strategist authors the roster as it does now. Both produce the same Structure section.

**Narrative keeps the three-variant option.** PPT Master's Stage 2 already produces three solutions for confirmation; under delegation the agent picks one. Unchanged, but the chosen variant's arc and recurring messages are written down as the Narrative section rather than left in confirmation answers.

## 4. Where the design spec goes

`design_spec.md` stays the single planning artifact and the lock's source. §I–§VIII are unchanged (they *are* the design system the renderer receives). §IX becomes the Slides section in the record format of §5, always at `complete` depth — `brief` depth is retired for this profile because the whole point is that copy and composition are decided before drawing. The Narrative section is written as a new block at the top of §IX (or a §IX.0), so the Slides stage and the renderer read it from the same file.

Roster invariance, the checker's §IX-vs-`svg_output` comparison, and `page_rhythm` in the lock are untouched: they read ids, order and titles, which the new block still carries.

## 5. The slide record

The ProposalIQ `SlideContent` shape, minus requirement attribution, plus the two things PPT Master already does better (`Relationships`, `Fact IDs`) and the one thing neither has (`Hierarchy`).

```
#### Slide 03 - Study arrangements
- Role:              architecture            (ProposalIQ canonical_slide_role)
- Audience move:     …                       (PPT Master; ≈ message_explanation)
- Story link:        after P02 … / before P04 …   (new; ProposalIQ has section-level continuity notes)
- Title:             …                       verbatim on the slide
- Key message:       …                       verbatim on the slide (PPT Master "Core message")
- Relationships:     …                       PPT Master, unchanged: units and their order/link/parent/membership/contrast/overlap
- Hierarchy:         focal → secondary → supporting; what the eye lands on first   (new)
- Content:           every visible text block, labelled, in the wording that goes on the slide   (ProposalIQ content_brief)
- Visual scaffold:   a plain-text sketch of the composition — zones, what sits where, what spans what, reading order; devices named in ordinary words; no coordinates   (ProposalIQ visual_scaffold, expanded)
- Avoid:             the specific weak imitation for this page   (new; from consulting-review.md §2 vocabulary)
- Reference:         library id — borrow: "…" — never: "…"   (new; §6)
- Editor notes:      what a human should check before issue   (ProposalIQ final_touches; never renderer instructions)
- Fact IDs:          …                       PPT Master, unchanged, optional
- Composition (binding): kept only when a template prototype or the user binds it; otherwise the scaffold is a Reference
```

Rules carried from ProposalIQ's Stage 3 prompt: Title and Key message are client-facing copy, no workflow language; Editor notes are for the proposal manager, "make the title dominant" belongs in the scaffold; every creative slide is reconstructable by a designer who invents no strategy and no copy. Rules carried from PPT Master: `Relationships` is an information model, never a shape; `Fact IDs` when a facts file exists; `Data class: scenario` for invented numbers.

**Sequencing for large decks.** Author section by section in roster order, each call receiving the sections already written (ProposalIQ Stage 3). A deck of six pages or fewer is one call.

## 6. References move upstream

`reference_library.py` now has `build` (a PDF or PPTX enters the library one deck at a time, so a reference deck the user supplies is built at run time), `sheet` (every slide of a form on one contact sheet, ids stamped) and `show` (one slide full size). The planner **looks rather than searches**: it asks for the sheet of the page's form, picks the one or two slides whose structure solves the page's problem, sees them full size, writes the Visual scaffold borrowing from them, and records on the slide:

```
- Reference: lib.293842e0.p10 — borrow: "left rail of tier names; one filled focal element; two narrow bands down the right edge for the cross-cutting concerns" — never: "wording, counts, colours, brand"
```

The renderer receives the same image. The reference shapes the sketch, not only the drawing. The library stays optional, confidence-based and outside the repository; a rejected slide returns only as a counterexample. This is the small change with the largest reach: it is the one place the planner sees real consulting work before deciding the page.

## 7. What the renderer receives

Exactly ProposalIQ's contract, starved: the **design system** (`design_spec.md §I–§VIII`, `spec_lock.md`, the template workspace), the **slide records** for the pages in hand, the **matched reference images**. No sources, no narrative, no evidence brief. Its budget goes to hierarchy, geometry and craft.

Two SVG-specific additions ProposalIQ does not need:

1. The text calibration table (`text_measure.py calibrate`) — the renderer must know what fits.
2. **Condense for fit only.** `executor-base.md` §2.1 lets the Executor paraphrase, condense and regroup. Under this profile: Title and Key message verbatim (ProposalIQ's rule); Content blocks may be shortened to fit a zone but never dropped, moved across pages, or added to; the scaffold's zones, spans and reading order are followed unless the renderer states in its page note why the page's content defeats them. Locking every word, as ProposalIQ does, works there because CSS reflows and because a failed mockup is acceptable; here a failed page is not.

The authoring preview loop is unchanged. The page note gains one line: `Drift: none | <what the render does that the scaffold did not say>`.

**The reviewer is a separate call.** cq-test1 established that this model at this effort accepts its own render with three visible collisions. Any run of this design uses a fresh-context review call per page that receives the render, the slide record and the reference image, and must list every overlap, overflow and collision before an outcome is recorded, then classify: `accept` / `execution_repair` (edit the SVG) / `concept_replan` (revise the slide record, redraw). Without this the test in §9 is not measurable. This is `FORK_RUN_LOG.md` candidate (a) and is a prerequisite, not part of the hypothesis.

## 8. Worked example — the cq-test1 architecture page in the new format

Written by hand from the same materials the run had. The Narrative and Structure sections are not repeated here; `plan/storyline.md` is the Narrative.

```
#### Slide 03 - Study arrangements

- Role: architecture
- Audience move: from "nine hospital projects and a vendor" to "one governed system with a hub in the middle of it"; the directors should be able to say where a patient's data goes and who watches the whole thing.
- Story link: after P02, which promised "one system" as reason one; before P04, which shows how this system is switched on over six months. The hub and the steering band reappear on P04 as the spanning concern.
- Title: Nine Harrowgate sites can run as one governed system through the hub and controlled data path
- Key message: One operating model links site waves, a central hub, controlled data movement, safety escalation and monthly oversight.
- Relationships: five wave-one sites and four conditional wave-two sites each connect to the central monitoring hub; the hub is one node on an ordered data path patch → vendor cloud → daily extract → group research data store → sponsor statistics team (weekly, de-identified); identified data stays inside the group boundary; safety desk and signed agreements are control endpoints, not path steps; monthly steering oversight spans every site and the hub; wave two is inside the system but conditional on gate 1.
- Hierarchy: 1 the hub — the only filled shape on the page; 2 the nine sites as a ring or row of outlined nodes with lines into the hub, wave two dashed; 3 the data path as a thin ordered chain running out of the hub to the sponsor; 4 the steering band spanning sites and hub; 5 controls (safety desk, agreements, ethics) as small labelled endpoints at the boundary. The eye lands on the hub, then sees that everything connects to it, then reads the path.
- Content:
    eyebrow: STUDY ARRANGEMENTS
    wave-one sites (5): Harrowgate Royal · St Aldan's · Millbrook · Carrow Vale · Eastfield
    wave-two sites (4): "4 further sites — only if gate 1 is passed"
    per-site line: principal investigator · research nurse 0.5 FTE · data coordinator 0.2 FTE
    hub: Central monitoring hub — cardiac physiology team; all alerts reviewed within 4 working hours; escalates to site clinician
    data path (5 steps): Wearable patch → Vendor cloud → Daily extract → Group research data store → Sponsor statistics team (weekly, de-identified)
    boundary label: Identified data never leaves the group
    safety: Safety desk — serious adverse events within 24 hours
    agreements: Signed agreements — group is controller; vendor and sponsor are processors
    ethics: One ethics approval covers all nine sites; site-specific assessment before activation
    steering band: MONTHLY STEERING — SPANS EVERY SITE AND THE HUB
    legend: solid = operating flow · dashed = scope / conditional
    source line: Source: supplied client materials — study arrangements, steering note
- Visual scaffold:
    ┌ title ─────────────────────────────────────────────────────────────────────┐
    │                                                                            │
    │  ┌ dashed group boundary ("identified data never leaves the group") ─────┐  │
    │  │  ▓▓▓ MONTHLY STEERING — spans every site and the hub ▓▓▓  (band across top of boundary) │
    │  │                                                                       │  │
    │  │   ○ Royal   ○ St Aldan's   ○ Millbrook   ○ Carrow Vale   ○ Eastfield   │  │
    │  │      \          \             |             /             /           │  │
    │  │       \          \            |            /             /            │  │
    │  │   ┈ ○ ┈ ○ ┈ ○ ┈ ○ ┈  (wave two, dashed nodes, dashed lines, "only if gate 1")  │
    │  │                       ┌──────────────┐                                 │  │
    │  │                       │  ●  HUB      │  ← the one filled shape          │  │
    │  │                       │ 4-hour review│                                 │  │
    │  │                       └──────┬───────┘                                 │  │
    │  │   patch ▸ vendor cloud ▸ daily extract ▸ research data store ─┼─▸ sponsor stats (outside boundary) │
    │  │                                                               │        │  │
    │  │   safety desk 24h ·  signed agreements ·  ethics: one approval  (small endpoints along the bottom edge) │
    │  └───────────────────────────────────────────────────────────────┘        │
    │  legend: solid operating flow / dashed scope · conditional         source │
    └────────────────────────────────────────────────────────────────────────────┘
    Reading order: title → hub → sites into hub → steering band → data path out to sponsor → controls → legend.
    The sponsor statistics team sits outside the dashed boundary; the path crosses the boundary once and that crossing is the "de-identified, weekly" label.
    The steering band is a band across, not a box beside. Wave two is drawn at the same size as wave one, dashed, never as a smaller afterthought box.
- Avoid: three stacked tiers labelled SITES / HUB / DATA with nothing connecting them (the cq-test1 result — it shows layers, not a system); a second filled element competing with the hub; the steering concern as a vertical box beside the figure; site names wrapped onto a second line that collides with the per-site line.
- Reference: lib.293842e0.p10 — borrow: "one filled focal element among outlined ones; cross-cutting concern drawn as a band across the whole figure; dashed panel as scope" — never: "wording, counts, colours, brand".
- Editor notes: confirm the four wave-two site names are still unconfirmed at issue; confirm "4 working hours" is working hours not clock hours; the ethics sentence is the client's, keep its wording.
- Fact IDs: ev.1.2, ev.1.3, ev.1.4, ev.1.5, ev.1.6, ev.1.7, ev.1.8, ev.1.9, ev.1.10
```

What this record decides that the cq-test1 block did not: the hub is the centre of the picture and the only fill; the sites are drawn connecting to it; the data path leaves the hub and crosses the boundary once; the steering band is across, not beside. None of that is geometry — no coordinate, no size — and all of it is what the render got wrong.

## 9. The test

Cheapest signal first. No stage is built until step 3 says the lever is real.

1. **This note** — read it, say yes or no to the record format and the renderer contract.
2. **Hand-author the four harrowgate slide records** in §5 format (P03 is above), with the reference library configured so the Reference lines cite real slides the renderer will see.
3. **One run**: the existing Executor and preview loop, the new records in §IX, the fresh-context reviewer from §7. Same model, same effort, same template as cq-test1. You judge the four renders by eye against `harrowgate-cq_20260918`.
   - **Yes** looks like: the architecture page is a hub-and-connections figure; hierarchy is visible in the first second; fewer revisions spent on labels; the reviewer's drift line is short.
   - **No** looks like: the same stacked tiers with the scaffold's words pasted on; the same collisions. Then the ceiling is the medium or the model, not the plan, and the next move is the reviewer and effort experiments in `FORK_RUN_LOG.md`, not stages.
4. **On yes, build in this order**, one harrowgate run each: the Slides stage with reference matching upstream → Narrative and Structure as written sections → the scale rule → the proposal spine as a deck template.

## 10. Open questions

- ~~Whether `Composition (binding)` from a template prototype and the Visual scaffold can disagree, and who wins.~~ Answered by cq-brief2: they did (the cover's "green lower panel"), and the reviewer enforced the scaffold over the template. The prototype wins; the scaffold is written against it, and the reviewer prompt says so.
- Whether the Slides stage should see the previous page's *render* as well as its record when continuity matters (the doc proposes it; cost is one image per page).
- Where the reviewer's `concept_replan` verdict writes: the slide record in `design_spec.md` is the owner, which means a mid-run spec edit — allowed today only for roster repair. Needs a rule.
- ProposalIQ renders the whole deck in one call, which gives cross-slide consistency for free; the preview loop is per page. Keep per page (the render-and-look needs it) and rely on the deck review for consistency.
