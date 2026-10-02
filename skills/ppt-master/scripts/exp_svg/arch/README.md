# Measured architecture scene authoring

The installed architecture helpers measure named semantic objects, place them,
route declared relationships, and emit natively editable SVG-to-PPTX pages.
Choose groups, composition and relationships from actual source meaning.
Nodes may stay ungrouped; rows, columns, layers, comparisons, capability maps,
local fixed coordinates, annotations and buses are available. The grammar below
describes tool inputs, not a required visual recipe.

## Complete page request

All dimensions are slide pixels. IDs are globally unique across zones, nodes,
ordinary edges, annotations and the optional legend. Source and target references
must exist. Strings keep exact source content. Resources use explicit local paths.

```json
{
  "page": {"template": "/project/templates/content.svg",
           "body": {"x": 64, "y": 208, "w": 1152, "h": 440},
           "texts": [{"id": "title", "text": "Measured architecture",
                      "x": 64, "baseline": 110, "size_px": 32,
                      "weight": "bold", "max_w": 1080, "max_lines": 2}]},
  "font": {"family": "Segoe UI"},
  "type": {"node_px": 16, "sub_px": 14, "edge_label_px": 14,
           "zone_label_px": 14, "legend_px": 14, "annotation_px": 16},
  "style": {"native_text_ownership": true, "node_text": "combined"},
  "nodes": [{"id": "a", "label": "Source", "sublabel": "Local records"},
            {"id": "b", "label": "Service"}],
  "root": {"layout": {"type": "rows", "rows": [["a", "b"]], "gap_x": 140}},
  "edges": [{"id": "ab", "source": "a", "target": "b", "label": "Requests", "kind": "sync"}]
}
```

`page.template` supplies a complete SVG root and a direct/nested
`<g id="chrome">...</g>` copied verbatim; `chrome_group_id` can name another
group. Set its canvas and root language to match the project. `page.body` owns
the full content rectangle. `page.texts` contains required `id`, `text`, `x`,
`baseline`, `size_px`, plus optional `weight`, `anchor` (`start/middle/end`),
`fill`, `max_w`, `max_lines`, `line_pitch_px`, `wrap` (`balanced/greedy`),
`baseline_of: last`, `style`, `role`, and `edge` (`top/bottom` for body fitting).
`font_files` on page supplies normal/bold fonts for page text. Standalone
`page_compose` supports `body.fit: between_texts` with its margins, but a
contract-guided request uses the exact immutable body. `page.extra_svg` accepts
well-formed supported SVG as a bespoke extension and explicitly excludes those
objects from helper geometry coverage.

## Scene vocabulary

| Object | Supported authored fields and behavior |
|---|---|
| Scene | optional `schema: exp_svg.arch.scene/v1`, `canvas: {w,h}`, `region: {x,y,w,h}` (full-page compose replaces it with body), `font: {family, files:{normal,bold}}`, `type`, `style`, `node_max_w`, `node_pad:[x,y]`, `caption_gap`, `density_ladder`, `zones`, `nodes`, `edges`, `annotations`, `legend`, `constraints`, `peer_sets`, `buses`, `root` |
| Node | `id`, `label`, optional `sublabel`, `zone`, `kind`, `min_w`, `min_h`, `max_w` (legacy outer wrap budget), or `wrap_width_px` (explicit text wrap budget, mutually exclusive with `max_w`), `at:{x,y}` or placement constraints; labels and padding measure their own frame |
| Zone | `id`, optional `label`, `kind` (`region`, `trust`, `group`, or a declared `style.zone_kinds` key), `parent`, `frame:{x,y,w,h}` for a fixed boundary, `at:{x,y}`, `pad`, `caption_max_w`, `layout`; a content-sized zone omits frame, `kind:group` suppresses caption and defaults padding to zero |
| Layout | `type:rows` with `rows:[[IDs],...]`; `type:columns` with `columns:[[IDs],...]`; `type:grid` with `items:[IDs]`, numeric `columns`; optional `gap_x`, `gap_y`, `justify`/`justify_rows` (`start`, `center`, `space-between`, `space-evenly`), `align_columns`, `uniform`, `reserve_label_gaps`, `label_gaps:{"a\|b":px}` |
| Root | `layout` over the full body; may list top-level zones, ungrouped nodes, annotation/legend IDs and buses. Zone layouts list their direct children. Parent/zone ownership must match layout membership. |
| Edge | `id`, `source`, `target`, optional `label`, `label_max_w`, `kind` (default `sync`), `source_side`, `target_side` (`N/E/S/W`), routing engine options through `route_connections.py`; omit sides for automatic routing. Labels are measured and preserved. |
| Bus | `id`, optional `kind`; reserve its ID in a layout between source/target columns. Flows are ordinary declared edges `node -> bus` or `bus -> node`. Branches are straight horizontal runs into a vertical trunk; blocked branches report failure. |
| Annotation | `id`, `text`, optional `role` (`body/label`), `max_w`, `weight`, `fill`, `italic`, `at:{x,y}`; or `attach:{to:ID,side:N/E/S/W,gap:px,align:start/center/end}`. May occupy a root/group layout slot. |
| Legend | optional `id` (defaults `legend`), `title`, `max_w`, `at:{x,y}` or `dock:top/bottom`, `items:[{text,kind}]` for edge samples or `{text,zone_kind}` for boundaries. Samples use the same style tables as rendered objects. |
| Peer set | `ids:[node IDs]`, `equal_height:true`, `axis:horizontal`, `align:centerline`; at least two members, one set per node. Equal measured heights retain individual widths. Actual centerline and height disagreement appears in placement findings. See [peer sizing](../../docs/experimental-peer-sizing.md). |

