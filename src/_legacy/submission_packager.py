"""Submission bundle packager for Stage 07 writing pipeline."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

KEEP_SUFFIXES = {
    ".tex", ".sty", ".bst", ".bib", ".cls",
    ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg",
}
EXCLUDE_SUFFIXES = {
    ".aux", ".log", ".out", ".fls", ".fdb_latexmk",
    ".synctex.gz", ".blg", ".bbl", ".toc", ".lof", ".lot",
    ".nav", ".snm", ".vrb",
}
EXCLUDE_DIRS = {"__pycache__", ".git", "__MACOSX", ".tmp"}


def package_submission(
    writing_dir: Path,
    figures_dir: Path,
    output_dir: Path,
    pdf_path: Path | None = None,
) -> Path | None:
    """Generate submission_bundle.zip containing all files needed for submission.

    Returns the path to the zip file, or None if packaging fails.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "submission_bundle.zip"

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add writing directory files
            _add_directory_to_zip(zf, writing_dir, "")

            # Add figures
            if figures_dir.exists():
                _add_directory_to_zip(zf, figures_dir, "figures")

            # Add compiled PDF if available and not already included
            if pdf_path and pdf_path.exists():
                arcname = pdf_path.name
                if arcname not in zf.namelist():
                    zf.write(pdf_path, arcname)

        return zip_path
    except Exception:
        if zip_path.exists():
            zip_path.unlink()
        return None


def _add_directory_to_zip(
    zf: zipfile.ZipFile,
    directory: Path,
    prefix: str,
) -> None:
    """Add files from a directory to a zip, filtering by suffix."""
    if not directory.exists():
        return
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        # Skip excluded directories
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        # Skip excluded suffixes
        if path.suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        # Only include known-good suffixes
        if path.suffix.lower() not in KEEP_SUFFIXES:
            continue

        rel = path.relative_to(directory)
        arcname = f"{prefix}/{rel}" if prefix else str(rel)
        zf.write(path, arcname)
