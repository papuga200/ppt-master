"""Thin tool-execution host: drive PPT Master with a model behind the OpenAI Responses API.

PPT Master is an agent skill; it needs a host that lets a model read files, write SVG, run the
skill's scripts and see images. This is that host and nothing more - the workflow lives in the
skill's documents, not here. It is not tied to any vendor's coding agent.

    python hosts/responses_api/host.py --session NAME --task-file task.txt
    python hosts/responses_api/host.py --session NAME --answer "..."      # answer a blocking gate
    python hosts/responses_api/host.py --session NAME --resume-pending    # after a crash mid-turn

- The conversation persists across invocations (`state.json` keeps the last response id), so a
  blocking gate - the model stops with a question - is answered on the next invocation.
- Every `IMAGE: <path>` line a script prints is attached to the tool result as a real image, so a
  rendered page or a matched reference is seen, not merely announced. Deliveries are logged.
- Model, effort and token use are written to the session state and to the `run` block of every
  project journal (`quality-run.json`) touched during the session.
- The API key is read from OPENAI_API_KEY, or from the `OPENAI_API_KEY=` line of the file named by
  PPT_MASTER_ENV_FILE; it is never printed or logged.

Environment: PPT_MASTER_MODEL, PPT_MASTER_EFFORT, PPT_MASTER_REFERENCE_LIBRARY,
PPT_MASTER_BROWSER_CHANNEL, PPT_MASTER_SESSIONS_DIR, PPT_MASTER_ENV_FILE; PPT_MASTER_API_BASE and
PPT_MASTER_API_KEY_VAR point the author at another Responses-API endpoint (OpenRouter:
`https://openrouter.ai/api/v1` with `OPENROUTER_API_KEY`), which is stateless - the host then resends the
saved `history.json` each turn (PPT_MASTER_STATELESS). The skill's own model calls stay on OPENAI_API_KEY. PPT_MASTER_READ_DENY (`;`-separated globs, default
`skills/ppt-master/scripts/**/*.py`) keeps the author out of script source.

Run it on the repository `.venv` (flask for the live-preview server that `page_review.py render`
needs, PyMuPDF, Pillow, Playwright with a browser installed - `python -m playwright install chromium`
- or PPT_MASTER_BROWSER_CHANNEL naming an installed one). The skill's scripts run on the same
interpreter as this host. A profile run takes around a hundred turns; at the `--max-turns` ceiling the
executed tool outputs are kept so `--resume-pending` continues the same turn.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = Path(sys.executable)
SCRIPTS = ROOT / "skills" / "ppt-master" / "scripts"
ENV_FILE = Path(os.environ["PPT_MASTER_ENV_FILE"]) if os.environ.get("PPT_MASTER_ENV_FILE") else None
OUT = Path(os.environ.get("PPT_MASTER_SESSIONS_DIR") or (ROOT / ".host-sessions")).resolve()
MODEL = os.environ.get("PPT_MASTER_MODEL", "gpt-5.6-luna")
API_BASE = os.environ.get("PPT_MASTER_API_BASE", "https://api.openai.com/v1").rstrip("/")
KEY_VAR = os.environ.get("PPT_MASTER_API_KEY_VAR", "OPENAI_API_KEY")
# A stateless endpoint (OpenRouter) keeps no server-side conversation: the host resends the whole history each turn.
STATELESS = os.environ.get("PPT_MASTER_STATELESS", "1" if ("openrouter" in API_BASE or "anthropic.com" in API_BASE) else "0") == "1"
# OpenRouter serves one model from many hosts at very different speeds (14 to 380 tokens/s measured for deepseek-v4.1-flash);
# its default routing favours the cheapest. PPT_MASTER_PROVIDER is a JSON provider-preferences object, e.g.
# {"order": ["Modal", "Together"], "allow_fallbacks": true}: an ordered pin keeps a conversation on one host, so its prompt cache holds.
PROVIDER = json.loads(os.environ["PPT_MASTER_PROVIDER"]) if os.environ.get("PPT_MASTER_PROVIDER") else None
EXTRA_HEADERS = {"HTTP-Referer": "https://github.com/papuga200/ppt-master", "X-Title": "ppt-master"} if "openrouter" in API_BASE else {}
EFFORT = os.environ.get("PPT_MASTER_EFFORT", "high")
LIBRARY = Path(os.environ["PPT_MASTER_REFERENCE_LIBRARY"]).resolve() if os.environ.get("PPT_MASTER_REFERENCE_LIBRARY") else None
SESSION_STARTED = time.time()
MAX_TOOL_OUTPUT = 60_000


def _key(name: str | None = None) -> str:
    name = name or KEY_VAR
    value = os.environ.get(name)
    if value:
        return value
    if ENV_FILE and ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{name} not available")


def _env_for_scripts() -> dict[str, str]:
    env = dict(os.environ)
    try:  # the skill's own model calls (the reviewer, image generation) stay on OpenAI whatever drives the author
        env["OPENAI_API_KEY"] = _key("OPENAI_API_KEY")
    except SystemExit:
        pass
    if os.environ.get("PPT_MASTER_REVIEW_KEY_VAR") and not os.environ.get("PPT_MASTER_REVIEW_API_BASE", "").strip().lower().startswith("cli:"):  # a reviewer from another family than the author (deck_runner sets it per tier)
        try:
            env[os.environ["PPT_MASTER_REVIEW_KEY_VAR"]] = _key(os.environ["PPT_MASTER_REVIEW_KEY_VAR"])
        except SystemExit:
            pass
    env.setdefault("IMAGE_BACKEND", "openai")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _inside(path: str) -> Path:
    resolved = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if ROOT not in resolved.parents and resolved != ROOT:
        raise ValueError(f"path outside the ppt-master checkout: {path}")
    return resolved


READ_DENY = [x for x in os.environ.get("PPT_MASTER_READ_DENY", "skills/ppt-master/scripts/*.py").split(";") if x]


def _read_denied(target: Path) -> bool:
    """The author reads the workflow's documents and the project, never the scripts' source (DeepSeek, mx-deepseek)."""
    rel = target.relative_to(ROOT).as_posix() if target.is_relative_to(ROOT) else str(target)
    from fnmatch import fnmatch
    return any(fnmatch(rel, pattern) for pattern in READ_DENY)


def tool_read_file(path: str, start: int = 1, end: int | None = None) -> str:
    target = _inside(path)
    if _read_denied(target):
        return "not readable by the author: this is script source. The workflow documents under skills/ppt-master (SKILL.md, workflows/, references/, scripts/docs/) say what each script does; run it with run_script."
    if target.is_dir():
        return "\n".join(sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir()))
    if target.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        return "this is an image: use read_image to see it"
    text = target.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    end = end or len(lines)
    chunk = "\n".join(lines[max(0, start - 1):end])
    return chunk[:MAX_TOOL_OUTPUT] + ("\n...[truncated]" if len(chunk) > MAX_TOOL_OUTPUT else "")


def _own_page_only(target: Path, path: str) -> None:
    """A page session (PPT_MASTER_PAGE_FILE, set by the runner) writes one page: its own. Any other SVG under svg_output/ is refused with
    the right name, so a drifted name cannot orphan the page (campaign Q4-r2 P04 wrote `04_gpt_6_luna_high_workhorse_...` for
    `04_gpt_6_luna_high_cut_workhorse_...`, and the run shipped without the planned page)."""
    own = os.environ.get("PPT_MASTER_PAGE_FILE")
    if not own or target.suffix.lower() != ".svg" or target.parent.name != "svg_output":
        return
    own_path = _inside(own)
    if target != own_path:
        raise ValueError(f"this session authors one page, `{own_path.relative_to(ROOT).as_posix()}` (that exact name); `{path}` is not it. "
                         "Write and edit your page under that name.")


def tool_write_file(path: str, content: str) -> str:
    target = _inside(path)
    _own_page_only(target, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {target.relative_to(ROOT)}"


def tool_edit_file(path: str, old: str, new: str) -> str:
    """Exact replacement of one unique passage: a local revision never re-sends the whole page."""
    target = _inside(path)
    _own_page_only(target, path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise ValueError(f"`old` occurs {count} times in {path}; it must occur exactly once (quote more context)")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"edited {target.relative_to(ROOT)} ({len(old)} -> {len(new)} characters)"


def tool_list_dir(path: str = ".") -> str:
    target = _inside(path)
    rows = []
    for p in sorted(target.rglob("*")):
        if any(part in (".venv", ".git", "__pycache__") for part in p.parts):
            continue
        rows.append(f"{p.relative_to(ROOT)}{'/' if p.is_dir() else ''}")
        if len(rows) >= 400:
            rows.append("...[truncated]")
            break
    return "\n".join(rows)


SCRIPT_TIMEOUT_FLOOR_S = 1200


def tool_run_script(script: str, args: list[str] | None = None, timeout_s: int = 900) -> str:
    script = script.replace("\\", "/")
    for prefix in ("skills/ppt-master/scripts/", str(SCRIPTS).replace("\\", "/") + "/"):
        if script.startswith(prefix):
            script = script[len(prefix):]
    script_path = (SCRIPTS / script).resolve()
    if SCRIPTS not in script_path.parents or script_path.suffix != ".py":
        raise ValueError("only the skill's own scripts may be run")
    if not script_path.is_file():
        raise ValueError(f"no such script: {script}")
    safe_args = []
    for item in args or []:
        if item.startswith("-"):
            safe_args.append(item)
        else:
            candidate = ROOT / item
            looks_like_path = " " not in item and ("/" in item or "\\" in item)
            safe_args.append(str(candidate) if candidate.exists() or looks_like_path else item)
    started = time.monotonic()
    # The author picks a timeout per call, and a short one (120 s) killed an independent review that was still working - the call was
    # billed and its verdict lost (Harrowgate, 24 Sep 2026). A review or a render under load is bounded by the script itself, so the
    # author may lengthen the wait but never shorten it below this floor.
    timeout_s = max(int(timeout_s or 0), SCRIPT_TIMEOUT_FLOOR_S)
    proc = subprocess.run(
        [str(PY), str(script_path), *safe_args], cwd=str(ROOT), env=_env_for_scripts(),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout_s,
    )
    _attach_printed_images(proc.stdout)
    out = proc.stdout[-MAX_TOOL_OUTPUT // 2:]
    err = proc.stderr[-MAX_TOOL_OUTPUT // 2:]
    return f"exit {proc.returncode} in {time.monotonic() - started:.1f}s\n--- stdout ---\n{out}\n--- stderr ---\n{err}"


PENDING_IMAGES: list[tuple[str, bytes]] = []
DELIVERED: list[str] = []
_IMAGE_SINK: list[tuple[str, bytes]] | None = None  # set by capture_images(): a caller that returns images with the tool result itself


def _queue_image(path: str, data: bytes) -> None:
    (PENDING_IMAGES if _IMAGE_SINK is None else _IMAGE_SINK).append((path, data))


class capture_images:
    """`with capture_images() as images: HANDLERS[name](**args)` - the images this one call produced, instead of the shared queue
    the Responses loop sends with its next message (the MCP tool server returns them inside the tool result)."""

    def __enter__(self) -> list[tuple[str, bytes]]:
        global _IMAGE_SINK
        self._previous, _IMAGE_SINK = _IMAGE_SINK, []
        return _IMAGE_SINK

    def __exit__(self, *exc) -> None:
        global _IMAGE_SINK
        _IMAGE_SINK = self._previous


def _image_allowed(target: Path) -> bool:
    roots = [ROOT] + ([LIBRARY] if LIBRARY else [])
    return any(root == target or root in target.parents for root in roots)


def _attach_printed_images(stdout: str) -> None:
    """A script announces an image with an `IMAGE: <path>` line; the model then receives the image itself."""
    for line in stdout.splitlines():
        if not line.startswith("IMAGE: "):
            continue
        target = Path(line[len("IMAGE: "):].strip()).resolve()
        if target.is_file() and _image_allowed(target) and target.stat().st_size <= 6_000_000:
            _queue_image(str(target), target.read_bytes())
            DELIVERED.append(str(target))


def tool_read_image(path: str) -> str:
    target = _inside(path)
    if target.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("read_image takes a PNG, JPEG or WebP file")
    data = target.read_bytes()
    if len(data) > 4_000_000:
        raise ValueError("image larger than 4 MB; read a smaller rendering")
    _queue_image(str(target.relative_to(ROOT)), data)
    return f"image {target.relative_to(ROOT)} ({len(data)} bytes) is attached to the next message"


TOOLS = [
    {"type": "function", "name": "read_file", "description": "Read a text file (or list a directory) inside the ppt-master checkout. Paths are relative to the checkout root. Optional 1-based line range.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"}}, "required": ["path"]}},
    {"type": "function", "name": "read_image", "description": "Look at an image file (PNG/JPEG/WebP) inside the checkout; it is shown to you with the next message.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"type": "function", "name": "write_file", "description": "Write a text file inside the ppt-master checkout.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"type": "function", "name": "edit_file", "description": "Replace one exact, unique passage of a text file inside the checkout. Use it for a local revision of a page SVG instead of rewriting the whole file.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}}, "required": ["path", "old", "new"]}},
    {"type": "function", "name": "list_dir", "description": "Recursive listing of a directory inside the checkout.",
     "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}},
    {"type": "function", "name": "run_script", "description": "Run one of the skill's own scripts (a path under skills/ppt-master/scripts, e.g. svg_to_pptx.py or confirm_ui/server.py) with arguments, in the checkout's Python. Returns exit code, stdout and stderr.",
     "parameters": {"type": "object", "properties": {"script": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}, "timeout_s": {"type": "integer"}}, "required": ["script"]}},
]
HANDLERS = {"read_file": tool_read_file, "read_image": tool_read_image, "write_file": tool_write_file, "edit_file": tool_edit_file, "list_dir": tool_list_dir, "run_script": tool_run_script}


def _log(transcript: Path, record: dict) -> None:
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _call(payload: dict, transcript: Path) -> dict:
    if "anthropic.com" in API_BASE:  # Claude: the Messages API through the official SDK, answered in Responses shape (anthropic_backend.py)
        import anthropic_backend
        return anthropic_backend.respond(payload, _key())
    request = urllib.request.Request(
        API_BASE + "/responses", data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json", **EXTRA_HEADERS}, method="POST",
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=1800) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:500]
            _log(transcript, {"event": "http_error", "status": exc.code, "body": body, "attempt": attempt})
            if exc.code in (408, 429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(15 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
            # http.client.IncompleteRead (a body cut off mid-read) is an HTTPException, not an OSError: it killed four page sessions at once (pga-par3)
            # A closed connection or a transport fault is re-sent: the request is idempotent on our side
            # (the same previous_response_id and the same inputs).
            _log(transcript, {"event": "transport_error", "error": repr(exc)[:300], "attempt": attempt})
            if attempt < 3:
                time.sleep(15 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


SYSTEM_FILE = Path(os.environ["PPT_MASTER_SYSTEM_FILE"]) if os.environ.get("PPT_MASTER_SYSTEM_FILE") else None


TOOLS_NOTE = ("Tools: read_file (text files or directory listings, relative to the repository root), read_image (see an image), write_file, edit_file (exact replacement of one unique passage - use it for local SVG revisions), list_dir, "
              "run_script (the skill's own scripts by path under skills/ppt-master/scripts, with arguments; paths in arguments are relative to the repository root). ")
IMAGES_NOTE = "Whenever a script prints an `IMAGE: <path>` line, this host attaches that image to the tool result: you see it with the next message and need not call read_image for it. "


def host_notes(tools_note: str = TOOLS_NOTE, images_note: str = IMAGES_NOTE) -> str:
    """The harness paragraph appended to every system prompt. A CLI host (cli_host.py) swaps the tool and image sentences."""
    return (
        "\n\n# Host notes\n"
        f"You are running inside a tool harness. SKILL_DIR is {ROOT / 'skills' / 'ppt-master'} and the repository root is {ROOT}. "
        + tools_note + images_note +
        "The scripts' Python is the checkout's own; do not cd, install anything, or run other programs. Image generation: run_script image_gen.py with the OpenAI backend "
        "(IMAGE_BACKEND=openai, model gpt-image-2, already configured). The user is present in this chat but not at a browser: use the chat confirmation surface for every "
        "blocking gate. At a blocking gate, stop calling tools and write the gate's content and its question as your reply; the user's answer arrives as the next message. "
        "Never confirm a gate on the user's behalf - unless the user's message explicitly delegates those decisions, in which case follow the workflow's delegation rule, state the decisions you made in one summary, and continue without stopping. When a route is finished, reply with a short plain-text summary naming every artifact path."
    )


def system_prompt(notes: str | None = None) -> str:
    if SYSTEM_FILE:  # a page author (deck_runner.py): its whole brief, identical across the deck's pages so the prefix caches
        text = SYSTEM_FILE.read_text(encoding="utf-8")
    else:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8") + "\n\n" + (ROOT / "skills" / "ppt-master" / "SKILL.md").read_text(encoding="utf-8")
    return text + (host_notes() if notes is None else notes)


def _write_run_blocks(session: str, usage_total: dict, host: str = "responses_api", model: str | None = None, effort: str | None = None,
                      images: int | None = None, started: float | None = None) -> None:
    """Model, effort and spend belong in the journal of every project this session touched."""
    model, effort = model or MODEL, effort or EFFORT
    delivered = len(DELIVERED) if images is None else images
    for journal_path in (ROOT / "projects").glob("*/quality-run.json"):
        if journal_path.stat().st_mtime < (started or SESSION_STARTED):
            continue
        def stamp(journal: dict, session=session) -> None:
            runs = journal.setdefault("run", {})
            earlier = (runs.get(session) or {}).get("images_delivered", 0)
            runs[session] = {"host": host, "model": model, "effort": effort, "usage": usage_total,
                             "images_delivered": earlier + delivered}

        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        from page_review import update_journal  # the journal is shared by pages authored in parallel
        update_journal(journal_path.parent, stamp)


def backend_label() -> str:
    return "anthropic-messages" if "anthropic.com" in API_BASE else "http-responses"


def identity() -> dict:
    """Who runs this session, written into state.json so a later run (deck_runner.sessions_of) can tell the tier and model apart."""
    found = {"model": MODEL, "effort": EFFORT, "backend": backend_label(), "api_base": API_BASE}
    if os.environ.get("PPT_MASTER_TIER"):
        found["tier"] = os.environ["PPT_MASTER_TIER"]
    return found


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # console codepages (GBK, cp1252) cannot print every tool result
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True, help="name under this directory for state and transcript")
    parser.add_argument("--task", help="the first user message (starts a new session)")
    parser.add_argument("--task-file", help="a file holding the first user message")
    parser.add_argument("--max-calls", type=int, default=400, help="deck-level ceiling on model calls across the whole session")
    parser.add_argument("--answer", help="the user's answer at a gate (continues the session)")
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--resume-pending", action="store_true", help="re-send the tool outputs a crashed turn never delivered")
    args = parser.parse_args()
    session_dir = OUT / args.session
    session_dir.mkdir(parents=True, exist_ok=True)
    state_path = session_dir / "state.json"
    transcript = session_dir / "transcript.jsonl"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    state.update(identity())
    if args.task_file:
        args.task = Path(args.task_file).read_text(encoding="utf-8")
    if args.task:
        input_items: list[dict] = [{"role": "user", "content": args.task}]
        previous_id = None
    elif args.answer:
        previous_id = state.get("last_response_id")
        if not previous_id:
            raise SystemExit("no session to continue")
        input_items = [{"role": "user", "content": args.answer}]
    elif args.resume_pending:
        previous_id = state.get("last_response_id")
        input_items = state.get("pending_input") or []
        if not previous_id or not input_items:
            raise SystemExit("nothing pending to resume")
    else:
        raise SystemExit("give --task, --answer or --resume-pending")
    usage_total = state.get("usage_total") or {"input_tokens": 0, "cached": 0, "output_tokens": 0, "reasoning": 0, "calls": 0}
    history_path = session_dir / "history.json"
    history: list = json.loads(history_path.read_text(encoding="utf-8")) if STATELESS and history_path.is_file() and not args.task else []
    _log(transcript, {"event": "start", "model": MODEL, "effort": EFFORT, "api_base": API_BASE, "stateless": STATELESS, "at": time.time(), "task": args.task, "answer": args.answer})
    for turn in range(args.max_turns):
        state["pending_input"] = [item for item in input_items if not (isinstance(item, dict) and item.get("role") == "user" and isinstance(item.get("content"), list))]
        state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
        if STATELESS:
            answered = {x.get("call_id") for x in history if isinstance(x, dict) and x.get("type") == "function_call_output"}
            # a resumed turn's outputs may already be in the saved history: never send one call's output twice
            history.extend(i for i in input_items if not (isinstance(i, dict) and i.get("type") == "function_call_output" and i.get("call_id") in answered))
            input_items = []
            history_path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
        payload = {"model": MODEL, "instructions": system_prompt(), "input": history if STATELESS else input_items, "tools": TOOLS,
                   "reasoning": {"effort": EFFORT}, "store": not STATELESS}
        if previous_id and not STATELESS:
            payload["previous_response_id"] = previous_id
        if PROVIDER and "openrouter" in API_BASE:
            payload["provider"] = PROVIDER
        if usage_total["calls"] >= args.max_calls:
            print(f"call ceiling reached ({args.max_calls}): stopping with the work on disk; continue with --answer and a higher --max-calls")
            break
        requested_at = time.time()
        response = _call(payload, transcript)
        api_s = round(time.time() - requested_at, 2)
        previous_id = response.get("id")
        usage = response.get("usage") or {}
        usage_total["input_tokens"] += usage.get("input_tokens", 0)
        usage_total["cached"] += (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
        usage_total["output_tokens"] += usage.get("output_tokens", 0)
        usage_total["reasoning"] += (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0)
        usage_total["calls"] += 1
        state.update({"last_response_id": previous_id, "usage_total": usage_total, "pending_input": []})
        state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
        outputs = response.get("output") or []
        if STATELESS:
            history.extend(outputs)
        calls = [item for item in outputs if item.get("type") == "function_call"]
        texts = [c.get("text") for item in outputs if item.get("type") == "message" for c in item.get("content") or [] if c.get("type") == "output_text"]
        _log(transcript, {"event": "turn", "turn": turn, "usage": usage, "at": time.time(), "api_s": api_s, "calls": [(c.get("name"), (c.get("arguments") or "")[:300]) for c in calls], "text": "\n".join(texts)[:6000]})
        print(f"turn {turn}: {len(calls)} tool call(s); tokens in {usage.get('input_tokens')} out {usage.get('output_tokens')}", flush=True)
        if not calls:
            (session_dir / "last_message.md").write_text("\n".join(texts), encoding="utf-8")
            print("\n=== MODEL STOPPED (gate or finish) ===\n" + "\n".join(texts))
            break
        input_items = []
        for call in calls:
            name = call.get("name")
            try:
                fn_args = json.loads(call.get("arguments") or "{}")
                result = HANDLERS[name](**fn_args)
            except Exception as exc:  # noqa: BLE001
                result = f"error: {type(exc).__name__}: {exc}"
            _log(transcript, {"event": "tool", "name": name, "args": (call.get("arguments") or "")[:2000], "result": result[:4000], "at": time.time()})
            print(f"  {name} {(call.get('arguments') or '')[:120]} -> {result[:100].replace(chr(10), ' ')}", flush=True)
            input_items.append({"type": "function_call_output", "call_id": call.get("call_id"), "output": result})
        if PENDING_IMAGES:
            content = []
            for rel, data in PENDING_IMAGES:
                mime = "image/jpeg" if rel.lower().endswith((".jpg", ".jpeg")) else "image/webp" if rel.lower().endswith(".webp") else "image/png"
                content.append({"type": "input_text", "text": f"image: {rel}"})
                content.append({"type": "input_image", "image_url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii")})
            _log(transcript, {"event": "images_delivered", "paths": [rel for rel, _ in PENDING_IMAGES]})
            input_items.append({"role": "user", "content": content})
            PENDING_IMAGES.clear()
    else:  # the turn ceiling: keep the executed tool outputs so --resume-pending continues the same turn
        state["pending_input"] = input_items
        state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
        print(f"turn ceiling reached ({args.max_turns}): tool outputs kept; continue with --resume-pending and a higher --max-turns", flush=True)
    _log(transcript, {"event": "end", "usage_total": usage_total, "at": time.time()})
    _write_run_blocks(args.session, usage_total)
    print("usage", usage_total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
