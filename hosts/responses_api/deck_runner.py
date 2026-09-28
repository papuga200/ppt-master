#!/usr/bin/env python3
"""Author a planned deck page by page, in parallel, each page in its own small conversation.

    python hosts/responses_api/deck_runner.py projects/<project> --session NAME
        [--authors authors.json] [--max-parallel 16] [--pages 03 05] [--max-turns 60]
        [--no-anchor] [--no-escalate] [--skip-export]

Why. One conversation for a whole deck re-reads everything it has ever seen on every call: on a
nine-page deck the context reached 330k tokens and 81% of the bill was cached re-reading
(FORK_RUN_LOG.md, pga-sol). The plan already carries the design thinking - `design_spec.md` §IX holds a
complete slide record per page - so a page author needs the contract, the design system and its own
record, nothing else. Pages become independent, so they run at once, and a page can go to the model
its difficulty deserves.

What it does.
1. Reads the project's §IX: one page per `#### Slide NN - name` block, its `Author tier` line
   (`frontier` or `workhorse`; workhorse when absent), its role, title and core message.
2. Builds ONE system prompt for every page author: the page-author brief, the contract documents
   inlined, the design system (§I-§VIII), the §IX note and Narrative, a one-line digest of every page,
   the lock and the text calibration. It is identical across pages, so the provider caches the prefix.
3. Starts the preview server once, then authors the ANCHOR page first (the first page that is not a
   cover, by the frontier author): its header, title zone and footer are the chrome every other page
   copies exactly. Continuity across isolated authors rests on: that chrome, the design system and
   lock, the Narrative's continuity rules, and the deck digest.
4. Fans out every other page in parallel, each to its tier's author (`authors.json`).
5. Runs the final checker; pages with blocking issues get a targeted repair message in their own session,
   in parallel, for up to `--repair-rounds` rounds. When that budget is spent the deck is exported anyway
   (the exporter's nonconforming-export override) and the open items are written beside it; `--strict-export` refuses instead.
6. Escalates a workhorse page that ended `unresolved` to the frontier author (fresh session, fresh
   revision budget, the reviewer's remaining items in hand).
7. Deck review (one fresh reviewer call over the contact sheet; report only), finalize, export, render
   the PPTX, and a summary: per page tier, model, calls, time, cost, outcome.

Nothing here decides design: the page loop, the reviewer gate and the contract are the skill's own.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = Path(__file__).resolve().parent / "host.py"
SKILL = ROOT / "skills" / "ppt-master"
SCRIPTS = SKILL / "scripts"
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_AUTHORS = {
    # GPT-6 Luna @ high since 24 Sep 2026 (user's decision, on the look): eight workhorse pages from four decks re-authored against
    # DeepSeek V4.1 Flash - author cost $0.27 vs $0.93 on six comparable pages, 5 of 6 passed at first draft (DeepSeek 4), mean
    # first pass 11.6 vs 11.7 min (FORK_RUN_LOG.md). Was deepseek/deepseek-v4.1-flash @ medium via OpenRouter pinned to
    # Modal -> Together -> Venice -> GMICloud; that entry remains the documented alternative.
    "workhorse": {"model": "gpt-6-luna", "effort": "high",
                  "api_base": "https://api.openai.com/v1", "key_var": "OPENAI_API_KEY"},
    # GPT-6 Sol @ high since 23 Sep 2026 (user's decision): on the Meridian architecture and Gantt it passed both at first draft for
    # $0.94 and 8.4 min on the Gantt, against GPT-5.6 Sol @ medium's $1.81 and 17-33 min (FORK_RUN_LOG.md).
    "frontier": {"model": "gpt-6-sol", "effort": "high",
                 "api_base": "https://api.openai.com/v1", "key_var": "OPENAI_API_KEY"},
}
# `--premium`: the frontier pages go to Claude Opus 5.5 @ medium instead of Sol - the best-looking hard pages we measured (Meridian
# architecture and Gantt, 23 Sep 2026) at about 3.5x Sol's cost per frontier page and no faster. Kept for decks where the look matters
# more than the bill; Sol stays the default. Direct Anthropic API (anthropic_backend.py), key ANTHROPIC_API_KEY.
PREMIUM_FRONTIER = {"model": "claude-opus-5-5", "effort": "medium", "api_base": "https://api.anthropic.com", "key_var": "ANTHROPIC_API_KEY"}
# The reviewer of a page comes from another model family than its author: a second pair of eyes with different blind spots.
# Chosen on ten labelled renders with the lint's findings attached (reviewer_bench, 20 Sep 2026; FORK_RUN_LOG.md): Gemini 3.8 Flash 9/10
# right, no false PASS, 10 s, $0.007 a review; Grok 4.6 10/10 and the only strong reviewer that called the structurally wrong figures
# CONCEPT_REPLAN, 73 s, $0.04 (Kimi K3 10/10, 43 s, $0.03 is the alternative). OpenRouter refuses Google and Anthropic models for this
# account, so Gemini goes through Google's own endpoint.
DEFAULT_REVIEWERS = {
    # Grok 4.6 @ medium (user's decision, restored 23 Sep 2026). GPT-6 Sol @ medium was tried as the reviewer the same day: accurate on
    # the labelled pages, 15 s and $0.023 a review, but stricter than Grok - on six pages it rejected everything, and the fixes it asked
    # for did not read as improvements to the user while costing $8.81 in author repairs. Sol stays the tested alternative.
    "workhorse": {"model": "x-ai/grok-4.6", "effort": "medium", "api_base": "https://openrouter.ai/api/v1", "key_var": "OPENROUTER_API_KEY",
                  "provider": {"sort": "throughput"}},
    "frontier": {"model": "x-ai/grok-4.6", "effort": "medium", "api_base": "https://openrouter.ai/api/v1", "key_var": "OPENROUTER_API_KEY",
                 "provider": {"sort": "throughput"}},
}
# The contract a page author needs for a flat, shapes-and-text page. Anything else it may still read_file.
CONTRACT_DOCS = [
    "references/executor-base.md", "references/shared-standards-core.md", "references/semantic-svg.md",
    "references/native-shape-authoring.md", "references/preset-shape-vocabulary.md", "references/topology-assembly.md",
    "references/executor-table.md", "references/native-data-interface.md", "references/consulting-typesetting.md", "references/consulting-review.md",
    "references/svg-image-embedding.md",
]

PAGE_AUTHOR_BRIEF = """# Page author

You are the author of ONE slide of a consulting deck, drawn as SVG under the PPT Master contract (the documents below) and exported later as native PowerPoint. A planner has already decided what the page says and how it is composed: that is your SLIDE RECORD, in the first user message. Other pages of the same deck are being authored at this moment by other authors you never see, and the deck must still read as one hand. That rests on five things you follow exactly: the design system and the execution lock below, the Narrative's continuity rules, the deck digest (what your neighbours say), and the CHROME SOURCE named in your job.

## What you may touch
- Write and edit only your own page file, `svg_output/<stem>.svg`, under the project named in your job. Never edit the design spec, the lock, another page, the templates or the sources.
- Never run the checker, finalize, export, the contact sheet or the preview server: the deck runner does those once for the whole deck. The preview server is already running.
- I am away: every decision is delegated to you. Never stop to ask. Do not read the skill's other documents unless a rule you need is missing from this prompt; never read script source.

## The record
`Title` and `Core message` are verbatim. `Content` contains the visible claims, evidence and explanations: preserve their meaning and all material qualifiers, but edit wording to fit and read naturally. `Audience question` and `Audience move` define what the reader must learn; `Visual task` defines what the visual must make readable. `Relationships`, `Hierarchy`, `Visual approach`, `Composition` and `Avoid` guide you. `Visual approach` and `Composition` preserve the intended carrier, focal point, grouping and reading path; they are starting ideas rather than fixed geometry. You own exact shape placement, spacing, coordinates, line weights and text fit. A page may be spare when one example, comparison or proof is enough. Use the lock's type hierarchy and consulting-typesetting.md; if material will not fit legibly, simplify the depiction without dropping the page's answer or evidence. `Editor notes` are for a human and are never drawn. A `[To be provided: ...]` in your Content is drawn exactly as written, in muted italic inside a dashed hairline slot of the final element's size: it marks what the firm must supply - never replace it with an invented name, client, photo or number. Every number is a scenario value from the record; never invent one.

If the record names an image from `images/`, inspect that exact file with `read_image` before placing it. Use the image only for the stated visual task, through an SVG `<image href="../images/<filename>" .../>` with source-aware cropping and a visible source line where the claim needs one. An imported slide preview is a screenshot of an existing slide: label it as such and do not imply its contents are native editable objects in the new deck. Do not replace an available source image with an invented schematic, and do not invent an image when the source catalog says the needed evidence is absent.

