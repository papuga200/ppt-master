"""EXPERIMENT-ONLY (svg-helpers-experiment-20260930): ledger immutability, reviewer/cash accounting, metrics export, pass counter.
No model call, no network."""

import csv
import json
from decimal import Decimal

import pytest

import test_exp_harness_support  # noqa: F401  (puts the harness on sys.path)

import ledger as ledger_mod  # noqa: E402
import pass_counter  # noqa: E402


def test_chain_verifies_and_detects_tampering(tmp_path):
    path = tmp_path / "ledger.jsonl"
    path.write_text('{"at": "2026-09-29T16:26:05Z", "event": "experiment_created"}\n', encoding="utf-8")  # legacy, unchained
    led = ledger_mod.Ledger(path)
    first = led.append({"event": "dispatch", "actor": "creator", "run_id": "A-luna-timeline"})
    led.append({"event": "end", "actor": "creator", "run_id": "A-luna-timeline", "status": "completed"})
    assert first["seq"] == 1 and first["prefix_sha256"]
    assert led.verify() == {"ok": True, "chained": 2, "legacy": 1, "errors": [], "warnings": []}

    original = path.read_bytes()
    path.write_bytes(original.replace(b'"status":"completed"', b'"status":"accepted!"'))  # the newest line, edited
    result = led.verify()
    assert result["ok"] is False and [e["error"] for e in result["errors"]] == ["record hash mismatch: this record was changed"]
    path.write_bytes(original.replace(b'"actor":"creator"', b'"actor":"reviewer"', 1))  # an earlier line, edited
    result = led.verify()
    assert result["ok"] is False and any("prefix hash mismatch" in e["error"] for e in result["errors"])

    path.write_bytes(original)
    lines = original.splitlines(keepends=True)
    path.write_bytes(lines[0] + lines[2])  # a removed record
    assert led.verify()["ok"] is False


def test_no_rewrite_api_and_cli_rules(tmp_path):
    led = ledger_mod.Ledger(tmp_path / "l.jsonl")
    assert not any(hasattr(led, name) for name in ("delete", "update", "rewrite", "truncate", "remove"))
    with pytest.raises(ledger_mod.LedgerError):
        led.append({"note": "no event type"})
    args = ["--ledger", str(tmp_path / "l.jsonl"), "append"]
    with pytest.raises(SystemExit, match="decision needs status"):
        ledger_mod.main(args + ["--event", "decision", "--run-id", "A-luna-timeline", "--data", '{"status": "great"}'])
    with pytest.raises(SystemExit, match="corrects_seq"):
        ledger_mod.main(args + ["--event", "correction", "--data", '{"note": "typo"}'])
    with pytest.raises(SystemExit, match="only by review_run"):
        ledger_mod.main(args + ["--event", "cash_settled", "--data", '{"reservation_id": "RV001", "usd": "0"}'])
    assert ledger_mod.main(args + ["--event", "decision", "--run-id", "A-luna-timeline", "--data", '{"status": "technical-failure"}']) == 0
    assert ledger_mod.main(args + ["--event", "correction", "--data", '{"corrects_seq": 1, "note": "reason clarified"}']) == 0
    records = led.records()
    assert [r["event"] for r in records] == ["decision", "correction"] and records[0]["status"] == "technical-failure"


def test_reviewer_ceilings_and_serial_state():
    records = [{"event": "reviewer_reserved", "kind": "normal", "call_id": f"RV{n:03d}"} for n in range(104)]
    records += [{"event": "end", "actor": "reviewer", "call_id": f"RV{n:03d}"} for n in range(104)]
    with pytest.raises(ledger_mod.LedgerError, match="normal reviewer-call ceiling"):
        ledger_mod.check_reviewer_ceiling(records, "normal")
    ledger_mod.check_reviewer_ceiling(records, "diagnostic")
    records += [{"event": "reviewer_reserved", "kind": "diagnostic", "call_id": f"DX{n}"} for n in range(8)]
    with pytest.raises(ledger_mod.LedgerError, match="reviewer-call ceiling reached: 112"):
        ledger_mod.check_reviewer_ceiling(records, "diagnostic")
    assert ledger_mod.reviewer_counts(records) == {"total": 112, "diagnostic": 8, "normal": 104}
    assert ledger_mod.open_reviewer_calls(records) == [f"DX{n}" for n in range(8)]


