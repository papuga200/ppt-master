> See [`executor-base.md`](./executor-base.md) for the complete authoring vocabulary and [`diagram-planning.md`](./diagram-planning.md) for diagram decisions.

# SVG Creation Tools Reference Manual

Discover construction capabilities before choosing a page realization; load the matching complete recipe and tool contract at its observable trigger.

## 1. Capability menu

**Reference — not a constraint**: These capabilities coexist with the complete SVG, preset, Boolean, topology, chart, table, image, typography and effects contracts already loaded or routed by the Executor. The menu selects no palette, style, scene density or node count.

| Observable trigger | Capability and complete material to load |
|---|---|
| Architecture, operating model, system comparison or a flow with measured groups | [`creation-recipes/architecture.md`](./creation-recipes/architecture.md), then [`arch/README.md`](../scripts/exp_svg/arch/README.md) and [`experimental-authoring-tools.md`](../scripts/docs/experimental-authoring-tools.md) |
| Timeline / Gantt with dates, lanes, gates, windows, deadlines or dependencies | [`creation-recipes/timeline.md`](./creation-recipes/timeline.md), then the full [`timeline/README.md`](../scripts/exp_svg/timeline/README.md) and [`experimental-authoring-tools.md`](../scripts/docs/experimental-authoring-tools.md) |
| A conventional flow or hierarchy suited to an ELK fragment | Existing `diagram_layout.py --help`; retain the Diagram contract in [`diagram-clarity.md`](./diagram-clarity.md) |
| A timeline using numeric horizon units and the original source spec | Existing `timeline_layout.py --help`; retain [`consulting-typesetting.md`](./consulting-typesetting.md) §6 |
| A native contour or shape combination | [`native-shape-authoring.md`](./native-shape-authoring.md), [`preset-shape-vocabulary.md`](./preset-shape-vocabulary.md), [`topology-assembly.md`](./topology-assembly.md) |
| A chart, table, list, image or ordinary SVG page | Existing corresponding Executor modules; [`consulting-typesetting.md`](./consulting-typesetting.md) for editable lists/tables and shape-owned text |
| A source layout that fits but has route, port or local allocation findings | The architecture recipe's candidate tools; full receipts remain available through `receipt_summary.py --help` |

**When to run**: Read the matching recipe and linked full contracts before the first request using that capability. Use `run_script <script path> --help` for current flags. A helper's name or a short catalog description is not its full schema.

---

## 2. Source and compiler

**Hard rule**: Choose one authoritative creation source for the page. For a measured scene page this is its request JSON; for a hand-authored page it is the SVG plus any independently hashed helper group source. Geometry fixes to a scene page update the request and regenerate it. Parallel edits to the generated SVG would disconnect review from the source used at the next regeneration.

**Per-page workspace**: In the deck runner use `analysis/authoring/<stem>/` for `plan.md`, the fact/relationship map, scene requests, measurements and candidate receipts. Its `contract.json` is projected by the runner from the actual template body-zone and locked floors. Pass `--contract <contract.json> --workspace <project>` to portable guided tools. The author chooses semantics and paint; the compiler materializes those choices.

**Validation**: The whole-page measured creators currently use a 1280 × 720 canvas. For another canvas or a template without a declared body-zone, the page job identifies the missing contract and the ordinary SVG route remains available.

**Reference — not a constraint**: The measured architecture route supports native text ownership, semantic peer sizing, nested or placement-only zones, explicit connector meanings, captions, notes and visual legends. The dated timeline route supports exact date conversion, wrapped task labels, stacked events, gates, dependencies, windows, beyond-horizon spans, chart allocation and note cards. Read their full vocabularies before discarding a capability as unavailable.

---

## 3. References with inspectable companions

```text
run_script reference_library.py match --form architecture --need "matched current and future stages"
run_script reference_library.py show <id> --project <project> --page <stem>
run_script reference_library.py companion <id> --kind annotations --project <project> --page <stem>
run_script reference_library.py companion <id> --kind fact_map --project <project> --page <stem>
run_script reference_library.py companion <id> --kind source_svg --project <project> --page <stem>
```

**Per-page reference**: Inspect the delivered image and the listed companions relevant to the borrowed technique. `source_svg`, `scene`, `fact_map`, `plan`, `annotations` and `recipe` are optional companion kinds. The companion command returns complete UTF-8 content even when the external library is outside the host file-reading root. Older image-only entries retain their existing behavior.

**Hard rule**: Borrow organization and devices within the approved style. Reference facts, wording, counts, branding and private teacher assets never become deck content. The external library stays external to this repository and the export.