## Built the way a person builds a slide
The deck is edited by people afterwards, so its objects must behave like theirs. After export, every text that sits inside a shape is moved into that shape's own text frame (it then wraps, and moves with the shape). Draw so that this works:
- A box, card, chip, bar or banner is ONE filled or outlined shape with its text drawn after it and fully inside it, with a few pixels of padding. Never let text straddle the edge of the shape it belongs to.
- One shape holds ONE column of text. When a card or a table row needs several columns (label | value, or the cells of a table), give every cell its own `<rect>` (its fill may equal the row's fill; the row band can stay behind) and put each cell's text inside its own rect. A grid of cell rectangles is how a table is built here.
- A list is a native list: one `<text>` per item starting with its typed marker (`<tspan fill="#B4162E">■</tspan> text`, or `1.` for an ordered list), never a drawn square beside a text (consulting-typesetting.md §5).
- A table is a native table: when your record has a `Native-ready: <key>=yes` line, that grid is drawn as `<g id="<key>" data-pptx-replace-with="table">` with its JSON `<metadata>` (schema `ppt-master.semantic-table.v2`, native-data-interface.md §2) AND the visible fallback in the same design; style it per cell (header band, row fills, first-column weight, sparse borders, padding) so the PowerPoint table looks like the fallback. After every edit inside that group run `run_script stamp_native_fallbacks.py <project>/svg_output/<stem>.svg --write`.
- One `<text>` per paragraph: the lines of one paragraph are positioned `<tspan>` lines inside that one `<text>`, never sibling `<text>` elements. A heading and the paragraph under it are two `<text>` elements with the same left edge.
- A label on a bar, chip, chevron or node is centred in its shape (`text-anchor="middle"` at the shape's centre, vertically centred), unless the design needs it left-aligned with padding.
- On a timeline or Gantt every bar carries its own label - inside the bar when it fits, otherwise starting just after the bar's end on the same row - never in a key or a lane heading (consulting-typesetting.md §6). A label that straddles a bar's edge is what the lint flags; fully inside or fully beside is clean.
- An arrow between two boxes is a straight `<line>` from the edge of one box to the edge of the other, or one that bends once at a right angle, ending ON the edges (it becomes a connector glued to both boxes in PowerPoint); avoid routes with several bends.
- Nothing is painted between a shape and the text that belongs to it: accent bars, icons and rules go where they do not overlap the text.

## Chrome
The header, the title zone and the footer are the deck's chrome. When your job names a chrome source, read that SVG first and reproduce those elements exactly - same positions, sizes, fonts, colours and rules - changing only the eyebrow text, the title text, the source line and the folio. The chrome group is `<g id="chrome" data-pptx-role="chrome">`: keep that role, it is what lets your page's groups sit inside the chrome's bounds without a contract error. When your job says you ARE the chrome anchor, draw them cleanly from §I Template Application and §II of the design spec: every other page will copy yours. A cover follows its own record alone: it carries no running footer, source line or folio unless its record lists one, and takes only fonts and colours from the chrome source.

## The loop (consulting-review.md is the way of looking)
1. Deliver each slide on your record's `Reference` lines: `run_script reference_library.py show <id> [<id>] --project <project> --page <stem>`; look at the images; borrow only what each line says.
2. Write the page. Render it: `run_script page_review.py render <project> <stem>`. Two things come back: the image, and a GEOMETRY LINT that measured the page in the browser, with an overlay image that boxes each finding.
   - `CERTAIN` findings (text on text, text off the canvas or invisible, a contract error) are measurements, not opinions: fix every one and render again. The reviewer refuses a render that still has one.
   - `FLAGGED` findings (a line through text, text leaving its shape, a shape over text) are probable defects. Fix those that are mistakes. One you drew on purpose and that reads cleanly may stay: the reviewer sees a zoomed crop of each and rules on it. More than eight is refused.
   - Then look at the image yourself for what a ruler cannot know: crowding, unused canvas, the wrong focal element, a figure that does not carry the record's relationships.
3. Ask the independent reviewer: `run_script page_review.py review <project> <stem>`. Its defect inventory is fact. `EXECUTION_REPAIR`: fix every listed item, render, review again. `CONCEPT_REPLAN`: redraw the figure, do not patch it. It reviews a given render once.
4. Budget: a first draft plus three revisions (a revision is a render of changed content; up to four renders that only fix lint findings are free and do not count). Record the outcome: `run_script page_review.py note <project> <stem> --outcome accepted --text "Preserve: ... Main weakness: ... Change made: ... Result: ... Drift: none|<what the render does that the scaffold did not say>"`. `accepted` is refused without a PASS review of the current revision; when the budget is spent, record `unresolved` and name the reviewer's remaining items. Never use --no-review.
5. Reply with exactly one line and stop: `DONE <stem> <accepted|unresolved>`.

## Known failure modes - check them before every render
Measured across 150 pages by ten models; each one has cost authors revisions or shipped as a defect.
- RELATIONSHIPS ARE DRAWN, NOT WRITTEN. Every relationship the record names is on the figure: a dependency is an arrow from one thing to the other; a milestone or gate is named AT its week on the chart; a flow is connected shapes. A caption list, a footnote, a strip below the chart or a legend never stands in for a drawn relationship. Before your first review, check the render against every `Avoid` line of your record.
- TEXT FIT BEFORE RENDER. Estimate every single-line string: about 0.55 x font size x characters (0.6 for bold or capitals). If it exceeds its zone, shorten the words or wrap them before you render. Never shrink a title or the chrome to make something fit.
- TYPE FLOOR. Nothing is set under its floor (1280 x 720 canvas, or the lock's `## type_floor`): running text and list items 16 px; table cells, diagram and chart labels, callouts and captions 14 px; sources, footnotes, header, footer and folio 11 px. The lint measures every text's rendered size (a scaled group counts) and reports `MIN_TYPE` as CERTAIN; a title under its layout's size is `TITLE_SHRUNK`. Never shrink below the floor to fit: cut the copy (the record allows shortening), move detail to the page's notes or an appendix, or change the exhibit (fewer columns, a chart instead of a table, two pages instead of one). When the geometry cannot tell what a text is, say it: `data-type-role="body|secondary|footnote|furniture|title"` on the text or its group (consulting-typesetting.md §8).
- FILL THE BODY. `DEAD_BAND` (an empty band across the page over 15% of the body height), `UNDERFILLED` (content in under 55% of it) and `HUDDLED` (the figure squeezed into a strip) are flagged for the reviewer: use the space - a larger figure, type above the floor, the takeaway or evidence moved into the gap - unless the whitespace frames a hero element on purpose.
- LEADING. The distance between the baselines of two lines of one paragraph is at least 1.4 x the font size for body text and labels (20 px at 14 px, 22-23 px at 16 px) and at least 1.15 x for titles. Never write a smaller `dy`.
- NATIVE TABLES. The render's lint runs the exporter's own table check (`NATIVE` findings): inside a `data-pptx-replace-with="table"` group every wrapped cell line ends with a space before the next `<tspan>` (or the lines are the cell's `paragraphs`), punctuation is identical in the drawing and the JSON, and any colour, weight, size or alignment you give a drawn cell is set on that cell in the JSON. Use only the schema's fields.
- NEVER SILENCE THE LINT. Do not widen `data-pptx-bounds` past the body zone or margins, and do not wrap modules in a new group to make a finding disappear: fix the geometry.
- TOOLS. Copy file paths exactly from your job (character for character - a hyphen is not an underscore). Never batch two edits that touch the same passage, and never send an edit whose old and new text are equal. Do not read your own file back after writing it: the render shows it. Leave `timeout_s` unset.
- STOP AT PASS. When the review says PASS, record `accepted` at once; its "highest-impact change" is then optional and not worth a revision.
- A record's field names (`Wave 1`, `Layer`, `Zone`) are not visible labels unless the `Content` gives them as text.
- READ WITHOUT A PRESENTER. The page is read by someone with no context and nobody to ask. Keep every definition and expansion the record gives; never abbreviate a name, invent shorthand, drop a unit or leave a code (like `W23`) without the explanation the record gives it.
- VISUAL ANSWER. Before rendering, point to the marks that answer `Audience question`. If the reader must trace an order, show a clear direction; if they must compare, align like terms; if they must understand a system, show its boundary and only the relationships needed at this level. Label nodes and non-obvious links directly. When a node names parallel inputs, actions or outputs, use a short list or labelled fragments inside it; place interpretation and provenance outside the node. Keep a sentence inside only when its exact wording is the evidence. Split a complex view into context then detail when the record permits. Do not make a diagram merely to fill space, and do not use a legend when a direct label is clearer.

## Working efficiently
Send independent tool calls together in one turn (several edits to different passages, or a render straight after a write). Use `edit_file` for local changes and `write_file` for a redraw. Do not re-read anything that is already in this prompt.
"""


TEMPLATE_BRIEF = """TEMPLATE JOB

Project: `{project}`. You design this deck's TEMPLATE before any page is drawn. Nobody will approve it: the pages are authored in parallel straight after you, each inside one of your layouts, and the exported PowerPoint will carry your layouts as its slide layouts. Work from the design spec and the execution lock in this prompt (brand, colours, type, spacing posture, §I Template Application) and from the records' `Layout` lines in §IX, which name the layouts this deck needs.

Write, under `{project}/templates/`:
1. One SVG per layout the records name - always `cover.svg` and `content.svg`; `section.svg`, `closing.svg` or another only if a record uses it. Canvas and contract as for any page (executor-base.md, shared-standards-core.md). Each layout holds ONLY what repeats on every slide that uses it, drawn final: the header (mark or logo, firm or client line, the rule), the title zone's rule or band, the footer (deck line, the place of the source line, the folio), the background field of a cover. Put all of it in ONE group `<g id="chrome" data-pptx-role="chrome" data-pptx-bounds="0 0 {width} {height}">` (the role tells the checker this is the page's static framing, so the page's own groups may sit inside its bounds).
   Text that changes per slide is NOT chrome: show it as sample text in a second group `<g id="sample" data-pptx-bounds="...">` with these ids on the `<text>` elements so authors know position, size, weight, colour and leading: `sample-eyebrow`, `sample-title` (two lines, at the title leading of consulting-typesetting.md), `sample-source`, `sample-folio`; the folio is the plain slide number (`7`, never `07`: it becomes PowerPoint's page-number field); on the cover: `sample-title`, `sample-subtitle`, `sample-meta`. Mark the free area with one unpainted guide `<rect id="body-zone" fill="none" stroke="none" .../>` inside the sample group.
2. `{project}/templates/template.md`: for each layout - what it is for; the body zone as x, y, width, height; the title zone; the exact type sizes, weights, colours and leading of title, eyebrow, source line and folio; the column grid and gutters pages should snap to; the marker character and colour for lists; table styling (header band, rules, padding) and card styling (fill, border, padding, corner) so that twenty authors draw the same table and the same card; connector style (weight, colour, arrowhead). Short and exact - it is read by every page author.

Design taste: a consulting house style - restrained, exact, one accent, generous title zone, hairline rules, no decoration that does not organise. Line and paragraph spacing per consulting-typesetting.md. Render each layout (`run_script page_review.py render` does not apply to templates; instead check your SVG by reading it back once) and keep every text inside the canvas.

Reply with exactly one line when done: `DONE template <layout names>`.
"""

BASE_TEMPLATE_BRIEF = """
BASE TEMPLATE - this deck is built on our firm's official template, not on a template of your own. `sources/base-template.md` describes it (theme colours and fonts, slide size, its layouts and where each is drawn). Before you draw, LOOK at it: `read_image` its layout renders and slide renders listed there (at least the title or cover layout and the title-and-content layout). Its layouts as SVG are under `{imported}/svg/` (`layout_*.svg`, `master_*.svg`; their images under `{imported}/images/`).
Reproduce its layouts in this job's format - do not redesign them: the same background and fields, the same marks, rules and bands at the same positions and sizes, the theme's colours and fonts, the title where the template puts its title at the template's size and weight, the body where the template's content placeholder sits. Copy the geometry of its artwork from the imported SVGs. The template's photographs are sample content, not chrome: leave them out and keep the layout's own geometry and fields; a mark or logo that the template draws as shapes is chrome and is copied. Where the official template has no place for something the brief requires (the eyebrow, the source line, the folio), add it in the template's own idiom - its type, its colours, its alignment - quietly. `template.md` states for every layout which official layout it reproduces. The records name the template's layouts by the names `base-template.md` gives them: draw the one of each name you are asked for from the official layout of that name, keeping its structure (its zones, rails, bands, and where its title and body sit).
"""

SOLUTION_BRIEF = """SOLUTION JOB

Project: `{project}`. Before anything is planned or drawn, you work out WHAT WE PROPOSE. You are the engagement partner and the solution architect of our firm, answering the request in `{project}/sources/` (read every file there: the client's documents, our firm's knowledge base, the request). Nobody has solved this for you, and nobody will approve your answer: it is built into the deck as you write it. Think hard, decide, and be specific - a proposal wins on a clear point of view, exact scope, a plan the client can see week by week, a team they can picture, and a price they can check.

Write one file, `{project}/solution.md`, with these parts:
1. THE CLIENT'S SITUATION in their words and ours: what hurts, why now, what they will judge us on (their evaluation criteria and weights), what they did NOT ask for but need, and the two or three things most likely to make a competitor's answer weaker.
2. WIN THEMES: three or four, each a claim we can prove on a page.
3. THE SOLUTION: the design and every material choice with its reason and the alternative we considered and why not (platform and architecture, data flow from source to report, controls and lineage, governance of definitions, the reports for each audience, any pilot or innovation component with its guardrails and how it is evaluated, security and privacy position). Name things once and keep the names.
4. SCOPE AND PHASING: what is in the fixed scope, what we choose where the client lets the vendor choose (with reasoning and how it is confirmed), and the path beyond this engagement.
5. THE PLAN: workstreams with sub-tasks and week ranges across the engagement's duration (overlaps are real - show them), milestones with their week, decision points, the client's governance rhythm and ours.
6. THE TEAM: named roles from our knowledge base with grade and days; what we need from the client's side.
7. THE PRICE: built bottom-up from our rate card (days x rate by role and grade), allocated by workstream so both views reconcile to the same total, other costs, payment milestones; in the client's currency and the structure of their pricing form. Check the arithmetic twice - a total that does not reconcile loses the commercial score.
8. PROOF: which of our credentials and accelerators support which claim; never claim what the knowledge base does not say.
9. RISKS AND ASSUMPTIONS we state openly, each with what we do about it.
10. WHAT THE DECK MUST MAKE THE READER BELIEVE, page by page in one line each (about the size the request asks for; the planner that follows decides the final structure).

COVER THE WHOLE REQUEST. Before you design, list for yourself (in part 1) every objective, scope item and deliverable the request names, and make sure the solution answers each one; a sharp answer to part of the request loses to a complete one. Specialise only after the whole scope is covered.
CREDIBLE EFFORT. Size the effort from the work first - hours per deliverable, per meeting, per draft, per stakeholder - then price it. When the price exceeds a ceiling, change the scope or the approach openly and say what moved; never shave hours until the total fits. Check the result as a reader would: hours per week, senior share, hours to write each deliverable.
WRITE FOR A READER WITH NO CONTEXT. The deck built from this is read by people who were not in the room: name things plainly, define every component, method and stage in a sentence, and expand abbreviations.

WHAT YOU DO NOT KNOW, YOU DO NOT WRITE. When the sources do not give a fact the proposal needs - a named person, a CV, a credential or client reference, a logo, a rate, a measured result - never invent it and never dress an assumption as a fact. Use a placeholder instead, written exactly as `[To be provided: <what, in a few words>]`, and design the place for it (a CV card, a credential card, a logo slot) at its final size so the editor drops the real thing in. Roles, grades, effort, scope, plan and design are yours to work out; people, track record and anything only the firm's records can prove are not. End `solution.md` with a list `## To be provided` of every placeholder you used and who in a firm would supply it. Every figure is from the sources or derived from them by arithmetic you show, or is labelled an assumption. Reply with exactly one line when done: `DONE solution`.
"""

DOCUMENT_BRIEF = """CONTENT JOB

Project: `{project}`. Before anything is planned or drawn, you work out WHAT THIS DECK SAYS. You are its subject-matter lead and its editor. The request is `{project}/sources/request.md`; the other files in `{project}/sources/` are seed documents and an index of where to look. The subject may be a product, a codebase or a practice: you may read any file in this repository checkout (`read_file`, `list_dir`) to find out and to verify. Documentation states intent; code, tests, run logs and real artefacts show what is actually there - verify every high-impact claim against them. Evidence comes from the checkout the request names and from `sources/`; the outputs of other projects in this workspace (their plans, reviews, evaluations, renders) are not evidence and are not read. Nobody will approve your answer: the deck is built from what you write.

If `analysis/source_visuals/catalog.md` exists, read it alongside the source documents. It lists images extracted from supplied files, standalone source images, and actual slide previews from supplied decks. Follow its links to normalized source text and inspect only candidates relevant to a claim. Record where each chosen visual came from and whether it is a screenshot or an embedded image; do not treat a supplied illustration as proof of a claim it does not show.

Write one file, `{project}/solution.md` (the content brief), with these parts:
1. THE READERS: each audience the request names, what each must be able to explain, decide or do after reading, and what they already know (assume nothing - the deck is sent to people with no context and nobody to ask).
2. THE STORY: the governing thought in one sentence a newcomer understands; the arc with a clear beginning (what this is and why it matters), middle (how it works, the evidence) and end (what it means, limits, what is asked or what to do next).
3. WHAT IT IS AND HOW IT WORKS: every component, route, stage and artefact, each defined in one plain sentence, with how they connect; the flows a user follows from request to result; the stack and dependencies.
4. EVIDENCE: every material claim with its status - `available now` (shown by code, tests or artefacts), `conditional` (on environment, host, model or licence), `future possibility`, or `unknown` (a company-specific fact nobody has supplied) - and its source (repository path, with a section or line where useful). Never promote a documentation claim to fact without checking the code, tests or artefacts; label synthetic or illustrative examples as such; quote measured figures (time, cost, counts) only from a run log or artefact, with the run named.
5. LIMITS AND OPEN QUESTIONS: what does not work, what is unproven, what an organisation must resolve before relying on it (as questions, never invented answers). For a software product this includes the licence and attribution obligations of the product and of its dependencies, what must be installed (runtimes, fonts, renderers), and where data goes (which model providers see what). The deck states the limits honestly and ONCE, on the page that owns them - not as a caveat on every page.
6. EXAMPLES AND WALKTHROUGHS: real ones, with their paths - at least one worked example a newcomer can follow end to end (the actual request or input, what the user does, the files and pages it produces, a review verdict, a before-and-after fix).
VALUE FIRST: the story opens with what the reader gains, in positive and concrete terms - who uses it, for what, instead of what, and what it saves or makes possible - before how it works and its limits. Candour about limits is essential; a deck that states value only as negations ("not X, not Y") reads as a warning, not an explanation.
7. GLOSSARY: every term, component and abbreviation the deck will use, each with a one-line plain definition, so the planner can define it at its first use.
8. WHAT EACH PAGE MUST MAKE THE READER UNDERSTAND: one line each, at the length the request suggests (the planner decides the final structure).
9. SOURCE MAP: claim -> source path, for every number and every capability statement.

WHAT YOU DO NOT KNOW, YOU DO NOT WRITE. A company-specific fact (an owner, an approval, a budget, a policy, a date, a measured outcome) that the sources do not give is a placeholder written exactly as `[To be provided: <what, in a few words>]`, never an invention. Reply with exactly one line when done: `DONE solution`.
"""

PLANNER_BRIEF = """PLANNING JOB

Project: {project}. Read its solution.md and all source files first. The solution owns verified facts and limits. Plan a deck that achieves the request's audience outcome, with the requested page count or structure when supplied. Use {exemplar} only for the document's section structure and field syntax; never copy its story, density, layouts, content, or drawing style. Write design_spec.md and spec_lock.md in {project}; use {exemplar_lock} for lock syntax.

Read `analysis/source_visuals/catalog.md` when present. It inventories visual assets from supplied documents and decks; a preview of an old slide is a sourced screenshot, while an embedded picture is a reusable image. Select an asset only when it answers a page's question or supplies real visual evidence. Inspect the chosen image and its source context before planning placement. Put its exact `images/...` path, original source and slide/page when known, visual job, and crop/label treatment on that slide's `Images` line. In §VIII use its basename as `Filename`, `Acquire Via: user`, and `Status: Existing`; project it into the lock's images section. Do not ask an author to draw a substitute for a real source image; if required visual proof is absent, say so in the plan and choose an honest presentation of the available evidence.

Plan in this order:
1. READER CONTRACT. In section IX Narrative, name each audience, what it already knows, its questions, the desired understanding or decision, the reading context, and what the file must explain without a presenter. For multiple purposes, show how the arc serves each without making every slide do every job.
2. INFORMATION PATH. List the minimum concepts and examples readers need before they can understand the next idea. Identify the first concrete proof or worked example and put it early enough to make the subject tangible. Choose an arc appropriate to the brief: question to answer, problem to evidence to decision, process to worked application, findings to implications, chronology, reference, or another structure justified by the material. Do not force a three-act story, a fixed slide count, or a diagram onto a subject that needs something else. Each page must earn a distinct step; split overloaded pages and merge redundant ones when page count is flexible.
3. SLIDE RECORDS. For every Slide NN record, write: Role, Author tier, Layout, Audience question (one question the reader has at that point), Audience move (before to after), Story link (why this follows the previous slide and prepares the next), Relationships (source-stated semantic units and their order, link, parent, membership, contrast or overlap; or none), Title (a clear answer rather than a topic label), Core message (one governing claim), Content (all visible claims, definitions, example labels, numbers and qualifiers in reader-facing language), Sources, Visual task (what the reader must see, compare, trace or locate to answer the question), Visual approach (a nonbinding suggested form and why it fits), Composition (nonbinding macro grouping, focal point and reading path, without coordinates), Hierarchy, Avoid, Reference, Editor notes, and data class where relevant. Each field has its own Markdown bullet line; do not put Role, Author tier and Layout on one line. Use headings exactly `#### Slide 01 - Name` (ASCII hyphen). Author tier is frontier for a page requiring complex visual judgement and workhorse for simpler pages. Layout must be among supplied template layouts when a base template is present. Use reference_library.py forms and a form's sheet to select at most two structural references for a body page, naming what to borrow without copying content.
4. VISUAL REASONING. Start from the question and evidence, then select the information relationship: comparison, sequence, process, hierarchy, boundary, connection, distribution, trend, part-to-whole, spatial arrangement, or a concrete example. Suggest a fitting carrier in Visual approach: direct evidence image, annotated example, chart, table, diagram, timeline, or concise prose where it explains better. Do not require a diagram on every slide. A diagram must have a scope/title, a clear reading direction when order matters, named entities, directly labelled non-obvious links, and a boundary when inclusion matters. Show only the level of detail needed for the reader's question; use context before component detail when complexity warrants it. Give one stable meaning to a visual cue across the deck. Leave exact shape selection, coordinates, element sizes, and fit to the page author.
5. COLD READ. Review the titles and visible Content alone, in order, with no solution, narrative notes, or speaker. Can a first-time reader say what this is, why each page matters, how evidence supports its claim, and what follows? Define a term when first used; expand unusual abbreviations, explain internal names and week codes, and remove references to unseen documents. A complex figure needs a plain reading sentence in visible copy. Repair missing bridges, unsupported claims, and jargon before drawing. Do not add padding to satisfy a word count: an illustrative page can be spare, while a reference or data page can be fuller if type remains readable.
6. CAPACITY AND TITLES. Every record must fit its layout at the legible type floors: body text 16 px, table cells, diagram and chart labels, callouts and captions 14 px, sources and footnotes 11 px (1280 x 720 canvas; a lock may declare other floors in `## type_floor`). The plan check sets each record's Content at those floors with the locked fonts in the area its layout gives content, and refuses a record that needs more (OVER_CAPACITY) - a table is counted at its wrapped height. Authors are told never to shrink type below a floor to fit, so a record over capacity cannot be drawn: cut the copy to what the page's question needs, split the page, or move detail to an appendix page. Being under capacity is never a fault; a spare page is a choice. Each Title is a full-sentence claim of 15 words or fewer that sets in at most two lines at the locked title size in its layout's title box (TITLE_FIT); shorten it, never plan a smaller title size. The fill ratio of every record is written to `.review/plan_capacity.md`.

Every high-impact factual or quantitative claim needs a source, or an explicit Data class: scenario; never invent company-specific owners, credentials, budgets, approvals, or measured outcomes. Use [To be provided: <what>] where the brief needs a fact the sources lack. Keep internal production instructions in Editor notes, not client-facing copy. A page may show a candid limitation where it changes the reader's judgement; group routine caveats on the page that owns them.

The supplied template provides typography, palette and chrome, while the page's content determines its information form. Use the existing template's page families for the jobs they suit. Do not fill every region solely because it exists. Names, numbers and semantic colours stay stable across pages.

Complete all required Design Spec sections I-X, including `## X. Speaker Notes Requirements`. In this runner set `Generation: disabled` unless the user requests speaker notes or narration; disabled §X needs no other fields. The visible slides are the deliverable: do not put a definition, claim, evidence, qualifier or reading bridge only in notes, and do not compress slide copy on the assumption that notes will explain it. Spend planning effort on slide substance, visual proof, legibility and the unaided reading path. Write spec_lock.md with the actual canvas, fonts, colours, layout names and images, in the exemplar lock's syntax. This runner authors pages from chrome SVG layouts and exports a flat PPTX: set pptx_structure.mode to flat, and omit pptx_masters, pptx_layouts, page_pptx_layouts and page_layouts. Imported template Slides are visual references, not valid structured Slide prototypes. Leave the images section empty if no image exists. Keep the `## forbidden` scaffold rules; add a project-specific row there only for an explicit user restriction, tagged `(user)`. Put source-derived caveats in the relevant page records or Editor notes instead. Reply exactly DONE plan <number of pages> when both files are complete.
"""


def collect_annotations(project: Path) -> dict[str, list[dict]]:
    """The user's comments from the live-preview interface: the editor stores each one on the element it is about
    (`data-edit-target="true"`, `data-edit-annotation="..."`). Returns {page stem: [{element, tag, text, comment}]}."""
    import xml.etree.ElementTree as ET
    found: dict[str, list[dict]] = {}
    for svg in sorted((project / "svg_output").glob("*.svg")):
        try:
            root = ET.parse(svg).getroot()
        except ET.ParseError:
            continue
        for elem in root.iter():
            if elem.get("data-edit-target") == "true" and (elem.get("data-edit-annotation") or "").strip():
                text = " ".join("".join(elem.itertext()).split())[:140]
                found.setdefault(svg.stem, []).append({"element": elem.get("id") or "(no id)", "tag": elem.tag.split("}", 1)[-1], "text": text,
                                                       "comment": elem.get("data-edit-annotation").strip()})
    return found


def revision_message(stem: str, comments: list[dict]) -> str:
    listing = "\n".join(f"{n}. On `<{c['tag']} id=\"{c['element']}\">`" + (f" (\"{c['text']}\")" if c["text"] else "") + f": {c['comment']}" for n, c in enumerate(comments, start=1))
    return (f"The user has looked at your page `{stem}.svg` in the preview and left these comments on its elements. They are the user's decisions: apply every one, as "
            "asked, even where it departs from your slide record (say so in your note). A comment about one element may need its neighbours to move: keep the page whole - "
            "spacing, alignment, the template's chrome and the typesetting rules still hold. When a comment is done, remove `data-edit-target` and `data-edit-annotation` "
            "from that element (they are the user's pending marks). This revision is allowed beyond the page's revision budget. Render, clear what the lint reports, ask the "
            f"reviewer for the new revision, and record the outcome again with `note`. Then reply `DONE {stem} <outcome>`.\n\n{listing}")


def keep_or_restore(before: dict, after: dict) -> str:
    """A repair must not demote a page that had passed. `before` and `after` are the page's journal entries around the repair.
    'fine' - still accepted; 'keep' - the repaired revision stays and stays accepted, because its review found no defect (polish only);
    'restore' - the repaired revision has real defects (or no review): the revision that passed comes back."""
    if before.get("outcome") != "accepted" or after.get("outcome") == "accepted":
        return "fine"
    review, lint = after.get("review") or {}, after.get("lint") or {}
    reviewed_current = review.get("sha") == after.get("last_sha")
    clean = reviewed_current and review.get("verdict") in ("PASS", "EXECUTION_REPAIR") and (review.get("blockers") or 0) == 0 and (lint.get("hard") or 0) == 0
    return "keep" if clean else "restore"


PLANNER_EXAMPLES = Path(__file__).resolve().parent / "planner_examples"
FILLER = re.compile(r"(?i)\b(to assess|tbd|to be confirmed|lorem ipsum)\b")
INTERNAL = re.compile(r"(?i)(submission blocker|before (?:submission|filing)|not ready to (?:file|submit)|must be (?:inserted|verified|completed) before)")


EVERYDAY = {"USD", "EUR", "GBP", "HKD", "AI", "CEO", "CFO", "CIO", "CTO", "COO", "IT", "UK", "US", "EU", "OK", "PDF", "FAQ", "HR", "Q1", "Q2", "Q3", "Q4",
            "TO", "BE", "PROVIDED", "AM", "PM", "ID", "NO", "N/A", "TBD", "VS", "FTE", "ROI", "KPI", "KPIS", "CV", "CVS", "HK", "SG", "SGD", "UAE", "NY"}
ACRONYM = re.compile(r"\b([A-Z][A-Z0-9&]{1,6})s?\b")


def undefined_terms(spec: str) -> dict[str, list[str]]:
    """Self-containment: abbreviations a reader meets before (or without) their expansion, and week codes never explained as weeks.
    An abbreviation counts as defined once the deck's copy has "Words (ABBR)" or "ABBR (words)" at or before its first use."""
    found: dict[str, list[str]] = {}
    defined: set[str] = set()
    # a capitalised token that the deck also writes as an ordinary word ("DESIGN" in an eyebrow, "design" in a sentence) is a word, not an abbreviation
    words = {w.lower() for w in re.findall(r"\b[a-z][a-z]+\b|\b[A-Z][a-z]+\b", spec)}
    for block in re.split(r"\n(?=#### Slide )", spec)[1:]:
        head = block.splitlines()[0].replace("#### ", "").strip()

        def field(name: str) -> str:
            m = re.search(rf"- \*\*{name}\*\*(?: \([^)]*\))?:(.*?)(?=\n- \*\*[A-Z][^*]*\*\*|\Z)", block, re.S)
            return m.group(1) if m else ""

        copy = " ".join(field(n) for n in ("Title", "Core message", "Content"))
        copy = re.sub(r"\[To be provided:[^\]]*\]", " ", copy)
        # text set in capitals (eyebrows, section labels) is typography, not abbreviation: skip runs of three or more capitalised words
        prose = re.sub(r"\b[A-Z][A-Z0-9&'’.-]*(?:[\s·/|:,-]+[A-Z][A-Z0-9&'’.-]*){2,}\b", " ", copy)
        defined |= set(re.findall(r"\(([A-Z][A-Z0-9&]{1,6})s?\)", copy)) | set(re.findall(r"\b([A-Z][A-Z0-9&]{1,6})s?\s+\((?=[a-z]|[A-Z][a-z])", copy))
        issues = []
        missing = sorted({a for a in ACRONYM.findall(prose) if a not in defined and a not in EVERYDAY and a.lower() not in words
                          and not a.isdigit() and not re.fullmatch(r"W\d+|P\d+|[A-Z]\d{1,2}", a)})
        if missing:
            issues.append("abbreviations a newcomer cannot read here (spell each out at its first use, e.g. `Words (ABBR)`): " + ", ".join(missing[:10]))
            defined |= set(missing)  # reported once, at first use
        if re.search(r"\bW\d{1,2}\b", copy) and not re.search(r"(?i)\bweeks?\b", copy):
            issues.append("week codes (W23) with no plain explanation on the page: say `week 23 of the engagement` or explain the code once on this page")
        if re.search(r"(?i)(\bsee §|§\s?\d|\bas discussed\b|\bper the (?:workbook|rfp|brief)\b)", copy):
            issues.append("a reference to material the reader does not have (a section number, `as discussed`, `per the workbook`): say the thing itself")
        if issues:
            found[head] = issues
    return found


# ---------------------------------------------------------------------------------------------------------------------------
# Capacity contract between plan and page (F02). A record's planned copy is set at the type floors (body 16 px, secondary 14 px,
# footnote 11 px, or the lock's `## type_floor`) with the locked fonts' real metrics, and compared with the area the record's
# layout gives its content. The author is told never to shrink below the floor to fit, so a record over capacity is a plan defect:
# cut, split the page, or move detail to notes or an appendix. Under capacity is never an error: density is a choice.
# ---------------------------------------------------------------------------------------------------------------------------
TEXT_FILL = 0.45          # share of a layout's content area that running text and labels can occupy on a packed, legible page (the
                          # rest is gutters, padding, rules, shapes and ragged line ends); calibrated on the 28 Sep, kirkland2 and meridian decks
OVER_CAPACITY_RATIO = 1.10  # a record is refused only when it needs clearly more than the page holds: the estimate is +/- 10%
COPY_SKIP_KEY = re.compile(r"(?i)^(?:running head|running header|eyebrow|kicker|folio|footer|page number|section code|tracker|chrome|layout|composition)\b")
FOOT_KEY = re.compile(r"(?i)^(?:source|sources|source line|footnote|footnotes|note line|provenance)\b")
SECONDARY_KEY = re.compile(r"(?i)\b(?:rows?|cells?|columns?|cols?|header|table|chart|axis|labels?|nodes?|lanes?|bars?|steps?|stages?|legend|ticks?|milestones?"
                           r"|gates?|phases?|exhibit|captions?|chips?|badges?|callouts?|annotations?|gloss(?:es)?|markers?|data|area \d+|box(?:es)?|cards?)\b")
SAMPLE_PROSE = ("Every reported measure traces to an approved source, a named owner and a stated definition, so the board can compare "
                "results across business units without re-checking the numbers by hand.")


def _skill_scripts() -> None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))


def _copy_words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text) if re.search(r"[^\W_]", w)])


