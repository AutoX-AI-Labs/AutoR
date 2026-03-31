"""Artifact scanner and manifest generator for Stage 07 writing pipeline."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .utils import RunPaths

FIGURE_SUFFIXES = {".png", ".pdf", ".svg", ".jpg", ".jpeg", ".eps"}
RESULT_SUFFIXES = {".json", ".jsonl", ".csv", ".tsv", ".parquet", ".npz", ".npy"}


def build_writing_manifest(paths: RunPaths) -> dict:
    """Scan workspace directories and produce a structured writing manifest.

    The manifest tells the agent what artifacts are available for the paper.
    Written to workspace/writing/manifest.json.
    """
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "figures": scan_figures(paths.figures_dir),
        "result_files": scan_results(paths.results_dir),
        "data_files": _scan_dir(paths.data_dir),
        "stage_summaries": _collect_stage_summaries(paths),
    }

    paths.writing_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = paths.writing_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def scan_figures(figures_dir: Path) -> list[dict]:
    """Return list of figure metadata dicts."""
    if not figures_dir.exists():
        return []
    results = []
    for path in sorted(figures_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in FIGURE_SUFFIXES:
            results.append({
                "filename": path.name,
                "rel_path": f"figures/{path.relative_to(figures_dir)}",
                "size_bytes": path.stat().st_size,
            })
    return results


def scan_results(results_dir: Path) -> list[dict]:
    """Return list of result file metadata dicts."""
    if not results_dir.exists():
        return []
    results = []
    for path in sorted(results_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in RESULT_SUFFIXES:
            results.append({
                "filename": path.name,
                "rel_path": f"results/{path.relative_to(results_dir)}",
                "type": path.suffix.lstrip("."),
            })
    return results


def _scan_dir(directory: Path) -> list[str]:
    """Return list of relative paths for all files in a directory."""
    if not directory.exists():
        return []
    return sorted(
        str(path.relative_to(directory.parent))
        for path in directory.rglob("*")
        if path.is_file()
    )


def _collect_stage_summaries(paths: RunPaths) -> dict[str, str]:
    """Collect paths to existing stage summaries."""
    summaries = {}
    if paths.stages_dir.exists():
        for stage_file in sorted(paths.stages_dir.glob("*.md")):
            if not stage_file.name.endswith(".tmp.md"):
                summaries[stage_file.stem] = str(stage_file.relative_to(paths.run_root))
    return summaries


def format_manifest_for_prompt(manifest: dict) -> str:
    """Format the manifest into a concise string for the agent prompt."""
    parts: list[str] = []

    figures = manifest.get("figures", [])
    if figures:
        parts.append("### Available Figures")
        for fig in figures:
            parts.append(f"- `{fig['rel_path']}` ({fig['size_bytes']} bytes)")

    result_files = manifest.get("result_files", [])
    if result_files:
        parts.append("\n### Available Result Files")
        for rf in result_files:
            parts.append(f"- `{rf['rel_path']}` (type: {rf['type']})")

    if not parts:
        parts.append("No experiment artifacts found in workspace.")

    return "\n".join(parts)
