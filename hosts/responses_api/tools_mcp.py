#!/usr/bin/env python3
"""The host's six tools as a minimal stdio MCP server, for a subscription CLI (Claude Code, Codex) that runs the agent loop itself.

    python hosts/responses_api/tools_mcp.py [--env-file mcp_env.json] [--log tools.jsonl]

JSON-RPC 2.0, one message per line on stdin/stdout: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`,
`ping`. No SDK. The tools are `host.HANDLERS` themselves - read_file, read_image, write_file, edit_file, list_dir, run_script -
with every guard they carry (containment in the checkout, READ_DENY on script source, only the skill's own scripts, the
1200 s timeout floor). What differs from the Responses host is where images go: every `IMAGE: <path>` a script prints, and
every `read_image`, comes back INSIDE the tool result as MCP image content (after the text), so the model sees the render
or the reference slide in the same step.

The environment is scrubbed on start (no model API keys, no Claude/MCP plumbing) and then overlaid with `--env-file`
(the runner's PPT_MASTER_* settings and the OS basics, written by cli_host.py; never a key). Model API keys reach the
skill's scripts only when the page reviewer is an HTTP endpoint (PPT_MASTER_REVIEW_API_BASE not `cli:*`) and
PPT_MASTER_SCRIPT_KEYS=1 - a subscription run makes no keyed call.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "skills" / "ppt-master" / "scripts"
SERVER_INFO = {"name": "pptm", "version": "1.0"}
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


def _prepare_env(env_file: str | None) -> None:
    """Scrub, then overlay. Runs BEFORE host is imported: host reads PPT_MASTER_* at import."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    from subscription_cli import scrub_env
    clean = scrub_env()
    if env_file:  # may name PPT_MASTER_ENV_FILE (a path, never a value) when the operator opted in with PPT_MASTER_SCRIPT_KEYS=1
        clean.update(json.loads(Path(env_file).read_text(encoding="utf-8")))
    os.environ.clear()
    os.environ.update(clean)


def _mime(path: str) -> str:
    lower = path.lower()
    return "image/jpeg" if lower.endswith((".jpg", ".jpeg")) else "image/webp" if lower.endswith(".webp") else "image/png"


def tool_list(host) -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "inputSchema": t["parameters"]} for t in host.TOOLS]


def call_tool(host, name: str, arguments: dict | None) -> tuple[dict, dict]:
    """(MCP result, log record). A handler's exception becomes the host's own `error: Type: msg` text with isError set."""
    started = time.time()
    images: list[tuple[str, bytes]] = []
    error = False
    if name not in host.HANDLERS:
        text, error = f"error: unknown tool {name!r}", True
    else:
        try:
            with host.capture_images() as images, contextlib.redirect_stdout(sys.stderr):  # nothing a tool prints may reach the protocol stream
                text = host.HANDLERS[name](**(arguments or {}))
        except Exception as exc:  # noqa: BLE001
            text, error = f"error: {type(exc).__name__}: {exc}", True
    if name == "read_image" and not error:  # the host's wording is for its next-message delivery; here the image is in this result
        text = text.replace("is attached to the next message", "is shown below")
    content: list[dict] = [{"type": "text", "text": text}]
    for path, data in images:
        content.append({"type": "text", "text": f"image: {path}"})
        content.append({"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": _mime(path)})
    result = {"content": content, "isError": error}
    record = {"event": "tool", "name": name, "args": json.dumps(arguments or {}, ensure_ascii=False)[:2000], "result": text[:4000],
              "images": [p for p, _ in images], "seconds": round(time.time() - started, 2), "error": error, "at": time.time()}
    return result, record


def handle(host, message: dict, log_path: Path | None = None) -> dict | None:
    """One JSON-RPC message -> its response (None for a notification)."""
    method, msg_id = message.get("method"), message.get("id")
    if msg_id is None:  # notifications (initialized, cancelled): nothing to answer
        return None
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                                                          "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tool_list(host)}}
    if method == "tools/call":
        params = message.get("params") or {}
        result, record = call_tool(host, params.get("name", ""), params.get("arguments"))
        if log_path:
            with log_path.open("a", encoding="utf-8") as handle_:
                handle_.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve(host, stdin, stdout, log_path: Path | None = None) -> None:
    for raw in stdin:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            if isinstance(message, list):  # a batch
                replies = [r for r in (handle(host, m, log_path) for m in message) if r is not None]
                reply = replies or None
            else:
                reply = handle(host, message, log_path)
        if reply is not None:
            stdout.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", help="JSON of environment variables to overlay after scrubbing (written by cli_host.py)")
    parser.add_argument("--log", help="append one JSON line per tool call here")
    args = parser.parse_args()
    _prepare_env(args.env_file)
    sys.path.insert(0, str(HERE))
    import host  # noqa: PLC0415 - after the environment is final
    if os.environ.get("PPT_MASTER_SCRIPT_KEYS") != "1" or os.environ.get("PPT_MASTER_REVIEW_API_BASE", "").lower().startswith("cli:"):
        # no key file is read for a subscription run
        host._env_for_scripts = lambda: {**os.environ, "PYTHONIOENCODING": "utf-8", "IMAGE_BACKEND": os.environ.get("IMAGE_BACKEND", "openai")}
    serve(host, sys.stdin.buffer, sys.stdout.buffer, Path(args.log) if args.log else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