def planned_copy(block: str) -> dict:
    """The visible words a record plans, by the floor they will be set at: {'body', 'secondary', 'footnote'} word counts and any
    planned table ({'rows': [[cell, ...], ...]}) from a `Rows:` line (`a · b | c · d`) or keyed `row N <field>:` lines."""
    _skill_scripts()
    import type_floor
    content = type_floor.record_field(block, "Content")
    counts = {"body": 0, "secondary": 0, "footnote": 0}
    keyed_rows: dict[int, list[str]] = {}
    table_rows: list[list[str]] = []
    header: list[str] = []
    for raw in content.splitlines():
        line = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", raw).strip()
        if not line:
            continue
        key, value = "", line
        match = re.match(r"^([A-Za-z][\w /()&'.,+-]{0,48}?)\s*:\s+(.*)$", line)
        if match and "`" not in match.group(1) and len(match.group(1).split()) <= 6:
            key, value = match.group(1).strip(), match.group(2)
        if COPY_SKIP_KEY.match(key):
            continue
        plain = re.sub(r"[`*_]|\[To be provided:\s*", " ", value).replace("]", " ")
        quoted = re.findall(r"`([^`]+)`", value)
        cells = quoted if len(quoted) >= 2 else [c.strip() for c in re.split(r"\s+·\s+|\s*\|\s*", plain) if c.strip()]
        row = re.match(r"(?i)^row\s*(\d+)\b", key)
        if row:  # `Row 3: a · b · c` is a whole row; `row 3 proof: ...` is one cell of it
            keyed_rows.setdefault(int(row.group(1)), []).extend(cells if re.fullmatch(r"(?i)row\s*\d+", key) else [plain.strip()])
            counts["secondary"] += _copy_words(plain)
            continue
        if re.match(r"(?i)^(?:rows|table rows|cells)$", key) and "|" in value:
            table_rows.extend([[c.strip() for c in re.split(r"\s+·\s+|\s*;\s+", part) if c.strip()] for part in plain.split("|")])
            counts["secondary"] += _copy_words(plain)
            continue
        if re.match(r"(?i)^(?:exhibit )?(?:columns|column headers|headers)$", key):
            header = cells
            counts["secondary"] += _copy_words(plain)
            continue
        role = "footnote" if FOOT_KEY.match(key) or re.match(r"(?i)^\s*source:", plain) else "secondary" if key and SECONDARY_KEY.search(key) else "body"
        counts[role] += _copy_words(plain)
    rows = table_rows or [keyed_rows[k] for k in sorted(keyed_rows)]
    table = {"rows": rows, "header": header} if len(rows) >= 2 else None
    return {**counts, "table": table, "total": sum(counts.values())}


def _word_area(size: float, family: str, pitch: float) -> float:
    """Area one average word occupies at `size` px: real advance width of sample prose per word, times the line pitch."""
    _skill_scripts()
    import text_measure
    width = text_measure.measure_real(SAMPLE_PROSE, size=size, family=family)
    return width / max(1, len(SAMPLE_PROSE.split())) * size * pitch


def table_height(table: dict, width: float, size: float, family: str) -> float:
    """Height of a planned table at `size` px across `width`: columns sized to their longest cell (bounded), each cell wrapped with
    real metrics inside 8 px side padding, rows 1.3 x size per line plus 12 px of padding (consulting-typesetting.md §3)."""
    _skill_scripts()
    import text_measure
    rows = [r for r in table["rows"] if r]
    columns = max(len(r) for r in rows + ([table["header"]] if table.get("header") else []))
    grid = ([table["header"]] if table.get("header") else []) + rows
    longest = [max((text_measure.measure_real(r[c], size=size, family=family) if c < len(r) else 0.0) for r in grid) for c in range(columns)]
    total = sum(max(60.0, v) for v in longest) or 1.0
    widths = [width * max(60.0, v) / total for v in longest]
    height = 0.0
    for r in grid:
        lines = max(len(text_measure.wrap_real(r[c], size=size, max_width=max(24.0, widths[c] - 16), family=family)) if c < len(r) and r[c] else 1
                    for c in range(columns))
        height += max(2.2 * size, lines * 1.3 * size + 12)
    return height


def record_capacity(copy: dict, area: dict, family: str, floors: dict) -> dict:
    """Required area of a record's copy at the floors against the text area its layout offers. Returns the words it plans, the words
    a page of this layout holds at the record's own body/secondary/footnote mix, and the fill ratio (1.0 = full)."""
    body_a = _word_area(floors["body"], family, 1.35)
    secondary_a = _word_area(floors["secondary"], family, 1.35)
    foot_a = _word_area(floors["footnote"], family, 1.3)
    table_area = 0.0
    secondary_words = copy["secondary"]
    if copy.get("table"):
        cells = sum(_copy_words(c) for r in copy["table"]["rows"] for c in r) + sum(_copy_words(c) for c in copy["table"].get("header") or [])
        table_area = table_height(copy["table"], area["width"], floors["secondary"], family) * area["width"]  # a table fills its own box
        secondary_words = max(0, secondary_words - cells)
    needed = (copy["body"] * body_a + secondary_words * secondary_a + copy["footnote"] * foot_a) / TEXT_FILL + table_area
    offered = area["area"]
    ratio = needed / offered if offered else 0.0
    words = copy["total"]
    return {"words": words, "capacity": int(round(words / ratio)) if ratio else 0, "ratio": ratio}


