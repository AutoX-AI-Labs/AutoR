from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.knowledge_base import initialize_knowledge_base, load_kb_entries, search_knowledge_base, write_kb_entry
from src.manager import ResearchManager
from src.manifest import load_run_manifest, rollback_to_stage
from src.operator import ClaudeOperator
from src.run_state import RUN_STATUS_COMPLETED, derive_run_state
from src.utils import approved_stage_summaries
from src.utils import STAGES, build_prompt, build_run_paths, ensure_run_layout


class ClawDockAlignmentTests(unittest.TestCase):
    def test_build_prompt_includes_pattern_and_kb_context(self) -> None:
        stage = STAGES[0]
        prompt = build_prompt(
            stage=stage,
            stage_template="Stage template body",
            user_request="Survey recent work on retrieval.",
            approved_memory="Approved memory body",
            kb_context="1. [user_goal] Original user goal",
            orchestration_context="Pattern: Parallel\nSubtasks: 3",
            handoff_context="Previous stage handoff summary",
            manifest_context="Current Stage: 01_literature_survey",
            revision_feedback=None,
        )

        self.assertIn("# Research Pipeline Mapping", prompt)
        self.assertIn(stage.orchestration_pattern, prompt)
        self.assertIn("# Knowledge Base Context", prompt)
        self.assertIn("# Routed Orchestration Context", prompt)
        self.assertIn("# Stage Handoff Context", prompt)
        self.assertIn("Pattern: Parallel", prompt)
        self.assertIn("Original user goal", prompt)

    def test_kb_search_prioritizes_matching_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            initialize_knowledge_base(paths, "Research goal")

            write_kb_entry(
                paths,
                entry_type="stage_approved",
                title="Literature survey approved",
                summary="Protein folding literature synthesis",
                content="Discussed literature evidence for protein folding.",
                stage=STAGES[0],
                tags=["literature"],
            )
            write_kb_entry(
                paths,
                entry_type="stage_approved",
                title="Hypothesis approved",
                summary="Hypothesis for protein folding experiments",
                content="Outlined a protein folding hypothesis.",
                stage=STAGES[1],
                tags=["hypothesis"],
            )

            results = search_knowledge_base(
                paths.knowledge_base_entries,
                query="protein folding literature",
                limit=3,
                stage=STAGES[0],
            )

            self.assertGreaterEqual(len(results), 1)
            self.assertEqual(results[0].entry.stage_slug, STAGES[0].slug)

    def test_fake_run_completes_with_state_and_kb(self) -> None:
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
                completed = manager.run("Build a reproducible research workflow.")

            self.assertTrue(completed)

            run_roots = sorted(path for path in runs_dir.iterdir() if path.is_dir())
            self.assertEqual(len(run_roots), 1)
            paths = build_run_paths(run_roots[0])

            manifest = load_run_manifest(paths.run_manifest)
            self.assertIsNotNone(manifest)
            assert manifest is not None
            state = derive_run_state(manifest)
            self.assertEqual(state.status, RUN_STATUS_COMPLETED)
            self.assertEqual(len(state.approved_stages), len(STAGES))

            entries = load_kb_entries(paths.knowledge_base_entries)
            entry_types = [entry.entry_type for entry in entries]
            self.assertIn("run_completed", entry_types)
            self.assertEqual(entry_types.count("stage_approved"), len(STAGES))

            self.assertEqual(len([entry for entry in manifest.stages if entry.approved]), len(STAGES))
            self.assertEqual(manifest.run_status, "completed")
            self.assertTrue(paths.handoff_dir.exists())
            self.assertTrue(any(path.name == "08_dissemination.md" for path in paths.handoff_dir.iterdir()))

            self.assertEqual(state.status, manifest.run_status.upper())
            self.assertEqual(state.current_stage_slug, manifest.current_stage_slug)

    def test_rollback_marks_downstream_stale_and_rebuilds_memory(self) -> None:
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
                self.assertTrue(manager.run("Rollback validation workflow."))

            run_root = next(path for path in runs_dir.iterdir() if path.is_dir())
            paths = build_run_paths(run_root)
            rollback_to_stage(paths, STAGES[2], reason="Redo study design")
            manifest = load_run_manifest(paths.run_manifest)
            assert manifest is not None

            by_slug = {entry.slug: entry for entry in manifest.stages}
            self.assertEqual(by_slug["03_study_design"].status, "pending")
            self.assertTrue(by_slug["03_study_design"].dirty)
            self.assertEqual(by_slug["04_implementation"].status, "stale")
            self.assertTrue(by_slug["04_implementation"].stale)
            self.assertEqual(by_slug["08_dissemination"].status, "stale")

            approved_memory = approved_stage_summaries(paths.memory.read_text(encoding="utf-8"))
            self.assertIn("Stage 01: Literature Survey", approved_memory)
            self.assertIn("Stage 02: Hypothesis Generation", approved_memory)
            self.assertNotIn("Stage 03: Study Design", approved_memory)

            status_text = manager.describe_run_status(run_root)
            self.assertIn("Current Stage: 03_study_design", status_text)
            self.assertIn("04_implementation: status=stale", status_text)


if __name__ == "__main__":
    unittest.main()
