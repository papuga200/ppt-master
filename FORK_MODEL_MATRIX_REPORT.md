# Model matrix — 19 September 2026

Four authors, one task. Same project inputs as cq-brief2 (`harrowgate-brief` records, bcg-proposal template, lock, sources, chosen references), same profile (render-and-look loop, independent reviewer in the loop, deck review, export, PowerPoint inspection), same reviewer for all four (`gpt-5.6-luna` at `high`, a fresh call per revision). Only the author changed. Sessions in `D:\Users\software\ppt-master-runs\` (`cq-brief2`, `mx-sol`, `mx-kimi`, `mx-deepseek`); the numbers below are from `hosts/responses_api/report.py` over the transcripts and journals. One run per model — a clear gap means something, a small one does not.

## The question

Is Luna the ceiling, or is the workflow? Answer: **both, and separably.** Every model completed the workflow end to end and honoured the reviewer gate, so the workflow holds across models. But the models differ sharply in first-draft quality and in how they repair, and that difference shows on the slides. Luna is the weakest author of the four on design; it is not the workflow's fault, and a better author does not remove the workflow's remaining faults either.

## Results

| | Luna @ high | Sol @ medium | Kimi K3 @ high | DeepSeek V4.1 Flash @ high |
|---|---|---|---|---|
| pages accepted (PASS review) | 0 of 4 | 2 of 4 | **4 of 4** | 2 of 4 |
| review verdicts | 2 PASS / 12 repair | 5 PASS / 10 repair | 8 PASS / 5 repair | 3 PASS / 9 repair / 2 replan |
| API calls | 114 | **80** | 115 | 133 |
| wall time | 28 min | **24 min** | 60 min | 120 min |
| API latency per call (est.) | 8 s | 11 s | 26 s | 49 s |
| input tokens (cached) | 17.6M (99%) | **9.9M** (98%) | 17.1M (96%) | 49.4M (99%) |
| output tokens | 81k | **40k** | 103k | 277k |
| reasoning share of output | 34% | 24% | 64% | 84% |
| peak context | 260k | **183k** | 248k | 540k |
| cost | $0.50 | $2.74 | $7.92 | **$0.40** |
| tool calls | 274 | **126** | 136 | 157 |
| edit_file calls | 163 | **31** | 32 | 35 |
| failed tool calls | 14 | **4** | 13 | 5 |
| reads of script source | 0 | 0 | 0 | 27 |

Costs: OpenRouter's own figure for Kimi and DeepSeek; list price for Luna and Sol (Sol at $2/M input, $10/M output).

## The slides (my judgment; the exported PowerPoint renders are in `projects/harrowgate-mx-kimi_20260919/.review/compare_model_matrix.png`)

**Architecture — the page that decides it.**
- **Kimi**: the record's picture. The hub is the only filled shape; all five sites converge into it on real connectors; wave two as same-size dashed boxes with dashed connectors; steering band across; the path crosses the boundary once; controls in outlined boxes; the staffing line moved clear. Accepted after 5 revisions. Best page of the day.
- **Sol**: cleanest execution of any run — no collisions, no prototype leftovers — but the sites reach the hub by one bus line, so "everything connects to the hub" is faint. Unresolved with one real item left (a sentence past the boundary).
- **Luna**: the prototype's stacked tiers with connectors through the site labels. Unresolved.
- **DeepSeek**: stacked tiers, numbered badges, the steering committee rotated down the right edge — the prototype's furniture. The reviewer nevertheless returned PASS on its fourth revision, which is the reviewer's noise cutting the other way.

**Timeline.** Sol's is the most legible (gates on the track, decision boxes tethered below in their own band, the month-six outcome as a box at the track's end). Kimi's is close. Luna and DeepSeek both float the gate callouts above the track.

**Executive summary.** Sol, Kimi and DeepSeek all drew the record's unboxed label column; Luna alone drew the template's filled label blocks. Kimi's passed on its first draft, the only page in any run to do so.

**Cover.** Sol and Kimi clean. DeepSeek shipped the prototype's stray "Proposal & Report" label and left the metadata in the title field.

Ranking on the deck: **Kimi ≳ Sol > Luna ≈ DeepSeek.**

## Behaviour

**Luna thrashes.** 163 `edit_file` calls against 31–35 for the others, 274 tool calls against 126–157, 14 failed calls, up to 17 tool calls in one turn, and 8 re-reads of its own pages. It repairs by many small patches, and its repairs on the architecture went sideways. High reasoning effort did not buy judgement; it bought edits.

**Sol is economical.** Fewest calls, fewest tokens, smallest context, fewest edits and failures, lowest reasoning share — and the cleanest execution. It reads the docs (15 skill-doc reads, the most), writes a page, fixes once. It is the model that follows the workflow as written. It did not draw the strongest concept.

**Kimi reasons its way to the picture.** 64% of its output is reasoning; 26 s a call; one hour. It is the only author that drew the architecture the record described and the only one to pass every page. It also recovered a port collision on its own (`--shutdown`, restart). Its cost is the price of that reasoning: $7.92, sixteen times Luna.

**DeepSeek reads code instead of docs.** 27 reads of the checker's and exporter's Python source (~5,000 lines) before drawing anything; 84% reasoning; a 540k-token context; 49M input tokens; two hours. Then a workmanlike deck, better than Luna's on two pages and worse on two, for 40 cents. It drew the only two `CONCEPT_REPLAN` verdicts and did redraw after them. Cheapest by far and slowest by far.

**Tool use was reliable on all four.** No page-name slips, no HTTP errors, one or two `--help` probes each, one text-only turn each. Stateless transport (resending the whole history through OpenRouter) worked without incident and cached at 96–99%.

## What this settles

1. **Luna is a bottleneck for design.** Two models produce better first drafts and better repairs on the same inputs. The workflow was not what held cq-brief1/2 back on the architecture page; the author was.
2. **The workflow holds across models.** Four authors, four complete runs, every `accepted` backed by a `PASS`, every `unresolved` with the reviewer's items named. The gate did its job for all of them.
3. **The reviewer's noise is model-independent and is the next thing to fix.** It passed DeepSeek's stacked-tier page and held Sol's clean timeline on nuances — the same precision problem seen on cq-brief2, now with a false pass as well as false blocks. The six fixes in the cq-brief2 entry stand; the closed blocker class and zoomed crops matter most.
4. **Cost-quality frontier.** Sol at medium is the sensible default: near-Kimi quality at a third of the cost and 40% of the time, and the least wasteful behaviour. Kimi at high is the quality ceiling of this set when the hour and the dollars are acceptable. DeepSeek Flash is the budget option only when wall time is free. Luna at high is dominated.
5. **Effort is not the lever.** Sol at medium beat Luna at high on every measure that matters. Model choice moved quality; effort moved cost.

## Caveats

One run per model, on one four-page deck, with hand-written records. Same-model variance was already visible between cq-brief1 and cq-brief2. A second run of Sol and Kimi would firm up the ordering; a run of Sol at high would say whether Sol has more headroom.
