#!/usr/bin/env python3
"""The Responses host's contract, run on a SUBSCRIPTION CLI: Claude Code (`claude -p`) or Codex (`codex exec`).

    python hosts/responses_api/cli_host.py --session NAME --max-turns N (--task-file F | --task T | --answer MSG | --resume-pending)

Selected by deck_runner when an author's api_base is `cli:claude` or `cli:codex` (PPT_MASTER_API_BASE). Same argv, same files in
<sessions>/<NAME>/ as host.py: transcript.jsonl (start / turn / tool / images_delivered / end events, the fields report.analyse
reads), state.json (usage_total, model, effort, backend, cli_session_id, pending_input), last_message.md; exit 0 on a normal
stop or at the call ceiling.

- The CLI runs the agent loop; the six host tools reach it as the `pptm` MCP server (tools_mcp.py), which reuses host.HANDLERS
  and their guards and returns every `IMAGE:` render inside the tool result. The CLI's own tools are off (`--tools ""` for
  Claude; Codex's shell tool disabled, read-only sandbox, approval never).
- Subscription only: the child environment is scrubbed (subscription_cli.scrub_env), `auth status` / `login status` must say
  claude.ai / ChatGPT before the call, and Claude's init event must report apiKeySource "none". A failure refuses to run (exit 3).
- `--answer` resumes the same CLI conversation (`claude -p --resume <id>`, `codex exec resume <thread>`).
- Ceiling: `--max-turns` is Claude's own --max-turns (model turns). Codex has none, so a watchdog counts tool-call events and stops
  the process group at the ceiling; the session is marked pending and `--resume-pending` continues it.
- Usage per invocation comes from the CLI's own accounting (Claude's result event; Codex's rollout file) and is written to the
  `end` event as `usage_run`, with a notional cost (`subscription-notional-list-price`) - a subscription bills nothing per call.
- No wall-clock limit is put on the model's work (user policy).

Environment: PPT_MASTER_MODEL, PPT_MASTER_EFFORT, PPT_MASTER_API_BASE (cli:claude | cli:codex), PPT_MASTER_SYSTEM_FILE,
PPT_MASTER_SESSIONS_DIR, PPT_MASTER_TIER, the reviewer's PPT_MASTER_REVIEW_*; PPT_MASTER_CLAUDE_BIN / PPT_MASTER_CODEX_BIN override
the executables.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRIPTS = ROOT / "skills" / "ppt-master" / "scripts"
for _p in (str(SCRIPTS), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import host  # noqa: E402 - side-effect free on import
import subscription_cli as sub  # noqa: E402

MCP_SERVER = HERE / "tools_mcp.py"
TOOL_PREFIX = "mcp__pptm__"
RESUME_NOTE = ("The previous run of this conversation stopped at its call ceiling before you finished. Continue the same task from "
               "where you stopped; do not redo finished steps. When done, reply as the task asks.")
# Set AFTER the scrub (which removes every CLAUDE_CODE_* and MCP_* the parent had): no CLAUDE.md/AGENTS.md memory, no auto-memory,
# no bundled skills in an author's context; a long MCP tool call (a render under load, a nested review) is waited for.
CLAUDE_ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS": "1",
              "MCP_TOOL_TIMEOUT": "86400000", "MCP_TIMEOUT": "120000"}
STOP_GRACE_S = 30  # after the call ceiling: time the CLI gets to shut down cleanly before its process tree is ended (not a model deadline)


def cli_notes(backend: str) -> str:
    """The Host notes, with the tool and image sentences rewritten for MCP tools."""
    if backend == "claude":
        names = "mcp__pptm__read_file, mcp__pptm__read_image, mcp__pptm__write_file, mcp__pptm__edit_file, mcp__pptm__list_dir and mcp__pptm__run_script"
    else:
        names = "the `pptm` server's read_file, read_image, write_file, edit_file, list_dir and run_script"
    tools = (f"Your tools are MCP tools: {names}. They are the only tools you use. read_file reads text files or lists a directory (paths "
             "relative to the repository root); read_image shows you an image; write_file; edit_file (exact replacement of one unique passage - use "
             "it for local SVG revisions); list_dir; run_script runs the skill's own scripts by path under skills/ppt-master/scripts, with arguments "
             "(paths in arguments are relative to the repository root). ")
    images = ("Whenever a script prints an `IMAGE: <path>` line, the image itself comes back inside that tool's result, after its text, so you see "
              "it at once and need not call read_image for it; read_image likewise returns the image in its result. ")
    if backend == "codex":
        images += ("Do not use a shell, apply_patch or any tool other than the pptm tools. If an image you expected is not visible in a tool "
                   "result, open its `IMAGE:` path with your image viewer (view_image). ")
    return host.host_notes(tools, images)


def _toml(value) -> str:
    if isinstance(value, list):
        return "[" + ",".join(_toml(v) for v in value) + "]"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value))


def mcp_server_args(session_dir: Path) -> list[str]:
    return [str(MCP_SERVER), "--env-file", str(session_dir / "mcp_env.json"), "--log", str(session_dir / "mcp_tools.jsonl")]


def write_mcp_env(session_dir: Path, base: dict | None = None) -> dict:
    env = sub.mcp_env(base)
    source = os.environ if base is None else base
    if source.get("PPT_MASTER_SCRIPT_KEYS") == "1" and source.get("PPT_MASTER_ENV_FILE"):  # explicit opt-in: an HTTP reviewer inside a CLI session
        env.update({"PPT_MASTER_SCRIPT_KEYS": "1", "PPT_MASTER_ENV_FILE": source["PPT_MASTER_ENV_FILE"]})
    (session_dir / "mcp_env.json").write_text(json.dumps(env, indent=1), encoding="utf-8")
    return env


def claude_argv(model: str, effort: str, system_file: Path, mcp_config: Path, max_turns: int, *, session_id: str | None = None,
                resume: str | None = None) -> list[str]:
    # Not --safe-mode: it ignores every --mcp-config server ("server ignored (safe mode)", verified 2026-09-29). User and project settings
    # (hooks, plugins, permissions) are skipped with --setting-sources "", memory files and bundled skills by CLAUDE_ENV below.
    argv = [sub.claude_bin(), "-p", "--setting-sources", "", "--strict-mcp-config", "--mcp-config", str(mcp_config), "--disable-slash-commands",
            "--tools", "", "--allowedTools", "mcp__pptm", "--permission-mode", "dontAsk", "--model", model]
    if effort in sub.CLAUDE_EFFORTS:
        argv += ["--effort", effort]
    argv += ["--system-prompt-file", str(system_file), "--max-turns", str(max_turns), "--output-format", "stream-json", "--verbose"]
    argv += ["--resume", resume] if resume else ["--session-id", session_id or str(uuid.uuid4())]
    return argv


def codex_argv(model: str, effort: str, system_file: Path, session_dir: Path, env: dict, *, resume: str | None = None) -> list[str]:
    server = [f"mcp_servers.pptm.command={_toml(sys.executable)}", f"mcp_servers.pptm.args={_toml(mcp_server_args(session_dir))}",
              f"mcp_servers.pptm.env_vars={_toml(sorted(k for k in env if k.upper() in sub.MCP_PASS_NAMES))}",
              "mcp_servers.pptm.startup_timeout_sec=120", "mcp_servers.pptm.tool_timeout_sec=86400",
              'mcp_servers.pptm.default_tools_approval_mode="approve"', 'sandbox_mode="read-only"']
    base = sub.codex_base_argv(model, effort, system_file)
    for item in server:
        base += ["-c", item]
    last = str(session_dir / "cli_last_message.txt")
    if resume:  # `resume` takes no -s/-C: the sandbox is set by -c above and the working root by the process cwd
        return [sub.codex_bin(), "exec", "resume", *base, "-o", last, resume, "-"]
    return [sub.codex_bin(), "exec", *base, "-C", str(ROOT), "-o", last, "-"]


class Session:
    """transcript.jsonl writer and the stream -> host-event mapping for both CLIs."""

    def __init__(self, session_dir: Path, backend: str, model: str, require_pptm: bool = True) -> None:
        self.dir, self.backend, self.model, self.require_pptm = session_dir, backend, model, require_pptm
        self.transcript = session_dir / "transcript.jsonl"
        self.turn = 0
        self.current: dict | None = None
        self.tool_uses: dict[str, tuple[str, dict]] = {}
        self.prev_input_at = time.time()
        self.texts: list[str] = []
        self.images = 0
        self.image_paths: list[str] = []
        self.tool_calls = 0
        self.result: dict | None = None
        self.init: dict | None = None
        self.rate_limit: dict | None = None
        self.thread_id: str | None = None
        self.codex_usage: dict | None = None
        self.errors: list[str] = []
        self.unexpected_tools: list[str] = []
        self.message_ids: list[str] = []
        self.codex_items: list[dict] = []  # Codex tool calls with their start/finish times, matched to the rollout's responses afterwards

    def log(self, record: dict) -> None:
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Claude ------------------------------------------------------------------------------------------------------------
    def _flush(self) -> None:
        if not self.current:
            return
        c, self.current = self.current, None
        usage = c["usage"]
        cache_read = usage.get("cache_read_input_tokens") or 0
        cache_write = usage.get("cache_creation_input_tokens") or 0
        mapped = {"input_tokens": (usage.get("input_tokens") or 0) + cache_read + cache_write, "input_tokens_details": {"cached_tokens": cache_read},
                  "cache_creation_input_tokens": cache_write, "output_tokens": usage.get("output_tokens") or 0,
                  "output_tokens_details": {"reasoning_tokens": 0}, "output_partial": True}
        self.log({"event": "turn", "turn": self.turn, "usage": mapped, "at": c["last_at"], "api_s": round(c["last_at"] - c["input_at"], 2),
                  "calls": c["calls"], "text": "\n".join(c["texts"])[:6000], "message_id": c["id"]})
        print(f"turn {self.turn}: {len(c['calls'])} tool call(s); tokens in {mapped['input_tokens']}", flush=True)
        self.turn += 1

    def on_claude(self, event: dict) -> None:
        kind, subtype, now = event.get("type"), event.get("subtype"), time.time()
        if kind == "system" and subtype == "init":
            self.init = event
            self.log({"event": "cli_init", "backend": "cli:claude", "apiKeySource": event.get("apiKeySource"), "model": event.get("model"),
                      "tools": event.get("tools"), "mcp_servers": event.get("mcp_servers"), "permissionMode": event.get("permissionMode"),
                      "claude_code_version": event.get("claude_code_version"), "session_id": event.get("session_id"), "at": now})
            sub.check_claude_init(event)  # raises SubscriptionError on key billing
            servers = {str(s.get("name")): s.get("status") for s in event.get("mcp_servers") or [] if isinstance(s, dict)}
            if self.require_pptm and servers.get("pptm") in (None, "failed", "disabled"):
                raise sub.SubscriptionError(f"the pptm tool server is not available to the CLI (mcp_servers={servers}): refusing to run a session without its tools")
            self.unexpected_tools = [t for t in event.get("tools") or [] if not str(t).startswith(TOOL_PREFIX)]
            if self.unexpected_tools:
                self.log({"event": "warning", "text": f"CLI offers tools beyond the pptm server: {self.unexpected_tools}", "at": now})
        elif kind == "rate_limit_event":
            self.rate_limit = event.get("rate_limit_info")
            self.log({"event": "rate_limit", "info": self.rate_limit, "at": now})
        elif kind == "system" and subtype == "api_retry":
            self.log({"event": "transport_error", "error": str({k: v for k, v in event.items() if k not in ("uuid", "session_id")})[:300], "at": now})
        elif kind == "assistant":
            message = event.get("message") or {}
            mid = message.get("id") or f"anon-{self.turn}"
            if self.current and self.current["id"] != mid:
                self._flush()
            if not self.current:  # one API response; Claude streams its parallel tool calls with their results in between
                self.current = {"id": mid, "calls": [], "texts": [], "usage": {}, "last_at": now, "input_at": self.prev_input_at}
                if mid not in self.message_ids:
                    self.message_ids.append(mid)
            self.current["usage"] = message.get("usage") or self.current["usage"]
            self.current["last_at"] = now
            for block in message.get("content") or []:
                if block.get("type") == "tool_use":
                    name = str(block.get("name") or "")
                    self.tool_uses[block.get("id")] = (name, block.get("input") or {})
                    self.current["calls"].append((name.removeprefix(TOOL_PREFIX), json.dumps(block.get("input") or {}, ensure_ascii=False)[:300]))
                    self.tool_calls += 1
                elif block.get("type") == "text":
                    self.current["texts"].append(block.get("text") or "")
                    self.texts.append(block.get("text") or "")
        elif kind == "user":  # tool results: the response they answer stays open until a new response id (or the result) arrives
            content = (event.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else []:
                if block.get("type") != "tool_result":
                    continue
                name, args = self.tool_uses.get(block.get("tool_use_id"), ("?", {}))
                parts = block.get("content")
                parts = [{"type": "text", "text": parts}] if isinstance(parts, str) else (parts or [])
                text = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text")
                images = [p for p in parts if p.get("type") == "image"]
                self.images += len(images)
                self.image_paths += [p["text"][len("image: "):] for p in parts if p.get("type") == "text" and str(p.get("text", "")).startswith("image: ")]
                self.log({"event": "tool", "name": name.removeprefix(TOOL_PREFIX), "args": json.dumps(args, ensure_ascii=False)[:2000],
                          "result": text[:4000], "images": len(images), "is_error": bool(block.get("is_error")), "at": now})
                print(f"  {name.removeprefix(TOOL_PREFIX)} {json.dumps(args, ensure_ascii=False)[:120]} -> {text[:100].replace(chr(10), ' ')}", flush=True)
                if not name.startswith(TOOL_PREFIX):
                    self.log({"event": "warning", "text": f"a tool outside the pptm server was used: {name}", "at": now})
            self.prev_input_at = now
        elif kind == "result":
            self._flush()
            self.result = event
            self.log({"event": "cli_result", "subtype": event.get("subtype"), "is_error": event.get("is_error"), "num_turns": event.get("num_turns"),
                      "total_cost_usd": event.get("total_cost_usd"), "usage": event.get("usage"), "modelUsage": event.get("modelUsage"),
                      "duration_ms": event.get("duration_ms"), "duration_api_ms": event.get("duration_api_ms"), "stop_reason": event.get("stop_reason"),
                      "terminal_reason": event.get("terminal_reason"), "api_error_status": event.get("api_error_status"),
                      "permission_denials": len(event.get("permission_denials") or []), "session_id": event.get("session_id"), "at": now})

    # Codex -------------------------------------------------------------------------------------------------------------
    def on_codex(self, event: dict) -> None:
        kind, item, now = event.get("type"), event.get("item") or {}, time.time()
        itype = item.get("type")
        if kind == "thread.started":
            self.thread_id = event.get("thread_id")
            self.log({"event": "cli_init", "backend": "cli:codex", "thread_id": self.thread_id, "at": now})
        elif kind == "item.started" and itype in ("mcp_tool_call", "command_execution"):
            self.tool_calls += 1
            self.codex_items.append({"id": item.get("id"), "started": now, "done": None, "name": str(item.get("tool") or itype),
                                     "args": json.dumps(item.get("arguments") or {k: item.get(k) for k in ("command",) if k in item}, ensure_ascii=False)[:300]})
        elif kind == "item.completed" and itype == "mcp_tool_call":
            result = item.get("result") or {}
            parts = result.get("content") or []
            text = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text") or str(item.get("error") or "")
            images = sum(1 for p in parts if p.get("type") == "image")
            self.images += images
            self.image_paths += [p["text"][len("image: "):] for p in parts if p.get("type") == "text" and str(p.get("text", "")).startswith("image: ")]
            name = str(item.get("tool") or "?")
            for known in self.codex_items:
                if known["id"] == item.get("id") and known["done"] is None:
                    known["done"] = now
            self.log({"event": "tool", "name": name, "args": json.dumps(item.get("arguments") or {}, ensure_ascii=False)[:2000], "result": text[:4000],
                      "images": images, "is_error": bool(item.get("error")) or bool(result.get("is_error") or result.get("isError")), "server": item.get("server"), "at": now})
            print(f"  {name} {json.dumps(item.get('arguments') or {}, ensure_ascii=False)[:120]} -> {text[:100].replace(chr(10), ' ')}", flush=True)
        elif kind == "item.completed" and itype in ("command_execution", "file_change", "web_search"):
            self.unexpected_tools.append(itype)
            self.log({"event": "tool", "name": itype, "args": json.dumps({k: item.get(k) for k in ("command", "changes", "query") if k in item}, ensure_ascii=False)[:2000],
                      "result": str(item.get("aggregated_output") or item.get("status") or "")[:4000], "unexpected": True, "at": now})
            self.log({"event": "warning", "text": f"Codex used its own {itype} tool instead of the pptm tools", "at": now})
        elif kind == "item.completed" and itype == "agent_message":
            self.texts.append(item.get("text") or "")
        elif kind == "turn.completed":
            self.codex_usage = event.get("usage")
        elif kind in ("turn.failed", "error"):
            self.errors.append(str(event.get("error") or event.get("message") or event)[:500])
            self.log({"event": "transport_error", "error": self.errors[-1][:300], "at": now})

    def codex_turns(self, since: float) -> tuple[dict | None, list[dict]]:
        """After the run: per-request usage from the rollout file becomes the `turn` events (the --json stream has one total)."""
        rollout = sub.codex_rollout(self.thread_id or "")
        audit = sub.read_rollout(rollout, since) if rollout else {"calls": [], "rate_limit": None, "context": {}}
        responses = audit["calls"]
        for n, call in enumerate(responses):
            u = call["usage"]
            at = call["at"] or time.time()
            following = responses[n + 1]["at"] if n + 1 < len(responses) and responses[n + 1]["at"] else float("inf")
            # the tool calls this response asked for start after it and before the next response; the time it took is measured from the last
            # input it saw: the previous response, or the last tool result that came back before it
            asked = [i for i in self.codex_items if at - 1 <= i["started"] < following]
            inputs = [since] + [responses[n - 1]["at"] or since for _ in [0] if n] + [i["done"] for i in self.codex_items if i["done"] and i["done"] <= at]
            self.log({"event": "turn", "turn": self.turn, "at": at, "api_s": round(max(0.0, at - max(inputs)), 2), "calls": [(i["name"], i["args"]) for i in asked],
                      "text": "", "response_id": call.get("response_id"),
                      "usage": {"input_tokens": u.get("input_tokens") or 0, "input_tokens_details": {"cached_tokens": u.get("cached_input_tokens") or 0},
                                "output_tokens": u.get("output_tokens") or 0, "output_tokens_details": {"reasoning_tokens": u.get("reasoning_output_tokens") or 0}}})
            self.turn += 1
        if audit["rate_limit"]:
            self.rate_limit = audit["rate_limit"]
            self.log({"event": "rate_limit", "info": audit["rate_limit"], "at": time.time()})
        context = audit["context"] or {}
        if context and (context.get("model") != self.model):
            self.log({"event": "warning", "text": f"Codex ran {context.get('model')} (asked {self.model})", "at": time.time()})
        return (str(rollout) if rollout else None), audit["calls"]


def _stop(proc: subprocess.Popen) -> None:
    """End the CLI at the call ceiling: a console break first, then the whole process tree (the MCP server is its child)."""
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(proc.pid, signal.SIGINT)
    except (OSError, ValueError):
        pass

    def finish() -> None:
        if proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(proc.pid, signal.SIGKILL)

    threading.Timer(STOP_GRACE_S, finish).start()


def run_cli(argv: list[str], stdin_text: str, env: dict, stream_log: Path, stderr_log: Path, on_event, ceiling=None) -> tuple[int, bool]:
    """Run the CLI with the message on stdin, handing each JSON event to `on_event`. `ceiling()` true -> stop it. Returns (exit, stopped)."""
    flags = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with stderr_log.open("ab") as err:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, cwd=str(ROOT), env=env, **flags)
        proc.stdin.write(stdin_text.encode("utf-8"))
        proc.stdin.close()
        stopped = False
        with stream_log.open("ab") as raw_log:
            for raw in proc.stdout:
                raw_log.write(raw)
                raw_log.flush()
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    on_event(event)
                except sub.SubscriptionError:
                    _stop(proc)
                    proc.wait()
                    raise
                if ceiling and not stopped and ceiling():
                    stopped = True
                    _stop(proc)
        return proc.wait(), stopped


def _add(total: dict, run: dict) -> dict:
    for key in ("input_tokens", "cached", "output_tokens", "reasoning", "calls"):
        total[key] = total.get(key, 0) + (run.get(key) or 0)
    if run.get("cost_usd") is not None:
        total["cost_usd"] = round(total.get("cost_usd", 0.0) + run["cost_usd"], 6)
    sources = {s for s in (total.get("cost_source"), run.get("cost_source")) if s}
    total["cost_source"] = sources.pop() if len(sources) == 1 else ("mixed" if sources else sub.COST_UNKNOWN)
    return total


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True)
    parser.add_argument("--task")
    parser.add_argument("--task-file")
    parser.add_argument("--answer")
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--max-calls", type=int, default=400, help="accepted for host.py compatibility; the CLI ceiling is --max-turns")
    parser.add_argument("--resume-pending", action="store_true")
    args = parser.parse_args(argv)
    backend = sub.backend_of(os.environ.get("PPT_MASTER_API_BASE"))
    if backend is None:
        raise SystemExit("cli_host.py needs PPT_MASTER_API_BASE=cli:claude or cli:codex")
    model = os.environ.get("PPT_MASTER_MODEL") or ("claude-opus-5-5" if backend == "claude" else "gpt-6-sol")
    effort = os.environ.get("PPT_MASTER_EFFORT", "high")
    session_dir = host.OUT / args.session
    session_dir.mkdir(parents=True, exist_ok=True)
    state_path = session_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    state.update({"model": model, "effort": effort, "backend": f"cli:{backend}", "api_base": f"cli:{backend}"})
    if os.environ.get("PPT_MASTER_TIER"):
        state["tier"] = os.environ["PPT_MASTER_TIER"]
    if args.task_file:
        args.task = Path(args.task_file).read_text(encoding="utf-8")
    resume = None
    if args.task:
        message = args.task
    elif args.answer:
        resume = state.get("cli_session_id")
        if not resume:
            raise SystemExit("no session to continue")
        message = args.answer
    elif args.resume_pending:
        resume = state.get("cli_session_id")
        if not resume or not state.get("pending_input"):
            raise SystemExit("nothing pending to resume")
        message = RESUME_NOTE
    else:
        raise SystemExit("give --task, --answer or --resume-pending")

    session = Session(session_dir, backend, model)
    started = time.time()
    session.log({"event": "start", "model": model, "effort": effort, "api_base": f"cli:{backend}", "backend": f"cli:{backend}", "stateless": False,
                 "at": started, "task": args.task, "answer": args.answer, "resume_pending": bool(args.resume_pending), "cli_session_id": resume})
    try:
        verified = sub.preflight(backend)
    except sub.SubscriptionError as exc:
        session.log({"event": "preflight_failed", "error": str(exc), "at": time.time()})
        print(f"REFUSED: {exc}", flush=True)
        return 3
    session.log({"event": "preflight", "backend": backend, "status": verified, "at": time.time()})

    system_file = session_dir / "system_prompt.md"
    system_file.write_text(host.system_prompt(cli_notes(backend)), encoding="utf-8")
    env = sub.scrub_env()
    write_mcp_env(session_dir, env | {k: v for k, v in os.environ.items() if k in ("PPT_MASTER_SCRIPT_KEYS", "PPT_MASTER_ENV_FILE")})
    ceiling = None
    if backend == "claude":
        mcp_config = session_dir / "mcp_config.json"
        mcp_config.write_text(json.dumps({"mcpServers": {"pptm": {"type": "stdio", "command": sys.executable, "args": mcp_server_args(session_dir), "env": {}}}},
                                         indent=1), encoding="utf-8")
        new_id = None if resume else str(uuid.uuid4())
        if new_id:
            state["cli_session_id"] = new_id
        argv = claude_argv(model, effort, system_file, mcp_config, args.max_turns, session_id=new_id, resume=resume)
        env |= CLAUDE_ENV
        on_event = session.on_claude
    else:
        argv = codex_argv(model, effort, system_file, session_dir, env, resume=resume)
        on_event = session.on_codex
        ceiling = lambda: session.tool_calls >= args.max_turns  # noqa: E731
    state["pending_input"] = []
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    (session_dir / "cli_argv.json").write_text(json.dumps(argv, indent=1), encoding="utf-8")

    try:
        code, stopped = run_cli(argv, message, env, session_dir / "cli_stream.jsonl", session_dir / "cli_stderr.log", on_event, ceiling)
    except sub.SubscriptionError as exc:
        session.log({"event": "refused", "error": str(exc), "at": time.time()})
        print(f"REFUSED: {exc}", flush=True)
        return 3

    rollout = None
    if backend == "claude":
        result = session.result or {}
        run = sub.claude_usage(result, calls=len(session.message_ids)) if result else {
            "input_tokens": 0, "cached": 0, "output_tokens": 0, "reasoning": 0, "calls": len(session.message_ids), "cost_usd": None, "cost_source": sub.COST_UNKNOWN}
        text = result.get("result") if isinstance(result.get("result"), str) else "\n".join(session.texts)
        at_ceiling = result.get("subtype") == "error_max_turns"
        failed = (not result) or (bool(result.get("is_error")) and not at_ceiling)
        state["cli_session_id"] = result.get("session_id") or state.get("cli_session_id")
        unexpected = sorted(set(result.get("modelUsage") or {}) - {model})
        if unexpected:
            session.log({"event": "warning", "text": f"models other than {model} were used: {unexpected}", "at": time.time()})
    else:
        if session.thread_id:
            state["cli_session_id"] = session.thread_id
        rollout, calls = session.codex_turns(started)
        if calls:
            summed = {"input_tokens": sum(c["usage"].get("input_tokens") or 0 for c in calls),
                      "cached_input_tokens": sum(c["usage"].get("cached_input_tokens") or 0 for c in calls),
                      "output_tokens": sum(c["usage"].get("output_tokens") or 0 for c in calls),
                      "reasoning_output_tokens": sum(c["usage"].get("reasoning_output_tokens") or 0 for c in calls)}
            run = sub.codex_usage(summed, model, calls=len(calls))
        else:
            run = sub.codex_usage(session.codex_usage, model, calls=1 if session.codex_usage else 0)
        last = session_dir / "cli_last_message.txt"
        text = last.read_text(encoding="utf-8", errors="replace") if last.is_file() else (session.texts[-1] if session.texts else "")
        at_ceiling = stopped
        failed = not stopped and (code != 0 or session.codex_usage is None)
    usage_total = _add(state.get("usage_total") or {"input_tokens": 0, "cached": 0, "output_tokens": 0, "reasoning": 0, "calls": 0}, run)
    state.update({"usage_total": usage_total, "rate_limit": session.rate_limit, "last_run": {"exit": code, "at_ceiling": at_ceiling, "failed": failed,
                  "rollout": rollout, "wall_s": round(time.time() - started, 1), "tool_calls": session.tool_calls, "images_delivered": session.images}})
    if at_ceiling:  # --resume-pending continues the same CLI conversation
        state["pending_input"] = [{"cli_continue": True, "at": time.time()}]
        print(f"call ceiling reached ({args.max_turns}): the conversation is kept; continue with --resume-pending", flush=True)
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    if text and not failed:
        (session_dir / "last_message.md").write_text(text, encoding="utf-8")
        print("\n=== MODEL STOPPED (gate or finish) ===\n" + text, flush=True)
    if session.images:
        session.log({"event": "images_delivered", "paths": session.image_paths[:session.images] or [f"image {n + 1}" for n in range(session.images)],
                     "count": session.images, "where": "inside MCP tool results"})
    session.log({"event": "end", "usage_total": usage_total, "usage_run": run, "exit": code, "at_ceiling": at_ceiling, "failed": failed, "at": time.time()})
    try:
        host._write_run_blocks(args.session, usage_total, host=f"cli:{backend}", model=model, effort=effort, images=session.images, started=started)
    except SystemExit:  # a locked journal must not turn a finished session into a failure
        pass
    print("usage", usage_total, flush=True)
    if failed:
        print(f"CLI run failed (exit {code}): see {session_dir / 'cli_stderr.log'}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
