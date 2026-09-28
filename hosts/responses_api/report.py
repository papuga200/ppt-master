#!/usr/bin/env python3
"""Report on host sessions: speed, tokens, cost, tool use and agentic behaviour, side by side.

    python hosts/responses_api/report.py SESSION [SESSION ...] [--sessions-dir DIR] [--md OUT.md]

Reads each session's transcript.jsonl (turn usage, tool calls and results, start/end times) and the
project journal (quality-run.json) the session worked on. Cost is OpenRouter's own per-turn figure when
present, otherwise computed from PRICES (USD per token: prompt, cached prompt, completion). API latency
is estimated as wall time minus the scripts' own reported run time when turns carry no timestamps
(sessions before the host logged `at` and `api_s`), and measured when they do.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import statistics
import sys
from pathlib import Path

PRICES = {  # USD per token; OpenRouter's listing, September 2026
    "gpt-5.6-luna": (0.2e-6, 0.02e-6, 1.2e-6),
    "gpt-5.6-sol": (2.0e-6, 0.2e-6, 10.0e-6),
    "gpt-6-sol": (2.0e-6, 0.2e-6, 10.0e-6),
    "gpt-6-luna": (0.1e-6, 0.01e-6, 0.5e-6),
    "gpt-6-astra": (10.0e-6, 1.0e-6, 50.0e-6),
    "openai/gpt-5.6-luna": (0.2e-6, 0.02e-6, 1.2e-6),
    "openai/gpt-5.6-sol": (2.0e-6, 0.2e-6, 10.0e-6),
    "moonshotai/kimi-k3": (1.7e-6, 0.17e-6, 8.5e-6),
    "deepseek/deepseek-v4.1-flash": (0.15e-6, 0.003e-6, 0.6e-6),
}
_EXIT_TIME = re.compile(r"exit (\d+) in ([\d.]+)s")
_REVIEW_TIME = re.compile(r"\[review\] .*?\((\d+)s\)")


def _load(session_dir: Path) -> list[dict]:
    path = session_dir / "transcript.jsonl"
    if not path.is_file():
        raise SystemExit(f"no transcript in {session_dir}")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _classify_read(path: str) -> str:
    p = path.replace("\\", "/")
    if "/scripts/" in p and p.endswith(".py"):
        return "script source"
    if p.startswith("skills/") or p.startswith("AGENTS") or p.startswith("hosts/"):
        return "skill docs"
    if "/sources/" in p:
        return "project sources"
    if "/templates/" in p:
        return "template prototypes"
    if "/svg_output/" in p:
        return "own pages"
    return "project files"


def analyse(session_dir: Path) -> dict:
    events = _load(session_dir)
    start = next((e for e in events if e.get("event") == "start"), {})
    end = next((e for e in reversed(events) if e.get("event") == "end"), None)
    turns = [e for e in events if e.get("event") == "turn"]
    tools = [e for e in events if e.get("event") == "tool"]
    images = sum(len(e.get("paths") or []) for e in events if e.get("event") == "images_delivered")
    http_errors = [e for e in events if e.get("event") in ("http_error", "transport_error")]
    model = start.get("model", "?")
    r: dict = {"session": session_dir.name, "model": model, "effort": start.get("effort"), "api_base": start.get("api_base", "https://api.openai.com/v1"),
               "stateless": start.get("stateless", False), "finished": end is not None}
    # tokens
    inp = sum(t["usage"].get("input_tokens", 0) for t in turns)
    cached = sum((t["usage"].get("input_tokens_details") or {}).get("cached_tokens", 0) for t in turns)
    out = sum(t["usage"].get("output_tokens", 0) for t in turns)
    reasoning = sum((t["usage"].get("output_tokens_details") or {}).get("reasoning_tokens", 0) for t in turns)
    r.update({"calls": len(turns), "input_tokens": inp, "cached_tokens": cached, "cache_ratio": (cached / inp) if inp else 0.0,
              "output_tokens": out, "reasoning_tokens": reasoning, "reasoning_share": (reasoning / out) if out else 0.0,
              "max_context": max((t["usage"].get("input_tokens", 0) for t in turns), default=0),
              "output_per_call": (out / len(turns)) if turns else 0.0})
    # cost
    reported = [t["usage"].get("cost") for t in turns if t["usage"].get("cost") is not None]
    if reported and len(reported) == len(turns):
        r["cost_usd"], r["cost_source"] = sum(reported), "openrouter"
    else:
        prices = PRICES.get(model) or PRICES.get(model.split("/")[-1])
        if prices:
            p_in, p_cached, p_out = prices
            r["cost_usd"], r["cost_source"] = (inp - cached) * p_in + cached * p_cached + out * p_out, "list price"
        else:
            r["cost_usd"], r["cost_source"] = None, "unknown"
    # time
    wall = ((end or {}).get("at") or 0) - (start.get("at") or 0) if end else None
    script_s = sum(float(m.group(2)) for e in tools for m in [_EXIT_TIME.search(e.get("result") or "")] if m)
    review_s = [int(m.group(1)) for e in tools for m in [_REVIEW_TIME.search(e.get("result") or "")] if m]
    measured = [t.get("api_s") for t in turns if t.get("api_s") is not None]
    r.update({"wall_s": wall, "script_s": script_s, "review_call_s": review_s,
              "api_s_per_call": (statistics.mean(measured) if measured else ((wall - script_s) / len(turns) if wall and turns else None)),
              "api_latency_source": "measured" if measured else "wall minus scripts"})
    # tool use
    by_name = collections.Counter(e.get("name") for e in tools)
    scripts = collections.Counter()
    reads = collections.Counter()
    failed = 0
    help_calls = 0
    page_name_slips = 0
    for e in tools:
        args = e.get("args") or ""
        result = e.get("result") or ""
        try:
            a = json.loads(args)
        except Exception:  # noqa: BLE001
            a = {}
        if e.get("name") == "run_script":
            script = Path(str(a.get("script", ""))).stem
            sub = (a.get("args") or [None])[0]
            scripts[f"{script} {sub}" if script in ("page_review", "reference_library", "project_manager") and sub and not str(sub).startswith("-") else script] += 1
            if any(str(x) in ("--help", "-h") for x in (a.get("args") or [])) or (a.get("args") == []):
                help_calls += 1
            if "no such page" in result:
                page_name_slips += 1
        if e.get("name") == "read_file":
            reads[_classify_read(str(a.get("path", "")))] += 1
        m = _EXIT_TIME.search(result)
        if result.startswith("error:") or (m and m.group(1) != "0"):
            failed += 1
    calls_per_turn = [len(t.get("calls") or []) for t in turns]
    text_only = sum(1 for c in calls_per_turn if c == 0)
    r.update({"tool_calls": len(tools), "tools_by_name": dict(by_name), "scripts": dict(scripts.most_common()), "reads": dict(reads),
              "failed_tool_calls": failed, "help_or_usage_calls": help_calls, "page_name_slips": page_name_slips,
              "calls_per_turn_mean": statistics.mean(calls_per_turn) if calls_per_turn else 0, "calls_per_turn_max": max(calls_per_turn, default=0),
              "text_only_turns": text_only, "http_errors": len(http_errors), "images_delivered": images,
              "edits": by_name.get("edit_file", 0), "writes": by_name.get("write_file", 0)})
    # project journal
    project = None
    for e in tools:
        m = re.search(r"projects[\\/]([A-Za-z0-9_.-]+)", e.get("args") or "")
        if m:
            project = m.group(1)
            break
    r["project"] = project
    if project:
        root = Path(__file__).resolve().parents[2] / "projects" / project
        journal = root / "quality-run.json"
        if journal.is_file():
            j = json.loads(journal.read_text(encoding="utf-8"))
            pages = {}
            for page, v in (j.get("pages") or {}).items():
                rv = v.get("review") or {}
                pages[page] = {"revisions": v.get("revisions"), "outcome": v.get("outcome"), "verdict": rv.get("verdict"), "blockers": rv.get("blockers")}
            r["pages"] = pages
            verdicts = collections.Counter()
            for f in (root / ".review" / "reviews").glob("*.md") if (root / ".review" / "reviews").is_dir() else []:
                m = re.search(r"VERDICT\W{0,12}(PASS|EXECUTION_REPAIR|CONCEPT_REPLAN)", f.read_text(encoding="utf-8"), re.I)
                verdicts[m.group(1).upper() if m else "UNPARSED"] += 1
            r["review_verdicts"] = dict(verdicts)
            r["exported"] = bool(list((root / "exports").glob("*.pptx"))) if (root / "exports").is_dir() else False
    return r


def _fmt_money(v):
    return "-" if v is None else f"${v:,.2f}"


def _fmt_s(v):
    if v is None:
        return "-"
    return f"{v/60:.0f} min" if v >= 120 else f"{v:.0f} s"


def markdown(rows: list[dict]) -> str:
    lines = ["| | " + " | ".join(r["session"] for r in rows) + " |", "|---|" + "---|" * len(rows)]
    def row(label, fn):
        lines.append(f"| {label} | " + " | ".join(str(fn(r)) for r in rows) + " |")
    row("model @ effort", lambda r: f"{r['model']} @ {r['effort']}")
    row("transport", lambda r: ("OpenRouter, stateless" if r["stateless"] else "OpenAI, stateful"))
    row("finished / exported", lambda r: f"{'yes' if r['finished'] else 'no'} / {'yes' if r.get('exported') else 'no'}")
    row("API calls", lambda r: r["calls"])
    row("tool calls", lambda r: r["tool_calls"])
    row("wall time", lambda r: _fmt_s(r["wall_s"]))
    row("API latency / call", lambda r: (f"{r['api_s_per_call']:.0f} s" if r["api_s_per_call"] else "-") + f" ({r['api_latency_source']})")
    row("scripts' own time", lambda r: _fmt_s(r["script_s"]))
    row("reviewer calls (s each)", lambda r: f"{len(r['review_call_s'])} ({statistics.mean(r['review_call_s']):.0f} s)" if r["review_call_s"] else "0")
    row("input tokens", lambda r: f"{r['input_tokens']/1e6:.1f}M")
    row("cached share", lambda r: f"{r['cache_ratio']*100:.0f}%")
    row("max context", lambda r: f"{r['max_context']/1e3:.0f}k")
    row("output tokens", lambda r: f"{r['output_tokens']/1e3:.0f}k")
    row("reasoning share of output", lambda r: f"{r['reasoning_share']*100:.0f}%")
    row("output / call", lambda r: f"{r['output_per_call']:.0f}")
    row("cost", lambda r: f"{_fmt_money(r['cost_usd'])} ({r['cost_source']})")
    row("calls per turn mean / max", lambda r: f"{r['calls_per_turn_mean']:.1f} / {r['calls_per_turn_max']}")
    row("text-only turns", lambda r: r["text_only_turns"])
    row("failed tool calls", lambda r: r["failed_tool_calls"])
    row("--help / usage calls", lambda r: r["help_or_usage_calls"])
    row("page-name slips", lambda r: r["page_name_slips"])
    row("HTTP / transport errors", lambda r: r["http_errors"])
    row("write_file / edit_file", lambda r: f"{r['writes']} / {r['edits']}")
    row("reads: skill docs", lambda r: r["reads"].get("skill docs", 0))
    row("reads: script source", lambda r: r["reads"].get("script source", 0))
    row("reads: template prototypes", lambda r: r["reads"].get("template prototypes", 0))
    row("reads: project sources", lambda r: r["reads"].get("project sources", 0))
    row("reads: own pages", lambda r: r["reads"].get("own pages", 0))
    row("images delivered", lambda r: r["images_delivered"])
    row("renders", lambda r: r["scripts"].get("page_review render", 0))
    row("reviews", lambda r: r["scripts"].get("page_review review", 0))
    row("review verdicts", lambda r: ", ".join(f"{k} {v}" for k, v in sorted((r.get("review_verdicts") or {}).items())) or "-")
    row("outcomes", lambda r: "; ".join(f"{p.split('_')[0]} {v['outcome'] or 'none'}({v['revisions']}r)" for p, v in sorted((r.get("pages") or {}).items())) or "-")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sessions", nargs="+")
    parser.add_argument("--sessions-dir", default=os.environ.get("PPT_MASTER_SESSIONS_DIR") or str(Path(__file__).resolve().parents[2] / ".host-sessions"))
    parser.add_argument("--md", help="write the comparison table to this file")
    parser.add_argument("--json", action="store_true", help="print the raw metrics as JSON")
    args = parser.parse_args()
    rows = [analyse(Path(args.sessions_dir) / s) for s in args.sessions]
    if args.json:
        print(json.dumps(rows, indent=1, default=str))
    table = markdown(rows)
    print(table)
    if args.md:
        Path(args.md).write_text(table + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
