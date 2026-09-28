# Few-shot calibration for story and visual handoff

These are fictional teaching examples. Copy their *level of decision*, not their topic, wording, palette, number of boxes, page count or visual form. Each record gives the page author a clear answer, visible copy, semantic relationships and macro composition. It leaves measurements and SVG primitives to execution. A simpler page can be shorter; a dense evidence page can carry more copy when that detail is needed and legible.

## Example A — a system diagram people can scan

#### Slide 03 - A permit request moves through one service before an officer decides

- **Role**: system explanation
- **Author tier**: frontier
- **Layout**: content
- **Audience question**: Where does an applicant's request go, and who makes the decision?
- **Audience move**: From an opaque digital service to a clear path with a human decision boundary.
- **Story link**: Follows the service definition; prepares the worked application example.
- **Relationships**: Applicant submits a request to the permit service; the service checks completeness and stores a case; an officer reviews the case and returns a decision to the applicant.
- **Title**: The service prepares the case; an officer decides
- **Core message**: The software routes information and an authorised officer owns the decision.
- **Content**: `Applicant input` with three short bullets: `Request form`, `Supporting documents`, `Contact details`. `Permit service` with three short bullets: `Checks completeness`, `Stores the case`, `Routes it to an officer`. `Officer` with two short bullets: `Reviews the case`, `Records a decision`. `Applicant output` with two short bullets: `Status update`, `Decision notice`. Visible reading line: `Read left to right: submission → preparation → human decision → notice.`
- **Sources**: illustrative scenario only; a real plan cites the supplied process and labels invented data.
- **Visual task**: Trace the request, locate the software boundary, and see who decides.
- **Visual approach**: A scoped flow diagram fits the handoff and decision boundary; directly label arrows whose meaning is not obvious.
- **Composition**: One left-to-right path. Make the software service the focal middle group, enclose only its functions, and put the officer outside that boundary. Keep the short bullet groups inside their boxes; place the reading line outside the diagram.
- **Hierarchy**: Human decision first; path second; exact data items third.
- **Avoid**: Paragraphs inside nodes, a generic cloud icon, a line with no direction, or a claim that the service approves permits.
- **Reference**: none; structure follows the source relationship.
- **Editor notes**: Keep the bullets parallel and short. Do not shrink text to fit an extra component; split detail onto a later page if needed.

## Example B — a small training page needs an actual task

#### Slide 06 - A reviewer checks the exported file before sending it

- **Role**: worked training step
- **Author tier**: workhorse
- **Layout**: content
- **Audience question**: What do I do after the draft is exported?
- **Audience move**: From a vague instruction to a repeatable check and a clear pass condition.
- **Story link**: Follows the export walkthrough; prepares the handoff checklist.
- **Relationships**: Open the file, inspect a complex page, edit a label, then decide whether to share or repair.
- **Title**: Open the PowerPoint, edit a label, and inspect the result
- **Core message**: The exported file is accepted only after its rendered appearance and basic editability are checked.
- **Content**: `Try this` with three numbered actions: `1. Open the exported .pptx in PowerPoint.`, `2. Select a diagram label and change one word.`, `3. Save, reopen, and compare the page with its preview.` Then one explicit result: `If a label moves, clips, or cannot be selected, return the page for repair.`
- **Sources**: illustrative workflow; replace with the product's actual supported editor and checks.
- **Visual task**: Locate the action, expected result and repair branch without reading a long paragraph.
- **Visual approach**: An annotated file screenshot if a real one is available; otherwise a concise action/result layout. Do not fabricate an interface.
- **Composition**: One dominant example area, with the numbered actions adjacent and the repair condition visibly separate beneath it. The example carries the page; instructions support it.
- **Hierarchy**: Task first, result second, exception third.
- **Avoid**: A decorative process diagram, unexplained UI labels, or a PASS badge without a tested outcome.
- **Reference**: none.
- **Editor notes**: A training slide may be spare because the learner performs the task.

## Example C — a decision page may need more detail

#### Slide 09 - Pilot option B covers the required teams at a lower setup cost

