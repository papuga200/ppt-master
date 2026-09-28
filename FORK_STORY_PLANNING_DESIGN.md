# Story-first planning for PPT Master

**Status:** Uncommitted prototype in the consulting-quality runner and shared planning guidance. The same-input self-documentation rerun completed on 25 September 2026; its deck-level review found material gaps. Keep the detailed-planning baseline available until targeted page comparisons establish the right granularity.

**Priority clarification:** The user values slide substance, visual clarity and unaided communication above speaker notes. The consulting runner now defaults §X notes to disabled unless requested, and its export writes plan-derived notes only when §X explicitly enables them. The earlier test exports included notes because their plans predate this clarification; those notes are not evidence that the slides communicate well. The slide and exported PowerPoint remain the acceptance surface.

**Source visual intake:** Supplied presentations and documents may contain the best evidence for a page. The consulting runner now calls the existing source converters before planning, copies embedded and standalone images into the project image pool, renders supplied PowerPoint slides as labelled preview candidates when a renderer is available, and writes `analysis/source_visuals/catalog.md` with paths, source-slide occurrences and provenance. The solution lead and planner are told to inspect and select a candidate for its slide job, record it in §VIII and the page's `Images` line, and distinguish a screenshot from native PowerPoint content. Page authors are told to inspect selected files before placement. A new fictional few-shot slide shows this handoff. Conversion and preview paths include a source-content revision so a replaced deck cannot leave old slides in the current catalog. A focused test extracted an embedded picture, a supplied PNG and two source-slide previews, then replaced the deck and confirmed that old embedded-image and slide-two entries left the catalog. A real PowerPoint-render smoke produced all three asset kinds with no intake issues; an additional DOCX smoke extracted its embedded picture. A separate one-slide SVG/PPTX smoke placed a cataloged preview through the native exporter: the PowerPoint render showed the image and `python-pptx` found one picture shape in the saved file. These checks establish technical intake and placement; a live agent selection from a complex source package has not yet been evaluated. It does not create the historical screenshots missing from the earlier self-documentation source package.

## Failure this change addresses

The previous self-documentation deck required too much prior context. Its runner asked for many words, full pixel zones and element-by-element scaffolds, then tested a newcomer mainly for unexplained terms. A page could satisfy all three checks while failing to explain why it existed, how its figure answered a question, or how it connected to the next page. Prescriptive geometry also made dense boxes and small labels more likely.

The 25 September rerun exposed a second handoff gap: a deck reviewer can ask for proof that the source package does not contain. A page author bound to the current record cannot supply that evidence; such a finding needs source intake or plan repair, while label and connector issues can go directly to the page author. Page-level PASS does not close a deck-level evidence gap.

## Planning contract

The workflow keeps the source-grounded solution, Design Spec and execution lock. It changes the order of decisions:

1. **Reader contract:** audience, prior knowledge, purpose, reading situation and observable outcome. Multiple purposes are sequenced across the deck; each page gets one primary job.
2. **Information path:** prerequisites, concrete proof or worked example, and an arc suited to the material. A fixed brief or page count remains binding. A one-slide answer, a chronological report, a training walkthrough and a decision case do not need the same spine.
3. **Page job:** one reader question, one answer, the before-to-after audience move, and the link from the previous idea to the next. `Content` contains the visible explanation and source-backed evidence.
4. **Visual task and composition:** identify what must be seen, compared, traced or located. The planner chooses a suggested carrier, focal point, macro grouping and reading path. These choices guide the author, who owns exact coordinates, text fit and a clearer form when the proposed one fails.
5. **Blind read:** a separate reviewer sees only titles and planned visible words in order. It reports missing definitions, examples, proof and bridges. The planner repairs these before any page is drawn. A second reviewer sees only rendered pages and transcribed drawn text, not the planning narrative.

The plan checker now requires the semantic fields and rejects pixel geometry in visual guidance. It no longer enforces a minimum word count, coordinate count, or scaffold length. Those old quotas measured compliance with a page recipe rather than reader understanding.

## Diagram selection across complexity

The same logic works at three levels. A simple relationship needs a small, directly labelled view. A moderate process needs an unambiguous path, decisions and outputs. A complex system needs a scope view before a focused internal view, with consistent names and cue meanings. Each diagram has a title or scope, names the things shown, and labels non-obvious links; arrows carry direction when order or flow matters. A real example, table, chart, image or short prose may be clearer than a boxes-and-arrows figure.

