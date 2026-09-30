"""Shared offline fixtures for the SVG helpers experiment harness tests (test_exp_harness_*.py). No test functions here.

EXPERIMENT-ONLY (svg-helpers-experiment-20260930). Nothing here calls a model or the network: the Claude CLI is a stub script
(behind a .cmd wrapper on Windows), OpenRouter is a local HTTP stub on 127.0.0.1, and the worktree is mirrored into a temp folder
so the real cli_host.py / tools_mcp.py / host.py run against temp files only.
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import sys
import textwrap
import threading
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
WORKTREE = SCRIPTS.parents[2]
HARNESS = Path(os.environ.get("EXP_HARNESS_DIR") or r"D:\Users\software\ppt-master-runs\svg-helpers-experiment-20260930\harness")
HANDOFF = HARNESS.parent / "handoff_snapshot"
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

MIRROR_FILES = ("hosts/responses_api/host.py", "hosts/responses_api/cli_host.py", "hosts/responses_api/tools_mcp.py",
                "hosts/responses_api/report.py", "skills/ppt-master/scripts/subscription_cli.py")

STUB_CLAUDE = r'''
import json, os, subprocess, sys, uuid

argv = sys.argv[1:]
log = os.environ.get("STUB_ARGV_LOG")
if log:
    with open(log, "a", encoding="utf-8") as h:
        h.write(json.dumps(argv) + "\n")

def emit(event):
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()

if argv[:2] == ["auth", "status"]:
    print(json.dumps({"loggedIn": True, "authMethod": os.environ.get("STUB_AUTH_METHOD", "claude.ai"), "apiProvider": "firstParty",
                      "subscriptionType": "max"}))
    sys.exit(0)

model = argv[argv.index("--model") + 1] if "--model" in argv else "unknown"
effective = os.environ.get("STUB_EFFECTIVE_MODEL") or model
stdin_text = sys.stdin.read()

if "--input-format" in argv:  # a single-shot review
    sid = str(uuid.uuid4())
    emit({"type": "system", "subtype": "init", "apiKeySource": "none", "model": effective, "session_id": sid, "tools": [], "mcp_servers": []})
    text = open(os.environ["STUB_REVIEW_TEXT"], encoding="utf-8").read()
    emit({"type": "assistant", "message": {"id": "msg_r1", "model": effective, "content": [{"type": "text", "text": text}]}, "session_id": sid})
    emit({"type": "result", "subtype": "success", "is_error": False, "num_turns": 1, "result": text, "session_id": sid,
          "total_cost_usd": 0.0421, "usage": {"input_tokens": 900, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 100,
                                              "output_tokens": 700}, "modelUsage": {effective: {"inputTokens": 1000}}})
    sys.exit(0)

# an author session: talk to the pptm MCP server named by --mcp-config and replay the scenario's tool calls
resume = argv[argv.index("--resume") + 1] if "--resume" in argv else None
sid = resume or argv[argv.index("--session-id") + 1]
scenario = json.load(open(os.environ["STUB_SCENARIO"], encoding="utf-8"))
steps = scenario["repair" if resume else "draft"]
config = json.load(open(argv[argv.index("--mcp-config") + 1], encoding="utf-8"))["mcpServers"]["pptm"]
server = subprocess.Popen([config["command"], *config["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
def rpc(n, method, params):
    server.stdin.write((json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params}) + "\n").encode("utf-8"))
    server.stdin.flush()
    return json.loads(server.stdout.readline().decode("utf-8"))
rpc(1, "initialize", {"protocolVersion": "2025-06-18"})
tools = [t["name"] for t in rpc(2, "tools/list", {})["result"]["tools"]]
emit({"type": "system", "subtype": "init", "apiKeySource": "none", "model": effective, "session_id": sid,
      "tools": ["mcp__pptm__" + t for t in tools], "mcp_servers": [{"name": "pptm", "status": "connected"}], "permissionMode": "dontAsk"})
project, page = os.environ.get("PPT_MASTER_PROJECT_PATH", ""), os.environ.get("PPT_MASTER_PAGE_FILE", "")
def fill(value):
    if isinstance(value, str):
        return value.replace("{project}", project).replace("{page}", page)
    if isinstance(value, list):
        return [fill(v) for v in value]
    if isinstance(value, dict):
        return {k: fill(v) for k, v in value.items()}
    return value
usage = {"input_tokens": 50, "cache_read_input_tokens": 400, "cache_creation_input_tokens": 30, "output_tokens": 120}
for n, step in enumerate(steps):
    args = fill(step["args"])
    tid = f"tu_{n}"
    emit({"type": "assistant", "message": {"id": f"msg_{'r' if resume else 'd'}{n}", "model": effective, "usage": usage,
                                            "content": [{"type": "tool_use", "id": tid, "name": "mcp__pptm__" + step["tool"], "input": args}]}})
    reply = rpc(10 + n, "tools/call", {"name": step["tool"], "arguments": args})["result"]
    emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "content": reply["content"], "is_error": reply["isError"]}]}})
server.stdin.close()
server.wait()
emit({"type": "assistant", "message": {"id": "msg_final", "model": effective, "usage": usage, "content": [{"type": "text", "text": "done: " + page}]}})
cost = float(os.environ.get("STUB_COST_CUMULATIVE_REPAIR" if resume else "STUB_COST_CUMULATIVE_DRAFT", "0.5"))
emit({"type": "result", "subtype": "success", "is_error": False, "num_turns": len(steps) + 1, "result": "done: " + page, "session_id": sid,
      "total_cost_usd": cost, "usage": usage, "modelUsage": {effective: {"inputTokens": 480}}})
'''

SUBMIT_CHECK = r'''
import hashlib, json, os, sys
sys.path.insert(0, {harness!r})
import pass_counter
args = sys.argv[1:]
svg = args[args.index("--svg") + 1] if "--svg" in args else os.environ.get("PPT_MASTER_EXP_PAGE_FILE", "")
digest = hashlib.sha256(open(svg, "rb").read()).hexdigest() if svg and os.path.isfile(svg) else None
result = pass_counter.claim(os.environ["PPT_MASTER_EXP_CHECK_STATE"], svg_sha256=digest)
print(json.dumps({{"stage_env": os.environ.get("PPT_MASTER_EXP_CHECK_STAGE"), "limit_env": os.environ.get("PPT_MASTER_EXP_CHECK_LIMIT"), **result}}))
sys.exit(0 if result["granted"] else 3)
'''

JSON_TOOL = r'''
import hashlib, json, sys
args = sys.argv[1:]
def opt(name):
    return args[args.index(name) + 1] if name in args else None
if opt("--summary"):  # the inspect_svg.py --summary mode: a short text that states the artifact hash
    report = json.load(open(opt("--summary"), encoding="utf-8"))
    text = "inspection of svg sha256 " + str(report.get("svg_sha256")) + "; report " + opt("--summary") + "\n"
    open(opt("--summary-out"), "w", encoding="utf-8").write(text)
    sys.exit(0)
if opt("--png"):
    open(opt("--png"), "wb").write(bytes.fromhex("89504e470d0a1a0a"))
out = opt("--out")
svg = opt("--svg")
payload = {{"tool": {name!r}, "status": "ok", "request": json.load(open(opt("--in"), encoding="utf-8")) if opt("--in") else None}}
if svg:
    payload["svg_sha256"] = hashlib.sha256(open(svg, "rb").read()).hexdigest()
    payload["checks"] = [{{"check_id": "OVL1", "check": "overlap", "targets": ["t1"], "status": "passed"}}]
if out:
    with open(out, "w", encoding="utf-8") as h:
        json.dump(payload, h)
print(json.dumps({{"status": "ok"}}))
'''

TEMPLATE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect id="bg" x="0" y="0" width="1280" height="720"/>'
                '<text id="logo" x="20" y="700">LOGO</text></svg>')
PLACEHOLDER_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect id="bg" x="0" y="0" width="1280" height="720"/>'
                   '<text id="logo" x="20" y="700">LOGO</text><text id="title" x="40" y="60">Title</text></svg>')
CONTENT_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"><rect id="bg" x="0" y="0" width="1280" height="720"/>'
               '<text id="logo" x="20" y="700">LOGO</text><text id="title" x="40" y="60">Delivery plan</text>'
               '<rect id="b1" x="100" y="200" width="300" height="30"/><rect id="b2" x="420" y="260" width="200" height="30"/>'
               '<rect id="b3" x="640" y="320" width="260" height="30"/><path id="d1" d="M400 215 L420 275"/>'
               '<text id="t1" x="100" y="190">Discovery</text><text id="t2" x="420" y="250">Build</text><text id="t3" x="640" y="310">Pilot</text></svg>')


def write_cmd_stub(folder: Path, name: str, script: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    py = folder / f"{name}.py"
    py.write_text(textwrap.dedent(script), encoding="utf-8")
    if os.name == "nt":
        cmd = folder / f"{name}.cmd"
        cmd.write_text(f'@"{sys.executable}" "{py}" %*\r\n', encoding="utf-8")
        return cmd
    sh = folder / name
    sh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py}" "$@"\n', encoding="utf-8")
    sh.chmod(0o755)
    return sh


def make_mirror(root: Path) -> Path:
    """A throwaway copy of the worktree's host files plus stub exp_svg tools: ROOT for cli_host/host/tools_mcp becomes `root`."""
    for rel in MIRROR_FILES:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(WORKTREE / rel, target)
    scripts = root / "skills" / "ppt-master" / "scripts"
    tools = {
        "exp_svg/inspect/submit_check.py": SUBMIT_CHECK.format(harness=str(HARNESS)),
        "exp_svg/inspect/inspect_svg.py": JSON_TOOL.format(name="inspect_svg"),
        "exp_svg/inspect/render_export.py": JSON_TOOL.format(name="render_export"),
        "exp_svg/timeline/build_timeline.py": JSON_TOOL.format(name="build_timeline"),
        "page_lint.py": JSON_TOOL.format(name="page_lint"),
    }
    for rel, source in tools.items():
        target = scripts / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source), encoding="utf-8")
    return root