- **Role**: decision
- **Author tier**: frontier
- **Layout**: content
- **Audience question**: Which pilot option should we fund, and what trade-off follows?
- **Audience move**: From two plausible options to an evidence-based choice with a stated risk.
- **Story link**: Uses the prior cost and coverage evidence; leads to the approval request.
- **Relationships**: Option A and B are compared on the same criteria; B meets the required coverage at lower setup cost, while A starts sooner.
- **Title**: Choose option B for coverage and cost, accepting a slower start
- **Core message**: B is the preferred pilot only if the start date can move by two weeks.
- **Content**: Comparison rows with the same units: `Teams covered: A 2; B 4 (requirement 4)`, `Setup cost: A $42k; B $31k`, `Start: A week 3; B week 5`. Recommendation: `Approve B if a week-5 start is acceptable; otherwise resolve the timing trade-off before funding.` Note: `All figures are scenario values for this teaching example.`
- **Sources**: scenario values only; a real decision page cites the supplied data and labels assumptions.
- **Visual task**: Compare options against the requirement and locate the condition that could reverse the recommendation.
- **Visual approach**: An aligned table suits three like-for-like criteria; a chart would add little. Emphasise the requirement and decision condition without hiding A's timing advantage.
- **Composition**: Title and recommendation at the top, a dominant compact comparison beneath, then a separated conditional decision line. Align values by criterion; do not bury the exception in a footnote.
- **Hierarchy**: Recommendation, criterion comparison, timing caveat.
- **Avoid**: Three unrelated cards, unequal units, or a bare “B wins” label.
- **Reference**: none.
- **Editor notes**: This is denser because the decision needs criteria, values and a condition; do not add copy to an explanatory page to match its density.

For diagram nodes, short parallel bullets or labelled fragments usually scan better than prose paragraphs. Put interpretation, provenance and caveats in a caption or nearby explanation. Use full sentences inside a node only when the wording itself is the evidence or the task requires verbatim language.

## Example D — a supplied deck image is evidence, not decoration

Its §VIII image row uses `source_decision_deck_pptx_f1e2d3c4b5a6_slide-007.png` as Filename, `user` as Acquire Via and `Existing` as Status. The content hash shown here is illustrative; use the exact filename in the project's catalog.

#### Slide 04 - The source deck's table hides the decision criterion

- **Role**: source evidence
- **Author tier**: workhorse
- **Layout**: content
- **Audience question**: What, exactly, makes the current decision slide hard to use?
- **Audience move**: From a general complaint about density to a visible, source-grounded example.
- **Story link**: Follows the decision requirement; prepares a clearer proposed comparison.
- **Relationships**: A small table in the supplied deck places the required criterion among several same-weight rows; the reader must find that row to make the decision.
- **Title**: The required criterion is buried in the existing table
- **Core message**: The source slide makes the decisive row hard to find at presentation size.
- **Content**: Label the image `Supplied deck, slide 7 — screenshot`. Two short callouts: `1. The required criterion uses the same weight as background rows.` and `2. The table must be read line by line to find it.` Visible source line: `Source: supplied decision deck, slide 7.`
- **Sources**: the supplied deck's slide 7 and its extracted text; these are fictional teaching sources in this example.
- **Images**: `images/source_decision_deck_pptx_f1e2d3c4b5a6_slide-007.png` — exact screenshot of supplied slide 7; show the relevant table at a readable scale with a labelled crop; do not redraw it as invented evidence.
- **Visual task**: Let the reader see the decisive row's weak prominence in the real supplied slide.
- **Visual approach**: Annotate the actual source-slide preview. A generic table or illustration would not show the defect being claimed.
- **Composition**: Give the screenshot most of the page, with two concise callouts beside the table and the source directly below it. Keep the crop large enough to read the criterion.
- **Hierarchy**: source evidence first, two observations second, provenance third.
- **Avoid**: A fabricated UI, an unattributed screenshot, or implying that the screenshot is editable native content in the new PowerPoint.
- **Reference**: none; the supplied slide is the evidence, not a style reference.
- **Editor notes**: Confirm slide number, source rights and legibility before sending. If the actual source slide is unavailable, replan the evidence; do not synthesize a fake screenshot.