def test_cash_state_counts_open_reservations_in_full():
    records = [{"event": "cash_reserved", "reservation_id": "RV002", "usd": "0.300000"},
               {"event": "cash_settled", "reservation_id": "RV002", "usd": "0.0123"},
               {"event": "cash_reserved", "reservation_id": "RV004", "usd": "0.250000"}]
    state = ledger_mod.cash_state(records)
    assert state == {"settled_usd": Decimal("0.0123"), "open_reserved_usd": Decimal("0.250000"), "committed_usd": Decimal("0.2623")}


def test_metrics_export_keeps_money_buckets_apart(tmp_path):
    led = ledger_mod.Ledger(tmp_path / "l.jsonl")
    led.append({"event": "end", "actor": "creator", "run_id": "A-luna-timeline", "stage": "draft", "status": "completed",
                "metrics": {"usage": {"input_tokens": 1000, "output_tokens": 50, "reasoning_tokens": None},
                            "money": {"api_cash_usd": 0.0, "subscription_notional_usd": 0.42, "infra_usd": None},
                            "timestamps": {"first_content_svg_write": "2026-09-30T10:00:00Z"}}})
    led.append({"event": "end", "actor": "reviewer", "run_id": "A-luna-timeline", "stage": "initial", "call_id": "RV002",
                "metrics": {"money": {"api_cash_usd": 0.0123, "api_cash_source": "billed-reported", "subscription_notional_usd": None}}})
    led.append({"event": "infra", "actor": "orchestrator", "money": {"infra_usd": None}})
    ledger_mod.export_metrics(led, tmp_path / "metrics.csv")
    rows = list(csv.DictReader((tmp_path / "metrics.csv").open(encoding="utf-8")))
    assert len(rows) == 3
    assert rows[0]["subscription_notional_usd"] == "0.42" and rows[0]["api_cash_usd"] == "0.0" and rows[0]["reasoning_tokens"] == ""
    assert rows[0]["first_content_svg_write_at"] == "2026-09-30T10:00:00Z"
    assert rows[1]["api_cash_usd"] == "0.0123" and rows[1]["subscription_notional_usd"] == ""
    summary = ledger_mod.summary(led)
    assert summary["money_separate_buckets"] == {"api_cash_usd": 0.0123, "subscription_notional_usd": 0.42, "infra_usd": 0.0}
    assert summary["money_unknown_counts"]["infra_usd"] == 2  # unknown stays unknown, not zero


def test_pass_counter_limits(tmp_path, capsys):
    state = tmp_path / "check_passes.json"
    pass_counter.init_state(state, "A-luna-timeline")
    with pytest.raises(Exception, match="already exists"):
        pass_counter.init_state(state, "A-luna-timeline")
    with pytest.raises(Exception, match="not the active stage"):
        pass_counter.claim(state)  # no stage started yet
    pass_counter.set_stage(state, "draft")
    assert [pass_counter.claim(state, svg_sha256=f"h{n}")["granted"] for n in range(3)] == [True, True, True]
    assert pass_counter.main(["claim", "--state", str(state)]) == 3  # the fourth is refused, and recorded
    assert json.loads(capsys.readouterr().out)["remaining"] == 0
    with pytest.raises(Exception, match="not the active stage"):
        pass_counter.claim(state, stage="repair")
    pass_counter.set_stage(state, "repair")
    assert [pass_counter.claim(state)["granted"] for _ in range(3)] == [True, True, False]
    saved = json.loads(state.read_text(encoding="utf-8"))
    assert pass_counter.granted_count(saved, "draft") == 3 and len(saved["stages"]["draft"]["claims"]) == 4
    assert pass_counter.granted_count(saved, "repair") == 2
