# exp_svg/timeline: `build_timeline` (experimental, v0.2.0)

JSON in, JSON out. Lays out a one-slide Gantt/timeline and returns an SVG group with stable content IDs, scene data
and a receipt, or an explicit `capacity_failure`. Isolated experiment code (SVG helpers experiment, 2026-09-30); not
wired into any workflow.

```
python3 scripts/exp_svg/timeline/build_timeline.py --in request.json --out result.json [--svg preview.svg]
python3 scripts/exp_svg/timeline/build_timeline.py --in request.json --out result.json --into <project>/svg_output/<page>.svg
python3 scripts/exp_svg/timeline/build_timeline.py ... --engine timeline_layout      # round-1 behaviour (v1 requests only)
```

Exit codes: `0` ok, `3` partial, `4` capacity_failure, `2` error. `result.json` is written in every case.

| File | Role |
|---|---|
| `build_timeline.py` | CLI, receipt, `--into`, engine selection; the round-1 path over the fork's unchanged `timeline_layout.py` |
| `dense_build.py` | request v1/v2 validation and normalisation to day offsets; runs the dense engine at the asked label size, then at the floor only if needed; status and capacity classification |
| `dense_layout.py` | the dense layout engine (default since v0.2.0) |
| `timeline_fonts.py` | label widths from the real font file (FreeType through Pillow, unhinted) |

## Dense engine (default)

Built in this folder from the ideas of `timeline_layout.py`; production code is untouched. It never drops, merges,
abbreviates or shrinks below the label floor (13.33 px unless a request asks a higher floor). Layout choices it makes:

- bar labels inside (1-3 lines, 8 px side padding, `bar_pad_y` top/bottom), beside on the same row (right or left, 1-3
  lines), or above the bar; a dependency's source keeps its right end clear, its target its left end;
- `style.bar_mode: "thin"`: thin bars (`bar_h_thin`, default 10 px) with every label beside or above them;
- lanes packed by searching item orders for the least lane height; rows then read by start date;
- lane events (`placement: "lane"`, e.g. steering updates) packed in their lane with the name beside the marker;
- gate and window names stacked above the ruler, milestone names below the lanes, each wrapped to 1-3 lines and placed
  so that no gate line, window leader or milestone leader passes through any name (checked while placing; greedy
  orders, deterministic shuffles, then a bounded exhaustive search); below the first level a milestone name hangs
  from a leader into its centre;
