from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.manifest import load_run_manifest
from src.utils import build_run_paths, ensure_run_layout, initialize_memory, write_text


REPO_ROOT = Path(__file__).resolve().parent.parent


class CliSmokeTests(unittest.TestCase):
    def test_cli_new_run_abort_creates_cancelled_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"

            result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--fake-operator",
                    "--goal",
                    "CLI smoke abort goal",
                    "--runs-dir",
                    str(runs_dir),
                ],
                cwd=REPO_ROOT,
                input="6\n",
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            run_roots = sorted(path for path in runs_dir.iterdir() if path.is_dir())
            self.assertEqual(len(run_roots), 1)
            manifest = load_run_manifest(run_roots[0] / "run_manifest.json")
            self.assertIsNotNone(manifest)
            assert manifest is not None
            self.assertEqual(manifest.run_status, "cancelled")
            self.assertEqual(manifest.current_stage_slug, "01_literature_survey")

    def test_cli_rejects_redo_and_rollback_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            run_root = runs_dir / "demo_run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "CLI conflict goal")
            initialize_memory(paths, "CLI conflict goal")

            result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--fake-operator",
                    "--resume-run",
                    "demo_run",
                    "--redo-stage",
                    "6",
                    "--rollback-stage",
                    "5",
                    "--runs-dir",
                    str(runs_dir),
                ],
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("mutually exclusive", result.stderr)

    def test_cli_resume_latest_targets_newest_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            older = runs_dir / "20260331_010101"
            newer = runs_dir / "20260331_020202"
            for run_root, goal in ((older, "older goal"), (newer, "newer goal")):
                paths = build_run_paths(run_root)
                ensure_run_layout(paths)
                write_text(paths.user_input, goal)
                initialize_memory(paths, goal)

            result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--fake-operator",
                    "--resume-run",
                    "latest",
                    "--redo-stage",
                    "1",
                    "--runs-dir",
                    str(runs_dir),
                ],
                cwd=REPO_ROOT,
                input="6\n",
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertFalse((older / "run_manifest.json").exists())
            manifest = load_run_manifest(newer / "run_manifest.json")
            self.assertIsNotNone(manifest)
            assert manifest is not None
            self.assertEqual(manifest.run_status, "cancelled")
            self.assertEqual(manifest.current_stage_slug, "01_literature_survey")


if __name__ == "__main__":
    unittest.main()
