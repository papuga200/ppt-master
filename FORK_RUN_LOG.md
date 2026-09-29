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

## cq-brief1 — 19 September 2026 — rich slide records (the deck-brief test, `FORK_DECK_BRIEF_DESIGN.md` §9 step 3)

**Setup.** Project `harrowgate-brief_20260919`: a copy of `harrowgate-cq_20260918`'s template workspace, lock and sources, with `design_spec.md §IX` rewritten by hand as complete slide records (Role, Story link, Hierarchy, a Content list of every visible text block, a plain-text Visual scaffold, Avoid, Reference, Editor notes) plus a Narrative block. Same host, model `gpt-5.6-luna`, effort `high`, same delegation. The reference library gained three real consulting proposals (McKinsey NJ 2023, BCG Virginia 2022, BCG NZ 2022), so the timeline page had two real workplans as references (`lib.d35f8b77.p45`, `lib.a725b71f.p14`). No fresh-context reviewer: one change at a time.

**Mechanics.** 92 calls; 13.2M input tokens of which 13.0M cached; 54k output. 25 images delivered. Three launch faults, all in the host or its environment, none in the profile: (1) the console codepage could not print an emoji in a tool result — `host.py` now reconfigures stdout/stderr to UTF-8; (2) the host was first started on the system Python, which lacks flask, so the preview server and every render failed — it must run on the repository `.venv`; (3) that venv's Playwright had no browser, installed mid-run (`python -m playwright install chromium`), after which renders worked; the three body pages were therefore drafted before their first render and reviewed afterwards; (4) the host's `--max-turns 60` ceiling stopped the run mid-repair and dropped the last turn's tool outputs — the host now keeps them as `pending_input` at the ceiling and defaults to 200; the session was recovered by fetching the stored response's call id and resumed with `--resume-pending`.

**Result: the plan lever is real.** Every body page drew the structure its record asked for on its first draft:

- Architecture: five site nodes converging on a single filled hub, wave two as dashed nodes, the steering committee as a band across the top inside a dashed group boundary, the data path leaving as a chain and crossing the boundary once at the "de-identified, weekly" label. cq-test1 drew three stacked tiers with nothing connecting them.
- Timeline: one continuous track with a month ruler, the two gates as diamonds on the track at M3 and M5, phase detail hanging below in its own band, gate decision boxes in a separate band tethered up to their diamonds, the steering concern above, an outcome band closing the track. cq-test1 had the gate boxes across the oversight line.
- Executive summary: a governing-thought panel, then three claim-plus-proof rows on hairlines; thresholds and fees preserved. The row labels became filled green blocks, heavier than the scaffold asked for, so the page has four tinted surfaces where the record wanted one.
- Cover: clean; the subtitle collision of both earlier runs is gone.

**Result: the reviewer is unchanged.** The exported architecture page still carries the per-site staffing line underneath the dashed wave-two nodes and their connectors — the exact case the record's Avoid line named — plus leftover prototype furniture (a grey zone at the right, numbered badges) and no visible connector from the hub into the data path. The page was accepted four times, the deck review wrote "no visible overlap, clipping or crowding", and the final checker passed. The timeline's outcome is stated twice (tile and band). Revisions used: cover 2, executive summary 4, architecture 4, timeline 5 — the budget of 3 is exceeded because the consolidated repair pass and the deck review both edit after acceptance and the tool counts but does not refuse.

**What this establishes.**

1. A richer plan in text changes what the SVG author draws. Hierarchy, spatial arrangement and the named weak imitation were all followed; the concept-level defect of cq-test1 did not recur on any page.
2. The medium is not the ceiling: the same model at the same effort produced a connected system figure in SVG once the record said what the picture was.
3. Execution defects of the collision class survive unchanged, and the author's self-review does not see them. The next lever is the reviewer (`FORK_RUN_LOG.md` cq-test1 candidate (a)), not the plan.
4. The reference sheets worked as designed: the planner (here, by hand) picked from the sheet; the author received the chosen slide and borrowed its devices without its content.

**Next.** (a) The fresh-context review call per page, same model first. (b) Then the Slides stage that writes these records from the Narrative and Structure sections, with reference matching in it. (c) The revision budget should refuse, or the deck-review edits should draw on a separate allowance, so the count means something.

## cq-brief1 follow-up — 19 September 2026 — one fresh-context review call

**Question.** The author accepted the cq-brief1 architecture page four times with a visible collision. Can the same model see it when it did not draw it?

