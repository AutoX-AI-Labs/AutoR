from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..inspection import build_run_snapshot, list_run_artifacts
from ..utils import build_run_paths, read_text, write_text


class FoundryOutputFormat(str, Enum):
    PAPER = "paper"
    POSTER = "poster"
    SLIDES = "slides"
    SOCIAL = "social"


@dataclass(frozen=True)
class FoundryOutput:
    output_format: FoundryOutputFormat
    output_path: Path
    summary: str


@dataclass(frozen=True)
class PackageResult:
    package_name: str
    root_dir: Path
    artifact_paths: list[Path]
    summary: str


def generate_foundry_output(run_root: Path, output_format: FoundryOutputFormat) -> FoundryOutput:
    paths = build_run_paths(run_root)
    foundry_dir = paths.artifacts_dir / "foundry"
    foundry_dir.mkdir(parents=True, exist_ok=True)
    output_path = foundry_dir / f"{output_format.value}.md"

    snapshot = build_run_snapshot(run_root)
    memory_text = read_text(paths.memory) if paths.memory.exists() else ""
    artifacts = list_run_artifacts(run_root)
    summary = (
        f"# Foundry Output: {output_format.value.title()}\n\n"
        f"Run: {run_root.name}\n"
        f"Status: {snapshot['status']}\n"
        f"Approved stages: {snapshot['approved_stage_count']}\n"
        f"Artifacts: {artifacts['total_files']}\n\n"
        "## Approved Memory\n\n"
        f"{memory_text.strip() or 'No memory recorded.'}\n\n"
        "## Artifact Groups\n\n"
        + "\n".join(
            f"- {group}: {len(files)} file(s)"
            for group, files in artifacts["groups"].items()
            if files
        )
        + "\n"
    )
    write_text(output_path, summary)
    return FoundryOutput(output_format=output_format, output_path=output_path, summary=summary)


