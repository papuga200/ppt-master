"""Subscription transport (F01): env scrubbing, CLI stream -> host transcript mapping, the pptm MCP tool server, runner dispatch,
reviewer CLI branch and retries, telemetry and reports. No model calls and no network: every CLI is stubbed or replayed from
short excerpts of real logs (fixtures/subscription_routes/)."""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
from argparse import Namespace
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
ROOT = SCRIPTS.parents[2]
HOSTS = ROOT / "hosts" / "responses_api"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "subscription_routes"
for _p in (str(SCRIPTS), str(HOSTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import subscription_cli as sub  # noqa: E402

# A 1x1 PNG.
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _lines(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _fresh_preflight():
    sub._PREFLIGHT.clear()
    yield
    sub._PREFLIGHT.clear()


# --- environment ---------------------------------------------------------------------------------------------------------

def test_scrub_env_removes_keys_and_claude_plumbing():
    base = {"ANTHROPIC_API_KEY": "x", "ANTHROPIC_BASE_URL": "https://api.anthropic.com", "ANTHROPIC_AUTH_TOKEN": "x", "CLAUDE_CODE_ENTRYPOINT": "desktop",
            "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDECODE": "1", "CLAUDE_AGENT_SDK_VERSION": "1", "CLAUDE_PID": "1", "CLAUDE_EFFORT": "high",
            "MCP_TIMEOUT": "1", "OPENAI_API_KEY": "x", "CODEX_API_KEY": "x", "OPENROUTER_API_KEY": "x", "GEMINI_API_KEY": "x",
            "PPT_MASTER_ENV_FILE": r"D:\secret.env", "PATH": "p", "PPT_MASTER_MODEL": "m", "CODEX_CLI_PATH": "c", "RANDOM_TOOL_SETTING": "r"}
    env = sub.scrub_env(base)
    assert set(env) == {"PATH", "PPT_MASTER_MODEL", "CODEX_CLI_PATH", "RANDOM_TOOL_SETTING", "PYTHONIOENCODING"}
    assert sub.scrub_env({"anthropic_api_key": "x", "Path": "p"}) == {"Path": "p", "PYTHONIOENCODING": "utf-8"}  # Windows names are case-blind
    mcp = sub.mcp_env(base)
    assert set(mcp) == {"PATH", "PPT_MASTER_MODEL", "CODEX_CLI_PATH", "PYTHONIOENCODING"}  # an MCP server gets no stray variables either


def test_backend_of_routes():
    assert sub.backend_of("cli:claude") == "claude" and sub.backend_of(" CLI:Codex ") == "codex"
    assert sub.backend_of("https://api.openai.com/v1") is None and sub.backend_of(None) is None
    with pytest.raises(sub.SubscriptionError):
        sub.backend_of("cli:gemini")


def test_preflight_refuses_anything_but_the_subscription(monkeypatch):
    monkeypatch.setattr(sub, "claude_bin", lambda: "claude")
    monkeypatch.setattr(sub, "codex_bin", lambda: "codex")
    seen_env = {}

    def fake(answer, code=0):
        def run(argv, **kwargs):
            seen_env.update(kwargs["env"])
            return subprocess.CompletedProcess(argv, code, stdout=answer, stderr="")
        return run

    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    ok = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"})
    assert sub.preflight("claude", runner=fake(ok))["authMethod"] == "claude.ai"
    assert "ANTHROPIC_API_KEY" not in seen_env
    sub._PREFLIGHT.clear()
    with pytest.raises(sub.SubscriptionError):
        sub.preflight("claude", runner=fake(json.dumps({"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"})))
    with pytest.raises(sub.SubscriptionError):
        sub.preflight("claude", runner=fake(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"})))
    assert sub.preflight("codex", runner=fake("Logged in using ChatGPT\n"))["login"] == "Logged in using ChatGPT"
    sub._PREFLIGHT.clear()
    with pytest.raises(sub.SubscriptionError):
        sub.preflight("codex", runner=fake("Logged in using an API key - sk-***\n"))
    with pytest.raises(sub.SubscriptionError):
        sub.preflight("codex", runner=fake("Not logged in\n", code=1))


# --- Claude stream -> transcript ----------------------------------------------------------------------------------------

def _claude_session(tmp_path, name):
    import cli_host
    session = cli_host.Session(tmp_path, "claude", "claude-opus-5-5", require_pptm=(name != "claude_stream.jsonl"))  # the 2026-09-28 run had no pptm server
    for event in _lines(name):
        session.on_claude(event)
    return session, _events(tmp_path / "transcript.jsonl")


def test_claude_stream_maps_to_host_transcript(tmp_path):
    session, events = _claude_session(tmp_path, "claude_stream.jsonl")
    init = next(e for e in events if e["event"] == "cli_init")
    assert init["apiKeySource"] == "none" and init["model"] == "claude-opus-5-5"
    turns = [e for e in events if e["event"] == "turn"]
    tools = [e for e in events if e["event"] == "tool"]
    assert len(turns) == len(session.message_ids) == 3  # one turn per API response, however many events it streamed as
    assert [t["turn"] for t in turns] == [0, 1, 2]
    assert all(t["usage"]["input_tokens"] >= t["usage"]["input_tokens_details"]["cached_tokens"] > 0 for t in turns)
    assert tools and tools[0]["name"] == "Bash" and tools[0]["result"]  # the 2026-09-28 run used built-in tools...
    assert any(e["event"] == "warning" and "outside the pptm server" in e["text"] for e in events)  # ...which a cli_host session flags
    assert any(e["event"] == "rate_limit" and e["info"]["isUsingOverage"] is False for e in events)
    usage = sub.claude_usage(session.result, calls=len(session.message_ids))
    assert usage == {**usage, "input_tokens": 122 + 247315 + 9291350, "cached": 9291350, "output_tokens": 97335, "reasoning": 45139, "calls": 3,
                     "cost_source": "subscription-notional-list-price"}
    assert usage["cost_usd"] == pytest.approx(5.783978)


def test_claude_parallel_tool_calls_stay_one_turn_and_images_are_counted(tmp_path):
    session, events = _claude_session(tmp_path, "claude_parallel_tools.jsonl")
    turns = [e for e in events if e["event"] == "turn"]
    tools = [e for e in events if e["event"] == "tool"]
    assert len(turns) == 2 and [c[0] for c in turns[0]["calls"]] == ["read_image", "list_dir", "write_file"]
    assert [t["name"] for t in tools] == ["read_image", "list_dir", "write_file"] and tools[0]["images"] == 1
    assert session.images == 1 and session.image_paths[0].endswith("kiwi.png")
    assert not any(e["event"] == "warning" for e in events)  # only pptm tools, only the asked model


def test_claude_init_on_a_key_or_without_the_tool_server_is_refused(tmp_path):
    import cli_host
    session = cli_host.Session(tmp_path, "claude", "claude-opus-5-5")
    base = {"type": "system", "subtype": "init", "tools": ["mcp__pptm__read_file"], "mcp_servers": [{"name": "pptm", "status": "connected"}]}
    with pytest.raises(sub.SubscriptionError):
        session.on_claude({**base, "apiKeySource": "ANTHROPIC_API_KEY"})
    with pytest.raises(sub.SubscriptionError):
        session.on_claude({**base, "apiKeySource": "none", "mcp_servers": []})
    session.on_claude({**base, "apiKeySource": "none"})
    assert session.init is not None


# --- Codex stream + rollout -> transcript -----------------------------------------------------------------------------

def test_codex_stream_and_rollout_map_to_host_transcript(tmp_path, monkeypatch):
    import cli_host
    home = tmp_path / "codex_home"
    rollout = next(FIXTURES.glob("rollout-*.jsonl"))
    (home / "sessions" / "2026" / "09" / "28").mkdir(parents=True)
    (home / "sessions" / "2026" / "09" / "28" / rollout.name).write_text(rollout.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    session_dir = tmp_path / "s"
    session_dir.mkdir()
    session = cli_host.Session(session_dir, "codex", "gpt-6-sol")
    for event in _lines("codex_stream.jsonl"):
        session.on_codex(event)
    assert session.thread_id == "01a0e864-d0ed-7cd2-b2c1-e2ad30a38267"
    assert session.codex_usage["input_tokens"] == 24568095 and session.tool_calls >= 2
    assert "command_execution" in session.unexpected_tools  # that run had a shell; a cli_host session flags one
    path, calls = session.codex_turns(since=0)
    assert path and len(calls) == 3
    events = _events(session_dir / "transcript.jsonl")
    turns = [e for e in events if e["event"] == "turn"]
    assert [t["usage"]["input_tokens"] for t in turns] == [c["usage"]["input_tokens"] for c in calls]
    assert turns[1]["usage"]["input_tokens_details"]["cached_tokens"] == calls[1]["usage"]["cached_input_tokens"]
    assert session.rate_limit["plan_type"] == "prolite" and session.rate_limit["primary"]["window_minutes"] == 10080
    mcp = [e for e in events if e["event"] == "tool" and e.get("server") == "codebase-memory-mcp"]
    assert mcp and mcp[0]["name"] == "index_status"
    usage = sub.codex_usage({k: sum(c["usage"].get(k) or 0 for c in calls) for k in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")},
                            "gpt-6-sol", calls=len(calls))
    assert usage["cost_source"] == "subscription-notional-list-price" and usage["cost_usd"] > 0
    assert sub.codex_usage({"input_tokens": 10}, "no-such-model", 1)["cost_source"] == "unknown"


# --- the pptm MCP server ------------------------------------------------------------------------------------------------

@pytest.fixture()
def root_png():
    folder = ROOT / ".host-sessions" / "_test_subscription_routes"
    folder.mkdir(parents=True, exist_ok=True)
    png = folder / "dot.png"
    png.write_bytes(PNG)
    yield png
    import shutil
    shutil.rmtree(folder, ignore_errors=True)


def _rpc(proc, message):
    proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
    proc.stdin.flush()
    if "id" not in message:
        return None
    return json.loads(proc.stdout.readline().decode("utf-8"))


def test_mcp_server_protocol_round_trip(root_png, tmp_path):
    env_file = tmp_path / "mcp_env.json"
    env_file.write_text(json.dumps({"PPT_MASTER_REVIEW_API_BASE": "cli:codex"}), encoding="utf-8")
    log = tmp_path / "tools.jsonl"
    env = {**os.environ, "ANTHROPIC_API_KEY": "must-not-leak", "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.Popen([sys.executable, str(HOSTS / "tools_mcp.py"), "--env-file", str(env_file), "--log", str(log)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(ROOT), env=env)
    try:
        init = _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                                         "clientInfo": {"name": "test", "version": "0"}}})
        assert init["result"]["protocolVersion"] == "2025-06-18" and init["result"]["capabilities"]["tools"] is not None
        assert _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
        assert _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
        tools = _rpc(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
        assert sorted(t["name"] for t in tools) == ["edit_file", "list_dir", "read_file", "read_image", "run_script", "write_file"]
        assert all(t["inputSchema"]["type"] == "object" for t in tools)
        listing = _rpc(proc, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "list_dir", "arguments": {"path": "hosts/responses_api/planner_examples"}}})
        assert "story_calibration.md" in listing["result"]["content"][0]["text"] and listing["result"]["isError"] is False
        doc = _rpc(proc, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "skills/ppt-master/SKILL.md", "end": 3}}})
        assert doc["result"]["content"][0]["text"].strip()
        nested = next(p for p in (SCRIPTS / "svg_quality").glob("*.py"))
        denied = _rpc(proc, {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": nested.relative_to(ROOT).as_posix()}}})
        assert denied["result"]["content"][0]["text"].startswith("not readable by the author")
        outside = _rpc(proc, {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "read_file", "arguments": {"path": "../outside.txt"}}})
        assert outside["result"]["isError"] is True and "outside the ppt-master checkout" in outside["result"]["content"][0]["text"]
        image = _rpc(proc, {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "read_image", "arguments": {"path": root_png.relative_to(ROOT).as_posix()}}})
        blocks = image["result"]["content"]
        assert [b["type"] for b in blocks] == ["text", "text", "image"] and "is shown below" in blocks[0]["text"]
        assert blocks[2]["mimeType"] == "image/png" and base64.b64decode(blocks[2]["data"]) == PNG
        script = _rpc(proc, {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "run_script", "arguments": {"script": "../../../evil.py"}}})
        assert script["result"]["isError"] is True and "only the skill's own scripts" in script["result"]["content"][0]["text"]
        unknown = _rpc(proc, {"jsonrpc": "2.0", "id": 10, "method": "resources/list"})
        assert unknown["error"]["code"] == -32601
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
    records = _events(log)
    assert [r["name"] for r in records] == ["list_dir", "read_file", "read_file", "read_file", "read_image", "run_script"]
    assert records[4]["images"] and records[3]["error"] is True