`align_columns` gives each global column its widest member; a wide singleton
enlarges its column rather than spanning all columns. `uniform` shares both
node width and height inside one layout; semantic peer sizing shares only
height across its declared node set. Insets include measured captions and gaps.
See [group space](../../docs/experimental-group-space.md) before fixing group frames.

`type` keys are `node_px`, `sub_px`, `edge_label_px`, `zone_label_px`,
`annotation_px`, `legend_px`. Library defaults are 16 px for nodes/annotations
and 13.333 px for other roles; contract-guided normalization raises omitted roles
to the project's floor. No helper reduces fonts to manufacture a fit.

`style` supports `text`, `muted`, `node_fill`, `node_stroke`,
`node_stroke_width`, `node_radius`, `label_bg`, `node_text`
(`separate/single/combined`), `native_text_ownership`, `node_kinds` with
`fill/stroke/width/dash/text`, `zone_kinds` with `fill/stroke/width/dash/text`,
and `edge_kinds` with `stroke/width/dash/head`. Built-in node kinds are
`external/datastore`, zone kinds `region/trust/group`, edge kinds
`sync/async/control/association`. Custom kinds need a matching style entry.
`native_text_ownership:true` emits one semantic shape and one editable text
component for each node. Keep combined text for label plus sublabel ownership.

`constraints` run in authored order. `place` uses `id,x,y`; relative
`right_of/left_of/below/above` use `id,of,gap,align`; `align` uses `ids,edge`
(`left/right/top/bottom/cx/cy`), `to` (placed ID or numeric coordinate);
`distribute` uses `ids,axis:x/y` and `span:[start,end]` or `start,gap`;
`same_size` uses `ids,dims:w/h/both`. References must already be placed.
Moving a parent translates descendants. Measured node sizing and semantic
peer sizing are preferable to late `same_size` when parent capacity matters.

## Public entry points and evidence

Use the installed absolute script paths and explicit request/output paths.
The recommended contract sequence and optional bounded search/inspection tools
are documented in [experimental authoring tools](../../docs/experimental-authoring-tools.md).

1. Measure labels (`measure_labels.py`) and full group budgets (`measure_groups.py`) when the page needs them.
2. Evaluate the full candidate with `capacity_preflight.py --family architecture --contract ...`.
3. Resolve its `blocking_constraints`; warnings preserve readiness. Optional bounded searches require their declared geometry authorization.
4. Build with `guided_build.py --family architecture --contract ... --preflight-receipt ... --page ...`.
5. Run the canonical checker, real SVG-to-PPTX export, visual inspection, and bounded native ownership audit.

Direct `compose_page.py --in REQUEST --out RECEIPT --evaluate-only` produces
the full evaluator envelope without SVG. Without `--evaluate-only`, add
`--page OUTPUT.svg`. `arrange.py` accepts the scene without page/root wrappers,
`--engine primitive/elk`; `route_connections.py` routes a placed scene with
`--engine orthogonal/libavoid`; `move_group.py` consumes a scene plus its move
request. All three support `--in`, `--out`, optional `--svg`. ELK needs the
existing Node backend and rejects peer declarations; libavoid is optional.
The ordinary primitive/orthogonal whole-page path uses no model.

Receipts retain measured objects/boxes/label boxes, routes, endpoint bindings,
bus paths, spacing scale, original findings and coverage. The composer owns
`ready`/`delivery_state`; helper geometry acceptance does not prove facts,
visual judgment or native export. Raw extensions retain a bespoke authoring
path with incomplete helper coverage and explicit external geometry auditing.
