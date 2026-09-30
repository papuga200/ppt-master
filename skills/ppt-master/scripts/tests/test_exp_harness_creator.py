"""EXPERIMENT-ONLY (svg-helpers-experiment-20260930): creator_run.py end to end, offline.

The real cli_host.py / tools_mcp.py / host.py run from a temp mirror of the worktree; `claude` is a stub that drives the pptm MCP
server with a scripted list of tool calls. Covered: fresh isolated workspace, script allowlist refusal, workspace read/write
guards, check-pass counting (3 in draft, the 4th refused; 2 in repair), SVG write snapshots and the first content-bearing write,
draft lock with hashes, deterministic stages on the locked copy, ledger events, resume of the run's OWN session only, the single
repair batch, and quarantine on an effective-model mismatch. No model call, no network.
"""

import json
import sys
import os
import stat

import pytest

import test_exp_harness_support as support

import common  # noqa: E402  (harness, on sys.path via support)
import creator_run  # noqa: E402

RUN_ID = "A-sonnet-timeline"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    mirror = support.make_mirror(tmp_path / "wt")
    evidence = support.make_evidence(tmp_path / "evidence")
    stub = support.write_cmd_stub(tmp_path / "bin", "claude", support.STUB_CLAUDE)
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps(support.draft_scenario()), encoding="utf-8")
    argv_log = tmp_path / "claude_argv.jsonl"
    monkeypatch.setenv("PPT_MASTER_CLAUDE_BIN", str(stub))
    monkeypatch.setenv("STUB_SCENARIO", str(scenario))
    monkeypatch.setenv("STUB_ARGV_LOG", str(argv_log))
    monkeypatch.setenv("STUB_COST_CUMULATIVE_DRAFT", "0.50")
    monkeypatch.setenv("STUB_COST_CUMULATIVE_REPAIR", "0.80")
    monkeypatch.delenv("STUB_EFFECTIVE_MODEL", raising=False)
    ctx = creator_run.Ctx(evidence, mirror, python=sys.executable)
    return {"ctx": ctx, "mirror": mirror, "evidence": evidence, "argv_log": argv_log, "tmp": tmp_path, "scenario": scenario}


