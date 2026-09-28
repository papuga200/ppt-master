#!/usr/bin/env python3
"""A library of real reference slides: build it from decks, look at a form on one sheet, pick a slide.

    reference_library.py build <deck.pdf|deck.pptx> ... [--library DIR] [--width 1600]
    reference_library.py sheet --form architecture [--limit 24] [--columns 4] [--project P --page PAGE]
    reference_library.py label ID ... --form timeline [--topology "..."] [--devices "a; b"]
    reference_library.py label ID ... --verdict rejected --reason "..."
    reference_library.py show ID ... [--project P --page PAGE]
    reference_library.py match --form architecture --need "oversight spanning every site, hub, data path" \
        [--density high] [--limit 1] [--exclude ID ...] [--project P] [--page PAGE]
    reference_library.py counterexamples --form timeline [--limit 1]
    reference_library.py forms

The library is a folder of rendered slide images plus one `index.json`; its location comes from
`--library` or the `PPT_MASTER_REFERENCE_LIBRARY` variable. Reference decks are usually other
firms' material, so the library lives outside this repository and is never packaged into a deck.

`build` renders every page of a deck (PDF through PyMuPDF; PPTX through PowerPoint or LibreOffice)
into `<sha256>/p<N>.png` and indexes each page with the form `unlabelled`. Rebuilding a deck replaces
its entries, so the library grows one deck at a time, including decks a user supplies for one run.

The planner then looks rather than searches: `sheet --form unlabelled` shows the new pages on one
contact sheet with their ids stamped, `label` files the form each one carries (a classifier model can
do this later; a person or the agent does it now), and `sheet --form <form>` shows every slide of
that form so the planner picks the one or two that solve this page's problem and `show`s them full
size. `match` remains for a keyword shortlist when a sheet is too large to look at.

A reference on disk is not a reference seen: the host attaches each `IMAGE:` path to the tool
result, and with `--project` the delivery is recorded in quality-run.json. An entry a user rejected
(`verdict: rejected`) never comes back as a positive match or on a sheet; `counterexamples` returns
those deliberately, with the reason. A reference lends structure and devices, never facts, wording,
counts, colours or branding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

WEAK_SCORE = 3.0
UNLABELLED = "unlabelled"
_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "that", "every", "each", "as", "is", "are", "by", "from"}


def _words(text: str) -> set[str]:
    words = set()
    for w in re.findall(r"[a-z][a-z-]+", text.lower()):
        if w in _STOP or len(w) <= 2:
            continue
        words.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)  # timelines ~ timeline
    return words


# Related exhibit forms (the planner's Exhibit vocabulary): a near form is still a useful structural reference.
RELATED_FORMS = {
    "bar-comparison": {"time-series", "part-to-whole", "key-figures", "comparison-table"},
    "time-series": {"bar-comparison", "part-to-whole"},
    "part-to-whole": {"bar-comparison", "time-series"},
    "distribution": {"bar-comparison"},
    "correlation": {"matrix"},
    "key-figures": {"bar-comparison", "summary"},
    "process-flow": {"loop", "timeline", "architecture"},
    "loop": {"process-flow"},
    "architecture": {"hub-and-spoke", "hierarchy", "process-flow"},
    "hub-and-spoke": {"architecture", "hierarchy"},
    "hierarchy": {"architecture", "team"},
    "matrix": {"comparison-table", "correlation"},
    "timeline": {"process-flow"},
    "table": {"comparison-table"},
    "comparison-table": {"table", "matrix"},
    "annotated-example": {"architecture"},
    "text-argument": {"summary"},
    "team": {"hierarchy"},
    "summary": {"text-argument", "key-figures"},
    "closing": {"text-argument"},
}


def _index_path(library: Path) -> Path:
    return library / "index.json"


def load(library: Path) -> list[dict]:
    index = _index_path(library)
    if not index.is_file():
        raise SystemExit(f"no index.json in the reference library: {library}")
    return json.loads(index.read_text(encoding="utf-8")).get("entries") or []


def save(library: Path, entries: list[dict]) -> None:
    library.mkdir(parents=True, exist_ok=True)
    _index_path(library).write_text(json.dumps({"version": 1, "entries": entries}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _rejected(entry: dict) -> bool:
    return (entry.get("verdict") or "").lower() in {"rejected", "weak"}


def _form(entry: dict) -> str:
    return (entry.get("labels") or {}).get("communication_form") or "other"


def score(entry: dict, form: str | None, need: set[str], density: str | None) -> tuple[float, list[str]]:
    labels = entry.get("labels") or {}
    total, why = 0.0, []
    if form and labels.get("communication_form") == form:
        total += 4.0
        why.append(f"same communication form ({form})")
    elif form and (labels.get("communication_form") in RELATED_FORMS.get(form, set())
                   or form in _words(" ".join([labels.get("archetype") or "", labels.get("topology") or ""]))):
        total += 2.0
        why.append(f"related form ({labels.get('communication_form')})")
    structure = _words(" ".join([labels.get("semantic_topology") or "", labels.get("description") or "", labels.get("purpose") or "",
                                 labels.get("why") or "", *(labels.get("use_cases") or []), *(labels.get("take") or []),
                                 *(labels.get("devices") or []), *(labels.get("hierarchy_devices") or [])]))
    shared = sorted(need & structure)
    if shared:
        total += min(4.0, 0.8 * len(shared))
        why.append("shares " + ", ".join(shared[:6]))
    if density and (density in {labels.get("density"), labels.get("density_band")} or density in str(labels.get("density") or "").split("-")):
        total += 1.0
        why.append(f"{density} density")
    return total, why


def observations(entry: dict) -> list[str]:
    labels = entry.get("labels") or {}
    notes = []
    if labels.get("semantic_topology"):
        notes.append(f"Structure: {labels['semantic_topology']}.")
    if labels.get("hierarchy_devices"):
        notes.append("Hierarchy is carried by " + "; ".join(labels["hierarchy_devices"][:4]) + ".")
    if labels.get("devices"):
        notes.append("Devices worth borrowing: " + "; ".join(labels["devices"][:5]) + ".")
    return notes


def _print(entry: dict, library: Path, total: float | None, why: list[str], *, counterexample: bool = False) -> Path:
    labels = entry.get("labels") or {}
    image = (library / entry["image"]).resolve()
    kind = "COUNTEREXAMPLE (do not imitate)" if counterexample else "reference"
    head = f"{kind} {entry['id']}"
    if total is not None:
        head += f" - score {total:.1f}" + (" - WEAK MATCH: use it only if it genuinely helps" if total < WEAK_SCORE and not counterexample else "")
    print(head)
    print(f"  form: {_form(entry)}" + (f" - source: {Path(entry.get('source', '')).name} p{entry.get('page')}" if entry.get("source") else ""))
    if labels.get("purpose") or labels.get("communication_goal") or labels.get("description"):
        print(f"  solves: {labels.get('purpose') or labels.get('communication_goal') or labels.get('description')}")
    if why:
        print(f"  matched because: {'; '.join(why)}")
    if counterexample and entry.get("reason"):
        print(f"  rejected because: {entry['reason']}")
    for line in observations(entry):
        print(f"  {line}")
    if labels.get("why"):
        print(f"  why it works: {labels['why']}")
    if labels.get("take"):
        print("  take: " + "; ".join(labels["take"]))
    if labels.get("avoid"):
        print("  avoid: " + "; ".join(labels["avoid"]))
    if labels.get("typography"):
        print(f"  typography: {labels['typography']} (our type floors still apply)")
    if entry.get("restrictions"):
        print(f"  provenance: {entry['restrictions']}")
    print("  Borrow the structure and devices that fit this page's content; never its facts, wording, counts or branding.")
    print(f"IMAGE: {image}")
    return image


def _record(project: str | None, page: str | None, delivered: list[dict]) -> None:
    if not project or not delivered:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from page_review import update_journal
    stamped = [{**item, "page": page, "at": time.strftime("%Y-%m-%dT%H:%M:%S")} for item in delivered]
    update_journal(Path(project).resolve(), lambda journal: journal.setdefault("references_delivered", []).extend(stamped))


# --- build -------------------------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _render_pdf(pdf: Path, out: Path, width: int) -> int:
    import fitz  # PyMuPDF
    out.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf) as document:
        for index, page in enumerate(document, start=1):
            zoom = width / page.rect.width
            page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(out / f"p{index}.png")
        return document.page_count


def _render_pptx(pptx: Path, out: Path, width: int) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from pptx_render import render_with_libreoffice, render_with_powerpoint
    with tempfile.TemporaryDirectory(prefix="reflib-") as scratch:
        work = Path(scratch)
        if not (render_with_powerpoint(pptx, work, width) or render_with_libreoffice(pptx, work, width)):
            raise SystemExit(f"no PPTX renderer available for {pptx.name}: export it to PDF and build from that")
        slides = sorted(work.glob("slide-*.png"))
        out.mkdir(parents=True, exist_ok=True)
        for index, slide in enumerate(slides, start=1):
            shutil.copyfile(slide, out / f"p{index}.png")
        return len(slides)


def build(library: Path, decks: list[Path], width: int) -> list[dict]:
    entries = load(library) if _index_path(library).is_file() else []
    for deck in decks:
        deck = deck.resolve()
        if not deck.is_file():
            raise SystemExit(f"not a file: {deck}")
        sha = _sha256(deck)
        folder = library / sha
        if folder.is_dir():
            shutil.rmtree(folder)
        if deck.suffix.lower() == ".pdf":
            count = _render_pdf(deck, folder, width)
        elif deck.suffix.lower() in {".pptx", ".ppt"}:
            count = _render_pptx(deck, folder, width)
        else:
            raise SystemExit(f"unsupported deck type: {deck.name} (PDF or PPTX)")
        entries = [entry for entry in entries if entry.get("sha256") != sha]
        for page in range(1, count + 1):
            entries.append({
                "id": f"lib.{sha[:8]}.p{page}",
                "source": str(deck),
                "sha256": sha,
                "page": page,
                "image": f"{sha}/p{page}.png",
                "labels": {"communication_form": UNLABELLED},
                "origin": "reference",
                "verdict": None,
                "reason": None,
            })
        print(f"built {deck.name}: {count} page(s) as lib.{sha[:8]}.p1..p{count}, form {UNLABELLED}")
    save(library, entries)
    return entries


# --- sheet -------------------------------------------------------------------------------------------

def build_sheet(library: Path, entries: list[dict], out: Path, columns: int = 4, cell_width: int = 480) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:  # Pillow < 10.1
        font = ImageFont.load_default()
    thumbs = []
    for entry in entries:
        with Image.open(library / entry["image"]) as source:
            ratio = cell_width / source.width
            thumbs.append((entry["id"], source.convert("RGB").resize((cell_width, int(source.height * ratio)), Image.LANCZOS)))
    if not thumbs:
        raise SystemExit("no page images to put on a sheet")
    cell_height = max(t.height for _, t in thumbs)
    label, gap = 30, 14
    columns = min(columns, len(thumbs))
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * (cell_width + gap) + gap, rows * (cell_height + label + gap) + gap), (236, 236, 232))
    draw = ImageDraw.Draw(sheet)
    for index, (name, thumb) in enumerate(thumbs):
        x = gap + (index % columns) * (cell_width + gap)
        y = gap + (index // columns) * (cell_height + label + gap)
        draw.text((x, y + 4), name, fill=(30, 30, 30), font=font)
        sheet.paste(thumb, (x, y + label))
        draw.rectangle((x - 1, y + label - 1, x + cell_width, y + label + thumb.height), outline=(190, 190, 186))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


# --- commands ----------------------------------------------------------------------------------------

def cmd_forms(entries: list[dict]) -> int:
    counts: dict[str, int] = {}
    for entry in entries:
        if not _rejected(entry):
            counts[_form(entry)] = counts.get(_form(entry), 0) + 1
    for form, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"{form}: {count}")
    return 0


def cmd_sheet(args: argparse.Namespace, library: Path, entries: list[dict]) -> int:
    chosen = [e for e in entries if _form(e) == args.form and not _rejected(e) and (library / e.get("image", "")).is_file()
              and e.get("id") not in args.exclude]
    if not chosen:
        print(f"no reference slides of form {args.form}: author the page directly (`forms` lists what the library holds)")
        return 0
    limit = max(1, args.limit)
    delivered = []
    for number, start in enumerate(range(0, len(chosen), limit), start=1):
        batch = chosen[start:start + limit]
        suffix = f"-{number}" if len(chosen) > limit else ""
        out = build_sheet(library, batch, library / "sheets" / f"{args.form}{suffix}.png", columns=args.columns)
        print(f"sheet {number}: {len(batch)} {args.form} slide(s) - " + ", ".join(e["id"] for e in batch))
        print(f"IMAGE: {out.resolve()}")
        delivered.append({"id": f"sheet:{args.form}{suffix}", "image": str(out.resolve()), "entries": [e["id"] for e in batch]})
    print("Pick the one or two that solve this page's communication problem and `show` them full size; borrow structure, never content.")
    _record(args.project, args.page, delivered)
    return 0


def cmd_label(args: argparse.Namespace, library: Path, entries: list[dict]) -> int:
    by_id = {e.get("id"): e for e in entries}
    missing = [i for i in args.ids if i not in by_id]
    if missing:
        raise SystemExit("unknown id(s): " + ", ".join(missing))
    if not (args.form or args.topology or args.devices or args.verdict):
        raise SystemExit("nothing to set: give --form, --topology, --devices or --verdict")
    for ident in args.ids:
        entry = by_id[ident]
        labels = entry.setdefault("labels", {})
        if args.form:
            labels["communication_form"] = args.form
        if args.topology:
            labels["semantic_topology"] = args.topology
        if args.devices:
            labels["devices"] = [d.strip() for d in args.devices.split(";") if d.strip()]
        if args.verdict:
            entry["verdict"] = None if args.verdict == "clear" else args.verdict
            entry["reason"] = args.reason if args.verdict != "clear" else None
        print(f"{ident}: form {_form(entry)}" + (f", verdict {entry['verdict']}" if entry.get("verdict") else ""))
    save(library, entries)
    return 0


def cmd_show(args: argparse.Namespace, library: Path, entries: list[dict]) -> int:
    by_id = {e.get("id"): e for e in entries}
    delivered = []
    for ident in args.ids:
        entry = by_id.get(ident)
        if not entry:
            raise SystemExit(f"unknown id: {ident}")
        if not (library / entry.get("image", "")).is_file():
            raise SystemExit(f"{ident}: image missing on disk ({entry.get('image')}); rebuild the deck")
        image = _print(entry, library, None, [], counterexample=_rejected(entry))
        delivered.append({"id": ident, "image": str(image), "counterexample": _rejected(entry)})
    _record(args.project, args.page, delivered)
    return 0


def cmd_match(args: argparse.Namespace, library: Path, entries: list[dict]) -> int:
    wanted_rejected = args.command == "counterexamples"
    need = _words(args.need)
    ranked = []
    for entry in entries:
        if _rejected(entry) != wanted_rejected or entry.get("id") in args.exclude or _form(entry) == UNLABELLED:
            continue
        if not (library / entry.get("image", "")).is_file():
            continue
        total, why = score(entry, args.form, need, args.density)
        if total > 0:
            ranked.append((total, entry, why))
    ranked.sort(key=lambda item: -item[0])
    if ranked and ranked[0][0] >= WEAK_SCORE and not wanted_rejected:
        ranked = [item for item in ranked if item[0] >= WEAK_SCORE]  # a strong match exists: do not pad with weak ones
    if not ranked:
        print("no useful reference for this page: author it directly")
        return 0
    delivered = []
    for total, entry, why in ranked[: max(1, min(args.limit, 3))]:
        image = _print(entry, library, total, why, counterexample=wanted_rejected)
        delivered.append({"id": entry["id"], "score": round(total, 1), "image": str(image), "counterexample": wanted_rejected})
    _record(args.project, args.page, delivered)
    return 0


def curate(library: Path, spec_path: Path) -> list[dict]:
    """Build a curated library from a spec: each entry names a rendered page image (`image_source`, optional `crop`
    [left, top, right, bottom] in px), its source deck and page, and the lead's labels (form, purpose, composition,
    density, typography, use cases, why it works, what to take and avoid, restrictions). Replaces the index."""
    from PIL import Image
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    library.mkdir(parents=True, exist_ok=True)
    (library / "images").mkdir(exist_ok=True)
    entries = []
    for item in spec["entries"]:
        source_image = Path(item["image_source"])
        image = Image.open(source_image).convert("RGB")
        if item.get("crop"):
            image = image.crop(tuple(item["crop"]))
        target = library / "images" / f"{item['id']}.png"
        image.save(target)
        labels = {"communication_form": item["form"], "purpose": item.get("purpose"), "semantic_topology": item.get("composition"),
                  "density": item.get("density"), "typography": item.get("typography"), "use_cases": item.get("use_cases") or [],
                  "why": item.get("why"), "take": item.get("take") or [], "avoid": item.get("avoid") or []}
        entries.append({"id": item["id"], "source": item.get("source") or str(source_image), "page": item.get("page"),
                        "image": f"images/{item['id']}.png", "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                        "labels": labels, "origin": "curated", "restrictions": item.get("restrictions"), "verdict": "good"})
    save(library, entries)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("build", "curate", "sheet", "label", "show", "match", "counterexamples", "forms"))
    parser.add_argument("ids", nargs="*", help="deck files for build; entry ids for label and show")
    parser.add_argument("--library", default=os.environ.get("PPT_MASTER_REFERENCE_LIBRARY"))
    parser.add_argument("--form")
    parser.add_argument("--need", default="", help="the relationships the page must show, in a few words")
    parser.add_argument("--density", choices=("low", "medium", "high"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--width", type=int, default=1600, help="build: rendered page width in px")
    parser.add_argument("--topology", help="label: one sentence on the slide's structure")
    parser.add_argument("--devices", help="label: devices worth borrowing, separated by ';'")
    parser.add_argument("--verdict", choices=("good", "rejected", "weak", "clear"))
    parser.add_argument("--reason")
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument("--project")
    parser.add_argument("--page")
    args = parser.parse_args()
    if not args.library:
        print("no reference library is configured (PPT_MASTER_REFERENCE_LIBRARY): continue without references and say so in the run summary")
        return 3
    library = Path(args.library).resolve()
    if args.command == "curate":
        if len(args.ids) != 1:
            raise SystemExit("curate needs one spec file")
        entries = curate(library, Path(args.ids[0]))
        print(f"library {library}: {len(entries)} curated entries")
        return 0
    if args.command == "build":
        if not args.ids:
            raise SystemExit("build needs at least one deck file")
        entries = build(library, [Path(p) for p in args.ids], args.width)
        unlabelled = sum(1 for e in entries if _form(e) == UNLABELLED)
        print(f"library {library}: {len(entries)} entries, {unlabelled} unlabelled - next: `sheet --form {UNLABELLED}` then `label`")
        return 0
    entries = load(library)
    if args.command == "forms":
        return cmd_forms(entries)
    if args.command == "sheet":
        if not args.form:
            raise SystemExit("sheet needs --form")
        args.limit = args.limit or 24
        return cmd_sheet(args, library, entries)
    if args.command == "label":
        if not args.ids:
            raise SystemExit("label needs at least one id")
        return cmd_label(args, library, entries)
    if args.command == "show":
        if not args.ids:
            raise SystemExit("show needs at least one id")
        return cmd_show(args, library, entries)
    args.limit = args.limit or 1
    return cmd_match(args, library, entries)


if __name__ == "__main__":
    sys.exit(main())
