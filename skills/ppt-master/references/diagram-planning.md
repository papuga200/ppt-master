> See [`diagram-clarity.md`](./diagram-clarity.md) for the diagram contract and [`svg-creation-tools.md`](./svg-creation-tools.md) for construction capabilities.

# Diagram Planning Reference Manual

Choose the explanation before geometry when a page needs a diagram, comparison of systems, or dense timeline.

## 1. Decisions and authority

**Hard rule**: Preserve the approved page's facts, names, qualifications and required relationships. A geometry tool cannot authorize their deletion or substitution. The Design Spec and lock keep their existing authority; the selected scene is a realization of them.

| Role | Retained decision |
|---|---|
| Strategist / planner | Reader question, page job, claim, semantic abstraction and level of detail, functional parent meanings, comparable business units, source-grounded semantic units and relationships, required distinctions, evidence and style anchors |
| Executor / page author | Actual carrier and layout family, physical grouping geometry, reading path within the preserved semantic organization, peer alignment, native objects, coordinates and measured fit |
| Reviewer | Compare rendered explanation with the record; distinguish semantic loss, measured defects, and discretionary visual improvements |

**Reference — not a constraint**: A reference image, old scene, template or preferred prototype supplies a possible organization. Judge it against this page's question and facts. It supplies no new fact, interface, ownership, count or business outcome.

---

## 2. Explanation before allocation

**Per-page plan**: Retain concise public design decisions rather than private reasoning. In the runner, write `analysis/authoring/<stem>/plan.md` with the whole-page ASCII sketch and a mapping to scene IDs. The planner records the semantic organization, abstraction and level of detail in the slide record. The author preserves them while completing the physical realization plan.

| Order | Decision | Retained evidence |
|---|---|---|
| 1 | Reader job | Question, page job, conclusion, required facts and qualifiers with sources |
| 2 | Family and abstraction | Planner-selected explanatory unit and semantic organization; two credible organizations when unclear; author-selected carrier/layout family and its tradeoff |
| 3 | Boundary meaning | Semantic parents and what each enclosure asserts: stage, responsibility, deployment, data scope or authority |
| 4 | Reading path | Main path, comparison axes, endpoints, local splits/joins, parallel work and supporting regions |
| 5 | Peers and representations | Comparable objects and their reason; each fact as node, local list, table cell, label, annotation or qualification |
| 6 | Whole-page sketch | ASCII sketch using actual object IDs; complete fact/relationship map; visual samples for the relationship grammar |
| 7 | Measurement | Full text at locked type scale, padding, captions, notes and connector space; source preflight receipt before detailed creation |

**Hard rule**: The ASCII sketch, fact/relationship map and machine scene describe the same diagram. A realization change updates these artifacts together. A change to semantic abstraction, functional parents or compared business units returns to the record's planner. Otherwise the rendered page can answer a different question while preserving its nouns.

**Reference — not a constraint**: A useful sketch shows nesting, aligned comparisons, parallel lanes and exception paths, including supporting material. An ASCII row of labels alone does not establish the explanation.

```text
Question: How does assessment change while every required system remains visible?
Current: [intake] -> [assessment: current services] -> [settlement]
Future:  [intake] -> [assessment: liability | damage] -> [settlement]
                               ^ required consumer and exception links
Compare the same business stages; expand real implementation differences locally.
```

---

## 3. Family and meaning

**Reference — not a constraint**: Common families, rather than a closed set of allowed answers.

| Family | Meaning to preserve |
|---|---|
| Aligned comparison | Match business stages or shared criteria. Equivalent abstraction does not require equal node counts or invented symmetric components. |
| Workflow / lineage | Actual order and concurrency. Distinguish data movement, calls, access, approval and authority. |
| Service / capability architecture | Consumers, capabilities, dependencies and boundaries. Independent capabilities need no invented execution sequence. |
| Layers / nested scopes | Real dependencies or containment. Distinguish deployment, responsibility and data scope. |
| Parallel lanes | Concurrent work or distinct responsibilities; show actual rejoins when present. |
| Hybrid | One dominant explanation with named local exceptions. |

**Hard rule**: Every required individually identified connection retains identifiable endpoints and meaning. A bus or list of endpoint names does not substitute for continuous individual links when the brief requires those links.

**Reference — not a constraint**: Use a shared bus when its destinations and relationship meaning are shared. Use a scope or qualification when it carries the meaning more faithfully than a control arrow. A placement-only container can organize geometry without claiming semantic ownership.

---

## 4. Useful density and native realization

**Reference — not a constraint**: Aim for enough source-grounded role, input, output and interface context to explain the primary objects. Keep local detail subordinate to the main comparison or path. Increasing node count or filling every region is not a quality target; a complete dense brief also cannot be erased to meet a count target.

**Per-page peers**: Declare horizontal semantic peers in the scene's supported `peer_sets`. Size their common outer height to the largest measured member, align their centerline and keep consistent padding and label treatment. Widths can differ when meaning or text requires it. A parent, ingress pair, exception note or local subprocess is not automatically a peer of downstream objects.

**Hard rule**: Preserve the lock's type floors and native text ownership. Fit is resolved through source-grounded wording, allocation or a different realization within the approved page, rather than smaller type or floating duplicate text.

**Reference — not a constraint**: Local native lists and tables can carry supporting facts without another box or arrow per fact. Preserve full meaning across the page, with qualifications adjacent to the claims they limit.

**Per-page legend**: Use actual swatches of the line weight, dash, colour and arrowhead used in the diagram, paired with plain meaning labels. Compare the swatches with the emitted connections. A text-only list of “solid” or “dotted” does not show the visual grammar.

---

## 5. Independent quality questions

| Question | Evidence to inspect |
|---|---|
| Clarity | Title, parents and primary objects answer the question; compared units match; sequence and boundaries are truthful; every required fact and link can be found. |
| Useful density | Context explains what each region does and why its relationships exist; secondary details repay their reading cost; gaps are identified as gaps. |
| Visual appeal | Balanced occupied regions, a focal point, coherent semantic styles, aligned peers, deliberate proportion and spacing within the selected design system. |
| Measured fit | Full source geometry fits its region; label/route findings have explicit severity; the source evaluator's blocking constraints are resolved. |
| Native delivery | Exported objects retain native text, table/list behavior and identified connector endpoints; PowerPoint parity is inspected. |

**Validation**: Report which evidence was observed. Capacity, scene correspondence, native-object count and a pleasant preview establish different things. A warning is reviewed as a warning; readiness comes from the selected evaluator's blocking constraints and the route's final gates.

---

## 6. Scoped reference lessons

**Reference — not a constraint**: The claims comparison examples align current and future business stages and expand liability/damage detail within the future assessment stage. The MIS examples distinguish the data and reporting parents and parallel AI/scenario responsibilities when the source establishes independent work. These are transferable organizations, not fixed architectures.

**Reference — not a constraint**: Strong prior examples are accessible through the external reference library with their source SVG, fact maps and annotations. Read the image and companions together. Dense later drafts that obscured the business explanation remain counterexamples rather than positive density targets. A historical successful render is not universal proof of quality.
