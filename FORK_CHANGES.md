# Fork changes

This is a fork of [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master); upstream's licence and notices are unchanged. Branch `consulting-quality` starts at upstream commit `47ef2b5679305c014672433728d39d99df4ee2ad` (tag `baseline-47ef2b5`). This file is the complete list of local changes, so an upstream update can be reviewed deliberately.

## Purpose

Consulting-quality slide design and a coherent deck, by shortening the path between a visual decision and its visible consequence. PPT Master's Strategist, Design Spec, lock, SVG contract, checker and exporter stay the foundation. There is no intermediate slide representation between the model and the SVG, and no fact-verification subsystem: faithfulness to the supplied material is an instruction to the model.

## Added

| Path | What it is |
|---|---|
| `skills/ppt-master/workflows/profiles/consulting-quality.md` | The profile: Default Generate plus a per-page render-and-inspect authoring loop, matched reference slides, a deck review, and inspection of the exported PPTX. Explicit intent only. |
| `skills/ppt-master/references/consulting-review.md` | The review language: the four-question page note, symptoms of generated-looking design, what strong architecture / timeline / summary / comparison pages do, the deck review. A way of looking, not a rule set. |
| `skills/ppt-master/scripts/page_review.py` | `render` (numbered backups, revision count, `IMAGE:` line, optional crop), `restore`, `note`, `contact-sheet`, `status`; keeps the small journal `quality-run.json`. |
| `skills/ppt-master/scripts/reference_library.py` | Matches a page's communication problem against a folder-plus-index library of real slides and prints the image path with a few observations. The library lives outside the repository (`PPT_MASTER_REFERENCE_LIBRARY`). Rejected slides return only as labelled counterexamples. |
| `skills/ppt-master/scripts/pptx_render.py` | Renders the exported PPTX itself (PowerPoint through COM, else LibreOffice + PyMuPDF) to per-slide PNGs and a contact sheet; says so plainly when no renderer exists. |
| `hosts/responses_api/host.py` | A thin tool-execution host for a model behind the OpenAI Responses API: file tools, `edit_file` for local SVG revisions, the skill's scripts, and real image delivery for every `IMAGE:` line. No workflow logic lives here. Production does not depend on any vendor's coding agent. |
| `skills/ppt-master/scripts/tests/test_consulting_quality_tools.py` | Tests for the journal and the matcher. |

## Changed upstream files

| Path | Change |
|---|---|
| `skills/ppt-master/scripts/visual_review.py` | `PPT_MASTER_BROWSER_CHANNEL` lets an installed browser (`msedge`, `chrome`) stand in for the bundled Chromium download. |
| `skills/ppt-master/workflows/routing.md`, `workflows/generate-pptx.md`, `SKILL.md`, `AGENTS.md` | One line or row each that routes to the profile and places its three additions in the Default sequence. The checker cadence and the opt-in `visual-review` stage are unchanged. |
| `.gitignore` | `.host-sessions/`. |

`scripts/prompt_audit_manifest.json` has not been updated for the two new prompt documents.

## Deliberately not brought over from Deck Builder

The semantic slide document, layout solver, resolved geometry, repair engine, evidence ledger, claim-level citation checks, fact-regression gates, requirement-coverage scoring, the rule registry, and the multi-role model configuration.
