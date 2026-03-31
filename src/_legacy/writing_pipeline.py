"""Stage 07 deterministic post-processing pipeline.

After the agent finishes generating LaTeX fragments, this module runs
the deterministic build → verify → package sequence. It is NOT a replacement
for the agent writing step — it is the engineering layer that turns agent
output into a compiled, verified paper package.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src._legacy.citation_verifier import VerificationReport, verify_citations, write_verification_json
from src._legacy.latex_build import BuildResult, compile_latex, run_chktex
from src._legacy.submission_packager import package_submission
from src.utils import RunPaths, append_log_entry
from src.writing_manifest import build_writing_manifest


TEMPLATE_DIR_NAME = "neurips_2025"

# Files from the template that should be copied into writing_dir.
_TEMPLATE_COPY_FILES = ["neurips_2025.sty", "main_template.tex"]

# Section files expected after agent writing.
EXPECTED_SECTIONS = [
    "abstract", "introduction", "related_work",
    "method", "experiments", "results", "conclusion",
]


@dataclass
class WritingPipelineResult:
    manifest: dict
    build_result: BuildResult
    verification: VerificationReport
    bundle_path: Path | None
    build_log_path: Path
    errors: list[str]


def run_writing_pipeline(paths: RunPaths) -> WritingPipelineResult:
    """Execute the full deterministic post-processing pipeline for Stage 07.

    Steps:
    1. Build writing manifest from workspace artifacts
    2. Set up NeurIPS template (copy .sty, generate main.tex if needed)
    3. Ensure sections/ directory has at least stub files
    4. Compile LaTeX → PDF
    5. Run chktex lint
    6. Verify citations and figure references
    7. Package submission bundle
    8. Write build artifacts (build_log.txt, build_manifest.json, citation_verification.json)
    """
    errors: list[str] = []

    # Step 1: Build manifest
    try:
        manifest = build_writing_manifest(paths)
    except Exception as exc:
        manifest = {}
        errors.append(f"Manifest generation failed: {exc}")

    # Step 2: Set up template
    try:
        setup_template(paths.writing_dir)
    except Exception as exc:
        errors.append(f"Template setup failed: {exc}")

    # Step 3: Ensure section stubs exist so pdflatex doesn't fail on missing \\input
    _ensure_section_stubs(paths.writing_dir)

    # Step 4: Ensure references.bib exists
    bib_path = paths.writing_dir / "references.bib"
    if not bib_path.exists():
        bib_path.write_text("% Auto-generated empty bibliography\n", encoding="utf-8")

    # Step 5: Compile LaTeX
    build_result = compile_latex(paths.writing_dir, main_tex="main.tex")

    # Step 6: Run chktex
    chktex_output = run_chktex(paths.writing_dir, main_tex="main.tex")
    build_result.chktex_output = chktex_output

    # Step 7: Verify citations and figures
    verification = verify_citations(
        writing_dir=paths.writing_dir,
        figures_dir=paths.figures_dir,
        main_tex="main.tex",
    )

    # Step 8: Write build artifacts
    paths.artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Build log
    build_log_path = paths.artifacts_dir / "build_log.txt"
    log_content = _format_build_log(build_result, chktex_output, verification)
    build_log_path.write_text(log_content, encoding="utf-8")

    # Citation verification JSON
    verification_json_path = paths.artifacts_dir / "citation_verification.json"
    write_verification_json(verification, verification_json_path)

    # Copy PDF to artifacts/
    if build_result.success and build_result.pdf_path:
        artifact_pdf = paths.artifacts_dir / "paper.pdf"
        shutil.copy2(build_result.pdf_path, artifact_pdf)

    # Step 9: Package submission bundle (best effort)
    bundle_path = package_submission(
        writing_dir=paths.writing_dir,
        figures_dir=paths.figures_dir,
        output_dir=paths.artifacts_dir,
        pdf_path=build_result.pdf_path,
    )

    # Step 10: Write build manifest
    _write_build_manifest(paths, build_result, verification, bundle_path)

    if not build_result.success:
        errors.append("LaTeX compilation did not produce a PDF.")

    return WritingPipelineResult(
        manifest=manifest,
        build_result=build_result,
        verification=verification,
        bundle_path=bundle_path,
        build_log_path=build_log_path,
        errors=errors,
    )


def setup_template(writing_dir: Path) -> None:
    """Copy NeurIPS template files into writing_dir and create main.tex if missing.

    Also creates empty stub .tex files for any expected sections that don't
    exist yet, so pdflatex won't fail on missing \\input{} files.
    """
    template_source = _find_template_dir()

    writing_dir.mkdir(parents=True, exist_ok=True)
    (writing_dir / "sections").mkdir(exist_ok=True)

    # Copy .sty
    sty_source = template_source / "neurips_2025.sty"
    sty_dest = writing_dir / "neurips_2025.sty"
    if sty_source.exists() and not sty_dest.exists():
        shutil.copy2(sty_source, sty_dest)

    # Create main.tex from template if it doesn't exist
    main_dest = writing_dir / "main.tex"
    if not main_dest.exists():
        template_tex = template_source / "main_template.tex"
        if template_tex.exists():
            shutil.copy2(template_tex, main_dest)

    # Create section stubs for any missing sections
    _ensure_section_stubs(writing_dir)


def _find_template_dir() -> Path:
    """Locate the template directory relative to this source file."""
    # templates/ is a sibling of src/ in the repo root
    src_dir = Path(__file__).resolve().parent
    repo_root = src_dir.parent
    template_dir = repo_root / "templates" / TEMPLATE_DIR_NAME
    if not template_dir.exists():
        raise FileNotFoundError(f"Template directory not found: {template_dir}")
    return template_dir


def _ensure_section_stubs(writing_dir: Path) -> None:
    """Create empty stub .tex files for any expected sections that don't exist.

    This prevents pdflatex from failing on missing \\input{} files.
    """
    sections_dir = writing_dir / "sections"
    sections_dir.mkdir(exist_ok=True)
    for section_name in EXPECTED_SECTIONS:
        section_file = sections_dir / f"{section_name}.tex"
        if not section_file.exists():
            section_file.write_text(
                f"% TODO: {section_name} content\n",
                encoding="utf-8",
            )


def _format_build_log(
    build_result: BuildResult,
    chktex_output: str,
    verification: VerificationReport,
) -> str:
    """Format a human-readable build log."""
    parts: list[str] = [
        f"Build Log — {datetime.now().isoformat(timespec='seconds')}",
        f"PDF generated: {build_result.success}",
        f"PDF path: {build_result.pdf_path or '(none)'}",
        "",
    ]

    if build_result.errors:
        parts.append("=== LaTeX Errors ===")
        for err in build_result.errors:
            line_info = f" (line {err.line_number})" if err.line_number else ""
            parts.append(f"  ! {err.message}{line_info}")
            if err.context_lines:
                parts.append(err.context_lines)
        parts.append("")

    if build_result.warnings:
        parts.append("=== Warnings ===")
        for warn in build_result.warnings:
            parts.append(f"  {warn}")
        parts.append("")

    if chktex_output:
        parts.append("=== chktex Output ===")
        parts.append(chktex_output)
        parts.append("")

    parts.append("=== Citation Verification ===")
    parts.append(f"  Status: {verification.overall_status}")
    parts.append(f"  Cite keys in .tex: {len(verification.cite_keys_in_tex)}")
    parts.append(f"  Entries in .bib: {len(verification.bib_keys)}")
    if verification.missing_in_bib:
        parts.append(f"  Missing in .bib: {sorted(verification.missing_in_bib)}")
    if verification.missing_figures:
        parts.append(f"  Missing figures: {sorted(verification.missing_figures)}")
    if verification.undefined_refs:
        parts.append(f"  Undefined refs: {sorted(verification.undefined_refs)}")

    parts.append("")
    parts.append("=== Full Compile Log ===")
    parts.append(build_result.log)

    return "\n".join(parts)


def _write_build_manifest(
    paths: RunPaths,
    build_result: BuildResult,
    verification: VerificationReport,
    bundle_path: Path | None,
) -> None:
    """Write build_manifest.json summarizing the pipeline run."""
    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pdf_generated": build_result.success,
        "pdf_path": str(build_result.pdf_path) if build_result.pdf_path else None,
        "error_count": len(build_result.errors),
        "warning_count": len(build_result.warnings),
        "citation_status": verification.overall_status,
        "bundle_path": str(bundle_path) if bundle_path else None,
    }
    manifest_path = paths.artifacts_dir / "build_manifest.json"
    manifest_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
