from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.project_bootstrap import (
    CodeState,
    ExperimentState,
    FileEntry,
    ProjectBootstrapResult,
    StageAssessment,
    WritingState,
    format_project_context_for_prompt,
    format_project_scan_for_prompt,
    load_project_bootstrap_summary,
    load_recommended_entry_stage,
    load_stage_assessments,
    project_bootstrap_exists,
    save_project_bootstrap,
    scan_project,
)
from src.utils import build_run_paths, ensure_run_layout


def _make_run(tmp: Path):
    run_root = tmp / "test_run"
    paths = build_run_paths(run_root)
    ensure_run_layout(paths)
    return paths


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


class ScanProjectTests(unittest.TestCase):
    def test_scan_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = scan_project(Path(tmp))
            self.assertEqual(result.total_files, 0)
            self.assertEqual(result.code_state.status, "not_started")

    def test_scan_nonexistent_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            scan_project(Path("/nonexistent"))

    def test_scan_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "file.txt"
            f.write_text("hi")
            with self.assertRaises(NotADirectoryError):
                scan_project(f)

    def test_scan_with_python_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "train.py").write_text("import torch\nprint('train')")
            (root / "model.py").write_text("import torch.nn as nn")
            (root / "utils.py").write_text("def helper(): pass")
            (root / "requirements.txt").write_text("torch>=2.0")
            result = scan_project(root)
            self.assertEqual(result.code_state.status, "complete")
            self.assertIn("Python", result.code_state.languages)
            self.assertIn("pytorch", result.code_state.frameworks)
            self.assertTrue(any("train.py" in ep for ep in result.code_state.entry_points))
            self.assertTrue(any("requirements.txt" in d for d in result.code_state.dependency_files))

    def test_scan_with_experiments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "configs").mkdir()
            (root / "configs" / "exp1.yaml").write_text("lr: 0.01")
            (root / "results").mkdir()
            (root / "results" / "metrics.json").write_text('{"acc": 0.9}')
            (root / "figures").mkdir()
            (root / "figures" / "plot.png").write_bytes(b"PNG")
            result = scan_project(root)
            self.assertIn(result.experiment_state.status, ("partial", "complete"))
            self.assertTrue(len(result.experiment_state.config_files) >= 1)

    def test_scan_with_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paper_dir = root / "paper"
            paper_dir.mkdir()
            (paper_dir / "main.tex").write_text(
                r"\begin{abstract}Our method\end{abstract}"
                r"\section{Introduction}We study..."
                r"\section{Method}Our approach..."
                r"\section{Conclusion}In summary..."
            )
            (paper_dir / "refs.bib").write_text("@article{a, title={A}}")
            result = scan_project(root)
            self.assertIn(result.writing_state.status, ("partial", "complete"))
            self.assertTrue(result.writing_state.has_introduction)
            self.assertTrue(result.writing_state.has_method)
            self.assertTrue(result.writing_state.has_conclusion)

    def test_scan_skips_hidden_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_dir = root / ".git"
            git_dir.mkdir()
            (git_dir / "config").write_text("gitconfig")
            (root / "code.py").write_text("x = 1")
            result = scan_project(root)
            self.assertEqual(result.total_files, 1)

    def test_recommended_entry_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Project with code but no experiments → entry at Stage 05
            (root / "train.py").write_text("import torch")
            (root / "model.py").write_text("class Model: pass")
            (root / "data.py").write_text("def load(): pass")
            (root / "utils.py").write_text("def f(): pass")
            (root / "eval.py").write_text("def evaluate(): pass")
            (root / "requirements.txt").write_text("torch")
            result = scan_project(root)
            # Should recommend a stage after implementation
            self.assertGreaterEqual(result.recommended_entry_stage, 4)


# ---------------------------------------------------------------------------
# Stage assessment
# ---------------------------------------------------------------------------


