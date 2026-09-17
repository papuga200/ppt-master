#!/usr/bin/env python3
"""Find a real reference slide that solves the same communication problem as the page in hand.

    reference_library.py match --form architecture --need "oversight spanning every site, hub, data path" \
        [--density high] [--limit 1] [--exclude ID ...] [--project PROJECT] [--page PAGE]
    reference_library.py counterexamples --form timeline [--limit 1]
    reference_library.py forms

The library is a folder of rendered slide images plus one `index.json`; its location comes from
`--library` or the `PPT_MASTER_REFERENCE_LIBRARY` variable. Reference decks are usually other
firms' material, so the library lives outside this repository and is never packaged into a deck.

Matching is on the communication problem first (the form, then the words of the need against each
entry's topology and devices), then on density. Brand is not a criterion: a reference lends
structure, not identity. An entry a user rejected (`verdict: rejected`) never comes back as a
positive match; `counterexamples` returns those deliberately, with the reason.

Each result prints the entry id, what problem the slide solves, a few concrete observations and an
`IMAGE: <path>` line. A reference on disk is not a reference seen: the host attaches each IMAGE
path to the tool result, and with `--project` the delivery is recorded in quality-run.json. A weak
match is said to be weak - no reference is better than a wrong one.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

WEAK_SCORE = 3.0
_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "that", "every", "each", "as", "is", "are", "by", "from"}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z-]+", text.lower()) if w not in _STOP and len(w) > 2}


def load(library: Path) -> list[dict]:
    index = library / "index.json"
    if not index.is_file():
        raise SystemExit(f"no index.json in the reference library: {library}")
    return json.loads(index.read_text(encoding="utf-8")).get("entries") or []


def _rejected(entry: dict) -> bool:
    return (entry.get("verdict") or "").lower() in {"rejected", "weak"}


def score(entry: dict, form: str | None, need: set[str], density: str | None) -> tuple[float, list[str]]:
    labels = entry.get("labels") or {}
    total, why = 0.0, []
    if form and labels.get("communication_form") == form:
        total += 4.0
        why.append(f"same communication form ({form})")
    elif form and form in _words(" ".join([labels.get("archetype") or "", labels.get("topology") or ""])):
        total += 2.0
        why.append(f"related form ({labels.get('communication_form')})")
    structure = _words(" ".join([labels.get("semantic_topology") or "", labels.get("description") or "",
                                 *(labels.get("devices") or []), *(labels.get("hierarchy_devices") or [])]))
    shared = sorted(need & structure)
    if shared:
        total += min(4.0, 0.8 * len(shared))
        why.append("shares " + ", ".join(shared[:6]))
    if density and density in {labels.get("density"), labels.get("density_band")}:
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


def _print(entry: dict, library: Path, total: float, why: list[str], *, counterexample: bool = False) -> Path:
    labels = entry.get("labels") or {}
    image = (library / entry["image"]).resolve()
    kind = "COUNTEREXAMPLE (do not imitate)" if counterexample else "reference"
    print(f"{kind} {entry['id']} - score {total:.1f}" + (" - WEAK MATCH: use it only if it genuinely helps" if total < WEAK_SCORE and not counterexample else ""))
    print(f"  solves: {labels.get('purpose') or labels.get('communication_goal') or labels.get('description')}")
    if why:
        print(f"  matched because: {'; '.join(why)}")
    if counterexample and entry.get("reason"):
        print(f"  rejected because: {entry['reason']}")
    for line in observations(entry):
        print(f"  {line}")
    print("  Borrow the structure and devices that fit this page's content; never its facts, wording, counts or branding.")
    print(f"IMAGE: {image}")
    return image


def _record(project: str | None, page: str | None, delivered: list[dict]) -> None:
    if not project or not delivered:
        return
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from page_review import load_journal, save_journal
    root = Path(project).resolve()
    journal = load_journal(root)
    for item in delivered:
        journal.setdefault("references_delivered", []).append({**item, "page": page, "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    save_journal(root, journal)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("match", "counterexamples", "forms"))
    parser.add_argument("--library", default=os.environ.get("PPT_MASTER_REFERENCE_LIBRARY"))
    parser.add_argument("--form")
    parser.add_argument("--need", default="", help="the relationships the page must show, in a few words")
    parser.add_argument("--density", choices=("low", "medium", "high"))
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--exclude", nargs="*", default=[])
    parser.add_argument("--project")
    parser.add_argument("--page")
    args = parser.parse_args()
    if not args.library:
        print("no reference library is configured (PPT_MASTER_REFERENCE_LIBRARY): continue without references and say so in the run summary")
        return 3
    library = Path(args.library).resolve()
    entries = load(library)
    if args.command == "forms":
        counts: dict[str, int] = {}
        for entry in entries:
            if not _rejected(entry):
                form = (entry.get("labels") or {}).get("communication_form") or "other"
                counts[form] = counts.get(form, 0) + 1
        for form, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"{form}: {count}")
        return 0
    wanted_rejected = args.command == "counterexamples"
    need = _words(args.need)
    ranked = []
    for entry in entries:
        if _rejected(entry) != wanted_rejected or entry.get("id") in args.exclude:
            continue
        if not (library / entry.get("image", "")).is_file():
            continue
        total, why = score(entry, args.form, need, args.density)
        if total > 0:
            ranked.append((total, entry, why))
    ranked.sort(key=lambda item: -item[0])
    if not ranked:
        print("no useful reference for this page: author it directly")
        return 0
    delivered = []
    for total, entry, why in ranked[: max(1, min(args.limit, 3))]:
        image = _print(entry, library, total, why, counterexample=wanted_rejected)
        delivered.append({"id": entry["id"], "score": round(total, 1), "image": str(image), "counterexample": wanted_rejected})
    _record(args.project, args.page, delivered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
