from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.utils import (
    DEFAULT_VENUE,
    STAGES,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    load_run_config,
    selected_venue_key,
    validate_stage_artifacts,
    write_text,
)
from src.writing_manifest import build_writing_manifest, format_manifest_for_prompt, scan_figures


STAGE_07 = next(stage for stage in STAGES if stage.slug == "07_writing")
REPO_ROOT = Path(__file__).resolve().parent.parent


class WritingPipelineTests(unittest.TestCase):
    def _build_paths(self) -> tuple[Path, object]:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        run_root = Path(tmp_dir.name) / "run"
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        write_text(paths.user_input, "Test writing pipeline")
        write_text(paths.memory, "# Approved Run Memory\n\n## Original User Goal\nTest\n\n## Approved Stage Summaries\n\n_None yet._\n")
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE)
        write_text(paths.data_dir / "design.json", '{"task":"test"}')
        write_text(paths.results_dir / "metrics.json", '{"accuracy": 0.9}')
        (paths.figures_dir / "accuracy.png").write_bytes(b"\x89PNG fake image data")
        return run_root, paths

    def _populate_valid_stage07_outputs(self, paths: object) -> None:
        sections_dir = paths.writing_dir / "sections"
        sections_dir.mkdir(parents=True, exist_ok=True)

        write_text(
            paths.writing_dir / "main.tex",
            (
                "% AutoR venue: neurips_2025\n"
                "\\documentclass{article}\n"
                "\\usepackage{neurips_2023}\n"
                "\\begin{document}\n"
                "\\input{sections/introduction}\n"
                "\\end{document}\n"
            ),
        )
        write_text(
            paths.writing_dir / "references.bib",
            (
                "@article{test2024,\n"
                "  title={Test},\n"
                "  author={Author, A.},\n"
                "  year={2024}\n"
                "}\n"
            ),
        )
        write_text(sections_dir / "introduction.tex", "\\section{Introduction}\nContent.\n")
        write_text(sections_dir / "method.tex", "\\section{Method}\nContent.\n")
        (paths.artifacts_dir / "paper.pdf").write_bytes(b"%PDF-1.4 minimal but present")
        write_text(paths.artifacts_dir / "build_log.txt", "=== Build Log ===\nFinal status: SUCCESS\n")
        write_text(
            paths.artifacts_dir / "citation_verification.json",
            json.dumps({"overall_status": "pass", "total_citations": 1}),
        )
        write_text(
            paths.artifacts_dir / "self_review.json",
            json.dumps({"overall_score": 8.0, "final_verdict": "ready", "rounds": 1}),
        )

    def test_stage07_validation_passes_with_expected_outputs(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        self.assertEqual(validate_stage_artifacts(STAGE_07, paths), [])

    def test_stage07_validation_requires_supported_venue_signal(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        write_text(
            paths.writing_dir / "main.tex",
            "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}\n",
        )
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("supported conference or journal manuscript" in problem for problem in problems))

    def test_stage07_validation_accepts_journal_profile_with_inline_bibliography(self) -> None:
        _, paths = self._build_paths()
        ensure_run_config(paths, model="sonnet", venue="nature")
        self._populate_valid_stage07_outputs(paths)
        (paths.writing_dir / "references.bib").unlink()
        write_text(
            paths.writing_dir / "main.tex",
            (
                "% AutoR venue: nature\n"
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "Journal draft.\n"
                "\\begin{thebibliography}{9}\n"
                "\\bibitem{test2024} Author. Test. 2024.\n"
                "\\end{thebibliography}\n"
                "\\end{document}\n"
            ),
        )
        self.assertEqual(validate_stage_artifacts(STAGE_07, paths), [])

    def test_run_config_defaults_to_neurips_when_missing(self) -> None:
        _, paths = self._build_paths()
        paths.run_config.unlink()
        self.assertEqual(selected_venue_key(paths), DEFAULT_VENUE)

    def test_run_config_persists_selected_venue(self) -> None:
        _, paths = self._build_paths()
        ensure_run_config(paths, model="opus", venue="nature")
        config = load_run_config(paths)
        self.assertEqual(config["model"], "opus")
        self.assertEqual(config["venue"], "nature")

    def test_resume_without_explicit_venue_preserves_existing_run_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            run_root = runs_dir / "demo_run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Resume test goal")
            write_text(
                paths.memory,
                "# Approved Run Memory\n\n## Original User Goal\nResume test\n\n## Approved Stage Summaries\n\n_None yet._\n",
            )
            ensure_run_config(paths, model="opus", venue="nature")

            result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--fake-operator",
                    "--resume-run",
                    "demo_run",
                    "--runs-dir",
                    str(runs_dir),
                ],
                cwd=REPO_ROOT,
                input="6\n",
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            config = load_run_config(paths)
            self.assertEqual(config["model"], "opus")
            self.assertEqual(config["venue"], "nature")

    def test_resume_old_run_without_run_config_falls_back_to_sonnet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            run_root = runs_dir / "legacy_run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Legacy resume goal")
            write_text(
                paths.memory,
                "# Approved Run Memory\n\n## Original User Goal\nLegacy test\n\n## Approved Stage Summaries\n\n_None yet._\n",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--fake-operator",
                    "--resume-run",
                    "legacy_run",
                    "--runs-dir",
                    str(runs_dir),
                ],
                cwd=REPO_ROOT,
                input="6\n",
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            config = load_run_config(paths)
            self.assertEqual(config["model"], "sonnet")
            self.assertEqual(config["venue"], DEFAULT_VENUE)

    def test_stage07_validation_does_not_accept_generic_journal_word_for_nature(self) -> None:
        _, paths = self._build_paths()
        ensure_run_config(paths, model="sonnet", venue="nature")
        self._populate_valid_stage07_outputs(paths)
        write_text(
            paths.writing_dir / "main.tex",
            (
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "This is a journal-style draft.\n"
                "\\end{document}\n"
            ),
        )
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("Expected venue: nature" in problem for problem in problems))

    def test_stage07_missing_build_log_with_pdf_is_warning(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        (paths.artifacts_dir / "build_log.txt").unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        build_log_issues = [p for p in problems if "build_log.txt" in p]
        self.assertTrue(len(build_log_issues) > 0)
        self.assertTrue(all(p.startswith("[warning]") for p in build_log_issues))

    def test_stage07_missing_build_log_without_pdf_is_error(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        (paths.artifacts_dir / "build_log.txt").unlink()
        (paths.artifacts_dir / "paper.pdf").unlink()
        # Also remove any PDF in writing dir
        for f in paths.writing_dir.glob("*.pdf"):
            f.unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        pdf_errors = [p for p in problems if "PDF" in p and not p.startswith("[warning]")]
        self.assertTrue(len(pdf_errors) > 0)

    def test_stage07_missing_self_review_is_warning(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        (paths.artifacts_dir / "self_review.json").unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        sr_issues = [p for p in problems if "self_review.json" in p]
        self.assertTrue(len(sr_issues) > 0)
        self.assertTrue(all(p.startswith("[warning]") for p in sr_issues))

    def test_stage07_single_file_main_tex_without_sections_passes(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        # Remove sections/ directory entirely
        import shutil
        sections_dir = paths.writing_dir / "sections"
        if sections_dir.exists():
            shutil.rmtree(sections_dir)
        problems = validate_stage_artifacts(STAGE_07, paths)
        errors = [p for p in problems if not p.startswith("[warning]")]
        self.assertEqual(errors, [], f"Unexpected errors: {errors}")

    def test_stage07_empty_sections_dir_is_warning(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        # Remove all .tex files from sections/ but keep directory
        sections_dir = paths.writing_dir / "sections"
        for f in sections_dir.glob("*.tex"):
            f.unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        section_issues = [p for p in problems if "sections/" in p]
        self.assertTrue(len(section_issues) > 0)
        self.assertTrue(all(p.startswith("[warning]") for p in section_issues))

    def test_scan_figures_returns_expected_metadata(self) -> None:
        _, paths = self._build_paths()
        figures = scan_figures(paths.figures_dir)
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0]["filename"], "accuracy.png")

    def test_build_writing_manifest_creates_manifest_json(self) -> None:
        _, paths = self._build_paths()
        manifest = build_writing_manifest(paths)
        self.assertIn("figures", manifest)
        self.assertIn("result_files", manifest)
        self.assertTrue((paths.writing_dir / "manifest.json").exists())

    def test_format_manifest_for_prompt_mentions_figures_and_results(self) -> None:
        _, paths = self._build_paths()
        manifest = build_writing_manifest(paths)
        formatted = format_manifest_for_prompt(manifest)
        self.assertIn("accuracy.png", formatted)
        self.assertIn("metrics.json", formatted)

    def test_registry_yaml_exists_and_mentions_conference_and_journal_profiles(self) -> None:
        registry_path = Path("templates/registry.yaml")
        self.assertTrue(registry_path.exists())
        text = registry_path.read_text(encoding="utf-8")
        self.assertIn("neurips_2025:", text)
        self.assertIn("nature:", text)
        self.assertIn('venue_type: "journal"', text)


if __name__ == "__main__":
    unittest.main()
