# Canonical PPT Master fork

Maintained 2026-10-03. This fork integrates the experimental measured SVG creators with the consulting-quality full-deck runner. The earlier Deck Builder repository is retired; its semantic engine is not the production generator here.

## Runtime

`hosts/responses_api/deck_runner.py` owns source-asset intake, solution, narrative/slide planning, template preparation, parallel page authors, fresh reviews, ordinary bounded repair, native export and PowerPoint parity. `skills/ppt-master/SKILL.md`, Default Generate, the consulting-quality profile, Design Spec and execution lock retain authority. Full client sources, model transcripts, reference decks and generated jobs remain local ignored data rather than public repository content.

`hosts/responses_api/route_profiles/sol61_xhigh_subscription.json` selects GPT6.1Sol at extra-high for both tiers. Pass it as both authors and reviewers to use that model for every stage. The same family reviewer is a fresh independent session; this is a user-selected route, not cross-family verification. Subscription authentication remains required; keys are scrubbed rather than silently billed.

```powershell
$env:PPT_MASTER_REFERENCE_LIBRARY = '<absolute external reference-library folder>'
python hosts/responses_api/deck_runner.py projects/<project> --session <name> --authors hosts/responses_api/route_profiles/sol61_xhigh_subscription.json --reviewers hosts/responses_api/route_profiles/sol61_xhigh_subscription.json --planner-effort xhigh --max-parallel 4
```

Initialize/import source files with `project_manager.py` first. Planning and design confirmations are delegated only when the user explicitly delegates those choices. Original optional creator craft packs can be supplied beneath project resources with an `analysis/creation-resources/catalog.md`; the approved facts, style and native export rules take precedence. The external reference library can pair images with faithful source SVGs/maps, plan and annotations; `reference_library.py companion` returns complete companion text through the host.

## Gain retention

| Gain | Canonical owner and qualification |
|---|---|
| Purpose/semantic abstraction before coordinates; comparable business stages | `references/diagram-planning.md`, actual planner input and slide records; layout realization remains the author’s decision within that organization |
| ASCII plus programmatic scene and faithful examples | Page author workspace, creation recipes and reference companions; reference assets remain external |
| Measured group/label capacity and one readiness rule | `scripts/exp_svg/arch/` and guided measurement/build; warnings remain distinct from blockers |
| Peer geometry, local fit/routing candidates and free-side routing | Measured architecture helpers and reusable candidate tools; restricted ports require a semantic reason |
| Date-proportional timelines and horizontal note cards | `scripts/exp_svg/timeline/`; original simple timeline route retained |
| Shape-owned text, native lists/tables, soft-break preservation | Authoring SVG contract, finalizer, native exporter and text-in-shapes pass; inspect the actual exported objects |
| Lossless large tool results and reachable resources | Responses/MCP hosts preserve oversized output in retrievable artifacts; full contracts remain discoverable |
| Exposed reasoning diagnostics and token/cost evidence | CLI host/diagnostic sidecars and per-request subscription estimates; no private reasoning is decoded |
| Existing images, charts, icon/shape vocabulary and export safeguards | Original core capabilities remain; template and native chart/table regressions are included in verification |

## Evidence and limitations

Integration verification and the two full business-deck runs are recorded separately. Earlier experiments are historical evidence, including failures and rejected over-dense drafts; they do not establish consistent quality or a fifteen-minute target. A passing geometry receipt does not establish semantic fidelity, attractive composition, complete connector attachment or PowerPoint visual parity. Native fallback exports are reported as a loss of that native capability. Provider tokens price a standard API-equivalent estimate; actual subscription usage has no per-call API invoice. Service-tier surcharges are not inferred. Unknown prices remain unknown.

The experimental namespace is retained for compatibility. It identifies measured helper implementation lineage, not an alternative pipeline that bypasses the canonical SVG source, roster, checker or export gates. Production gains must be exercised by the full runner rather than by copying helper files alone.

Planning-side CLI conversations that stop at their tool-call ceiling are retained
as pending. The runner resumes that same conversation before accepting the stage's
handoff, including after a runner restart. Each continuation retains cumulative
usage and adds its own telemetry event. Failed invocations stop rather than being
treated as successful continuations. This recovery does not enlarge page-author
repair budgets or add a model wall-clock deadline.

The text-in-shapes export pass also attaches native connectors to the four real
vertices of `diamond` and `flowChartDecision` shapes. Bounding-box corners and
arbitrary points on sloping edges are deliberately excluded: attaching those to
a different native site would change the authored route. Six focused decision
connector tests and four existing connector/text-host tests passed. A retained
16-slide PowerPoint comparison gained three fully attached connectors with no
ink movement above two pixels. This is a narrow export correction, not proof
that every diagram connector is fully attached; table endpoints, unsupported
ports and complex return routes still require inspection.

Native bulleted paragraphs whose authors drew wrapped continuation lines as
separate SVG texts now retain those lines in their original native paragraph.
Hanging indentation, mixed emphasis and explicit breaks/custom tabs preserve
the authored positions; neighbouring items then share one editable list frame.
The correction excludes other columns, new headings, markers and painted row
separators. Eight focused tests passed. In the retained twelve-slide actual
PowerPoint comparison, the two affected lists became complete native lists
with no ink movement above two pixels; nine chart/data package parts were
unchanged. The retained Meridian package matched the earlier exporter in all
fifty parts. This does not certify every list or arbitrary text grouping.