def plan_capacity(spec: str, lock: str, project: Path | None = None) -> tuple[dict[str, list[str]], list[dict]]:
    """OVER_CAPACITY and TITLE_FIT findings per record, and a row per record for the plan report (fill ratio, words, capacity)."""
    _skill_scripts()
    import text_measure
    import type_floor
    floors = type_floor.floors(lock)
    fonts = type_floor.typography(lock)
    body_family = fonts.get("body_family") or fonts.get("font_family") or "Segoe UI"
    found: dict[str, list[str]] = {}
    report: list[dict] = []
    for block in re.split(r"\n(?=#### Slide )", spec)[1:]:
        head = block.splitlines()[0].replace("#### ", "").strip()
        number = re.match(r"Slide (\d+)", head)
        number = int(number.group(1)) if number else None
        layout = type_floor.layout_name(lock, block, number)
        role = type_floor.record_field(block, "Role")
        rhythm = next((v for k, v in type_floor.lock_sections(lock).get("page_rhythm", {}).items() if type_floor.page_number(k) == number), "")
        sparse = bool(type_floor.SPARSE_ROLE.search(f"{role} {rhythm} {layout or ''}")) and rhythm != "dense"
        issues: list[str] = []
        title = re.sub(r"[`*]|^[\"“]|[\"”]$", "", type_floor.record_field(block, "Title")).strip()
        if title:
            box = type_floor.title_box(project, lock, layout)
            wrap_width = box["width"] - 19.2  # PowerPoint's default 0.1 in text insets each side
            lines = text_measure.wrap_real(title, size=box["size"], max_width=wrap_width, family=box["family"], weight=box["weight"])
            words = _copy_words(title)
            if len(lines) > 2:
                issues.append(f"TITLE_FIT: the title needs {len(lines)} lines at the locked {box['size']:g} px in a {box['width']:.0f} px title box "
                              f"(two at most): cut it to its claim in 15 words or fewer, never shrink it")
            if words > 15 and not sparse:
                issues.append(f"TITLE_FIT: the title has {words} words; a consulting action title states its claim in 15 or fewer")
        row = {"slide": head, "layout": layout or "-", "sparse": sparse, "title_lines": len(lines) if title else 0}
        if not sparse:
            copy = planned_copy(block)
            area = type_floor.body_area(project, lock, layout)
            fit = record_capacity(copy, area, body_family, floors)
            row.update(words=fit["words"], capacity=fit["capacity"], ratio=round(fit["ratio"], 2), table=bool(copy["table"]), area=area["source"])
            if fit["ratio"] > OVER_CAPACITY_RATIO:
                issues.append(f"OVER_CAPACITY: slide {number:02d} plans ~{fit['words']} words; at the {floors['body']:g}/{floors['secondary']:g} px floors "
                              f"the body holds ~{fit['capacity']} ({100 * fit['ratio']:.0f}% of the page): cut, split the page, or move detail to notes/appendix"
                              + ("; a planned table is counted at its wrapped height at the secondary floor" if copy["table"] else ""))
        report.append(row)
        if issues:
            found[head] = issues
    return found, report


def capacity_report(report: list[dict]) -> str:
    lines = ["# Plan capacity at the type floors", "", "| Slide | Layout | Words | Holds ~ | Fill | Title lines |", "|---|---|---:|---:|---:|---:|"]
    for row in report:
        if row.get("sparse"):
            lines.append(f"| {row['slide']} | {row['layout']} | sparse page | | | {row['title_lines']} |")
        else:
            lines.append(f"| {row['slide']} | {row['layout']} | {row['words']} | {row['capacity']} | {100 * row['ratio']:.0f}% | {row['title_lines']} |")
    return "\n".join(lines) + "\n"


def plan_lint(spec: str, target_low: int | None = None, lock: str | None = None, project: Path | None = None,
              report: list | None = None) -> dict[str, list[str]]:
    """Check the semantic handoff and reader-facing copy. With the execution lock it also holds each record to the page it will be
    drawn on (plan_capacity): OVER_CAPACITY at the type floors and TITLE_FIT at the locked title size. Density below capacity is a
    choice, never a finding; `report` (a list) receives one fill-ratio row per record for the plan report."""
    found: dict[str, list[str]] = {}
    for block in re.split(r"\n(?=#### Slide )", spec)[1:]:
        head = block.splitlines()[0].replace("#### ", "").strip()
        issues: list[str] = []
        if not re.fullmatch(r"Slide \d+\s*[-–—]\s*.+", head):
            issues.append("slide heading must identify a number and name so the runner can parse it")

        def field(name: str) -> str:
            m = re.search(rf"- \*\*{name}\*\*(?: \([^)]*\))?:(.*?)(?=\n- \*\*[A-Z][^*]*\*\*|\Z)", block, re.S)
            return m.group(1) if m else ""

        for name in ("Role", "Author tier", "Layout", "Audience question", "Audience move", "Story link", "Relationships",
                     "Title", "Core message", "Content", "Sources", "Visual task", "Visual approach", "Composition", "Hierarchy", "Avoid", "Editor notes"):
            if not field(name).strip():
                issues.append(f"missing field `{name}`")
        if field("Audience question").strip() and "?" not in field("Audience question"):
            issues.append("`Audience question` must be phrased as a question the reader can answer from this page")
        if re.search(r"\b[xy]\s*=\s*\d|\b(?:width|height)\s*=\s*\d", field("Visual approach") + field("Composition") + field("Hierarchy")):
            issues.append("the plan prescribes element geometry; leave coordinates and fit to the page author")
        copy = field("Content")
        filler = FILLER.findall(copy)
        if len(filler) >= 4:
            issues.append(f"`Content` repeats filler ({len(filler)} x `{filler[0]}`): design the page around what is known")
        lines = [ln.strip() for ln in copy.splitlines() if len(ln.strip()) > 20]
        repeated = {ln for ln in lines if lines.count(ln) >= 3}
        if repeated:
            issues.append("`Content` repeats identical rows: " + next(iter(repeated))[:80])
        leaked = INTERNAL.findall(field("Title") + " " + field("Core message") + " " + copy)
        if leaked:
            issues.append(f"client-facing copy carries an internal note (`{leaked[0]}`): move it to `Editor notes`")
        if issues:
            found[head] = issues
    for head, issues in undefined_terms(spec).items():  # self-containment: what a reader with no context cannot read
        found.setdefault(head, []).extend(issues)
    if lock is not None:
        capacity, rows = plan_capacity(spec, lock, project)
        for head, issues in capacity.items():
            found.setdefault(head, []).extend(issues)
        if report is not None:
            report.extend(rows)
    return found


OFFICE_DEFAULT_FONTS = {"Calibri", "Calibri Light", "Aptos", "Aptos Display"}
OFFICE_DEFAULT_ACCENTS = {"4F81BD", "C0504D", "9BBB59", "8064A2", "4BACC6", "F79646", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5", "70AD47",
                          "156082", "E97132", "196B24", "0F9ED5", "A02B93", "4EA72E"}


def template_styles_used(pptx: Path) -> dict:
    """The fonts and colours a template's slides, layouts and masters actually set - which is where a generated template (the Create
    Template route's review PPTX) keeps its identity, while its theme stays the Office default (selfdoc test, 24 Sep 2026: the deck
    followed the default theme's Calibri instead of the template's Georgia and Arial)."""
    import zipfile
    title_fonts: dict[str, int] = {}
    text_fonts: dict[str, int] = {}
    colours: dict[str, int] = {}
    defaults: list[bool] = []  # a notes or handout theme is often the Office default even when the slides' theme is not
    with zipfile.ZipFile(pptx) as z:
        for name in z.namelist():
            if re.match(r"ppt/theme/theme\d+\.xml$", name):
                xml = z.read(name).decode("utf-8", errors="replace")
                faces = set(re.findall(r'<a:(?:major|minor)Font>\s*<a:latin typeface="([^"]+)"', xml))
                accents = set(re.findall(r'<a:accent\d>\s*<a:srgbClr val="([0-9A-Fa-f]{6})"', xml))
                defaults.append(bool(faces) and faces <= OFFICE_DEFAULT_FONTS and {a.upper() for a in accents} <= OFFICE_DEFAULT_ACCENTS)
            if not re.match(r"ppt/(slides/slide|slideLayouts/slideLayout|slideMasters/slideMaster)\d+\.xml$", name):
                continue
            xml = z.read(name).decode("utf-8", errors="replace")
            for shape in re.findall(r"<p:sp>.*?</p:sp>", xml, re.S):
                target = title_fonts if re.search(r'<p:ph[^>]*type="(?:title|ctrTitle)"', shape) else text_fonts
                for face in re.findall(r'<a:latin typeface="([^"+][^"]*)"', shape):
                    target[face] = target.get(face, 0) + 1
            for colour in re.findall(r'<a:srgbClr val="([0-9A-Fa-f]{6})"', xml):
                colours[colour.upper()] = colours.get(colour.upper(), 0) + 1
    ranked = lambda d: [k for k, _ in sorted(d.items(), key=lambda kv: -kv[1])]  # noqa: E731
    return {"title_fonts": ranked(title_fonts)[:3], "text_fonts": ranked(text_fonts)[:4], "colours": [f"#{c}" for c in ranked(colours)[:10]],
            "theme_is_default": bool(defaults) and all(defaults)}


def parse_pages(spec: str) -> list[dict]:
    """One dict per `#### Slide NN - name` block of §IX, in roster order."""
    outline = spec[spec.index("## IX."):] if "## IX." in spec else spec
    headers = list(re.finditer(r"^#### Slide (\d+)\s*[-–—]\s*(.+?)[ \t]*$", outline, re.M))
    pages = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(outline)
        block = outline[header.start():end]
        block = re.split(r"\n(?=### |## )", block)[0].rstrip()

        def field(name: str, block: str = block) -> str:
            match = re.search(rf"^- \*\*{name}(?: \([^)]*\))?\*\*:[ \t]*(.+)$", block, re.M)
            return match.group(1).strip() if match else ""

        number = int(header.group(1))
        name = header.group(2).strip()
        slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40].rstrip("_")
        tier = field("Author tier").lower()
        pages.append({"number": number, "name": name, "stem": f"{number:02d}_{slug}", "record": block,
                      "tier": tier if tier in ("frontier", "workhorse") else "workhorse",
                      "role": field("Role").lower(), "title": field("Title"), "core_message": field("Core message"),
                      "layout": (re.sub(r"[^a-z0-9_-]", "", field("Layout").lower().split()[0]) if field("Layout") else "")
                                or ("cover" if "cover" in field("Role").lower() else "content")})
    return pages


def speaker_notes_enabled(spec: str) -> bool:
    """Only an explicit enabled outcome in §X authorizes generated speaker notes."""
    section = re.search(r"(?ms)^## X\. Speaker Notes Requirements[ \t]*\n(.*?)(?=^## |\Z)", spec)
    if not section:
        return False
    generation = re.search(r"(?m)^- \*\*Generation\*\*:[ \t]*(enabled|disabled)\b", section.group(1), re.I)
    return bool(generation and generation.group(1).lower() == "enabled")


def deck_digest(pages: list[dict]) -> str:
    lines = [f"- P{p['number']:02d} ({p['role'] or 'page'}, file {p['stem']}.svg): {p['title']} - {p['core_message']}" for p in pages]
    return "\n".join(lines)


TEMPLATE_TOUCH = """## What you may touch (template stage)
- You are the TEMPLATE DESIGNER of this deck, not a page author: write only under `{project}/templates/` (one SVG per layout and `template.md`). Never edit the design spec, the lock, the pages or the sources.
- Never run the checker, finalize, export, the contact sheet or the preview server: the deck runner does those.
- I am away: every decision is delegated to you. Never stop to ask.
- The page authors' brief above tells you what every page author will be told: each page is drawn inside one of your layouts.

"""


def template_brief_system(project: Path) -> str:
    """The page-author brief as the template designer's reference, with its 'what you may touch' rules replaced by the template
    stage's own: the page rules forbid writing templates, and a model that obeys them refuses the template job."""
    head, _, rest = PAGE_AUTHOR_BRIEF.partition("## What you may touch")
    _, _, tail = rest.partition("\n## ")
    return (head.replace("# Page author", "# Template designer\n\nYou design this deck's TEMPLATE; your job is in the first user message. Everything from here to "
                         "'What you may touch' is the brief every PAGE AUTHOR receives - read it as what your layouts must serve, not as your job.\n\n"
                         "## The page authors' brief (for reference)", 1)
            + TEMPLATE_TOUCH.format(project=project.relative_to(ROOT).as_posix()) + "## " + tail)


def build_system(project: Path, pages: list[dict], calibration: str, role: str = "page") -> str:
    spec = (project / "design_spec.md").read_text(encoding="utf-8")
    head, _, outline = spec.partition("## IX.")
    first_slide = re.search(r"^### Part|^#### Slide", outline, re.M)
    outline_intro = ("## IX." + outline[:first_slide.start()]).rstrip() if first_slide else ""
    parts = [template_brief_system(project) if role == "template" else PAGE_AUTHOR_BRIEF, "# Contract documents\n"]
    for rel in CONTRACT_DOCS:  # static first: the prefix is shared by every page of every deck
        path = SKILL / rel
        if path.is_file():
            parts.append(f"\n<document path=\"skills/ppt-master/{rel}\">\n{path.read_text(encoding='utf-8')}\n</document>\n")
    project_rel = project.relative_to(ROOT).as_posix()
    parts.append(f"\n# This deck - project `{project_rel}`\n\n## Design spec: project, canvas, theme, typography, layout, icons, images\n\n{head.rstrip()}\n")
    parts.append(f"\n## Outline note and Narrative\n\n{outline_intro}\n")
    parts.append(f"\n## Deck digest - what every page says (you author one of them)\n\n{deck_digest(pages)}\n")
    lock = project / "spec_lock.md"
    if lock.is_file():
        parts.append(f"\n## Execution lock (spec_lock.md)\n\n{lock.read_text(encoding='utf-8')}\n")
    catalog = project / "analysis" / "source_visuals" / "catalog.md"
    if catalog.is_file():
        parts.append(f"\n## Source visual inventory\n\nThe supplied visual candidates and their provenance are listed at "
                     f"`{catalog.relative_to(ROOT).as_posix()}`. Use only the assets selected in your slide record; "
                     "inspect their actual pixels before placing them.\n")
    if calibration:
        parts.append(f"\n## Text calibration (text_measure.py calibrate --outline)\n\n```\n{calibration.strip()[:6000]}\n```\n")
    return "".join(parts)


