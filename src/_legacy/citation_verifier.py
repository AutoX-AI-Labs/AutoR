"""Citation and figure reference consistency verifier for Stage 07."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Regex patterns validated by AI-Scientist-v2 and data-to-paper.
CITE_PATTERN = re.compile(r"\\cite[tp]?\{([^}]+)\}")
INCLUDEGRAPHICS_PATTERN = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
BIB_ENTRY_PATTERN = re.compile(r"@\w+\{([^,]+),")
LABEL_PATTERN = re.compile(r"\\label\{([^}]+)\}")
REF_PATTERN = re.compile(r"\\(?:c?ref|Cref)\{([^}]+)\}")
INPUT_PATTERN = re.compile(r"\\input\{([^}]+)\}")

FIGURE_SUFFIXES = {".png", ".pdf", ".svg", ".jpg", ".jpeg", ".eps"}


@dataclass
class VerificationReport:
    cite_keys_in_tex: set[str] = field(default_factory=set)
    bib_keys: set[str] = field(default_factory=set)
    missing_in_bib: set[str] = field(default_factory=set)
    unused_in_bib: set[str] = field(default_factory=set)
    figure_refs: set[str] = field(default_factory=set)
    figures_available: set[str] = field(default_factory=set)
    missing_figures: set[str] = field(default_factory=set)
    unused_figures: set[str] = field(default_factory=set)
    label_keys: set[str] = field(default_factory=set)
    ref_keys: set[str] = field(default_factory=set)
    undefined_refs: set[str] = field(default_factory=set)
    overall_status: str = "pass"


def verify_citations(
    writing_dir: Path,
    figures_dir: Path,
    main_tex: str = "main.tex",
) -> VerificationReport:
    """Cross-check \\cite{} keys against .bib, and \\includegraphics against figures/."""
    report = VerificationReport()

    # Collect all .tex content (main + \\input'd files)
    all_tex = _collect_all_tex(writing_dir, main_tex)

    # Extract cite keys
    for match in CITE_PATTERN.finditer(all_tex):
        for key in match.group(1).split(","):
            key = key.strip()
            if key:
                report.cite_keys_in_tex.add(key)

    # Extract bib keys from all .bib files
    for bib_path in writing_dir.glob("*.bib"):
        bib_content = bib_path.read_text(encoding="utf-8", errors="replace")
        for match in BIB_ENTRY_PATTERN.finditer(bib_content):
            report.bib_keys.add(match.group(1).strip())

    report.missing_in_bib = report.cite_keys_in_tex - report.bib_keys
    report.unused_in_bib = report.bib_keys - report.cite_keys_in_tex

    # Extract figure references
    for match in INCLUDEGRAPHICS_PATTERN.finditer(all_tex):
        ref = match.group(1).strip()
        report.figure_refs.add(ref)

    # Collect available figures
    if figures_dir.exists():
        for path in figures_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in FIGURE_SUFFIXES:
                report.figures_available.add(path.name)

    # Normalize figure refs to filenames for comparison
    ref_filenames = {Path(ref).name for ref in report.figure_refs}
    report.missing_figures = ref_filenames - report.figures_available
    report.unused_figures = report.figures_available - ref_filenames

    # Extract labels and refs
    for match in LABEL_PATTERN.finditer(all_tex):
        report.label_keys.add(match.group(1).strip())
    for match in REF_PATTERN.finditer(all_tex):
        report.ref_keys.add(match.group(1).strip())
    report.undefined_refs = report.ref_keys - report.label_keys

    # Determine overall status
    if report.missing_in_bib or report.missing_figures:
        report.overall_status = "fail"
    elif report.undefined_refs:
        report.overall_status = "warn"

    return report


def write_verification_json(report: VerificationReport, output_path: Path) -> None:
    """Write verification report to JSON."""
    data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "citations": {
            "total_cite_keys": len(report.cite_keys_in_tex),
            "total_bib_entries": len(report.bib_keys),
            "missing_in_bib": sorted(report.missing_in_bib),
            "unused_in_bib": sorted(report.unused_in_bib),
        },
        "figures": {
            "total_referenced": len(report.figure_refs),
            "total_available": len(report.figures_available),
            "missing": sorted(report.missing_figures),
            "unused": sorted(report.unused_figures),
        },
        "cross_references": {
            "total_labels": len(report.label_keys),
            "total_refs": len(report.ref_keys),
            "undefined_refs": sorted(report.undefined_refs),
        },
        "overall_status": report.overall_status,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _collect_all_tex(writing_dir: Path, main_tex: str) -> str:
    """Recursively collect all .tex content starting from main_tex."""
    parts: list[str] = []
    visited: set[str] = set()
    _collect_tex_recursive(writing_dir, main_tex, parts, visited)
    return "\n".join(parts)


def _collect_tex_recursive(
    writing_dir: Path, tex_name: str, parts: list[str], visited: set[str]
) -> None:
    """Recursively collect .tex content, following \\input{} directives."""
    if tex_name in visited:
        return
    visited.add(tex_name)

    # Try with and without .tex extension
    candidates = [
        writing_dir / tex_name,
        writing_dir / f"{tex_name}.tex",
    ]
    for candidate in candidates:
        if candidate.exists():
            content = candidate.read_text(encoding="utf-8", errors="replace")
            parts.append(content)
            # Follow \\input{} directives
            for match in INPUT_PATTERN.finditer(content):
                child = match.group(1).strip()
                _collect_tex_recursive(writing_dir, child, parts, visited)
            return
