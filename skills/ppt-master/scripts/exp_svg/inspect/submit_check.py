#!/usr/bin/env python3
"""
PPT Master - exp_svg submit_check (creator-facing render/check pass)

A creator submits the current page SVG for one explicit render/check pass. The tool snapshots
the SVG (copy + sha256) into a numbered pass folder, renders it in Chromium, runs inspect_svg
against the run's inspection request and checklist, writes the full report and a budgeted
reviewer summary, prints the summary and an `IMAGE: <png>` line, and counts the pass against
the stage's limit. A pass is an explicit snapshot, not every small edit.

Limits (from the environment or a config file, never from the creator's command line):
    EXP_SVG_PASS_LIMIT_DRAFT   default 3   passes in the draft stage
    EXP_SVG_PASS_LIMIT_REPAIR  default 2   passes in the repair stage
    EXP_SVG_PASS_CONFIG        optional JSON {"limits": {"draft": 3, "repair": 2}, "request": "...", "run_dir": "..."}
    EXP_SVG_PASS_LEDGER        optional path of the pass ledger (the orchestrator can keep it outside
                               the creator's folder); default <run dir>/passes.json
    EXP_SVG_RUN_DIR            default run dir; else --run-dir; else <svg dir>/.exp_svg_passes
    EXP_SVG_REQUEST            default inspection request; else --in

Beyond the limit the tool refuses before rendering anything and says so (exit 4). An SVG
byte-identical to the latest submitted pass is not counted again: the previous result is
returned and marked as a repeat.

Usage:
    python3 submit_check.py --svg page.svg --stage draft|repair [--in request.json] [--run-dir DIR] [--export] [--max-tokens 2000]

Examples:
    EXP_SVG_PASS_LIMIT_DRAFT=3 python3 submit_check.py --svg svg_output/07_plan.svg --stage draft --in request.json

Dependencies:
    playwright (Chromium); render_export.py dependencies when --export is given
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import common  # noqa: E402

common.ensure_scripts_path()

import inspect_svg as I  # noqa: E402
import summary as S  # noqa: E402

TOOL = "submit_check"
DEFAULT_LIMITS = {"draft": 3, "repair": 2}
REFUSED_EXIT = 4


def load_config() -> dict:
    path = os.environ.get("EXP_SVG_PASS_CONFIG")
    return common.read_json(Path(path)) if path else {}


def limits(config: dict) -> dict:
    lim = dict(DEFAULT_LIMITS)
    lim.update(config.get("limits") or {})
    for stage in ("draft", "repair"):
        env = os.environ.get(f"EXP_SVG_PASS_LIMIT_{stage.upper()}")
        if env:
            lim[stage] = int(env)
    return lim


class LedgerLock:
    def __init__(self, ledger: Path):
        self.path = ledger.with_name(ledger.name + ".lock")

    def __enter__(self) -> "LedgerLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("ascii"))
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    owner = int(self.path.read_text(encoding="ascii").strip() or "0")
                except (OSError, ValueError):
                    owner = 0
                from render_export import _pid_alive
                if owner and not _pid_alive(owner):
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                time.sleep(0.5)

    def __exit__(self, *exc) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass


def harness_claim(stage: str, digest: str) -> tuple[bool, str]:
    """Experiment harness mode (orchestrator integration, D019): claim one pass in the trial's state file through the
    harness pass counter. Returns (granted, detail)."""
    import subprocess
    counter = Path(os.environ["PPT_MASTER_EXP_HARNESS_DIR"]) / "pass_counter.py"
    proc = subprocess.run([sys.executable, str(counter), "claim", "--state", os.environ["PPT_MASTER_EXP_CHECK_STATE"], "--stage", stage,
                           "--svg-sha256", digest], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return proc.returncode == 0, (proc.stdout or proc.stderr).strip()[:400]


def creator_request(svg: Path) -> tuple[Optional[dict], Optional[str]]:
    """The creator-side request the harness wrote (floors, canvas, chrome exemptions; never a checklist), with the scale the
    creator declared in <workspace>/work/scene.json merged in for timelines (decision D011)."""
    path = os.environ.get("PPT_MASTER_EXP_CREATOR_REQUEST")
    if not path or not Path(path).is_file():
        return None, None
    request = json.loads(Path(path).read_text(encoding="utf-8"))
    request.pop("checklist", None)
    timeline = request.get("timeline")
    if isinstance(timeline, dict) and "scale_defaults" in timeline:
        timeline = dict(timeline)
        defaults = timeline.pop("scale_defaults")
        timeline.pop("scale_source", None)
        scene_path = Path(svg).resolve().parent.parent / "work" / "scene.json"
        try:
            declared = json.loads(scene_path.read_text(encoding="utf-8")).get("time_scale") if scene_path.is_file() else None
        except (OSError, ValueError, AttributeError):
            declared = None
        if isinstance(declared, dict) and isinstance(declared.get("origin_x"), (int, float)) and isinstance(declared.get("px_per_week"), (int, float)) \
                and declared["px_per_week"] > 0:
            timeline["scale"] = {**defaults, "origin_x": float(declared["origin_x"]), "px_per_unit": float(declared["px_per_week"])}
            if isinstance(declared.get("tick_pattern"), str) and declared["tick_pattern"]:
                timeline["ticks"] = {"pattern": declared["tick_pattern"], "anchor": declared.get("tick_anchor") or "center"}
        request["timeline"] = timeline
    return request, common.sha256_bytes(json.dumps(request, sort_keys=True).encode("utf-8"))


def submit(svg: Path, stage: str, request_path: Optional[Path], run_dir: Path, ledger_path: Path, lim: dict, *,
           export: bool = False, max_tokens: int = 2000, claim=None, request_override: Optional[tuple] = None) -> tuple[int, dict, str]:
    started = time.perf_counter()
    svg = Path(svg).resolve()
    data = svg.read_bytes()
    digest = common.sha256_bytes(data)
    with LedgerLock(ledger_path):
        ledger = common.read_json(ledger_path) if ledger_path.is_file() else {"schema": "exp_svg.passes/v1", "passes": []}
        used = [p for p in ledger["passes"] if p["stage"] == stage and not p.get("repeat")]
        latest = next((p for p in reversed(ledger["passes"]) if p.get("result") and not p.get("repeat")), None)
        if latest and latest["svg_sha256"] == digest and latest.get("result"):
            text = Path(latest["summary"]).read_text(encoding="utf-8") if Path(latest["summary"]).is_file() else ""
            note = (f"REPEAT: this SVG is byte-identical to pass {latest['pass_id']} (sha256 {digest[:16]}); "
                    f"not counted. {len(used)} of {lim[stage]} {stage} passes used.\n")
            ledger["passes"].append({"pass_id": latest["pass_id"] + "-repeat", "stage": stage, "svg_sha256": digest, "repeat": True,
                                     "at": common.utc_now(), "of": latest["pass_id"]})
            common.write_json(ledger_path, ledger)
            res = common.envelope(TOOL, input_hash=digest, status=latest["result"]["status"], started=started, repeat_of=latest["pass_id"],
                                  png=latest.get("png"), report=latest.get("report"))
            return 0, res, note + text
        if len(used) >= lim[stage]:
            msg = (f"REFUSED: the {stage} stage allows {lim[stage]} submitted render/check passes and all {len(used)} are used "
                   f"({', '.join(p['pass_id'] for p in used)}). Nothing was rendered or checked. Measurement tools remain available; "
                   f"finish the stage with the SVG as it is, or report the unresolved issues.\n")
            ledger["passes"].append({"pass_id": None, "stage": stage, "svg_sha256": digest, "refused": True, "at": common.utc_now()})
            common.write_json(ledger_path, ledger)
            res = common.envelope(TOOL, input_hash=digest, status="error", started=started, refused=True, stage=stage, used=len(used), limit=lim[stage])
            return REFUSED_EXIT, res, msg
        if claim is not None:
            granted, detail = claim(stage, digest)
            if not granted:
                ledger["passes"].append({"pass_id": None, "stage": stage, "svg_sha256": digest, "refused": True, "harness": detail, "at": common.utc_now()})
                common.write_json(ledger_path, ledger)
                res = common.envelope(TOOL, input_hash=digest, status="error", started=started, refused=True, stage=stage, harness=detail)
                return REFUSED_EXIT, res, f"REFUSED by the run's check allowance ({stage}): {detail}\nNothing was rendered or checked.\n"
        pass_id = f"{stage}-{len(used) + 1}"
        folder = run_dir / "passes" / pass_id
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        snap = folder / svg.name
        snap.write_bytes(data)
        (folder / (svg.name + ".sha256")).write_text(f"{digest}  {svg.name}\n", encoding="utf-8")
        entry = {"pass_id": pass_id, "stage": stage, "n": len(used) + 1, "limit": lim[stage], "svg": str(svg), "snapshot": str(snap),
                 "svg_sha256": digest, "at": common.utc_now()}
        ledger["passes"].append(entry)
        common.write_json(ledger_path, ledger)
    # outside the ledger lock: render, inspect, summarise (a crash leaves the pass counted, as submitted)
    if request_override is not None:
        request, rhash = request_override
        base = None
        checklist, chash, csrc = None, None, None
    else:
        request, rhash, base = I.load_request(request_path) if request_path else ({}, None, None)
        checklist, chash, csrc = I.load_checklist(request, base, None)
    png = folder / "render.png"
    t0 = time.perf_counter()
    report = I.inspect_file(snap, request, checklist, png=png, request_hash=rhash, checklist_hash=chash, checklist_src=csrc)
    common.write_json(folder / "inspect_report.json", report)
    timings = {"inspect_s": round(time.perf_counter() - t0, 3)}
    text = S.render(report, max_tokens, str(folder / "inspect_report.json"))
    export_result = None
    if export:
        t1 = time.perf_counter()
        from render_export import render_export
        export_result = render_export(snap, folder / "render_export")
        common.write_json(folder / "render_export" / "render_export.json", export_result)
        timings["render_export_s"] = round(time.perf_counter() - t1, 3)
        conv = [f for f in export_result["findings"] if f["attribution"] in ("conversion", "exporter_contract")]
        text += (f"EXPORT (conversion evidence, not author findings): status {export_result['status']}; "
                 f"{len(conv)} conversion/contract findings: " + "; ".join(f"{f['code']}" for f in conv[:12]) + "\n")
    header = f"PASS {pass_id} ({entry['n']} of {lim[stage]} {stage} passes) | svg sha256 {digest}\n"
    text = header + text
    (folder / "summary.txt").write_text(text, encoding="utf-8")
    res = common.envelope(TOOL, input_hash=digest, status=report.get("status", "error"), started=started, pass_id=pass_id, stage=stage,
                          used=entry["n"], limit=lim[stage], png=str(png) if png.is_file() else None, report=str(folder / "inspect_report.json"),
                          summary=str(folder / "summary.txt"), summary_tokens_est=S.estimate_tokens(text), timings_s=timings,
                          export=(export_result or {}).get("status"))
    res["output_sha256"] = report.get("output_sha256")
    common.write_json(folder / "submit_result.json", res)
    with LedgerLock(ledger_path):
        ledger = common.read_json(ledger_path)
        for p in ledger["passes"]:
            if p.get("pass_id") == pass_id and not p.get("repeat"):
                p.update(result={"status": res["status"], "failed": report.get("result", {}).get("failed"), "unverified": report.get("result", {}).get("unverified")},
                         png=res["png"], report=res["report"], summary=res["summary"], elapsed_s=res["elapsed_s"])
        common.write_json(ledger_path, ledger)
    return (0 if res["status"] != "error" else 1), res, text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit one render/check pass of the current page SVG (counted against the stage limit).",
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--stage", choices=["draft", "repair"], required=True)
    parser.add_argument("--in", dest="request", type=Path, help="inspection request JSON (default EXP_SVG_REQUEST or the config's request)")
    parser.add_argument("--run-dir", type=Path, help="where pass folders go (default EXP_SVG_RUN_DIR, config run_dir, or <svg dir>/.exp_svg_passes)")
    parser.add_argument("--export", action="store_true", help="also run render_export.py (native PPTX, PowerPoint render, parity)")
    parser.add_argument("--max-tokens", type=int, default=2000)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    from console_encoding import configure_utf8_stdio
    configure_utf8_stdio()
    if not args.svg.is_file():
        print(f"error: no such SVG: {args.svg}", file=sys.stderr)
        return 1
    config = load_config()
    lim = limits(config)
    run_dir = Path(os.environ.get("EXP_SVG_RUN_DIR") or args.run_dir or config.get("run_dir") or (args.svg.resolve().parent / ".exp_svg_passes"))
    ledger = Path(os.environ.get("EXP_SVG_PASS_LEDGER") or (run_dir / "passes.json"))
    req = args.request or (Path(os.environ["EXP_SVG_REQUEST"]) if os.environ.get("EXP_SVG_REQUEST") else None) or \
        (Path(config["request"]) if config.get("request") else None)
    stage, claim, override = args.stage, None, None
    if os.environ.get("PPT_MASTER_EXP_CHECK_STATE"):  # experiment harness mode (D019): the harness, not the caller, sets stage and limit
        stage = os.environ.get("PPT_MASTER_EXP_CHECK_STAGE") or args.stage
        lim = {**lim, stage: int(os.environ.get("PPT_MASTER_EXP_CHECK_LIMIT") or lim[stage])}
        out = os.environ.get("PPT_MASTER_EXP_CHECK_OUT")
        run_dir = Path(out) if out else run_dir  # relative to the host's working directory, the repository root
        ledger = run_dir / "passes.json"
        claim = harness_claim
        override = creator_request(args.svg)
        if override[0] is None:
            override = ({}, None)
    code, res, text = submit(args.svg, stage, req, run_dir.resolve(), ledger.resolve(), lim, export=args.export, max_tokens=args.max_tokens,
                             claim=claim, request_override=override)
    sys.stdout.write(text)
    if res.get("png"):
        print(f"IMAGE: {res['png']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