def test_mcp_env_is_scrubbed_then_overlaid(tmp_path, monkeypatch):
    import tools_mcp
    env_file = tmp_path / "env.json"
    env_file.write_text(json.dumps({"PPT_MASTER_MODEL": "x", "PPT_MASTER_ENV_FILE": "kept-only-when-listed"}), encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("CLAUDECODE", "1")
    saved = dict(os.environ)
    try:
        tools_mcp._prepare_env(str(env_file))
        assert "OPENAI_API_KEY" not in os.environ and "CLAUDECODE" not in os.environ
        assert os.environ["PPT_MASTER_MODEL"] == "x" and os.environ["PPT_MASTER_ENV_FILE"] == "kept-only-when-listed"
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_run_script_images_come_back_inside_the_tool_result(root_png, monkeypatch):
    import host
    import tools_mcp
    monkeypatch.setitem(host.HANDLERS, "run_script", lambda **kw: (host._attach_printed_images(f"IMAGE: {root_png}\n"), "exit 0 in 0.1s")[1])
    before = list(host.PENDING_IMAGES)
    result, record = tools_mcp.call_tool(host, "run_script", {"script": "page_review.py", "args": ["render"]})
    assert [b["type"] for b in result["content"]] == ["text", "text", "image"] and record["images"] == [str(root_png)]
    assert host.PENDING_IMAGES == before  # the Responses host's next-message queue is untouched
    with host.capture_images() as images:
        host.tool_read_image(root_png.relative_to(ROOT).as_posix())
    assert len(images) == 1 and host.PENDING_IMAGES == before


# --- cli_host main (the CLI replayed) -----------------------------------------------------------------------------------

@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    import cli_host
    import host
    monkeypatch.setattr(host, "OUT", tmp_path)
    system = tmp_path / "system.md"
    system.write_text("SYSTEM BRIEF\n", encoding="utf-8")
    monkeypatch.setattr(host, "SYSTEM_FILE", system)
    monkeypatch.setattr(sub, "preflight", lambda backend, runner=None: {"stub": backend})
    monkeypatch.setattr(sub, "claude_bin", lambda: "claude")
    monkeypatch.setattr(sub, "codex_bin", lambda: "codex")
    monkeypatch.setattr(host, "_write_run_blocks", lambda *a, **k: None)
    monkeypatch.setenv("PPT_MASTER_MODEL", "claude-haiku-4-5")
    monkeypatch.setenv("PPT_MASTER_EFFORT", "low")
    monkeypatch.setenv("PPT_MASTER_TIER", "workhorse")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    calls = []

    def fake_run(stream_name, code=0, stopped=False, extra=None):
        def run(argv, stdin_text, env, stream_log, stderr_log, on_event, ceiling=None):
            calls.append({"argv": argv, "stdin": stdin_text, "env": env})
            events = _lines(stream_name) if stream_name else []
            for event in events + (extra or []):
                on_event(event)
            return code, stopped
        return run

    return cli_host, calls, fake_run, tmp_path


def test_cli_host_claude_session_writes_the_host_files(cli_env, monkeypatch):
    cli_host, calls, fake_run, out = cli_env
    import report
    monkeypatch.setenv("PPT_MASTER_API_BASE", "cli:claude")
    monkeypatch.setattr(cli_host, "run_cli", fake_run("claude_parallel_tools.jsonl"))
    assert cli_host.main(["--session", "s1", "--max-turns", "7", "--task", "do it"]) == 0
    argv, env = calls[0]["argv"], calls[0]["env"]
    assert "--safe-mode" not in argv and argv[argv.index("--tools") + 1] == "" and argv[argv.index("--max-turns") + 1] == "7"
    assert argv[argv.index("--allowedTools") + 1] == "mcp__pptm" and "--session-id" in argv and "--bare" not in argv
    assert "ANTHROPIC_API_KEY" not in env and env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1" and calls[0]["stdin"] == "do it"
    config = json.loads((out / "s1" / "mcp_config.json").read_text(encoding="utf-8"))
    assert config["mcpServers"]["pptm"]["args"][0].endswith("tools_mcp.py")
    assert "SYSTEM BRIEF" in (out / "s1" / "system_prompt.md").read_text(encoding="utf-8")
    assert "mcp__pptm__run_script" in (out / "s1" / "system_prompt.md").read_text(encoding="utf-8")
    state = json.loads((out / "s1" / "state.json").read_text(encoding="utf-8"))
    assert state["model"] == "claude-haiku-4-5" and state["effort"] == "low" and state["backend"] == "cli:claude" and state["tier"] == "workhorse"
    assert state["cli_session_id"] == "4975e1d4-6782-4ed1-8a42-545a07011f2c" and state["usage_total"]["calls"] == 2
    assert state["usage_total"]["cost_source"] == "subscription-notional-list-price" and not state["pending_input"]
    assert (out / "s1" / "last_message.md").read_text(encoding="utf-8").startswith("WORD=KIWI 42")
    r = report.analyse(out / "s1")
    assert (r["calls"], r["tool_calls"], r["images_delivered"], r["finished"]) == (2, 3, 1, True)
    assert r["input_tokens"] == 5623 and r["cost_source"] == "subscription-notional-list-price" and r["backend"] == "cli:claude"
    # --answer resumes the same conversation
    assert cli_host.main(["--session", "s1", "--max-turns", "7", "--answer", "fix it"]) == 0
    argv = calls[1]["argv"]
    assert argv[argv.index("--resume") + 1] == "4975e1d4-6782-4ed1-8a42-545a07011f2c" and "--session-id" not in argv
    assert json.loads((out / "s1" / "state.json").read_text(encoding="utf-8"))["usage_total"]["calls"] == 4


def test_cli_host_claude_ceiling_is_resumable(cli_env, monkeypatch):
    cli_host, calls, fake_run, out = cli_env
    monkeypatch.setenv("PPT_MASTER_API_BASE", "cli:claude")
    stream = [e for e in _lines("claude_parallel_tools.jsonl") if e["type"] != "result"]
    ceiling = {"type": "result", "subtype": "error_max_turns", "is_error": True, "num_turns": 2, "total_cost_usd": 0.01,
               "usage": {"input_tokens": 10, "output_tokens": 5}, "modelUsage": {"claude-haiku-4-5": {}}, "session_id": "4975e1d4-6782-4ed1-8a42-545a07011f2c"}
    monkeypatch.setattr(cli_host, "run_cli", fake_run(None, extra=stream + [ceiling]))
    assert cli_host.main(["--session", "s2", "--max-turns", "2", "--task", "long job"]) == 0
    assert json.loads((out / "s2" / "state.json").read_text(encoding="utf-8"))["pending_input"]
    monkeypatch.setattr(cli_host, "run_cli", fake_run("claude_parallel_tools.jsonl"))
    assert cli_host.main(["--session", "s2", "--max-turns", "2", "--resume-pending"]) == 0
    assert calls[-1]["stdin"] == cli_host.RESUME_NOTE and "--resume" in calls[-1]["argv"]
    assert not json.loads((out / "s2" / "state.json").read_text(encoding="utf-8"))["pending_input"]


def test_cli_host_refuses_on_a_failed_preflight_or_key_billing(cli_env, monkeypatch):
    cli_host, calls, fake_run, out = cli_env
    monkeypatch.setenv("PPT_MASTER_API_BASE", "cli:claude")

    def refuse(backend, runner=None):
        raise sub.SubscriptionError("not on the subscription")
    monkeypatch.setattr(sub, "preflight", refuse)
    assert cli_host.main(["--session", "s3", "--task", "x"]) == 3 and not calls
    monkeypatch.setattr(sub, "preflight", lambda backend, runner=None: {})

    def keyed(argv, stdin_text, env, stream_log, stderr_log, on_event, ceiling=None):
        on_event({"type": "system", "subtype": "init", "apiKeySource": "ANTHROPIC_API_KEY", "mcp_servers": [{"name": "pptm", "status": "connected"}]})
        return 0, False
    monkeypatch.setattr(cli_host, "run_cli", keyed)
    assert cli_host.main(["--session", "s4", "--task", "x"]) == 3
    assert any(e["event"] == "refused" for e in _events(out / "s4" / "transcript.jsonl"))


def test_cli_host_codex_argv_and_resume(cli_env, monkeypatch):
    cli_host, calls, fake_run, out = cli_env
    monkeypatch.setenv("PPT_MASTER_API_BASE", "cli:codex")
    monkeypatch.setenv("PPT_MASTER_MODEL", "gpt-6-luna")
    monkeypatch.setenv("CODEX_HOME", str(out / "no_codex_home"))
    monkeypatch.setattr(cli_host, "run_cli", fake_run("codex_stream.jsonl"))
    assert cli_host.main(["--session", "c1", "--max-turns", "9", "--task", "page job"]) == 0
    argv = calls[0]["argv"]
    joined = " ".join(argv)
    assert argv[:2] == ["codex", "exec"] and argv[-1] == "-" and "--ignore-user-config" in argv and argv[argv.index("-m") + 1] == "gpt-6-luna"
    assert "--disable shell_tool" in joined and 'model_reasoning_effort="low"' in joined and 'approval_policy="never"' in joined
    assert "model_instructions_file=" in joined and 'mcp_servers.pptm.default_tools_approval_mode="approve"' in joined and 'sandbox_mode="read-only"' in joined
    assert "OPENAI_API_KEY" not in calls[0]["env"] and "ANTHROPIC_API_KEY" not in calls[0]["env"]
    env_file = json.loads((out / "c1" / "mcp_env.json").read_text(encoding="utf-8"))
    assert env_file["PPT_MASTER_API_BASE"] == "cli:codex" and "ANTHROPIC_API_KEY" not in env_file
    state = json.loads((out / "c1" / "state.json").read_text(encoding="utf-8"))
    assert state["cli_session_id"] == "01a0e864-d0ed-7cd2-b2c1-e2ad30a38267" and state["backend"] == "cli:codex"
    assert state["usage_total"]["input_tokens"] == 24568095  # no rollout here: the stream's own total
    assert cli_host.main(["--session", "c1", "--max-turns", "9", "--answer", "repair"]) == 0
    argv = calls[1]["argv"]
    assert argv[:3] == ["codex", "exec", "resume"] and argv[-2:] == ["01a0e864-d0ed-7cd2-b2c1-e2ad30a38267", "-"] and "-C" not in argv


FAKE_CODEX = r'''
import json, sys, time
sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "t-1"}), flush=True)
for n in range(10000):
    print(json.dumps({"type": "item.started", "item": {"id": f"i{n}", "type": "mcp_tool_call", "tool": "list_dir", "arguments": {}}}), flush=True)
    time.sleep(0.05)
'''


def test_codex_watchdog_stops_the_cli_at_the_call_ceiling(tmp_path, monkeypatch):
    import cli_host
    monkeypatch.setattr(cli_host, "STOP_GRACE_S", 3)
    fake = tmp_path / "fake_codex.py"
    fake.write_text(FAKE_CODEX, encoding="utf-8")
    session = cli_host.Session(tmp_path, "codex", "gpt-6-luna")
    started = time.time()
    code, stopped = cli_host.run_cli([sys.executable, str(fake)], "go", dict(os.environ), tmp_path / "stream.jsonl", tmp_path / "err.log",
                                     session.on_codex, ceiling=lambda: session.tool_calls >= 3)
    assert stopped and 3 <= session.tool_calls < 50 and time.time() - started < 30
    assert session.thread_id == "t-1"


# --- the reviewer's CLI branch and retries ---------------------------------------------------------------------------

def _payload():
    return {"model": "claude-opus-5-5", "instructions": "REVIEW INSTRUCTIONS", "store": False, "reasoning": {"effort": "high"},
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "SLIDE RECORD"},
                                                   {"type": "input_text", "text": "image: a.png"},
                                                   {"type": "input_image", "image_url": "data:image/png;base64," + base64.b64encode(PNG).decode()},
                                                   {"type": "input_text", "text": "RENDERED SLIDE"}]}]}


