"""LaTeX compilation service layer for Stage 07 writing pipeline."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LatexError:
    message: str
    line_number: int | None = None
    context_lines: str | None = None


@dataclass
class BuildResult:
    success: bool
    pdf_path: Path | None = None
    log: str = ""
    errors: list[LatexError] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    attempts: int = 0
    chktex_output: str | None = None


# Four-step compile sequence validated by AI-Scientist-v2, data-to-paper, CodeScientist, micromanubot.
_COMPILE_STEPS = [
    ("pdflatex", ["-interaction=nonstopmode"]),
    ("bibtex", []),
    ("pdflatex", ["-interaction=nonstopmode"]),
    ("pdflatex", ["-interaction=nonstopmode"]),
]

_ERROR_PATTERN = re.compile(r"^! (.+)$", re.MULTILINE)
_LINE_PATTERN = re.compile(r"l\.(\d+)")
_OVERFLOW_PATTERN = re.compile(r"Overfull \\hbox \((.+?)pt too wide\)")


def compile_latex(
    working_dir: Path,
    main_tex: str = "main.tex",
    timeout: int = 60,
) -> BuildResult:
    """Execute the four-step pdflatex+bibtex compile sequence.

    Success is determined by whether the output PDF exists and is non-empty,
    not by process exit codes (pdflatex often returns non-zero but still
    produces a usable PDF).
    """
    stem = Path(main_tex).stem
    log_parts: list[str] = []
    all_errors: list[LatexError] = []
    all_warnings: list[str] = []

    tex_content = ""
    tex_path = working_dir / main_tex
    if tex_path.exists():
        tex_content = tex_path.read_text(encoding="utf-8", errors="replace")

    for step_idx, (engine, extra_args) in enumerate(_COMPILE_STEPS):
        if engine == "bibtex":
            cmd = [engine, stem]
        else:
            cmd = [engine] + extra_args + [main_tex]

        step_label = f"Step {step_idx + 1}: {' '.join(cmd)}"
        log_parts.append(f"\n{'=' * 60}\n{step_label}\n{'=' * 60}")

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(working_dir),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            log_parts.append(proc.stdout)
            if proc.stderr:
                log_parts.append(f"STDERR:\n{proc.stderr}")

            if engine == "pdflatex":
                errors = extract_latex_errors(proc.stdout, tex_content)
                all_errors.extend(errors)
                warnings = _extract_overflow_warnings(proc.stdout)
                all_warnings.extend(warnings)

        except subprocess.TimeoutExpired:
            log_parts.append(f"TIMEOUT after {timeout}s")
            all_errors.append(LatexError(message=f"{engine} timed out after {timeout}s"))
        except FileNotFoundError:
            log_parts.append(f"ERROR: {engine} not found on PATH")
            all_errors.append(LatexError(message=f"{engine} not found. Is TeX Live installed?"))
            break

    pdf_path = working_dir / f"{stem}.pdf"
    success = pdf_path.exists() and pdf_path.stat().st_size > 0

    full_log = "\n".join(log_parts)

    return BuildResult(
        success=success,
        pdf_path=pdf_path if success else None,
        log=full_log,
        errors=all_errors,
        warnings=all_warnings,
        attempts=1,
    )


def run_chktex(
    working_dir: Path,
    main_tex: str = "main.tex",
) -> str:
    """Run chktex with the suppressed-warning set validated by AI-Scientist-v2."""
    cmd = ["chktex", main_tex, "-q", "-n2", "-n24", "-n13", "-n1"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return (proc.stdout + proc.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def extract_latex_errors(pdflatex_output: str, tex_content: str = "") -> list[LatexError]:
    """Extract structured errors from pdflatex stdout.

    Pattern: lines starting with '! ' are errors, 'l.NNN' gives the line number.
    """
    errors: list[LatexError] = []
    lines = pdflatex_output.splitlines()
    tex_lines = tex_content.splitlines() if tex_content else []

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("! "):
            message = line[2:].strip()
            # Look ahead up to 4 lines for line number
            context_chunk = "\n".join(lines[i : i + 5])
            line_match = _LINE_PATTERN.search(context_chunk)
            line_number = int(line_match.group(1)) if line_match else None

            context_lines = None
            if line_number and tex_lines:
                start = max(0, line_number - 2)
                end = min(len(tex_lines), line_number + 1)
                context_lines = "\n".join(
                    f"{'>>>' if j + 1 == line_number else '   '} {j + 1}: {tex_lines[j]}"
                    for j in range(start, end)
                )

            errors.append(LatexError(
                message=message,
                line_number=line_number,
                context_lines=context_lines,
            ))
        i += 1

    return errors


def _extract_overflow_warnings(pdflatex_output: str) -> list[str]:
    return [
        f"Overfull hbox ({m.group(1)}pt too wide)"
        for m in _OVERFLOW_PATTERN.finditer(pdflatex_output)
    ]


def format_build_errors_for_prompt(result: BuildResult) -> str:
    """Format build errors into a string suitable for feeding back to an agent."""
    parts: list[str] = []
    if result.errors:
        parts.append("## LaTeX Compilation Errors\n")
        for err in result.errors:
            parts.append(f"- {err.message}")
            if err.line_number:
                parts.append(f"  (line {err.line_number})")
            if err.context_lines:
                parts.append(f"  ```\n{err.context_lines}\n  ```")
    if result.chktex_output:
        parts.append(f"\n## chktex Lint Output\n```\n{result.chktex_output}\n```")
    return "\n".join(parts)
