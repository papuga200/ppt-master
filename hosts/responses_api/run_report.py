"""Where the time and the money of one deck run went - per step and per model.

    python hosts/responses_api/run_report.py <sessions dir> <session name> <project> [-o report.md]

Prefers the runner's structured telemetry `<sessions>/<session>.runner.jsonl` (deck_runner.py writes it): stage start/end with UTC
timestamps, one `model_session` event per author/planner/template/repair invocation (host.py or cli_host.py) with the usage that
invocation added, and one `model_call` event per single-shot call the runner makes itself (blind read, deck review). Page reviews come
from the project's review journal. Every cost carries its `cost_source`: `billed-api` (a keyed endpoint), `subscription-notional-list-price`
(a subscription CLI: nothing is billed per call, the figure is the list-price equivalent) or `unknown`; the two kinds are never summed
into one figure.

Without runner.jsonl (runs before it existed) it falls back to the session folders and the free-text runner log, as before.
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
STEP_ORDER = ["solution", "planner", "planner_repair", "newcomer_read", "template", "page authoring", "page", "escalation", "repair",
              "checker and parity repairs", "parity_repair", "page reviews", "page_review", "deck review", "deck_review", "deck_repair", "revise"]
STAGE_ORDER = ["base_template", "source_assets", "solution", "planner", "plan_gate", "template", "anchor", "pages", "deck_checker", "deck_review",
               "deck_repair", "export", "final_lint"]


def _money(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def clock(text: str) -> int:
    h, m, s = (int(v) for v in text.split(":"))
    return h * 3600 + m * 60 + s


def _row(step, what, model, calls, wall_s, api_s, usage: dict, cost, source) -> dict:
    return {"step": step, "what": what, "model": model, "calls": calls or 0, "wall_s": wall_s or 0, "api_s": api_s or 0,
            "in": usage.get("input_tokens") or 0, "cached": usage.get("cached") or 0, "out": usage.get("output_tokens") or 0,
            "reasoning": usage.get("reasoning") or 0, "cost": cost, "source": source or report.COST_UNKNOWN}


def review_rows(journal: dict, include_deck: bool) -> list[dict]:
    rows = []
    for stem, entry in (journal.get("pages") or {}).items():
        for review in entry.get("review_log") or []:
            usage = review.get("usage") or {}
            source = usage.get("cost_source")
            cost = usage.get("cost")
            if cost is None and source != report.COST_NOTIONAL:
                price = REVIEWER_PRICES.get(review.get("model"))
                if price:
                    cost = (usage.get("input_tokens") or 0) * price[0] + (usage.get("output_tokens") or 0) * price[1]
                    source = source or report.COST_BILLED
            if cost is not None and not source:
                source = report.COST_BILLED  # a review from before cost_source existed: always a keyed endpoint
            rows.append(_row("page reviews", f"{stem} rev{review.get('rev')} -> {review.get('verdict')}", review.get("model"), 1, review.get("seconds"),
                             review.get("seconds"), {"input_tokens": usage.get("input_tokens"), "cached": usage.get("cached_tokens"),
                                                     "output_tokens": usage.get("output_tokens"), "reasoning": usage.get("reasoning_tokens")}, cost, source))
    if include_deck:
        for review in journal.get("deck_review") or []:
            if isinstance(review, dict) and review.get("usage"):
                usage = review["usage"]
                rows.append(_row("deck review", "whole deck on one sheet", review.get("model"), 1, review.get("seconds"), review.get("seconds"),
                                 {"input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}, usage.get("cost"),
                                 usage.get("cost_source") or (report.COST_BILLED if usage.get("cost") is not None else report.COST_UNKNOWN)))
    return rows


def telemetry_rows(events: list[dict], sessions: Path) -> list[dict]:
    rows = []
    for e in events:
        if e.get("event") == "model_session":
            what = f"{e.get('page') or e.get('stage')} ({e.get('mode')}, {e.get('tier')})"
            api_s = 0.0
            try:  # time inside model calls, when the session's transcript measured it
                turns = [json.loads(line) for line in (sessions / e["session"] / "transcript.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
                t0, t1 = e["t"] - (e.get("wall_s") or 0), e["t"]
                api_s = sum(t.get("api_s") or 0 for t in turns if t.get("event") == "turn" and t0 - 1 <= (t.get("at") or 0) <= t1 + 1)
            except (OSError, KeyError, ValueError):
                pass
            rows.append(_row(e.get("stage"), what, f"{e.get('model')} @ {e.get('effort')} [{e.get('backend')}]", (e.get("usage") or {}).get("calls"),
                             e.get("wall_s"), api_s, e.get("usage") or {}, e.get("cost_usd"), e.get("cost_source")))
        elif e.get("event") == "model_call":
            what = (f"{e.get('page')} rev{e.get('rev')} -> {e.get('verdict')}" if e.get("stage") == "page_review" else f"{e.get('stage')} ({e.get('outcome')})")
            rows.append(_row(e.get("stage"), what, f"{e.get('model')} @ {e.get('effort')} [{e.get('backend')}]",
                             (e.get("usage") or {}).get("calls"), e.get("wall_s"), e.get("wall_s"), e.get("usage") or {}, e.get("cost_usd"), e.get("cost_source")))
    return rows


def stage_timeline(events: list[dict]) -> tuple[list[tuple[str, float, float, str]], float]:
    starts = [e for e in events if e.get("event") in ("stage_start", "run_start")]
    if not starts:
        return [], 0.0
    t0 = min(e["t"] for e in starts)
    spans: dict[str, list[float]] = {}
    outcomes: dict[str, str] = {}
    for e in events:
        if e.get("event") == "stage_end" and e.get("stage") not in ("page_job",):
            begin = e["t"] - (e.get("wall_s") or 0)
            span = spans.setdefault(e["stage"], [begin, e["t"]])
            span[0], span[1] = min(span[0], begin), max(span[1], e["t"])
            if e.get("outcome"):
                outcomes[e["stage"]] = str(e["outcome"])
    ends = [e["t"] for e in events if "t" in e]
    order = sorted(spans, key=lambda k: (STAGE_ORDER.index(k) if k in STAGE_ORDER else 99, spans[k][0]))
    return [(k, spans[k][0] - t0, spans[k][1] - spans[k][0], outcomes.get(k, "")) for k in order], (max(ends) - t0 if ends else 0.0)


def table(rows: list[dict], group_key: str) -> list[str]:
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r[group_key], {"calls": 0, "wall_s": 0.0, "api_s": 0.0, "in": 0, "cached": 0, "out": 0, "reasoning": 0, "n": 0,
                                             "billed": 0.0, "notional": 0.0, "unknown": 0})
        for k in ("calls", "wall_s", "api_s", "in", "cached", "out", "reasoning"):
            g[k] += r[k]
        g["n"] += 1
        if r["cost"] is None or r["source"] == report.COST_UNKNOWN:
            g["unknown"] += 1
        elif r["source"] == report.COST_NOTIONAL:
            g["notional"] += r["cost"]
        else:
            g["billed"] += r["cost"]
    order = sorted(groups, key=lambda k: (STEP_ORDER.index(k) if k in STEP_ORDER else 99, str(k)))
    out = [f"| {group_key} | sessions/calls | model calls | time in model calls | summed session time | input tokens | of which cached | output tokens | "
           "of which reasoning | billed USD | notional USD (subscription) | cost unknown |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in order:
        g = groups[k]
        out.append(f"| {k} | {g['n']} | {g['calls']} | {g['api_s'] / 60:.1f} min | {g['wall_s'] / 60:.1f} min | {g['in'] / 1e3:.0f}k | {g['cached'] / max(g['in'], 1):.0%} | "
                   f"{g['out'] / 1e3:.1f}k | {g['reasoning'] / 1e3:.1f}k | {g['billed']:.2f} | {g['notional']:.2f} | {g['unknown'] or ''} |")
    total = {k: sum(g[k] for g in groups.values()) for k in ("calls", "api_s", "wall_s", "in", "out", "reasoning", "billed", "notional", "unknown")}
    out.append(f"| **total** | {len(rows)} | {total['calls']} | {total['api_s'] / 60:.1f} min | {total['wall_s'] / 60:.1f} min | {total['in'] / 1e3:.0f}k | | "
               f"{total['out'] / 1e3:.1f}k | {total['reasoning'] / 1e3:.1f}k | **{total['billed']:.2f}** | **{total['notional']:.2f}** | {total['unknown'] or ''} |")
    return out


def legacy(sessions: Path, session: str, journal: dict) -> tuple[list[dict], list[tuple[str, float, float, str]], float]:
    rows = []
    for folder in sorted(p for p in sessions.glob(f"{session}.*") if p.is_dir() and not p.name.endswith(".deck")):
        try:
            r = report.analyse(folder)
        except SystemExit:
            continue
        name = folder.name[len(session) + 1:]
        step = name if name in ("solution", "planner", "template") else "page authoring"
        rows.append(_row(step, name, f"{r['model']} @ {r['effort']}", r["calls"], r.get("wall_s"), (r.get("api_s_per_call") or 0) * r["calls"],
                         {"input_tokens": r["input_tokens"], "cached": r["cached_tokens"], "output_tokens": r["output_tokens"], "reasoning": r["reasoning_tokens"]},
                         r.get("cost_usd"), r.get("cost_source")))
    rows += review_rows(journal, include_deck=True)
    log = sessions / f"{session}.runner.log"
    stamps = re.findall(r"^\[(\d\d:\d\d:\d\d)\] (.+)$", log.read_text(encoding="utf-8", errors="replace"), re.M) if log.is_file() else []
    timeline = []
    total_wall = 0.0
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
                timeline.append((label, (a - start) % 86400, (b - a) % 86400, ""))
        total_wall = (clock(stamps[-1][0]) - start) % 86400
    return rows, timeline, total_wall


def build(sessions: Path, session: str, project: Path) -> str:
    journal = json.loads((project / "quality-run.json").read_text(encoding="utf-8")) if (project / "quality-run.json").is_file() else {"pages": {}}
    telemetry_path = sessions / f"{session}.runner.jsonl"
    events = [json.loads(line) for line in telemetry_path.read_text(encoding="utf-8").splitlines() if line.strip()] if telemetry_path.is_file() else []
    if events:
        source = f"structured telemetry `{telemetry_path.name}`"
        # page reviews: the reviews' own telemetry lines when page_review.py wrote them (PPT_MASTER_TELEMETRY_FILE), else the journal's review_log
        reviewed = any(e.get("event") == "model_call" and e.get("stage") == "page_review" for e in events)
        rows = telemetry_rows(events, sessions) + ([] if reviewed else review_rows(journal, include_deck=False))
        timeline, total_wall = stage_timeline(events)
        preflight = [e for e in events if e.get("event") == "preflight"]
        warnings = next((e.get("warnings") for e in reversed(events) if e.get("event") == "run_end"), None) or []
    else:
        source = "session folders and the free-text runner log (no runner.jsonl for this run)"
        rows, timeline, total_wall = legacy(sessions, session, journal)
        preflight, warnings = [], []
    billed = sum(r["cost"] for r in rows if r["cost"] is not None and r["source"] not in (report.COST_NOTIONAL, report.COST_UNKNOWN))
    notional = sum(r["cost"] for r in rows if r["cost"] is not None and r["source"] == report.COST_NOTIONAL)
    unknown = sum(1 for r in rows if r["cost"] is None or r["source"] == report.COST_UNKNOWN)
    lines = [f"# Run report - `{session}` - {project.name}", "", f"Source: {source}.", "",
             f"**Wall clock: {total_wall / 60:.1f} min**. **Billed API cost: USD {billed:.2f}.** **Subscription use at list-price equivalent: USD {notional:.2f}** "
             f"(notional - a subscription call bills nothing by itself){f'; {unknown} call group(s) with no known price' if unknown else ''}. "
             "Pages are authored in parallel, so the per-step and per-session times below overlap and do not add up to the wall clock.", ""]
    if preflight:
        lines += ["Subscription pre-flight: " + "; ".join(f"{e.get('backend')} {e.get('outcome')} {json.dumps(e.get('status') or e.get('error'))}" for e in preflight), ""]
    if warnings:
        lines += ["**Warnings:** " + "; ".join(warnings), ""]
    lines += ["## Wall clock by stage", "", "| stage | starts at | lasts | outcome |", "|---|---|---|---|",
              *[f"| {label} | +{begin / 60:.1f} min | {length / 60:.1f} min | {outcome} |" for label, begin, length, outcome in timeline], "",
              "## By step", "", *table(rows, "step"), "", "## By model", "", *table(rows, "model"), "",
              "## Every session and model call", "", "| step | what | model | calls | session time | input | reasoning | output | cost USD | cost source |",
              "|---|---|---|---|---|---|---|---|---|---|",
              *[f"| {r['step']} | {r['what']} | {r['model']} | {r['calls']} | {r['wall_s'] / 60:.1f} min | {r['in'] / 1e3:.0f}k | {r['reasoning'] / 1e3:.1f}k | {r['out'] / 1e3:.1f}k | "
                f"{_money(r['cost'])} | {r['source']} |"
                for r in sorted(rows, key=lambda r: (STEP_ORDER.index(r['step']) if r['step'] in STEP_ORDER else 99, str(r['what'])))], "",
              "Notes: repairs and escalations run inside the page's own session; with runner.jsonl each invocation is its own row (step = repair, "
              "escalation, deck_repair, ...). Keyed endpoints are priced at list (report.PRICES / REVIEWER_PRICES) unless the endpoint reported its cost. "
              "Claude CLI sessions carry Claude Code's own list-price estimate (`total_cost_usd`, costBasis list); Codex CLI sessions report tokens only and "
              "are priced at report.PRICES - both are notional."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sessions")
    parser.add_argument("session")
    parser.add_argument("project")
    parser.add_argument("-o", "--output")
    args = parser.parse_args()
    text = build(Path(args.sessions), args.session, Path(args.project))
    Path(args.output).write_text(text, encoding="utf-8") if args.output else None
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
