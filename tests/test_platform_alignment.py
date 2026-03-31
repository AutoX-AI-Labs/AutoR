from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.manager import ResearchManager
from src.operator import ClaudeOperator
from src.platform.debate import HypothesisDebateWorkflow
from src.platform.foundry import (
    FoundryOutputFormat,
    generate_foundry_output,
    generate_paper_package,
    generate_release_package,
)
from src.platform.literature import LiteratureSurveyWorkflow
from src.platform.orchestration import HierarchicalPattern, ParallelPattern, SequentialPattern, SwarmPattern
from src.platform.playbook import OvernightPlaybookEngine, PlaybookStep
from src.platform.router import ResearchPipelineRouter
from src.platform.security import ROLE_SCOPES, authorize_scope
from src.platform.semantic import SemanticIndexer
from src.platform.types import ResearchTask, TaskResult
from src.utils import STAGES


class PlatformAlignmentTests(unittest.TestCase):
    def test_semantic_indexer_ranks_relevant_document_first(self) -> None:
        matches = SemanticIndexer().rank(
            "protein folding literature evidence",
            [
                "agent orchestration and task routing",
                "protein folding literature survey and evidence extraction",
                "deployment and docker compose instructions",
            ],
            limit=3,
        )

        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0].index, 1)

    def test_literature_workflow_generates_records_and_artifacts(self) -> None:
        workflow = LiteratureSurveyWorkflow()
        result = workflow.run("protein folding benchmark reliability", limit_per_source=2, allow_network=False)
        self.assertGreaterEqual(len(result.records), 2)

        with tempfile.TemporaryDirectory() as tmp_dir:
            artifacts = workflow.write_artifacts(Path(tmp_dir), "01_literature_survey", result)
            self.assertEqual(len(artifacts), 2)
            self.assertTrue(all(path.exists() for path in artifacts))

    def test_hypothesis_debate_workflow_produces_turns(self) -> None:
        workflow = HypothesisDebateWorkflow()
        result = workflow.run("improve hypothesis quality", kb_context=["literature note"], rounds=2)
        self.assertEqual(result.rounds, 2)
        self.assertGreaterEqual(len(result.turns), 3)
        self.assertIn("Moderator synthesis", result.winning_hypothesis)

    def test_playbook_engine_writes_summary(self) -> None:
        engine = OvernightPlaybookEngine()
        steps = [
            PlaybookStep(name="prepare", command="prepare"),
            PlaybookStep(name="run", command="run"),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir)
            summary = engine.run(run_root, "05_experimentation", "goal", steps)
            self.assertEqual(len(summary.completed_steps), 2)
            self.assertTrue((run_root / "results" / "05_experimentation_playbook_summary.json").exists())

    def test_orchestration_patterns_execute_tasks(self) -> None:
        tasks = [
            ResearchTask(task_id="1", title="A", goal="a", pipeline_stage="analysis", project_id="run"),
            ResearchTask(task_id="2", title="B", goal="b", pipeline_stage="analysis", project_id="run"),
        ]

        def runner(task: ResearchTask) -> TaskResult:
            return TaskResult(task_id=task.task_id, output=f"done:{task.title}")

        sequential_results = SequentialPattern().execute(tasks, runner)
        parallel_results = ParallelPattern(max_workers=2).execute(tasks, runner)
        swarm_results = SwarmPattern(rounds=2).execute(tasks, runner)
        hierarchical_results = HierarchicalPattern().execute(
            tasks[0],
            planner=lambda root: tasks,
            runner=runner,
        )

        self.assertEqual([item.output for item in sequential_results], ["done:A", "done:B"])
        self.assertEqual(sorted(item.output for item in parallel_results), ["done:A", "done:B"])
        self.assertEqual(len(swarm_results), 2)
        self.assertEqual(len(hierarchical_results), 2)

    def test_router_executes_stage_specific_workflows(self) -> None:
        router = ResearchPipelineRouter()

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(__file__).resolve().parents[1]
            runs_dir = Path(tmp_dir) / "runs"
            manager = ResearchManager(
                project_root=repo_root,
                runs_dir=runs_dir,
                operator=ClaudeOperator(fake_mode=True, output_stream=io.StringIO()),
                output_stream=io.StringIO(),
            )
            paths = manager.create_run_paths("Study reliable literature and experiments.")

            literature_result = router.execute(paths, STAGES[0], 1, "Study reliable literature and experiments.", "kb")
            debate_result = router.execute(paths, STAGES[1], 1, "Study reliable literature and experiments.", "kb")
            playbook_result = router.execute(paths, STAGES[4], 1, "Study reliable literature and experiments.", "kb")
            paper_result = router.execute(paths, STAGES[6], 1, "Study reliable literature and experiments.", "kb")
            release_result = router.execute(paths, STAGES[7], 1, "Study reliable literature and experiments.", "kb")

            self.assertIn("citations", " ".join(literature_result.artifact_paths))
            self.assertIn("debate", " ".join(debate_result.artifact_paths))
            self.assertIn("playbook", " ".join(playbook_result.artifact_paths))
            self.assertIn("paper_package", " ".join(paper_result.artifact_paths))
            self.assertIn("release_package", " ".join(release_result.artifact_paths))

    def test_foundry_generation_writes_output(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]

        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            manager = ResearchManager(
                project_root=repo_root,
                runs_dir=runs_dir,
                operator=ClaudeOperator(fake_mode=True, output_stream=io.StringIO()),
                output_stream=io.StringIO(),
            )

            with patch("builtins.input", side_effect=["5"] * len(STAGES)):
                self.assertTrue(manager.run("Generate a foundry-ready package."))

            run_root = next(path for path in runs_dir.iterdir() if path.is_dir())
            output = generate_foundry_output(run_root, FoundryOutputFormat.PAPER)
            self.assertEqual(output.output_format, FoundryOutputFormat.PAPER)
            self.assertIn("paper.md", str(output.output_path))
            self.assertIn("Foundry Output: Paper", output.summary)

            paper_package = generate_paper_package(run_root)
            release_package = generate_release_package(run_root)
            self.assertTrue(any(path.name == "manuscript.tex" for path in paper_package.artifact_paths))
            self.assertTrue(any(path.name == "paper.pdf" for path in paper_package.artifact_paths))
            self.assertTrue(any(path.name == "readiness_checklist.md" for path in release_package.artifact_paths))
            self.assertTrue(any(path.name == "artifact_bundle_manifest.json" for path in release_package.artifact_paths))

    def test_security_role_map_and_authorization(self) -> None:
        self.assertIn("researcher", ROLE_SCOPES)
        authorize_scope("researcher", "task.read")
        with self.assertRaises(PermissionError):
            authorize_scope("unknown-role", "task.read")


if __name__ == "__main__":
    unittest.main()