class StageAssessmentTests(unittest.TestCase):
    def test_all_not_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = scan_project(Path(tmp))
            for a in result.stage_assessments:
                self.assertEqual(a.status, "not_started")
            self.assertEqual(result.recommended_entry_stage, 1)

    def test_complete_code_moves_entry_past_stage4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ["main.py", "model.py", "train.py", "data.py", "utils.py", "eval.py"]:
                (root / name).write_text("# code")
            (root / "requirements.txt").write_text("torch")
            result = scan_project(root)
            s04 = next(a for a in result.stage_assessments if a.stage_number == 4)
            self.assertEqual(s04.status, "complete")
            self.assertGreaterEqual(result.recommended_entry_stage, 5)


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------


class SaveLoadTests(unittest.TestCase):
    def _sample_result(self) -> ProjectBootstrapResult:
        return ProjectBootstrapResult(
            project_root="/tmp/my-project",
            scanned_at="2026-04-04T10:00:00",
            total_files=42,
            code_state=CodeState(
                languages=["Python"], frameworks=["pytorch"],
                entry_points=["train.py"], total_code_files=15,
                status="complete", evidence=["15 code files"],
            ),
            experiment_state=ExperimentState(
                config_files=["configs/exp1.yaml"],
                result_files=["results/metrics.json"],
                status="partial", evidence=["1 config, 1 result"],
            ),
            writing_state=WritingState(
                tex_files=["paper/main.tex"], bib_files=["paper/refs.bib"],
                status="partial", evidence=["1 .tex file"],
            ),
            stage_assessments=[
                StageAssessment(1, "Literature Survey", "partial", "medium", [".bib exists"]),
                StageAssessment(4, "Implementation", "complete", "high", ["15 code files"]),
                StageAssessment(5, "Experimentation", "partial", "medium", ["1 result"]),
            ],
            recommended_entry_stage=5,
            file_tree_sample=["train.py", "model.py"],
        )

    def test_save_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_run(Path(tmp))
            save_project_bootstrap(paths, self._sample_result())

            self.assertTrue((paths.bootstrap_dir / "project_state.json").exists())
            self.assertTrue((paths.bootstrap_dir / "experiment_inventory.json").exists())
            self.assertTrue((paths.bootstrap_dir / "writing_state.json").exists())
            self.assertTrue((paths.bootstrap_dir / "stage_assessments.json").exists())
            self.assertTrue((paths.bootstrap_dir / "scan_metadata.json").exists())
            self.assertTrue((paths.bootstrap_dir / "bootstrap_summary.md").exists())

            summary = load_project_bootstrap_summary(paths)
            self.assertIsNotNone(summary)
            self.assertIn("Stage 05", summary)

            assessments = load_stage_assessments(paths)
            self.assertEqual(len(assessments), 3)

            entry = load_recommended_entry_stage(paths)
            self.assertEqual(entry, 5)

    def test_project_bootstrap_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_run(Path(tmp))
            self.assertFalse(project_bootstrap_exists(paths))
            save_project_bootstrap(paths, self._sample_result())
            self.assertTrue(project_bootstrap_exists(paths))

    def test_load_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_run(Path(tmp))
            self.assertIsNone(load_project_bootstrap_summary(paths))
            self.assertIsNone(load_stage_assessments(paths))
            self.assertIsNone(load_recommended_entry_stage(paths))


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------


class FormatPromptTests(unittest.TestCase):
    def _sample_result(self) -> ProjectBootstrapResult:
        return SaveLoadTests._sample_result(self)

    def test_format_scan_for_prompt(self) -> None:
        result = self._sample_result()
        text = format_project_scan_for_prompt(result)
        self.assertIn("Repository File Tree", text)
        self.assertIn("Code Analysis", text)
        self.assertIn("Experiment Analysis", text)
        self.assertIn("Writing Analysis", text)
        self.assertIn("Stage Assessments", text)

    def test_format_context_for_prompt_none_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_run(Path(tmp))
            self.assertIsNone(format_project_context_for_prompt(paths))

    def test_format_context_for_prompt_with_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_run(Path(tmp))
            save_project_bootstrap(paths, self._sample_result())
            text = format_project_context_for_prompt(paths)
            self.assertIsNotNone(text)
            self.assertIn("Project Bootstrap Summary", text)
            self.assertIn("Stage Assessments", text)


if __name__ == "__main__":
    unittest.main()
