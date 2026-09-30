"""EXPERIMENT-ONLY (svg-helpers-experiment-20260930): review_run.py offline.

Grok goes to a local stub HTTP server (never OpenRouter); Sonnet goes to a stub `claude` CLI. Covered: cash-cap refusal when the
cap is null, reservation arithmetic and settlement, response schema validation, blinding of the payload, fixed reviewer order,
serial execution, the 112/8 ceilings, no retry of a malformed answer, quarantine on a model mismatch, and the API key never
reaching any written file. No model call, no network beyond 127.0.0.1.
"""

import argparse
import base64
import json
from decimal import Decimal
from pathlib import Path

import pytest

import test_exp_harness_support as support

import common  # noqa: E402
import ledger as ledger_mod  # noqa: E402
import review_run  # noqa: E402

RUN_ID = "A-luna-timeline"
FAKE_KEY = "sk-or-v1-TESTONLY-0123456789abcdef"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture()
def world(tmp_path, monkeypatch):
    evidence = support.make_evidence(tmp_path / "evidence", cash_cap=1.0)
    svg = tmp_path / "locked" / "slide.svg"
    svg.parent.mkdir()
    svg.write_text(support.CONTENT_SVG, encoding="utf-8")
    sha = common.sha256_file(svg)
    image = tmp_path / "render_7f3a.png"
    image.write_bytes(PNG)
    style = tmp_path / "style_ref_A.png"
    style.write_bytes(PNG)
    summary = tmp_path / "summary.md"
    summary.write_text(f"# Inspection\nsvg sha256: {sha}\nchecks: 12 run, 1 unverified (d1 endpoint)\nreport: D:\\secret\\trials\\x\\report.json\n",
                       encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(f"OTHER=1\nOPENROUTER_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return {"evidence": evidence, "svg": svg, "sha": sha, "image": image, "style": style, "summary": summary, "env_file": env_file,
            "tmp": tmp_path, "brief": evidence / "fixtures" / "T-DEV" / "creator" / "brief.md"}


def _args(world, reviewer, phase="initial", **extra):
    values = {"run_id": RUN_ID, "phase": phase, "reviewer": reviewer, "kind": "normal", "image": str(world["image"]),
              "inspection_summary": str(world["summary"]), "svg": str(world["svg"]), "brief": str(world["brief"]),
              "style_ref": [str(world["style"])], "extra_instructions": None, "allow_token": None,
              "max_output_tokens": 32000, "env_file": str(world["env_file"]), "dry_run": None,
              "evidence_root": str(world["evidence"]), "worktree": None, "ledger": None}
    values.update(extra)
    return argparse.Namespace(**values)


def _grok_reply(text, model="x-ai/grok-4.6", cost=0.0123):
    usage = {"input_tokens": 3100, "output_tokens": 900, "output_tokens_details": {"reasoning_tokens": 600}}
    if cost is not None:
        usage["cost"] = cost
    return {"id": "gen-1", "model": model, "status": "completed", "usage": usage,
            "output": [{"type": "reasoning", "id": "r1", "summary": [{"type": "summary_text", "text": "private musing"}]},
                       {"type": "message", "content": [{"type": "output_text", "text": text}]}]}


def _ledger(world):
    return ledger_mod.Ledger(world["evidence"] / "ledger.jsonl")


def _sonnet_stub(world, monkeypatch, review_text, model=None):
    stub = support.write_cmd_stub(world["tmp"] / "bin", "claude", support.STUB_CLAUDE)
    text_file = world["tmp"] / "review_text.txt"
    text_file.write_text(review_text, encoding="utf-8")
    monkeypatch.setenv("PPT_MASTER_CLAUDE_BIN", str(stub))
    monkeypatch.setenv("STUB_REVIEW_TEXT", str(text_file))
    monkeypatch.setenv("STUB_ARGV_LOG", str(world["tmp"] / "argv.jsonl"))
    if model:
        monkeypatch.setenv("STUB_EFFECTIVE_MODEL", model)
    else:
        monkeypatch.delenv("STUB_EFFECTIVE_MODEL", raising=False)


# --- cash cap ---------------------------------------------------------------------------------------------------------------------
def test_null_cash_cap_refuses_before_any_slot_or_request(world, monkeypatch):
    (world["evidence"] / "manifest.json").write_text(json.dumps({**json.loads((world["evidence"] / "manifest.json").read_text()),
                                                                 "routes": {"grok_reviewer": {"cash_cap_usd": None}}}), encoding="utf-8")
    led = _ledger(world)
    led.append({"event": "reviewer_reserved", "run_id": RUN_ID, "phase": "initial", "kind": "normal", "call_id": "RV001", "svg_sha256": world["sha"]})
    led.append({"event": "end", "actor": "reviewer", "call_id": "RV001"})
    with support.StubOpenRouter(_grok_reply("{}")) as server:
        monkeypatch.setenv("EXP_OPENROUTER_BASE_URL", server.base)
        with pytest.raises(review_run.ReviewError, match="api_cash_cap_usd is not set"):
            review_run.run_review(_args(world, "grok"))
        assert server.requests == []
    assert ledger_mod.reviewer_counts(led.records())["total"] == 1  # no slot consumed
    for manifest in ({"api_cash_cap_usd": None}, {}, {"routes": {"grok_reviewer": {"cash_cap_usd": None}}}, {"api_cash_cap_usd": 5, "routes": {"grok_reviewer": {"cash_cap_usd": 7}}},
                     {"api_cash_cap_usd": 0}):
        path = world["tmp"] / "m.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(review_run.ReviewError, match="REFUSED"):
            review_run.read_cash_cap(path)
    path.write_text(json.dumps({"api_cash_cap_usd": 12.5}), encoding="utf-8")
    assert review_run.read_cash_cap(path) == Decimal("12.5")


def test_reservation_arithmetic_and_cap_check():
    snap = {"reservation_input_usd_per_token": "0.000002", "reservation_output_usd_per_token": "0.000006"}
    # (1000 x 2e-6 + 32000 x 6e-6) x 1.25 = (0.002 + 0.192) x 1.25 = 0.2425
    assert review_run.reservation_usd(1000, 32000, snap) == Decimal("0.242500")
    assert review_run.reservation_usd(1, 1, snap) == Decimal("0.000010")  # rounded UP to the micro-dollar
    records = [{"event": "cash_reserved", "reservation_id": "RV002", "usd": "0.242500"},
               {"event": "cash_settled", "reservation_id": "RV002", "usd": "0.0123"}]
    plan = review_run.check_cash(records, Decimal("0.5"), Decimal("0.2425"))
    assert plan["committed_after_usd"] == "0.2548"
    records.append({"event": "cash_reserved", "reservation_id": "RV004", "usd": "0.242500"})  # open: counts in full
    # 0.0123 settled + 0.2425 open + 0.2425 new = 0.4973 > 0.49
    with pytest.raises(review_run.ReviewError, match="would commit 0.497300 USD against the 0.49 USD cap"):
        review_run.check_cash(records, Decimal("0.49"), Decimal("0.2425"))
    assert review_run.check_cash(records, Decimal("0.4973"), Decimal("0.2425"))["committed_after_usd"] == "0.497300"  # exactly at the cap
    live = review_run.price_snapshot()
    assert Decimal(live["reservation_input_usd_per_token"]) >= Decimal("0.000002")
    assert Decimal(live["reservation_output_usd_per_token"]) >= Decimal("0.000006")
    assert live["snapshot_date"] == "2026-09-30" and live["model"] == "x-ai/grok-4.6"


# --- schema ------------------------------------------------------------------------------------------------------------------------
def test_schema_validation():
    sha = "a" * 64
    good = support.valid_review(sha)
    assert review_run.validate_review(json.dumps(good), sha)["status"] == "valid"
    assert review_run.validate_review("```json\n" + json.dumps(good) + "\n```", sha)["extraction"] == "fenced"
    assert review_run.validate_review("Here is my review:\n" + json.dumps(good), sha)["status"] == "malformed"
    cases = {
        "missing `scores`": {k: v for k, v in good.items() if k != "scores"},
        "artifact_sha256 does not match": {**good, "artifact_sha256": "b" * 64},
        "verdict must be one of": {**good, "verdict": "EXECUTION_REPAIR"},
        "scores.readability.score must be 0-3": {**good, "scores": {**good["scores"], "readability": {"score": 4, "evidence": "x"}}},
        "blockers[0] lacks `suggested_change`": {**good, "blockers": [{k: v for k, v in good["blockers"][0].items() if k != "suggested_change"}]},
        "element_ids must be a list": {**good, "blockers": [{**good["blockers"][0], "element_ids": "b2"}]},
        "scores.composition_spacing must be an object": {**good, "scores": {**good["scores"], "composition_spacing": 2}},
    }
    for expected, value in cases.items():
        result = review_run.validate_review(json.dumps(value), sha)
        assert result["status"] == "malformed" and any(expected in e for e in result["errors"]), (expected, result["errors"])
    unscored = {**good, "scores": {**good["scores"], "readability": {"score": None, "evidence": ""}}}
    assert review_run.validate_review(json.dumps(unscored), sha)["status"] == "valid"  # null = unassessable
    bare_repair = review_run.validate_review(json.dumps({**good, "blockers": []}), sha)
    assert bare_repair["status"] == "malformed" and bare_repair["consistency_errors"] == ["a repair verdict must name at least one blocker"]
    assert review_run.validate_review(json.dumps({**good, "verdict": "pass"}), sha)["consistency_errors"] == ["a pass verdict cannot carry blockers"]


# --- blinding ----------------------------------------------------------------------------------------------------------------------
def test_payload_is_blinded(world):
    out = world["tmp"] / "dry"
    result = review_run.run_review(_args(world, "grok", dry_run=str(out)))
    assert result["status"] == "dry-run"
    manifest = json.loads((out / "request_manifest.json").read_text(encoding="utf-8"))
    text = json.dumps(manifest["request"])
    for forbidden in ("luna", "gpt-6", "A-luna-timeline", "render_7f3a", "style_ref_A", "D:\\\\secret", "claude", "sonnet", "cost_usd"):
        assert forbidden.lower() not in text.lower(), forbidden
    assert "<path>" in text and world["sha"] in text
    assert [p["type"] for p in manifest["request"]["input"][0]["content"]].count("input_image") == 2
    assert _ledger(world).records() == []  # a dry run reserves nothing

    world["summary"].write_text(f"sha {world['sha']}\nauthored by gpt-6-luna for A-luna-timeline\n", encoding="utf-8")
    with pytest.raises(review_run.ReviewError, match="would reveal identity or economics"):
        review_run.run_review(_args(world, "grok", dry_run=str(out)))
    world["summary"].write_text(f"sha {world['sha']}\ncreator latency 412 s, notional 0.61\n", encoding="utf-8")
    with pytest.raises(review_run.ReviewError, match="would reveal"):
        review_run.run_review(_args(world, "sonnet", dry_run=str(out)))
    # fixture vocabulary is identical for every creator: an architecture brief may name "Azure OpenAI"; run identity still refused
    world["brief"].write_text("# Brief\n\nThe gateway calls the Azure OpenAI deployment.\n", encoding="utf-8")
    world["summary"].write_text(f"sha {world['sha']}\nnode n4 'Azure OpenAI' inside zone z2\n", encoding="utf-8")
    ok = review_run.run_review(_args(world, "grok", dry_run=str(world["tmp"] / "dry2")))
    manifest = json.loads((Path(ok["out"]) / "request_manifest.json").read_text(encoding="utf-8"))
    assert manifest["blinding"]["fixture_vocabulary_exempt"] == ["openai"]
    world["summary"].write_text(f"sha {world['sha']}\nnode n4 'Azure OpenAI'; drafted by gpt-6-luna\n", encoding="utf-8")
    with pytest.raises(review_run.ReviewError, match="gpt-6-luna"):
        review_run.run_review(_args(world, "grok", dry_run=str(out)))
    world["summary"].write_text("checks: 12 run\n", encoding="utf-8")
    with pytest.raises(review_run.ReviewError, match="does not state the reviewed SVG's SHA-256"):
        review_run.run_review(_args(world, "sonnet", dry_run=str(out)))
    world["summary"].write_text(json.dumps({"svg_sha256": "f" * 64, "note": world["sha"]}), encoding="utf-8")
    with pytest.raises(review_run.ReviewError, match="is not the reviewed SVG's hash"):
        review_run.run_review(_args(world, "sonnet", dry_run=str(out)))


# --- order, serial, ceilings -------------------------------------------------------------------------------------------------------
def test_fixed_order_serial_and_final_reuse(world):
    led = _ledger(world)
    with pytest.raises(review_run.ReviewError, match="next is sonnet, not grok"):
        review_run.check_order(led.records(), common.find_run(common.run_plan(world["evidence"]), RUN_ID), "initial", "grok", "normal", world["sha"])
    run = common.find_run(common.run_plan(world["evidence"]), RUN_ID)
    led.append({"event": "reviewer_reserved", "run_id": RUN_ID, "phase": "initial", "kind": "normal", "call_id": "RV001", "svg_sha256": world["sha"]})
    with pytest.raises(review_run.ReviewError, match="still open"):
        review_run.check_order(led.records(), run, "initial", "grok", "normal", world["sha"])
    led.append({"event": "end", "actor": "reviewer", "call_id": "RV001"})
    review_run.check_order(led.records(), run, "initial", "grok", "normal", world["sha"])
    with pytest.raises(review_run.ReviewError, match="same locked SVG"):
        review_run.check_order(led.records(), run, "initial", "grok", "normal", "e" * 64)
    led.append({"event": "reviewer_reserved", "run_id": RUN_ID, "phase": "initial", "kind": "normal", "call_id": "RV002", "svg_sha256": world["sha"]})
    led.append({"event": "failure", "actor": "reviewer", "call_id": "RV002"})
    with pytest.raises(review_run.ReviewError, match="already has its 2 review"):
        review_run.check_order(led.records(), run, "initial", "sonnet", "normal", world["sha"])
    with pytest.raises(review_run.ReviewError, match="reuse the existing judgments"):
        review_run.check_order(led.records(), run, "final", "sonnet", "normal", world["sha"])
    review_run.check_order(led.records(), run, "final", "sonnet", "normal", "c" * 64)
    with pytest.raises(review_run.ReviewError, match="next is sonnet"):
        review_run.check_order(led.records(), run, "final", "grok", "normal", "c" * 64)
    with pytest.raises(review_run.ReviewError, match="must target an artifact that already had its normal review"):
        review_run.check_order(led.records(), run, "final", "grok", "diagnostic", "c" * 64)
    review_run.check_order(led.records(), run, "initial", "grok", "diagnostic", world["sha"])
    full = led.records() + [{"event": "reviewer_reserved", "kind": "normal", "call_id": f"X{n}"} for n in range(110)]
    full += [{"event": "end", "actor": "reviewer", "call_id": f"X{n}"} for n in range(110)]
    with pytest.raises(ledger_mod.LedgerError, match="ceiling"):
        review_run.check_order(full, run, "final", "sonnet", "normal", "c" * 64)


# --- Grok through the stub server -------------------------------------------------------------------------------------------------
def test_grok_call_reserves_settles_and_never_leaks_the_key(world, monkeypatch):
    led = _ledger(world)
    led.append({"event": "reviewer_reserved", "run_id": RUN_ID, "phase": "initial", "kind": "normal", "call_id": "RV001", "svg_sha256": world["sha"]})
    led.append({"event": "end", "actor": "reviewer", "call_id": "RV001"})
    with support.StubOpenRouter(_grok_reply(json.dumps(support.valid_review(world["sha"])))) as server:
        monkeypatch.setenv("EXP_OPENROUTER_BASE_URL", server.base)
        result = review_run.run_review(_args(world, "grok"))
    assert result["status"] == "valid" and result["review_id"] == "RV002"
    assert len(server.requests) == 1
    request = server.requests[0]
    assert request["path"] == "/api/v1/responses" and request["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"
    body = request["body"]
    assert body["model"] == "x-ai/grok-4.6" and body["reasoning"] == {"effort": "medium"} and body["store"] is False
    assert body["max_output_tokens"] == 32000 and body["provider"] == {"sort": "throughput"}
    reserved = [r for r in led.records() if r["event"] == "cash_reserved"]
    settled = [r for r in led.records() if r["event"] == "cash_settled"]
    assert len(reserved) == 1 and Decimal(reserved[0]["usd"]) > Decimal("0.24")
    assert settled[0]["usd"] == "0.0123" and settled[0]["source"].startswith("billed-reported")
    out = Path(result["out"])
    assert json.loads((out / "review.json").read_text(encoding="utf-8"))["verdict"] == "repair"
    assert "private musing" not in (out / "response_body.json").read_text(encoding="utf-8")
    end = [r for r in led.records() if r["event"] == "end" and r.get("call_id") == "RV002"][0]
    assert end["metrics"]["money"]["api_cash_usd"] == 0.0123 and end["metrics"]["money"]["subscription_notional_usd"] is None
    assert end["metrics"]["usage"]["reasoning_tokens"] == 600
    for path in world["evidence"].rglob("*"):
        if path.is_file():
            assert FAKE_KEY not in path.read_text(encoding="utf-8", errors="replace"), path
    assert led.verify()["ok"]


def test_grok_malformed_is_recorded_not_retried_and_mismatch_quarantines(world, monkeypatch):
    led = _ledger(world)
    for n, reply in enumerate((_grok_reply("The slide looks fine overall."), _grok_reply(json.dumps(support.valid_review(world["sha"])), model="x-ai/grok-4.7"))):
        led.append({"event": "reviewer_reserved", "run_id": RUN_ID, "phase": "initial", "kind": "normal", "call_id": f"S{n}", "svg_sha256": world["sha"]})
        led.append({"event": "end", "actor": "reviewer", "call_id": f"S{n}"})
        with support.StubOpenRouter(reply) as server:
            monkeypatch.setenv("EXP_OPENROUTER_BASE_URL", server.base)
            result = review_run.run_review(_args(world, "grok", kind="diagnostic") if n else _args(world, "grok"))
        assert len(server.requests) == 1  # one request, no retry
        if n == 0:
            assert result["status"] == "malformed"
            validation = json.loads((Path(result["out"]) / "validation.json").read_text(encoding="utf-8"))
            assert validation["status"] == "malformed" and not (Path(result["out"]) / "review.json").exists()
        else:
            assert result["status"] == "quarantined"
            assert any(r["event"] == "quarantined" and r["call_id"] == result["review_id"] for r in led.records())
    assert ledger_mod.reviewer_counts(led.records()) == {"total": 4, "diagnostic": 1, "normal": 3}


def test_grok_http_error_settles_and_consumes_the_slot(world, monkeypatch):
    led = _ledger(world)
    led.append({"event": "reviewer_reserved", "run_id": RUN_ID, "phase": "initial", "kind": "normal", "call_id": "RV001", "svg_sha256": world["sha"]})
    led.append({"event": "end", "actor": "reviewer", "call_id": "RV001"})
    with support.StubOpenRouter({"error": {"message": "provider unavailable"}}, status=503) as server:
        monkeypatch.setenv("EXP_OPENROUTER_BASE_URL", server.base)
        result = review_run.run_review(_args(world, "grok"))
    assert result["status"] == "failed" and result["failure"]["status"] == 503
    settled = [r for r in led.records() if r["event"] == "cash_settled"][0]
    reserved = [r for r in led.records() if r["event"] == "cash_reserved"][0]
    assert settled["usd"] == reserved["usd"] and settled["source"].startswith("unknown-outcome")
    assert ledger_mod.open_reviewer_calls(led.records()) == []


def test_openrouter_base_must_be_https_or_local(monkeypatch):
    monkeypatch.setenv("EXP_OPENROUTER_BASE_URL", "http://example.com/api/v1")
    with pytest.raises(review_run.ReviewError, match="https"):
        review_run.openrouter_base()


# --- Sonnet through the stub CLI --------------------------------------------------------------------------------------------------
def test_sonnet_review_through_the_subscription_cli(world, monkeypatch):
    _sonnet_stub(world, monkeypatch, json.dumps(support.valid_review(world["sha"])))
    result = review_run.run_review(_args(world, "sonnet"))
    assert result["status"] == "valid" and result["review_id"] == "RV001"
    calls = [json.loads(line) for line in (world["tmp"] / "argv.jsonl").read_text(encoding="utf-8").splitlines()]
    review_call = [c for c in calls if "-p" in c][0]
    assert review_call[review_call.index("--model") + 1] == "claude-sonnet-5-5"
    assert review_call[review_call.index("--effort") + 1] == "high" and review_call[review_call.index("--max-turns") + 1] == "1"
    assert review_call[review_call.index("--tools") + 1] == ""
    metrics = json.loads((Path(result["out"]) / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["single_request"] is True and metrics["identity"]["verified"] is True
    assert metrics["money"]["subscription_notional_usd"] == 0.0421 and metrics["money"]["api_cash_usd"] == 0.0
    assert not [r for r in _ledger(world).records() if r["event"].startswith("cash_")]
    # the next reviewer in the fixed order is grok; a second sonnet is refused
    with pytest.raises(review_run.ReviewError, match="next is grok"):
        review_run.run_review(_args(world, "sonnet"))


def test_sonnet_model_mismatch_quarantines(world, monkeypatch):
    _sonnet_stub(world, monkeypatch, json.dumps(support.valid_review(world["sha"])), model="claude-haiku-5")
    result = review_run.run_review(_args(world, "sonnet"))
    assert result["status"] == "quarantined"
    metrics = json.loads((Path(result["out"]) / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["quarantined"] is True and metrics["money"]["subscription_notional_usd"] == 0.0421  # cost kept


def test_sonnet_auth_refusal_consumes_no_slot(world, monkeypatch):
    _sonnet_stub(world, monkeypatch, "{}")
    monkeypatch.setenv("STUB_AUTH_METHOD", "apiKey")  # key billing: refused before any reservation
    with pytest.raises(review_run.ReviewError, match="not on the claude.ai subscription"):
        review_run.run_review(_args(world, "sonnet"))
    assert _ledger(world).records() == []
    assert not (world["evidence"] / "reviews").exists()
