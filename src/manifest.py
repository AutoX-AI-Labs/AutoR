from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .utils import (
    STAGES,
    RunPaths,
    StageSpec,
    approved_stage_summaries,
    extract_markdown_section,
    parse_refinement_suggestions,
    read_text,
    render_approved_stage_entry,
    write_text,
)


STAGE_STATUS_PENDING = "pending"
STAGE_STATUS_RUNNING = "running"
STAGE_STATUS_HUMAN_REVIEW = "human_review"
STAGE_STATUS_APPROVED = "approved"
STAGE_STATUS_STALE = "stale"
STAGE_STATUS_FAILED = "failed"
STAGE_STATUS_CANCELLED = "cancelled"


@dataclass(frozen=True)
class StageManifestEntry:
    number: int
    slug: str
    title: str
    status: str = STAGE_STATUS_PENDING
    approved: bool = False
    dirty: bool = False
    stale: bool = False
    attempt_count: int = 0
    session_id: str | None = None
    final_stage_path: str = ""
    draft_stage_path: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    handoff_path: str | None = None
    compressed_summary: str = ""
    invalidated_reason: str | None = None
    invalidated_by_stage: str | None = None
    last_error: str | None = None
    updated_at: str = ""
    approved_at: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "slug": self.slug,
            "title": self.title,
            "status": self.status,
            "approved": self.approved,
            "dirty": self.dirty,
            "stale": self.stale,
            "attempt_count": self.attempt_count,
            "session_id": self.session_id,
            "final_stage_path": self.final_stage_path,
            "draft_stage_path": self.draft_stage_path,
            "artifact_paths": list(self.artifact_paths),
            "handoff_path": self.handoff_path,
            "compressed_summary": self.compressed_summary,
            "invalidated_reason": self.invalidated_reason,
            "invalidated_by_stage": self.invalidated_by_stage,
            "last_error": self.last_error,
            "updated_at": self.updated_at,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "StageManifestEntry":
        return cls(
            number=int(payload.get("number") or 0),
            slug=str(payload.get("slug") or ""),
            title=str(payload.get("title") or ""),
            status=str(payload.get("status") or STAGE_STATUS_PENDING),
            approved=bool(payload.get("approved", False)),
            dirty=bool(payload.get("dirty", False)),
            stale=bool(payload.get("stale", False)),
            attempt_count=int(payload.get("attempt_count") or 0),
            session_id=str(payload["session_id"]) if payload.get("session_id") is not None else None,
            final_stage_path=str(payload.get("final_stage_path") or ""),
            draft_stage_path=str(payload.get("draft_stage_path") or ""),
            artifact_paths=[str(item) for item in payload.get("artifact_paths", []) if str(item).strip()],
            handoff_path=str(payload["handoff_path"]) if payload.get("handoff_path") is not None else None,
            compressed_summary=str(payload.get("compressed_summary") or ""),
            invalidated_reason=str(payload["invalidated_reason"]) if payload.get("invalidated_reason") is not None else None,
            invalidated_by_stage=str(payload["invalidated_by_stage"]) if payload.get("invalidated_by_stage") is not None else None,
            last_error=str(payload["last_error"]) if payload.get("last_error") is not None else None,
            updated_at=str(payload.get("updated_at") or ""),
            approved_at=str(payload["approved_at"]) if payload.get("approved_at") is not None else None,
        )


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    created_at: str
    updated_at: str
    run_status: str
    last_event: str
    current_stage_slug: str | None
    latest_approved_stage_slug: str | None
    last_error: str | None
    completed_at: str | None
    stages: list[StageManifestEntry]

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_status": self.run_status,
            "last_event": self.last_event,
            "current_stage_slug": self.current_stage_slug,
            "latest_approved_stage_slug": self.latest_approved_stage_slug,
            "last_error": self.last_error,
            "completed_at": self.completed_at,
            "stages": [stage.to_dict() for stage in self.stages],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "RunManifest":
        stages = payload.get("stages", [])
        return cls(
            run_id=str(payload.get("run_id") or ""),
            created_at=str(payload.get("created_at") or _now()),
            updated_at=str(payload.get("updated_at") or _now()),
            run_status=str(payload.get("run_status") or STAGE_STATUS_PENDING),
            last_event=str(payload.get("last_event") or "run.created"),
            current_stage_slug=str(payload["current_stage_slug"]) if payload.get("current_stage_slug") is not None else None,
            latest_approved_stage_slug=str(payload["latest_approved_stage_slug"]) if payload.get("latest_approved_stage_slug") is not None else None,
            last_error=str(payload["last_error"]) if payload.get("last_error") is not None else None,
            completed_at=str(payload["completed_at"]) if payload.get("completed_at") is not None else None,
            stages=[StageManifestEntry.from_dict(item) for item in stages if isinstance(item, dict)],
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def initialize_run_manifest(paths: RunPaths) -> RunManifest:
    timestamp = _now()
    manifest = RunManifest(
        run_id=paths.run_root.name,
        created_at=timestamp,
        updated_at=timestamp,
        run_status=STAGE_STATUS_PENDING,
        last_event="run.created",
        current_stage_slug=None,
        latest_approved_stage_slug=None,
        last_error=None,
        completed_at=None,
        stages=[
            StageManifestEntry(
                number=stage.number,
                slug=stage.slug,
                title=stage.stage_title,
                final_stage_path=str(paths.stage_file(stage).relative_to(paths.run_root)),
                draft_stage_path=str(paths.stage_tmp_file(stage).relative_to(paths.run_root)),
                updated_at=timestamp,
            )
            for stage in STAGES
        ],
    )
    save_run_manifest(paths.run_manifest, manifest)
    return manifest


def ensure_run_manifest(paths: RunPaths) -> RunManifest:
    manifest = load_run_manifest(paths.run_manifest)
    if manifest is not None:
        return manifest
    return initialize_run_manifest(paths)


def load_run_manifest(path: Path) -> RunManifest | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return RunManifest.from_dict(json.loads(text))


def save_run_manifest(path: Path, manifest: RunManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def get_stage_entry(manifest: RunManifest, stage: StageSpec) -> StageManifestEntry:
    for entry in manifest.stages:
        if entry.slug == stage.slug:
            return entry
    raise KeyError(f"Stage not found in manifest: {stage.slug}")


def update_stage_entry(paths: RunPaths, stage: StageSpec, **changes: object) -> RunManifest:
    manifest = ensure_run_manifest(paths)
    updated_entries: list[StageManifestEntry] = []
    for entry in manifest.stages:
        if entry.slug != stage.slug:
            updated_entries.append(entry)
            continue
        payload = entry.to_dict()
        payload.update(changes)
        payload["updated_at"] = _now()
        updated_entries.append(StageManifestEntry.from_dict(payload))
    latest_approved = _latest_approved_slug(updated_entries)
    updated_manifest = RunManifest(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        updated_at=_now(),
        run_status=manifest.run_status,
        last_event=manifest.last_event,
        current_stage_slug=changes.get("current_stage_slug", manifest.current_stage_slug)
        if "current_stage_slug" in changes
        else manifest.current_stage_slug,
        latest_approved_stage_slug=latest_approved,
        last_error=manifest.last_error,
        completed_at=manifest.completed_at,
        stages=updated_entries,
    )
    save_run_manifest(paths.run_manifest, updated_manifest)
    return updated_manifest


def mark_stage_running_manifest(paths: RunPaths, stage: StageSpec, attempt_no: int) -> RunManifest:
    return _update_manifest_metadata(
        paths,
        stage,
        status=STAGE_STATUS_RUNNING,
        run_status=STAGE_STATUS_RUNNING,
        last_event="stage.started",
        approved=False,
        dirty=False,
        stale=False,
        attempt_count=attempt_no,
        invalidated_reason=None,
        invalidated_by_stage=None,
        last_error=None,
        current_stage_slug=stage.slug,
    )


def mark_stage_human_review_manifest(paths: RunPaths, stage: StageSpec, attempt_no: int, artifact_paths: list[str]) -> RunManifest:
    return _update_manifest_metadata(
        paths,
        stage,
        status=STAGE_STATUS_HUMAN_REVIEW,
        run_status=STAGE_STATUS_HUMAN_REVIEW,
        last_event="stage.awaiting_human_review",
        approved=False,
        dirty=False,
        stale=False,
        attempt_count=attempt_no,
        artifact_paths=artifact_paths,
        current_stage_slug=stage.slug,
    )


def mark_stage_approved_manifest(
    paths: RunPaths,
    stage: StageSpec,
    attempt_no: int,
    artifact_paths: list[str],
    compressed_summary: str,
    handoff_path: str,
) -> RunManifest:
    return _update_manifest_metadata(
        paths,
        stage,
        status=STAGE_STATUS_APPROVED,
        run_status=STAGE_STATUS_PENDING,
        last_event="stage.approved",
        approved=True,
        dirty=False,
        stale=False,
        attempt_count=attempt_no,
        artifact_paths=artifact_paths,
        compressed_summary=compressed_summary,
        handoff_path=handoff_path,
        approved_at=_now(),
        invalidated_reason=None,
        invalidated_by_stage=None,
        last_error=None,
        current_stage_slug=None,
    )


def mark_stage_failed_manifest(paths: RunPaths, stage: StageSpec, error: str) -> RunManifest:
    return _update_manifest_metadata(
        paths,
        stage,
        status=STAGE_STATUS_FAILED,
        run_status=STAGE_STATUS_FAILED,
        last_event="stage.failed",
        approved=False,
        dirty=True,
        stale=False,
        last_error=error,
        current_stage_slug=stage.slug,
    )


def sync_stage_session_id(paths: RunPaths, stage: StageSpec, session_id: str | None) -> RunManifest:
    return _update_manifest_metadata(paths, stage, session_id=session_id)


def rollback_to_stage(paths: RunPaths, rollback_stage: StageSpec, reason: str | None = None) -> RunManifest:
    manifest = ensure_run_manifest(paths)
    updated_entries: list[StageManifestEntry] = []
    current_slug = rollback_stage.slug
    invalidated_reason = reason or f"Rolled back to {rollback_stage.stage_title}"
    for entry in manifest.stages:
        payload = entry.to_dict()
        if entry.number < rollback_stage.number:
            updated_entries.append(entry)
            continue
        if entry.number == rollback_stage.number:
            payload.update(
                {
                    "status": STAGE_STATUS_PENDING,
                    "approved": False,
                    "dirty": True,
                    "stale": False,
                    "invalidated_reason": invalidated_reason,
                    "invalidated_by_stage": rollback_stage.slug,
                    "approved_at": None,
                }
            )
        else:
            payload.update(
                {
                    "status": STAGE_STATUS_STALE,
                    "approved": False,
                    "dirty": True,
                    "stale": True,
                    "invalidated_reason": invalidated_reason,
                    "invalidated_by_stage": rollback_stage.slug,
                    "approved_at": None,
                }
            )
        payload["updated_at"] = _now()
        updated_entries.append(StageManifestEntry.from_dict(payload))

    updated_manifest = RunManifest(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        updated_at=_now(),
        run_status=STAGE_STATUS_PENDING,
        last_event="run.rolled_back",
        current_stage_slug=current_slug,
        latest_approved_stage_slug=_latest_approved_slug(updated_entries),
        last_error=None,
        completed_at=None,
        stages=updated_entries,
    )
    save_run_manifest(paths.run_manifest, updated_manifest)
    rebuild_memory_from_manifest(paths, updated_manifest)
    return updated_manifest


def rebuild_memory_from_manifest(paths: RunPaths, manifest: RunManifest | None = None) -> None:
    manifest = manifest or ensure_run_manifest(paths)
    goal_text = read_text(paths.user_input).strip()
    entries: list[str] = []
    for stage in STAGES:
        entry = get_stage_entry(manifest, stage)
        if not entry.approved:
            continue
        stage_path = paths.stage_file(stage)
        if not stage_path.exists():
            continue
        entries.append(render_approved_stage_entry(stage, read_text(stage_path)))

    body = (
        "# Approved Run Memory\n\n"
        "## Original User Goal\n"
        f"{goal_text}\n\n"
        "## Approved Stage Summaries\n\n"
    )
    if entries:
        body += "\n\n".join(entries) + "\n"
    else:
        body += "_None yet._\n"
    write_text(paths.memory, body)


def format_manifest_status(manifest: RunManifest) -> str:
    lines = [
        f"Run: {manifest.run_id}",
        f"Updated At: {manifest.updated_at}",
        f"Run Status: {manifest.run_status}",
        f"Last Event: {manifest.last_event}",
        f"Current Stage: {manifest.current_stage_slug or 'None'}",
        f"Latest Approved Stage: {manifest.latest_approved_stage_slug or 'None'}",
        "",
        "Stages:",
    ]
    for entry in manifest.stages:
        flags = []
        if entry.approved:
            flags.append("approved")
        if entry.dirty:
            flags.append("dirty")
        if entry.stale:
            flags.append("stale")
        suffix = f" [{' '.join(flags)}]" if flags else ""
        lines.append(
            f"- {entry.slug}: status={entry.status}, attempts={entry.attempt_count}, "
            f"session_id={entry.session_id or 'none'}{suffix}"
        )
    return "\n".join(lines)


def write_stage_handoff(paths: RunPaths, stage: StageSpec, stage_markdown: str) -> Path:
    paths.handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_path = paths.handoff_dir / f"{stage.slug}.md"
    objective = extract_markdown_section(stage_markdown, "Objective") or "Not provided."
    key_results = extract_markdown_section(stage_markdown, "Key Results") or "Not provided."
    files_produced = extract_markdown_section(stage_markdown, "Files Produced") or "Not provided."
    suggestions = parse_refinement_suggestions(stage_markdown)
    handoff = (
        f"# Handoff: {stage.stage_title}\n\n"
        "## Objective\n"
        f"{objective}\n\n"
        "## Key Results\n"
        f"{key_results}\n\n"
        "## Files Produced\n"
        f"{files_produced}\n\n"
        "## Open Questions / Refinement Hooks\n"
        f"1. {suggestions[0]}\n"
        f"2. {suggestions[1]}\n"
        f"3. {suggestions[2]}\n"
    )
    write_text(handoff_path, handoff)
    return handoff_path


def build_handoff_context(paths: RunPaths, upto_stage: StageSpec | None = None, max_stages: int = 4) -> str:
    manifest = ensure_run_manifest(paths)
    approved_entries = [entry for entry in manifest.stages if entry.approved]
    if upto_stage is not None:
        approved_entries = [entry for entry in approved_entries if entry.number < upto_stage.number]
    approved_entries = approved_entries[-max_stages:]
    chunks: list[str] = []
    for entry in approved_entries:
        if not entry.handoff_path:
            continue
        handoff_path = paths.run_root / entry.handoff_path
        if not handoff_path.exists():
            continue
        chunks.append(read_text(handoff_path).strip())
    return "\n\n".join(chunks).strip() or "No stage handoff summaries available yet."


def build_manifest_context(paths: RunPaths, upto_stage: StageSpec | None = None) -> str:
    manifest = ensure_run_manifest(paths)
    entries = manifest.stages
    if upto_stage is not None:
        entries = [entry for entry in entries if entry.number <= upto_stage.number]
    lines = [
        f"Current Stage: {manifest.current_stage_slug or 'None'}",
        f"Latest Approved Stage: {manifest.latest_approved_stage_slug or 'None'}",
    ]
    for entry in entries:
        lines.append(
            f"- {entry.slug}: status={entry.status}, approved={entry.approved}, "
            f"dirty={entry.dirty}, stale={entry.stale}, attempts={entry.attempt_count}"
        )
    return "\n".join(lines)


def approved_stage_numbers(manifest: RunManifest) -> list[int]:
    return [entry.number for entry in manifest.stages if entry.approved]


def _update_manifest_metadata(paths: RunPaths, stage: StageSpec, **changes: object) -> RunManifest:
    manifest = ensure_run_manifest(paths)
    updated_entries: list[StageManifestEntry] = []
    for entry in manifest.stages:
        if entry.slug != stage.slug:
            updated_entries.append(entry)
            continue
        payload = entry.to_dict()
        payload.update(changes)
        payload["updated_at"] = _now()
        updated_entries.append(StageManifestEntry.from_dict(payload))
    current_stage_slug = changes.get("current_stage_slug")
    updated_manifest = RunManifest(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        updated_at=_now(),
        run_status=str(changes.get("run_status") or manifest.run_status),
        last_event=str(changes.get("last_event") or manifest.last_event),
        current_stage_slug=current_stage_slug if isinstance(current_stage_slug, str) or current_stage_slug is None else manifest.current_stage_slug,
        latest_approved_stage_slug=_latest_approved_slug(updated_entries),
        last_error=str(changes["last_error"]) if changes.get("last_error") is not None else manifest.last_error,
        completed_at=str(changes["completed_at"]) if changes.get("completed_at") is not None else manifest.completed_at,
        stages=updated_entries,
    )
    save_run_manifest(paths.run_manifest, updated_manifest)
    return updated_manifest


def update_manifest_run_status(
    paths: RunPaths,
    *,
    run_status: str,
    last_event: str,
    last_error: str | None = None,
    completed_at: str | None = None,
    current_stage_slug: str | None = None,
) -> RunManifest:
    manifest = ensure_run_manifest(paths)
    updated_manifest = RunManifest(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        updated_at=_now(),
        run_status=run_status,
        last_event=last_event,
        current_stage_slug=current_stage_slug,
        latest_approved_stage_slug=manifest.latest_approved_stage_slug,
        last_error=last_error,
        completed_at=completed_at,
        stages=manifest.stages,
    )
    save_run_manifest(paths.run_manifest, updated_manifest)
    return updated_manifest


def _latest_approved_slug(entries: list[StageManifestEntry]) -> str | None:
    approved = [entry for entry in entries if entry.approved]
    if not approved:
        return None
    latest = max(approved, key=lambda item: item.number)
    return latest.slug