def test_review_call_claude_branch(monkeypatch):
    import page_review
    monkeypatch.setenv("PPT_MASTER_REVIEW_API_BASE", "cli:claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setattr(sub, "preflight", lambda backend, runner=None: {})
    monkeypatch.setattr(sub, "claude_bin", lambda: "claude")
    seen = {}

    def run(argv, stdin_text, cwd, env):
        seen.update(argv=argv, stdin=json.loads(stdin_text), env=env, system=Path(argv[argv.index("--system-prompt-file") + 1]).read_text(encoding="utf-8"))
        stream = [{"type": "system", "subtype": "init", "apiKeySource": "none", "model": "claude-opus-5-5"},
                  {"type": "assistant", "message": {"id": "m1", "content": [{"type": "text", "text": "ok"}], "usage": {}}},
                  {"type": "result", "subtype": "success", "is_error": False, "result": "VERDICT: PASS\nBLOCKERS: 0", "total_cost_usd": 0.02,
                   "usage": {"input_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 20, "output_tokens": 30,
                             "output_tokens_details": {"thinking_tokens": 12}}, "modelUsage": {"claude-opus-5-5": {}}}]
        return 0, [json.dumps(e) for e in stream], ""
    monkeypatch.setattr(sub, "_run", run)
    text, usage = page_review._review_call(_payload())
    assert text.startswith("VERDICT: PASS")
    assert usage == {**usage, "input_tokens": 125, "cached_tokens": 100, "output_tokens": 30, "reasoning_tokens": 12, "cost": 0.02,
                     "cost_source": "subscription-notional-list-price", "backend": "cli:claude", "attempts": 1}
    argv = seen["argv"]
    for flag in ("--no-session-persistence", "--safe-mode", "--strict-mcp-config"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--max-turns") + 1] == "1" and argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--input-format") + 1] == "stream-json" and "--bare" not in argv
    assert seen["system"] == "REVIEW INSTRUCTIONS" and "ANTHROPIC_API_KEY" not in seen["env"]
    blocks = seen["stdin"]["message"]["content"]
    assert [b["type"] for b in blocks] == ["text", "text", "image", "text"] and blocks[2]["source"]["data"] == base64.b64encode(PNG).decode()


