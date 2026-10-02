# Experimental architecture peer sizing

The primitive architecture arranger accepts explicit scene-level semantic peers:

```json
{
  "peer_sets": [
    {
      "ids": ["left-service", "right-service"],
      "equal_height": true,
      "axis": "horizontal",
      "align": "centerline"
    }
  ]
}
```

Declare peers only when the source comparison establishes their correspondence.
The array is optional. Each set requires at least two existing node IDs, with
no duplicates within or across sets. Zone IDs are invalid. The shown values of
`equal_height`, `axis` and `align` are required; other variants are unsupported.
Invalid declarations raise an actionable `HelperError`. ELK rejects declarations
because its backend replaces measured frames; use the primitive engine.

`exp_svg/arch/scene.py` measures every declared member from current labels,
sublabels, font sizes, padding and wrap budgets. The common height is the maximum
of each member's padded measured height and authored `min_h`. Original wrap
budgets at scale 1 supply a common floor even when a wider wrap is requested.
Selected tighter wraps can increase the height. Widths retain each member's own
measurement and `min_w`; this feature never copies widths, changes font sizes,
rewrites labels or adds a legend. An existing `layout.uniform` still has its own
width-sharing behavior, so omit it when unequal peer widths are intended.

`scene.size_node(scene, node, wrap_scale=1.0)` updates the normalized working
scene's declared members, including frame and inner-height metrics. Members
retain their own selected wrap scales in `measure.wrap_scale`. Baseline and
current measurements are rebuilt instead of trusting cached text metrics.
`scene.normalize(input)` returns a deep copy; `arrange.arrange(input)` preserves
the caller's request. Measurement evidence includes `measure.peer_height_px`.

`exp_svg/arch/arrange.py` repeats its existing primitive size pass before
placement when a later parent increases a peer set's common height. Each
completed pass supplies a monotone floor for the next pass; rejected wrap trials
do not themselves become floors. All existing parents and capacity checks are
remeasured against that floor. The finite wrap ladder and finite measured
heights make this converge without a model call. A floor needed by an earlier
selected wrap can remain after later sizing changes, so the result may contain
extra vertical padding. It is never a promise that a fixed frame will fit.

`align: "centerline"` records the intended correspondence; peer sizing does not
move cross-zone objects. Use existing row layouts and positional constraints to
establish centerlines. Parent captions, insets and frame origins can still
offset corresponding centers. Placement checks report `peer_centerline_mismatch`
above 0.5 px and `peer_height_mismatch` above 0.1 px. The ordinary full-page
evaluator owns the resulting readiness decision. This sizing aid alone proves
neither alignment nor route, aesthetics, export or native-editability checks.