def make_evidence(root: Path, cash_cap=None, run_plan: dict | None = None) -> Path:
    """A throwaway evidence root: the real frozen run_plan/PROMPTS, a manifest, one fixture and one package."""
    (root / "handoff_snapshot").mkdir(parents=True)
    shutil.copy2(HANDOFF / "PROMPTS.md", root / "handoff_snapshot" / "PROMPTS.md")
    plan = run_plan or json.loads((HANDOFF / "run_plan.json").read_text(encoding="utf-8"))
    (root / "handoff_snapshot" / "run_plan.json").write_text(json.dumps(plan), encoding="utf-8")
    manifest = json.loads((HARNESS.parent / "manifest.json").read_text(encoding="utf-8"))
    manifest["api_cash_cap_usd"] = cash_cap
    manifest["routes"]["grok_reviewer"]["cash_cap_usd"] = cash_cap
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    recipe = (manifest.get("reviewer_recipe") or {}).get("path")  # the frozen reviewer recipe travels with the manifest (D021)
    if recipe and (HARNESS.parent / recipe).is_file():
        (root / recipe).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HARNESS.parent / recipe, root / recipe)
    creator = root / "fixtures" / "T-DEV" / "creator"
    creator.mkdir(parents=True)
    (creator / "brief.md").write_text("# Brief\n\nA delivery plan with Discovery, Build and Pilot phases.\n", encoding="utf-8")
    (creator / "template").mkdir()
    (creator / "template" / "content.svg").write_text(TEMPLATE_SVG, encoding="utf-8")
    (creator / "style_contract.md").write_text("Navy titles, grey rules, no gradients.\n", encoding="utf-8")
    (creator / "references").mkdir()
    (creator / "references" / "cur-gantt.png").write_bytes(bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"))
    protected = root / "fixtures" / "_protected" / "T-DEV"
    protected.mkdir(parents=True)
    (protected / "checklist.json").write_text('{"items": [{"id": "T1", "text": "secret expected content"}]}', encoding="utf-8")
    package = root / "packages" / "A" / "timeline"
    package.mkdir(parents=True)
    (package / "recipe.md").write_text("Choose the time scale first; build bars with build_timeline.\n", encoding="utf-8")
    (package / "package.json").write_text(json.dumps({
        "package_id": "pkgA-timeline-v1", "family": "timeline", "recipe": "recipe.md",
        "scripts": [{"script": "exp_svg/timeline/build_timeline.py", "purpose": "dates to bars", "usage": "--in req.json --out res.json"},
                    {"script": "exp_svg/inspect/submit_check.py", "purpose": "submit one check pass", "usage": "--svg <page>"}],
    }), encoding="utf-8")
    return root


def draft_scenario() -> dict:
    return {
        "draft": [
            {"tool": "write_file", "args": {"path": "{page}", "content": PLACEHOLDER_SVG}},
            {"tool": "run_script", "args": {"script": "page_lint.py", "args": ["{page}"]}},
            {"tool": "read_file", "args": {"path": "hosts/responses_api/host.py"}},
            {"tool": "read_file", "args": {"path": "{project}/inputs/fixture/brief.md"}},
            {"tool": "write_file", "args": {"path": "{project}/inputs/fixture/brief.md", "content": "tampered"}},
            {"tool": "run_script", "args": {"script": "exp_svg/timeline/build_timeline.py", "args": ["--out", "{project}/work/receipt.json"]}},
            {"tool": "write_file", "args": {"path": "{page}", "content": CONTENT_SVG}},
            {"tool": "run_script", "args": {"script": "exp_svg/inspect/submit_check.py", "args": ["--svg", "{page}"]}},
            {"tool": "run_script", "args": {"script": "exp_svg/inspect/submit_check.py", "args": ["--svg", "{page}"]}},
            {"tool": "run_script", "args": {"script": "exp_svg/inspect/submit_check.py", "args": ["--svg", "{page}"]}},
            {"tool": "run_script", "args": {"script": "exp_svg/inspect/submit_check.py", "args": ["--svg", "{page}"]}},
        ],
        "repair": [
            {"tool": "edit_file", "args": {"path": "{page}", "old": ">Pilot<", "new": ">Pilot (4 weeks)<"}},
            {"tool": "run_script", "args": {"script": "exp_svg/inspect/submit_check.py", "args": ["--svg", "{page}"]}},
        ],
    }


class StubOpenRouter:
    """A local stand-in for OpenRouter's /responses endpoint. Records every request; answers with a configurable body."""

    def __init__(self, reply: dict, status: int = 200) -> None:
        self.reply, self.status, self.requests = reply, status, []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(self.rfile.read(length) or b"{}")})
                data = json.dumps(outer.reply).encode("utf-8")
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/api/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def valid_review(sha: str, verdict: str = "repair", blockers: list | None = None) -> dict:
    finding = {"id": "B1", "requirement_id": "R-labels", "element_ids": ["b2"], "evidence": "Bar b2 has no task name inside or beside it.",
               "severity": "blocker", "certainty": "certain", "suggested_change": "Place the label 'Build' left-aligned inside b2."}
    return {"artifact_sha256": sha, "verdict": verdict, "blockers": [finding] if blockers is None else blockers, "advisories": [],
            "uncertainties": ["d1: does the dependency end on b2's left edge?"],
            "scores": {k: {"score": 2, "evidence": "b1-b3 readable"} for k in
                       ("semantic_clarity", "readability", "hierarchy_reading_order", "composition_spacing", "template_style_fidelity")}}
