from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.manifest import (
    initialize_run_manifest,
    load_run_manifest,
    mark_stage_approved_manifest,
    mark_stage_human_review_manifest,
    mark_stage_running_manifest,
    update_manifest_run_status,
)
from src.utils import STAGES, build_run_paths, ensure_run_config, ensure_run_layout, initialize_memory, write_text


class RunManifestTests(unittest.TestCase):
    def test_manifest_initialization_and_stage_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            run_root = runs_dir / "run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Manifest smoke test")
            initialize_memory(paths, "Manifest smoke test")
            ensure_run_config(paths, model="sonnet", venue="neurips_2025")

            manifest = initialize_run_manifest(paths)
            self.assertEqual(manifest.run_status, "pending")
            self.assertEqual(len(manifest.stages), len(STAGES))
            self.assertTrue(all(entry.status == "pending" for entry in manifest.stages))

            running = mark_stage_running_manifest(paths, STAGES[0], attempt_no=1)
            self.assertEqual(running.run_status, "running")

            human_review = mark_stage_human_review_manifest(
                paths,
                STAGES[0],
                attempt_no=1,
                artifact_paths=["stages/01_literature_survey.md"],
            )
            self.assertEqual(human_review.run_status, "human_review")

            approved = mark_stage_approved_manifest(
                paths,
                STAGES[0],
                attempt_no=1,
                artifact_paths=["stages/01_literature_survey.md"],
            )
            self.assertEqual(approved.run_status, "pending")
            self.assertTrue(next(entry for entry in approved.stages if entry.slug == STAGES[0].slug).approved)

            completed = update_manifest_run_status(
                paths,
                run_status="completed",
                last_event="run.completed",
                current_stage_slug=None,
                completed_at="2026-03-31T00:00:00",
            )
            self.assertEqual(completed.run_status, "completed")

            loaded = load_run_manifest(paths.run_manifest)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.run_status, "completed")
            self.assertEqual(loaded.completed_at, "2026-03-31T00:00:00")


if __name__ == "__main__":
    unittest.main()