- gate lines are drawn as segments that stop at every label and lane-event marker they would cross;
- labels in the lanes end at the plan horizon when a dashed beyond-horizon span exists;
- multi-line labels at 1.3 x leading (the fork lint's floor is 1.28 x);
- a legend (symbols only) under the chart or in the rail column beside the milestone strip, whichever needs less height;
- a density search (row gap, lane padding, rail width), most generous first; labels drop from the asked size to the
  floor only when nothing fits at the asked size.

When nothing fits, the densest draft is still returned, with `status: capacity_failure` and `capacity.binding`
naming the constraint: `height` with `needs_px`, `available_px`, `over_by_px` and a per-part breakdown (lanes, rows,
header names, milestone strip, ruler, legend), or `bounds` with the element that leaves the region.

## Request (`exp_svg.build_timeline.request.v2`; v1 requests are accepted)

```json
{
  "schema": "exp_svg.build_timeline.request.v2",
  "calendar": {"start": "2026-07-27", "horizon_weeks": 26, "prefix": "W"},
  "ruler": {"edge_labels": ["27 Jul 2026", "22 Jan 2027"]},
  "lanes": [{"id": "report", "name": "Reporting and dashboards"}, {"id": "pmo", "name": "Project management and governance"}],
  "tasks": [{"id": "b_apm", "name": "Agency Performance Model", "lane": "report", "weeks": [8, 14]},
            {"id": "b_uat", "name": "User acceptance testing (UAT) and tuning", "lane": "report", "weeks": [17, 21]},
            {"id": "b_ws", "name": "26 weekly delivery workshops", "lane": "pmo", "start": "2026-07-27", "end": "2027-01-22"}],
  "milestones": [{"id": "s05", "name": "Monthly steering update", "week": 5, "placement": "lane", "lane": "pmo"},
                 {"id": "D5", "name": "D5: go-live and stopping the old packs", "week": 21, "kind": "gate"},
                 {"id": "M5", "name": "Go-live 4–8 January 2027", "week": 24, "payment": true, "focal": true}],
  "windows": [{"id": "holiday", "name": "Holiday window: no releases, skeleton cover", "weeks": [22, 23]},
              {"id": "float", "name": "Float (unplanned)", "weeks": [27, 27], "style": "dashed"}],
  "dependencies": [{"id": "DEP-02", "from": "b_apm", "to": "b_uat"}, {"id": "DEP-05", "from": "D5", "to": "M5"}],
  "legend": [{"symbol": "payment", "text": "Payment milestone"}, {"symbol": "gate", "text": "Decision point"}],
  "style": {"font_family": "Segoe UI", "label_px": 14, "bar_pad_x": 8, "bar_pad_y": 4, "bar_mode": "labelled",
            "colors": {"bar": "#0F5C3A", "gate": "#0F5C3A", "focal": "#F2A31B"}},
  "floors": {"label_px": 13.33, "body_px": 16},
  "bounds": {"x": 54, "y": 140, "w": 1172, "h": 476}
}
```

| Field | Meaning |
|---|---|
| `calendar` | `start` (Monday of week 1) and either `end` (last day shown) or `horizon_weeks`; `milestone_anchor` `end_of_day` (default) or `start_of_day` for dated points |
| `ruler.edge_labels` | optional texts shown at the start and at the end of the horizon (e.g. the two calendar dates) |
| `tasks[]` | `id`, `name`, `lane`, and `weeks: [a, b]` (start of week a to end of week b) or `start`/`end` (inclusive dates); optional `fill`, `text`; `beyond_horizon: true` allows a task past the horizon |
| `milestones[]` | `id`, `name`, `week` (end of week n; `at`: start/middle/end) or `date`; `kind`: `milestone` or `gate`; `placement`: `strip` (default, under the lanes) or `lane` (a lane event, needs `lane`); `payment` (outer ring), `focal` (accent fill, bold name); `emphasis` is read as `focal` |
| `windows[]` | `id`, `name`, `weeks` or dates; `style`: `shaded` (default) or `dashed` (e.g. float beyond the horizon, which extends the scale) |
| `dependencies[]` | `id`, `from`, `to`: any task or milestone/gate id |
| `legend[]` | `symbol` (`gate`, `milestone`, `payment`, `focal`, `event`, `window`, `float`, `dependency`) and `text`: symbols only |
| `style` | font stack, `label_px`/`lane_px`/`tick_px` (raised to the floor if lower), `bar_pad_x`, `bar_pad_y`, `bar_mode` (`labelled` or `thin`), `bar_h_thin`, `lane_label_w` (else searched), `name_max_lines` (3), colour tokens (`bar`, `bar_text`, `text`, `rail_text`, `muted`, `band`, `gate`, `milestone`, `focal`, `event`, `dependency`, `window`, `float`, `axis`, `leader`) |
| `floors.label_px` | the label floor, never below 13.33 |
| `bounds` | the body region in canvas px (1280 x 720; 1 px = 0.75 pt) |
| `options.engine` | `dense` (default) or `timeline_layout` |

## Result (`exp_svg.build_timeline.result.v1`)

- `status`: `ok` | `partial` (drawn, with named unsatisfied constraints) | `capacity_failure` (best draft kept,
  `capacity.binding` names the constraint) | `error` (`errors[]`).
- `svg.fragment`: one `<g id="timeline" data-layout="timeline_layout" data-engine="exp_svg.dense_layout 0.2.0"
  data-output-sha=...>`. The digest is the one `page_lint.py` recomputes, so the lint treats the group as helper-written
  and flags later hand edits (TIMELINE_HAND_EDITED). Elements carry `data-content-id` (`lane:`, `task:`, `milestone:`,
  `window:`, `dependency:`, `tick:`, `legend:`) and `data-role`. With `--into`, the request is kept beside the page.
- `scene`: scale (`x_of_calendar_start`, `px_per_day`, conventions), density and height breakdown, lanes, tasks (x0, x1,
  y, h, row, label placement and rectangle), markers (x, y, label rectangle; gates with their line segments), windows,
  dependency polylines, the engine's own checks.
- `receipt`: `tool`, `tool_version` (0.2.0), `engine`, `engine_version`, `engine_sha256` (timeline_layout.py),
  `adapter_sha256`, `adapter_files_sha256` (every .py here), `input_sha256`, `output_sha256` (fragment + scene),
  `elapsed_ms`, `status`.

A tool status is not acceptance: the qualification's independent checker (browser geometry against the request) is
the evidence. Measured limits: the frozen T-DEV brief does not fit its body region at the floor (needs at least
621 px of 476); dense T-DEV layouts take 3.5-4.6 s per call.