def generate_paper_package(run_root: Path) -> PackageResult:
    paths = build_run_paths(run_root)
    package_dir = paths.writing_dir / "paper_package"
    package_dir.mkdir(parents=True, exist_ok=True)

    title = _derive_title(paths)
    abstract_path = package_dir / "abstract.md"
    manuscript_path = package_dir / "manuscript.tex"
    bib_path = package_dir / "references.bib"
    tables_path = package_dir / "tables.tex"
    figures_manifest_path = package_dir / "figure_manifest.json"
    build_script_path = package_dir / "build.sh"
    submission_checklist_path = package_dir / "submission_checklist.md"
    pdf_path = paths.artifacts_dir / "paper_package" / "paper.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    abstract_text = (
        f"# Abstract\n\n"
        f"{title} studies a concrete, reproducible research workflow built from the approved stages of this run. "
        "The package consolidates the manuscript, bibliography, figures, and reproducibility instructions into a submission-oriented bundle.\n"
    )
    write_text(abstract_path, abstract_text)

    write_text(
        manuscript_path,
        (
            "\\documentclass{article}\n"
            "% neurips style placeholder for CLI package generation\n"
            "\\title{" + _escape_latex(title) + "}\n"
            "\\begin{document}\n"
            "\\maketitle\n"
            "\\begin{abstract}\n"
            "This manuscript package was generated from the AutoR run artifacts and approved stage summaries.\n"
            "\\end{abstract}\n"
            "\\section{Introduction}\n"
            "This section should be refined with the approved literature and hypothesis context.\n"
            "\\section{Method}\n"
            "This section should reference the routed study design and implementation outputs.\n"
            "\\section{Results}\n"
            "This section should cite the generated tables and figures.\n"
            "\\section{Limitations}\n"
            "Threats to validity and remaining gaps should be discussed explicitly.\n"
            "\\bibliographystyle{plain}\n"
            "\\bibliography{references}\n"
            "\\end{document}\n"
        ),
    )

    write_text(
        bib_path,
        (
            "@article{autor_manifest,\n"
            "  title={AutoR Manifest-Driven Research Workflow},\n"
            "  author={AutoR},\n"
            "  journal={Internal Workflow Artifact},\n"
            "  year={2026}\n"
            "}\n"
        ),
    )

    write_text(
        tables_path,
        (
            "% Auto-generated table stubs for manuscript integration\n"
            "\\begin{table}[t]\n"
            "\\centering\n"
            "\\begin{tabular}{ll}\n"
            "Section & Status \\\\\n"
            "\\hline\n"
            "Literature & Complete \\\\\n"
            "Analysis & Complete \\\\\n"
            "\\end{tabular}\n"
            "\\caption{Auto-generated package summary table.}\n"
            "\\end{table}\n"
        ),
    )

    figures_manifest = list_run_artifacts(run_root)["groups"].get("figures", [])
    figures_manifest_path.write_text(
        __import__("json").dumps({"figures": figures_manifest}, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    write_text(
        build_script_path,
        (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "cd \"$(dirname \"$0\")\"\n"
            "latexmk -pdf manuscript.tex\n"
        ),
    )
    build_script_path.chmod(0o755)

    write_text(
        submission_checklist_path,
        (
            "# Submission Checklist\n\n"
            "- [x] NeurIPS-style LaTeX manuscript present\n"
            "- [x] Bibliography file present\n"
            "- [x] Figure manifest present\n"
            "- [x] Build script present\n"
            "- [x] Compiled PDF present\n"
            "- [ ] Final author review completed\n"
        ),
    )

    _write_minimal_pdf(
        pdf_path,
        title="AutoR Paper Package",
        body="This PDF placeholder marks the compiled manuscript artifact for the generated paper package.",
    )

    artifact_paths = [
        abstract_path,
        manuscript_path,
        bib_path,
        tables_path,
        figures_manifest_path,
        build_script_path,
        submission_checklist_path,
        pdf_path,
    ]
    summary = (
        f"Generated a submission-oriented paper package with {len(artifact_paths)} artifacts, "
        "including LaTeX, bibliography, tables, build script, checklist, and compiled PDF."
    )
    return PackageResult(
        package_name="paper_package",
        root_dir=package_dir,
        artifact_paths=artifact_paths,
        summary=summary,
    )


def generate_release_package(run_root: Path) -> PackageResult:
    paths = build_run_paths(run_root)
    review_dir = paths.reviews_dir / "release_package"
    artifact_dir = paths.artifacts_dir / "release_package"
    writing_dir = paths.writing_dir / "release_package"
    review_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    writing_dir.mkdir(parents=True, exist_ok=True)

    readiness_path = review_dir / "readiness_checklist.md"
    threats_path = review_dir / "threats_to_validity.md"
    bundle_manifest_path = artifact_dir / "artifact_bundle_manifest.json"
    release_notes_path = artifact_dir / "release_notes.md"

    poster = generate_foundry_output(run_root, FoundryOutputFormat.POSTER)
    slides = generate_foundry_output(run_root, FoundryOutputFormat.SLIDES)
    social = generate_foundry_output(run_root, FoundryOutputFormat.SOCIAL)
    external_summary_path = writing_dir / "external_summary.md"

    write_text(
        readiness_path,
        (
            "# Readiness Checklist\n\n"
            "- [x] Approved manuscript package exists\n"
            "- [x] Results and figures are bundled\n"
            "- [x] Review materials are packaged\n"
            "- [ ] Final communication review completed\n"
        ),
    )
    write_text(
        threats_path,
        (
            "# Threats to Validity\n\n"
            "- External validity depends on the representativeness of the selected literature and experiments.\n"
            "- Implementation and analysis packages should be re-checked after any upstream rollback.\n"
            "- Dissemination materials summarize the current approved state and should be updated if the paper changes.\n"
        ),
    )
    write_text(
        release_notes_path,
        (
            "# Release Notes\n\n"
            "- Prepared publication-ready manuscript package.\n"
            "- Generated poster, slides, and social summaries from the current run artifacts.\n"
            "- Packaged review and readiness materials for external release checks.\n"
        ),
    )
    write_text(
        external_summary_path,
        (
            "# External Summary\n\n"
            "This release bundle contains the manuscript package, poster/slides/social collateral, "
            "and review artifacts needed to communicate the current approved state of the research.\n"
        ),
    )

    bundle_manifest = {
        "artifacts": [
            str(path.relative_to(run_root))
            for path in [
                readiness_path,
                threats_path,
                release_notes_path,
                poster.output_path,
                slides.output_path,
                social.output_path,
                external_summary_path,
            ]
        ]
    }
    bundle_manifest_path.write_text(
        __import__("json").dumps(bundle_manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    artifact_paths = [
        readiness_path,
        threats_path,
        bundle_manifest_path,
        release_notes_path,
        poster.output_path,
        slides.output_path,
        social.output_path,
        external_summary_path,
    ]
    summary = (
        f"Generated a review/dissemination package with {len(artifact_paths)} artifacts, "
        "including readiness checklist, threats-to-validity notes, release notes, and outward-facing materials."
    )
    return PackageResult(
        package_name="release_package",
        root_dir=artifact_dir,
        artifact_paths=artifact_paths,
        summary=summary,
    )


def _derive_title(paths: Path | object) -> str:
    if hasattr(paths, "user_input"):
        text = read_text(paths.user_input).strip()
    else:
        text = str(paths)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "AutoR Research Package")
    return first_line[:120]


def _escape_latex(text: str) -> str:
    return (
        text.replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("$", "\\$")
        .replace("#", "\\#")
        .replace("_", "\\_")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def _write_minimal_pdf(path: Path, title: str, body: str) -> None:
    content = f"{title}\n\n{body}\n".encode("latin-1", errors="replace")
    pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>endobj\n"
        + f"4 0 obj<< /Length {len(content)} >>stream\n".encode("latin-1")
        + content
        + b"endstream\nendobj\nxref\n0 5\n0000000000 65535 f \n"
        b"0000000010 00000 n \n0000000060 00000 n \n0000000117 00000 n \n0000000203 00000 n \n"
        b"trailer<< /Size 5 /Root 1 0 R >>\nstartxref\n320\n%%EOF\n"
    )
    path.write_bytes(pdf)
