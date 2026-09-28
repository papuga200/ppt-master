# Consulting Typesetting

How text is set on a consulting page so that it reads easily and edits like a hand-built PowerPoint. A packed page is dense in *information*, never in *leading*: when the words do not fit, the words, the size step or the structure change - the spacing does not.

Measured on our own decks before these rules (pga-par3): body text at a median 1.25 x line spacing with paragraphs as tight as 1.08 x, titles at 1.04 x, 27 bullets drawn as loose squares against 2 typed. Readers called it squished; editors had to realign every list by hand.

## 1. Line spacing (`dy` of a positioned `<tspan>` ÷ `font-size`)

| Text | Line spacing |
|---|---|
| Slide title (24 px and up) | 1.15 - 1.2 |
| Heading inside the page (15 - 23 px) | 1.2 - 1.3 |
| Body and table text (11 - 14 px) | 1.4 - 1.5, never under 1.3 |
| Notes and sources (under 11 px) | about 1.4 |
| A big number with its caption | the caption's first baseline sits one caption line below the number's baseline |

## 2. Paragraph spacing: inside a group is always tighter than between groups

| Between | Extra space on top of one line of the text that follows |
|---|---|
| A heading and its paragraph | 0.3 - 0.5 of the paragraph's font size (the heading belongs to what follows it) |
| Two paragraphs of one block | 0.5 - 0.7 of the font size |
| Two list items | 0.35 - 0.5 of the font size |
| Two blocks (a new heading) | at least double the paragraph gap, and visibly more than any gap inside either block |

Equal things get equal gaps: the same gap between every pair of list items, every pair of rows, every pair of cards.

## 3. Padding and measure

- Text keeps at least 10 - 12 px from the edge of the shape it sits in (8 px top and bottom in a compact chip or bar).
- A one-line table row is at least 2.2 x its font size tall; a cell's text keeps 8 px left/right and 6 px top/bottom.
- A line of body text runs 45 - 95 characters. Longer: narrow the measure or set two columns. Shorter than 30 on most lines: the column is too narrow for prose - use labels or a list.

## 4. When it does not fit

In this order: shorten the wording (the record allows shortening, never dropping); take the type one step down, never under the lock's annotation size for body and footnote size for notes; restructure (two columns, a list instead of prose, a table instead of cards). Never close up the leading, never let text leave its shape.

## 5. Lists are native lists

A list is ONE `<text>` per item, stacked on one left edge, each starting with its marker as the first characters - not a drawn square or circle next to a text. The exporter turns a leading marker into a real PowerPoint bullet with a hanging indent and keeps the marker's colour, so the brand's coloured square is simply typed:

```xml
<text x="72" y="300" font-size="12" fill="#1F1F1F"><tspan fill="#B4162E">■</tspan> connectors for Datadog, GitLab, PagerDuty and Jira</text>
<text x="72" y="322" font-size="12" fill="#1F1F1F"><tspan fill="#B4162E">■</tspan> baselines and thresholds per service</text>
```

Markers the exporter recognises: `■ ▪ ● • ◆ ◇ ◦ ‣ ·`. An ordered list types its number the same way (`<tspan fill="#B4162E" font-weight="bold">1.</tspan> text`); after export it becomes PowerPoint's automatic numbering in that colour. A second line of an item is a positioned `<tspan>` inside the item's `<text>`, its `x` at the text after the marker. Numbered badges (a numeral in a circle) stay shapes only where the number is a *label on a figure* (a step in a diagram), not a list.

## 6. Timelines and Gantt charts: every bar carries its own label

A bar without a name is a coloured rectangle: the reader has to count down a list to find out what it is, and the editor who moves a bar no longer knows which task moved. So each bar is labelled where it is - never in a legend, a key, or a "sub-tasks in bar order" line in the lane heading.

- The label goes INSIDE the bar when it fits with 6 px of padding each side (light text on a dark bar, dark on a light one), left-aligned or centred.
- When the bar is too short for its words, the label sits BESIDE it on the same row: starting 6 px after the bar's right end, or ending 6 px before its left end when the right is taken. Fully outside is clean; straddling the bar's edge is the defect (that is what the lint flags) - so never start a long label inside a short bar.
- Shorten before you shrink: `PR mode on pilot services (wk 14-18)` becomes `PR mode, pilot`; the weeks are on the ruler. Bar labels may use the annotation size.
- Give the lanes the height this needs: two bars that would share a row with their labels colliding go on two rows of the lane.
- Everything that happens at a time is written AT that time on the chart: a milestone's name at its marker, a gate's name at its line, a dependency's arrow between the two bars it ties, the pilot window's name on its shaded span. The reader sees each thing exactly where it happens. A legend explains symbols only (what a bar, a triangle, a diamond, an arrow, a shaded span mean); it never carries content - no `Milestones: wk 10 ..., wk 14 ...` line under the chart.

## 7. Tables are native tables

A grid whose rows and columns both carry meaning - including `label | content` rows - is a PowerPoint table, styled to the deck: header band, row fills, first-column weight, sparse rules, cell padding, all expressed per cell in the table's JSON ([`native-data-interface.md`](./native-data-interface.md) §2, schema `ppt-master.semantic-table.v2`). The text lives in the cells. Draw the visible fallback to the same design, because the fallback is what the preview shows and the JSON is what PowerPoint gets: same rows, same words, same fills, same alignment. Row heights follow §3. The exporter refuses a native table whose JSON and fallback disagree, so: every `<text>` inside the table group must equal, as one string, a cell's text in the JSON - a cell's text that runs over several lines ends each line with a space before the next `<tspan>` (`WHERE THE <tspan x="54" dy="17">TIME GOES</tspan>`), or the lines are that cell's `paragraphs` in the same order; a cell with a heading and a paragraph lists both as `paragraphs`; header cells carry `"align": "l"` (they export centred otherwise); then stamp the page (`stamp_native_fallbacks.py <page>.svg --write`). What is *not* a table: a row of KPI cards, a Gantt, a figure with a legend.
