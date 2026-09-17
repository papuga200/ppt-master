#!/usr/bin/env python3
"""Authoring preview loop for the consulting-quality profile.

The author renders a page right after writing it, looks at the image, and either keeps the
page or edits its SVG. This tool owns the mechanics around that look:

    page_review.py render <project> <page> [--crop X,Y,W,H]
    page_review.py restore <project> <page> --rev N
    page_review.py note <project> <page> --outcome accepted|unresolved --text "..."
    page_review.py contact-sheet <project>
    page_review.py status <project>

``render`` saves a numbered copy of the SVG under ``.review/backup/`` whenever its content
changed since the last render, renders the page through ``visual_review.py`` (starting the
live-preview server when none is running), counts the revision in ``quality-run.json`` and
prints an ``IMAGE: <path>`` line. A host that shows images to its model attaches every such
path to the tool result; a host that cannot must open the path with its own image tool.

A revision is a render of changed SVG content. A crop or a second look at unchanged content
is not a revision. The budget is a ceiling, never a target.
"""

from __future__ import annotations

import argparse
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
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=3):
            return True
    except Exception:  # noqa: BLE001 - any failure means "start one"
        return False


def _ensure_server(project: Path) -> None:
    if _server_running(project):
        return
    subprocess.run([sys.executable, str(SCRIPTS / "svg_editor" / "server.py"), str(project), "--live", "--daemon", "--no-browser"],
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


def cmd_render(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    svg = _page_file(project, args.page)
    stem = svg.stem
    journal = load_journal(project)
    entry = journal["pages"].setdefault(stem, {"renders": 0, "revisions": 0, "last_sha": None, "backups": [], "outcome": None})
    digest = hashlib.sha256(svg.read_bytes()).hexdigest()
    changed = digest != entry.get("last_sha")
    if changed:
        if entry["last_sha"] is not None:
            entry["revisions"] += 1
        backup_dir = project / ".review" / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        rev = len(entry["backups"])
        backup = backup_dir / f"{stem}.rev{rev}.svg"
        backup.write_bytes(svg.read_bytes())
        entry["backups"].append({"rev": rev, "sha": digest, "file": str(backup.relative_to(project)).replace("\\", "/")})
        entry["last_sha"] = digest
        entry["outcome"] = None
    records = _render(project, [svg.name])
    record = next((r for r in records if r.get("ok")), None)
    if record is None:
        save_journal(project, journal)
        print(f"render failed: {json.dumps(records)[:1500]}")
        return 4
    entry["renders"] += 1
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
    save_journal(project, journal)
    budget = journal.get("revision_budget", DEFAULT_REVISION_BUDGET)
    left = budget - entry["revisions"]
    print(f"page {stem}: rev{current_rev} rendered ({'new content' if changed else 'unchanged content'}); "
          f"revisions used {entry['revisions']} of {budget}")
    if left <= 0:
        print("revision budget exhausted: look at this render, keep the best revision (restore an earlier one if it is better), "
              "and record the outcome with `note` - accepted, or unresolved with the issue named. Do not edit this page again.")
    print(f"IMAGE: {image}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    svg = _page_file(project, args.page)
    journal = load_journal(project)
    entry = journal["pages"].get(svg.stem) or {}
    match = next((b for b in entry.get("backups", []) if b["rev"] == args.rev), None)
    if match is None:
        raise SystemExit(f"no rev{args.rev} recorded for {svg.stem}")
    svg.write_bytes((project / match["file"]).read_bytes())
    entry["last_sha"] = match["sha"]
    entry.setdefault("restored", []).append(args.rev)
    save_journal(project, journal)
    print(f"restored {svg.stem} to rev{args.rev}; render it again before judging it")
    return 0


def cmd_note(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    svg = _page_file(project, args.page)
    journal = load_journal(project)
    entry = journal["pages"].setdefault(svg.stem, {"renders": 0, "revisions": 0, "last_sha": None, "backups": [], "outcome": None})
    if not entry.get("renders"):
        raise SystemExit("this page has never been rendered: an outcome is recorded only for a page that was looked at")
    notes_dir = project / ".review" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    with (notes_dir / f"{svg.stem}.md").open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {time.strftime('%Y-%m-%d %H:%M:%S')} - {args.outcome}\n\n{args.text.strip()}\n")
    entry["outcome"] = args.outcome
    entry["outcome_sha"] = hashlib.sha256(svg.read_bytes()).hexdigest()
    save_journal(project, journal)
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
        stale = entry.get("outcome") and entry.get("outcome_sha") != hashlib.sha256(_page_file(project, page).read_bytes()).hexdigest()
        print(f"{page}: renders {entry['renders']}, revisions {entry['revisions']}/{budget}, "
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
    note = sub.add_parser("note")
    note.add_argument("project")
    note.add_argument("page")
    note.add_argument("--outcome", choices=("accepted", "unresolved"), required=True)
    note.add_argument("--text", required=True)
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
