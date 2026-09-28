"""Prepare source-file visuals for the consulting deck runner.

The standard project importer already extracts Office/PDF pictures. This
adapter also handles projects whose source files were placed directly in
`sources/`, and makes the resulting choices visible to the planner.
"""

from __future__ import annotations

import hashlib
import filecmp
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


DOCUMENT_SUFFIXES = {".pptx", ".pptm", ".ppsx", ".ppsm", ".potx", ".potm", ".pdf", ".docx", ".doc", ".odt"}
PRESENTATION_SUFFIXES = {".pptx", ".pptm", ".ppsx", ".ppsm", ".potx", ".potm"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".svg", ".emf", ".wmf"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "source"


def _relative(path: Path, project: Path) -> str:
    return path.relative_to(project).as_posix()


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")


def _copy_direct_image(source: Path, project: Path) -> Path:
    digest = _revision(source)[:10]
    name = f"source_{_slug(source.stem)}_{digest}{source.suffix.lower()}"
    destination = project / "images" / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file() or not filecmp.cmp(source, destination, shallow=False):
        shutil.copy2(source, destination)
    return destination


def _revision(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def _catalog_line(item: dict) -> str:
    context = f", slide {item['slide']}" if item.get("slide") else ""
    occurrences = item.get("occurrences") or []
    slides = sorted({occurrence.get("slide_index") for occurrence in occurrences
                     if isinstance(occurrence, dict) and isinstance(occurrence.get("slide_index"), int)})
    if slides:
        context += ", on source slide" + ("s" if len(slides) > 1 else "") + " " + ", ".join(map(str, slides))
    pixels = item.get("pixels")
    if pixels:
        context += f", {pixels[0]}×{pixels[1]} px"
    return f"- `{item['path']}` — {item['kind']} from `{item['source']}`{context}"


def prepare(project: Path, scripts: Path) -> dict:
    """Convert source documents, surface embedded pictures and slide previews.

    Missing render support is recorded rather than mistaken for missing source
    evidence. No extracted image is selected for a slide automatically.
    """
    project = project.resolve()
    sources = project / "sources"
    result: dict = {"schema_version": 1, "documents": [], "assets": [], "issues": []}
    if not sources.is_dir():
        return result

    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from project_management.cli import ProjectManager

    manager = ProjectManager()
    analysis = project / "analysis" / "source_visuals"
    images = project / "images"
    namespace_sources: dict[str, str] = {}
    propagated_dirs: set[Path] = set()
    document_files = sorted(p for p in sources.iterdir() if p.is_file() and p.suffix.lower() in DOCUMENT_SUFFIXES)
    for source in document_files:
        identity = _slug(source.stem + "_" + source.suffix.lstrip("."))
        revision = _revision(source)
        existing_md = source.with_suffix(".md")
        existing_assets = existing_md.with_name(existing_md.stem + "_files")
        converted = analysis / "conversions" / f"{identity}_{revision}.md"
        markdown = existing_md if existing_md.is_file() and existing_assets.is_dir() else converted
        if markdown == converted and not converted.is_file():
            converted.parent.mkdir(parents=True, exist_ok=True)
            done = _run(scripts / "source_to_md.py", str(source), "-o", str(converted))
            if done.returncode or not converted.is_file():
                result["issues"].append(f"{_relative(source, project)}: conversion failed: {(done.stderr or done.stdout)[-400:].strip()}")
        if markdown.is_file():
            result["documents"].append({"source": _relative(source, project), "text": _relative(markdown, project)})
            namespace_sources[markdown.stem] = _relative(source, project)
            companion = markdown.with_name(markdown.stem + "_files")
            if companion.is_dir():
                manager._propagate_image_assets(companion, project)
                propagated_dirs.add(companion.resolve())

        if source.suffix.lower() in PRESENTATION_SUFFIXES:
            render_dir = analysis / "previews" / f"{identity}_{revision}"
            slides = sorted(render_dir.glob("slide-*.png")) if render_dir.is_dir() else []
            if not slides:
                rendered = _run(scripts / "pptx_render.py", str(source), "--out", str(render_dir))
                slides = sorted(render_dir.glob("slide-*.png")) if rendered.returncode == 0 else []
                if not slides:
                    result["issues"].append(f"{_relative(source, project)}: slide preview unavailable: {(rendered.stderr or rendered.stdout)[-300:].strip()}")
            for preview in slides:
                target = images / f"source_{identity}_{revision}_{preview.stem}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.is_file() or target.stat().st_mtime < preview.stat().st_mtime:
                    shutil.copy2(preview, target)
                result["assets"].append({
                    "path": _relative(target, project), "kind": "source_slide_preview",
                    "source": _relative(source, project), "slide": int(preview.stem.split("-")[-1]),
                    "use": "evidence screenshot or visual reference; a placed screenshot is a picture, not native slide objects",
                })

    for companion in sorted(p for p in sources.glob("*_files") if p.is_dir() and (p / "image_manifest.json").is_file()):
        namespace = companion.name[:-len("_files")]
        markdown = sources / f"{namespace}.md"
        namespace_sources.setdefault(namespace, _relative(markdown if markdown.is_file() else companion, project))
        if companion.resolve() not in propagated_dirs:
            manager._propagate_image_assets(companion, project)

    for source in sorted(p for p in sources.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
                         and not any(part.endswith("_files") for part in p.relative_to(sources).parts[:-1])):
        target = _copy_direct_image(source, project)
        result["assets"].append({"path": _relative(target, project), "kind": "supplied_image",
                                 "source": _relative(source, project), "use": "source image; inspect content and crop before placing"})

    manifest = images / "image_manifest.json"
    if manifest.is_file():
        try:
            entries = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            entries = []
            result["issues"].append("images/image_manifest.json: unreadable")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or not isinstance(entry.get("filename"), str):
                continue
            namespace = str(entry.get("source_namespace") or "")
            if namespace not in namespace_sources:
                continue
            path = images / entry["filename"]
            if not path.is_file():
                continue
            result["assets"].append({
                "path": _relative(path, project), "kind": "embedded_image",
                "source": namespace_sources[namespace],
                "occurrences": entry.get("occurrences") or [],
                "pixels": [entry["pixel_width"], entry["pixel_height"]]
                if isinstance(entry.get("pixel_width"), int) and isinstance(entry.get("pixel_height"), int) else None,
                "use": "embedded source image; inspect its surrounding source text and slide/page before placing",
            })

    result["assets"].sort(key=lambda item: (item["kind"], item["source"], item["path"]))
    analysis.mkdir(parents=True, exist_ok=True)
    (analysis / "catalog.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Source visual assets", "",
             "Candidates only. Choose an image because it supports a slide's claim, inspect it, and cite the source. "
             "A source-slide preview is a screenshot, not editable PowerPoint content.", "",
             "## Converted source text", ""]
    lines.extend(f"- `{item['source']}` → `{item['text']}`" for item in result["documents"])
    if not result["documents"]:
        lines.append("No convertible documents supplied.")
    lines.extend(["", "## Available visuals", ""])
    lines.extend(_catalog_line(item) for item in result["assets"])
    if not result["assets"]:
        lines.append("No source images found.")
    if result["issues"]:
        lines.extend(["", "## Intake limits", ""])
        lines.extend(f"- {issue}" for issue in result["issues"])
    (analysis / "catalog.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