def test_review_call_codex_branch(monkeypatch):
    import page_review
    monkeypatch.setenv("PPT_MASTER_REVIEW_API_BASE", "cli:codex")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setattr(sub, "preflight", lambda backend, runner=None: {})
    monkeypatch.setattr(sub, "codex_bin", lambda: "codex")
    monkeypatch.setenv("CODEX_HOME", str(Path(__file__).resolve().parent / "no-such-codex-home"))
    seen = {}

    def run(argv, stdin_text, cwd, env):
        images = [argv[i + 1] for i, a in enumerate(argv) if a == "--image"]
        seen.update(argv=argv, prompt=stdin_text, env=env, images=[Path(p).read_bytes() for p in images])
        Path(argv[argv.index("-o") + 1]).write_text("VERDICT: EXECUTION_REPAIR\nBLOCKERS: 1", encoding="utf-8")
        stream = [{"type": "thread.started", "thread_id": "t-9"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "x"}},
                  {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 50, "reasoning_output_tokens": 20}}]
        return 0, [json.dumps(e) for e in stream], ""
    monkeypatch.setattr(sub, "_run", run)
    payload = {**_payload(), "model": "gpt-6-sol"}
    text, usage = page_review._review_call(payload)
    assert text.startswith("VERDICT: EXECUTION_REPAIR") and usage["backend"] == "cli:codex" and usage["cost_source"] == "subscription-notional-list-price"
    assert usage["cost"] == pytest.approx(800 * 2e-6 + 200 * 0.2e-6 + 50 * 10e-6)
    argv = seen["argv"]
    assert argv.index("-") < argv.index("--image") and seen["images"] == [PNG]  # `-` first: `-i a.png -` would read `-` as an image
    assert "image 1 = image_01.png" in seen["prompt"] and seen["prompt"].index("SLIDE RECORD") < seen["prompt"].index("[image 1]") < seen["prompt"].index("RENDERED SLIDE")
    assert "OPENAI_API_KEY" not in seen["env"] and 'model_reasoning_effort="high"' in " ".join(argv) and "--ignore-user-config" in argv