This is drawn from the [C4 system context and zoom levels](https://c4model.com/diagrams), [C4 notation guidance](https://c4model.com/diagrams/notation), [Microsoft architecture-diagram practices](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/design-diagrams), and [IBM Carbon chart-selection guidance](https://carbondesignsystem.com/data-visualization/chart-types/). The examples are pattern references, not slide assets or a prescribed visual language. The operational guidance lives in `skills/ppt-master/references/diagram-clarity.md`.

## Acceptance evidence

- The plan has a reader question, audience move, story link and visual task per page. Sparse pages pass if they communicate; decorative density does not earn a pass.
- The blind planned-copy review finds no material comprehension gap before authoring.
- The rendered deck's visual review identifies no ambiguous figure or missing bridge that prevents a first-time reader from following it.
- PowerPoint output is inspected after export because SVG preview acceptance alone cannot establish editability or rendering parity.
- The self-documentation run uses the same request, frozen subject snapshot and reusable template as the previous run. Record differences in the plan and final deck; do not claim a usability improvement from prompt compliance alone.

## Same-input rerun observed on 25 September 2026

The isolated runtime is `D:/Users/software/ppt-master-selfdoc-story-20260925` and the project is `projects/ppt-master-selfdoc-story-20260925`. It uses the earlier run's request, frozen code snapshot, template and solution. The new planner produced fourteen page records. Its planned-copy cold read passed after plan repairs. Fourteen page authors reached page-level PASS, but the independent rendered-deck review returned `CHANGES`.

The reviewer could not trace P03's boundaries and direction clearly, found P07's two-runner relationship ambiguous, and called P04/P08/P13 too dense. It asked for real visual proof of historical failure on P02/P11; the supplied source package does not contain the historical page and PowerPoint images. This is a source-intake and planning limitation, not a missing drawing command. The checker initially blocked flat-mode export because five SVGs carried structured-layout metadata; removing only that incompatible metadata and repairing the project schema allowed export. The deck was exported with fourteen notes files and native tables, then rendered in PowerPoint. Its source map is beside the export. The exported P03 still has sentence-like text inside several boxes, and P13 remains too dense to use as a sponsor slide. This deck is a test artefact, not a sendable communication.

Observed run cost: 280 author calls, 20.4 million input tokens, about $5.28 author cost plus $0.74 reviewer cost, and about 46 minutes wall time. The long author run did not compensate for the missing historical visual evidence or the density of the decision table. The exact figures are from the run summary under `.host-sessions/selfdoc-story-20260925.summary.md`; they describe this test only.

### Targeted page experiment after the full rerun

Use the system-boundary page (P03) as the smallest useful comparison. Keep its verified facts, audience question and house template. Compare the current run's rendered page with a revised record that explicitly calls for short parallel bullets inside the person, host, model, script and output groups; keep definitions and provenance in a nearby reading line. The revised record also states the focal point, grouping and path without pixel coordinates. Inspect both renders at presentation size and with no narration. A better page lets a newcomer identify what is local, what calls a remote model, what scripts do, and who accepts the deck without decoding paragraphs. If the author cannot preserve accuracy and legibility from this record, add detail to the visual handoff before changing the shared planning rules.

**Result:** The isolated P03 variant is `projects/ppt-master-selfdoc-p03-bullets-20260925` in the same runtime. Only P03's record and page drawing were intentionally changed; the other thirteen drawings were copied from the full run for an export check. The new record gives short parallel bullet content, one central project boundary, remote model outside it, and a labelled human-review loop. Its page reviewer returned PASS with no geometry findings. The one-page run took 5.6 minutes, 14 author calls, about $0.41 author cost and $0.03 reviewer cost. The variant deck passed the final SVG quality gate and exported as a fourteen-slide PowerPoint with notes and a source map. The P03 PowerPoint render preserved the bullets and direction labels without visible clipping. The author kept exact box geometry in its control; a more explicit content and composition handoff was enough for this local improvement.

An additional blind model read saw only the exported P03 image, without its record or deck, and returned `CLEAR`: it identified the local project, remote model, script operations, input, output and human acceptance. It still noted parsing effort from the nested boxes and mixed arrow directions. The review is saved in `.review/blind_p03_powerpoint.md` in the variant project. A human newcomer check remains necessary, and this variant does not resolve P04/P08/P13 density or absent historical proof on P02/P11. These model reviews do not measure a gain in human comprehension. Do not generalise a reduced-geometry planner contract from one improved page alone.

## Limits

Automated reader review is a diagnostic, not evidence that an actual novice understands the deck. Human zero-context readers remain the strongest acceptance test for a deck intended to be sent without a presenter. The runner still uses the existing PowerPoint exporter, so text reflow and overlaps need inspection on the final file. Source accuracy remains a separate check from story quality.
