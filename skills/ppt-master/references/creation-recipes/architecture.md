> See [`diagram-planning.md`](../diagram-planning.md) before allocation and the complete [`arch/README.md`](../../scripts/exp_svg/arch/README.md) before writing a scene.

# Measured Architecture Creation Reference Manual

Load for architecture, system comparisons, operating models or flows that benefit from measured groups and native scene compilation.

## 1. Organize the explanation

**Per-page plan**: Read the record's semantic abstraction, level of detail, functional parents and compared business stages before allocating groups. Select the actual carrier/layout family within that organization. Retain the whole-page ASCII sketch, required fact/relationship mapping, actual sequence or parallelism, peer sets and relationship grammar in the authoring workspace. Keep implementation differences inside the shared comparison stages.

**Reference — not a constraint**: Start with automatic attachment sides. Explicit sides express actual ingress/egress or another semantic condition. A fixed attachment preference without semantic need can exhaust otherwise usable route space.

**Per-page style**: Derive font, sizes, paint, line weights and cue meanings from the lock and template. Declare horizontal semantic peers with common outer height and centerline. Use the scene's native text ownership and combined node text for shape-owned labels. Show legends with actual visual samples.

---

## 2. Measure before creation

| Need | Tool |
|---|---|
| Label width / wrapping without constructing a scene | `exp_svg/arch/measure_labels.py --in labels.json --out labels.receipt.json` |
| Whole-group capacity including captions, padding and descendants | `exp_svg/arch/measure_groups.py --in scene.json --out group-space.json` |
| Complete source geometry, capacity and routes | `exp_svg/capacity_preflight.py --family architecture --in scene.json --out preflight.json --contract contract.json --workspace <project>` |
| Compact view of residuals without losing the full receipt | `exp_svg/arch/receipt_summary.py --in <architecture-evaluation.json>` |
| Plan memberships / reading order correspondence | `exp_svg/arch/organization_check.py --plan <plan.json> --request scene.json --receipt <architecture-evaluation.json> --out organization.json` |

**Validation**: Read the complete source evaluator's `ready`, `delivery_state` and `blocking_constraints`. Measurements include space used by captions, descendants and padding. An attractive small preview or a text-only fit estimate does not prove routing fit. The correspondence checker proves declared mapping, not that the selected explanation is appropriate.

---

## 3. Resolve the measured constraint

**Reference — not a constraint**: Select a candidate tool for a finding it can affect; these tools propose request variants and retain full trial evidence. They emit no final SVG. The source evaluator remains the readiness authority.

| Finding | Candidate capability |
|---|---|
| Allocation or group-space pressure | `exp_svg/fit_candidates.py` for allowed gaps/widths; `exp_svg/arch/local_frame_candidates.py` for local frames |
| Endpoint-side pressure | `exp_svg/arch/attachment_candidates.py` |
| Route-order pressure | `exp_svg/arch/route_order_candidates.py` |
| Port corridor / clearance uncertainty | `exp_svg/arch/port_clearance.py` |

**Per-page candidates**: Use a new output directory for each search and inspect `selected-request.json`, `selected-receipt.json`, `summary.json` and `trials-full.json`. Adopt a candidate only when its semantic map, declared peer policy and style remain faithful. A local change does not authorize a new business sequence or omitted relationship.

---

## 4. Compile and review

```text
run_script exp_svg/guided_build.py --family architecture --in scene.json --out build.json --page <project>/svg_output/<stem>.svg --preflight-receipt preflight.json --contract contract.json --workspace <project>
run_script page_review.py render <project> <stem>
```

**Validation**: The scene, ASCII sketch and fact/relationship map correspond to the actual image. Inspect direction, target contact, labels, boundary meaning, peer heights, captions and native ownership before the profile's independent review. Geometry warnings remain visible for judgement; resolve measured blockers without suppressing them. After a change regenerate from the selected request and repeat the affected checks.
