"""EXPERIMENT-ONLY (svg-helpers-experiment-20260930): the opt-in host guards and telemetry added for the experiment.

host.py: PPT_MASTER_SCRIPT_ALLOWLIST (refusal + log; unset = unchanged behaviour), PPT_MASTER_READ_ROOTS / PPT_MASTER_WRITE_ROOTS.
tools_mcp.py: PPT_MASTER_SVG_SNAPSHOT_DIR snapshots of SVG writes. cli_host.py: --answer-file takes the resume path.
The host module is pointed at a temp checkout; no model call, no network.
"""

import importlib.util
import json
import sys

import pytest

import test_exp_harness_support as support

HOSTS = support.WORKTREE / "hosts" / "responses_api"


def _load(name):
    if str(HOSTS) not in sys.path:
        sys.path.insert(0, str(HOSTS))
    spec = importlib.util.spec_from_file_location(f"exp_guard_{name}", HOSTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def host(tmp_path, monkeypatch):
    for name in ("PPT_MASTER_SCRIPT_ALLOWLIST", "PPT_MASTER_READ_ROOTS", "PPT_MASTER_WRITE_ROOTS", "PPT_MASTER_GUARD_LOG", "PPT_MASTER_SVG_SNAPSHOT_DIR"):
        monkeypatch.delenv(name, raising=False)
    module = _load("host")
    root = tmp_path / "checkout"
    scripts = root / "skills" / "ppt-master" / "scripts"
    (scripts / "exp_svg" / "timeline").mkdir(parents=True)
    (scripts / "allowed.py").write_text("print('allowed ran')\n", encoding="utf-8")
    (scripts / "other.py").write_text("print('other ran')\n", encoding="utf-8")
    (scripts / "exp_svg" / "timeline" / "build.py").write_text("import sys; print('build', sys.argv[1:])\n", encoding="utf-8")
    (root / "projects" / "w1" / "work").mkdir(parents=True)
    (root / "projects" / "w1" / "svg_output").mkdir()
    (root / "projects" / "w1" / "brief.md").write_text("brief", encoding="utf-8")
    (root / "projects" / "other").mkdir(parents=True)
    (root / "projects" / "other" / "secret.md").write_text("another run's output", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "SCRIPTS", scripts)
    monkeypatch.setattr(module, "_env_for_scripts", lambda: {**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    return module


def test_allowlist_unset_keeps_current_behaviour(host):
    assert "other ran" in host.tool_run_script("other.py")
    assert "allowed ran" in host.tool_run_script("skills/ppt-master/scripts/allowed.py")


def test_allowlist_refuses_and_logs(host, tmp_path, monkeypatch):
    log = tmp_path / "guard.jsonl"
    monkeypatch.setenv("PPT_MASTER_SCRIPT_ALLOWLIST", "allowed.py;exp_svg/timeline/build.py")
    monkeypatch.setenv("PPT_MASTER_GUARD_LOG", str(log))
    assert "allowed ran" in host.tool_run_script("allowed.py")
    assert "build" in host.tool_run_script("skills/ppt-master/scripts/exp_svg/timeline/build.py", ["x"])
    with pytest.raises(ValueError, match=r"`other.py` is not on this session's script allowlist; allowed: allowed.py, exp_svg/timeline/build.py"):
        host.tool_run_script("other.py")
    with pytest.raises(ValueError, match="not on this session's script allowlist"):
        host.tool_run_script("exp_svg/timeline/../../other.py")  # a traversal resolves to the real script name first
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [r["script"] for r in records] == ["other.py", "other.py"]
    assert all(r["guard"] == "PPT_MASTER_SCRIPT_ALLOWLIST" and r["event"] == "refused" for r in records)


def test_allowlist_set_but_empty_refuses_everything(host, monkeypatch):
    monkeypatch.setenv("PPT_MASTER_SCRIPT_ALLOWLIST", "")
    with pytest.raises(ValueError, match=r"allowed: \(none\)"):
        host.tool_run_script("allowed.py")


def test_workspace_roots(host, monkeypatch):
    monkeypatch.setenv("PPT_MASTER_READ_ROOTS", "projects/w1")
    monkeypatch.setenv("PPT_MASTER_WRITE_ROOTS", "projects/w1/svg_output;projects/w1/work")
    assert host.tool_read_file("projects/w1/brief.md") == "brief"
    for call in (lambda: host.tool_read_file("projects/other/secret.md"), lambda: host.tool_list_dir("projects"),
                 lambda: host.tool_list_dir("."), lambda: host.tool_write_file("projects/w1/brief.md", "x"),
                 lambda: host.tool_edit_file("projects/w1/brief.md", "brief", "x"),
                 lambda: host.tool_run_script("allowed.py", ["projects/other/secret.md"]),
                 lambda: host.tool_run_script("allowed.py", ["--in=projects/other/secret.md"])):
        with pytest.raises(ValueError, match="outside this session's workspace"):
            call()
    assert "wrote" in host.tool_write_file("projects/w1/work/scene.json", "{}")
    assert "allowed ran" in host.tool_run_script("allowed.py", ["--out", "projects/w1/work/r.json", "--flag"])
    assert (host.ROOT / "projects" / "w1" / "brief.md").read_text(encoding="utf-8") == "brief"


def test_svg_write_snapshots(host, tmp_path, monkeypatch):
    tools_mcp = _load("tools_mcp")
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("PPT_MASTER_SVG_SNAPSHOT_DIR", str(snaps))
    page = "projects/w1/svg_output/slide.svg"
    result, _ = tools_mcp.call_tool(host, "write_file", {"path": page, "content": "<svg/>"})
    assert not result["isError"]
    tools_mcp.call_tool(host, "edit_file", {"path": page, "old": "<svg/>", "new": "<svg><rect/></svg>"})
    tools_mcp.call_tool(host, "write_file", {"path": "projects/w1/work/scene.json", "content": "{}"})  # not an SVG: no snapshot
    tools_mcp.call_tool(host, "edit_file", {"path": page, "old": "absent", "new": "x"})  # failed edit: no snapshot
    rows = [json.loads(line) for line in (snaps / "snapshots.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["seq"], r["tool"]) for r in rows] == [(1, "write_file"), (2, "edit_file")]
    assert (snaps / rows[1]["copy"]).read_text(encoding="utf-8") == "<svg><rect/></svg>"
    assert rows[0]["path"] == page


def test_cli_host_answer_file_takes_the_resume_path(tmp_path, monkeypatch):
    cli_host = _load("cli_host")
    monkeypatch.setenv("PPT_MASTER_API_BASE", "cli:claude")
    monkeypatch.setattr(cli_host.host, "OUT", tmp_path)
    answer = tmp_path / "answer.md"
    answer.write_text("x" * 50000, encoding="utf-8")  # longer than a Windows command line allows
    with pytest.raises(SystemExit, match="no session to continue"):
        cli_host.main(["--session", "s1", "--answer-file", str(answer)])