def test_review_call_retries_transient_failures_only(monkeypatch):
    import page_review
    sleeps = []
    monkeypatch.setattr(page_review.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setenv("PPT_MASTER_REVIEW_API_BASE", "https://example.invalid/v1")
    outcomes = [urllib.error.URLError("reset"), sub.CliCallError("no result"), ("VERDICT: PASS", {"input_tokens": 1})]

    def once(payload, base):
        item = outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item[0], dict(item[1])
    monkeypatch.setattr(page_review, "_review_call_once", once)
    text, usage = page_review._review_call({"model": "m"})
    assert text == "VERDICT: PASS" and usage["attempts"] == 3 and sleeps == [15, 45] and len(usage["failed_attempts"]) == 2

    for error in (sub.SubscriptionError("key billing"), urllib.error.HTTPError("u", 400, "bad", {}, None)):
        attempts = []
        monkeypatch.setattr(page_review, "_review_call_once", lambda payload, base, e=error: (attempts.append(1), (_ for _ in ()).throw(e)))
        with pytest.raises(type(error)):
            page_review._review_call({"model": "m"})
        assert len(attempts) == 1  # never retried

    attempts = []
    monkeypatch.setattr(page_review, "_review_call_once", lambda payload, base: (attempts.append(1), (_ for _ in ()).throw(urllib.error.HTTPError("u", 503, "busy", {}, None))))
    with pytest.raises(urllib.error.HTTPError):
        page_review._review_call({"model": "m"})
    assert len(attempts) == 3  # one call and at most two retries


# --- the runner: dispatch, reviewer env, tier recovery, blind read, telemetry, reports ---------------------------------

def _runner(tmp_path, authors=None, reviewers=None):
    import deck_runner
    runner = deck_runner.Runner.__new__(deck_runner.Runner)
    runner.args = Namespace(session="run1", max_turns=11, max_parallel=2)
    runner.project = tmp_path / "project"
    runner.project.mkdir(exist_ok=True)
    runner.sessions = tmp_path / "sessions"
    runner.sessions.mkdir(exist_ok=True)
    runner.deck_dir = runner.sessions / "run1.deck"
    runner.deck_dir.mkdir(exist_ok=True)
    runner.authors = authors or {"workhorse": {"model": "gpt-6-luna", "effort": "high", "api_base": "cli:codex"},
                                 "frontier": {"model": "gpt-6-sol", "effort": "high", "api_base": "https://api.openai.com/v1", "key_var": "OPENAI_API_KEY"}}
    runner.reviewers = reviewers or {"workhorse": {"model": "gpt-6-sol", "effort": "high", "api_base": "cli:codex"},
                                     "frontier": {"model": "x-ai/grok-4.6", "effort": "medium", "api_base": "https://openrouter.ai/api/v1",
                                                  "key_var": "OPENROUTER_API_KEY", "provider": {"sort": "throughput"}}}
    runner.warnings = []
    import threading
    runner._telemetry_lock = threading.Lock()
    runner.telemetry_path = runner.sessions / "run1.runner.jsonl"
    return deck_runner, runner


def test_runner_host_dispatches_on_api_base_and_records_telemetry(tmp_path, monkeypatch):
    deck_runner, runner = _runner(tmp_path)
    seen = []

    def fake_run(argv, cwd, stdout, stderr, env):
        seen.append({"argv": argv, "env": env})
        session = argv[argv.index("--session") + 1]
        (runner.sessions / session).mkdir(exist_ok=True)
        usage = {"input_tokens": 1000, "cached": 400, "output_tokens": 100, "reasoning": 10, "calls": 3}
        if env["PPT_MASTER_API_BASE"].startswith("cli:"):
            usage.update(cost_usd=0.5, cost_source="subscription-notional-list-price")
        (runner.sessions / session / "state.json").write_text(json.dumps({"usage_total": usage}), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(deck_runner.subprocess, "run", fake_run)
    assert runner.host("run1.01_cover", "workhorse", ["--task-file", "t.txt"], stage="page", page="01_cover") == 0
    assert runner.host("run1.planner", "frontier", ["--answer", "fix"], stage="planner_repair") == 0
    cli, http = seen
    assert cli["argv"][1].endswith("cli_host.py") and http["argv"][1].endswith("host.py") and not http["argv"][1].endswith("cli_host.py")
    assert cli["argv"][cli["argv"].index("--max-turns") + 1] == "11" and cli["env"]["PPT_MASTER_API_BASE"] == "cli:codex"
    assert cli["env"]["PPT_MASTER_TIER"] == "workhorse" and cli["env"]["PPT_MASTER_REVIEW_API_BASE"] == "cli:codex"
    assert cli["env"]["PPT_MASTER_TELEMETRY_FILE"].endswith("run1.runner.jsonl")
    assert cli["env"]["PPT_MASTER_REVIEW_KEY_VAR"] == "" and "PPT_MASTER_REVIEW_PROVIDER" not in cli["env"]
    assert http["env"]["PPT_MASTER_REVIEW_KEY_VAR"] == "OPENROUTER_API_KEY" and json.loads(http["env"]["PPT_MASTER_REVIEW_PROVIDER"]) == {"sort": "throughput"}
    events = _events(runner.telemetry_path)
    sessions = [e for e in events if e["event"] == "model_session"]
    assert [(e["backend"], e["stage"], e["page"], e["mode"]) for e in sessions] == [("cli:codex", "page", "01_cover", "task"), ("http-responses", "planner_repair", None, "answer")]
    assert sessions[0]["cost_source"] == "subscription-notional-list-price" and sessions[0]["cost_usd"] == 0.5 and sessions[0]["usage"]["calls"] == 3
    assert sessions[1]["cost_source"] == "billed-api" and sessions[1]["cost_usd"] == pytest.approx(600 * 2e-6 + 400 * 0.2e-6 + 100 * 10e-6)
    assert all(e["at"].endswith("Z") for e in events)


def test_runner_preflights_each_cli_in_use_before_any_stage(tmp_path, monkeypatch):
    _, runner = _runner(tmp_path)
    asked = []
    monkeypatch.setattr(sub, "preflight", lambda backend, runner=None: asked.append(backend) or {"ok": True})
    runner.preflight_subscriptions()
    assert asked == ["codex"]

    def refuse(backend, runner=None):
        raise sub.SubscriptionError("API key login")
    monkeypatch.setattr(sub, "preflight", refuse)
    with pytest.raises(SystemExit, match="subscription route refused"):
        runner.preflight_subscriptions()
    assert [e["outcome"] for e in _events(runner.telemetry_path) if e["event"] == "preflight"] == ["ok", "refused"]


def test_sessions_of_reads_the_tier_back_from_state(tmp_path):
    same = {"workhorse": {"model": "claude-opus-5-5", "api_base": "cli:claude"}, "frontier": {"model": "claude-opus-5-5", "api_base": "cli:claude"}}
    deck_runner, runner = _runner(tmp_path, authors=same)
    folder = runner.sessions / "run1.02_page"
    folder.mkdir()
    (folder / "state.json").write_text(json.dumps({"model": "claude-opus-5-5", "api_base": "cli:claude", "tier": "workhorse"}), encoding="utf-8")
    assert runner.sessions_of("02_page") == ("run1.02_page", "workhorse")  # same model on both tiers: only the recorded tier can tell
    authors = {"workhorse": {"model": "gpt-6-luna"}, "frontier": {"model": "gpt-6-sol"}}
    assert deck_runner.tier_of_state({"model": "gpt-6-luna"}, authors) == "workhorse"  # a host.py session from before `tier` existed
    assert deck_runner.tier_of_state({}, authors) == "frontier"
    import host
    os.environ["PPT_MASTER_TIER"] = "workhorse"
    try:
        assert host.identity()["tier"] == "workhorse" and host.identity()["backend"] in ("http-responses", "anthropic-messages")
    finally:
        os.environ.pop("PPT_MASTER_TIER")


def test_newcomer_read_degrades_instead_of_aborting(tmp_path, monkeypatch):
    import page_review
    _, runner = _runner(tmp_path)
    (runner.project / "design_spec.md").write_text("#### Slide 01 - Cover\n\n- **Title**: A title\n- **Content**: Words.\n", encoding="utf-8")
    runner.say = lambda text: None

    def fail(payload):
        raise RuntimeError("reviewer down after retries")
    monkeypatch.setattr(page_review, "_review_call", fail)
    assert runner.newcomer_read() == {}
    assert runner.warnings and "UNAVAILABLE" in (runner.project / ".review" / "plan_reader.md").read_text(encoding="utf-8")
    call = next(e for e in _events(runner.telemetry_path) if e["event"] == "model_call")
    assert call["stage"] == "newcomer_read" and call["outcome"].startswith("failed")
    monkeypatch.setattr(page_review, "_review_call", lambda payload: ("Slide 01: unclear | repair: define it\nVERDICT: REVISE",
                                                                      {"input_tokens": 10, "output_tokens": 5, "cost": 0.001, "cost_source": "subscription-notional-list-price",
                                                                       "backend": "cli:codex", "attempts": 1}))
    found = runner.newcomer_read()
    assert list(found) == ["Slide 01 - Cover"]
    ok = [e for e in _events(runner.telemetry_path) if e["event"] == "model_call"][-1]
    assert ok["outcome"] == "ok" and ok["backend"] == "cli:codex" and ok["cost_source"] == "subscription-notional-list-price"


def test_run_report_prefers_runner_telemetry_and_separates_billed_from_notional(tmp_path):
    import run_report
    sessions = tmp_path / "sessions"
    project = tmp_path / "project"
    sessions.mkdir()
    project.mkdir()
    t = 1_790_000_000.0
    events = [{"event": "run_start", "t": t}, {"event": "stage_start", "stage": "planner", "t": t},
              {"event": "model_session", "stage": "planner", "tier": "frontier", "model": "gpt-6-sol", "effort": "high", "backend": "http-responses",
               "session": "run1.planner", "mode": "task", "wall_s": 100, "t": t + 100, "usage": {"input_tokens": 1000, "cached": 0, "output_tokens": 100, "reasoning": 50, "calls": 4},
               "cost_usd": 0.5, "cost_source": "billed-api"},
              {"event": "stage_end", "stage": "planner", "wall_s": 100, "t": t + 100, "outcome": "ok"},
              {"event": "model_session", "stage": "page", "page": "02_x", "tier": "workhorse", "model": "claude-opus-5-5", "effort": "high", "backend": "cli:claude",
               "session": "run1.02_x", "mode": "task", "wall_s": 60, "t": t + 170, "usage": {"input_tokens": 5000, "cached": 4000, "output_tokens": 300, "reasoning": 100, "calls": 6},
               "cost_usd": 1.25, "cost_source": "subscription-notional-list-price"},
              {"event": "model_call", "stage": "deck_review", "model": "gpt-6-sol", "effort": "high", "backend": "cli:codex", "outcome": "ok", "wall_s": 20, "t": t + 200,
               "usage": {"input_tokens": 700, "cached": 0, "output_tokens": 70, "reasoning": 7, "calls": 1}, "cost_usd": None, "cost_source": "unknown"},
              {"event": "run_end", "t": t + 210, "warnings": ["blind reader review unavailable"]}]
    (sessions / "run1.runner.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    (project / "quality-run.json").write_text(json.dumps({"pages": {"02_x": {"review_log": [
        {"rev": 0, "verdict": "PASS", "model": "gpt-6-sol", "seconds": 12, "usage": {"input_tokens": 100, "output_tokens": 10, "cost": 0.01, "cost_source": "subscription-notional-list-price"}},
        {"rev": 1, "verdict": "PASS", "model": "x-ai/grok-4.6", "seconds": 30, "usage": {"input_tokens": 1000, "output_tokens": 100}}]}}}), encoding="utf-8")
    text = run_report.build(sessions, "run1", project)
    assert "structured telemetry" in text and "Billed API cost: USD 0.50" in text and "list-price equivalent: USD 1.26" in text
    assert "| planner | +0.0 min | 1.7 min | ok |" in text and "blind reader review unavailable" in text
    assert "claude-opus-5-5 @ high [cli:claude]" in text and "1 call group(s) with no known price" in text


