#!/usr/bin/env python3
"""Authoring preview loop for the consulting-quality profile.

The author renders a page right after writing it, looks at the image, and either keeps the
page or edits its SVG. This tool owns the mechanics around that look:

    page_review.py render <project> <page> [--crop X,Y,W,H]
    page_review.py review <project> <page>
    page_review.py restore <project> <page> --rev N
    page_review.py note <project> <page> --outcome accepted|unresolved --text "..." [--no-review]
    page_review.py contact-sheet <project>
    page_review.py status <project>

``render`` saves a numbered copy of the SVG under ``.review/backup/`` whenever its content
changed since the last render, renders the page through ``visual_review.py`` (starting the
live-preview server when none is running), counts the revision in ``quality-run.json`` and
prints an ``IMAGE: <path>`` line. A host that shows images to its model attaches every such
path to the tool result; a host that cannot must open the path with its own image tool.

``review`` is the independent reviewer: one fresh model call with no history that receives
only the current render, the page's slide record from ``design_spec.md`` §IX, the reference
slides delivered for the page, and the review language. It must inventory every overlap,
clip, crossing and leftover before it judges the concept, and ends with ``VERDICT: PASS |
EXECUTION_REPAIR | CONCEPT_REPLAN``. The author that drew the page does not see it well
(FORK_RUN_LOG.md, cq-brief1); a call that did not draw it does. The verdict is recorded in
the journal against the reviewed revision, and ``note --outcome accepted`` is refused while
the current revision has no PASS review (``--no-review`` records an explicit exception).
Model and effort: ``PPT_MASTER_REVIEW_MODEL`` (default gpt-5.6-luna) and
``PPT_MASTER_REVIEW_EFFORT`` (default high); the key from ``OPENAI_API_KEY`` or the
``PPT_MASTER_ENV_FILE`` line. A review is not a revision and does not count against the budget.

A revision is a render of changed SVG content. A crop or a second look at unchanged content
is not a revision. The budget is a ceiling, never a target.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
JOURNAL = "quality-run.json"
DEFAULT_REVISION_BUDGET = 3
LINT_FIX_ALLOWANCE = 4  # renders that only fix measured geometry, outside the design-revision budget


def _journal_path(project: Path) -> Path:
    return project / JOURNAL


def load_journal(project: Path) -> dict:
    path = _journal_path(project)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"schema_version": 1, "profile": "consulting-quality", "revision_budget": DEFAULT_REVISION_BUDGET,
            "pages": {}, "references_delivered": [], "deck_review": [], "pptx_inspection": []}


def save_journal(project: Path, journal: dict) -> None:
    journal["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _journal_path(project).write_text(json.dumps(journal, indent=1, ensure_ascii=False), encoding="utf-8")


@contextlib.contextmanager
def journal_lock(project: Path, timeout: float = 60.0):
    """Pages are authored in parallel, each by its own process: one writer at a time on quality-run.json."""
    lock = project / ".review" / "journal.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 120:  # a crashed writer's lock
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise SystemExit(f"the review journal stayed locked for {timeout:.0f}s: {lock}")
            time.sleep(0.05)
        except PermissionError:  # Windows: the holder is deleting it right now
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def update_journal(project: Path, mutate):
    """Read-modify-write under the lock. `mutate(journal)` changes it in place; its return value is passed back."""
    with journal_lock(project):
        journal = load_journal(project)
        result = mutate(journal)
        save_journal(project, journal)
        return result


def _page_entry(journal: dict, stem: str) -> dict:
    return journal["pages"].setdefault(stem, {"renders": 0, "revisions": 0, "last_sha": None, "backups": [], "outcome": None})


def _page_file(project: Path, page: str) -> Path:
    name = page if page.endswith(".svg") else f"{page}.svg"
    target = project / "svg_output" / Path(name).name
    if not target.is_file():
        raise SystemExit(f"no such page: {target}")
    return target


def _server_running(project: Path) -> bool:
    lock = project / "live_preview" / "lock.json"
    if not lock.is_file():
        return False
    try:
        import urllib.request
        port = int(json.loads(lock.read_text(encoding="utf-8"))["port"])
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3) as response:
            served = json.load(response).get("project")
        # another project's server may be answering on the port this lock remembers (two runs raced for it)
        return served is None or Path(served).resolve() == project.resolve()
    except Exception:  # noqa: BLE001 - any failure means "start one"
        return False


def _ensure_server(project: Path) -> None:
    if _server_running(project):
        return
    import hashlib
    import socket
    # Several decks start their servers at the same instant: each project starts its search at its own place in the range,
    # and a start that loses a race for a port tries the next free one.
    offset = int(hashlib.sha1(str(project.resolve()).lower().encode("utf-8")).hexdigest(), 16) % 400
    tried: set[int] = set()
    for _attempt in range(5):
        port = None
        for step in range(400):
            candidate = 6060 + (offset + step) % 400
            if candidate in tried:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if probe.connect_ex(("127.0.0.1", candidate)) != 0:
                    port = candidate
                    break
        if port is None:
            break
        tried.add(port)
        subprocess.run([sys.executable, str(SCRIPTS / "svg_editor" / "server.py"), str(project), "--live", "--daemon", "--no-browser", "--port", str(port)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        for _ in range(20):
            if _server_running(project):
                return
            time.sleep(0.5)
    raise SystemExit("the live-preview server did not start; see live_preview/server.log")


def _render(project: Path, pages: list[str] | None) -> list[dict]:
    _ensure_server(project)
    command = [sys.executable, str(SCRIPTS / "visual_review.py"), str(project)]
    if pages:
        command += ["--pages", *pages]
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    start = proc.stdout.find("{")
    if start < 0:
        raise SystemExit(f"renderer failed (exit {proc.returncode}):\n{proc.stdout[-800:]}\n{proc.stderr[-800:]}")
    report, _ = json.JSONDecoder().raw_decode(proc.stdout[start:])
    return report.get("pages") or report.get("records") or []


def _render_and_lint(project: Path, svg: Path, want_lint: bool) -> tuple[list[dict], dict | None, str | None]:
    """The preview and the geometry lint in ONE browser, with the contract check running beside them in its own process:
    one launch instead of two, and the checker's start-up no longer adds to the wait. Falls back to the separate steps when the
    one-browser path cannot start (the preview then comes from visual_review.py as before)."""
    _ensure_server(project)
    handle = None
    try:
        import page_lint
        import visual_review
        from playwright.sync_api import sync_playwright
        if want_lint:
            handle = page_lint.start_contract(svg)
        server_url = visual_review.discover_server_url(project)
        visual_review.check_server(server_url, project)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel=os.environ.get("PPT_MASTER_BROWSER_CHANNEL") or None)
            try:
                records = visual_review.render_pages(server_url, [svg.name], project / ".preview", browser=browser)
                lint, lint_error = None, None
                if want_lint and any(r.get("ok") for r in records):
                    owned, handle = handle, None  # lint_page owns the contract check from here
                    try:
                        lint = page_lint.lint_page(project, svg.stem, browser=browser, contract_handle=owned)
                    except Exception as exc:  # noqa: BLE001 - a page still renders when the ruler is unavailable
                        lint_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                return records, lint, lint_error
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - the one-browser path failed before a result: take the separate, slower steps
        print(f"(one-browser render unavailable - {type(exc).__name__}: {str(exc)[:160]}; rendering in separate steps)")
        records = _render(project, [svg.name])
        lint, lint_error = None, None
        if want_lint and any(r.get("ok") for r in records):
            try:
                import page_lint
                lint = page_lint.lint_page(project, svg.stem)
            except Exception as exc2:  # noqa: BLE001
                lint_error = f"{type(exc2).__name__}: {str(exc2)[:200]}"
        return records, lint, lint_error
    finally:
        if handle is not None:  # started but never handed to the lint (the render failed): stop it, leave nothing behind
            import page_lint
            page_lint.stop_contract(handle)


def cmd_render(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    svg = _page_file(project, args.page)
    stem = svg.stem
    content = svg.read_bytes()
    digest = hashlib.sha256(content).hexdigest()

    def begin(journal: dict) -> bool:
        entry = _page_entry(journal, stem)
        changed = digest != entry.get("last_sha")
        if changed:
            previous_lint = entry.get("lint") or {}
            fixing_geometry = previous_lint.get("sha") == entry.get("last_sha") and (previous_lint.get("hard", 0) + previous_lint.get("soft", 0)) > 0
            if entry["last_sha"] is not None and fixing_geometry and entry.get("lint_fixes", 0) < LINT_FIX_ALLOWANCE:
                entry["lint_fixes"] = entry.get("lint_fixes", 0) + 1  # nudging a label off a line is not a design revision
            elif entry["last_sha"] is not None:
                entry["revisions"] += 1
            backup_dir = project / ".review" / "backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            rev = len(entry["backups"])
            backup = backup_dir / f"{stem}.rev{rev}.svg"
            backup.write_bytes(content)
            entry["backups"].append({"rev": rev, "sha": digest, "file": str(backup.relative_to(project)).replace("\\", "/")})
            entry["last_sha"] = digest
            entry["outcome"] = None
        return changed

    changed = update_journal(project, begin)
    want_lint = not args.crop and os.environ.get("PPT_MASTER_NO_LINT") != "1"
    records, lint, lint_error = _render_and_lint(project, svg, want_lint)  # slow, and outside the lock: other pages render at the same time
    record = next((r for r in records if r.get("ok")), None)
    if record is None:
        print(f"render failed: {json.dumps(records)[:1500]}")
        return 4

    def finish(journal: dict) -> tuple[dict, int]:
        entry = _page_entry(journal, stem)
        entry["renders"] += 1
        return dict(entry), journal.get("revision_budget", DEFAULT_REVISION_BUDGET)

    entry, budget = update_journal(project, finish)
    import page_lint
    if lint is not None:
        summary = {"sha": digest, "hard": sum(1 for f in lint["blockers"] if f.get("hard")), "soft": sum(1 for f in lint["blockers"] if not f.get("hard")),
                   "items": [{k: f.get(k) for k in ("kind", "hard", "rect", "message", "crop", "item")} for f in lint["blockers"]], "notes": [f["message"] for f in lint["notes"]][:6]}
        update_journal(project, lambda journal: _page_entry(journal, stem).__setitem__("lint", summary))
    elif lint_error:
        print(f"geometry lint unavailable: {lint_error}")
    image = Path(record["path"])
    if record.get("all_background"):
        print("warning: the render is a blank surface (a broken reference or a missing asset)")
    if args.crop:
        from PIL import Image
        x, y, w, h = (int(float(v)) for v in args.crop.split(","))
        crop_dir = project / ".preview" / "crops"
        crop_dir.mkdir(parents=True, exist_ok=True)
        with Image.open(image) as source:
            region = source.crop((x, y, x + w, y + h))
            scale = max(1, min(3, 1600 // max(1, w)))
            if scale > 1:
                region = region.resize((region.width * scale, region.height * scale), Image.LANCZOS)
            image = crop_dir / f"{stem}_{x}_{y}_{w}_{h}.png"
            region.save(image)
    current_rev = len(entry["backups"]) - 1
    left = budget - entry["revisions"]
    print(f"page {stem}: rev{current_rev} rendered ({'new content' if changed else 'unchanged content'}); "
          f"revisions used {entry['revisions']} of {budget}")
    if left <= 0:
        print("revision budget exhausted: look at this render, keep the best revision (restore an earlier one if it is better), "
              "and record the outcome with `note` - accepted, or unresolved with the issue named. Do not edit this page again.")
    print(f"IMAGE: {image}")
    if lint is not None:
        print()
        print(page_lint.render_text(lint))
        if entry.get("lint_fixes"):
            print(f"  geometry fixes used {entry['lint_fixes']} of {LINT_FIX_ALLOWANCE} (they do not count as design revisions)")
        if lint.get("overlay"):
            print(f"IMAGE: {lint['overlay']}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    svg = _page_file(project, args.page)
    def restore(journal: dict) -> None:
        entry = journal["pages"].get(svg.stem) or {}
        match = next((b for b in entry.get("backups", []) if b["rev"] == args.rev), None)
        if match is None:
            raise SystemExit(f"no rev{args.rev} recorded for {svg.stem}")
        svg.write_bytes((project / match["file"]).read_bytes())
        entry["last_sha"] = match["sha"]
        entry.setdefault("restored", []).append(args.rev)

    update_journal(project, restore)
    print(f"restored {svg.stem} to rev{args.rev}; render it again before judging it")
    return 0


REVIEW_INSTRUCTIONS = """You are an independent visual reviewer of one rendered slide. You did not draw it and you have no stake in it. You receive the slide record it was drawn from, the review language of this profile, any reference slide the author was shown (a reference lends structure and devices, never content), the rendered image, and the result of a geometry lint that measured the page in the browser.

