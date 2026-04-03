from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .artifact_index import indexed_artifacts_for_category, write_artifact_index
from .utils import RunPaths


FIGURE_SUFFIXES = {".png", ".pdf", ".svg", ".jpg", ".jpeg", ".eps"}
RESULT_SUFFIXES = {".json", ".jsonl", ".csv", ".tsv", ".parquet", ".npz", ".npy"}


def build_writing_manifest(paths: RunPaths) -> dict[str, object]:
    artifact_index = write_artifact_index(paths)
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "artifact_index_path": str(paths.artifact_index.relative_to(paths.run_root)),
        "figures": indexed_artifacts_for_category(artifact_index, "figures"),
        "result_files": indexed_artifacts_for_category(artifact_index, "results"),
        "data_files": indexed_artifacts_for_category(artifact_index, "data"),
        "stage_summaries": _collect_stage_summaries(paths),
    }

    paths.writing_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = paths.writing_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def scan_figures(figures_dir: Path) -> list[dict[str, object]]:
    if not figures_dir.exists():
        return []

    figures: list[dict[str, object]] = []
    for path in sorted(figures_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in FIGURE_SUFFIXES:
            figures.append(
                {
                    "filename": path.name,
                    "rel_path": f"figures/{path.relative_to(figures_dir)}",
                    "size_bytes": path.stat().st_size,
                }
            )
    return figures


def scan_results(results_dir: Path) -> list[dict[str, object]]:
    if not results_dir.exists():
        return []

    results: list[dict[str, object]] = []
    for path in sorted(results_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in RESULT_SUFFIXES:
            results.append(
                {
                    "filename": path.name,
                    "rel_path": f"results/{path.relative_to(results_dir)}",
                    "type": path.suffix.lstrip("."),
                }
            )
    return results


def format_manifest_for_prompt(manifest: dict[str, object]) -> str:
    parts: list[str] = []
    artifact_index_path = manifest.get("artifact_index_path")
    if isinstance(artifact_index_path, str) and artifact_index_path.strip():
        parts.append(f"Artifact index: `{artifact_index_path}`")

    figures = manifest.get("figures", [])
    if isinstance(figures, list) and figures:
        parts.append("\n### Available Figures")
        for fig in figures:
            if isinstance(fig, dict):
                line = f"- `{fig['rel_path']}` ({fig['size_bytes']} bytes)"
                schema = _format_schema(fig.get("schema"))
                if schema:
                    line += f" | {schema}"
                parts.append(line)

    result_files = manifest.get("result_files", [])
    if isinstance(result_files, list) and result_files:
        parts.append("\n### Available Result Files")
        for result in result_files:
            if isinstance(result, dict):
                line = f"- `{result['rel_path']}` (type: {result.get('suffix', '').lstrip('.') or 'file'})"
                schema = _format_schema(result.get("schema"))
                if schema:
                    line += f" | {schema}"
                parts.append(line)

    data_files = manifest.get("data_files", [])
    if isinstance(data_files, list) and data_files:
        parts.append("\n### Available Data Files")
        for data_file in data_files:
            if isinstance(data_file, dict):
                line = f"- `{data_file['rel_path']}`"
                schema = _format_schema(data_file.get("schema"))
                if schema:
                    line += f" | {schema}"
                parts.append(line)

    stage_summaries = manifest.get("stage_summaries", {})
    if isinstance(stage_summaries, dict) and stage_summaries:
        parts.append("\n### Available Stage Summaries")
        for stage_slug, rel_path in sorted(stage_summaries.items()):
            parts.append(f"- `{stage_slug}` -> `{rel_path}`")

    if not parts:
        parts.append("No experiment artifacts found in workspace.")

    return "\n".join(parts)


def _scan_dir(directory: Path) -> list[str]:
    if not directory.exists():
        return []

    return sorted(
        str(path.relative_to(directory.parent))
        for path in directory.rglob("*")
        if path.is_file()
    )


def _collect_stage_summaries(paths: RunPaths) -> dict[str, str]:
    summaries: dict[str, str] = {}
    if paths.stages_dir.exists():
        for stage_file in sorted(paths.stages_dir.glob("*.md")):
            if not stage_file.name.endswith(".tmp.md"):
                summaries[stage_file.stem] = str(stage_file.relative_to(paths.run_root))
    return summaries


def _format_schema(schema: object) -> str:
    if not isinstance(schema, dict) or not schema:
        return ""

    pieces: list[str] = []
    kind = str(schema.get("kind") or schema.get("source") or "").strip()
    if kind:
        pieces.append(kind)
    if isinstance(schema.get("columns"), list) and schema["columns"]:
        pieces.append("columns=" + ", ".join(str(item) for item in schema["columns"][:6]))
    if isinstance(schema.get("keys"), list) and schema["keys"]:
        pieces.append("keys=" + ", ".join(str(item) for item in schema["keys"][:6]))
    if "row_count" in schema:
        pieces.append(f"rows={schema['row_count']}")
    if "item_count" in schema:
        pieces.append(f"items={schema['item_count']}")
    if "sidecar_path" in schema:
        pieces.append(f"schema={schema['sidecar_path']}")

    return ", ".join(pieces)