def test_report_analyse_labels_http_costs_billed(tmp_path):
    import report
    folder = tmp_path / "s"
    folder.mkdir()
    (folder / "transcript.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"event": "start", "model": "gpt-6-sol", "effort": "high", "api_base": "https://api.openai.com/v1", "at": 0},
        {"event": "turn", "usage": {"input_tokens": 1000, "output_tokens": 10}, "api_s": 2},
        {"event": "end", "usage_total": {}, "at": 5}]), encoding="utf-8")
    r = report.analyse(folder)
    assert r["cost_source"] == "billed-api" and r["calls"] == 1 and r["backend"] == "http-responses"
    assert report.cost_of("gpt-6-luna", 100, 0, 0, "cli:codex") == (pytest.approx(100 * 0.1e-6), "subscription-notional-list-price")
    assert report.cost_of("unknown-model", 1, 0, 0) == (None, "unknown")


def test_a_page_review_writes_its_own_telemetry_line(tmp_path, monkeypatch):
    import argparse
    import page_review
    project = tmp_path / "p"
    (project / "svg_output").mkdir(parents=True)
    (project / "svg_output" / "01_cover.svg").write_text("<svg/>", encoding="utf-8")
    (project / ".preview").mkdir()
    (project / ".preview" / "01_cover.png").write_bytes(PNG)
    monkeypatch.setenv("PPT_MASTER_NO_LINT", "1")
    monkeypatch.setattr(page_review, "_render_and_lint", lambda root, svg, want_lint: ([{"ok": True, "path": str(project / ".preview" / "01_cover.png")}], None, None))
    page_review.cmd_render(argparse.Namespace(project=str(project), page="01_cover", crop=None))
    monkeypatch.setattr(page_review, "_review_call", lambda payload: ("VERDICT: PASS\nBLOCKERS: 0", {
        "input_tokens": 900, "cached_tokens": 100, "output_tokens": 40, "reasoning_tokens": 30, "cost": 0.004,
        "cost_source": "subscription-notional-list-price", "backend": "cli:codex", "attempts": 2}))
    telemetry = tmp_path / "run1.runner.jsonl"
    monkeypatch.setenv("PPT_MASTER_TELEMETRY_FILE", str(telemetry))
    page_review.cmd_review(argparse.Namespace(project=str(project), page="01_cover"))
    (line,) = _events(telemetry)
    assert (line["event"], line["stage"], line["page"], line["verdict"], line["backend"], line["attempts"]) == ("model_call", "page_review", "01_cover", "PASS", "cli:codex", 2)
    assert line["usage"]["reasoning"] == 30 and line["cost_source"] == "subscription-notional-list-price" and line["at"].endswith("Z")
    usage = page_review.load_journal(project)["pages"]["01_cover"]["review_log"][0]["usage"]
    assert usage["backend"] == "cli:codex" and usage["cost_source"] == "subscription-notional-list-price"


