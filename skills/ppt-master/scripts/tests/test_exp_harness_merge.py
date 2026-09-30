"""EXPERIMENT-ONLY (svg-helpers-experiment-20260930): the deterministic two-review merge (merge_findings.py). No model call."""

import json

import pytest

import test_exp_harness_support as support

import merge_findings  # noqa: E402

SHA = "d" * 64


def _finding(fid, req, elements, evidence, change="Fix it locally.", severity="blocker"):
    return {"id": fid, "requirement_id": req, "element_ids": elements, "evidence": evidence, "severity": severity,
            "certainty": "certain", "suggested_change": change}


def _review(name, blockers=(), advisories=(), verdict=None, scores=2, usable=True):
    body = support.valid_review(SHA, verdict or ("repair" if blockers else "pass"), list(blockers))
    body["advisories"] = list(advisories)
    for key in body["scores"]:
        body["scores"][key] = {"score": scores, "evidence": f"{name} evidence"}
    return {"name": name, "source": f"{name}.json", "validation_status": "valid" if usable else "malformed",
            "review": body if usable else None, "usable": usable}


INSPECTION = {"status": "ok", "checks": [
    {"check_id": "OVL1", "check": "overlap", "targets": ["#t2", "b2"], "status": "passed"},
    {"check_id": "TF3", "check": "type_floor", "targets": ["t9"], "status": "failed", "message": "11.2 px < 13.333 px"},
    {"check_id": "FIT2", "check": "text_fit", "targets": ["t5:line2"], "status": "unverified"},
    {"check_id": "OVL2", "check": "overlap", "targets": ["t4"], "status": "waived"},
]}


def test_merge_dispositions_and_provenance():
    sonnet = _review("sonnet", blockers=[
        _finding("B1", "R-labels", ["b2"], "Bar b2 has no task name."),
        _finding("B2", "R-read", ["t2"], "Label t2 overlaps bar b2 and is hard to read."),
        _finding("B3", "R-dep", ["d1"], "Dependency d1 points to the wrong target (Pilot instead of Build)."),
        _finding("B4", "R-fit", ["t5"], "Text t5 overflows its box."),
    ])
    grok = _review("grok", blockers=[_finding("G1", "R-labels", ["b2", "b3"], "Bars b2 and b3 lack names.")],
                   advisories=[_finding("G2", "R-dep", ["d1"], "d1 could be clearer.", severity="minor")])
    packet = merge_findings.merge([sonnet, grok], INSPECTION)
    by_req = {m["requirement_id"]: m for m in packet["items"] if m["requirement_id"]}

    labels = by_req["R-labels"]  # duplicate across reviewers, merged, both sources kept
    assert labels["disposition"] == "agreed_blocker" and labels["element_ids"] == ["b2", "b3"]
    assert sorted((s["reviewer"], s["id"]) for s in labels["sources"]) == [("grok", "G1"), ("sonnet", "B1")]

    dep = by_req["R-dep"]  # blocker vs advisory: contested, both positions visible
    assert dep["disposition"] == "contested" and dep["blocker_by"] == ["sonnet"] and dep["advisory_by"] == ["grok"]
    assert dep["deterministic"] is None  # a semantic claim is never judged by geometry

    overlap = by_req["R-read"]  # a geometric claim contradicted by a passed overlap check on the same element
    assert overlap["disposition"] == "overridden_by_deterministic" and overlap["deterministic"]["result"] == "contradicts"

    fit = by_req["R-fit"]  # only an unverified check covers t5: no override, stays a single-source blocker
    assert fit["disposition"] == "single_source_blocker" and fit["deterministic"]["result"] == "not_covered"

    added = [m for m in packet["items"] if m["disposition"] == "deterministic_blocker"]
    assert [m["element_ids"] for m in added] == [["t9"]] and added[0]["geometric_class"] == "type_size"

    assert packet["decision_hint"] == "repair"
    assert packet["counts"]["agreed_blocker"] == 1 and packet["counts"]["overridden_by_deterministic"] == 1
    assert [m["id"] for m in packet["items"]] == [f"M{n:02d}" for n in range(1, len(packet["items"]) + 1)]
    assert packet["scores_side_by_side"]["readability"]["by_reviewer"] == {"grok": 2, "sonnet": 2}


def test_semantic_words_block_a_geometric_override():
    claim = _finding("B1", "R-x", ["t2"], "Label t2 overlaps the bar, and it is missing the milestone date.")
    assert merge_findings.classify_geometric(claim) is None
    assert merge_findings.classify_geometric(_finding("B2", "R-x", ["t2"], "The border of t2 overlaps b2")) == "overlap"
    assert merge_findings.classify_geometric(_finding("B3", "R-x", ["t2"], "Caption set at 9 pt, too small")) == "type_size"
    assert merge_findings.classify_geometric(_finding("B4", "R-x", ["t2"], "Label t2 overlaps and overflows its box")) is None  # mixed


def test_disagreeing_verdicts_and_malformed_reviews_block_an_unconditional_pass():
    assert merge_findings.merge([_review("sonnet"), _review("grok")], None)["decision_hint"] == "pass"
    bad = merge_findings.merge([_review("sonnet"), _review("grok", usable=False)], None)
    assert bad["decision_hint"] == "no_unconditional_pass" and bad["missing_or_malformed_reviews"] == ["grok"]
    split = merge_findings.merge([_review("sonnet"), _review("grok", verdict="insufficient_evidence")], None)
    assert split["decision_hint"] == "no_unconditional_pass"
    scores = merge_findings.merge([_review("sonnet", scores=3), _review("grok", scores=1)], None)["scores_side_by_side"]
    assert scores["semantic_clarity"]["spread"] == 2 and "mean" not in json.dumps(scores)


def test_cli_output_is_deterministic_and_creator_packet_is_blinded(tmp_path):
    folders = {}
    for name, review in (("sonnet", _review("sonnet", blockers=[_finding("B1", "R-labels", ["b2"], "Bar b2 has no task name.")])),
                         ("grok", _review("grok", blockers=[_finding("G1", "R-labels", ["b2"], "b2 unnamed.")]))):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "review.json").write_text(json.dumps(review["review"]), encoding="utf-8")
        (folder / "validation.json").write_text(json.dumps({"status": "valid"}), encoding="utf-8")
        folders[name] = folder
    inspection = tmp_path / "inspection.json"
    inspection.write_text(json.dumps(INSPECTION), encoding="utf-8")
    outputs = []
    for run in ("a", "b"):
        args = ["--review", f"sonnet={folders['sonnet']}", "--review", f"grok={folders['grok']}", "--inspection", str(inspection),
                "--out-json", str(tmp_path / f"{run}.json"), "--out-md", str(tmp_path / f"{run}.md")]
        assert merge_findings.main(args) == 0
        outputs.append(((tmp_path / f"{run}.json").read_bytes(), (tmp_path / f"{run}.md").read_text(encoding="utf-8")))
    assert outputs[0] == outputs[1]
    markdown = outputs[0][1]
    assert "review A" in markdown and "review B" in markdown
    assert "sonnet" not in markdown.lower() and "grok" not in markdown.lower()
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        merge_findings.main(args)
