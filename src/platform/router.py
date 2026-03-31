from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..utils import RunPaths, StageSpec, write_text
from .agents import AgentRuntimeManager, CommandResearchAgent
from .debate import HypothesisDebateWorkflow
from .foundry import generate_paper_package, generate_release_package
from .literature import LiteratureSurveyWorkflow
from .observability import ObservabilityCollector
from .orchestration import HierarchicalPattern, ParallelPattern, SequentialPattern, SwarmPattern
from .playbook import OvernightPlaybookEngine, PlaybookStep
from .types import PipelineStage, ProvenanceRecord, ResearchTask, TaskResult


@dataclass(frozen=True)
class StageRoutingResult:
    stage_slug: str
    attempt_no: int
    pattern: str
    summary_text: str
    artifact_paths: list[str]
    subtask_count: int
    results: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {
            "stage_slug": self.stage_slug,
            "attempt_no": self.attempt_no,
            "pattern": self.pattern,
            "summary_text": self.summary_text,
            "artifact_paths": list(self.artifact_paths),
            "subtask_count": self.subtask_count,
            "results": list(self.results),
        }


class ResearchPipelineRouter:
    def __init__(self) -> None:
        self.literature = LiteratureSurveyWorkflow()
        self.debate = HypothesisDebateWorkflow()
        self.playbook = OvernightPlaybookEngine()
        self.runtime = AgentRuntimeManager()
        self.runtime.register(
            CommandResearchAgent(
                name="generic-worker",
                domain="general",
                pipeline_stages=list(_PIPELINE_STAGE_BY_SLUG.values()),
                handler=self._generic_handler,
            )
        )

    def execute(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        user_goal: str,
        kb_context: str,
    ) -> StageRoutingResult:
        if stage.slug == "01_literature_survey":
            return self._execute_literature(paths, stage, attempt_no, user_goal)
        if stage.slug == "02_hypothesis_generation":
            return self._execute_debate(paths, stage, attempt_no, user_goal, kb_context)
        if stage.slug == "05_experimentation":
            return self._execute_playbook(paths, stage, attempt_no, user_goal)
        if stage.slug == "07_writing":
            return self._execute_paper_package(paths, stage, attempt_no)
        if stage.slug == "08_dissemination":
            return self._execute_release_package(paths, stage, attempt_no)
        return self._execute_generic(paths, stage, attempt_no, user_goal)

    def _execute_literature(self, paths: RunPaths, stage: StageSpec, attempt_no: int, user_goal: str) -> StageRoutingResult:
        result = self.literature.run(user_goal, limit_per_source=3, allow_network=False)
        artifact_paths = [
            str(path.relative_to(paths.run_root))
            for path in self.literature.write_artifacts(paths.literature_dir, stage.slug, result)
        ]
        summary = (
            f"Queried literature adapters for '{user_goal[:120]}'. "
            f"Collected {len(result.records)} records with {result.validation_failures} validation failures."
        )
        self._emit(paths.run_root, stage, attempt_no, "router.literature.executed", record_count=len(result.records))
        return StageRoutingResult(
            stage_slug=stage.slug,
            attempt_no=attempt_no,
            pattern=stage.orchestration_pattern,
            summary_text=summary,
            artifact_paths=artifact_paths,
            subtask_count=len(result.records),
            results=[record.to_dict() for record in result.records],
        )

    def _execute_debate(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        user_goal: str,
        kb_context: str,
    ) -> StageRoutingResult:
        result = self.debate.run(user_goal, kb_context=[kb_context], rounds=2)
        artifact_paths = [
            str(path.relative_to(paths.run_root))
            for path in self.debate.write_artifacts(paths.notes_dir, stage.slug, result)
        ]
        summary = (
            f"Ran {result.rounds} swarm debate rounds and produced {len(result.turns)} turns. "
            f"Winning direction: {result.winning_hypothesis}"
        )
        self._emit(paths.run_root, stage, attempt_no, "router.debate.executed", debate_rounds=result.rounds)
        return StageRoutingResult(
            stage_slug=stage.slug,
            attempt_no=attempt_no,
            pattern=stage.orchestration_pattern,
            summary_text=summary,
            artifact_paths=artifact_paths,
            subtask_count=len(result.turns),
            results=[turn.to_dict() for turn in result.turns],
        )

    def _execute_playbook(self, paths: RunPaths, stage: StageSpec, attempt_no: int, user_goal: str) -> StageRoutingResult:
        steps = [
            PlaybookStep(name="prepare-ablation-grid", command="prepare-grid"),
            PlaybookStep(name="run-primary-experiment", command="run-primary"),
            PlaybookStep(name="aggregate-results", command="aggregate"),
        ]
        result = self.playbook.run(paths.run_root, stage.slug, user_goal, steps)
        artifact_path = str((paths.results_dir / f"{stage.slug}_playbook_summary.json").relative_to(paths.run_root))
        summary = (
            f"Executed overnight playbook with {len(result.steps)} steps; "
            f"completed {len(result.completed_steps)} step(s) and recorded {len(result.failures)} failure(s)."
        )
        self._emit(paths.run_root, stage, attempt_no, "router.playbook.executed", playbook_steps=len(result.steps))
        return StageRoutingResult(
            stage_slug=stage.slug,
            attempt_no=attempt_no,
            pattern=stage.orchestration_pattern,
            summary_text=summary,
            artifact_paths=[artifact_path],
            subtask_count=len(result.steps),
            results=[result.to_dict()],
        )

    def _execute_paper_package(self, paths: RunPaths, stage: StageSpec, attempt_no: int) -> StageRoutingResult:
        package = generate_paper_package(paths.run_root)
        artifact_paths = [str(path.relative_to(paths.run_root)) for path in package.artifact_paths]
        self._emit(paths.run_root, stage, attempt_no, "router.paper_package.executed", artifact_count=len(artifact_paths))
        return StageRoutingResult(
            stage_slug=stage.slug,
            attempt_no=attempt_no,
            pattern=stage.orchestration_pattern,
            summary_text=package.summary,
            artifact_paths=artifact_paths,
            subtask_count=len(artifact_paths),
            results=[{"package_name": package.package_name, "summary": package.summary}],
        )

    def _execute_release_package(self, paths: RunPaths, stage: StageSpec, attempt_no: int) -> StageRoutingResult:
        package = generate_release_package(paths.run_root)
        artifact_paths = [str(path.relative_to(paths.run_root)) for path in package.artifact_paths]
        self._emit(paths.run_root, stage, attempt_no, "router.release_package.executed", artifact_count=len(artifact_paths))
        return StageRoutingResult(
            stage_slug=stage.slug,
            attempt_no=attempt_no,
            pattern=stage.orchestration_pattern,
            summary_text=package.summary,
            artifact_paths=artifact_paths,
            subtask_count=len(artifact_paths),
            results=[{"package_name": package.package_name, "summary": package.summary}],
        )

    def _execute_generic(self, paths: RunPaths, stage: StageSpec, attempt_no: int, user_goal: str) -> StageRoutingResult:
        subtasks = self._build_generic_tasks(paths.run_root.name, stage, attempt_no, user_goal)
        runner = lambda task: self.runtime.get("generic-worker").run(task)
        pattern_name = stage.orchestration_pattern.lower()
        if "parallel" in pattern_name and "+" in pattern_name:
            results = SequentialPattern().execute(subtasks, runner)
        elif "parallel" in pattern_name:
            results = ParallelPattern(max_workers=min(len(subtasks), 4)).execute(subtasks, runner)
        elif "hierarchical" in pattern_name:
            results = HierarchicalPattern().execute(subtasks[0], planner=lambda _root: subtasks, runner=runner)
        elif "swarm" in pattern_name:
            results = SwarmPattern(rounds=2).execute(subtasks, runner)
        else:
            results = SequentialPattern().execute(subtasks, runner)

        summary = {
            "stage_slug": stage.slug,
            "attempt_no": attempt_no,
            "pattern": stage.orchestration_pattern,
            "subtask_count": len(subtasks),
            "subtasks": [{"task_id": task.task_id, "title": task.title} for task in subtasks],
            "results": [{"task_id": result.task_id, "output": result.output} for result in results],
        }
        artifact_path = paths.notes_dir / f"{stage.slug}_attempt_{attempt_no:02d}_orchestration.json"
        write_text(artifact_path, json.dumps(summary, indent=2, ensure_ascii=True))
        self._emit(paths.run_root, stage, attempt_no, "router.generic.executed", subtask_count=len(subtasks))
        return StageRoutingResult(
            stage_slug=stage.slug,
            attempt_no=attempt_no,
            pattern=stage.orchestration_pattern,
            summary_text=f"Planned and executed {len(subtasks)} routed subtasks for {stage.stage_title}.",
            artifact_paths=[str(artifact_path.relative_to(paths.run_root))],
            subtask_count=len(subtasks),
            results=summary["results"],
        )

    def _build_generic_tasks(
        self,
        project_id: str,
        stage: StageSpec,
        attempt_no: int,
        user_goal: str,
    ) -> list[ResearchTask]:
        stage_key: PipelineStage = _PIPELINE_STAGE_BY_SLUG[stage.slug]
        templates = {
            "03_study_design": ["Plan protocol", "Define variables", "Set evaluation criteria"],
            "04_implementation": ["Prepare environment", "Implement pipeline", "Validate execution"],
            "06_analysis": ["Compute statistics", "Generate visuals", "Interpret findings"],
            "07_writing": ["Outline manuscript", "Draft sections", "Check consistency"],
            "08_dissemination": ["Draft poster", "Draft slides", "Draft social summary"],
        }
        titles = templates.get(stage.slug, [stage.display_name])
        tasks: list[ResearchTask] = []
        for index, title in enumerate(titles, start=1):
            tasks.append(
                ResearchTask(
                    task_id=f"{stage.slug}-attempt-{attempt_no:02d}-task-{index:02d}",
                    title=title,
                    goal=f"{user_goal}\nSubtask: {title}",
                    pipeline_stage=stage_key,
                    project_id=project_id,
                    kb_context=[stage.slug],
                    human_gate_required=False,
                )
            )
        return tasks

    def _generic_handler(self, task: ResearchTask) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            output=f"Completed routed subtask: {task.title}",
            provenance=[ProvenanceRecord(agent_name="generic-worker", action=f"execute:{task.title}")],
        )

    def _emit(self, run_root: Path, stage: StageSpec, attempt_no: int, span_name: str, **payload: object) -> None:
        collector = ObservabilityCollector(run_root)
        collector.emit_span(
            span_name,
            run_id=run_root.name,
            stage_slug=stage.slug,
            attempt_no=attempt_no,
            **payload,
        )


_PIPELINE_STAGE_BY_SLUG: dict[str, PipelineStage] = {
    "01_literature_survey": "literature_survey",
    "02_hypothesis_generation": "hypothesis_generation",
    "03_study_design": "study_design",
    "04_implementation": "implementation",
    "05_experimentation": "experimentation",
    "06_analysis": "analysis",
    "07_writing": "writing",
    "08_dissemination": "dissemination",
}
