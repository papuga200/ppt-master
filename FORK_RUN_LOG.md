# Fork run log

## cq-test1 — 18 September 2026 — first paid run under the consulting-quality profile

**Setup.** Branch `consulting-quality` at its first commit. Host `hosts/responses_api`, model `gpt-5.6-luna`, effort `high`. Same brief, materials and local deck template as the unmodified Default run of 17 September (the Step A baseline); gates delegated; speaker notes off. One invocation, no operator input.

**Mechanics: all worked.** The model routed to the profile, asked for and received one reference for the architecture page and one for the timeline, rendered every page and received the image (20 image deliveries), revised pages with local edits, recorded four outcomes, ran the deck review, exported, rendered the PPTX through PowerPoint and looked at it. 97 calls; 15.4M input tokens of which 15.2M cached; 47k output tokens. No failed call, no stop.

**Result: not better than the baseline, and the reason is specific.** The exported deck carries defects that are plainly visible in the renders the model was shown:

- Architecture page: the second line of site names overprints the staffing line beneath it; the last box of the data path overflows; the lower annotations are crowded against the scope boundary.
- Timeline: the gate boxes sit across the oversight line; the phase-ruler labels are crossed by the tether lines.
- Cover: the subtitle collides with the last title line (the same defect as the baseline).

The model saw each of these images and recorded `accepted`, once with "Main weakness: none", and the deck review found "no deck-level change required". The checker reported two advisory warnings only. So the loop delivered the image, and the author did not see what was in it. The composition is also plainer than the baseline's architecture figure: the revisions spent their budget on metadata and label trimming, not on the figure.

**What this establishes.**

1. The plumbing of Steps B, C and D is in place and reliable.
2. With this model at this effort, author self-inspection is not a dependable reviewer of its own render. The plan anticipates this (section 14.4): either a separate vision-capable reviewer looks at the render, or the look has to be made harder to wave through.
3. One page exceeded its revision budget (cover, 4 of 3): the tool reports exhaustion but does not refuse. 

**Candidate next steps, none taken.** (a) A fresh-context review call per page that receives only the render and the brief and must list every overlap, overflow and collision before any outcome is recorded - same model first, to separate "cannot see" from "will not criticise its own work". (b) A measured overlap report from the rendered page (text boxes against each other) handed to the author with the image, since the checker's zone estimate missed real collisions. (c) Hold the model fixed and rerun at `xhigh` to see whether effort changes what it sees. One change at a time.
