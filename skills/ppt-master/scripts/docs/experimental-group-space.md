# Experimental architecture group space

Run `exp_svg/arch/measure_groups.py` on the **full architecture compose request**
before authoring or resizing a group:

```bash
python3 scripts/exp_svg/arch/measure_groups.py --in architecture.json --out group-space.json
```

The UTF-8 JSON ledger reports all zones (including layout-only groups and the
root body), their outer frames, inner capacities, heading lines and measured
bands, heading gap, padding and complete insets. `content` is the measured
layout extent at the final node wrap selected by primitive arrangement.
`minimum_outer` adds those insets and also accommodates the measured heading
width; `deficit` is the positive difference from the supplied outer dimensions,
in pixels rounded to two decimals. `children` identifies each contributing
child size. `culprit_child_ids` identifies children actually crossing the inner
boundary after placement; it is evidence of overflow, not an attribution of
which child should be removed. Heading width failure has its own flag.

`frame_source` distinguishes `supplied_fixed`, `content_sized`, and `page_body`.
For a content-sized group, its outer dimensions are inferred evidence rather
than an authored constraint. `kind: "group"` follows compose semantics: its
heading is suppressed and its default padding is zero. Other zones keep their
measured, potentially wrapped headings. Empty headings consume no heading gap.
For zones without layouts, the content extent is the union of placed direct
children. This is a size budget; an offset child can cross a boundary even when
that union could fit after translation.

For the retained insurance `current` group, a 90 px outer height leaves 39.8 px
inside after a one-line 18.2 px heading, 8 px heading gap and 12 px padding on
each side. Its nodes require 57.6 px, so the minimum outer height is 107.8 px
and the height deficit is 17.8 px. The ledger makes this available without
producing an SVG.

The aid uses public `page_compose.compose`, `arrange.arrange`, scene measurement
and `arrange.layout_extent`; internal `compose_page._install_root` and
`arrange._grid_lists` supply the existing compose root/group adapter and layout
enumeration. It adds no layout engine. It deep-copies the request, reads the
template/fonts, and writes only the requested `.json` ledger. It rejects an
output path equal to its request or input resources. The Python function
`measure_groups(request)` writes no files.

Scope is **requested spacing**, including primitive node-wrap attempts, uniform
sizes, nested groups, spacers and reserved flow-label gaps. It does not try the
composer's density ladder, route edges or render a page. Bus slots retain the
composer's spacer dimensions, but bus-route feasibility is not evaluated.
The existing font measurement is approximate glyph-advance measurement (or its
existing estimator fallback), not a browser verification. `font_evidence`
reports the normal/bold font source, resolved file and measurement backend.
This ledger proves
no route, aesthetic, native-editability or export checks. A larger minimum
frame can change heading wrapping, parent capacity or routes; remeasure the
edited request and run the ordinary compose and delivery checks.

## Aligned grids and wide singleton rows

`layout.align_columns: true` shares column widths across **all** rows. Each
column takes its widest member, so a wide single-item row enlarges column one;
it does not span the other columns. For example, two 220 px nodes with a 32 px
gap need 472 px. Appending a 472 px singleton to that aligned grid makes its
total width 472 + 32 + 220 = 724 px. Turn off column alignment for independently
centred rows, or use a separate layout group for the wide note when consistent
columns are meaningful. Preserve all text and relationships.

For aligned layouts the ledger includes `alignment_diagnostic`, showing the
extent without column alignment and the extra width/height induced by global
slots. For `type: columns` the axes are swapped and the extra can be height.
This is an explanatory comparison, not an automatic layout edit or a routing
proof. Measure the **latest complete labels and layout**, including any added
notes, before accepting its frames; an earlier skeleton ledger becomes stale
when either changes.
