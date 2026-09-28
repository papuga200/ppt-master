"""Where the time and the money of one deck run went - per step and per model.

    python hosts/responses_api/run_report.py <sessions dir> <session name> <project> [-o report.md]

Reads every host session of the run (`<session>.<stage or page>`), the project's review journal (the reviewer's calls) and the runner's
log (wall-clock of the steps, which overlap - pages are authored in parallel, so step times do not add up to the run's wall time).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import report  # noqa: E402

REVIEWER_PRICES = {"gpt-6-sol": (2.0e-6, 10.0e-6), "x-ai/grok-4.7": (1.6e-6, 4.8e-6), "x-ai/grok-4.6": (2.0e-6, 6.0e-6), "gemini-3.8-flash": (0.75e-6, 3.75e-6), "gpt-5.6-luna": (0.2e-6, 1.2e-6)}
STEP_ORDER = ["solution", "planner", "template", "page authoring", "checker and parity repairs", "page reviews", "deck review"]


def clock(text: str) -> int:
    h, m, s = (int(v) for v in text.split(":"))
    return h * 3600 + m * 60 + s


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sessions")
    parser.add_argument("session")
    parser.add_argument("project")
    parser.add_argument("-o", "--output")
    args = parser.parse_args()
    sessions, project = Path(args.sessions), Path(args.project)
    rows = []
    for folder in sorted(p for p in sessions.glob(f"{args.session}.*") if p.is_dir() and not p.name.endswith(".deck")):
        try:
            r = report.analyse(folder)
        except SystemExit:
            continue
        name = folder.name[len(args.session) + 1:]
        step = name if name in ("solution", "planner", "template") else "page authoring"
        rows.append({"step": step, "what": name, "model": f"{r['model']} @ {r['effort']}", "calls": r["calls"], "wall_s": r.get("wall_s") or 0, "api_s": (r.get("api_s_per_call") or 0) * r["calls"],
                     "in": r["input_tokens"], "cached": r["cached_tokens"], "out": r["output_tokens"], "cost": r.get("cost_usd") or 0.0})
    journal = json.loads((project / "quality-run.json").read_text(encoding="utf-8")) if (project / "quality-run.json").is_file() else {"pages": {}}
    for stem, entry in (journal.get("pages") or {}).items():
        for review in entry.get("review_log") or []:
            usage = review.get("usage") or {}
            price = REVIEWER_PRICES.get(review.get("model"), (0, 0))
            cost = usage.get("cost") if usage.get("cost") is not None else (usage.get("input_tokens") or 0) * price[0] + (usage.get("output_tokens") or 0) * price[1]
            rows.append({"step": "page reviews", "what": f"{stem} rev{review.get('rev')} -> {review.get('verdict')}", "model": review.get("model"), "calls": 1, "wall_s": review.get("seconds") or 0,
                         "api_s": review.get("seconds") or 0, "in": usage.get("input_tokens") or 0, "cached": 0, "out": usage.get("output_tokens") or 0, "cost": cost or 0.0})
    for review in journal.get("deck_review") or []:
        if isinstance(review, dict) and review.get("usage"):
            usage = review["usage"]
            rows.append({"step": "deck review", "what": "whole deck on one sheet", "model": review.get("model"), "calls": 1, "wall_s": review.get("seconds") or 0, "api_s": review.get("seconds") or 0,
                         "in": usage.get("input_tokens") or 0, "cached": 0, "out": usage.get("output_tokens") or 0, "cost": usage.get("cost") or 0.0})
    log = sessions / f"{args.session}.runner.log"
    stamps = re.findall(r"^\[(\d\d:\d\d:\d\d)\] (.+)$", log.read_text(encoding="utf-8", errors="replace"), re.M) if log.is_file() else []
    timeline = []
    if stamps:
        start = clock(stamps[0][0])
        marks = [("solution", r"solution: .* started", r"solution: finished"), ("planner", r"planner: .* started", r"planner: finished"), ("template", r"template: .* started", r"template: finished"),
                 ("pages in parallel, each with its own checker repairs and escalation", r"P\d+ .* author .* started", r"^(deck checker repair round|checker: )"),
                 ("deck-wide checker and its repairs", r"^(deck checker repair round|checker: )", r"deck review"),
                 ("deck review and deck repair", r"deck review", r"(speaker notes|exported|text in shapes)"), ("export, text pass, PowerPoint render, final lint", r"(speaker notes|text in shapes)", r"final lint")]
        for label, begin, finish in marks:
            a = next((clock(t) for t, line in stamps if re.search(begin, line)), None)
            b = next((clock(t) for t, line in stamps if re.search(finish, line) and a is not None and clock(t) >= a), None)
            if a is not None and b is not None:
                timeline.append((label, (a - start) % 86400, (b - a) % 86400))
        total_wall = (clock(stamps[-1][0]) - start) % 86400
    else:
        total_wall = 0

    def table(group_key: str) -> list[str]:
        groups: dict[str, dict] = {}
        for r in rows:
            g = groups.setdefault(r[group_key], {"calls": 0, "wall_s": 0.0, "api_s": 0.0, "in": 0, "cached": 0, "out": 0, "cost": 0.0, "n": 0})
            for k in ("calls", "wall_s", "api_s", "in", "cached", "out", "cost"):
                g[k] += r[k]
            g["n"] += 1
        order = sorted(groups, key=lambda k: (STEP_ORDER.index(k) if k in STEP_ORDER else 99, k))
        out = [f"| {group_key} | sessions | model calls | time in model calls | summed session time | input tokens | of which cached | output tokens | cost USD |", "|---|---|---|---|---|---|---|---|---|"]
        for k in order:
            g = groups[k]
            out.append(f"| {k} | {g['n']} | {g['calls']} | {g['api_s'] / 60:.1f} min | {g['wall_s'] / 60:.1f} min | {g['in'] / 1e3:.0f}k | {g['cached'] / max(g['in'], 1):.0%} | {g['out'] / 1e3:.0f}k | {g['cost']:.2f} |")
        total = {k: sum(g[k] for g in groups.values()) for k in ("calls", "api_s", "wall_s", "in", "out", "cost")}
        out.append(f"| **total** | {len(rows)} | {total['calls']} | {total['api_s'] / 60:.1f} min | {total['wall_s'] / 60:.1f} min | {total['in'] / 1e3:.0f}k | | {total['out'] / 1e3:.0f}k | **{total['cost']:.2f}** |")
        return out

    lines = [f"# Run report - `{args.session}` - {project.name}", "",
             f"**Wall clock: {total_wall / 60:.1f} min** from the first step to the final lint. **Model cost: USD {sum(r['cost'] for r in rows):.2f}**. "
             "Pages are authored in parallel, so the per-step and per-session times below overlap and do not add up to the wall clock.", "",
             "## Wall clock by step (from the runner's log)", "", "| step | starts at | lasts |", "|---|---|---|",
             *[f"| {label} | +{begin / 60:.1f} min | {length / 60:.1f} min |" for label, begin, length in timeline], "",
             "## By step", "", *table("step"), "", "## By model", "", *table("model"), "",
             "## Every session and reviewer call", "", "| step | what | model | calls | session time | input | output | cost USD |", "|---|---|---|---|---|---|---|---|",
             *[f"| {r['step']} | {r['what']} | {r['model']} | {r['calls']} | {r['wall_s'] / 60:.1f} min | {r['in'] / 1e3:.0f}k | {r['out'] / 1e3:.1f}k | {r['cost']:.3f} |"
               for r in sorted(rows, key=lambda r: (STEP_ORDER.index(r['step']) if r['step'] in STEP_ORDER else 99, r['what']))], "",
             "Notes: repairs and escalations run inside the page's own session, so their cost sits in that page's row. Sol is priced at list (USD 2 / 0.2 cached / 10 per million tokens); "
             "DeepSeek and Grok costs are what OpenRouter reported. A deck-review row appears only when the run recorded its usage."]
    text = "\n".join(lines) + "\n"
    Path(args.output).write_text(text, encoding="utf-8") if args.output else None
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
