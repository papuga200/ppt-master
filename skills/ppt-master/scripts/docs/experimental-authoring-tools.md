# Experimental measured authoring tools

These tools ship inside the installed skill. They consume current local JSON
and font/template resources; no experiment directory, private campaign fixture,
model call, or network request is needed. Architecture request grammar lives in
[`../exp_svg/arch/README.md`](../exp_svg/arch/README.md); timeline grammar lives in
[`../exp_svg/timeline/README.md`](../exp_svg/timeline/README.md).

## Portable contract

`guided_measure.py`, `capacity_preflight.py`, `guided_build.py`, and
`fit_candidates.py` accept `--contract <canvas.json>` and optional
`--workspace <absolute-project>`. With a workspace, source and output paths must
stay inside it. Without it, explicit paths work independently of repository
location. `PPT_MASTER_PROJECT_PATH` remains a workspace fallback; absent an
explicit contract, the legacy location is `<workspace>/inputs/fixture/canvas.json`.

```json
{
  "template": "content.svg",
  "body_zone": {"x": 64, "y": 208, "w": 1152, "h": 440},
  "type_floors": {"label_px_min": 14, "body_px_min": 16,
                  "timeline_chart_label_px_min": 14},
  "native_editability_required": true,
  "source_layout_preflight_required": true,
  "layout_constraints": {"labelled_bar_padding_y_min_px": 8}
}
```

Relative `template` resolves beside the contract. With no `template` field,
`template/content.svg` beside the contract is retained for legacy fixtures.
`page.template` must equal the resolved template, and `page.body` must exactly
equal `body_zone`; body fitting overrides are forbidden. Contract floors reject
explicit undersized text roles and raise omitted architecture defaults to the
label floor. Native ownership sets architecture `node_text: combined` and
`native_text_ownership: true` for both creators. Historical `first_draft_only`
freezes an existing page and requires a matching preflight; ordinary canonical
authoring can revise pages. Source geometry preflight remains required whenever
`source_layout_preflight_required` is set, including revisions.
Explicit-contract preflights retain raw request, contract-file and normalized
request fingerprints. Builds reject a stale contract or altered normalization;
remeasure rather than reusing an earlier readiness decision.

## Callable tools

Invoke each through its concrete installed scripts path. Outputs are UTF-8 JSON;
stdout gives a concise view or artifact reference, while complete evidence stays
on disk. `--help` writes no files. Paths below start at the installed scripts root.

| Tool | Inputs and outputs |
|---|---|
| `exp_svg/arch/measure_labels.py` | `--in labels.json --out measured.json`; request-only font/wrap measurement, optional browser verification |
| `exp_svg/guided_measure.py` | `--in labels.json --out measured.json --contract canvas.json`; contract role floors, provenance retained in `.summary.json` |
| `exp_svg/arch/measure_groups.py` | `--in architecture.json --out groups.json`; complete group capacity ledger, requested spacing only |
| `exp_svg/capacity_preflight.py` | `--family architecture\|timeline --in request.json --out preflight.json --contract canvas.json`; no SVG |
| `exp_svg/guided_build.py` | Above arguments plus `--page svg_output/NN_page.svg --preflight-receipt preflight.json`; creator receipt and resolved `.request.json`/`.contract.json` |
| `exp_svg/fit_candidates.py` | `--in architecture.json --out-dir NEW --contract canvas.json [--allow-gaps] [--allow-node-widths]`; at most 27 combinations, selected request + matching `preflight.json` |
| `exp_svg/timeline/prepare_note_cards.py` | `--in timeline.json --out prepared.json --receipt cards.json [--contract canvas.json --workspace PROJECT]`; measured horizontal note strip, no SVG |
| `exp_svg/arch/attachment_candidates.py` | `--in architecture.json --edge ID --out NEW --allow-adapt-sides`; at most 18 pairs for one optional edge |
| `exp_svg/arch/local_frame_candidates.py` | `--in architecture.json --zone ID` (repeatable) `--step-px 4 --out NEW --allow-adapt-frames`; baseline plus four single-coordinate trials per selected zone |
| `exp_svg/arch/route_order_candidates.py` | `--in architecture.json --out NEW`; at most six deterministic edge processing orders |
| `exp_svg/arch/port_clearance.py` | `--request architecture.json --receipt evaluation.json [--edge ID] --out exits.json`; endpoint exits only, no complete-route proof |
| `exp_svg/arch/receipt_summary.py` | `--in evaluation.json [--ids ID ...] [--out view.json]`; retains every finding and original readiness, filters geometry only |
| `exp_svg/arch/organization_check.py` | `--plan mapping.json --request architecture.json [--receipt evaluation.json] --out correspondence.json`; read-only declared membership/order diagnostics |
| `exp_svg/inspect/native_editability.py` | `--svg page.svg [--pptx one-slide.pptx] --out ownership.json`; declared semantic shapes/lists/tables and architecture nodes |

