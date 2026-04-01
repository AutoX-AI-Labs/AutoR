from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.utils import (
    DEFAULT_VENUE,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    validate_dissemination_readiness,
    write_text,
)


class TestDisseminationReadiness(unittest.TestCase):
    def _build_paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        run_root = Path(tmp_dir.name) / "run"
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        write_text(paths.user_input, "Test goal")
        write_text(paths.memory, "# Approved Run Memory\n\n## Approved Stage Summaries\n\n_None yet._\n")
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE)
        return paths

    def test_no_pdf_returns_warning(self) -> None:
        paths = self._build_paths()
        warnings = validate_dissemination_readiness(paths)
        self.assertTrue(any("PDF" in w for w in warnings))

    def test_no_main_tex_returns_warning(self) -> None:
        paths = self._build_paths()
        warnings = validate_dissemination_readiness(paths)
        self.assertTrue(any("main.tex" in w for w in warnings))

    def test_no_review_files_returns_warning(self) -> None:
        paths = self._build_paths()
        warnings = validate_dissemination_readiness(paths)
        self.assertTrue(any("review" in w.lower() for w in warnings))

    def test_missing_readiness_report_returns_warning(self) -> None:
        paths = self._build_paths()
        warnings = validate_dissemination_readiness(paths)
        self.assertTrue(any("readiness_report.json" in w for w in warnings))

    def test_readiness_report_blocking_gaps_surfaced(self) -> None:
        paths = self._build_paths()
        # Create all required files
        write_text(paths.writing_dir / "main.tex", "\\documentclass{article}")
        (paths.artifacts_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
        write_text(paths.reviews_dir / "checklist.md", "# Checklist\n- Done")
        write_text(
            paths.reviews_dir / "readiness_report.json",
            json.dumps({
                "ready": False,
                "blocking_gaps": ["Missing GloGNN baseline", "No Pei 2020 splits"],
                "warnings": [],
                "assets": [],
            }),
        )
        warnings = validate_dissemination_readiness(paths)
        self.assertTrue(any("GloGNN" in w for w in warnings))
        self.assertTrue(any("Pei 2020" in w for w in warnings))

    def test_all_present_ready_true_returns_no_blocking(self) -> None:
        paths = self._build_paths()
        write_text(paths.writing_dir / "main.tex", "\\documentclass{article}")
        (paths.artifacts_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
        write_text(paths.reviews_dir / "checklist.md", "# Checklist\n- Done")
        write_text(
            paths.reviews_dir / "readiness_report.json",
            json.dumps({
                "ready": True,
                "blocking_gaps": [],
                "warnings": [],
                "assets": [],
            }),
        )
        warnings = validate_dissemination_readiness(paths)
        self.assertEqual(warnings, [])

    def test_malformed_json_returns_warning(self) -> None:
        paths = self._build_paths()
        write_text(paths.writing_dir / "main.tex", "\\documentclass{article}")
        (paths.artifacts_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
        write_text(paths.reviews_dir / "checklist.md", "# Checklist")
        write_text(paths.reviews_dir / "readiness_report.json", "not valid json{{{")
        warnings = validate_dissemination_readiness(paths)
        self.assertTrue(any("could not be parsed" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