Work in this order:
1. DEFECTS.
   a. Rule on every item the geometry lint FLAGGED, from its zoomed crop: `item N: DEFECT - why` when it hurts reading or looks like a mistake (a line through the body of the letters, text straddling a box edge, a label spilling out of its box), or `item N: ACCEPTABLE - why` when you have looked and it is plainly intended and legible (a guide line crossing a label's margin, a label that deliberately continues past its bar onto clear space). The author has left these in; you decide.
   b. Then list what a ruler cannot know, scanning the image top to bottom: a stray or empty element; text too small or low in contrast to read; crowding that blocks the reading path; or visible wording that a new reader cannot understand. On a diagram, check it against the DIAGRAM CONTRACT below: a connector without one arrowhead at its target, a loop that does not end with a head on the node it returns to, decision exits written as a phrase instead of drawn as labelled arrows to end states, a label floating unattached, a number with no matching marker, a boundary that leaves out what its words include, a decorative axis - each is a DEFECT. Open space is acceptable when it supports the page's focus; call it a defect only when content is crowded elsewhere or the page cannot answer its question. Do not manufacture an item: a clean page has none.
2. CONCEPT CHECK. Read the image as a person who has not seen the record. State what question the page seems to answer and what its visual actually shows. Then compare with the record's Audience question, Visual task, Relationships, Hierarchy and nonbinding Composition. Can a reader answer the intended question from the marks and labels, including the direction, grouping and evidence? Are diagram nodes scannable where they contain parallel items, or are they prose paragraphs the reader must decode? Does the chosen carrier fit the content better than a simple list, table, example or image would? A reference lends structure, not content. Name each material departure and say whether it is local or structural.
3. VERDICT. PASS when step 1 has no DEFECT and step 2 has no structural departure; EXECUTION_REPAIR when step 1 has a DEFECT or the departures in step 2 are local; CONCEPT_REPLAN whenever step 2 found a structural departure, regardless of how small the local fixes look. Then the single highest-impact change.

Judge only what is visible. End with exactly two lines:
VERDICT: <PASS|EXECUTION_REPAIR|CONCEPT_REPLAN>
BLOCKERS: <count of DEFECT rulings plus the items in 1b>"""


def _api_key(name: str = "OPENAI_API_KEY") -> str:
    key = os.environ.get(name)
    env_file = os.environ.get("PPT_MASTER_ENV_FILE")
    if not key and env_file and Path(env_file).is_file():
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        raise SystemExit("no API key for the reviewer: set OPENAI_API_KEY or PPT_MASTER_ENV_FILE")
    return key


def _review_call_chat(payload: dict, base: str, key: str) -> tuple[str, dict]:
    """The same review through a chat-completions endpoint (Google's OpenAI-compatible one: base .../v1beta/openai), for a
    reviewer that has no Responses API."""
    import urllib.request
    parts = [{"type": "text", "text": item["text"]} if item["type"] == "input_text" else {"type": "image_url", "image_url": {"url": item["image_url"]}}
             for item in payload["input"][0]["content"]]
    body = {"model": payload["model"], "messages": [{"role": "system", "content": payload.get("instructions") or ""}, {"role": "user", "content": parts}]}
    if (payload.get("reasoning") or {}).get("effort"):
        body["reasoning_effort"] = payload["reasoning"]["effort"]
    request = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=900) as response:
        answer = json.load(response)
    usage = answer.get("usage") or {}
    return (answer["choices"][0]["message"].get("content") or ""), {"input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens")}


REVIEW_RETRIES = 2  # at most two retries after a failed attempt, for HTTP and CLI reviewers alike
REVIEW_BACKOFF_S = (15, 45)
_RETRY_HTTP = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}


def _review_call_once(payload: dict, base: str) -> tuple[str, dict]:
    """One review request. `cli:claude` / `cli:codex` go to the subscription CLI (subscription_cli.py); anything else is a Responses API
    endpoint (or Google's chat-completions one)."""
    import urllib.request
    import subscription_cli
    if subscription_cli.backend_of(base):
        return subscription_cli.review(payload, base)
    key_var = os.environ.get("PPT_MASTER_REVIEW_KEY_VAR", "OPENAI_API_KEY")
    if "openrouter" in base and os.environ.get("PPT_MASTER_REVIEW_PROVIDER"):
        payload = {**payload, "provider": json.loads(os.environ["PPT_MASTER_REVIEW_PROVIDER"])}
    if "generativelanguage.googleapis.com" in base:
        text, usage = _review_call_chat(payload, base, _api_key(key_var))
    else:
        request = urllib.request.Request(base + "/responses", data=json.dumps(payload).encode("utf-8"),
                                         headers={"Authorization": f"Bearer {_api_key(key_var)}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=900) as response:
            body = json.load(response)
        text = "\n".join(c.get("text", "") for item in body.get("output") or [] if item.get("type") == "message"
                         for c in item.get("content") or [] if c.get("type") == "output_text")
        usage = body.get("usage") or {}
    usage = dict(usage)
    usage.setdefault("backend", "http")
    usage.setdefault("cost_source", "billed-api")  # a keyed endpoint bills per call; the cost may be priced later (run_report.REVIEWER_PRICES)
    return text, usage


def _retryable(exc: BaseException) -> bool:
    import http.client
    import urllib.error
    import subscription_cli
    if isinstance(exc, subscription_cli.SubscriptionError):  # auth or key billing: never retried, never worked around
        return False
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRY_HTTP
    return isinstance(exc, (subscription_cli.CliCallError, urllib.error.URLError, ConnectionError, TimeoutError, OSError,
                            http.client.HTTPException, json.JSONDecodeError))


def _review_call(payload: dict) -> tuple[str, dict]:
    """One review with no history, retried at most twice (15 s, then 45 s) on a transient failure. Returns (text, usage); usage carries
    `backend`, `cost_source` and `attempts`. PPT_MASTER_REVIEW_API_BASE / _KEY_VAR / _PROVIDER point it at another endpoint (OpenRouter)
    or at a subscription CLI (`cli:claude`, `cli:codex`), so the reviewer can come from a different model family than the author."""
    base = os.environ.get("PPT_MASTER_REVIEW_API_BASE", "https://api.openai.com/v1").strip().rstrip("/")
    failures = []
    for attempt in range(REVIEW_RETRIES + 1):
        try:
            text, usage = _review_call_once(payload, base)
            usage["attempts"] = attempt + 1
            if failures:
                usage["failed_attempts"] = failures
            return text, usage
        except Exception as exc:  # noqa: BLE001 - classified below
            failures.append(f"{type(exc).__name__}: {str(exc)[:200]}")
            if attempt >= REVIEW_RETRIES or not _retryable(exc):
                raise
            print(f"[review] attempt {attempt + 1} failed ({failures[-1]}); retrying in {REVIEW_BACKOFF_S[attempt]}s", file=sys.stderr, flush=True)
            time.sleep(REVIEW_BACKOFF_S[attempt])
    raise RuntimeError("unreachable")


def _telemetry(project: Path, record: dict) -> None:
    """One line in the runner's runner.jsonl (PPT_MASTER_TELEMETRY_FILE, set by deck_runner). One O_APPEND write per line, so parallel
    page sessions and the runner never interleave inside a line."""
    target = os.environ.get("PPT_MASTER_TELEMETRY_FILE")
    if not target:
        return
    from datetime import datetime, timezone
    now = time.time()
    line = {"at": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "t": round(now, 3), "project": project.name, **record}
    try:
        fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, (json.dumps(line, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:  # telemetry never fails a review
        pass


def _slide_record(project: Path, stem: str) -> str:
    """The page's §IX block, located by the leading page number of its file stem."""
    import re
    number = re.match(r"(\d+)", stem)
    spec = project / "design_spec.md"
    if not number or not spec.is_file():
        return ""
    text = spec.read_text(encoding="utf-8")
    match = re.search(rf"(#### Slide {int(number.group(1)):02d}\b.*?)(?=\n#### Slide |\n### |\n## |\Z)", text, re.S)
    return match.group(1).strip() if match else ""


def _diagram_contract() -> str:
    """The Diagram contract section of diagram-clarity.md: what a reviewer holds every diagram to (authors get the whole file)."""
    import re
    path = SCRIPTS.parent / "references" / "diagram-clarity.md"
    if not path.is_file():
        return ""
    match = re.search(r"^## Diagram contract.*?(?=^## |\Z)", path.read_text(encoding="utf-8"), re.S | re.M)
    return match.group(0).strip() if match else ""


def _page_references(project: Path, stem: str, journal: dict) -> list[Path]:
    import re
    number = re.match(r"(\d+)", stem)
    keys = {stem, stem + ".svg"}
    if number:
        keys.add(f"P{int(number.group(1)):02d}")
    images = []
    for item in journal.get("references_delivered") or []:
        if item.get("page") in keys and not item.get("counterexample") and not str(item.get("id", "")).startswith("sheet:"):
            path = Path(item.get("image", ""))
            if path.is_file() and path not in images:
                images.append(path)
    return images[:3]


def _image_item(path: Path) -> list[dict]:
    import base64
    mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    return [{"type": "input_text", "text": f"image: {path.name}"},
            {"type": "input_image", "image_url": f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")}]


def cmd_review(args: argparse.Namespace) -> int:
    import re
    project = Path(args.project).resolve()
    svg = _page_file(project, args.page)
    stem = svg.stem
    journal = load_journal(project)
    entry = journal["pages"].get(stem) or {}
    digest = hashlib.sha256(svg.read_bytes()).hexdigest()
    image = project / ".preview" / f"{stem}.png"
    if not entry.get("renders") or entry.get("last_sha") != digest or not image.is_file():
        raise SystemExit("render this revision first: the reviewer judges the current render, never the markup")
    previous = entry.get("review") or {}
    if previous.get("sha") == digest and previous.get("verdict") != "UNPARSED":
        raise SystemExit(f"this render was already reviewed: {previous.get('verdict')} with {previous.get('blockers')} blocker(s) ({previous.get('file')}). "
                         "Fix the listed items, render, then review the new revision; a second opinion on an unchanged render is not asked for")
    lint = entry.get("lint") or {}
    flagged = []
    if lint.get("sha") == digest:
        if lint.get("hard", 0):
            raise SystemExit(f"the geometry lint measured {lint['hard']} certain defect(s) on this render (text on text, invisible or off-canvas text, a contract error): "
                             "fix them and render again - the reviewer is not asked while one stands")
        flagged = [item for item in lint.get("items") or [] if not item.get("hard")]
        if len(flagged) > 8:
            raise SystemExit(f"the geometry lint flagged {len(flagged)} places on this render: too many to be intended. Fix them and render again before asking the reviewer")
    record = _slide_record(project, stem) or "(no slide record found in design_spec.md §IX for this page)"
    language = SCRIPTS.parent / "references" / "consulting-review.md"
    content = [{"type": "input_text", "text": "SLIDE RECORD (design_spec.md §IX):\n\n" + record}]
    if language.is_file():
        content.append({"type": "input_text", "text": "REVIEW LANGUAGE (consulting-review.md):\n\n" + language.read_text(encoding="utf-8")})
    contract = _diagram_contract()
    if contract:
        content.append({"type": "input_text", "text": "DIAGRAM CONTRACT (diagram-clarity.md):\n\n" + contract})
    references = _page_references(project, stem, journal)
    for ref in references:
        content.append({"type": "input_text", "text": "REFERENCE SLIDE the author was shown (structure only, never content):"})
        content.extend(_image_item(ref))
    content.append({"type": "input_text", "text": "RENDERED SLIDE to review:"})
    content.extend(_image_item(image))
    if lint.get("sha") == digest:
        if flagged:
            listing = "\n".join(f"  item {item.get('item') or n}: {item['kind']} - {item['message']}" for n, item in enumerate(flagged, start=1))
            content.append({"type": "input_text", "text": "GEOMETRY LINT. The page was measured in the browser. No text overlaps text, none is off the canvas or invisible, and the export "
                            "contract passes. It FLAGGED the places below as probable defects; each has a zoomed crop. Rule on every one in step 1: DEFECT or ACCEPTABLE, with a reason.\n" + listing})
            for item in flagged:
                if item.get("crop") and Path(item["crop"]).is_file():
                    content.append({"type": "input_text", "text": f"zoomed crop of item {item.get('item')}:"})
                    content.extend(_image_item(Path(item["crop"])))
        else:
            content.append({"type": "input_text", "text": "GEOMETRY LINT. The page was measured in the browser: no text overlaps text, no line runs through text, no text leaves its "
                            "shape, nothing is off the canvas, and the export contract passes. Do not hunt for such collisions; judge what a ruler cannot."})
    model = os.environ.get("PPT_MASTER_REVIEW_MODEL", "gpt-5.6-luna")
    effort = os.environ.get("PPT_MASTER_REVIEW_EFFORT", "high")
    payload = {"model": model, "instructions": REVIEW_INSTRUCTIONS, "store": False, "input": [{"role": "user", "content": content}]}
    if effort and effort != "none":  # a model without a reasoning dial takes none
        payload["reasoning"] = {"effort": effort}
    started = time.time()
    text, usage = _review_call(payload)
    # The two closing lines, tolerating markdown around them ("## VERDICT\n\nPASS - ...", "**BLOCKERS:** 0").
    verdict_match = re.search(r"VERDICT\W{0,12}(PASS|EXECUTION_REPAIR|CONCEPT_REPLAN)\b", text, re.I)
    blockers_match = re.search(r"BLOCKERS\W{0,8}(\d+)", text, re.I)
    verdict = verdict_match.group(1) if verdict_match else "UNPARSED"
    blockers = int(blockers_match.group(1)) if blockers_match else None
    rev = max(0, len(entry.get("backups") or []) - 1)
    reviews_dir = project / ".review" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    out = reviews_dir / f"{stem}.rev{rev}.md"
    out.write_text(f"# {stem} rev{rev} - independent review\n\nmodel {model} effort {effort} - {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n{text.strip()}\n", encoding="utf-8")
    review = {"sha": digest, "rev": rev, "lint_items_ruled": len(flagged), "verdict": verdict, "blockers": blockers, "file": str(out.relative_to(project)).replace("\\", "/"),
              "model": model, "effort": effort, "references": [str(r) for r in references], "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "usage": {k: usage.get(k) for k in ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "cost", "cost_source", "backend", "attempts")},
              "seconds": round(time.time() - started, 1)}

    def keep(current: dict) -> None:  # the reviewer call ran outside the lock; only this page's entry is written back
        page = _page_entry(current, stem)
        page["review"] = review
        page.setdefault("review_log", []).append({k: review[k] for k in ("rev", "verdict", "model", "usage", "seconds")})

    update_journal(project, keep)
    _telemetry(project, {"event": "model_call", "stage": "page_review", "page": stem, "rev": rev, "verdict": verdict, "model": model, "effort": effort,
                         "backend": usage.get("backend"), "outcome": "ok", "wall_s": review["seconds"], "attempts": usage.get("attempts"),
                         "usage": {"input_tokens": usage.get("input_tokens") or 0, "cached": usage.get("cached_tokens") or 0,
                                   "output_tokens": usage.get("output_tokens") or 0, "reasoning": usage.get("reasoning_tokens") or 0, "calls": 1},
                         "cost_usd": usage.get("cost"), "cost_source": usage.get("cost_source")})
    print(text.strip())
    print(f"\n[review] {stem} rev{rev}: {verdict}, blockers {blockers if blockers is not None else '?'} ({time.time() - started:.0f}s); "
          + ("record `accepted` only after every blocker is fixed and a new render is reviewed" if verdict != "PASS" else "this revision may be accepted"))
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    svg = _page_file(project, args.page)
    journal = load_journal(project)
    entry = journal["pages"].setdefault(svg.stem, {"renders": 0, "revisions": 0, "last_sha": None, "backups": [], "outcome": None})
    if not entry.get("renders"):
        raise SystemExit("this page has never been rendered: an outcome is recorded only for a page that was looked at")
    digest = hashlib.sha256(svg.read_bytes()).hexdigest()
    review = entry.get("review") or {}
    text = args.text.strip()
    if args.outcome == "accepted" and not getattr(args, "no_review", False):
        if review.get("sha") != digest:
            raise SystemExit("no independent review of this revision: run `review` on the current render before recording `accepted`")
        if review.get("verdict") != "PASS":
            raise SystemExit(f"the independent review of this revision returned {review.get('verdict')} with {review.get('blockers')} blocker(s) "
                             f"({review.get('file')}): fix them, render, and review again - or record `unresolved` with the issue named")
    elif args.outcome == "accepted":
        text += "\n[accepted without an independent review of this revision]"
    notes_dir = project / ".review" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    with (notes_dir / f"{svg.stem}.md").open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {time.strftime('%Y-%m-%d %H:%M:%S')} - {args.outcome}\n\n{text}\n")

    def record(current: dict) -> None:
        page = _page_entry(current, svg.stem)
        page["outcome"] = args.outcome
        page["outcome_sha"] = digest

    update_journal(project, record)
    print(f"{svg.stem}: {args.outcome}")
    return 0


def build_contact_sheet(images: list[Path], out: Path, columns: int = 3, cell_width: int = 640) -> Path:
    from PIL import Image, ImageDraw
    thumbs = []
    for path in images:
        with Image.open(path) as source:
            ratio = cell_width / source.width
            thumbs.append((path.stem, source.convert("RGB").resize((cell_width, int(source.height * ratio)), Image.LANCZOS)))
    if not thumbs:
        raise SystemExit("no page images to put on a contact sheet")
    cell_height = max(t.height for _, t in thumbs)
    label, gap = 22, 12
    rows = (len(thumbs) + columns - 1) // columns
    columns = min(columns, len(thumbs))
    sheet = Image.new("RGB", (columns * (cell_width + gap) + gap, rows * (cell_height + label + gap) + gap), (236, 236, 232))
    draw = ImageDraw.Draw(sheet)
    for index, (name, thumb) in enumerate(thumbs):
        x = gap + (index % columns) * (cell_width + gap)
        y = gap + (index // columns) * (cell_height + label + gap)
        draw.text((x, y + 3), f"{index + 1}. {name}", fill=(40, 40, 40))
        sheet.paste(thumb, (x, y + label))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def cmd_contact_sheet(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    records = _render(project, None)
    failed = [r.get("page") for r in records if not r.get("ok")]
    images = [Path(r["path"]) for r in records if r.get("ok")]
    sheet = build_contact_sheet(sorted(images), project / ".preview" / "contact_sheet.png")
    if failed:
        print(f"pages that failed to render: {failed}")
    print(f"contact sheet of {len(images)} page(s), in roster order")
    print(f"IMAGE: {sheet}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    journal = load_journal(project)
    budget = journal.get("revision_budget", DEFAULT_REVISION_BUDGET)
    for page in sorted(p.stem for p in (project / "svg_output").glob("*.svg")):
        entry = journal["pages"].get(page)
        if not entry:
            print(f"{page}: never rendered")
            continue
        digest = hashlib.sha256(_page_file(project, page).read_bytes()).hexdigest()
        stale = entry.get("outcome") and entry.get("outcome_sha") != digest
        review = entry.get("review") or {}
        review_state = ("none" if not review else review.get("verdict", "?") + (" (stale)" if review.get("sha") != digest else ""))
        print(f"{page}: renders {entry['renders']}, revisions {entry['revisions']}/{budget}, review {review_state}, "
              f"outcome {entry.get('outcome') or 'none'}{' (edited since - look again)' if stale else ''}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render")
    render.add_argument("project")
    render.add_argument("page")
    render.add_argument("--crop", help="X,Y,W,H in canvas pixels: a closer look at one region of the same render")
    render.set_defaults(fn=cmd_render)
    restore = sub.add_parser("restore")
    restore.add_argument("project")
    restore.add_argument("page")
    restore.add_argument("--rev", type=int, required=True)
    restore.set_defaults(fn=cmd_restore)
    review = sub.add_parser("review")
    review.add_argument("project")
    review.add_argument("page")
    review.set_defaults(fn=cmd_review)
    note = sub.add_parser("note")
    note.add_argument("project")
    note.add_argument("page")
    note.add_argument("--outcome", choices=("accepted", "unresolved"), required=True)
    note.add_argument("--text", required=True)
    note.add_argument("--no-review", action="store_true", help="record `accepted` without an independent review of this revision (the exception is written into the note)")
    note.set_defaults(fn=cmd_note)
    sheet = sub.add_parser("contact-sheet")
    sheet.add_argument("project")
    sheet.set_defaults(fn=cmd_contact_sheet)
    status = sub.add_parser("status")
    status.add_argument("project")
    status.set_defaults(fn=cmd_status)
    args = parser.parse_args()
    os.environ.setdefault("PPT_MASTER_PROJECT_PATH", str(Path(args.project).resolve()))
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