The three architecture searches write `selected-request.json`,
`selected-receipt.json`, `summary.json`, and `trials-full.json` to a new directory.
They never emit SVG. Search budgets depend on the finite candidate input set,
without a model wall-clock deadline. Only explicitly authorized optional geometry
can vary; text, source relationships, membership, facts and identity remain exact.
Unspecified attachment sides use the router's normal automatic choice. Set sides
only for real semantic/brief constraints; do not invent a side quota.

## Readiness and delivery evidence

`compose_page.evaluate` is the architecture readiness authority. Wrappers and
searches consume `ready` and `delivery_state`; they do not reinterpret residual
lists. `spacing_tightened` remains a warning. Unknown residuals block. Raw
`page.extra_svg` yields incomplete coverage and requires external geometry
auditing rather than a fabricated helper certificate. A measured bespoke SVG
route remains possible under its explicit audit and canonical export gates.

Group ledgers and font measurement are diagnostic evidence, not route or export
acceptance. Remeasure after changing text, fonts, wraps, frames or layout. The
group ledger does not run the density ladder; full preflight and build do.

Timeline `bounds` is an explicit positive finite chart rectangle inside the full
immutable body. Omitted/null/`"auto"` uses the full body. A separate note strip
must fit below the chart without overlap. `page.note_cards` has `strip: {x,y,w,h}`
spanning body width and exactly three `cards: [{id, heading, text}, ...]`; IDs are
unique lowercase SVG-safe names. Cards use measured 16 px text, 21 px line pitch,
14 px padding/gaps, and one semantic shape owner each. The helper rejects
insufficient space or oversized words instead of deleting text. Arbitrary extras
and collisions with page texts still need inspection. Pass the contract when
preparing cards: body floors above 16 px are explicitly unsupported by this
fixed helper. Prepared requests retain their 16 px body floor so subsequent
contract normalization also rejects an incompatible raised floor.

Organization plans use `page_job`, `reading_direction`, optional `groups` with
`id`, `parent`, `visible`, `role`, `members`, `ungrouped_nodes`, and optional
`primary_stages` (arrays of IDs). Directions include left/right, top/bottom,
parallel and nonlinear readings. Sequence checks apply only to declared ordered
stages; comparisons and layers need no invented stages or boundaries. Missing
descriptive mappings warn; contradictions in declared membership are errors.
This check never changes composer readiness.

Native auditing verifies one shape owns its geometry and editable text, one list
owns editable native paragraphs/bullets, and a table exports as a real `a:tbl`
with matching cell text. PPTX evidence requires a one-slide export and unique
stable object names. Source-only results leave export ownership unverified.
Unmarked semantic objects, visual parity, exact fitting and factual accuracy
are outside this bounded audit. Run the canonical checker and real exporter;
passing a synthetic test or source receipt alone is insufficient delivery proof.
