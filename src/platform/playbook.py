from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .fault_tolerance import CheckpointManager, ErrorClassifier, RetryPolicy
from .observability import ObservabilityCollector


@dataclass(frozen=True)
class PlaybookStep:
    name: str
    command: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "command": self.command,
        }


@dataclass(frozen=True)
class PlaybookSummary:
    stage_slug: str
    steps: list[PlaybookStep]
    completed_steps: list[str]
    failures: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "stage_slug": self.stage_slug,
            "steps": [step.to_dict() for step in self.steps],
            "completed_steps": list(self.completed_steps),
            "failures": list(self.failures),
        }


class OvernightPlaybookEngine:
    def __init__(self, retry_policy: RetryPolicy | None = None) -> None:
        self.retry_policy = retry_policy or RetryPolicy()
        self.error_classifier = ErrorClassifier()

    def run(
        self,
        run_root: Path,
        stage_slug: str,
        goal: str,
        steps: list[PlaybookStep],
    ) -> PlaybookSummary:
        checkpoint = CheckpointManager(run_root / "control" / f"{stage_slug}_playbook_checkpoint.json")
        collector = ObservabilityCollector(run_root)
        completed_steps: list[str] = []
        failures: list[str] = []

        for step in steps:
            def _execute() -> None:
                collector.emit_span("playbook.step.started", stage_slug=stage_slug, step=step.name)
                collector.emit_metric("clawdock.research.experiment_recovery_total", 0.0, stage_slug=stage_slug)

            try:
                self.retry_policy.run(_execute)
                completed_steps.append(step.name)
                checkpoint.save(
                    {
                        "goal": goal,
                        "stage_slug": stage_slug,
                        "completed_steps": completed_steps,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{step.name}: {self.error_classifier.classify(str(exc))}")

        summary = PlaybookSummary(
            stage_slug=stage_slug,
            steps=steps,
            completed_steps=completed_steps,
            failures=failures,
        )
        summary_path = run_root / "results" / f"{stage_slug}_playbook_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary.to_dict(), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        return summary