def page_task(project: Path, page: dict, anchor: dict | None, note: str = "") -> str:
    project_rel = project.relative_to(ROOT).as_posix()
    layout = project / "templates" / f"{page.get('layout') or 'content'}.svg"
    if layout.is_file():
        chrome = (f"TEMPLATE: your layout is `{project_rel}/templates/{layout.name}` - read it first. The template's rules are already in your system prompt "
                  "(the deck's template section): do not read template.md again. "
                  "Copy the layout's `<g id=\"chrome\" data-pptx-role=\"chrome\">` group into your page VERBATIM as its first group (same ids, role, positions, paint - it becomes a slide layout "
                  "in PowerPoint, so every page's copy must be identical). Set your own eyebrow, title, source line and folio (the plain slide number, `7` not `07`) exactly where and how the layout's "
                  "`sample-*` texts show (position, size, weight, colour, leading) - do not copy the sample group itself - and keep your figure inside the body zone.")
    elif anchor is None or anchor["stem"] == page["stem"]:
        chrome = ("CHROME: you ARE the deck's chrome anchor. Every other page will copy your header, title zone and footer exactly, "
                  "so draw them cleanly and conventionally from §I Template Application and §II.")
    elif page["role"] == "cover":
        chrome = (f"CHROME SOURCE: `{project_rel}/svg_output/{anchor['stem']}.svg` - read it first; a cover follows its own record for the field "
                  "and takes only the footer style (source line, deck line, folio) from it.")
    else:
        chrome = (f"CHROME SOURCE: `{project_rel}/svg_output/{anchor['stem']}.svg` - read it first and reproduce its header, title zone and footer "
                  "exactly; change only the eyebrow, the title, the source line and the folio.")
    return (f"PAGE JOB\n\nProject: `{project_rel}`\nYour page: Slide {page['number']:02d} - {page['name']}\n"
            f"Your file: `{project_rel}/svg_output/{page['stem']}.svg` (this exact name; `<stem>` is `{page['stem']}`)\n{chrome}\n{note}\n"
            f"SLIDE RECORD\n\n{page['record']}\n")


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project = Path(args.project).resolve()
        self.sessions = Path(os.environ.get("PPT_MASTER_SESSIONS_DIR") or (ROOT / ".host-sessions")).resolve()
        self.deck_dir = self.sessions / f"{args.session}.deck"
        self.deck_dir.mkdir(parents=True, exist_ok=True)
        self.authors = dict(DEFAULT_AUTHORS)
        if getattr(args, "premium", False):
            self.authors["frontier"] = dict(PREMIUM_FRONTIER)
        if args.authors:
            self.authors.update(json.loads(Path(args.authors).read_text(encoding="utf-8")))
        self.reviewers = dict(DEFAULT_REVIEWERS)
        if args.reviewers:
            self.reviewers.update(json.loads(Path(args.reviewers).read_text(encoding="utf-8")))
        self.page_sessions: dict[str, list[str]] = {}
        self.authored_by: dict[str, str] = {}
        self.session_tier: dict[str, str] = {}
        self.outstanding: dict[str, list[str]] = {}
        self.lint_open: dict[str, list[str]] = {}
        self.checker_repairs: dict[str, int] = {}  # checker repair rounds spent per page (page-level and deck-level share the budget)
        self.text_in_shapes = ""
        self.native_refused = ""
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))

    # --- plumbing ---------------------------------------------------------------------------------
    def script(self, name: str, *script_args: str, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / name), *script_args], cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=check, env={**os.environ, "PYTHONUTF8": "1"})

    def prepare_source_assets(self) -> None:
        """Expose visuals in supplied decks and files before content planning."""
        from source_assets import prepare
        catalog = prepare(self.project, SCRIPTS)
        if catalog["documents"] or catalog["assets"] or catalog["issues"]:
            self.say(f"source visuals: {len(catalog['documents'])} converted document(s), "
                     f"{len(catalog['assets'])} candidate image(s), {len(catalog['issues'])} intake issue(s); "
                     "see analysis/source_visuals/catalog.md")

    def host(self, session: str, tier: str, extra: list[str]) -> int:
        author = self.authors[tier]
        env = {**os.environ, "PYTHONUTF8": "1", "PPT_MASTER_MODEL": author["model"], "PPT_MASTER_EFFORT": author.get("effort", "medium"),
               "PPT_MASTER_API_BASE": author.get("api_base", "https://api.openai.com/v1"), "PPT_MASTER_API_KEY_VAR": author.get("key_var", "OPENAI_API_KEY"),
               "PPT_MASTER_SYSTEM_FILE": str(self.deck_dir / "system.md"), "PPT_MASTER_SESSIONS_DIR": str(self.sessions)}
        env.pop("PPT_MASTER_STATELESS", None)
        env.pop("PPT_MASTER_PROVIDER", None)
        if author.get("provider"):
            env["PPT_MASTER_PROVIDER"] = json.dumps(author["provider"])
        env.update(self.reviewer_env(tier))
        log = self.sessions / f"{session}.log"
        with log.open("a", encoding="utf-8") as handle:
            proc = subprocess.run([sys.executable, str(HOST), "--session", session, "--max-turns", str(self.args.max_turns), *extra],
                                  cwd=str(ROOT), stdout=handle, stderr=subprocess.STDOUT, env=env)
        return proc.returncode

    def reviewer_env(self, tier: str) -> dict[str, str]:
        reviewer = self.reviewers.get(tier) or self.reviewers["workhorse"]
        env = {"PPT_MASTER_REVIEW_MODEL": reviewer["model"], "PPT_MASTER_REVIEW_EFFORT": reviewer.get("effort") or "none",
               "PPT_MASTER_REVIEW_API_BASE": reviewer.get("api_base", "https://api.openai.com/v1"), "PPT_MASTER_REVIEW_KEY_VAR": reviewer.get("key_var", "OPENAI_API_KEY")}
        if reviewer.get("provider"):
            env["PPT_MASTER_REVIEW_PROVIDER"] = json.dumps(reviewer["provider"])
        return env

    def final_lint(self, pages: list[dict]) -> dict[str, list[str]]:
        """One last measurement of every page as it ships: what the ruler still finds goes beside the deck, it blocks nothing."""
        import page_lint
        found: dict[str, list[str]] = {}
        for stem in [p["stem"] for p in pages if (self.project / "svg_output" / f"{p['stem']}.svg").is_file()]:
            try:
                result = page_lint.lint_page(self.project, stem, contract=False)
            except Exception as exc:  # noqa: BLE001
                self.say(f"final lint unavailable: {exc}")
                return found
            entry = self.journal_page(stem)
            ruled = entry.get("review") or {}
            for finding in result["blockers"]:
                accepted = not finding.get("hard") and ruled.get("verdict") == "PASS" and ruled.get("sha") == entry.get("last_sha")
                if not accepted:  # a flagged item on a page the reviewer passed was looked at and ruled acceptable
                    found.setdefault(stem, []).append(("CERTAIN " if finding.get("hard") else "FLAGGED ") + finding["message"][:300])
        self.say("final lint: " + (", ".join(f"{k} {len(v)}" for k, v in found.items()) if found else "nothing open"))
        return found

    def journal_page(self, stem: str) -> dict:
        from page_review import load_journal
        return (load_journal(self.project).get("pages") or {}).get(stem) or {}

    def say(self, text: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {text}", flush=True)

    # --- stages -----------------------------------------------------------------------------------
    def author(self, page: dict, tier: str, anchor: dict | None, *, suffix: str = "", note: str = "") -> str:
        session = f"{self.args.session}.{page['stem']}{suffix}"
        task = self.deck_dir / f"{page['stem']}{suffix}.task.txt"
        task.write_text(page_task(self.project, page, anchor, note), encoding="utf-8")
        self.page_sessions.setdefault(page["stem"], []).append(session)
        self.authored_by[page["stem"]] = tier
        self.session_tier[session] = tier + (" (escalated)" if suffix else "")
        started = time.time()
        self.say(f"P{page['number']:02d} {page['stem']}: {tier} author ({self.authors[tier]['model']}) started")
        code = self.host(session, tier, ["--task-file", str(task)])
        entry = self.journal_page(page["stem"])
        self.say(f"P{page['number']:02d} {page['stem']}: {entry.get('outcome') or 'no outcome'} "
                 f"(review {(entry.get('review') or {}).get('verdict')}, {entry.get('revisions', 0)} revisions, {time.time() - started:.0f}s, exit {code})")
        return session

    def fan_out(self, jobs: list) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, self.args.max_parallel)) as pool:
            for future in concurrent.futures.as_completed([pool.submit(job) for job in jobs]):
                future.result()

    def checker(self) -> dict[str, list[str]]:
        self.script("svg_quality_checker.py", str(self.project), "--canonical-authoring", "--stage", "final", "--json")
        report_path = self.project / "validation" / "svg_quality_report.json"
        if not report_path.is_file():
            return {}
        report = json.loads(report_path.read_text(encoding="utf-8"))
        blocking: dict[str, list[str]] = {}
        for issue in ((report.get("categories") or {}).get("blocking") or {}).get("issues") or []:
            blocking.setdefault(Path(str(issue.get("file") or "")).stem or "_project", []).append(str(issue.get("message") or "")[:900])
        project_issues = report.get("project_issues") or {}
        for category, items in (project_issues.items() if isinstance(project_issues, dict) else [("project", project_issues)]):
            for issue in items or []:
                blocking.setdefault("_project", []).append(f"{category}: {str(issue)[:900]}")
        return blocking

    def page_checker(self, page: dict) -> list[str]:
        """The deck checker's verdict on this one file, as soon as its author is done: a page does not wait for its slowest sibling
        to learn that it needs a repair. The deck-wide checker still runs after all pages (roster, project-level items)."""
        import page_lint
        svg = self.project / "svg_output" / f"{page['stem']}.svg"
        if not svg.is_file():
            return []
        try:
            return [finding["message"] for finding in page_lint.contract_issues(svg)]
        except Exception as exc:  # noqa: BLE001 - the deck-wide checker after all pages is the gate that counts
            self.say(f"P{page['number']:02d} {page['stem']}: page checker unavailable ({type(exc).__name__}) - left to the deck checker")
            return []

    def check_and_repair(self, page: dict) -> None:
        stem = page["stem"]
        while self.checker_repairs.get(stem, 0) < self.args.repair_rounds:
            issues = self.page_checker(page)
            if not issues:
                return
            self.checker_repairs[stem] = self.checker_repairs.get(stem, 0) + 1
            self.say(f"P{page['number']:02d} {stem}: checker repair {self.checker_repairs[stem]} of {self.args.repair_rounds}, straight after its author")
            self.repair(page, issues)

    def after_author(self, page: dict, anchor: dict | None) -> None:
        """What used to wait for every page: the page's checker repairs, then - for a workhorse page left unaccepted - escalation to
        the frontier author and that author's checker repairs. Runs inside the page's own job, so it starts the moment the page ends."""
        if page["stem"] not in self.page_sessions:
            return
        self.check_and_repair(page)
        if (not self.args.no_escalate and self.authored_by.get(page["stem"]) == "workhorse"
                and self.journal_page(page["stem"]).get("outcome") != "accepted"):
            self.say(f"P{page['number']:02d} {page['stem']}: escalating to the frontier author")
            self.escalate(page, anchor)
            self.check_and_repair(page)

    def repair(self, page: dict, issues: list[str], hint: str = "") -> None:
        session = self.page_sessions[page["stem"]][-1]
        listing = "\n".join(f"- {text}" for text in issues) + (f"\n\n{hint}" if hint else "")
        message = (f"The deck's final quality checker found blocking issues in your page `{page['stem']}.svg`. This repair is allowed beyond the page's "
                   f"revision budget. Fix exactly these and change nothing else, render the page, ask the reviewer for the new revision, and record the "
                   f"outcome again with `note` (accepted on PASS, otherwise unresolved with the items named). Then reply `DONE {page['stem']} <outcome>`.\n\n{listing}")
        self.say(f"P{page['number']:02d} {page['stem']}: repair of {len(issues)} item(s)")
        before = json.loads(json.dumps(self.journal_page(page["stem"])))
        self.host(session, self.authored_by[page["stem"]], ["--answer", message])
        self.settle(page, before)

    def settle(self, page: dict, before: dict, user_change: bool = False) -> str:
        """After a repair: a page that had passed is never left demoted (keep_or_restore). A change the user asked for is never rolled back."""
        from page_review import update_journal, _page_entry
        stem = page["stem"]
        after = self.journal_page(stem)
        decision = keep_or_restore(before, after)
        if decision == "restore" and user_change:
            decision = "fine"
            self.say(f"P{page['number']:02d} {stem}: the user's change stands although its review is {((after.get('review') or {}).get('verdict'))} - see the review")
        if decision == "keep":
            def keep(journal: dict) -> None:
                entry = _page_entry(journal, stem)
                entry["outcome"] = "accepted"
                entry["kept_after_repair"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "review": (entry.get("review") or {}).get("verdict"),
                                              "why": "the page had passed; the repair's review found no defect, only polish"}
            update_journal(self.project, keep)
            self.say(f"P{page['number']:02d} {stem}: stays accepted - it had passed, and the repair's review found no defect")
        elif decision == "restore":
            passed = before.get("review") or {}
            backup = next((b for b in before.get("backups") or [] if b.get("sha") == passed.get("sha")), None)
            if backup is None:
                self.say(f"P{page['number']:02d} {stem}: could not find the revision that passed - left as the repair made it")
                return "fine"
            self.script("page_review.py", "restore", str(self.project), stem, "--rev", str(backup["rev"]))
            os.environ["PPT_MASTER_NO_LINT"], previous = "1", os.environ.get("PPT_MASTER_NO_LINT")
            self.script("page_review.py", "render", str(self.project), stem)  # the preview image follows the restored file
            os.environ.pop("PPT_MASTER_NO_LINT") if previous is None else os.environ.__setitem__("PPT_MASTER_NO_LINT", previous)

            def put_back(journal: dict) -> None:
                entry = _page_entry(journal, stem)
                entry["review"], entry["outcome"], entry["lint"] = passed, "accepted", before.get("lint")
                entry["repair_rolled_back"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "why": "the repaired revision did not pass; the revision that had passed was restored",
                                               "failed_review": (after.get("review") or {}).get("file")}
            update_journal(self.project, put_back)
            self.say(f"P{page['number']:02d} {stem}: repair rolled back - the revision that had passed (rev{backup['rev']}) is restored; the failed attempt's review is kept")
        return decision

    def sessions_of(self, stem: str) -> tuple[str, str] | None:
        """The page's latest conversation from an earlier run of this session name, and the tier that owns it."""
        folders = sorted((f for f in self.sessions.glob(f"{self.args.session}.{stem}*") if f.is_dir()), key=lambda f: f.stat().st_mtime)
        if not folders:
            return None
        state = folders[-1] / "state.json"
        model = json.loads(state.read_text(encoding="utf-8")).get("model", "") if state.is_file() else ""
        return folders[-1].name, ("workhorse" if model == self.authors["workhorse"]["model"] else "frontier")

    def revise(self) -> int:
        """Revise from the user's comments: every annotated page goes back to its own author; then checker, export, final lint."""
        started = time.time()
        self.prepare_source_assets()
        pages = {p["stem"]: p for p in parse_pages((self.project / "design_spec.md").read_text(encoding="utf-8"))}
        comments = {stem: items for stem, items in collect_annotations(self.project).items() if stem in pages}
        if not comments:
            print("no comments found: annotate elements in the live preview (the URL is in live_preview/lock.json), save, and run --revise again")
            return 0
        self.say("comments: " + ", ".join(f"{stem} {len(items)}" for stem, items in comments.items()))
        if self.args.dry_run:
            for stem, items in comments.items():
                print(f"\n--- would be sent to {self.sessions_of(stem)} ---\n{revision_message(stem, items)}")
            return 0
        import page_review
        page_review._ensure_server(self.project)
        system = self.deck_dir / "system.md"
        if not system.is_file():
            calibration = self.script("text_measure.py", "calibrate", str(self.project), "--outline").stdout
            system.write_text(build_system(self.project, list(pages.values()), calibration) + self.template_rules(), encoding="utf-8")
        jobs = []
        for stem, items in comments.items():
            found = self.sessions_of(stem)
            if found is None:
                self.say(f"{stem}: no author session of `{self.args.session}` found - skipped")
                continue
            session, tier = found
            self.page_sessions[stem], self.authored_by[stem] = [session], tier

            def job(stem=stem, items=items, session=session, tier=tier) -> None:
                before = json.loads(json.dumps(self.journal_page(stem)))
                self.say(f"P{pages[stem]['number']:02d} {stem}: {len(items)} comment(s) to its author ({self.authors[tier]['model']})")
                self.host(session, tier, ["--answer", revision_message(stem, items)])
                self.settle(pages[stem], before, user_change=True)
            jobs.append(job)
        self.fan_out(jobs)
        blocking = self.checker()
        deck = self.export(dict(blocking) or None)  # deck-level (_project) items also need the override: the exporter refuses any failed report
        self.lint_open = self.final_lint(list(pages.values()))
        left = collect_annotations(self.project)
        self.say(f"revised in {(time.time() - started) / 60:.1f} min; deck: {deck.relative_to(ROOT) if deck else 'none'}; comments still marked: "
                 + (", ".join(f"{k} {len(v)}" for k, v in left.items()) if left else "none"))
        return 0

    def escalate(self, page: dict, anchor: dict | None) -> None:
        from page_review import update_journal, _page_entry
        entry = self.journal_page(page["stem"])
        review_file = (entry.get("review") or {}).get("file")
        remaining = (self.project / review_file).read_text(encoding="utf-8")[:6000] if review_file and (self.project / review_file).is_file() else "(no review on file)"

        def reset(journal: dict) -> None:
            current = _page_entry(journal, page["stem"])
            current["escalated_from"] = {"tier": "workhorse", "revisions": current.get("revisions"), "outcome": current.get("outcome")}
            current["revisions"], current["outcome"] = 0, None

        update_journal(self.project, reset)
        note = ("\nESCALATION: a first author left this page unresolved. Its SVG is at your file path: read it, keep what works, and redraw what does not - "
                "you have a fresh revision budget. The independent reviewer's last report on it:\n\n" + remaining + "\n")
        self.author(page, "frontier", anchor, suffix=".frontier", note=note)

    def deck_review(self, pages: list[dict]) -> None:
        import page_review
        sheet = self.script("page_review.py", "contact-sheet", str(self.project))
        image = self.project / ".preview" / "contact_sheet.png"
        if not image.is_file():
            self.say(f"deck review skipped: no contact sheet ({sheet.stdout[-200:]})")
            return
        import xml.etree.ElementTree as ET
        drawn_words = []
        for page in pages:
            svg = self.project / "svg_output" / f"{page['stem']}.svg"
            if svg.is_file():
                root = ET.parse(svg).getroot()
                words = [" ".join("".join(element.itertext()).split()) for element in root.iter() if element.tag.endswith("}text") or element.tag == "text"]
                drawn_words.append(f"P{page['number']:02d}: " + " | ".join(w for w in words if w))
        instructions = ("You are a first-time reader sent this deck with no presenter, brief or notes. Read the visual contact sheet and the "
                        "text actually drawn on the slides, in order. Do not infer intent from an unseen plan. First describe the message "
                        "you understand from the deck in three sentences. Then identify pages where the visual fails to show the claimed "
                        "comparison, sequence, boundary, example or evidence; where labels, direction or scope are ambiguous; where type is "
                        "too small or cluttered to read; or where an unexplained term or missing bridge prevents understanding. Check recurring "
                        "names, visual cues, chrome and summary against the body. Prioritize only material issues. Give a `Prioritised change "
                        "list` of bullets starting with PNN and saying what and why. End with `DECK VERDICT: PASS` only if a newcomer "
                        "can follow the deck without oral explanation; otherwise `DECK VERDICT: CHANGES`.")
        content = [{"type": "input_text", "text": "VISIBLE WORDS TRANSCRIBED FROM THE DRAWN SLIDES, IN ORDER:\n\n" + "\n\n".join(drawn_words)},
                   {"type": "input_text", "text": "CONTACT SHEET (roster order, left to right, top to bottom):"}, *page_review._image_item(image)]
        reviewer = self.reviewers["frontier"]  # the whole deck on one sheet is the hardest look of the run
        payload = {"model": reviewer["model"], "instructions": instructions, "store": False, "input": [{"role": "user", "content": content}]}
        if reviewer.get("effort"):
            payload["reasoning"] = {"effort": reviewer["effort"]}
        saved = {k: os.environ.get(k) for k in self.reviewer_env("frontier")}
        os.environ.update(self.reviewer_env("frontier"))
        try:
            review_started = time.time()
            text, usage = page_review._review_call(payload)
        except Exception as exc:  # noqa: BLE001 - the deck still exports without its review
            self.say(f"deck review failed: {exc}")
            return
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        out = self.project / ".review" / "deck_review.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"# Deck review - independent, over the contact sheet\n\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n{text.strip()}\n", encoding="utf-8")
        page_review.update_journal(self.project, lambda journal: journal.setdefault("deck_review", []).append(
            {"model": reviewer["model"], "seconds": round(time.time() - review_started, 1), "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "usage": {k: usage.get(k) for k in ("input_tokens", "output_tokens", "cost")}}))
        verdict = re.search(r"DECK VERDICT\W{0,6}(PASS|CHANGES)", text, re.I)
        self.say(f"deck review: {verdict.group(1).upper() if verdict else 'unparsed'} -> {out.relative_to(ROOT)}")

    def stage_host(self, name: str, task: str, tier: str = "frontier", effort: str | None = None) -> int:
        """One planning-side conversation (planner, template) on the frontier author, with the deck's documents as its system prompt."""
        session = f"{self.args.session}.{name}"
        task_file = self.deck_dir / f"{name}.task.txt"
        task_file.write_text(task, encoding="utf-8")
        self.session_tier[session] = f"{name} ({tier})"
        self.page_sessions.setdefault(f"_{name}", []).append(session)
        if effort:
            saved = dict(self.authors[tier])
            self.authors[tier] = {**saved, "effort": effort}
        started = time.time()
        self.say(f"{name}: {self.authors[tier]['model']} @ {self.authors[tier].get('effort')} started")
        code = self.host(session, tier, ["--task-file", str(task_file)])
        if effort:
            self.authors[tier] = saved
        self.say(f"{name}: finished in {time.time() - started:.0f}s (exit {code})")
        return code

    def solve(self) -> None:
        """What we propose - worked out by the tool from the client's documents and the firm's knowledge base. Runs only when no solution.md is given."""
        if (self.project / "solution.md").is_file() or not (self.project / "sources").is_dir() or (self.project / "design_spec.md").is_file():
            return
        project_rel = self.project.relative_to(ROOT).as_posix()
        document = getattr(self.args, "brief", "proposal") == "document"
        (self.deck_dir / "system.md").write_text(
            ("You are the editor of a consulting-quality deck that documents or explains a subject for readers with no context. Read the sources and the repository, "
             "verify, decide and write; use the file tools only.\n") if document else
            "You work for a consulting firm's proposal team. Read, think, decide and write; use the file tools only.\n", encoding="utf-8")
        self.stage_host("solution", (DOCUMENT_BRIEF if document else SOLUTION_BRIEF).format(project=project_rel), effort=self.args.planner_effort)
        if not (self.project / "solution.md").is_file():
            raise SystemExit("the solution stage did not write solution.md")

    def plan(self) -> None:
        """Narrative -> Structure -> Slides, written by the planner into design_spec.md and spec_lock.md. A stage runs only when its product is missing."""
        if (self.project / "design_spec.md").is_file() and (self.project / "spec_lock.md").is_file():
            return
        project_rel = self.project.relative_to(ROOT).as_posix()
        exemplar = self.args.exemplar or "projects/pga-sentinel-par4_20260920"
        parts = [PAGE_AUTHOR_BRIEF.split("## What you may touch")[0].replace("# Page author", "# Planner's view of what the page authors are told"), "# Documents\n"]
        for rel in ("references/plan-core.md", "references/diagram-clarity.md", "references/consulting-typesetting.md", "references/consulting-review.md"):
            parts.append(f"\n<document path=\"skills/ppt-master/{rel}\">\n{(SKILL / rel).read_text(encoding='utf-8')}\n</document>\n")
        calibration = PLANNER_EXAMPLES / "story_calibration.md"
        parts.append(f"\n# Few-shot planning examples (structure and granularity only)\n\n{calibration.read_text(encoding='utf-8')}\n")
        (self.deck_dir / "system.md").write_text("".join(parts), encoding="utf-8")
        self.stage_host("planner", PLANNER_BRIEF.format(project=project_rel, exemplar=f"{exemplar}/design_spec.md", exemplar_lock=f"{exemplar}/spec_lock.md",
                                                        ),
                        effort=self.args.planner_effort)
        if not (self.project / "design_spec.md").is_file() or not (self.project / "spec_lock.md").is_file():
            raise SystemExit("the planner did not write design_spec.md and spec_lock.md")
        (self.project / "svg_output").mkdir(exist_ok=True)
        for revision in range(3):
            lock = (self.project / "spec_lock.md").read_text(encoding="utf-8")
            fill: list[dict] = []
            issues = plan_lint((self.project / "design_spec.md").read_text(encoding="utf-8"), lock=lock, project=self.project, report=fill)
            (self.project / ".review").mkdir(exist_ok=True)
            (self.project / ".review" / "plan_capacity.md").write_text(capacity_report(fill), encoding="utf-8")
            if not re.search(r"(?m)^## pptx_structure\s*\n- mode: flat\s*$", lock) or re.search(r"(?m)^## (?:pptx_masters|pptx_layouts|page_pptx_layouts|page_layouts)\s*$", lock):
                issues.setdefault("Deck", []).append("this runner requires pptx_structure.mode: flat and no structured mapping sections; imported template slides are visual references, not complete Slide prototypes")
            validated = self.script("project_manager.py", "validate", str(self.project))
            if validated.returncode:
                errors = validated.stdout.split("[ERROR]", 1)[-1].split("[WARN]", 1)[0]
                issues.setdefault("Deck", []).append("project validation failed: " + " ".join(errors.split())[:1200])
            for head, items in self.newcomer_read().items():
                issues.setdefault(head, []).extend(items)
            if not issues:
                self.say("plan check: clean after blind reader review")
                break
            if revision == 2:
                raise SystemExit("plan remains unclear after three reviews: " + "; ".join(f"{k}: {v}" for k, v in issues.items())[:1200])
            self.say("plan check: " + ", ".join(f"{k.split(' - ')[0]} {len(v)}" for k, v in issues.items()) + " - back to the planner")
            listing = "\n".join(f"- {slide}: " + "; ".join(items) for slide, items in issues.items())
            message = ("A blind reader saw only the visible slide words in order and identified missing understanding. Repair the story, "
                       "definitions, evidence, transitions and visual task in the affected records of "
                       f"`{project_rel}/design_spec.md`. Edit the roster if needed; preserve verified facts and the user's page constraints. "
                       "Do not add filler or pixel coordinates. OVER_CAPACITY and TITLE_FIT items are measured at the type floors: cut the copy, split "
                       "the page or move detail to an appendix page, and shorten titles; never plan smaller type. Then reply `DONE plan <number of pages>`.\n\n" + listing)
            saved = dict(self.authors["frontier"])
            self.authors["frontier"] = {**saved, "effort": self.args.planner_effort}
            try:
                self.host(f"{self.args.session}.planner", "frontier", ["--answer", message])
            finally:
                self.authors["frontier"] = saved

    def prepare_base_template(self) -> None:
        """An official template the deck must be built on: copied into the project, rendered as PowerPoint draws it, imported to SVG
        (masters and layouts), its layouts drawn to PNG, and summarised in sources/base-template.md for the solution, planner and
        template stages. Everything else stays outside sources/, which the solution and planning stages read file by file."""
        source = Path(self.args.base_template).resolve()
        workspace_spec = None
        if source.is_dir():  # a template workspace from the Create Template route: its review PPTX is the template, its design spec explains it
            previews = sorted(source.glob("exports/*template_preview*.pptx")) or sorted(source.glob("exports/*.pptx")) or sorted(source.glob("*.pptx"))
            specs = sorted(source.glob("templates/design_spec*.md")) or sorted(source.glob("design_spec*.md"))
            if not previews:
                raise SystemExit(f"no review PPTX in the template workspace {source} (expected exports/<id>_template_preview.pptx)")
            workspace_spec, source = (specs[0] if specs else None), previews[-1]
        if not source.is_file():
            raise SystemExit(f"no such template: {source}")
        folder = self.project / "base_template"
        summary = self.project / "sources" / "base-template.md"
        if summary.is_file() and (folder / "import" / "analysis" / "manifest.json").is_file():
            self.say("base template: prepared earlier - " + summary.relative_to(ROOT).as_posix())
            return
        folder.mkdir(parents=True, exist_ok=True)
        pptx = folder / "template.pptx"
        if source.suffix.lower() == ".potx":  # a template package: the same parts under another main content type
            import zipfile
            with zipfile.ZipFile(source) as zin, zipfile.ZipFile(pptx, "w", zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    data = zin.read(item.filename)
                    if item.filename == "[Content_Types].xml":
                        data = data.replace(b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
                    zout.writestr(item, data)
        else:
            shutil.copyfile(source, pptx)
        rendered = self.script("pptx_render.py", str(pptx), "--out", str(folder / "render"))
        imported = self.script("pptx_template_import.py", str(pptx), "-o", str(folder / "import"), "--inheritance-mode", "both")
        manifest_path = folder / "import" / "analysis" / "manifest.json"
        if not manifest_path.is_file():
            raise SystemExit("the base template could not be imported: " + (imported.stdout + imported.stderr)[-800:])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        layout_pngs = self.render_svgs(sorted((folder / "import" / "svg").glob("layout_*.svg")) + sorted((folder / "import" / "svg").glob("master_*.svg")),
                                       folder / "layouts")
        rel = lambda path: path.relative_to(ROOT).as_posix()  # noqa: E731
        theme = manifest.get("theme") or {}
        size = manifest.get("slideSize") or {}
        used = template_styles_used(pptx)
        lines = ["# Our firm's official template", "",
                 f"Every page of this deck is built on our official template `{source.name}`. It is the house style: the fonts and colours its slides "
                 "actually use, its layouts and its marks override any other description of our style. Pages are drawn at "
                 f"{size.get('width_px', 1280)} x {size.get('height_px', 720)} px, the template's own proportions.", "",
                 "## What the template's slides actually use - this governs", "",
                 "Title fonts: " + (", ".join(used["title_fonts"]) or "(none set on the slides - use the theme's)"), "",
                 "Text fonts: " + (", ".join(used["text_fonts"]) or "(none set on the slides - use the theme's)"), "",
                 "Colours, most used first: " + (", ".join(used["colours"]) or "(none set on the slides - use the theme's)"), "",
                 "## The PowerPoint theme", "",
                 "Many templates set fonts and colours on their shapes and leave the file's theme at the Office default. Where the theme below differs "
                 "from what the slides use above, the slides win" + (" - here the theme IS the Office default, so ignore it." if used["theme_is_default"] else "."), "",
                 "Colours (theme slots): " + ", ".join(f"{k} {v}" for k, v in (theme.get("colors") or {}).items()), "",
                 "Fonts: " + ", ".join(f"{k} {v}" for k, v in (theme.get("fonts") or {}).items()), ""]
        families = list(dict.fromkeys(used["title_fonts"] + used["text_fonts"])) or [v for k, v in (theme.get("fonts") or {}).items() if k.endswith("Latin") and v]
        try:
            stand_ins = self.font_stand_ins(families)
        except Exception as exc:  # noqa: BLE001 - the summary is still useful without the font check
            stand_ins = [f"(font check unavailable: {type(exc).__name__})"]
        if stand_ins:
            lines += ["### Fonts the previews cannot draw", "", *stand_ins, ""]
        lines += ["## Layouts", ""]
        by_svg = {png.stem: png for png in layout_pngs}
        lines += ["In each record's `Layout` line, name the layout by the **name to use** below (the page's job decides which one).", ""]
        seen_names: set[str] = set()
        for layout in manifest.get("layouts") or []:
            svg_name = layout.get("svgFile") or ""
            holders = ", ".join(f"{h.get('semanticRole') or h.get('type')}" + (f" at {h['geometry']}" if h.get("geometry") else "") for h in layout.get("placeholders") or [])
            png = by_svg.get(Path(svg_name).stem)
            display = layout.get("displayName") or layout.get("name") or svg_name
            core = re.sub(r"^[\d\s\u00b7.\u2013\u2014-]+", "", display)  # "01 · Editorial cover" -> "Editorial cover"
            core = re.split(r"\s[\u2014\u2013-]\s", core)[-1]  # "deck-name — Blank" -> "Blank"
            use = re.sub(r"[^a-z0-9]+", "_", core.lower()).strip("_") or "layout"
            while use in seen_names:
                use += "_2"
            seen_names.add(use)
            lines.append(f"- name to use: `{use}` - **{display}** ({layout.get('layoutType') or 'layout'}): "
                         f"`{rel(folder / 'import' / 'svg' / svg_name)}`" + (f", render `{rel(png)}`" if png else "") + (f"; placeholders: {holders}" if holders else ""))
        slides = sorted((folder / "render").glob("slide-*.png"))
        lines += ["", "## How PowerPoint draws its sample slides", ""]
        lines += [f"- `{rel(png)}`" for png in slides] or ["(the template has no sample slides; look at the layout renders above)"]
        if (folder / "render" / "contact_sheet.png").is_file():
            lines += ["", f"All sample slides on one sheet: `{rel(folder / 'render' / 'contact_sheet.png')}`"]
        lines += ["", "Look at these images with `read_image`; do not read the SVG files unless you draw the template itself."]
        if workspace_spec is not None:
            shutil.copyfile(workspace_spec, self.project / "sources" / "template-design-spec.md")
            lines += ["", "The template's own design specification (typography, colour, spacing, page families and the reasons for them) is "
                      "`sources/template-design-spec.md`: follow it."]
        summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.base_template_dir = folder
        self.say(f"base template: {source.name} - {len(manifest.get('layouts') or [])} layouts, {len(slides)} sample slide(s) rendered"
                 + ("" if rendered.returncode == 0 else " (PowerPoint render unavailable)") + f"; summary {rel(summary)}")

    def font_stand_ins(self, families: list[str]) -> list[str]:
        """The previews and the lint draw in a browser, PowerPoint in Office. A theme font Office has (often only in its cloud-font
        cache) but the browser cannot draw falls back to whatever comes next in the page's font-family list - and a narrower fallback
        would let text that overflows in PowerPoint pass in the preview. For each such font: measure the real one from Office's cache
        and name the closest installed stand-in that is at least as wide."""
        import base64
        import glob
        from playwright.sync_api import sync_playwright
        cache = Path(os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\FontCache\4\CloudFonts"))
        candidates = [f for f in families] + ["Century Gothic", "Verdana", "Segoe UI", "Arial", "Calibri", "Georgia"]
        sample = "Kirkland's roadmap links equity, privacy and data governance to every priority project in 2023 (Q3)"
        lines: list[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=os.environ.get("PPT_MASTER_BROWSER_CHANNEL") or None)
            try:
                page = browser.new_page()
                for family in families:
                    base_name = family.split(" ")[0] if not (cache / family).is_dir() else family
                    files = sorted(glob.glob(str(cache / family / "*.ttf"))) or sorted(glob.glob(str(cache / base_name / "*.ttf")))
                    faces = "".join(f"@font-face{{font-family:'Real{i}';src:url(data:font/ttf;base64,{base64.b64encode(Path(f).read_bytes()).decode('ascii')})}}"
                                    for i, f in enumerate(files))
                    page.set_content(f"<html><head><style>{faces}</style></head><body>" + "".join(f"<span style=\"font-family:'Real{i}'\">x</span>" for i in range(len(files))) + "</body></html>")
                    widths = page.evaluate("""async ([n, sample, candidates]) => {
                        await document.fonts.ready; const c = document.createElement('canvas').getContext('2d'); const w = f => { c.font = `20px ${f}`; return c.measureText(sample).width; };
                        const fallback = w('monospace'), serif = w('serif');
                        const real = []; for (let i = 0; i < n; i++) real.push(w(`Real${i}`));
                        const installed = {}; for (const f of candidates) { const a = w(`"${f}", monospace`), b = w(`"${f}", serif`); installed[f] = (a === b) ? a : null; }
                        return {real, installed, fallback, serif}; }""", [len(files), sample, candidates])
                    if widths["installed"].get(family):
                        continue  # the browser draws it itself
                    real = max(widths["real"]) if widths["real"] else None
                    usable = {f: w for f, w in widths["installed"].items() if w and f != family}
                    if real is None:
                        lines.append(f"- `{family}`: neither installed nor in Office's font cache here - pages still name it first; the previews show the next font in the list.")
                        continue
                    wider = sorted((w, f) for f, w in usable.items() if w >= real)
                    if wider:
                        width, stand_in = wider[0]
                        lines.append(f"- `{family}`: PowerPoint draws it, the browser cannot. Write `font-family=\"'{family}', '{stand_in}', sans-serif\"` - "
                                     f"{stand_in} stands in for the previews and is {100 * (width / real - 1):.0f}% wider, so what fits in the preview fits in PowerPoint. "
                                     "Never let it fall back to a narrower face.")
                    else:
                        lines.append(f"- `{family}`: PowerPoint draws it, the browser cannot, and no installed face is as wide - leave 10% spare width in every text box set in it.")
            finally:
                browser.close()
        return lines

    def render_svgs(self, svgs: list[Path], out: Path) -> list[Path]:
        """PNG pictures of the imported layout SVGs, drawn from their own folder so their relative image links resolve."""
        out.mkdir(parents=True, exist_ok=True)
        made: list[Path] = []
        if not svgs:
            return made
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=os.environ.get("PPT_MASTER_BROWSER_CHANNEL") or None)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                for svg in svgs:
                    box = re.search(r'viewBox="\s*[\d.-]+[ ,]+[\d.-]+[ ,]+([\d.]+)[ ,]+([\d.]+)', svg.read_text(encoding="utf-8", errors="replace"))
                    width, height = (int(float(box.group(1))), int(float(box.group(2)))) if box else (1280, 720)
                    page.set_viewport_size({"width": width, "height": height})
                    page.goto(svg.resolve().as_uri(), wait_until="load")
                    page.wait_for_timeout(80)
                    target = out / f"{svg.stem}.png"
                    page.screenshot(path=str(target), type="png")
                    made.append(target)
            finally:
                browser.close()
        return made

    def newcomer_read(self) -> dict[str, list[str]]:
        """Blind review of visible slide words only, before any page is drawn."""
        import page_review
        spec = (self.project / "design_spec.md").read_text(encoding="utf-8")
        pages = parse_pages(spec)
        texts = []
        for page in pages:
            m = re.search(r"^- \*\*Content\*\*:(.*?)(?=\n- \*\*[A-Z][^*]*\*\*|\Z)", page["record"], re.M | re.S)
            title = re.search(r"^- \*\*Title\*\*:[ \t]*(.+)$", page["record"], re.M)
            texts.append(f"#### Slide {page['number']:02d} - {page['name']}\nTitle: {title.group(1).strip() if title else ''}\n{(m.group(1) if m else '').strip()}")
        instructions = ("You are a first-time reader of a deck sent without a presenter. You have no brief, source, notes or prior discussion. "
                        "Read only the visible slide title and content in order. After each slide ask: what is this about, what did I learn, why "
                        "should I believe it, and what do I need to know before the next slide? Mark a slide only when a missing definition, "
                        "example, proof, explanation or transition materially prevents an answer. Ignore minor style preferences. A title that "
                        "names a topic without a conclusion is a problem when the page never resolves it. Do not use outside knowledge to fill "
                        "gaps. Report each finding as `Slide NN: problem | repair: specific missing information`. For a whole-deck gap use "
                        "`Deck: problem | repair: specific missing bridge`. If the visible words let a newcomer follow the argument, write "
                        "`VERDICT: PASS`; otherwise end with `VERDICT: REVISE`. Do not infer design intent from unseen material.")
        reviewer = self.reviewers["frontier"]
        payload = {"model": reviewer["model"], "instructions": instructions, "store": False,
                   "input": [{"role": "user", "content": [{"type": "input_text", "text": "\n\n".join(texts)}]}]}
        if reviewer.get("effort"):
            payload["reasoning"] = {"effort": reviewer["effort"]}
        saved = {k: os.environ.get(k) for k in self.reviewer_env("frontier")}
        os.environ.update(self.reviewer_env("frontier"))
        try:
            text, _ = page_review._review_call(payload)
        except Exception as exc:  # noqa: BLE001 - quality gate reports unavailable reviewer
            self.say(f"newcomer read unavailable: {type(exc).__name__}")
            raise SystemExit("blind reader review unavailable; plan cannot be accepted") from exc
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        by_number = {p["number"]: f"Slide {p['number']:02d} - {p['name']}" for p in pages}
        review_path = self.project / ".review" / "plan_reader.md"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text("# Blind reader review of visible planned slide words\n\n" + text.strip() + "\n", encoding="utf-8")
        found: dict[str, list[str]] = {}
        for number, problem in re.findall(r"(?im)^\W*slide\s*0?(\d{1,2})\W*:\s*(.+)$", text):
            head = by_number.get(int(number))
            if head and problem.strip():
                found.setdefault(head, []).append("blind reader: " + problem.strip()[:700])
        for problem in re.findall(r"(?im)^\W*deck\W*:\s*(.+)$", text):
            found.setdefault("Deck", []).append("blind reader: " + problem.strip()[:700])
        if not found and not re.search(r"(?im)^\s*VERDICT:\s*PASS\b", text):
            found.setdefault("Deck", []).append("blind reader review did not yield a parseable PASS; inspect plan_reader.md")
        self.say("newcomer read: " + (", ".join(k.split(" - ")[0] for k in found) if found else "PASS"))
        return found

    def page_capacity(self) -> tuple[dict[str, list[str]], list[dict]]:
        """The plan's capacity contract for this project: per record, the planned words against what its layout holds at the type
        floors, and the title's lines at the locked title size (plan_capacity). Used by the plan gate; callable on its own."""
        spec = (self.project / "design_spec.md").read_text(encoding="utf-8")
        lock = (self.project / "spec_lock.md").read_text(encoding="utf-8")
        return plan_capacity(spec, lock, self.project)

    def template(self, pages: list[dict]) -> None:
        """The deck's template: used when provided, otherwise created - before any page, with no approval gate."""
        folder = self.project / "templates"
        needed = sorted({p["layout"] for p in pages})
        if folder.is_dir() and all((folder / f"{name}.svg").is_file() for name in needed):
            self.mark_chrome()
            self.say("template: provided - " + ", ".join(needed))
            return
        folder.mkdir(exist_ok=True)
        project_rel = self.project.relative_to(ROOT).as_posix()
        lock = (self.project / "spec_lock.md").read_text(encoding="utf-8")
        size = re.search(r"viewBox[^0-9]*0 0 (\d+) (\d+)", lock) or re.search(r"(\d{3,4})\s*[x×]\s*(\d{3,4})", lock)
        width, height = (size.group(1), size.group(2)) if size else ("1280", "720")
        adopt = ""
        if (self.project / "sources" / "base-template.md").is_file() and (self.project / "base_template" / "import").is_dir():
            adopt = BASE_TEMPLATE_BRIEF.format(project=project_rel, imported=(self.project / "base_template" / "import").relative_to(ROOT).as_posix())
        system = self.deck_dir / "system.md"
        page_system = system.read_text(encoding="utf-8") if system.is_file() else None
        calibration = self.script("text_measure.py", "calibrate", str(self.project), "--outline").stdout
        system.write_text(build_system(self.project, pages, calibration, role="template"), encoding="utf-8")
        try:
            self.stage_host("template", TEMPLATE_BRIEF.format(project=project_rel, width=width, height=height) + adopt
                            + "\nLayouts the records name: " + ", ".join(needed) + "\n")
        finally:
            if page_system is not None:
                system.write_text(page_system, encoding="utf-8")
        self.mark_chrome()
        missing = [name for name in needed if not (folder / f"{name}.svg").is_file()]
        self.say("template: " + (f"MISSING {missing} - those pages fall back to the chrome anchor" if missing else "created - " + ", ".join(needed)))

    def mark_chrome(self) -> int:
        """Every layout's `<g id="chrome">` carries `data-pptx-role="chrome"` - deterministic, whatever the template stage wrote. Without it
        the page's own groups overlap the chrome's full-canvas bounds and the checker refuses the page (53 of 59 first renders, 24 Sep 2026)."""
        fixed = 0
        for svg in (self.project / "templates").glob("*.svg") if (self.project / "templates").is_dir() else []:
            text = svg.read_text(encoding="utf-8")
            new = re.sub(r'<g\s+id="chrome"(?![^>]*data-pptx-role=)', '<g id="chrome" data-pptx-role="chrome"', text)
            if new != text:
                svg.write_text(new, encoding="utf-8")
                fixed += 1
        return fixed

    def template_rules(self) -> str:
        rules = self.project / "templates" / "template.md"
        if not rules.is_file():
            return ""
        return chr(10) + "## The deck's template (templates/template.md) - every page follows it" + chr(10) * 2 + rules.read_text(encoding="utf-8") + chr(10)

    def deck_repair(self, pages: list[dict]) -> None:
        """The deck review's findings go back to the authors of the pages they name - one round, in the pages' own sessions."""
        review = self.project / ".review" / "deck_review.md"
        if not review.is_file():
            return
        text = review.read_text(encoding="utf-8")
        changes = text[text.lower().rfind("prioritised change"):] if "prioritised change" in text.lower() else text
        by_number = {p["number"]: p for p in pages}
        wanted: dict[str, list[str]] = {}
        changes = re.split(r"\n\s*DECK VERDICT", changes)[0]
        for item in re.split(r"\n\s*(?=(?:\d+[.)]|[-*•])\s)", changes):  # numbered or bulleted, as the reviewer chose
            item = " ".join(item.split())
            head = re.split(r"\s[—–-]\s|:", re.sub(r"^(?:\d+[.)]|[-*•])\s*", "", item), maxsplit=1)[0]
            numbers = {int(n) for n in re.findall(r"\bP0?(\d{1,2})\b", head)}
            numbers |= {int(n) for n in re.findall(r"(?i)\b(?:page|slide)s?\s+0?(\d{1,2})\b", head)}
            lead = re.match(r"\s*0?(\d{1,2})\s*[,:\u2013\u2014-]", head)  # "07, P08: ..." or "7 - ..." - a bare page number that opens the item
            if lead:
                numbers.add(int(lead.group(1)))
            for number in numbers:
                if number in by_number and by_number[number]["stem"] in self.page_sessions:
                    wanted.setdefault(by_number[number]["stem"], []).append(item[:900])
        if not wanted:
            self.say("deck repair: nothing addressed to a page")
            return
        self.say("deck repair: " + ", ".join(f"{k} {len(v)}" for k, v in wanted.items()))
        hint = ("These findings come from a blind reader of the whole drawn deck. Repair the visual explanation, direct labels, legibility, "
                "missing on-slide definition or cross-page consistency as the finding specifies. Preserve sourced facts and the page's "
                "audience question. If the record itself prevents the repair, say so in your note rather than silently ignoring the issue.")
        by_stem = {p["stem"]: p for p in pages}
        self.fan_out([lambda s=stem, i=items: self.repair(by_stem[s], i, hint) for stem, items in wanted.items()])

    def write_source_map(self, deck: Path) -> int:
        """`<deck>.sources.md`: each slide, its title and the sources its record names - what a later update starts from."""
        pages = parse_pages((self.project / "design_spec.md").read_text(encoding="utf-8"))
        rows = []
        for page in pages:
            m = re.search(r"^- \*\*Sources\*\*:(.*?)(?=\n- \*\*[A-Z][^*]*\*\*|\Z)", page["record"], re.M | re.S)
            title = re.search(r"^- \*\*Title\*\*:[ \t]*(.+)$", page["record"], re.M)
            if m and m.group(1).strip():
                sources = " ".join(m.group(1).split())
                rows.append(f"| {page['number']} | {(title.group(1).strip() if title else page['name'])[:140]} | {sources[:1200]} |")
        if not rows:
            return 0
        deck.with_suffix(".sources.md").write_text("\n".join([f"# Slide-to-source map - {deck.name}", "", "From each slide record's `Sources` line (the planner's). "
                                                             "Verify before relying on it: it names where a claim comes from, it does not prove the claim.", "",
                                                             "| slide | title | sources |", "|---|---|---|", *rows, ""]), encoding="utf-8")
        return len(rows)

    def write_notes(self) -> int:
        """Generate optional notes only when §X explicitly enables them."""
        spec = (self.project / "design_spec.md").read_text(encoding="utf-8")
        if not speaker_notes_enabled(spec):
            return 0
        pages = parse_pages(spec)
        folder = self.project / "notes"
        folder.mkdir(exist_ok=True)
        written = 0
        for page in pages:
            def field(name: str, record: str = page["record"]) -> str:
                match = re.search(rf"^- \*\*{name}(?: \([^)]*\))?\*\*:[ \t]*(.+)$", record, re.M)
                return match.group(1).strip() if match else ""
            data = re.search(r"^- (?:\*\*)?(Fact IDs[^\n]*|Data class[^\n]*)$", page["record"], re.M)
            parts = [("Message", page["core_message"]), ("What this page must do", field("Audience move")), ("How it connects", field("Story link")),
                     ("Notes for the editor", field("Editor notes")), ("Data", data.group(1).replace("**", "") if data else "")]
            text = "\n\n".join(f"{label}: {value}" for label, value in parts if value)
            target = folder / f"{page['stem']}.md"
            if text and not target.is_file():  # never over a note somebody wrote
                target.write_text(text + "\n", encoding="utf-8")
                written += 1
        return written

    def export(self, outstanding: dict[str, list[str]] | None = None) -> Path | None:
        """Export the deck. With checker issues still outstanding after the repair budget, export anyway through the exporter's
        own override: it normalises what it can and still runs the strict converter, so a page that cannot be converted fails loudly."""
        self.script("finalize_svg.py", str(self.project))
        notes = self.write_notes()
        flags = (["--enable-dangerous-nonconforming-svg-export"] if outstanding else [])
        if notes:
            self.say(f"speaker notes written for {notes} page(s) from their records")
        if "data-pptx-replace-with=" in "".join(p.read_text(encoding="utf-8", errors="replace") for p in (self.project / "svg_output").glob("*.svg")):
            flags.append("--native-charts-and-tables")  # a marked table or chart becomes the PowerPoint object, not its drawn fallback
        known = set((self.project / "exports").glob("*.pptx")) if (self.project / "exports").is_dir() else set()
        result = self.script("svg_to_pptx.py", str(self.project), *flags)
        made = set((self.project / "exports").glob("*.pptx")) - known if (self.project / "exports").is_dir() else set()
        if not made and "--native-charts-and-tables" in flags and not getattr(self, "native_retried", False):
            # the exporter names, per page, where a table's JSON and its drawn fallback disagree: the page's own author closes the gap, once
            self.native_retried = True
            findings: dict[str, list[str]] = {}
            for line in (result.stdout + result.stderr).splitlines():
                match = re.match(r"^\s*(\S+)\.svg:\s+(.+)$", line)
                if match and match.group(1) in self.page_sessions:
                    findings.setdefault(match.group(1), []).append(match.group(2)[:1500])
            by_stem = {p["stem"]: p for p in parse_pages((self.project / "design_spec.md").read_text(encoding="utf-8"))}
            if findings:
                self.say("native tables refused - parity repair by the pages' authors: " + ", ".join(f"{k} {len(v)}" for k, v in findings.items()))
                hint = ("These come from the exporter's check that the PowerPoint table (the JSON) says and shows what the drawn fallback does; nothing is visibly wrong. "
                        "Every `<text>` inside the table group must equal, as one string, a cell's text in the JSON: where a cell's text runs over several lines, end each line "
                        "with a space before the next `<tspan>` (so the joined text reads with its spaces), or list the lines as that cell's `paragraphs` in the same order; a cell "
                        "holding a heading and a paragraph lists both as `paragraphs`. Header cells carry their alignment in the JSON (`\"align\": \"l\"`). Keep the look; then "
                        "run stamp_native_fallbacks.py on the page with --write.")
                self.fan_out([lambda s=stem, i=items: self.repair(by_stem[s], i, hint) for stem, items in findings.items() if stem in by_stem])
                blocking = self.checker()  # the exporter wants a fresh, passing report for the repaired pages
                return self.export(dict(blocking) or None)
        if not made and "--native-charts-and-tables" in flags:  # still refused after the authors' repair: ship the drawn tables and say so
            self.say("native tables refused by the exporter - exporting the drawn fallback instead: " + (result.stdout + result.stderr)[-500:].replace(chr(10), " | "))
            self.native_refused = (result.stdout + result.stderr)[-1500:]
            result = self.script("svg_to_pptx.py", str(self.project), *[f for f in flags if f != "--native-charts-and-tables"])
            made = set((self.project / "exports").glob("*.pptx")) - known
        decks = sorted((self.project / "exports").glob("*.pptx"), key=lambda p: p.stat().st_mtime) if (self.project / "exports").is_dir() else []
        if not decks or not made:  # never post-process a deck from an earlier export as if it were this one
            self.say(f"export failed: {result.stdout[-400:]} {result.stderr[-400:]}")
            return None
        decks = sorted(made, key=lambda p: p.stat().st_mtime)
        if not self.args.floating_text:  # text goes inside the shapes it sits on; the exporter's own file is kept under exports/floating-text/
            merged = self.script("pptx_text_in_shapes.py", str(decks[-1]), "--in-place", "--report", str(decks[-1].with_suffix(".text-in-shapes.json")))
            self.text_in_shapes = (merged.stdout.strip().splitlines() or [merged.stderr.strip()[-300:]])[0]
            self.say("text in shapes: " + self.text_in_shapes)
        self.script("pptx_render.py", str(decks[-1]), "--project", str(self.project))
        if outstanding:
            lines = [f"# Outstanding checker issues at export - {decks[-1].name}", "",
                     f"The repair budget ({self.args.repair_rounds} round(s)) was spent with these blocking checker items still open. The deck was exported "
                     "anyway through the exporter's nonconforming-export override; look at these pages in the PowerPoint render first.", ""]
            for stem, issues in outstanding.items():
                lines += [f"## {'the deck (project-level checks)' if stem == '_project' else stem}", *[f"- {text}" for text in issues], ""]
            decks[-1].with_suffix(".outstanding.md").write_text(chr(10).join(lines), encoding="utf-8")
        mapped = self.write_source_map(decks[-1])
        if mapped:
            self.say(f"slide-to-source map: {mapped} page(s) -> {decks[-1].with_suffix('.sources.md').name}")
        self.say(f"exported {decks[-1].relative_to(ROOT)}" + (f" WITH {sum(len(v) for v in outstanding.values())} OUTSTANDING CHECKER ISSUE(S) on {', '.join(outstanding)}" if outstanding else ""))
        return decks[-1]

    def summary(self, pages: list[dict], started: float, deck: Path | None) -> str:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import report
        rows, total_cost, total_calls, total_in, total_out = [], 0.0, 0, 0, 0
        for page in pages:
            entry = self.journal_page(page["stem"])
            for session in self.page_sessions.get(page["stem"], []):
                try:
                    r = report.analyse(self.sessions / session)
                except SystemExit:
                    continue
                total_cost += r.get("cost_usd") or 0.0
                total_calls += r["calls"]
                total_in += r["input_tokens"]
                total_out += r["output_tokens"]
                rows.append(f"| P{page['number']:02d} {page['stem']} | {self.session_tier.get(session, page['tier'])}"
                            f" | {r['model']} @ {r['effort']} | {r['calls']} | {(r['wall_s'] or 0) / 60:.1f} min | {r['max_context'] / 1e3:.0f}k | ${r.get('cost_usd') or 0:.2f}"
                            f" | {entry.get('outcome') or 'none'} ({(entry.get('review') or {}).get('verdict')}, {entry.get('revisions', 0)}r) |")
        accepted = sum(1 for p in pages if self.journal_page(p["stem"]).get("outcome") == "accepted")
        reviews = [r for p in pages for r in self.journal_page(p["stem"]).get("review_log") or []]
        review_cost = sum((r.get("usage") or {}).get("cost") or 0.0 for r in reviews)
        review_models = sorted({r.get("model") for r in reviews if r.get("model")})
        lint_lines = [f"- `{stem}`: {text}" for stem, items in self.lint_open.items() for text in items]
        lines = [f"# Deck run `{self.args.session}` - {self.project.name}", "",
                 f"Wall time {(time.time() - started) / 60:.1f} min; {len(pages)} pages, {accepted} accepted; {total_calls} author calls; "
                 f"{total_in / 1e6:.1f}M input tokens, {total_out / 1e3:.0f}k output; author cost ${total_cost:.2f}; {len(reviews)} reviewer calls by {', '.join(review_models) or 'none'}"
                 f"{f' (${review_cost:.2f} where the endpoint reports cost)' if review_cost else ''}, {sum(r.get('seconds') or 0 for r in reviews) / 60:.1f} min of reviewing."
                 + (f" Export: `{deck.relative_to(ROOT).as_posix()}`." if deck else " No export.")
                 + (f" **Exported with {sum(len(v) for v in self.outstanding.values())} checker issue(s) outstanding on {', '.join(self.outstanding)}** - see the `.outstanding.md` beside the deck." if deck and self.outstanding else ""), "",
                 "| page | tier | author | calls | wall | peak context | cost | outcome |", "|---|---|---|---|---|---|---|---|", *rows, "",
                 *(["## Editable structure", "", self.text_in_shapes, ""] if self.text_in_shapes else []),
                 "## Geometry lint on the pages as shipped", "", *(lint_lines or ["Nothing open: every finding was fixed, or ruled acceptable by the reviewer that passed the page."]), ""]
        text = "\n".join(lines)
        (self.sessions / f"{self.args.session}.summary.md").write_text(text, encoding="utf-8")
        return text

    # --- the run ----------------------------------------------------------------------------------
    def run(self) -> int:
        started = time.time()
        spec_path = self.project / "design_spec.md"
        if getattr(self.args, "base_template", None):
            self.prepare_base_template()
        self.prepare_source_assets()
        self.solve()
        self.plan()
        pages = parse_pages(spec_path.read_text(encoding="utf-8"))
        if self.args.pages:
            wanted = {int(p) for p in self.args.pages}
            pages = [p for p in pages if p["number"] in wanted]
        if not pages:
            raise SystemExit("no `#### Slide NN - name` blocks found in §IX")
        (self.project / "svg_output").mkdir(exist_ok=True)
        import page_review
        page_review._ensure_server(self.project)  # once, before any page renders
        calibration = self.script("text_measure.py", "calibrate", str(self.project), "--outline").stdout
        all_pages = parse_pages(spec_path.read_text(encoding="utf-8"))
        (self.deck_dir / "system.md").write_text(build_system(self.project, all_pages, calibration), encoding="utf-8")
        if not self.args.no_template:
            self.template(all_pages)
            (self.deck_dir / "system.md").write_text(build_system(self.project, all_pages, calibration) + self.template_rules(), encoding="utf-8")
        templated = all((self.project / "templates" / f"{p['layout']}.svg").is_file() for p in all_pages)
        self.say(f"{len(pages)} page(s): " + ", ".join(f"P{p['number']:02d}:{p['tier']}" for p in pages)
                 + f"; system prompt {(self.deck_dir / 'system.md').stat().st_size / 1e3:.0f} KB")

        anchor = None
        if not self.args.no_anchor and len(all_pages) > 1 and not templated:
            anchor = next((p for p in all_pages if p["role"] != "cover"), all_pages[0])
            if (self.project / "svg_output" / f"{anchor['stem']}.svg").is_file() and anchor["number"] not in {p["number"] for p in pages}:
                self.say(f"anchor P{anchor['number']:02d} already on disk")
            else:
                self.author(anchor, "frontier" if not self.args.anchor_own_tier else anchor["tier"], anchor)
        rest = [p for p in pages if anchor is None or p["stem"] != anchor["stem"]]
        jobs = [lambda p=p: (self.author(p, p["tier"], anchor), self.after_author(p, anchor)) for p in rest]
        if anchor is not None and anchor["stem"] in {p["stem"] for p in pages}:
            jobs.append(lambda: self.after_author(anchor, anchor))
        self.fan_out(jobs)  # each page runs author -> its checker repairs -> escalation on its own, not in lock-step with the others

        by_stem = {p["stem"]: p for p in pages}
        blocking = self.checker()  # the deck-wide gate: roster and project items, and anything a page's own check could not see
        for round_number in range(1, self.args.repair_rounds + 1):  # the exporter refuses a deck whose final report has blocking issues
            to_repair = [(by_stem[stem], issues) for stem, issues in blocking.items()
                         if stem in by_stem and stem in self.page_sessions and self.checker_repairs.get(stem, 0) < self.args.repair_rounds]
            if blocking.get("_project"):
                self.say("checker project issues: " + " | ".join(blocking["_project"])[:600])
            if not to_repair:
                break
            self.say(f"deck checker repair round {round_number}: " + ", ".join(f"{p['stem']} {len(i)}" for p, i in to_repair))
            for p, _ in to_repair:
                self.checker_repairs[p["stem"]] = self.checker_repairs.get(p["stem"], 0) + 1
            self.fan_out([lambda p=p, i=i: self.repair(p, i) for p, i in to_repair])
            blocking = self.checker()
        self.say("checker: " + (", ".join(f"{k} {len(v)}" for k, v in blocking.items()) + " blocking issue(s) remain" if blocking else "no blocking issues"))

        deck = None
        if not self.args.skip_export:
            self.deck_review(all_pages)
            if not self.args.no_deck_repair:
                self.deck_repair(pages)
                blocking = self.checker()
            outstanding = dict(blocking)  # deck-level (_project) items block the exporter too, so they ship through the override and are listed
            if outstanding and self.args.strict_export:
                self.say("export skipped (--strict-export): the final checker still reports blocking issues on " + ", ".join(outstanding))
            else:  # the repair budget is spent: the deck ships, with what is still open written beside it
                deck = self.export(outstanding or None)
            self.outstanding = outstanding
        self.lint_open = self.final_lint(pages)
        text = self.summary(pages, started, deck)
        print("\n" + text)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project", help="project directory with design_spec.md and spec_lock.md")
    parser.add_argument("--session", required=True, help="name of this deck run; page sessions are <session>.<stem>")
    parser.add_argument("--authors", help="JSON mapping tier -> {model, effort, api_base, key_var}; merged over the defaults")
    parser.add_argument("--reviewers", help="JSON mapping tier -> {model, effort, api_base, key_var, provider} for the independent reviewer; merged over the defaults")
    parser.add_argument("--premium", action="store_true", help="frontier pages by Claude Opus 5.5 @ medium instead of Sol: best-looking hard pages, about 3.5x the cost, no faster")
    parser.add_argument("--max-parallel", type=int, default=16, help="pages authored at once (16 since 23 Sep 2026: a 10-12 page deck no longer queues pages behind the first 8)")
    parser.add_argument("--max-turns", type=int, default=60, help="model-call ceiling per page session")
    parser.add_argument("--pages", nargs="*", help="only these page numbers (the anchor is still authored first when absent from disk)")
    parser.add_argument("--no-anchor", action="store_true", help="no chrome anchor: every page starts at once")
    parser.add_argument("--anchor-own-tier", action="store_true", help="author the anchor with its own tier instead of the frontier author")
    parser.add_argument("--no-escalate", action="store_true")
    parser.add_argument("--repair-rounds", type=int, default=2, help="checker repair rounds; when spent, the deck is exported anyway with the open items listed beside it")
    parser.add_argument("--exemplar", help="project whose design_spec.md and spec_lock.md show the planner the FORMAT (default: the PGA case)")
    parser.add_argument("--planner-effort", default="high", help="reasoning effort of the planner (the judgement-heavy stage)")
    parser.add_argument("--no-template", action="store_true", help="skip the template stage: chrome comes from an anchor page")
    parser.add_argument("--base-template", help="our official .pptx/.potx, or a template workspace from the Create Template route: the template stage reproduces its layouts instead of designing its own, and its theme is the house style")
    parser.add_argument("--brief", choices=("proposal", "document"), default="proposal",
                        help="what the first stage works out: a proposal's solution (default), or the content of a deck that documents, explains or trains (it reads the repository to verify claims)")
    parser.add_argument("--no-deck-repair", action="store_true", help="report the deck review without handing its findings back to the pages")
    parser.add_argument("--revise", action="store_true", help="revise from the user's comments in the live preview: each annotated page goes back to its author, then the deck is re-exported")
    parser.add_argument("--dry-run", action="store_true", help="with --revise: show the comments found and what would be sent, call no model")
    parser.add_argument("--floating-text", action="store_true", help="keep the exporter's floating text boxes: skip the pass that moves text inside its shapes")
    parser.add_argument("--strict-export", action="store_true", help="refuse to export while the final checker reports blocking issues")
    parser.add_argument("--skip-export", action="store_true")
    args = parser.parse_args()
    return Runner(args).revise() if args.revise else Runner(args).run()


if __name__ == "__main__":
    sys.exit(main())
