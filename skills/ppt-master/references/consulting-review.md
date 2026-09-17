---
description: Review language for the consulting-quality profile - how to look at a rendered page and at a whole deck, what weak consulting design looks like, and what strong diagram, timeline and summary pages do.
---

# Consulting Review

> Loaded only by [`consulting-quality`](../workflows/profiles/consulting-quality.md). It is a way of looking, not a rule set: nothing here is a quota, a ban, or a checker input. The technical contract stays with [`shared-standards-core.md`](./shared-standards-core.md) and the checker.

## 1. The page review note

Judge the rendered image, never the markup: a weakness is what a reader would experience. After each look, answer four questions in a few lines, and record them with `page_review.py note` when the page is settled.

| Question | What a good answer looks like |
|---|---|
| **Preserve** - what already works and must survive the next edit? | "The phase band and the milestone hierarchy are clear." Name it so the next revision does not undo it. |
| **Main weakness** - what single thing most weakens this page? | One thing, the highest-impact one. "The five workstreams are drawn as one sequence, so the page hides parallel delivery." |
| **Next change** - what specific change would fix it, and is it local or a recomposition? | "Recompose as aligned lanes under the same phase band; reserve a clear channel for the two handoffs." |
| **Verification** - what will the next render show if it worked? | "Parallel work is visible, labels are readable, each handoff has an unambiguous endpoint." |

Outcome is one of: **accept** (a page that communicates clearly and fits the deck is accepted at once - using the whole revision allowance is never a goal), **revise** (one change, the most important one, then render again), or **unresolved** (the budget is spent or the approach is exhausted: keep the best revision and name the remaining issue plainly).

Distinguish a local defect from a wrong composition. Overlapping or clipped labels, a cramped zone, a stray alignment need a local edit that leaves the rest alone. A system drawn as unrelated cards, a plan with parallel work drawn as one line, a summary that lists instead of arguing need a redraw of the figure. Neither is a reason to touch other pages.

If two successive revisions leave the same major problem in place, change the approach - look at another reference, choose another composition, try a permitted mockup - rather than repeating the edit. If a revision made the page worse, restore the better one (`page_review.py restore`). Reviewers, including you, can be wrong: resolve ambiguous feedback by the page's objective, not by satisfying every remark.

## 2. Symptoms of generated-looking design

Prompts for the eye, not prohibitions. A card, three columns, or an accent are fine when the content asks for them.

| Symptom | The question that exposes it | The usual cure |
|---|---|---|
| Everything weighs the same | Where does the eye land first - and is that the message? | One focal element by fill, size or containment; mute its siblings. If nothing deserves it, the page has no message yet. |
| A container around every item | What does this border or fill mean? | Remove the box and keep its content, or give the boundary a meaning: outline for a grouping that owns nothing, tint for what belongs together, dashes for what is planned or outside. Separate zones with white space, not rules. |
| The same card row again | Is this page's content really a set of parallel peers? | Draw the structure the content has: layers, a hub, a flow, lanes, a matrix. Vary form only where the information differs. |
| Arrows that clarify nothing | What relation does each connector state, and could a reader say it aloud? | Fewer, labelled or legend-defined connectors with clear endpoints; two line styles always get a legend. |
| A title that fits any deck | Could this title be swapped with another page's without loss? | State the finding as a sentence, with the entity and the figure in it. |
| A cross-cutting concern as one more box | Does governance, security or oversight look like a peer of what it governs? | Draw it as a band across, or a rail beside, everything it applies to. |
| Groups padded to match | Do unequal groups look equal? | Let counts and widths differ; a band that holds more is drawn larger. |
| Decoration without meaning | Does this icon, stripe or shape say anything the words do not? | Delete it. |
| Title repeated in the body | Is the first body line the title again? | Replace it with the proof: the mechanism, the figure, the consequence. |
| Text that overlaps, clips or crowds | At reading size, does anything touch, overflow its zone, or sit on a line? | Widen the zone, shorten the label, or move it outside the crowded region. This is always fixed, never accepted. |

## 3. What strong pages do

**Architecture and arrangement pages.** The body is one figure. Structure is nested or stacked and the nesting is the argument. Hierarchy is carried by geometry - one filled focal element among outlined ones, containment depth, band width - while type only names things. High density is fine when every piece sits in a named zone. A left rail or an axis declares the reading order. Scope is a dashed boundary. A left-hand list can be tied to the figure with numbered badges. Every line style is defined in a small legend.

**Timelines and delivery plans.** Draw the distinctions the content needs and no more: a simple sequence is a simple sequence, but parallel workstreams, overlapping phases, handoffs and gates must be visible as such. One continuous track or aligned lanes over a shared phase ruler; decisions (gates) sit on the track with what they decide and what happens otherwise; detail hangs off the track instead of replacing it; a concern that is not a phase runs as a band above or below. Date-driven positions are computed, qualitative ones are not faked as dates.

**Executive summaries.** A synthesis of the argument, not the body titles repeated. The governing thought once, then a small number of rows, each a claim with its proof, separated by hairlines or white space rather than boxed as equal cards. The recommendation or decision asked for is the focal element.

**Comparisons.** Shared axes or a shared baseline so the eye compares like with like; the verdict is visible without reading every cell.

## 4. The deck review

After the last page is settled, look at the contact sheet and read the titles in order, then open the full-size pages that matter. Look for what a page-by-page loop cannot see:

- Does the argument progress, and does the ending resolve what the opening asked?
- Does the executive summary match the argument the body actually makes?
- Is the same claim repeated without progression?
- Do related concepts keep the same name, colour and treatment on every page; does a later page introduce a contradictory visual vocabulary?
- Are different kinds of content drawn identically, or identical kinds drawn differently without reason?
- Are dense pages carried by hierarchy, and is the rhythm between dense and light pages deliberate?

Write a short prioritised change list - what, on which page, why, and how the next render will show it. Apply it to the affected pages only. A change to a recurring decision (label hierarchy, footer, line weight) is made once at its owner - the Design Spec entry - then every affected page is edited and rendered again. One deck review plus one targeted verification is the normal amount; do not polish indefinitely.