# --- page sessions: one page each, never abandoned unwritten (campaign F01 cycle 2) ------------------------------------

def test_a_page_session_writes_only_its_own_page(monkeypatch):
    import host
    folder = ROOT / ".host-sessions" / "_test_own_page"
    (folder / "svg_output").mkdir(parents=True, exist_ok=True)
    try:
        own = folder / "svg_output" / "04_luna_cut_spend.svg"
        rel = lambda p: p.relative_to(ROOT).as_posix()
        monkeypatch.setenv("PPT_MASTER_PAGE_FILE", str(own))
        with pytest.raises(ValueError, match="04_luna_cut_spend.svg"):  # the drifted name is refused and the right one named
            host.tool_write_file(rel(folder / "svg_output" / "04_luna_spend.svg"), "<svg/>")
        assert not (folder / "svg_output" / "04_luna_spend.svg").exists()
        assert "wrote" in host.tool_write_file(rel(own), "<svg><g id='a'/></svg>")
        assert "edited" in host.tool_edit_file(rel(own), "id='a'", "id='b'")
        (folder / "svg_output" / "03_other.svg").write_text("<svg id='x'/>", encoding="utf-8")
        with pytest.raises(ValueError, match="authors one page"):
            host.tool_edit_file(rel(folder / "svg_output" / "03_other.svg"), "id='x'", "id='y'")
        assert "wrote" in host.tool_write_file(rel(folder / "notes" / "timeline.json"), "{}")  # other files stay writable
        monkeypatch.delenv("PPT_MASTER_PAGE_FILE")
        assert "wrote" in host.tool_write_file(rel(folder / "svg_output" / "03_other.svg"), "<svg/>")  # planner/template sessions: no guard
    finally:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)


