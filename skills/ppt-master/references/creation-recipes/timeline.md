> See the complete [`timeline/README.md`](../../scripts/exp_svg/timeline/README.md) and [`experimental-authoring-tools.md`](../../scripts/docs/experimental-authoring-tools.md) for all request fields and flags.

# Measured Timeline Creation Reference Manual

Load for a dated timeline or Gantt with tasks, lanes, gates, dependencies, windows or note cards.

## 1. Preserve time semantics

**Hard rule**: Preserve every approved task, date, event, gate, deadline, dependency and qualification. Exact date conversion and the documented endpoint convention define the scale. A candidate fit result cannot shorten duration or silently remove work.

**Per-page plan**: Sketch the actual lanes, parallel work, milestones, dependencies and dated limits before chart allocation. Map every required item to stable request IDs. Match the page's business explanation before choosing rows or marker bands.

**Reference — not a constraint**: Use the dated dense creator for wrapped labels, lane events, stacked gate/milestone names, windows, beyond-horizon spans and dependencies between items. `timeline_layout.py` remains available for the original numeric-horizon spec. Both produce the hashed `data-layout="timeline_layout"` group that the canonical lint recognizes.

---

## 2. Allocate the whole page

**Per-page style**: Use locked fonts and type floors, a readable labelled-bar padding floor, native text ownership and named bars. Keep decisions, deliverables and deadlines labelled at their time marks. Use actual visual samples when a legend explains encoding. [`consulting-typesetting.md`](../consulting-typesetting.md) §6 governs the label treatment.

**Reference — not a constraint**: Chart `bounds` can occupy a finite positive subset of the fixed page body. Reserve a supporting region when notes materially help the page's explanation. The whole-page receipt includes this support rather than measuring the chart alone.

| Need | Tool |
|---|---|
| Measured whole-page note cards | `exp_svg/timeline/prepare_note_cards.py --help`, before timeline preflight |
| Whole-page capacity | `exp_svg/capacity_preflight.py --family timeline --in request.json --out preflight.json --contract contract.json --workspace <project>` |
| Alternate permitted allocation | `exp_svg/fit_candidates.py --help` |
| Native full-page compilation | `exp_svg/guided_build.py --family timeline --in request.json --out build.json --page <project>/svg_output/<stem>.svg --preflight-receipt preflight.json --contract contract.json --workspace <project>` |

**Validation**: Inspect the binding capacity constraint, event packing, chart bounds, complete labels and note-card space before creation. The helper does not drop content to reach `ok`. Fit proves allocation, while the rendered chart still needs semantic and visual inspection.

---

## 3. Rebuild from one source

**Hard rule**: Change the source request and regenerate its hashed timeline group. A direct coordinate edit produces `TIMELINE_HAND_EDITED`; an untracked manually drawn Gantt produces `TIMELINE_NOT_FROM_HELPER`. Keep the source request and build receipt beside the page's plan.

**Per-page review**: Render through `page_review.py`, inspect exact dates and dependency targets, resolve certain findings and review flagged ones through the selected profile. Use the same canonical native-PPTX export, text-in-shapes adoption and PowerPoint parity inspection as other pages.
