"""Tests for Stage 07 writing-related modules.

Covers:
- validate_stage_artifacts() for stage 07 (venue-agnostic)
- writing_manifest module (still active)
- templates/registry.yaml structure
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from src.utils import RunPaths, StageSpec, build_run_paths, ensure_run_layout, validate_stage_artifacts
from src.writing_manifest import build_writing_manifest, format_manifest_for_prompt, scan_figures


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STAGE_07 = StageSpec(7, "07_writing", "Writing")


@pytest.fixture
def tmp_run(tmp_path: Path) -> RunPaths:
    """Create a minimal run directory structure."""
    run_root = tmp_path / "test_run"
    paths = build_run_paths(run_root)
    ensure_run_layout(paths)
    # Create minimal prior-stage artifacts so Stage 07 validation doesn't fail on those
    (paths.data_dir / "design.json").write_text('{"key": "value"}')
    (paths.results_dir / "metrics.json").write_text('{"accuracy": 0.9}')
    (paths.figures_dir / "accuracy.png").write_bytes(b"\x89PNG fake image data")
    return paths


def _populate_writing_dir(paths: RunPaths) -> None:
    """Fill writing dir with the minimum artifacts that pass Stage 07 validation."""
    sections_dir = paths.writing_dir / "sections"
    sections_dir.mkdir(parents=True, exist_ok=True)

    (paths.writing_dir / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}\n"
    )
    (paths.writing_dir / "references.bib").write_text(
        "@article{test2024,\n  title={Test},\n  author={A},\n  year={2024},\n}\n"
    )
    (sections_dir / "introduction.tex").write_text("\\section{Introduction}\nContent.\n")
    (sections_dir / "method.tex").write_text("\\section{Method}\nContent.\n")

    # Compiled PDF (fake)
    (paths.artifacts_dir / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    (paths.artifacts_dir / "build_log.txt").write_text("=== Build Log ===\nFinal status: SUCCESS\n")
    (paths.artifacts_dir / "citation_verification.json").write_text(
        json.dumps({"overall_status": "pass", "total_citations": 1})
    )
    (paths.artifacts_dir / "self_review.json").write_text(
        json.dumps({"overall_score": 8.0, "final_verdict": "ready", "rounds": 1})
    )


# ---------------------------------------------------------------------------
# Stage 07 artifact validation tests (venue-agnostic)
# ---------------------------------------------------------------------------

class TestStage07Validation:
    def test_complete_setup_passes(self, tmp_run: RunPaths) -> None:
        _populate_writing_dir(tmp_run)
        problems = validate_stage_artifacts(STAGE_07, tmp_run)
        assert problems == []

    def test_rejects_missing_main_tex(self, tmp_run: RunPaths) -> None:
        _populate_writing_dir(tmp_run)
        (tmp_run.writing_dir / "main.tex").unlink()
        problems = validate_stage_artifacts(STAGE_07, tmp_run)
        assert any("main.tex" in p for p in problems)

    def test_rejects_missing_bib(self, tmp_run: RunPaths) -> None:
        _populate_writing_dir(tmp_run)
        (tmp_run.writing_dir / "references.bib").unlink()
        problems = validate_stage_artifacts(STAGE_07, tmp_run)
        assert any(".bib" in p.lower() or "references" in p.lower() for p in problems)

    def test_rejects_missing_sections(self, tmp_run: RunPaths) -> None:
        _populate_writing_dir(tmp_run)
        import shutil
        shutil.rmtree(tmp_run.writing_dir / "sections")
        problems = validate_stage_artifacts(STAGE_07, tmp_run)
        assert any("section" in p.lower() for p in problems)

    def test_rejects_missing_pdf(self, tmp_run: RunPaths) -> None:
        _populate_writing_dir(tmp_run)
        (tmp_run.artifacts_dir / "paper.pdf").unlink()
        problems = validate_stage_artifacts(STAGE_07, tmp_run)
        assert any("pdf" in p.lower() for p in problems)

    def test_rejects_missing_build_log(self, tmp_run: RunPaths) -> None:
        _populate_writing_dir(tmp_run)
        (tmp_run.artifacts_dir / "build_log.txt").unlink()
        problems = validate_stage_artifacts(STAGE_07, tmp_run)
        assert any("build_log" in p for p in problems)

    def test_rejects_missing_citation_verification(self, tmp_run: RunPaths) -> None:
        _populate_writing_dir(tmp_run)
        (tmp_run.artifacts_dir / "citation_verification.json").unlink()
        problems = validate_stage_artifacts(STAGE_07, tmp_run)
        assert any("citation_verification" in p for p in problems)

    def test_rejects_missing_self_review(self, tmp_run: RunPaths) -> None:
        _populate_writing_dir(tmp_run)
        (tmp_run.artifacts_dir / "self_review.json").unlink()
        problems = validate_stage_artifacts(STAGE_07, tmp_run)
        assert any("self_review" in p for p in problems)

    def test_empty_writing_dir_returns_seven_errors(self, tmp_run: RunPaths) -> None:
        problems = validate_stage_artifacts(STAGE_07, tmp_run)
        # main.tex, .bib, sections/, PDF, build_log.txt, citation_verification.json, self_review.json
        assert len(problems) == 7


# ---------------------------------------------------------------------------
# Writing manifest tests
# ---------------------------------------------------------------------------

class TestWritingManifest:
    def test_scan_figures(self, tmp_run: RunPaths) -> None:
        figures = scan_figures(tmp_run.figures_dir)
        assert len(figures) == 1
        assert figures[0]["filename"] == "accuracy.png"

    def test_scan_figures_empty_dir(self, tmp_path: Path) -> None:
        figures = scan_figures(tmp_path / "nonexistent")
        assert figures == []

    def test_build_manifest(self, tmp_run: RunPaths) -> None:
        manifest = build_writing_manifest(tmp_run)

        assert "figures" in manifest
        assert "result_files" in manifest
        assert len(manifest["figures"]) == 1
        assert (tmp_run.writing_dir / "manifest.json").exists()

        # Verify JSON is valid
        raw = (tmp_run.writing_dir / "manifest.json").read_text()
        parsed = json.loads(raw)
        assert parsed["figures"] == manifest["figures"]

    def test_format_for_prompt(self, tmp_run: RunPaths) -> None:
        manifest = build_writing_manifest(tmp_run)
        text = format_manifest_for_prompt(manifest)
        assert "accuracy.png" in text
        assert "metrics.json" in text

    def test_format_empty_manifest(self) -> None:
        text = format_manifest_for_prompt({"figures": [], "result_files": []})
        assert "No experiment artifacts found" in text


# ---------------------------------------------------------------------------
# Template registry tests
# ---------------------------------------------------------------------------

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "templates" / "registry.yaml"

REQUIRED_FIELDS = {"display_name", "official_url", "style_package", "bib_style", "citation_style", "page_limit", "refs_in_limit"}


class TestRegistryYaml:
    @pytest.fixture(autouse=True)
    def _load_registry(self) -> None:
        assert REGISTRY_PATH.exists(), f"registry.yaml not found at {REGISTRY_PATH}"
        yaml = YAML(typ="safe")
        with open(REGISTRY_PATH) as f:
            self.registry = yaml.load(f)

    def test_is_non_empty_dict(self) -> None:
        assert isinstance(self.registry, dict)
        assert len(self.registry) >= 1

    def test_all_entries_have_required_fields(self) -> None:
        for venue_key, config in self.registry.items():
            missing = REQUIRED_FIELDS - set(config.keys())
            assert not missing, f"Venue '{venue_key}' missing fields: {missing}"

    def test_page_limits_are_positive_ints(self) -> None:
        for venue_key, config in self.registry.items():
            assert isinstance(config["page_limit"], int), f"{venue_key}: page_limit must be int"
            assert config["page_limit"] > 0, f"{venue_key}: page_limit must be positive"

    def test_refs_in_limit_is_bool(self) -> None:
        for venue_key, config in self.registry.items():
            assert isinstance(config["refs_in_limit"], bool), f"{venue_key}: refs_in_limit must be bool"

    def test_citation_style_is_valid(self) -> None:
        valid_styles = {"natbib", "cite"}
        for venue_key, config in self.registry.items():
            assert config["citation_style"] in valid_styles, (
                f"{venue_key}: citation_style must be one of {valid_styles}"
            )

    def test_neurips_2025_is_default(self) -> None:
        assert "neurips_2025" in self.registry
        assert self.registry["neurips_2025"]["page_limit"] == 9
