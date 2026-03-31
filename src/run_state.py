from __future__ import annotations

from dataclasses import dataclass, field

from .manifest import RunManifest


RUN_STATUS_PENDING = "PENDING"
RUN_STATUS_RUNNING = "RUNNING"
RUN_STATUS_HUMAN_REVIEW = "HUMAN_REVIEW"
RUN_STATUS_COMPLETED = "COMPLETED"
RUN_STATUS_FAILED = "FAILED"
RUN_STATUS_CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class RunState:
    run_id: str
    status: str
    created_at: str
    updated_at: str
    last_event: str
    current_stage_slug: str | None = None
    current_stage_title: str | None = None
    current_pattern: str | None = None
    current_attempt: int | None = None
    human_review_required: bool = True
    waiting_for_human_review: bool = False
    approved_stages: list[dict[str, str]] = field(default_factory=list)
    last_error: str | None = None
    completed_at: str | None = None


def derive_run_state(manifest: RunManifest) -> RunState:
    current_entry = next((entry for entry in manifest.stages if entry.slug == manifest.current_stage_slug), None)
    approved_entries = [entry for entry in manifest.stages if entry.approved]
    return RunState(
        run_id=manifest.run_id,
        status=manifest.run_status.upper(),
        created_at=manifest.created_at,
        updated_at=manifest.updated_at,
        last_event=manifest.last_event,
        current_stage_slug=manifest.current_stage_slug,
        current_stage_title=current_entry.title if current_entry else None,
        current_pattern=None,
        current_attempt=current_entry.attempt_count if current_entry else None,
        human_review_required=True,
        waiting_for_human_review=manifest.run_status == "human_review",
        approved_stages=[
            {
                "slug": entry.slug,
                "title": entry.title,
                "approved_at": entry.approved_at or "",
            }
            for entry in approved_entries
        ],
        last_error=manifest.last_error,
        completed_at=manifest.completed_at,
    )


def format_run_state(state: RunState) -> str:
    lines = [
        f"Run: {state.run_id}",
        f"Status: {state.status}",
        f"Last Event: {state.last_event}",
        f"Updated At: {state.updated_at}",
    ]

    if state.current_stage_title:
        lines.append(f"Current Stage: {state.current_stage_title}")
    if state.current_pattern:
        lines.append(f"Stage Pattern: {state.current_pattern}")
    if state.current_attempt is not None:
        lines.append(f"Current Attempt: {state.current_attempt}")

    lines.append(f"Waiting For Human Review: {state.waiting_for_human_review}")
    lines.append(f"Approved Stages: {len(state.approved_stages)}")

    if state.last_error:
        lines.append(f"Last Error: {state.last_error}")
    if state.completed_at:
        lines.append(f"Completed At: {state.completed_at}")

    return "\n".join(lines)