**Setup.** One Responses API call, `gpt-5.6-luna` at `high` (the author's effort), no history: the accepted 1280×720 render (`.preview/03_study_arrangements.png`), the P03 slide record from §IX, and a reviewer instruction that requires a defect inventory (every overlap, touch, crossing, clip, collision, leftover) before any concept judgement or verdict. 55 s; 2,987 tokens in, 7,394 out. Output kept at `projects/harrowgate-brief_20260919/.review/reviews/03_study_arrangements.fresh-high.md`.

**Result.** It listed every defect: the connectors crossing the per-site staffing line; the leftover numbered badges `2` and `3` (the `3` overlapping `Wearable patch`); the grey block behind the hub ("reads partly as stacked bands"); the grey block at the right ("leftover prototype material"). Concept check: the data path does not visibly leave the hub; wave two is drawn as small dashed circles, not same-size nodes as the record asked. Verdict `EXECUTION_REPAIR`; highest-impact change: a connector from the hub into the path, routed away from the staffing line.

**What this establishes.** The model can see the page. The author could not, because it was judging its own drawing from inside its own context. The reviewer belongs in the loop as a separate call with nothing but the render, the record and the reference; its inventory gates `accepted`. Deck Builder's `critic.md` is the prompt to port, minus its evidence tools.

## cq-brief2 — 19 September 2026 — the independent reviewer in the loop

**Setup.** `harrowgate-brief2_20260919`: the same records, template, lock, sources, references, model and effort as cq-brief1. One change: `page_review.py review` in the loop — a fresh call per revision (render + §IX record + review language + the page's delivered references; defect inventory first; `VERDICT` line) — and `note --outcome accepted` refused without a `PASS` review of the current revision. The author was told to look and fix first, then ask. 114 calls; 17.6M input tokens (17.3M cached); 81k output; 14 review calls at ~15–85 s each.

**Result: the gate works, and it is truthful.** Every page ended `unresolved` with the reviewer's remaining items quoted in the note; the author never wrote `accepted` over a defect and never used `--no-review`. The reviewer caught, on first sight: the prototype's stray "Proposal & Report" label on the cover (present and unnoticed on both earlier runs); the heavy filled label blocks on the executive summary (the drift noted by hand on cq-brief1); seven real collisions on the architecture draft; the gate diamonds hiding the M3/M5 labels on the timeline; and, after the checker's consolidated repair pass, a regression it introduced on the executive summary (a hairline through "enrolment pauses if not met", "COMMITMENT" clipped, the label blocks back). Cover and executive summary reached `PASS` once each before that repair pass undid them.

**Result: the deck is not better than cq-brief1's, and the reasons are specific.**

1. *First-draft variance.* This run's author drew the architecture as the prototype's three stacked tiers with connectors through all five site labels — the exact figure the record's Avoid line names and the one cq-brief1 did not draw. Same model, same record. Its three revisions patched connectors instead of redrawing, and the page stayed broken.
2. *Under-classification.* The reviewer's own concept check said "reads as three stacked tiers rather than one connected figure" and still returned `EXECUTION_REPAIR`. That is `CONCEPT_REPLAN`; routed as a replan the author would have redrawn the figure. The prompt must make a failed concept check decisive.
3. *Reviewer precision.* On the timeline draft, six of ten "blockers" were phantom tether crossings at 12-px ruler labels; on the final timeline it raised three alignment nuances as blockers and dropped the one real item (untethered gate callouts). Recall is high; precision on small type and on a clean page is not. A hard gate plus a noisy reviewer leaves a good page `unresolved`.
4. *Scaffold against prototype.* The cover's record described a "green lower panel" the bound prototype does not have; the reviewer enforced the record over the template on every pass, so a clean cover ended `unresolved` with `BLOCKERS: 0`. The record was wrong, and the prompt had no rule for the conflict.
5. *A blind repair pass.* The checker's consolidated repair edits reviewed pages without a look; the post-repair review caught what it broke, but the author had no budget left to fix it.

**What this establishes.** The reviewer is the right detector: with it, the journal tells the truth and the shipped deck's defects are named rather than hidden. The remaining levers are all small and all upstream of the model: (a) blockers are a closed class — overlap, touch, crossing, clip, wrong zone, leftover — and alignment or taste items are notes that never block; a clean page must return `PASS`; (b) the reviewer receives 2× crops of the quadrants with the render; (c) a failed concept check is `CONCEPT_REPLAN`, full stop; (d) the binding prototype wins over the scaffold, stated in both the record note and the reviewer prompt, and the scaffold is written against the prototype; (e) the consolidated repair pass renders and reviews what it touches, or the budget reserves one revision for it; (f) a `CONCEPT_REPLAN` verdict grants a redraw outside the three local revisions.

**Next.** Apply (a)–(f) — prompt, tool and record changes only — and rerun once. Then the Slides stage that writes the records.

## mx-sol, mx-kimi, mx-deepseek — 19 September 2026 — the model matrix

Same inputs and profile as cq-brief2, reviewer fixed on `gpt-5.6-luna` at `high`, authors varied: `gpt-5.6-sol` @ medium (OpenAI), `moonshotai/kimi-k3` @ high and `deepseek/deepseek-v4.1-flash` @ high (both through OpenRouter's stateless Responses API; the host gained `PPT_MASTER_API_BASE`, `PPT_MASTER_API_KEY_VAR` and a resent-history mode). A Luna @ medium run was started and stopped as redundant. Full report: `FORK_MODEL_MATRIX_REPORT.md`; per-session numbers from `hosts/responses_api/report.py`.

**Result.** Kimi passed all four pages (the only run to do so) and drew the record's architecture; Sol was the most economical and the cleanest executor (80 calls, 24 min, $2.74, 31 edits) with two pages left one item short; DeepSeek was cheapest ($0.40) and slowest (2 h, 49M tokens, 27 reads of script source) for a deck on a par with Luna's; Luna @ high, with 163 edits and 14 failed calls, was the weakest author. Luna is a bottleneck for design; the workflow held for every model; the reviewer's precision problem is model-independent and produced a false PASS (DeepSeek's stacked-tier architecture) as well as false blocks.

**Next.** Sol @ medium as the default author; the reviewer's closed blocker class and zoomed crops; then the Slides stage.

## pga-sol, pga-deepseek, pga-par — 20 September 2026 — packed records, then per-page parallel authoring with tier routing

**The case.** A nine-page proposal to Pinnacle Asia Banking Group for "Sentinel" (production-health monitoring, agent-proposed fixes as PRs, automated review, human approval): cover, executive summary with KPI strip, workflow-today, the loop, architecture, security table, target operating model, a nine-lane Gantt with overlaps, dependencies, milestones and two gates, benefits and commercials. Three source documents, every number a scenario value; the client's own design system (Segoe UI, crimson `#B4162E`, the peak mark) read from their deck generator. Flat route - no prototype zones; records carry a `Fill` line; the reviewer's blockers are a closed class including unused canvas; a structural departure is `CONCEPT_REPLAN`; the author's `read_file` refuses script source.

**pga-sol (one conversation, Sol @ medium).** 154 calls, 49 min, $7.37; 7 of 9 accepted on a PASS. Packed, on-brand, consistent - the density the earlier runs never produced. Where the money went: cached re-reading $5.98 (81%), new input $0.67, visible output $0.55, reasoning $0.17 (2%). Context grew from 7k to 332k tokens; page 9 paid to re-read pages 1-8. Time: API 29 min, scripts 20 min of which 28 serial reviewer calls 16 min.

**pga-deepseek (one conversation, DeepSeek V4.1 Flash @ high).** Stopped by a host death at call 84 with 4 of 9 pages done, all four accepted on a PASS, $0.26. The four pages match Sol's in structure figure for figure: the plan, not the model, is drawing.

**pga-par (`hosts/responses_api/deck_runner.py`).** Each page in its own conversation with one shared 41k-token system prompt (page-author brief, eight contract documents, design system, Narrative, a one-line digest of every page, lock, calibration); an anchor page first (Sol), whose chrome every other page copies; then eight pages at once, routed by the record's `Author tier` - architecture and Gantt to Sol, six to DeepSeek @ medium; one checker pass with targeted repair in each page's own session; deck review over the contact sheet; export. **18.6 min, $1.46 of author cost, 133 calls, peak context 61-87k, 8 of 9 accepted on a PASS** (the architecture in 4.4 min, where the single conversation left it unresolved after four revisions; three DeepSeek pages passed review on their first draft). The deck review found the chrome identical across P02-P09 and the two models' pages indistinguishable; it also found the gates named three different ways across P02, P08 and P09 - an inconsistency in the records themselves, caught at deck level.

**What the test exposed.** (1) The exporter refuses a deck whose final checker report has blocking issues; one repair round left two on the anchor page, so the runner now repeats repairs (two rounds) and exports only on a clean report. (2) DeepSeek's pages took 9-15 min each: OpenRouter's default routing sent every call to DeepInfra at ~89 tokens/s. A benchmark of 15 hosts on this workload's shape (long cached prefix, a 3-4k-token SVG write, small replies) measured Modal at 378 tokens/s, Together 266, Venice/GMICloud ~210, and Morph at 14; the workhorse author is now pinned Modal → Together → Venice → GMICloud with fallbacks (`PPT_MASTER_PROVIDER`), an ordered pin so a conversation's prompt cache holds. (3) The reviewer (Luna @ high; ~7k tokens in, ~4k out, $0.006 a call, $0.17 a deck) still passes 12-pixel defects - a connector through "may do" on the accepted architecture page. Planned: a geometry lint from the rendered DOM (text × line, text × text, overflow, empty quadrant) ahead of any model call; a fast cheap model for the concept check; a strong model only to confirm a PASS on frontier pages.

## Geometry lint and the reviewer benchmark — 20 September 2026

**The lint (`skills/ppt-master/scripts/page_lint.py`).** A page is laid out in Chromium and every line of text, stroke and shape is measured with its paint order. Tuned over seven passes on the 46 renders of the earlier runs: 31 clean, 15 flagged, every checked flag real, including defects no model had named (a label on the week numbers, a leftover badge, a column rule through table text, a title rule through a third title line). It is deliberately not exhaustive. `CERTAIN` findings (text on text, off-canvas or invisible text, a contract error in this file) must be fixed before a review is given; `FLAGGED` findings (a line through text, text leaving its shape, a shape over text) go to the reviewer with a 3x crop each, and the reviewer rules `DEFECT` or `ACCEPTABLE` - intention is a judgement, so a model makes it, looking at the place. Renders that only fix lint findings do not count against the three design revisions (allowance four). Crowding without overlap is left to the reviewer. The end-to-end smoke test caught one bug before the run: the per-file contract check reported the deck's incomplete roster as a certain defect, which would have blocked every page of a parallel run; only the file's own issues count now. It also found the preview-server port race of the model matrix: a lock file could point at another project's server; the check now compares the served project and a new server takes a free port.

**Reviewer benchmark.** Ten labelled renders (five with known defects, five clean), the new instructions, the lint's findings and crops attached, one call each. OpenRouter refuses Google and Anthropic models for this account (403, as for OpenAI), so Gemini ran through Google's own endpoint (`page_review._review_call_chat`); Claude was not testable.

| reviewer | right | false PASS | false alarm | called the three structurally wrong figures CONCEPT_REPLAN | s / review | $ / review |
|---|---|---|---|---|---|---|
| gpt-5.6-luna @ high (until today) | 8/10 | 0 | 2 | 0/3 | 46 | 0.008 |
| gpt-5.6-luna @ medium | 8/10 | 0 | 2 | 1/3 | 16 | 0.003 |
| gemini-3.8-flash | 9/10 | 0 | 1 | 1/3 | 10 | 0.007 |
| gemini-3.5-flash | 9/10 | 0 | 1 | 0/3 | 13 | 0.005 |
| gemini-3.5-flash-lite | 9/10 | 1 | 0 | 0/3 | 6 | 0.003 |
| gemini-3.1-pro | 7/10 | 0 | 3 | 2/3 | 19 | 0.018 |
| qwen3.8-flash | 8/10 | 0 | 1 (+1 unparsed) | 0/3 | 141 | 0.004 |
| qwen3-vl-235b | 7/10 | 0 | 3 | 2/3 | 24 | 0.003 |
| glm-5v-turbo | 8/10 | 0 | 2 | 1/3 | 73 | 0.014 |
| kimi-k2.6 | 8/10 | 0 | 2 | 0/3 | 94 | 0.051 |
| kimi-k3 | 10/10 | 0 | 0 | 0/3 | 43 | 0.029 |
| qwen3.8-max | 10/10 | 0 | 0 | 0/3 | 202 | 0.066 |
| grok-4.6 | 10/10 | 0 | 0 | 2/3 | 73 | 0.037 |

**Reading.** With the lint's measurements attached, almost no reviewer passes a defective page any more: the ruler turned recall from a model problem into a given. What separates reviewers now is noise on clean pages (the "false alarms" are small-type opinions, not hallucinations) and whether a structurally wrong figure is called a replan rather than a repair. Ten pages is a small sample: it picks a default, it does not rank.

**Chosen.** Workhorse pages (DeepSeek author): `gemini-3.8-flash` @ medium - another family, 10 s, under a cent. Frontier pages (Sol author) and the deck review: `x-ai/grok-4.6` @ medium - 10/10, no false alarm, and the only perfect scorer that named the wrong figures as replans; `kimi-k3` is the alternative (faster, never called a replan). `deck_runner.py --reviewers` overrides both.

## pga-par2 — 20 September 2026 — the lint in the loop, heterogeneous reviewers, fast DeepSeek hosts

Same nine records as pga-par with the gate names standardised (`Gate 1 (week 20)`, `Gate 2 (week 24)`, and a continuity rule saying so). Workhorse pages: DeepSeek V4.1 Flash @ medium pinned Modal → Together → Venice → GMICloud, reviewed by `gemini-3.8-flash`. Frontier pages (P05 architecture, P08 Gantt) and the anchor (P02): Sol @ medium, reviewed by `x-ai/grok-4.6`, which also read the whole deck.

| run | wall | cost | accepted | note |
|---|---|---|---|---|
| pga-sol (one conversation) | 49 min | $7.37 | 7/9 | |
| pga-par | 18.6 min | $1.46 + ~$0.17 reviews | 8/9 | Gantt unresolved; export needed the override |
| **pga-par2** | **15.2 min** | **$1.79 + ~$0.2 reviews** | **9/9** | clean checker, clean export, final lint nothing open |

**What the lint did.** The anchor's first render had measured findings; Sol cleared them in four geometry-fix renders (none counted as a design revision) and Grok passed the first review it was asked for. Seven of nine pages were accepted with zero design revisions; twelve reviewer calls for nine pages (pga-par needed about 28). The architecture page, which shipped last time with a connector through "may do" and text past its box, is clean; the Gantt, last time's unresolved page, passed.

**What it did not do.** (1) The cover went unresolved on DeepSeek because the author brief told covers to take "the footer style" from the anchor, so it drew a running footer and folio that the reviewer rightly refused, and it left the locked light logo unused; escalation to Sol fixed both in 82 s. The brief now says a cover carries no running footer unless its record lists one. (2) The lint measures the browser's layout, not PowerPoint's: in the PowerPoint render of the Gantt three bar labels are tight against their neighbours ("Shadow: propose, no PRs" under "Repo knowledge", "Integration/failure tests" running into "Pilot: Payments API +", an arrowhead on "PR mode on pilot services"). Small, but it is the class the lint cannot see; the profile's PPTX inspection step is where it belongs. (3) The deck review (Grok) found real cross-page drift - "Remediation Agent" on P05/P06 for the step every other page calls Propose, P07 renaming the six steps with "agent", Gate 2 blue on P02 and red on P08, a data-class stamp only on the two Sol pages - and nothing acts on it: the runner reports the deck review, it has no deck-repair round. Most of these come from the hand-written records (the records themselves say "Remediation Agent"), which is an argument for the Slides stage, not for more repair.

**Next.** A deck-repair round that hands each page its lines of the deck review (cheap: each page session is still open); then the Slides stage that writes the records - the original goal, still unbuilt.

## pga-par3 — 20 September 2026 — text inside shapes, Grok reviewing every page

**Why.** The user opened pga-par2 in PowerPoint: 490 text objects, every one a floating non-wrapping text box over a rectangle, no shape holding its own text, multi-line text as stacks of one-line boxes, titles in pieces, tables as text over stripes. It looks right and edits badly.

**`pptx_text_in_shapes.py` (new; runs on the exported .pptx, upstream's exporter untouched).** (1) one-line texts that are the lines of one paragraph are joined into one paragraph, and a hand break becomes a space wherever PowerPoint's own wrapping would break at the same word; (2) a text box goes into the smallest shape that contains it and is painted beneath it - the shape's own text frame, insets reproducing the position, word-wrap on, a lone centred label anchored to the middle; (3) what is left forms heading-and-body blocks: neighbours only, a block ends at a rule, at a larger heading, or at a drawn bullet; (4) the slide's title becomes its real title placeholder (lifted out of its group). `--verify` compares the PowerPoint renders before and after; the runner keeps the exporter's file under `exports/floating-text/`, so the pass can be re-applied without a model run.

**What had to be measured (calibration decks rendered by PowerPoint).** A line at single spacing is 1.2 x the font size tall for every font tried; with exact spacing the line is that tall and the baseline sits at 80% of it (capital tops at 0.8 x spacing - 0.75 x size below the line top, against 0.25 x size at single spacing); paragraph spacing keeps whole points only (fractions are dropped, so the pass writes whole points and carries the remainder); the exporter's text-width estimates run up to a quarter too wide for bold type, so wrap prediction uses real advance widths from the installed font files (PIL); PowerPoint also breaks after a hyphen. With these, pga-par2 re-processed renders with no ink moved by more than 2 px on any slide: 490 text boxes -> 339 text objects, 107 loose lines joined into 48 paragraphs, 121 texts inside 79 shapes, 9 real titles.

**The run (pga-par3).** Same case; records with the deck review's continuity fixes (step names fixed, `Remediation Agent (Propose step)`, both gates crimson, no data-class stamp); the author brief gained "built the way a person builds a slide" (one shape per box with its text inside, one column of text per shape, a table as a grid of cell rectangles, one `<text>` per paragraph, centred labels, nothing painted between a shape and its text); reviewer `x-ai/grok-4.6` on every page and the deck (user's decision: about $0.35 more a deck, no wall time, since pages run in parallel). Result: 9/9 accepted, clean checker, clean export; author cost $1.59 + $0.23 (P05 rerun) + P02 repair, reviews about $0.45. The brief changed how pages are drawn: 232 texts inside 189 shapes (121 in 79 before) and 6 loose lines to join (107 before) - the pass became the safety net rather than the mechanism.

**What broke, and what it exposed.** (1) A network drop killed four page sessions at once: `http.client.IncompleteRead` is an `HTTPException`, not an `OSError`, and the host's retry did not catch it (fixed). Two workhorse pages were escalated to Sol and passed; the runner does not retry a frontier page, so P05 was re-authored with `--pages 5` (PASS, 3.8 min). Wall time 28.5 min instead of about 15. (2) **A lint bug**: for `first line<tspan dy>second line</tspan>` the lint measured only the tspans, so the first line of every multi-line text was invisible to it. The anchor page shipped with a heading's second line touching its paragraph; Grok passed it; it showed only in the PowerPoint render. Fixed (bare text nodes are measured through a Range); the corrected lint reported both collisions as certain, Sol repaired the page in one revision. A "crowding" rule tried at the same time fired only on deliberately tight titles and was dropped. (3) The deck review's remaining items are narrower (P07 step suffixes, P06 tie-to-step, P09 Gate 2 and an MTTR baseline to check) and still nothing acts on them.

**Still not right for editing, and where it belongs.** Tables: the authors now give each cell its own rectangle, which puts text inside shapes but is not a table. The skill already emits native PowerPoint tables (`data-pptx-replace-with="table"` with JSON, §IX `Native-ready: <key>=yes`, export flag `--native-charts-and-tables`); our records never declare it, the brief never mentions it, the runner never passes the flag. That is the next change, with the Slides stage that writes the records. Header, footer and sub-heading placeholders need a slide master: the template route the user parked. Drawn bullets stay shapes (native bullets would need the marker removed and the indent reproduced).

## pga-par4 — 20 September 2026 — typesetting rules, native lists, native tables, editing affordances

**Why.** The user read pga-par3 as squished and asked for common-sense line and paragraph spacing, and for PowerPoint's own constructs styled to our look: bulleted and numbered lists instead of drawn squares beside text boxes, tables with their text in the cells. Measured on pga-par3: body text at a median 1.25 x line spacing (down to 1.08 x), titles 1.04 x, 27 drawn bullets against 2 typed; upstream's own guidance says 1.4-1.5 x for small body - my "packed pages" brief had pushed the authors to squeeze.

**Changes.** `references/consulting-typesetting.md` (line spacing by role, paragraph / list / block gaps with "inside a group tighter than between groups", padding and measure, what to do when words do not fit, lists as native lists with a typed coloured marker - the exporter already turns a leading `■` into a native bullet in the marker's colour - and tables as native tables styled per cell) travels with every page author, with `native-data-interface.md`; the lint measures line spacing (`TIGHT_LEADING`, flagged); records gained `Native-ready: <key>=yes` on five pages (including the executive summary's label | content rows); the runner exports with `--native-charts-and-tables` when a page marks a table, and writes speaker notes from each record (message, what the page must do, notes for the editor, data provenance). The export pass gained: objects named after their text, thin rectangles to real lines, alt text, typed numbers to automatic numbering, and the repeated header / logo / rules / footer / page number moved to ONE new slide layout with the page number as a field (the cover keeps its layout).

**Result.** 14.6 min, 9/9 accepted, 7 with zero design revisions, clean checker; author cost $1.74, reviews $0.37. Body text at 1.42-1.44 x, headings 1.2 x, titles 1.14 x, by the authors themselves. Five real PowerPoint tables (3x2, 7x4, 6x4, 6x3, 5x4), 40 native bullet paragraphs, notes on every slide, 8 slides on the new "Content - header and footer" layout.

**What broke.** (1) The exporter refused the native tables at first: its parity check wants every `<text>` of a table's fallback to equal, as one string, a cell's text in the JSON - our authors broke cell text over `<tspan>` lines without the space at the line's end ("WHERE THE" + "TIME GOES" reads "THETIME"), and left header alignment out of the JSON. Both are now in the typesetting rules, and the runner hands such findings to the pages' own sessions and retries the native export once (then falls back to the drawn tables and says so). My first version of that retry forgot to refresh the final checker report and re-ran the text pass over the previous export, overwriting its kept original; fixed (a fresh report before re-export; only a deck made by this export is post-processed). (2) The pass joined native bullet items into one paragraph - the exporter had already turned the typed marker into `buChar`, so the marker was no longer in the text - and gave bullet blocks a frame too narrow by the hanging indent; fixed (a bulleted paragraph never joins; the indent counts in the width). After both, the pass moves no ink by more than 2 px against the exporter's original.

**Requirements recorded from the user (not built).** A template is the default, not an option: use the one provided, otherwise create one (masters, layouts, placeholders; more than one master only for distinct design families) before pages are authored, with NO approval gate - "you made the template and it was good; changes can be done later". That stage replaces the chrome anchor page and the pass's header/footer promotion (kept as the flat-deck fallback). Next for editing friction: connectors glued to the boxes they join (today 0 connectors: 21 plain lines and freeform arrows stay behind when a box moves); a deck-repair round; native charts; sections.

**Later the same day.** (1) The user noticed pga-par4's Gantt had no labels on its bars. Cause: the new lint put 20 findings on Sol's first draft (labels straddling short bars), and the cheapest way to clear them was to strip the labels and list the sub-tasks in the lane heading; nothing required labels, the reviewer passed it. Now required in `consulting-typesetting.md` §6 (every bar named on it or right beside it; milestones, gates, windows named where they happen; a legend explains symbols only), in the reviewer's timeline guidance, in the brief (fully inside or fully beside is clean - only straddling is flagged), and measured by the lint (`BAR_WITHOUT_LABEL`: six or more thin wide bars, each needs text on it or beside it; 17/17 on par4's Gantt, 0 on par3's labelled one, silent on table and architecture pages). Lesson recorded: every lint rule changes what is cheapest for the author - close the escape it opens. (2) `glue_connectors` in the export pass: straight line shapes whose ends lie on rectangle edges become `p:cxnSp` with `stCxn` / `endCxn`; on par4's architecture slide 11 arrows (10 glued at both ends), render identical, and PowerPoint (COM) confirms a moved box drags its connector. Multi-bend freeform arrows (3 on that slide) cannot be expressed as PowerPoint elbow connectors and stay drawings.

## meridian1 — 20 September 2026 — request in, proposal out: solution, plan, template, pages, review, deck repair, export

**The case.** Meridian Life Assurance's RFP MLA-2026-DAP-014 (agency performance reporting and analytics platform; three of ten business units in six months; Power BI preference; a contained natural-language querying pilot) from ProposalIQ's `demo_rfp`. Inputs: the RFP texts, a firm knowledge base (who we are, rate card, accelerators, security position, house style - credentials and CVs declared NOT available) and a four-line request. I first wrote a pre-solved brief (solution, plan, team, price, page list); the user stopped that: the tool is given high-level requirements and turns them into the proposal. It was moved aside, and three stages were added.

**New stages.** `solve()` - a SOLUTION stage (Sol @ high): the client's situation and what they judge, win themes, the solution with reasons and rejected alternatives, scope, a week-by-week plan, the team by role and days, a price built bottom-up from the rate card that reconciles in the client's pricing structure, proof, risks, what each page must make the reader believe -> `solution.md`. `plan()` - the PLANNER (Sol @ high): Narrative -> Structure -> slide records in our format, with `Author tier`, `Layout`, `Native-ready`, references chosen from the library's contact sheets; the PGA spec is the format exemplar. `template()` - the TEMPLATE stage (Sol @ medium): one SVG per layout the records name plus `template.md` (zones, type, grid, table / card / connector styling), used when provided, created otherwise, no approval gate; pages copy the layout's chrome group verbatim and all start at once (no anchor page). `deck_repair()` hands the deck review's findings to the pages' own sessions. Standing rule in all three briefs: WHAT YOU DO NOT KNOW, YOU DO NOT WRITE - people, CVs, credentials, client references and unproven results become `[To be provided: ...]` in a drawn slot of the final size, listed for the editor. Proposal rule: never enumerate the client's requirements.

**Gate.** `FORK_ACCEPTANCE_CHECKLIST.md` (what the user approved, 40 items) and `hosts/responses_api/acceptance.py` (30 automatic checks on the plan, the template, the configuration, the journal, the SVGs and the exported deck, including the PowerPoint before/after render of the export pass). `run_report.py` reports time and cost per step and per model.

**Result.** Main run 33.2 min wall, 10/10 accepted, 8 on the first draft; then two hand-started passes (deck repair with a fixed parser, one more repair of the Gantt) to 45.8 min. Cost USD 6.01: solution 0.26, planner 0.57, template 0.17, page authoring 4.12 (Sol @ medium 3.52 for seven sessions, DeepSeek 0.76 for four), 24 Grok reviews 0.89; the deck review's own call was not recorded by this run (about 0.05-0.10; recorded from now on). The planner marked six of ten pages frontier, which is where the money went. The tool's own answer: HKD 7.507m fixed for 595 days (my pre-solved one: 12.2m for 820), named components (Trust Gate, Agency Metric Catalogue, BU Performance Cockpit, Group Performance Lens, Data Trust Console, Ask Meridian), a scored pilot-BU selection method, a 30-question benchmark with stop / refine / progress for the pilot, and nine placeholders where the firm must supply people, credentials and declarations - including, unprompted, that the knowledge base cannot substantiate some compliance declarations. Acceptance: all automatic checks pass on the final deck (six native tables, 60 native list paragraphs, 19 glued connectors, chrome and a page-number field on one layout with a title placeholder, notes on every slide, body text at 1.36 x, no requirement enumeration, export pass moves at most 0.23% of ink).

**What broke, and what it taught.** (1) The planner wrote `- inventory: none` under `## images`; the checker read "none" as an image file and blocked the project; fixed by hand mid-run and in the planner brief. (2) The deck-repair parser expected a numbered list and Grok wrote dashes: "nothing addressed to a page"; fixed and re-run by hand - the four findings were real (a wrong folio, the fee written two ways, phase labels differing between two pages, an incomplete status sequence). (3) The deck repair spent the Gantt's last revision; its next review had no defect but asked for a polish and returned EXECUTION_REPAIR, leaving an accepted page `unresolved`; one more repair passed. Open design question: a deck-repair change should not be able to demote a page that had passed. (4) The acceptance run caught two pass bugs: the folio never became a field because the template's full-page white field counted as "painted under it" (chrome sitting on chrome now moves together), and a long list drifted 2-3 px because PowerPoint draws an exact line spacing at the NEAREST WHOLE POINT (12.75 pt is 13, 12.4 is 12 - measured over ten-line spans; now modelled). (5) Eyes on the final Gantt: bars, milestones and gates are labelled where they happen and the workstreams overlap, but the last repair left the phase header busy (REPEAT drawn three times, the week ruler on two levels) and one bar label is clipped at its end. It ships accepted; it is the page a human would touch first.

**Closing the day (no model calls).** Decisions from the user: a repair may not demote a page that had passed - built (`keep_or_restore` + `Runner.settle`: polish-only review keeps the repaired revision accepted; defects, a failed lint or no review restore the revision that had passed and keep the failed attempt's review; a change the user asked for is never rolled back); revise from my comments - built (`collect_annotations`, `revision_message`, `deck_runner.py --revise [--dry-run]`: the comments the live-preview interface stores on elements go to the annotated page's own author, then checker, export, final lint). Verified without a model: unit tests (23 pass), and on the Meridian project a comment posted through the preview server's own API was saved into the page, found by `--revise --dry-run`, addressed to the right conversation (Sol's Gantt session), then deleted through the API; the project's checker still passes. Set aside by the user: an independent review of the plan; templates with more than one master.

## Grok 4.7 and 4.6 as reviewer and as author — 22 September 2026

**Reviewer.** Grok 4.7 on the ten labelled pages: 10/10, no false PASS, no false alarm, 2/3 replans - identical to 4.6 - but 135 s and $0.052 a review against 73 s and $0.037 (its token price is 20% lower; it writes about 60% more). Kept 4.6.

**Author.** The Meridian architecture (P03) and Gantt (P07) re-authored from the same records, template and reviewer in copies of the project. Sol: 5.4 min / $0.40 / 0 revisions and 17 min (33 with later repairs) / $1.41 / 3 (5). Grok 4.7: 40 min / $5.66 / 2 and 30 min / $3.78 / 1. Grok 4.6: 17.7 min / $3.01 / 3 and 22 min / $3.50 / 1. All six pages accepted. Why Grok costs more: reasoning is 56-83% of its output (Sol 28-42%) - the 4.7 architecture page wrote 127k output tokens against Sol's 16k; its prompt cache hits 84-95% against Sol's 96-98%; two to three times more calls. Quality by eye: level - Sol's architecture the tightest, Grok 4.6's Gantt the clearest. Verdict: Sol stays the frontier author; Grok 4.7 is worse than 4.6 in both roles. Test copies: `projects/meridian-grok-author_20260922`, `projects/meridian-grok46-author_20260922`. Spend: $16.20 on the author runs, $0.52 on the benchmark.

## Claude Opus 5.5 as author — 23 September 2026

**Plumbing.** `hosts/responses_api/anthropic_backend.py` (new): when `PPT_MASTER_API_BASE` is `https://api.anthropic.com`, `host._call` sends the turn through the official `anthropic` SDK (Messages API, streaming): the host runs stateless, Claude's assistant content (thinking blocks included) is kept verbatim in the history as an `anthropic_assistant` item and sent back unchanged (append-only history), the system prompt and the conversation's end carry cache breakpoints, `output_config.effort` carries the effort, cost is computed from list price ($4 / $20, cache write $5, cache read $0.20 per M). Anthropic requires `max_tokens` on every request (OpenAI/OpenRouter do not, and we never set it): first set at 64k, too low - Opus spent one reply on 88k tokens of reasoning, was cut off with no tool call, and both pages stopped ($3.44 lost); now 128k (the model's maximum) plus recovery: a cut-off reply's unfinished tool call is dropped and never run, and the model is told to continue in smaller steps.

**Result** (Meridian P03 architecture, P07 Gantt; same records, template, Grok 4.6 reviewer). Opus 5.5 @ medium: architecture 12.2 min, 8 calls, 0 revisions, $2.71; Gantt 21.7 min, 12 calls, 1 revision, $3.54 - both accepted. Against Sol @ medium: 5.4 min / $0.40 / 0 and 17 min first pass / $1.41 / 3. Opus thinks first and draws once: single replies of 53k and 88k output tokens taking 9 and 14.5 minutes; its reasoning is carried forward, so it is billed again as cache writes. Quality by eye: the best architecture page of any author (clean numbered gate sequence, labelled lineage and security bands, legible type); the Gantt about level with Sol's (phase overlap drawn cleanly, but in the PowerPoint render two milestone labels collide and one card's text is clipped). Verdict: best quality on the hardest page, about 3.5x Sol's cost per frontier page and not faster; Sol stays the frontier author. A low-effort Opus run is the untested option. Decks: `ppt-master-runs/author-decks/` (four full decks and a 16-slide comparison deck).

**Opus 5.5 @ low (same test, 23 Sep 2026).** Architecture 5.0 min, 6 calls, 0 revisions, $1.05, accepted; Gantt 9.5 min, 9 calls, $1.29, left unresolved - the reviewer twice asked for milestone names at their weeks and Opus recorded `unresolved` with three revisions unused. Both pages $2.34 against Sol's $1.81. The user's verdict, having looked at the decks: Opus at low was not as good as Sol at medium and costs more - **Sol stays the frontier author**. The proposed "no early give-up" rule was not adopted. Comparison deck with five authors: `ppt-master-runs/author-decks/Meridian - architecture and Gantt by author (comparison, with Opus low).pptx`.

**Premium option.** The user asked for Opus 5.5 @ medium as the option for a special deck: `deck_runner.py --premium` authors the frontier pages with it (`PREMIUM_FRONTIER`); everything else is unchanged and Sol stays the default.

## GPT-6 Sol / Luna / Astra and Claude Fable 5.1 as authors — 23 September 2026

Same Meridian P03 architecture and P07 Gantt, same records, template and Grok 4.6 reviewer; seven runs in parallel. Slugs `gpt-6-sol` ($2 / $10), `gpt-6-luna` ($0.10 / $0.50), `gpt-6-astra` ($10 / $50), `claude-fable-5-1` ($10 / $50, via `anthropic_backend.py`).

| author | architecture | Gantt | both pages |
|---|---|---|---|
| GPT-5.6 Sol @ medium (today's default) | 5.4 min · 0 rev · $0.40 | 17 min first pass · 3 rev · $1.41 | $1.81 |
| GPT-6 Sol @ low | 4.5 · 0 · $0.22 | 10.3 · 2 · $0.40 · unresolved | $0.62 |
| GPT-6 Sol @ medium | 7.1 · 1 · $0.52 | 9.6 · 1 · $0.47 | $0.99 |
| **GPT-6 Sol @ high** | **4.9 · 0 · $0.44** | **8.4 · 0 · $0.50** | **$0.94** |
| GPT-6 Luna @ high | 32.6 (14 idle) · 1 · $0.09 | 26.3 · 2 · $0.18 | $0.27 |
| GPT-6 Luna @ xhigh | 12.9 · 1 · $0.06 | 18.1 · 1 · $0.09 | $0.15 |
| GPT-6 Astra @ medium | 10.3 · 0 · $1.83 | 11.7 · 0 · $2.28 | $4.11 |
| Claude Fable 5.1 @ medium | 11.5 · 0 · $4.75 | 46.8 (incl. a broken stream + resume) · 0 · $10.19 | $14.94 |

GPT-6 Sol @ high passed both pages at first draft at about half GPT-5.6 Sol's cost and half its Gantt time - the first model to beat the default on every axis; the frontier-author decision is the user's. Luna xhigh is the cheapest acceptable author measured ($0.15 for both pages) but slow. Found and fixed during the run: seven decks starting preview servers at once raced for one port (each project now starts its port search at its own offset and retries); a stream broken mid-reply by the peer was not retried by the SDK (now retried in `anthropic_backend._stream_with_retry`); a page left unresolved waits for the slowest sibling before the checker repair round (open). Deck: `ppt-master-runs/author-decks/Meridian - architecture and Gantt by author (all models).pptx`.


**Decision (23 Sep 2026).** The user made GPT-6 Sol @ high the frontier author (`deck_runner.DEFAULT_AUTHORS`, acceptance check 3.2).

## GPT-6 Sol @ medium as reviewer, and a fix pass on its findings — 23 September 2026

**Benchmark.** On the ten labelled renders GPT-6 Sol @ medium scored 8/10 as labelled, with no false PASS, 4/5 replans, 15 s and $0.023 a review; Grok 4.6 scored 10/10 at 54 s and $0.038 the same day. On inspection, Sol's two "false alarms" were real defects the labels had missed: a grey legend dot on the pga-sentinel-sol loop, and an ambiguous hub junction on the Harrowgate kimi page. Corrected, Sol is 10/10. **Decision:** the user made GPT-6 Sol @ medium the reviewer for every page and the deck review (`DEFAULT_REVIEWERS`, acceptance check 3.3). Grok 4.6 is the documented fallback.

**Self-review.** Sol @ medium re-reviewed the six GPT-6 Sol author pages that Grok had accepted. It returned repair or replan on all six, where Grok had passed three architecture pages. Its findings were real: only one source arrowed into ingestion, Trust Gate notes sat detached from their diamonds, Gantt text was tiny, and dependencies were written as text instead of drawn.

**Fix pass.** Each page's conversation was reopened and GPT-6 Sol @ high was given Sol medium's review as a user request (beyond the revision budget; `settle(user_change=True)`), then re-reviewed by Sol @ medium. Script: scratchpad `sol_fixes.py`.

| page | time | calls | author + reviews | Sol reviews | result |
|---|---|---|---|---|---|
| low · architecture | 9.5 min | 26 | $0.92 + $0.16 | 5 | PASS |
| low · Gantt | 21.4 min | 60 | $2.20 + $0.41 | 9 | still EXECUTION_REPAIR |
| medium · architecture | 8.0 min | 39 | $1.10 + $0.09 | 3 | PASS |
| medium · Gantt | 13.4 min | 47 | $1.40 + $0.26 | 6 | PASS |
| high · architecture | 8.2 min | 31 | $0.92 + $0.14 | 5 | PASS |
| high · Gantt | 8.2 min | 28 | $1.07 + $0.13 | 3 | PASS |

Five of six pages pass. The fix pass cost $8.81 against $2.55 for the original six pages. Visible gains: all three sources now arrow into ingestion, and the Gantts draw dependencies as connectors. The cost came from unbounded loops: with the budget lifted, one page took nine reviews and still failed. The stricter reviewer raises quality, and the revision budget is what keeps its loops affordable in normal runs. Deck: `ppt-master-runs/author-decks/GPT-6 Sol pages - before and after Sol-medium review.pptx`.

**Reverted the same day.** Having looked at the before/after deck, the user saw no real improvement from Sol's reviews and restored Grok 4.6 @ medium as the reviewer (`DEFAULT_REVIEWERS`, acceptance check 3.3, checklist 3.3). Sol ran on the same review harness as Grok, with no model-specific instructions. **Capped replay:** with the fix held to a fresh three-revision budget, the fix pass would have cost $5.13 instead of $8.81, and its slowest page would have taken 7.9 min instead of 21.4. But only two of the six pages (medium architecture, high Gantt) would have passed; the other four would have ended unresolved. Held to each page's own remaining budget, the cost would have been $4.64, with one pass. Script: scratchpad `capped_fix.py`. Caveat: an author told the budget still applies might pace its renders differently.

## Latency quick wins — 23 September 2026

The user approved the latency audit's quick wins. Three were built; one was measured and set aside.

- **Render in one browser.** `page_review.py render` draws the preview and measures the geometry lint in one Chromium, with the contract check running beside them in its own process (`page_lint.start_contract` / `finish_contract`). It falls back to the separate steps if the one-browser path cannot start. On copies of the Meridian pages, the preview pixels and every lint finding were identical, including a planted page with 15 findings and 2 contract errors. One render went from 11-12 s to 6-7 s. Ten renders at once went from 30 s to 19 s each.
- **A page's checker repairs start as soon as its author ends.** Each page's job now runs author, then the checker on its own file, then up to `--repair-rounds` repairs, then escalation of an unaccepted workhorse page, then its checker repairs (`Runner.after_author`). Nothing waits for the slowest sibling. The deck-wide checker still runs after all pages, sharing the same per-page repair budget. Tests cover the ordering and the shared budget.
- **16 pages at once** (`--max-parallel`, was 8): a 10-12 page deck no longer queues pages behind the first eight.
- **Template alongside the planner: not built.** On meridian1 the template stage took 0.9 min against the planner's 6.1 min, and it reads the planner's design system and layouts. Overlapping them would save under a minute and could let the template and the plan diverge.

Tests: 26 pass.

## kirkland1 — 23 September 2026 — a real request, an official template, 12 pages (setup)

**Why.** The user asked for a bigger, real-world stress test: a real published request with published evaluation criteria, about twelve pages, built on a clean official template, judged on content and logic as well as looks, with the full cost measured.

**The request.** City of Kirkland (WA), Smart City Master Plan Consulting Services, Job #25-22-PB (RFP of 18 April 2022, 37 pages, plus Addendum #1 with the City's answers), from kirklandwa.gov. It scores written proposals and finalist interviews on one 100-point table: experience of the firm and key staff 30, approach and methodology 40, cost 20 (fixed price per task with hours, hourly rates by role, at most $100K including contingency), references 10. The first draft of the plan is due by 1 August 2023. The pipeline sees only the RFP, the addendum, `request.md` (mid-May 2022, about twelve pages for the finalist interview) and a synthetic knowledge base for the fictional Tessellate (Seattle/Vancouver public-sector practice, USD hourly rate card, methods; no credentials, references or CVs - those must become placeholders).

**The template.** Microsoft's "Sleek corporate finance presentation" (create.microsoft.com; Microsoft's terms allow building content with it, not redistributing it - it stays under the git-ignored `projects/`). 58 layouts, 15 sample slides; white pages, one blue (#3B43D7), Raleway Medium headings and Century Gothic body, stock photographs. It is airy where our pages are dense: a test of style transfer as much as of layout.

**Built for it.**
- `deck_runner.py --base-template <.pptx|.potx>`: the template is copied into the project, rendered by PowerPoint, imported (`pptx_template_import.py`), its layouts drawn to PNG, and summarised in `sources/base-template.md` (theme, layouts with renders and placeholders, sample slides). The template stage then reproduces its layouts in our format instead of designing its own (`BASE_TEMPLATE_BRIEF`).
- Fonts: for each theme font the browser cannot draw (here Raleway, which exists only in Office's cloud-font cache), the real font is measured from that cache and the closest installed stand-in at least as wide is named (Century Gothic, 2% wider). This keeps the previews and the lint on the safe side of PowerPoint.
- `hosts/responses_api/evaluate_proposal.py`: an evaluation panel from another model family (Claude Opus 5.5 @ medium) scores the exported deck as PowerPoint draws it. It covers each RFP criterion with its weight, logic, consistency (it recomputes totals), integrity (inventions against the knowledge base; placeholders are not penalised), template fidelity and visual quality. Beside that, it measures the fonts and colours the PPTX actually uses against the template's theme.

**Run.** `deck_runner.py projects/kirkland-smart-city_20260923 --session kirkland1 --base-template ...` with the defaults: GPT-6 Sol @ high (solution, planner, template, frontier pages), DeepSeek V4.1 Flash (workhorse pages), Grok 4.6 reviewing, 16 pages at once, the new per-page repairs and one-browser render.

**Result.** The first attempt stopped at the template stage. The template ran under the page authors' system prompt, which says never to edit the templates, and GPT-6 Sol @ high obeyed it and wrote nothing (GPT-5.6 Sol had ignored that line on meridian1). Fixed: the template stage now gets its own system prompt (`template_brief_system`, with a test). The attempt was stopped and resumed from the template stage; it cost $0.11.

| step | time | cost |
|---|---|---|
| base template preparation (import, PowerPoint render, layout renders, font check) | about 1 min | none |
| solution (GPT-6 Sol @ high) | 2.9 min | $0.25 |
| planner | 5.0 min | $0.67 |
| template (reproduces the official Title and Content layouts) | 1.7 min | $0.36 |
| 12 pages in parallel (9 Sol, 3 DeepSeek); slowest the Gantt, 10.1 min | 10.4 min | $3.60 authors + $0.55 Grok reviews |
| deck-wide checker, deck review and repair, export, final lint | 6.7 min | $0.06 deck review |
| **run total** | **about 28 min** of model work from request to deck (18.8 min from the template stage) | **$5.49**, plus $0.11 for the aborted attempt |
| evaluation panel (Claude Opus 5.5 @ medium) | 1.7 min | $0.40 |

**Pipeline outcomes.**
- All 12 pages were accepted on a PASS: 8 at their first draft, 4 after one revision.
- The checker had nothing to repair.
- The deck review caught two real cross-page errors, and both were fixed by the pages' own authors:
  - a folio showing 7 on page 6;
  - a maximum fee of $98,720 on pages 11 and 12, which should be $98,920.
- The final lint found nothing open, and every automatic acceptance check passed.
- The solution's fee reconciles exactly:
  - by role: 512 hours from the rate card, $94,120;
  - by task: the same $94,120;
  - with the $4,800 contingency, $98,920, which is $1,080 under the City's ceiling;
  - the first draft is due at W44 (June 2023), ahead of the 1 August 2023 deadline.

**The panel's scores** (`projects/kirkland-smart-city_20260923/.review/proposal_evaluation.md`):

| measure | score |
|---|---|
| RFP-weighted score | 50% |
| experience | 3/10 |
| approach | 6/10 |
| cost | 8/10 |
| references | 1/10 |
| logic | 7/10 |
| consistency | 9/10 (every total and week recomputed and found to agree) |
| integrity | 9/10 (no inventions; 11 placeholders, all where a reader expects them) |
| template fidelity | 7/10 |
| visual quality | 5/10 |
| verdict | not shortlisted as it stands |

Measured, after the fix to the count: 100% theme fonts; 74% of colour uses in the palette.

**What the panel found, in the order it matters.**
1. 40% of the marks (experience and references) are empty by design: the knowledge base has no credentials, CVs or references.
2. Internal notes leak onto client-facing slides: "Submission blocker", "not ready to file", "must be inserted before submission".
3. The approach narrows to a data-and-metrics thesis. It has no Kirkland definition of "smart city", no vision tied to the 11 Council goals, no best-practice or policy layer and no regional role. Two slides go on an ITS-count example the RFP did not ask for.
4. The effort looks too low for a year's work: 512 hours, 2 Partner days, 68 hours to write the plan. The solution sized the effort to fit under the cap.
5. Content-free figures: 30 cells reading "To assess" on page 4, and the same brief row repeated three times on page 7.
6. The Gantt is hard to read: labels over bars, colliding week ticks. Grok passed it.
7. Template departures: none of the template's picture layouts are used (no images were available), and an amber accent sits off the palette.

## Why kirkland1 was thin, and the prescriptive planner — 23 September 2026

**The user's verdict on kirkland1:** ugly, and not as dense as we like. Measured on the PowerPoint renders against meridian1:

| per body slide (median) | meridian1 | kirkland1 |
|---|---|---|
| words on the slide | 407 | 241 |
| body area not white | 52% | 22% |
| body area in tinted fills | 35% | 10% |

**Causes, in order of weight.**
1. **The plan was thin: 246 words of Content per record against Meridian's 484.** The planner is the frontier author, so it switched to GPT-6 Sol with the frontier default; it had only been tested drawing pages. On the same solution, GPT-5.6 Sol @ high planned 308 words and a 60% longer figure description ($0.59, 6.1 min, `projects/kirkland-plan56_20260923`). So the model explains part of the gap. A thinner solution (5,400 against 7,700 words) and a less concrete RFP explain the rest.
2. **Our own brief asked for a "plain-text sketch, no coordinates".** GPT-6 obeyed it and placed nothing; GPT-5.6 had placed zones anyway on Meridian.
3. **The template stage carried Microsoft's airy style** as instructed: a deeper title zone, near-white lavender fills, pale connectors.
4. **Century Gothic is about 10% wider than Segoe UI.**
5. **Nothing enforced density.** Grok passed 8 of 12 pages at their first draft.

**Built (the user's go-ahead).**
- **PRESCRIPTIVE RECORDS in the planner brief:**
  - a word budget for each body page, measured from Meridian's liked density and scaled to this deck's body zone and body-font width (`Runner.page_capacity`; Kirkland: 390 words, band 331-448);
  - `Fill` with every zone as x/y ranges;
  - `Visual scaffold` element by element: kind, zone, the Content it carries, type role, colour token, connections;
  - no filler grids or repeated rows;
  - internal notes only in `Editor notes`;
  - a supplied template never lowers density.
- **Example records in the planner's prompt:** Meridian's architecture, Gantt and fee-table records (`hosts/responses_api/planner_examples/`). Take their precision, never their content. The Gantt's symbol legend was removed, following the user's rule on timelines.
- **`plan_lint` plus one repair turn** in the planner's own conversation. It flags records under the budget, without placed zones, with a thin element list, with filler or repeated rows, with internal notes in client copy, or missing fields. On the existing plans it flags all 12 GPT-6 records, all 12 GPT-5.6 records and 3 of Meridian's. Tests: 29 pass.

**Result: GPT-6 Sol @ high, same Kirkland solution** (`projects/kirkland2-smart-city_20260923`). $0.95, 7.6 min, with one record sent back once and then clean.

| per body record (median) | GPT-6 before | GPT-5.6 | GPT-6, new brief | Meridian |
|---|---|---|---|---|
| Content words | 246 | 308 | **393** | 484 |
| Visual scaffold words | 46 | 74 | **168** | 107 |
| coordinates placed | 0 | 0 | **20** | 6 |

Its lock now reads: "increase density through meaningful native tables, operating diagrams and a fully labelled five-stream Gantt rather than compressing line spacing".

**kirkland2: the deck from the prescriptive plan** (same solution and template; `projects/kirkland2-smart-city_20260923`).

| | kirkland1 | kirkland2 |
|---|---|---|
| words per body slide (median, in the PPTX) | 241 | 332 (Meridian 407) |
| body area not white | 22% | 52% (Meridian 52%) |
| body area in tinted fills | 10% | 30% (Meridian 35%) |
| pages accepted on a PASS | 12 of 12 | 11 of 12 (the Gantt unresolved after 3 revisions) |
| page stage (wall) | 10.4 min | 25.5 min |
| cost from the planner to the final lint | $5.24 | $9.14 |
| panel: RFP-weighted score | 50%, not shortlisted | **64%, shortlisted** |
| panel: approach / cost / experience / references | 6 / 8 / 3 / 1 | 8 / 9 / 4 / 2 |
| panel: logic / consistency / integrity / template / visual | 7 / 9 / 9 / 7 / 5 | 8 / 9 / 9 / 7 / 6 |

Why it was slower: denser pages. Two DeepSeek pages took 23-25 minutes each (P04, 33 turns, with calls of up to 46 s; P10), and the Sol Gantt used all three revisions in 20 minutes. The evaluation cost $0.37.

**New problem found by the panel: the export breaks pages the preview shows as clean.**
- Verified on P04: in the browser preview, the table and the two boxes below it fit. In PowerPoint, the native table's rows grow to fit Century Gothic's line height, and the fifth row slides under the boxes.
- The panel also found clipped text on P03, P06, P11 and P12. These are probably the same class of problem (text metrics that differ between the browser and PowerPoint), but that has not been verified page by page.
- The lint and the reviewer judge the browser render, so neither can see it. Acceptance check 6.10 (the export moves nothing) needs the PowerPoint render and was run with `--no-render`.
- Open: compare every page's PowerPoint render with its preview after export, and send differences back to the page's author, or fix row heights at export.

## GPT-6 Luna @ high as workhorse author against DeepSeek V4.1 Flash — 24 September 2026

Eight workhorse pages, two from each of four decks. Luna re-authored each page on a copy of its deck, with only that page removed. Everything else was the same: plan, template, Grok 4.6 reviewer, the page-by-page runner, no escalation. DeepSeek's pages are the ones that shipped. Script: scratchpad `luna_workhorse.py`. Deck: `ppt-master-runs/author-decks/Workhorse pages - GPT-6 Luna high vs DeepSeek.pptx`.

| page | DeepSeek first pass, author cost | Luna first pass, author cost |
|---|---|---|
| Meridian P08 team and governance | 6.0 min, 0 rev, $0.29 | 12.7 min, 0 rev, $0.04 |
| Meridian P09 fee | 6.2 min, 0 rev, $0.16 | 13.0 min, 0 rev, $0.06 (2 table-parity repairs after export) |
| Kirkland P04 inventory | 25.2 min, 2 rev, $0.20 | 19.5 min, 3 rev, $0.07 |
| Kirkland P10 roles | 23.2 min, 0 rev, $0.14 | 8.6 min, 0 rev, $0.03 |
| PGA P03 workflow today | 4.8 min, 0 rev, $0.08 | 8.4 min, 0 rev, $0.03 (table-parity repair) |
| PGA P07 target operating model | 4.8 min, 1 rev, $0.06 | 7.4 min, 0 rev, $0.04 (table-parity repair) |
| Harrowgate P02 executive summary | earlier single-conversation harness | 10.4 min, 1 rev, $0.06 |
| Harrowgate P03 study arrangements | earlier single-conversation harness | 36.0 min, 2 rev, $0.17 |

**The six comparable pages:**
- **Author cost:** $0.93 for DeepSeek, $0.27 for Luna.
- **Review cost:** $0.41 against $0.52. Luna's pages needed more reviews: its native tables failed the exporter's parity check three times, where DeepSeek's did not.
- **First-pass time:** median 6.1 against 10.7 min; mean 11.7 against 11.6. Luna is slower where DeepSeek's pinned fast hosts are quick (Meridian, PGA), and faster on the dense Kirkland pages, where DeepSeek took 23-25 min.
- **First-draft passes:** 4 of 6 for DeepSeek, 5 of 6 for Luna.

**Harrowgate:** the old project's layered pages cannot go through the current flat exporter. Luna's two Harrowgate pages are shown as their browser previews.
**Runner gap found:** when only project-level checker issues remain, the export override is not applied, so the export fails. Open.

**Decision (24 Sep 2026): GPT-6 Luna @ high is the workhorse author** (the user, on the look). `DEFAULT_AUTHORS["workhorse"]`, acceptance check 3.2 and checklist 3.2 are updated. DeepSeek V4.1 Flash, pinned to fast hosts, stays the documented alternative.

**Exportability, clarified.**
- Luna's pages were not what failed to export. The Harrowgate project declares the old `pptx_structure: structured` mode with layered layout attributes, which the current exporter rejects. Luna copied those attributes from the deck's existing pages, and DeepSeek's own Harrowgate pages would fail the same way today.
- Exported flat on their own (with the old layout attributes stripped), Luna's two Harrowgate pages render cleanly in PowerPoint: `projects/harrowgate-lunawh-pages_20260924`.
- Luna's native tables did fail the exporter's text/JSON parity check three times, where DeepSeek's did not; the pages' own repair fixed each one automatically.
- Runner gap fixed: deck-level (`_project`) checker items now also export through the override and are listed in `.outstanding.md`, instead of failing the export. Tests: 29 pass.
## Failure modes across models and runs, and the low-risk fixes — 24 September 2026

Three read-only analyses:
- Luna: `scratchpad/failure_luna.md`, 12 Luna pages;
- pages: `scratchpad/failure_pages.md`, 150 page records from 16 model/effort groups, with a model x category matrix and dedicated GPT-6 Sol and Luna sections;
- system: `scratchpad/failure_system.md`, deck and pipeline level.

**Top failure modes (evidence in those files).**
1. **Chrome contract error on the first render: 53 of 59 pages, every model.** The template's `<g id="chrome">` had no `data-pptx-role="chrome"`, and "copy verbatim" was in the job. Luna gave up once over it.
2. **Timeline milestone names and dependencies put in a strip or list instead of on the chart.** 10 of 12 authors on the same Meridian record; GPT-6 Sol on 4 of 5 Gantts.
3. **Dirty first drafts:** text overflow and tight leading. Luna 12/12, GPT-5.6 Sol 16/19, GPT-6 Sol 8/19, DeepSeek 7/27.
4. **Defects that exist only in PowerPoint** (native table rows grow, clipping, list renumbering): 4-6 of 12 kirkland2 pages. No in-loop check sees them.
5. **Native-table parity refusals at export:** Luna 3 of 5 table pages, DeepSeek 7/42, Sol 3/19.
6. **Revising after a PASS** (Sol 4/19), and give-ups on 0-blocker taste items.
7. **Tool misuse** (Luna: 18% of edit calls failed - misspelled paths, stale edits) and model-chosen timeouts killing paid reviews (6 cases).
8. **Deck level:**
   - the solution is too narrow, with effort sized to fit the fee cap;
   - pages not self-contained: abbreviations, week codes and shorthand;
   - very small type;
   - the deck-repair parser missed bare page numbers;
   - the deck reviewer works from low-resolution thumbnails.

**Ranked by impact against regression risk; the low-risk ones were built.**

| fix | impact | regression risk | built |
|---|---|---|---|
| runner adds `data-pptx-role="chrome"` to every template chrome group; template and author briefs say so; the lint message names the fix | high (53/59 first renders) | low (deterministic, exactly what the contract asks) | yes |
| exporter's native-table check runs in the render's lint (`native_parity.py`, in the background, only on pages with a native object) | high for Luna | low (the same gate the exporter applies; verified on the revisions it refused, and clean on the repaired ones) | yes |
| host timeout floor of 1200 s for the author's `run_script` | medium | low | yes |
| author "known failure modes" section: relationships drawn not written, text fit estimate, leading at least 1.4x, native-table text rules, never silence the lint, tool hygiene, stop at PASS, field names are not labels, read without a presenter | high (all authors) | low (restates rules the contract and review already enforce) | yes |
| job no longer tells authors to read template.md, which is already in the system prompt | low-medium | low | yes |
| self-contained decks: the planner's THE READER HAS NO CONTEXT contract; `undefined_terms` in the plan check (abbreviations before their expansion, week codes never explained, references to documents the reader does not have); the deck review's SELF-CONTAINED look; the evaluator's self-containment score | high (the user's principle) | low-medium (one more planner repair turn on most runs) | yes |
| solution brief: cover the whole request, size effort from the work, write for a reader with no context | high (panel scores) | low-medium | yes |
| timeline rule in the planner: marker labels at their week, dependencies as arrows, no restating strip | medium | low | yes |
| deck-repair parser also reads "page 7", "slide 7" and a bare "07," at the start of an item | low-medium | low | yes |
| compare each page's PowerPoint render with its preview after export and send differences to the page's author | high | medium (noisy image diff; needs design) | next |
| minimum type size lint | high for legibility | trades against density - the user's call | needs decision |
| accept an EXECUTION_REPAIR with 0 blockers | medium | medium (quality) | no |
| higher-resolution deck review input; deck-level cross-page text checks | medium | medium | later |

Tests: 31 pass.

## selfdoc — 24 September 2026 — PPT Master documents itself (gist brief)

**Setup.**
- Brief: https://gist.github.com/papuga200/44b07f9f53cad8406d67bbe79f39f451.
- Two routes on a clean runtime copy (`D:\Users\software\ppt-master-selfdoc-20260924`), with a separate read-only reference copy of the fork as the subject.
  1. The Create Template route, run as one conversation with GPT-6 Sol @ high.
  2. The deck runner with `--base-template <template workspace> --brief document`.
     - Authors: Sol for frontier pages, Luna @ high for workhorse pages.
     - Reviewer: Grok 4.6 @ medium.
- Gates were delegated. Full record: `D:\Users\software\ppt-master-runs\selfdoc-20260924\` (`SELFDOC_TEST_REPORT.md`, `SUPERVISOR_LOG.md`, `run_record.json`).

**Template:**
- "System Atlas": original and coherent;
- native Master with 8 Layouts;
- USD 1.12.

**Run 1, first export: 12 slides, USD 5.35, 29.4 min.**
- The deck used Calibri, not the template's fonts, because the harness read the PPTX theme, which is the Office default for a generated template.
- It used 3 of 8 layouts.
- Opus 5.5 evaluation: self-containment 4, factual 8, narrative 6, visual 4, template reuse 5.
- Claims audit: 0 wrong, 0 unsupported, 14 imprecise.

**System fixes after run 1:**
- `template_styles_used` takes fonts and colours from what the template's slides use, and treats a file as default only when all its themes are;
- layouts are listed by the name to use;
- `newcomer_read`: one reviewer call listing what a reader with no context cannot follow, fed to the plan repair;
- `--brief document` sets density at 0.75 of proposal density;
- `DOCUMENT_BRIEF`: value first, a worked example, licences and data flow, limits stated once.

**Run 2 was stopped (USD 3.16).** It read run 1's outputs, including the supervisor's evaluation, from the shared `projects/` folder. The outputs were isolated, and the content brief now says other projects' outputs are not evidence. A host-level read restriction is open.

**Also fixed before run 3:**
- the plan-check field regex (a bracketed note after a field name);
- `page_capacity` uses the slides' body font.

**Run 3, final: 13 slides, USD 6.41, 37.0 min.**
- Scores: self-containment 6, factual 7, narrative 7, visual 5, template reuse 7.
- 6 of 8 layouts; the template's fonts and palette.
- 0 wrong or unsupported claims.
- Remaining:
  - PowerPoint-only collisions and clipping on about 8 slides;
  - a wrong folio on slide 8;
  - an incomplete licence list (EbookLib AGPL, edge-tts LGPL, CC BY icons);
  - no upstream MIT attribution;
  - runner-only features described as default;
  - small type;
  - the exported PPTX theme is still the Office default.

**After run 3:** a FOLIO certain-defect check in `page_lint.py`. This is the fourth deck with a wrong page number. 33 tests pass.

**Open, ranked:**
1. Compare each page's PowerPoint render with its preview after export, and send the differences back to the page's author.
2. Write the template's colours and fonts into the exported theme.
3. A host-level read restriction between projects.
4. Minimum type size (the user's call).
5. Upstream attribution in the content brief.

## meridian-final-a / meridian-final-b — 29 September 2026 — the optimisation campaign's two final demonstrations

**Setup.**
- Frozen commit 182c2170 on `campaign/optimization-20260929`, after ten failure families and two qualification rounds. F01 cycle 2 fixed the Luna page losses found in round 2.
- Each run had its own detached worktree (`ppt-master-final-a` / `-b`), holding only `projects/meridian-final/sources`: the Meridian request, RFP, compliance annex, response workbook and firm knowledge base, hash-checked against the freeze.
- Both used the curated reference library and `--brief proposal --max-parallel 4 --max-turns 40 --revision-budget 2 --repair-rounds 2 --no-escalate`.
- The runs went one after the other, with no intervention.
- Evidence: `ppt-master-runs/campaign-20260929/final/`: `freeze_manifest.*`, `readiness.md`, `run_a_assessment.md`, `run_b_assessment.md`, `comparison.md`, `run_*_report.md`, and the sessions.

**Run A: Claude subscription, Opus 5.5 high in every role.**
- 88.4 min; 16 slides, 15 accepted.
- Parity 15 -> 0; consistency 0.
- 334 calls; USD 91.15 notional (billed 0); about 16% of the Claude five-hour window.
- Meets the frozen criteria: every dimension 3 at deck level; the price reconciles exactly by grade and by workstream; dates, placeholders and pilot evaluation all check.
- Notes: P12's title is cut short; P13's grade headers are offset from their bar segments.

**Run B: Codex subscription, GPT-6 Sol high (planning, frontier pages, reviews) and GPT-6 Luna high (workhorse pages).**
- 90.8 min; 16 slides, 13 accepted.
- Parity 3 -> 0; consistency 0 certain.
- 581 calls; USD 7.41 notional (billed 0); Codex weekly window 46% -> 50%.
- Accurate and cleanly drawn, but it does not meet the pass rule. D1 and D2 are at 2: the executive answer carries no price or direct ask, the ask is hedged ("consider ... not an award or contract"), and internal instructions leak into client copy.

**What this establishes.**
1. The fork produces a client-grade 16-slide proposal from an RFP, unassisted, on a subscription route.
2. Accuracy, consistency and export fidelity now hold on both routes. The remaining gap between routes is persuasive planning and writing.
3. The per-page "wall" column in the runner summary spans a page's first to last session, including deck repair. It overstates page time; use `run_report.py` for stage times.
4. Opus cost is dominated by resumed long sessions: deck repair and planner repair are 42% of Run A's notional cost.
