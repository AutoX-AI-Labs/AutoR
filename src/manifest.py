from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from .utils import RunPaths, StageSpec, STAGES


@dataclass(frozen=True)
class StageManifestEntry:
    number: int
    slug: str
    title: str
    status: str = "pending"
    approved: bool = False
    dirty: bool = False
    attempt_count: int = 0
    session_id: str | None = None
    final_stage_path: str = ""
    draft_stage_path: str = ""
    artifact_paths: list[str] = field(default_factory=list)
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
            "attempt_count": self.attempt_count,
            "session_id": self.session_id,
            "final_stage_path": self.final_stage_path,
            "draft_stage_path": self.draft_stage_path,
            "artifact_paths": list(self.artifact_paths),
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
            status=str(payload.get("status") or "pending"),
            approved=bool(payload.get("approved", False)),
            dirty=bool(payload.get("dirty", False)),
            attempt_count=int(payload.get("attempt_count") or 0),
            session_id=str(payload["session_id"]) if payload.get("session_id") is not None else None,
            final_stage_path=str(payload.get("final_stage_path") or ""),
            draft_stage_path=str(payload.get("draft_stage_path") or ""),
            artifact_paths=[str(item) for item in payload.get("artifact_paths", []) if str(item).strip()],
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
            run_status=str(payload.get("run_status") or "pending"),
            last_event=str(payload.get("last_event") or "run.created"),
            current_stage_slug=str(payload["current_stage_slug"]) if payload.get("current_stage_slug") is not None else None,
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
        run_status="pending",
        last_event="run.created",
        current_stage_slug=None,
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


def load_run_manifest(path) -> RunManifest | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return RunManifest.from_dict(json.loads(text))


def save_run_manifest(path, manifest: RunManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def format_manifest_status(manifest: RunManifest) -> str:
    lines = [
        f"Run: {manifest.run_id}",
        f"Updated At: {manifest.updated_at}",
        f"Run Status: {manifest.run_status}",
        f"Last Event: {manifest.last_event}",
        f"Current Stage: {manifest.current_stage_slug or 'None'}",
        "Stages:",
    ]
    for entry in manifest.stages:
        lines.append(
            f"- {entry.slug}: status={entry.status}, approved={entry.approved}, attempts={entry.attempt_count}, "
            f"session_id={entry.session_id or 'none'}"
        )
    return "\n".join(lines)


def update_manifest_run_status(
    paths: RunPaths,
    *,
    run_status: str,
    last_event: str,
    current_stage_slug: str | None = None,
    last_error: str | None = None,
    completed_at: str | None = None,
) -> RunManifest:
    manifest = ensure_run_manifest(paths)
    updated = RunManifest(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        updated_at=_now(),
        run_status=run_status,
        last_event=last_event,
        current_stage_slug=current_stage_slug,
        last_error=last_error,
        completed_at=completed_at,
        stages=manifest.stages,
    )
    save_run_manifest(paths.run_manifest, updated)
    return updated


def update_stage_entry(paths: RunPaths, stage: StageSpec, **changes: object) -> RunManifest:
    manifest = ensure_run_manifest(paths)
    updated_stages: list[StageManifestEntry] = []
    for entry in manifest.stages:
        if entry.slug != stage.slug:
            updated_stages.append(entry)
            continue
        payload = entry.to_dict()
        payload.update(changes)
        payload["updated_at"] = _now()
        updated_stages.append(StageManifestEntry.from_dict(payload))

    updated = RunManifest(
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        updated_at=_now(),
        run_status=manifest.run_status,
        last_event=manifest.last_event,
        current_stage_slug=manifest.current_stage_slug,
        last_error=manifest.last_error,
        completed_at=manifest.completed_at,
        stages=updated_stages,
    )
    save_run_manifest(paths.run_manifest, updated)
    return updated


def mark_stage_running_manifest(paths: RunPaths, stage: StageSpec, attempt_no: int) -> RunManifest:
    update_manifest_run_status(
        paths,
        run_status="running",
        last_event="stage.started",
        current_stage_slug=stage.slug,
    )
    return update_stage_entry(
        paths,
        stage,
        status="running",
        approved=False,
        dirty=False,
        attempt_count=attempt_no,
        last_error=None,
    )


def mark_stage_human_review_manifest(
    paths: RunPaths,
    stage: StageSpec,
    attempt_no: int,
    artifact_paths: list[str],
) -> RunManifest:
    update_manifest_run_status(
        paths,
        run_status="human_review",
        last_event="stage.awaiting_human_review",
        current_stage_slug=stage.slug,
    )
    return update_stage_entry(
        paths,
        stage,
        status="human_review",
        approved=False,
        dirty=False,
        attempt_count=attempt_no,
        artifact_paths=artifact_paths,
    )


def mark_stage_approved_manifest(
    paths: RunPaths,
    stage: StageSpec,
    attempt_no: int,
    artifact_paths: list[str],
) -> RunManifest:
    update_manifest_run_status(
        paths,
        run_status="pending",
        last_event="stage.approved",
        current_stage_slug=None,
    )
    return update_stage_entry(
        paths,
        stage,
        status="approved",
        approved=True,
        dirty=False,
        attempt_count=attempt_no,
        artifact_paths=artifact_paths,
        approved_at=_now(),
    )


def mark_stage_failed_manifest(paths: RunPaths, stage: StageSpec, error: str) -> RunManifest:
    update_manifest_run_status(
        paths,
        run_status="failed",
        last_event="stage.failed",
        current_stage_slug=stage.slug,
        last_error=error,
    )
    return update_stage_entry(
        paths,
        stage,
        status="failed",
        approved=False,
        dirty=True,
        last_error=error,
    )


def sync_stage_session_id(paths: RunPaths, stage: StageSpec, session_id: str | None) -> RunManifest:
    return update_stage_entry(paths, stage, session_id=session_id)
