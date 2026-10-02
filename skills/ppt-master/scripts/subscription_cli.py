#!/usr/bin/env python3
"""Subscription transport: run a model through the Claude Code CLI (`claude -p`) or the Codex CLI (`codex exec`)
on the user's own subscription, never on an API key.

Used by the scripted runner's CLI host (`hosts/responses_api/cli_host.py`) for tool-using sessions and by
`page_review._review_call` for single-shot reviews (api_base `cli:claude` or `cli:codex`).

    python skills/ppt-master/scripts/subscription_cli.py preflight claude|codex|all

Guarantees:
- Every CLI child starts from a SCRUBBED environment: no ANTHROPIC_*, CLAUDE_CODE_*, CLAUDECODE, MCP_* or model API keys, so
  `claude -p` cannot switch to key billing (a present ANTHROPIC_API_KEY always wins in print mode) and Codex cannot use
  CODEX_API_KEY/OPENAI_API_KEY. A `.env` file is never loaded into a CLI child.
- Pre-flight (no model call): `claude auth status --json` must report authMethod `claude.ai` and apiProvider `firstParty`;
  `codex login status` must say ChatGPT. Anything else refuses to run.
- In the stream: Claude's `system/init` event must carry `apiKeySource: "none"`; otherwise the call is stopped.
- Costs are never billed amounts: Claude's `total_cost_usd` is a list-price estimate and Codex reports tokens only, so both
  are labelled `subscription-notional-list-price` (or `unknown` when no price is known).

Nothing here imposes a wall-clock limit on a model call (user policy); ceilings are logical (turns, tool calls).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ROOT = SCRIPTS.parents[2]
HOSTS = ROOT / "hosts" / "responses_api"

COST_BILLED = "billed-api"
COST_NOTIONAL = "subscription-notional-list-price"
COST_UNKNOWN = "unknown"

# Environment that must never reach a subscription CLI child (routes/subscription_routes.md §1.1, §2.1).
SCRUB_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_", "MCP_")
SCRUB_NAMES = {"CLAUDECODE", "CLAUDE_AGENT_SDK_VERSION", "CLAUDE_PID", "CLAUDE_EFFORT", "OPENAI_API_KEY", "CODEX_API_KEY",
               "OPENROUTER_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "PPT_MASTER_ENV_FILE"}
# What an MCP tool server spawned by a CLI needs to run the skill's scripts (Codex passes only a small default set to MCP children).
MCP_PASS_NAMES = {"PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE",
                  "HOMEPATH", "HOME", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
                  "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "USERNAME", "USERDOMAIN", "COMPUTERNAME", "NUMBER_OF_PROCESSORS",
                  "PROCESSOR_ARCHITECTURE", "OS", "LANG", "LC_ALL", "CODEX_HOME", "CODEX_CLI_PATH", "PLAYWRIGHT_BROWSERS_PATH",
                  "IMAGE_BACKEND", "VIRTUAL_ENV"}
CLAUDE_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
CODEX_EFFORTS = {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
# Codex features switched off for an orchestrated call: the model gets the MCP tools and its image viewer, nothing that runs code
# or reaches out. `shell_tool` and `unified_exec` are Codex's command runners (see F01_REPORT.md for what was verified).
CODEX_DISABLED_FEATURES = ("shell_tool", "unified_exec", "apps", "plugins", "multi_agent", "browser_use", "browser_use_external",
                           "computer_use", "image_generation", "in_app_browser", "hooks", "goals", "tool_suggest", "skill_search",
                           "skill_mcp_dependency_install", "remote_plugin")
# Notional prices for tokens a subscription CLI reports (USD per token: input, cached input, output). The report's table wins
# where it knows the model (hosts/responses_api/report.py PRICES).
NOTIONAL_PRICES = {
    "gpt-6-sol": (2.0e-6, 0.2e-6, 10.0e-6),
    "gpt-6.1-sol": (2.0e-6, 0.1e-6, 10.0e-6),
}


class SubscriptionError(RuntimeError):
    """The subscription route cannot be guaranteed (auth, API-key source): never retried, never silently worked around."""


class CliCallError(RuntimeError):
    """A CLI call failed in a way a retry may fix (non-zero exit, no result, rate limit)."""


def scrub_env(base: dict | None = None, extra: dict | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for name in list(env):
        upper = name.upper()
        if upper.startswith(SCRUB_PREFIXES) or upper in SCRUB_NAMES:
            env.pop(name)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.update(extra or {})
    return env


def mcp_env(base: dict | None = None) -> dict[str, str]:
    """The variables an MCP tool server needs: the OS basics plus the runner's PPT_MASTER_* settings - never a key."""
    env = scrub_env(base)
    return {k: v for k, v in env.items() if k.upper() in MCP_PASS_NAMES or k.upper().startswith(("PPT_MASTER_", "PYTHON"))}


