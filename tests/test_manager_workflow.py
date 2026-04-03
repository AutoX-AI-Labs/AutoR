from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.manager import ResearchManager
from src.operator import ClaudeOperator
from src.utils import (
    STAGES,
    append_approved_stage_summary,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    initialize_memory,
    read_text,
    write_text,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _stage_markdown(stage_number: int, stage_name: str, marker: str) -> str:
    return (
        f"# Stage {stage_number:02d}: {stage_name}\n\n"
        "## Objective\n"
        f"{marker} objective\n\n"
        "## Previously Approved Stage Summaries\n"
        "None yet.\n\n"
        "## What I Did\n"
        f"{marker} work\n\n"
        "## Key Results\n"
        f"{marker} result\n\n"
        "## Files Produced\n"
        f"- `workspace/notes/{marker}.md`\n\n"
        "## Suggestions for Refinement\n"
        "1. Refine one\n"
        "2. Refine two\n"
        "3. Refine three\n\n"
        "## Your Options\n"
        "1. Use suggestion 1\n"
        "2. Use suggestion 2\n"
        "3. Use suggestion 3\n"
        "4. Refine with your own feedback\n"
        "5. Approve and continue\n"
        "6. Abort\n"
    )


class ManagerWorkflowTests(unittest.TestCase):
    def test_abort_does_not_promote_draft_stage_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--fake-operator",
                    "--goal",
                    "approval timing test",
                    "--runs-dir",
                    str(runs_dir),
                ],
                cwd=REPO_ROOT,
                input="6\n",
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            run_root = sorted(path for path in runs_dir.iterdir() if path.is_dir())[-1]
            self.assertTrue((run_root / "stages" / "01_literature_survey.tmp.md").exists())
            self.assertFalse((run_root / "stages" / "01_literature_survey.md").exists())

    def test_redo_stage_prompt_excludes_future_approved_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            run_root = runs_dir / "demo"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "redo stage test")
            initialize_memory(paths, "redo stage test")
            ensure_run_config(paths, model="sonnet", venue="neurips_2025")

            for stage, marker in zip(STAGES[:4], ("one", "two", "three-old", "four-old")):
                append_approved_stage_summary(paths.memory, stage, _stage_markdown(stage.number, stage.display_name, marker))

            manager = ResearchManager(
                project_root=REPO_ROOT,
                runs_dir=runs_dir,
                operator=ClaudeOperator(fake_mode=True),
            )
            manager._redo_start_stage = STAGES[2]
            prompt = manager._build_stage_prompt(paths, STAGES[2], revision_feedback=None, continue_session=False)

            self.assertIn("two result", prompt)
            self.assertNotIn("three-old result", prompt)
            self.assertNotIn("four-old result", prompt)

    def test_reapproving_stage_replaces_current_entry_and_drops_future_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "memory rewrite test")
            initialize_memory(paths, "memory rewrite test")

            for stage, marker in zip(STAGES[:4], ("one", "two", "three-old", "four-old")):
                append_approved_stage_summary(paths.memory, stage, _stage_markdown(stage.number, stage.display_name, marker))

            append_approved_stage_summary(
                paths.memory,
                STAGES[2],
                _stage_markdown(STAGES[2].number, STAGES[2].display_name, "three-new"),
            )
            memory_text = read_text(paths.memory)

            self.assertIn("one result", memory_text)
            self.assertIn("two result", memory_text)
            self.assertIn("three-new result", memory_text)
            self.assertNotIn("three-old result", memory_text)
            self.assertNotIn("four-old result", memory_text)

    def test_select_stages_requires_actual_approved_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            run_root = runs_dir / "demo"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Mention Stage 01: Literature Survey in the goal only.")
            initialize_memory(paths, "Mention Stage 01: Literature Survey in the goal only.")
            ensure_run_config(paths, model="sonnet", venue="neurips_2025")
            write_text(paths.stage_file(STAGES[0]), "stale final file")

            manager = ResearchManager(
                project_root=REPO_ROOT,
                runs_dir=runs_dir,
                operator=ClaudeOperator(fake_mode=True),
            )
            pending = manager._select_stages_for_run(paths, None)

            self.assertEqual(pending[0].slug, "01_literature_survey")


if __name__ == "__main__":
    unittest.main()