def _argv_calls(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_draft_then_repair_end_to_end(env):
    ctx = env["ctx"]
    result = creator_run.cmd_draft(ctx, RUN_ID, None, 40)
    assert result["status"] == "completed", result
    trial = creator_run.Trial(ctx, RUN_ID)
    manifest = trial.manifest()

    # the workspace is fresh, blinded and holds only the fixture's creator files and the package files
    project = ctx.worktree / manifest["workspace"]["project_rel"]
    assert manifest["workspace"]["name"].startswith("w-") and RUN_ID not in manifest["workspace"]["project_rel"]
    inputs = sorted(p.relative_to(project / "inputs").as_posix() for p in (project / "inputs").rglob("*") if p.is_file())
    assert inputs == ["fixture/brief.md", "fixture/references/cur-gantt.png", "fixture/style_contract.md", "fixture/template/content.svg",
                      "package/package.json", "package/recipe.md"]
    assert "expected content" not in json.dumps([p.read_bytes().decode("utf-8", "replace") for p in (project / "inputs").rglob("*") if p.is_file()])
    assert manifest["script_allowlist"] == ["exp_svg/timeline/build_timeline.py", "exp_svg/inspect/submit_check.py"]
    assert manifest["creator"]["model"] == "claude-sonnet-5-5" and manifest["creator"]["api_base"] == "cli:claude"

    record = json.loads((trial.dir / "draft" / "invocations" / "01" / "record.json").read_text(encoding="utf-8"))
    # guards: the non-allowlisted script, the read outside the workspace and the write into inputs/ were all refused and logged
    refusals = {(r["guard"], r["tool"]) for r in record["guard_refusals"]}
    assert ("PPT_MASTER_SCRIPT_ALLOWLIST", "run_script") in refusals
    assert ("PPT_MASTER_READ_ROOTS", "read_file") in refusals
    assert ("PPT_MASTER_WRITE_ROOTS", "write_file") in refusals
    assert record["inputs_unchanged"] is True
    lint = [t for t in record["tools"] if t["script"] == "page_lint.py"]
    assert lint and lint[0]["error"] and lint[0]["refused"]

    # pass counting: three granted in the draft stage, the fourth refused
    passes = json.loads(trial.check_state.read_text(encoding="utf-8"))
    claims = passes["stages"]["draft"]["claims"]
    assert [c["granted"] for c in claims] == [True, True, True, False]
    assert record["check_passes_granted"] == 3
    assert [t["exit"] for t in record["submit_checks"]] == [0, 0, 0, 3]

    # snapshots: the placeholder write is not content-bearing, the full draft is
    snaps = record["svg_snapshots"]
    assert [s["content_bearing"] for s in snaps] == [False, True]
    ts = record["timestamps_epoch"]
    assert ts["first_svg_write"] < ts["first_content_svg_write"] <= ts["first_submit_check_start"]
    assert ts["first_model_response"] and ts["first_tool_call"]

    # identity, auth and usage evidence
    assert record["identity"]["verified"] is True and record["identity"]["model_effective"] == "claude-sonnet-5-5"
    assert record["authentication"]["verified"] is True and record["money"]["api_cash_usd"] == 0.0
    assert record["money"]["subscription_notional_usd"] == 0.5
    assert record["usage"]["input_tokens"] == 480 and record["usage"]["reasoning_tokens"] is None

    # the draft lock: a read-only copy with hashes; deterministic stages ran on the copy
    lock = json.loads((trial.dir / "draft" / "lock_manifest.json").read_text(encoding="utf-8"))
    locked_svg = trial.dir / "draft" / "locked" / "svg_output" / "slide.svg"
    assert lock["svg"]["sha256"] == common.sha256_file(locked_svg) == common.sha256_bytes(support.CONTENT_SVG.encode("utf-8"))
    assert not os.stat(locked_svg).st_mode & stat.S_IWRITE
    inspect = json.loads((trial.dir / "draft" / "inspect_svg" / "result.json").read_text(encoding="utf-8"))
    assert inspect["svg_sha256"] == lock["svg"]["sha256"] and inspect["request"]["harness"]["svg"] == str(locked_svg)
    assert inspect["request"]["checklist"].endswith("checklist.json")  # the protected checklist reaches the inspector only
    inspect_record = json.loads((trial.dir / "draft" / "inspect_svg" / "record.json").read_text(encoding="utf-8"))
    assert inspect_record["summary"]["states_svg_sha256"] is True and (trial.dir / "draft" / "inspect_svg" / "render.png").is_file()
    assert (trial.dir / "draft" / "render_export" / "result.json").is_file()
    draft_record = json.loads((trial.dir / "draft" / "stage_record.json").read_text(encoding="utf-8"))
    assert draft_record["check_passes"] == {"granted": 3, "submit_check_calls": 4, "limit": 3}
    assert draft_record["protocol_flags"] == []

    # repair resumes this run's own session, once
    packet = env["tmp"] / "packet.md"
    packet.write_text("## Blockers\n- M01: label the Pilot bar with its duration.\n", encoding="utf-8")
    repair = creator_run.cmd_repair(ctx, RUN_ID, packet)
    assert repair["resume_check"]["own_session_resumed"] is True
    calls = [c for c in _argv_calls(env["argv_log"]) if "-p" in c]
    assert len(calls) == 2
    draft_sid = calls[0][calls[0].index("--session-id") + 1]
    assert calls[1][calls[1].index("--resume") + 1] == draft_sid == draft_record["cli_session_id"]
    assert calls[1][calls[1].index("--model") + 1] == "claude-sonnet-5-5"
    passes = json.loads(trial.check_state.read_text(encoding="utf-8"))
    assert [c["granted"] for c in passes["stages"]["repair"]["claims"]] == [True]
    repair_record = json.loads((trial.dir / "repair" / "invocations" / "01" / "record.json").read_text(encoding="utf-8"))
    assert repair_record["money"]["subscription_notional_usd"] == pytest.approx(0.30)  # 0.80 cumulative - 0.50 already charged
    assert repair_record["money"]["subscription_notional_cumulative_usd"] == 0.8
    final_svg = trial.dir / "final" / "locked" / "svg_output" / "slide.svg"
    assert "Pilot (4 weeks)" in final_svg.read_text(encoding="utf-8")
    assert "Pilot (4 weeks)" not in locked_svg.read_text(encoding="utf-8")  # the locked draft is untouched
    with pytest.raises(creator_run.CreatorError, match="one external-feedback repair batch"):
        creator_run.cmd_repair(ctx, RUN_ID, packet)

    # the ledger holds the whole story and its chain verifies
    led = ctx.ledger
    assert led.verify()["ok"]
    events = [(r["event"], r.get("actor"), r.get("stage")) for r in led.records()]
    assert ("dispatch", "creator", "draft") in events and ("end", "creator", "repair") in events
    assert ("end", "deterministic", "draft") in events and ("end", "deterministic", "final") in events
    names = {r.get("name") for r in led.records() if r["event"] == "timestamp"}
    assert {"dispatch", "first_content_svg_write", "first_submit_check_start", "inspection_start", "render_export_end",
            "repair_dispatch", "final_svg"} <= names


def test_repair_refuses_a_foreign_session(env):
    ctx = env["ctx"]
    env["scenario"].write_text(json.dumps({"draft": [{"tool": "write_file", "args": {"path": "{page}", "content": support.CONTENT_SVG}}],
                                           "repair": []}), encoding="utf-8")
    assert creator_run.cmd_draft(ctx, RUN_ID, None, 40)["status"] == "completed"
    trial = creator_run.Trial(ctx, RUN_ID)
    state_path = trial.session_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["cli_session_id"] = "00000000-0000-0000-0000-000000000000"  # another conversation
    state_path.write_text(json.dumps(state), encoding="utf-8")
    packet = env["tmp"] / "packet.md"
    packet.write_text("fix it", encoding="utf-8")
    with pytest.raises(creator_run.CreatorError, match="refusing to resume"):
        creator_run.cmd_repair(ctx, RUN_ID, packet)
    assert not trial.stage_dir("repair").exists()
    assert len([c for c in _argv_calls(env["argv_log"]) if "-p" in c]) == 1  # no second CLI conversation was started

    state["cli_session_id"] = json.loads((trial.dir / "draft" / "stage_record.json").read_text(encoding="utf-8"))["cli_session_id"]
    state["model"] = "claude-opus-5-5"  # a model switch is refused as well
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(creator_run.CreatorError, match="model/effort"):
        creator_run.cmd_repair(ctx, RUN_ID, packet)


def test_effective_model_mismatch_quarantines(env, monkeypatch):
    ctx = env["ctx"]
    env["scenario"].write_text(json.dumps({"draft": [{"tool": "write_file", "args": {"path": "{page}", "content": support.CONTENT_SVG}}],
                                           "repair": []}), encoding="utf-8")
    monkeypatch.setenv("STUB_EFFECTIVE_MODEL", "claude-haiku-5")
    creator_run.cmd_draft(ctx, RUN_ID, None, 40)
    trial = creator_run.Trial(ctx, RUN_ID)
    quarantine = json.loads((trial.dir / "quarantine.json").read_text(encoding="utf-8"))
    assert quarantine["identity"]["mismatch"] is True
    assert any(r["event"] == "quarantined" and r["run_id"] == RUN_ID for r in ctx.ledger.records())
    end = [r for r in ctx.ledger.records() if r["event"] == "end" and r.get("actor") == "creator"][0]
    assert end["metrics"]["quarantined"] is True and end["metrics"]["money"]["subscription_notional_usd"] == 0.5  # cost kept


def test_run_id_is_used_once_and_package_must_exist(env):
    ctx = env["ctx"]
    (env["evidence"] / "trials" / RUN_ID).mkdir(parents=True)
    with pytest.raises(creator_run.CreatorError, match="already exists"):
        creator_run.prepare(ctx, RUN_ID, None, 40)
    with pytest.raises(common.HarnessError, match="not in run_plan"):
        creator_run.prepare(ctx, "Z-nobody-timeline", None, 40)
    with pytest.raises(creator_run.CreatorError, match="no package directory"):
        creator_run.prepare(ctx, "B-sonnet-timeline", None, 40)


def test_codex_identity_comes_from_the_rollout(tmp_path):
    rollout = tmp_path / "rollout-2026-09-30T10-00-00-thread1.jsonl"
    rows = [{"type": "turn_context", "payload": {"model": "gpt-6-luna", "effort": "high", "sandbox_policy": {"type": "read-only"}}},
            {"type": "token_usage_record", "payload": {"usage": {"input_tokens": 900, "cached_input_tokens": 600, "output_tokens": 80,
                                                                 "reasoning_output_tokens": 40}}}]
    rollout.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    state = {"last_run": {"rollout": str(rollout)}}
    ok = creator_run.identity_evidence("cli:codex", "gpt-6-luna", "high", [], [], state)
    assert ok["verified"] is True and ok["effort_verified"] is True and ok["model_effective"] == "gpt-6-luna"
    wrong = creator_run.identity_evidence("cli:codex", "gpt-6-sol", "high", [], [], state)
    assert wrong["mismatch"] is True and wrong["verified"] is False
    low = creator_run.identity_evidence("cli:codex", "gpt-6-luna", "xhigh", [], [], state)
    assert low["mismatch"] is True  # an effort mismatch quarantines too
    missing = creator_run.identity_evidence("cli:codex", "gpt-6-luna", "high", [], [], {"last_run": {}})
    assert missing["verified"] is False and missing["mismatch"] is False and missing["model_verified"] is None  # unverified, not assumed


def test_codex_route_env_is_scrubbed_and_guarded(env, monkeypatch):
    ctx = env["ctx"]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-pass")
    monkeypatch.setenv("PPT_MASTER_REVIEW_API_BASE", "https://example.invalid")
    monkeypatch.setenv("PPT_MASTER_ENV_FILE", "D:/somewhere/.env")
    trial = creator_run.prepare(ctx, "A-luna-timeline", None, 40)
    child = creator_run.build_env(ctx, trial, "draft")
    assert "OPENAI_API_KEY" not in child and "PPT_MASTER_ENV_FILE" not in child and "PPT_MASTER_REVIEW_API_BASE" not in child
    assert child["PPT_MASTER_API_BASE"] == "cli:codex" and child["PPT_MASTER_MODEL"] == "gpt-6-luna" and child["PPT_MASTER_EFFORT"] == "high"
    assert child["PPT_MASTER_SCRIPT_ALLOWLIST"] == "exp_svg/timeline/build_timeline.py;exp_svg/inspect/submit_check.py"
    project = trial.manifest()["workspace"]["project_rel"]
    assert child["PPT_MASTER_READ_ROOTS"] == project and child["PPT_MASTER_WRITE_ROOTS"] == f"{project}/svg_output;{project}/work"
    assert child["PPT_MASTER_EXP_CHECK_STAGE"] == "draft" and child["PPT_MASTER_EXP_CHECK_LIMIT"] == "3"
    assert child["PPT_MASTER_EXP_CHECK_STATE"] == str(trial.check_state)
