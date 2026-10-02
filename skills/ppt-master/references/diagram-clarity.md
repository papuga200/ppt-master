# Diagram clarity: choose the view that answers the page question

This is planning guidance for any deck, not a diagram template or a required style. The page's audience question and source-backed claim come first. The visual task says what a reader must **see** to understand the answer. Executor chooses the carrier and geometry. A sentence, photo, annotated screenshot, chart or table may answer better than a diagram.

For diagrams and dense timelines, load [`diagram-planning.md`](./diagram-planning.md) before allocation. It separates the planner's semantic organization and abstraction from the author's carrier, layout family and geometry.

## Choose the relationship before the form

| Reader needs to understand | Prefer to test first | What must be explicit |
|---|---|---|
| What this is and where it sits | One subject with people/systems around it | Scope boundary; names and purposes; labelled interactions |
| What happens next | Short process or journey | Direction, start/end, decision branches, output |
| How parts fit | Structure at one level of detail | Parent/grouping boundaries; only material links |
| How two options differ | Aligned comparison | Same criteria, units and reference point |
| What changed or how much | Value-driven chart | Units, baseline, scale, direct labels, provenance |
| What a user does | Annotated real or faithful example | Input, action, result, meaningful callouts |
| What to decide | Evidence and options | Criterion, trade-off, recommendation or open choice |

For a simple relationship, use a small number of directly labelled elements and allow the visual to breathe. For a dense system, show a context view before the focused internal view; do not shrink every component into one slide. Only a user-requested exhaustive reference view should carry an exhaustive inventory, and it still needs grouping and an overview. Directional links have arrowheads; label any link whose meaning is not obvious. Avoid colour-only semantics, unexplained icons, legends that could be direct labels, intersecting connectors, and repeated containers without a grouping meaning. Reuse names and cue meanings across related pages. Keep one visual level of detail per diagram unless the contrast between levels is the actual lesson.

When a node holds several inputs, actions or outputs, write short parallel bullets or labelled fragments inside it. Place the reading sentence, interpretation, provenance and caveats beside or below the figure. A sentence inside a node is useful when its exact wording is evidence; otherwise it usually slows scanning. Preserve full meaning through the whole page, not through prose packed into every box.

## Primary examples and the transferable principle

- [C4 system context](https://c4model.com/diagrams/system-context): a whole system as one unit, with external people and systems. Transferable: answer the scope question before exposing components.
- [C4 diagram levels](https://c4model.com/diagrams): context, containers, components and code serve different audience questions; use only the levels that add value. Transferable: progressive detail, not all levels by default.
- [C4 notation and review](https://c4model.com/diagrams/notation): meaningful titles, names, descriptions and labelled relationships make diagrams usable on their own. Transferable: explain the marks, not just draw them.
- [Microsoft architecture diagram guidance](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/design-diagrams): match diagrams to audience questions, use clear directional links, label relationships, include boundaries, and layer context before detail. Transferable to nontechnical process and operating-model diagrams too.
- [IBM Carbon chart types](https://carbondesignsystem.com/data-visualization/chart-types/): select a chart from the analytic purpose, such as comparison, trend, part-to-whole or connection. Transferable: a familiar visual grammar can reduce explanation when it matches the question.

These are pattern references, not assets to copy into a deck. A real data chart must use real or explicitly labelled scenario values. For a technical diagram, exact architecture still comes from the source, never from a reference example.

## Diagram contract (authors draw to it; the reviewer and the lint check it)

A diagram is read without a presenter. Every mark states one relationship, and every relationship the record names is a mark. The geometry lint measures the items tagged `[lint]`; the reviewer rules on the rest.

**Connectors**
- Every connector has a direction: one arrowhead, at the target end only (`marker-end`, or a small filled triangle touching the end). A line with no head is allowed only for a declared association (dashed, or a tether from a label to its mark). [lint `CONNECTOR_NO_TARGET`]
- Each end touches something: the edge of a node, a container, another connector, or an end-state shape. An arrow that stops in empty space, or points at floating text, has no target. [lint `CONNECTOR_NO_TARGET`]
- Prefer orthogonal routes: straight, or one or two right-angle bends. No diagonal shortcuts across the figure, no crossings you can avoid, no line running through a node it does not attach to. [lint `LINE_THROUGH_NODE`]

**Loops, exits and end states**
- A loop shows where it starts and where it returns: it leaves the deciding node and ends with an arrowhead on the node it returns to. A labelled underline below a row of steps is not a loop. [lint `LOOP_WITHOUT_HEAD`]
- Every exit of a decision (pass / fail, accept / repair / replan, budget spent) is its own labelled arrow to an explicit end state or to the step it re-enters. Never write the exits as a phrase beside the figure ("PASS → accepted, budget → unresolved").
- A terminal outcome is a node (a pill or box), not free text at the end of an arrow.

**Labels**
- Every label is attached: inside its shape, on or beside its connector (within about 12 px, off the line, never across another line), or a declared caption directly under or beside the figure. A short phrase floating in the figure area is an orphan. [lint `ORPHAN_LABEL`]
- No text crosses a line or a container's border: a label that belongs outside the boundary sits wholly outside it. [lint `LINE_THROUGH_TEXT`, `BOUNDARY_CROSSING`]
- Connector labels sit beside a straight segment, off every other line; a label names the relationship ("sends page images"), not a code.
- No internal codes (`EXECUTION_REPAIR`, `P09`, `W23`) on a reader's page unless the record defines them there.

**Callouts and keys**
- Numbered callouts are keyed both ways: every number in the notes column has the same number as a marker on the figure, and every marker on the figure has its note. [lint `UNKEYED_CALLOUT`]
- A legend explains symbols only (what a dashed line, a colour, a triangle means); it never carries content that could be a direct label. Draw the actual visual samples per [`diagram-planning.md`](./diagram-planning.md) §4.

**Boundaries, axes and scales**
- A container or boundary includes exactly what the text says it includes. If the words say "on your machine", every component on the machine is inside the outline and nothing else is.
- An axis appears only when its dimension is real: a time axis with dated or numbered ticks, a scale with units. An arrow with ticks under a process is decoration; remove it or give it a scale.
- One visual level of detail per figure; group only where the grouping means something.

**Laying it out**
- Choose the construction capability through [`svg-creation-tools.md`](./svg-creation-tools.md). Measured native architecture scenes and dated dense timelines coexist with the original ELK diagram and numeric-horizon timeline helpers. Keep one authoritative request per helper-built diagram and regenerate after changes; [`svg-creation-tools.md`](./svg-creation-tools.md) §2 defines the source/compiler contract.
- Arrows that are straight or bend at right angles between two boxes become native connectors glued to both boxes after export (`pptx_text_in_shapes.py`): draw them as one `<line>`, or one `<path>` of horizontal and vertical segments (`M x y H .. V .. H ..`) whose ends sit on the box edges.