def test_runner_names_the_page_file_and_continues_a_session_that_wrote_no_page(tmp_path, monkeypatch):
    deck_runner, runner = _runner(tmp_path)
    runner.page_sessions, runner.authored_by, runner.session_tier = {}, {}, {}
    monkeypatch.setattr(deck_runner, "page_task", lambda project, page, anchor, note="": "task")
    monkeypatch.setattr(runner, "journal_page", lambda stem: {}, raising=False)
    seen = []

    def fake_run(argv, cwd, stdout, stderr, env):
        seen.append({"argv": argv, "env": env})
        session = argv[argv.index("--session") + 1]
        (runner.sessions / session).mkdir(exist_ok=True)
        if len(seen) == write_on:
            (runner.project / "svg_output").mkdir(exist_ok=True)
            (runner.project / "svg_output" / "02_fees.svg").write_text("<svg/>", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(deck_runner.subprocess, "run", fake_run)
    page = {"number": 2, "stem": "02_fees"}
    write_on = 2  # the first session stops without writing; one continuation writes the page
    runner.author(page, "workhorse", None)
    assert len(seen) == 2 and seen[0]["env"]["PPT_MASTER_PAGE_FILE"] == str(runner.project / "svg_output" / "02_fees.svg")
    answer = seen[1]["argv"][seen[1]["argv"].index("--answer") + 1]
    assert "02_fees.svg" in answer and "write_file" in answer and "read-only" in answer and "DONE 02_fees" in answer
    stages = [e["stage"] for e in _events(runner.telemetry_path) if e["event"] == "model_session"]
    assert stages == ["page", "page_retry"]
    seen.clear()
    (runner.project / "svg_output" / "02_fees.svg").unlink()
    write_on = 99  # never written: two continuations, then the runner moves on
    runner.author(page, "workhorse", None)
    assert len(seen) == 1 + deck_runner.AUTHOR_NO_PAGE_RETRIES == 3
    runner.host("run1.planner", "frontier", ["--answer", "fix"], stage="planner_repair")
    assert "PPT_MASTER_PAGE_FILE" not in seen[-1]["env"]  # only page sessions carry the guard


def test_codex_notes_say_the_pptm_tools_write_despite_the_read_only_sandbox():
    import cli_host
    codex, claude = cli_host.cli_notes("codex"), cli_host.cli_notes("claude")
    assert "read-only" in codex and "write_file and edit_file tools do write" in codex and "never stop" in codex
    assert "read-only" not in claude


def test_only_planned_pages_stay_in_svg_output(tmp_path, monkeypatch):
    deck_runner, runner = _runner(tmp_path)
    (runner.project / "design_spec.md").write_text("spec", encoding="utf-8")
    monkeypatch.setattr(deck_runner, "parse_pages", lambda text: [{"stem": "01_cover"}, {"stem": "07_pilot"}])
    out = runner.project / "svg_output"
    out.mkdir()
    for name in ("01_cover.svg", "07_pilot.svg", "07_tl_preview.svg", "07_pilot.timeline.json"):
        (out / name).write_text("x", encoding="utf-8")
    assert runner.set_aside_strays() == ["07_tl_preview.svg"]
    assert sorted(p.name for p in out.iterdir()) == ["01_cover.svg", "07_pilot.svg", "07_pilot.timeline.json"]
    assert (runner.project / ".stray" / "07_tl_preview.svg").is_file()
    assert runner.set_aside_strays() == []


def test_a_script_reading_stdin_cannot_swallow_the_mcp_channel(tmp_path):
    reader = SCRIPTS / "_test_reads_stdin.py"
    reader.write_text("import sys\nprint(f'read {len(sys.stdin.read())} characters')\n", encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.Popen([sys.executable, str(HOSTS / "tools_mcp.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(ROOT), env=env)
    import threading
    watchdog = threading.Timer(120, proc.kill)  # without the fix the script eats the next message and waits for EOF: no answer ever comes
    watchdog.start()
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                                                                  "clientInfo": {"name": "test", "version": "0"}}})
        for message in ({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "run_script", "arguments": {"script": reader.name, "args": ["--input", "-"]}}},
                        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_dir", "arguments": {"path": "hosts/responses_api/planner_examples"}}}):
            proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        proc.stdin.flush()
        first, second = (json.loads(proc.stdout.readline().decode("utf-8") or "null") for _ in range(2))
        assert first and first["id"] == 2 and "read 0 characters" in first["result"]["content"][0]["text"]
        assert second and second["id"] == 3 and "story_calibration.md" in second["result"]["content"][0]["text"]
    finally:
        watchdog.cancel()
        reader.unlink(missing_ok=True)
        if proc.poll() is None:
            proc.stdin.close()
            proc.wait(timeout=30)