def claude_bin() -> str:
    found = os.environ.get("PPT_MASTER_CLAUDE_BIN") or shutil.which("claude")
    if not found:
        raise SubscriptionError("the Claude Code CLI (`claude`) is not on PATH; set PPT_MASTER_CLAUDE_BIN")
    return found


def codex_bin() -> str:
    for candidate in (os.environ.get("PPT_MASTER_CODEX_BIN"), os.environ.get("CODEX_CLI_PATH")):
        if candidate and Path(candidate).is_file():
            return candidate
    found = shutil.which("codex")
    if not found:
        raise SubscriptionError("the Codex CLI (`codex`) is not found; set PPT_MASTER_CODEX_BIN or CODEX_CLI_PATH")
    return found


def backend_of(api_base: str | None) -> str | None:
    """`cli:claude` / `cli:codex` (any case, surrounding spaces ignored) -> `claude` / `codex`; anything else -> None."""
    value = (api_base or "").strip().lower()
    if value in ("cli:claude", "cli:codex"):
        return value.split(":", 1)[1]
    if value.startswith("cli:"):
        raise SubscriptionError(f"unknown CLI route {api_base!r}: use cli:claude or cli:codex")
    return None


_PREFLIGHT: dict[str, dict] = {}


def preflight(backend: str, runner=subprocess.run) -> dict:
    """Assert the CLI is logged in on the subscription. Makes no model call. Cached per process."""
    if backend in _PREFLIGHT:
        return _PREFLIGHT[backend]
    env = scrub_env()
    if backend == "claude":
        proc = runner([claude_bin(), "auth", "status", "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                      cwd=tempfile.gettempdir())
        try:
            status = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise SubscriptionError(f"`claude auth status --json` did not return JSON (exit {proc.returncode})") from exc
        info = {k: status.get(k) for k in ("loggedIn", "authMethod", "apiProvider", "subscriptionType")}
        if not status.get("loggedIn") or status.get("authMethod") != "claude.ai" or status.get("apiProvider") != "firstParty":
            raise SubscriptionError(f"Claude Code is not on the claude.ai subscription: {info}. Log in with `claude` -> /login; API keys are refused")
    elif backend == "codex":
        proc = runner([codex_bin(), "login", "status"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                      cwd=tempfile.gettempdir())
        text = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode != 0 or "chatgpt" not in text.lower():
            raise SubscriptionError(f"Codex is not logged in with ChatGPT ({text[:200]!r}). Run `codex login`; API keys are refused")
        info = {"login": text.splitlines()[-1][:120] if text else ""}
    else:
        raise SubscriptionError(f"unknown backend {backend!r}")
    _PREFLIGHT[backend] = info
    return info


def price_of(model: str) -> tuple[float, float, float] | None:
    try:
        if str(HOSTS) not in sys.path:
            sys.path.append(str(HOSTS))
        import report  # noqa: PLC0415 - the report's price table is the one source when it knows the model
        prices = report.PRICES.get(model) or report.PRICES.get(model.split("/")[-1])
        if prices:
            return prices
    except Exception:  # noqa: BLE001
        pass
    return NOTIONAL_PRICES.get(model)


def notional_cost(model: str, input_tokens: int, cached: int, output_tokens: int,
                  cache_write: int = 0) -> tuple[float | None, str]:
    prices = price_of(model)
    if not prices:
        return None, COST_UNKNOWN
    p_in, p_cached, p_out = prices
    long_request = model.split("/")[-1] == "gpt-6.1-sol" and input_tokens > 272_000
    input_multiplier, output_multiplier = (2.0, 1.5) if long_request else (1.0, 1.0)
    return (input_multiplier * (max(0, input_tokens - cached - cache_write) * p_in
                               + cached * p_cached + cache_write * p_in * 1.25)
            + output_tokens * p_out * output_multiplier), COST_NOTIONAL


# --- Claude stream-json ------------------------------------------------------------------------------------------------

def claude_usage(result: dict, calls: int | None = None) -> dict:
    """A Claude `result` event -> the host's usage shape (input includes cache reads and writes; `cached` = cache reads)."""
    usage = result.get("usage") or {}
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_write = usage.get("cache_creation_input_tokens") or 0
    total_in = (usage.get("input_tokens") or 0) + cache_read + cache_write
    cost = result.get("total_cost_usd")
    return {"input_tokens": total_in, "cached": cache_read, "cache_write": cache_write, "output_tokens": usage.get("output_tokens") or 0,
            "reasoning": (usage.get("output_tokens_details") or {}).get("thinking_tokens") or 0,
            "calls": calls if calls is not None else (result.get("num_turns") or 0),
            "cost_usd": cost, "cost_source": COST_NOTIONAL if cost is not None else COST_UNKNOWN,
            "duration_ms": result.get("duration_ms"), "duration_api_ms": result.get("duration_api_ms")}


def check_claude_init(event: dict) -> None:
    source = event.get("apiKeySource")
    if source != "none":
        raise SubscriptionError(f"claude -p started with apiKeySource={source!r}: that is key billing, not the subscription - stopped")


def _data_url(url: str) -> tuple[str, str]:
    match = re.match(r"data:([^;]+);base64,(.*)$", url, re.S)
    if not match:
        raise ValueError("only base64 data URLs are supported for CLI review images")
    return match.group(1), match.group(2)


def _payload_parts(payload: dict) -> list[dict]:
    parts = []
    for message in payload.get("input") or []:
        content = message.get("content")
        if isinstance(content, str):
            parts.append({"type": "input_text", "text": content})
        else:
            parts.extend(content or [])
    return parts


def claude_review_message(payload: dict) -> dict:
    """The Responses payload's user content -> one Claude stream-json user message (text and base64 images, in order)."""
    blocks = []
    for item in _payload_parts(payload):
        if item.get("type") == "input_text":
            blocks.append({"type": "text", "text": item.get("text") or ""})
        elif item.get("type") == "input_image":
            mime, data = _data_url(item["image_url"])
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
    return {"type": "user", "message": {"role": "user", "content": blocks}, "parent_tool_use_id": None}


def claude_review_argv(model: str, effort: str | None, system_file: Path) -> list[str]:
    argv = [claude_bin(), "-p", "--safe-mode", "--strict-mcp-config", "--setting-sources", "", "--model", model,
            "--system-prompt-file", str(system_file), "--tools", "", "--max-turns", "1", "--no-session-persistence",
            "--permission-mode", "dontAsk", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
    if effort in CLAUDE_EFFORTS:
        argv[argv.index("--system-prompt-file"):argv.index("--system-prompt-file")] = ["--effort", effort]
    return argv


def parse_claude_stream(lines, on_event=None) -> dict:
    """Read a Claude stream-json output: assert the subscription at init, collect the result, text and rate-limit info."""
    out: dict = {"init": None, "result": None, "rate_limit": None, "texts": [], "message_ids": [], "retries": []}
    for raw in lines:
        raw = raw.strip() if isinstance(raw, str) else raw.decode("utf-8", "replace").strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind, sub = event.get("type"), event.get("subtype")
        if kind == "system" and sub == "init":
            out["init"] = event
            check_claude_init(event)
        elif kind == "rate_limit_event":
            out["rate_limit"] = event.get("rate_limit_info")
        elif kind == "system" and sub == "api_retry":
            out["retries"].append({k: event.get(k) for k in ("error", "attempt", "retry_delay_ms") if k in event})
        elif kind == "assistant":
            message = event.get("message") or {}
            if message.get("id") and message["id"] not in out["message_ids"]:
                out["message_ids"].append(message["id"])
            out["texts"].extend(c.get("text", "") for c in message.get("content") or [] if c.get("type") == "text")
        elif kind == "result":
            out["result"] = event
        if on_event:
            on_event(event)
    return out


# --- Codex --json ----------------------------------------------------------------------------------------------------

def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))


def codex_base_argv(model: str, effort: str | None, instructions_file: Path | None, *, reasoning_summary: str | None = None) -> list[str]:
    argv = ["--json", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules", "-m", model,
            "-c", 'approval_policy="never"', "-c", "project_doc_max_bytes=0", "-c", 'web_search="disabled"',
            "-c", "include_apps_instructions=false"]
    if reasoning_summary is not None:
        if reasoning_summary not in {"auto", "concise", "detailed", "none"}:
            raise ValueError("Invalid model_reasoning_summary setting")
        argv += ["-c", f'model_reasoning_summary="{reasoning_summary}"']
    if effort in CODEX_EFFORTS:
        argv += ["-c", f'model_reasoning_effort="{effort}"']
    if instructions_file:
        argv += ["-c", f"model_instructions_file={json.dumps(str(instructions_file))}"]
    for feature in CODEX_DISABLED_FEATURES:
        argv += ["--disable", feature]
    return argv


def codex_usage(usage: dict | None, model: str, calls: int) -> dict:
    usage = usage or {}
    inp, cached, out = usage.get("input_tokens") or 0, usage.get("cached_input_tokens") or 0, usage.get("output_tokens") or 0
    cost, source = notional_cost(model, inp, cached, out, usage.get("cache_write_input_tokens") or 0)
    return {"input_tokens": inp, "cached": cached, "cache_write": usage.get("cache_write_input_tokens") or 0, "output_tokens": out,
            "reasoning": usage.get("reasoning_output_tokens") or 0, "calls": calls, "cost_usd": cost, "cost_source": source}


def codex_request_usage(calls: list[dict], model: str) -> dict:
    """Price each recorded request separately; invocation totals are not context sizes."""
    requests = [codex_usage(call.get("usage"), model, 1) for call in calls]
    total = {key: sum(row[key] for row in requests)
             for key in ("input_tokens", "cached", "cache_write", "output_tokens", "reasoning", "calls")}
    known = bool(requests) and all(row["cost_usd"] is not None for row in requests)
    total.update(cost_usd=sum(row["cost_usd"] for row in requests) if known else None,
                 cost_source=COST_NOTIONAL if known else COST_UNKNOWN,
                 cost_basis="standard-api-equivalent-per-request",
                 pricing_source="https://developers.openai.com/api/docs/models/gpt-6.1-sol"
                 if model.split("/")[-1] == "gpt-6.1-sol" else None)
    return total


def codex_rollout(thread_id: str, home: Path | None = None) -> Path | None:
    sessions = (home or codex_home()) / "sessions"
    if not thread_id or not sessions.is_dir():
        return None
    found = sorted(sessions.rglob(f"rollout-*-{thread_id}.jsonl"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def _iso_epoch(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_rollout(path: Path, since: float | None = None) -> dict:
    """Per-request usage (token_usage_record), the latest rate-limit window and the model/effort the thread really ran on."""
    calls, rate, context = [], None, {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        at = _iso_epoch(record.get("timestamp"))
        if since is not None and at is not None and at < since - 1:
            continue
        payload = record.get("payload") or {}
        if record.get("type") == "token_usage_record":
            calls.append({"at": at, "usage": payload.get("usage") or {}, "response_id": payload.get("response_id")})
        elif record.get("type") == "turn_context":
            context = {"model": payload.get("model"), "effort": payload.get("effort"), "sandbox": (payload.get("sandbox_policy") or {}).get("type")}
        elif payload.get("type") == "token_count" and payload.get("rate_limits"):
            limits = payload["rate_limits"]
            rate = {"plan_type": limits.get("plan_type"), "primary": limits.get("primary"), "secondary": limits.get("secondary"),
                    "has_credits": (limits.get("credits") or {}).get("has_credits"), "rate_limit_reached_type": limits.get("rate_limit_reached_type")}
    return {"calls": calls, "rate_limit": rate, "context": context}


def parse_codex_stream(lines, on_event=None) -> dict:
    out: dict = {"thread_id": None, "usage": None, "texts": [], "errors": [], "tool_calls": 0, "shell_calls": 0}
    for raw in lines:
        raw = raw.strip() if isinstance(raw, str) else raw.decode("utf-8", "replace").strip()
        if not raw:
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        item = event.get("item") or {}
        if kind == "thread.started":
            out["thread_id"] = event.get("thread_id")
        elif kind == "turn.completed":
            out["usage"] = event.get("usage")
        elif kind in ("turn.failed", "error"):
            out["errors"].append(str(event.get("error") or event.get("message") or event)[:500])
        elif kind == "item.started" and item.get("type") in ("mcp_tool_call", "command_execution"):
            out["tool_calls"] += 1
            out["shell_calls"] += item.get("type") == "command_execution"
        elif kind == "item.completed" and item.get("type") == "agent_message":
            out["texts"].append(item.get("text") or "")
        if on_event:
            on_event(event)
    return out


# --- single-shot review calls ----------------------------------------------------------------------------------------

def _run(argv: list[str], stdin_text: str, cwd: Path, env: dict) -> tuple[int, list[str], str]:
    """Run a CLI to completion. No wall-clock limit (user policy): the model call is allowed to finish."""
    proc = subprocess.run(argv, input=stdin_text.encode("utf-8"), capture_output=True, cwd=str(cwd), env=env)
    return proc.returncode, proc.stdout.decode("utf-8", "replace").splitlines(), proc.stderr.decode("utf-8", "replace")


def review_claude(payload: dict, run=None) -> tuple[str, dict]:
    preflight("claude")
    run = run or _run
    model = payload["model"]
    effort = (payload.get("reasoning") or {}).get("effort")
    with tempfile.TemporaryDirectory(prefix="pptm-review-") as scratch:
        system_file = Path(scratch) / "system.md"
        system_file.write_text(payload.get("instructions") or "", encoding="utf-8")
        message = claude_review_message(payload)
        started = time.time()
        code, lines, stderr = run(claude_review_argv(model, effort, system_file), json.dumps(message) + "\n", Path(scratch), scrub_env())
    parsed = parse_claude_stream(lines)
    result = parsed["result"]
    if parsed["init"] is None or result is None:
        raise CliCallError(f"claude -p ended without a result (exit {code}): {stderr.strip()[-400:]}")
    if result.get("is_error"):
        raise CliCallError(f"claude -p review failed: {result.get('subtype')} {result.get('api_error_status')} {str(result.get('result'))[:300]}")
    usage = claude_usage(result, calls=len(parsed["message_ids"]) or 1)
    unexpected = sorted(set(result.get("modelUsage") or {}) - {model})
    return (result.get("result") or "\n".join(parsed["texts"])), {
        "input_tokens": usage["input_tokens"], "cached_tokens": usage["cached"], "output_tokens": usage["output_tokens"],
        "reasoning_tokens": usage["reasoning"], "cost": usage["cost_usd"], "cost_source": usage["cost_source"], "backend": "cli:claude",
        "seconds": round(time.time() - started, 1), "rate_limit": parsed["rate_limit"], "other_models": unexpected or None,
        "api_key_source": (parsed["init"] or {}).get("apiKeySource")}


def codex_review_prompt(payload: dict, image_names: list[str]) -> str:
    lines = []
    if image_names:
        lines.append(f"{len(image_names)} image(s) are attached to this message, in this order: "
                     + "; ".join(f"image {n} = {name}" for n, name in enumerate(image_names, start=1))
                     + ". Where the text below says [image N], it means that attachment.")
    lines.append("Answer directly from what you are given. Do not run commands or use tools.\n")
    n = 0
    for item in _payload_parts(payload):
        if item.get("type") == "input_text":
            lines.append(item.get("text") or "")
        elif item.get("type") == "input_image":
            n += 1
            lines.append(f"[image {n}]")
    return "\n".join(lines)


def review_codex(payload: dict, run=None) -> tuple[str, dict]:
    preflight("codex")
    run = run or _run
    model = payload["model"]
    effort = (payload.get("reasoning") or {}).get("effort")
    with tempfile.TemporaryDirectory(prefix="pptm-review-") as scratch:
        folder = Path(scratch)
        instructions = folder / "instructions.md"
        instructions.write_text(payload.get("instructions") or "", encoding="utf-8")
        images, names = [], []
        for item in _payload_parts(payload):
            if item.get("type") == "input_image":
                mime, data = _data_url(item["image_url"])
                target = folder / f"image_{len(images) + 1:02d}.{'jpg' if 'jpeg' in mime else 'webp' if 'webp' in mime else 'png'}"
                target.write_bytes(base64.b64decode(data))
                images.append(target)
                names.append(target.name)
        last = folder / "last.txt"
        argv = [codex_bin(), "exec", *codex_base_argv(model, effort, instructions), "-s", "read-only", "-C", str(folder), "-o", str(last), "-"]
        for image in images:  # after the `-` prompt marker: `-i a.png -` would read `-` as an image path
            argv += ["--image", str(image)]
        started = time.time()
        since = time.time()
        code, lines, stderr = run(argv, codex_review_prompt(payload, names), folder, scrub_env())
        text = last.read_text(encoding="utf-8", errors="replace") if last.is_file() else ""
    parsed = parse_codex_stream(lines)
    if code != 0 or parsed["usage"] is None:
        raise CliCallError(f"codex exec review failed (exit {code}): {'; '.join(parsed['errors'])[:300]} {stderr.strip()[-300:]}")
    rollout = codex_rollout(parsed["thread_id"] or "")
    audit = read_rollout(rollout, since) if rollout else {"calls": [], "rate_limit": None, "context": {}}
    usage = (codex_request_usage(audit["calls"], model) if audit["calls"]
             else codex_usage(parsed["usage"], model, calls=1))
    return (text or (parsed["texts"][-1] if parsed["texts"] else "")), {
        "input_tokens": usage["input_tokens"], "cached_tokens": usage["cached"], "output_tokens": usage["output_tokens"],
        "reasoning_tokens": usage["reasoning"], "cost": usage["cost_usd"], "cost_source": usage["cost_source"], "backend": "cli:codex",
        "seconds": round(time.time() - started, 1), "rate_limit": audit["rate_limit"], "ran_on": audit["context"] or None,
        "tool_calls": parsed["tool_calls"] or None}


def review(payload: dict, api_base: str) -> tuple[str, dict]:
    backend = backend_of(api_base)
    if backend == "claude":
        return review_claude(payload)
    if backend == "codex":
        return review_codex(payload)
    raise SubscriptionError(f"not a CLI route: {api_base!r}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args[0] != "preflight" or args[1] not in ("claude", "codex", "all"):
        print("usage: subscription_cli.py preflight claude|codex|all")
        return 2
    for backend in (("claude", "codex") if args[1] == "all" else (args[1],)):
        try:
            print(backend, json.dumps(preflight(backend)))
        except SubscriptionError as exc:
            print(f"{backend} REFUSED: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
