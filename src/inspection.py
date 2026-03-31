from __future__ import annotations

import mimetypes
from datetime import datetime
from pathlib import Path

from .knowledge_base import KBSearchResult, load_kb_entries, search_knowledge_base
from .manifest import load_run_manifest
from .utils import STAGES, StageSpec, approved_stage_summaries, build_run_paths, read_text


def list_run_roots(runs_dir: Path) -> list[Path]:
    if not runs_dir.exists():
        return []
    return sorted(path for path in runs_dir.iterdir() if path.is_dir())


def run_exists(runs_dir: Path, run_id: str) -> bool:
    return (runs_dir / run_id).exists()


def build_run_snapshot(run_root: Path) -> dict[str, object]:
    paths = build_run_paths(run_root)
    manifest = load_run_manifest(paths.run_manifest)
    memory_text = read_text(paths.memory) if paths.memory.exists() else ""
    approved_memory = approved_stage_summaries(memory_text)
    approved_titles = {
        entry.title
        for entry in (manifest.stages if manifest else [])
        if entry.approved
    }
    kb_entries = load_kb_entries(paths.knowledge_base_entries)

    stage_statuses: list[dict[str, object]] = []
    for stage in STAGES:
        final_stage_path = paths.stage_file(stage)
        tmp_stage_path = paths.stage_tmp_file(stage)
        approved = stage.stage_title in approved_titles or stage.stage_title in approved_memory
        stage_statuses.append(
            {
                "number": stage.number,
                "slug": stage.slug,
                "title": stage.stage_title,
                "pattern": stage.orchestration_pattern,
                "approved": approved,
                "final_exists": final_stage_path.exists(),
                "draft_exists": tmp_stage_path.exists(),
                "final_stage_path": str(final_stage_path),
                "draft_stage_path": str(tmp_stage_path),
            }
        )

    snapshot = {
        "run_id": run_root.name,
        "run_root": str(run_root),
        "status": manifest.run_status.upper() if manifest else "UNKNOWN",
        "last_event": manifest.last_event if manifest else None,
        "updated_at": manifest.updated_at if manifest else None,
        "current_stage_slug": manifest.current_stage_slug if manifest else None,
        "current_stage_title": next((entry.title for entry in manifest.stages if entry.slug == manifest.current_stage_slug), None) if manifest and manifest.current_stage_slug else None,
        "current_pattern": None,
        "current_attempt": next((entry.attempt_count for entry in manifest.stages if entry.slug == manifest.current_stage_slug), None) if manifest and manifest.current_stage_slug else None,
        "waiting_for_human_review": manifest.run_status == "human_review" if manifest else False,
        "last_error": manifest.last_error if manifest else None,
        "completed_at": manifest.completed_at if manifest else None,
        "approved_stage_count": len([entry for entry in manifest.stages if entry.approved]) if manifest else 0,
        "knowledge_base_entry_count": len(kb_entries),
        "knowledge_base_entry_types": _count_entry_types(kb_entries),
        "stages": stage_statuses,
    }
    return snapshot


def list_run_summaries(runs_dir: Path) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for run_root in list_run_roots(runs_dir):
        snapshot = build_run_snapshot(run_root)
        summaries.append(
            {
                "run_id": snapshot["run_id"],
                "status": snapshot["status"],
                "updated_at": snapshot["updated_at"],
                "current_stage_title": snapshot["current_stage_title"],
                "waiting_for_human_review": snapshot["waiting_for_human_review"],
                "approved_stage_count": snapshot["approved_stage_count"],
                "knowledge_base_entry_count": snapshot["knowledge_base_entry_count"],
            }
        )
    return summaries


def load_run_state_snapshot(run_root: Path) -> object | None:
    paths = build_run_paths(run_root)
    return load_run_manifest(paths.run_manifest)


def list_run_kb_entries(
    run_root: Path,
    *,
    limit: int = 20,
    entry_type: str | None = None,
) -> list[dict[str, object]]:
    paths = build_run_paths(run_root)
    entries = load_kb_entries(paths.knowledge_base_entries)
    if entry_type:
        entries = [entry for entry in entries if entry.entry_type == entry_type]
    entries = entries[-limit:]
    return [entry.to_dict() for entry in reversed(entries)]


def search_run_kb(run_root: Path, query: str, limit: int = 5) -> list[dict[str, object]]:
    paths = build_run_paths(run_root)
    results = search_knowledge_base(paths.knowledge_base_entries, query=query, limit=limit)
    return [_serialize_kb_search_result(result) for result in results]


def get_stage_snapshot(run_root: Path, stage_slug: str) -> dict[str, object]:
    paths = build_run_paths(run_root)
    stage = _resolve_stage(stage_slug)
    final_path = paths.stage_file(stage)
    draft_path = paths.stage_tmp_file(stage)
    final_text = read_text(final_path) if final_path.exists() else ""
    draft_text = read_text(draft_path) if draft_path.exists() else ""
    return {
        "run_id": run_root.name,
        "stage_slug": stage.slug,
        "stage_title": stage.stage_title,
        "final_stage_path": str(final_path),
        "draft_stage_path": str(draft_path),
        "final_exists": final_path.exists(),
        "draft_exists": draft_path.exists(),
        "final_markdown": final_text,
        "draft_markdown": draft_text,
        "selected_markdown": final_text or draft_text,
    }


def get_run_log_tail(run_root: Path, max_chars: int = 6000) -> dict[str, object]:
    paths = build_run_paths(run_root)
    logs_text = read_text(paths.logs) if paths.logs.exists() else ""
    raw_logs_text = read_text(paths.logs_raw) if paths.logs_raw.exists() else ""
    return {
        "run_id": run_root.name,
        "logs_path": str(paths.logs),
        "logs_raw_path": str(paths.logs_raw),
        "logs_tail": logs_text[-max_chars:] if logs_text else "",
        "logs_raw_tail": raw_logs_text[-max_chars:] if raw_logs_text else "",
    }


def get_run_observability(run_root: Path, max_chars: int = 6000) -> dict[str, object]:
    spans_path = run_root / "observability" / "spans.jsonl"
    metrics_path = run_root / "observability" / "metrics.jsonl"
    spans_text = read_text(spans_path) if spans_path.exists() else ""
    metrics_text = read_text(metrics_path) if metrics_path.exists() else ""
    return {
        "run_id": run_root.name,
        "spans_path": str(spans_path),
        "metrics_path": str(metrics_path),
        "spans_tail": spans_text[-max_chars:] if spans_text else "",
        "metrics_tail": metrics_text[-max_chars:] if metrics_text else "",
    }


def get_run_messages(run_root: Path, max_chars: int = 6000) -> dict[str, object]:
    outbox_path = run_root / "messages" / "outbox.jsonl"
    outbox_text = read_text(outbox_path) if outbox_path.exists() else ""
    return {
        "run_id": run_root.name,
        "outbox_path": str(outbox_path),
        "outbox_tail": outbox_text[-max_chars:] if outbox_text else "",
    }


def list_run_artifacts(run_root: Path) -> dict[str, object]:
    paths = build_run_paths(run_root)
    groups = {
        "literature": paths.literature_dir,
        "code": paths.code_dir,
        "data": paths.data_dir,
        "results": paths.results_dir,
        "writing": paths.writing_dir,
        "figures": paths.figures_dir,
        "artifacts": paths.artifacts_dir,
        "notes": paths.notes_dir,
        "reviews": paths.reviews_dir,
    }

    grouped_artifacts: dict[str, list[dict[str, object]]] = {}
    total_files = 0
    for group_name, directory in groups.items():
        artifacts: list[dict[str, object]] = []
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if not path.is_file():
                    continue
                artifacts.append(_serialize_artifact(path, run_root))
        grouped_artifacts[group_name] = artifacts
        total_files += len(artifacts)

    return {
        "run_id": run_root.name,
        "total_files": total_files,
        "groups": grouped_artifacts,
    }


def get_artifact_preview(run_root: Path, relative_path: str, max_chars: int = 8000) -> dict[str, object]:
    run_root_resolved = run_root.resolve()
    candidate = (run_root_resolved / relative_path).resolve()
    try:
        candidate.relative_to(run_root_resolved)
    except ValueError as exc:
        raise ValueError(f"Artifact path escapes the run root: {relative_path}") from exc

    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Artifact not found: {relative_path}")

    artifact = _serialize_artifact(candidate, run_root)
    preview_kind = artifact["preview_kind"]
    preview_text = ""
    if preview_kind == "text":
        preview_text = read_text(candidate)[:max_chars]

    return {
        "run_id": run_root.name,
        "artifact": artifact,
        "preview_text": preview_text,
        "download_path": relative_path,
    }


def _serialize_kb_search_result(result: KBSearchResult) -> dict[str, object]:
    return {
        "score": result.score,
        "entry": result.entry.to_dict(),
    }


def _count_entry_types(entries: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        entry_type = getattr(entry, "entry_type", "")
        counts[entry_type] = counts.get(entry_type, 0) + 1
    return counts


def resolve_artifact_file(run_root: Path, relative_path: str) -> tuple[Path, str]:
    run_root_resolved = run_root.resolve()
    candidate = (run_root_resolved / relative_path).resolve()
    try:
        candidate.relative_to(run_root_resolved)
    except ValueError as exc:
        raise ValueError(f"Artifact path escapes the run root: {relative_path}") from exc

    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Artifact not found: {relative_path}")

    content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return candidate, content_type


def _resolve_stage(value: str) -> StageSpec:
    normalized = value.strip().lower()
    for stage in STAGES:
        if normalized in {stage.slug.lower(), str(stage.number), f"{stage.number:02d}"}:
            return stage
    raise ValueError(f"Unknown stage identifier: {value}")


def _serialize_artifact(path: Path, run_root: Path) -> dict[str, object]:
    suffix = path.suffix.lower()
    preview_kind = "binary"
    if suffix in {".md", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".yaml", ".yml", ".py", ".tex", ".html"}:
        preview_kind = "text"
    elif suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        preview_kind = "image"
    elif suffix == ".pdf":
        preview_kind = "pdf"

    return {
        "relative_path": str(path.resolve().relative_to(run_root.resolve())),
        "name": path.name,
        "group": path.parts[-2] if len(path.parts) >= 2 else "",
        "size_bytes": path.stat().st_size,
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "preview_kind": preview_kind,
        "suffix": suffix,
    }
