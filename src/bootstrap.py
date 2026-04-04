from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .utils import RunPaths

# ---------------------------------------------------------------------------
# Suffix sets for corpus scanning
# ---------------------------------------------------------------------------

_CORPUS_SUFFIXES = {".pdf", ".tex", ".bib", ".bibtex", ".md", ".txt"}

_MAX_CHARS_PER_FILE = 8000
_MAX_FILES = 50


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BibEntry:
    """A single parsed BibTeX entry."""
    cite_key: str
    entry_type: str  # article, inproceedings, book, etc.
    title: str = ""
    authors: str = ""
    year: str = ""
    venue: str = ""  # journal, booktitle, or publisher
    doi: str = ""


@dataclass
class PaperMetadata:
    """Per-paper metadata extracted before Claude analysis."""
    source_path: str
    file_type: str  # "pdf", "tex", "bib", "notes"
    title: str = ""
    abstract: str = ""
    sections: list[str] = field(default_factory=list)  # section headings found
    bib_entries: list[BibEntry] = field(default_factory=list)
    extracted_text: str = ""
    char_count: int = 0


@dataclass
class CorpusManifest:
    """Summary of what was scanned and how."""
    corpus_path: str
    scanned_at: str
    total_files_found: int
    files_processed: int
    files_skipped: int
    skipped_reasons: list[str] = field(default_factory=list)
    papers: list[PaperMetadata] = field(default_factory=list)

    @property
    def unique_bib_entries(self) -> list[BibEntry]:
        """Deduplicated bibliography entries across all papers."""
        seen: set[str] = set()
        entries: list[BibEntry] = []
        for paper in self.papers:
            for bib in paper.bib_entries:
                key = bib.cite_key.lower()
                if key not in seen:
                    seen.add(key)
                    entries.append(bib)
        return entries

    @property
    def stats(self) -> dict[str, int | str]:
        type_counts = {}
        for p in self.papers:
            type_counts[p.file_type] = type_counts.get(p.file_type, 0) + 1
        years = [e.year for p in self.papers for e in p.bib_entries if e.year.isdigit()]
        return {
            "total_papers": len(self.papers),
            "by_type": type_counts,
            "unique_references": len(self.unique_bib_entries),
            "year_range": f"{min(years)}–{max(years)}" if years else "unknown",
        }


@dataclass
class ResearchProfile:
    themes: list[str] = field(default_factory=list)
    terminology: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    venues: list[str] = field(default_factory=list)
    confidence: str = ""  # "high", "medium", "low" based on corpus size
    summary: str = ""


@dataclass
class CitationNeighborhood:
    frequently_cited: list[dict[str, str]] = field(default_factory=list)
    related_authors: list[str] = field(default_factory=list)
    key_venues: list[str] = field(default_factory=list)
    seed_papers: list[dict[str, str]] = field(default_factory=list)  # high-priority refs for Stage 01


@dataclass
class StyleProfile:
    """Structured writing style analysis (not just free text)."""
    voice: str = ""           # "passive", "active", "mixed"
    person: str = ""          # "first_plural", "first_singular", "impersonal"
    formality: str = ""       # "formal", "semi-formal"
    avg_section_count: int = 0
    section_ordering: list[str] = field(default_factory=list)  # typical section sequence
    abstract_pattern: str = ""  # e.g. "problem-method-result-impact"
    notation_conventions: list[str] = field(default_factory=list)
    paragraph_style: str = ""   # e.g. "topic-sentence-first", "long-form-argument"
    notes: str = ""             # free-form additional observations


@dataclass
class BootstrapResult:
    profile: ResearchProfile
    citation_neighborhood: CitationNeighborhood
    style_profile: StyleProfile
    summary: str
    corpus_manifest: CorpusManifest


# ---------------------------------------------------------------------------
# BibTeX parsing
# ---------------------------------------------------------------------------

_BIB_ENTRY_RE = re.compile(
    r"@(\w+)\s*\{\s*([^,\s]+)\s*,(.+?)\n\s*\}",
    re.DOTALL,
)
_BIB_FIELD_RE = re.compile(
    r"(\w+)\s*=\s*[{\"](.+?)[}\"]",
    re.DOTALL,
)


def parse_bibtex(text: str) -> list[BibEntry]:
    """Parse BibTeX text into structured entries."""
    entries: list[BibEntry] = []
    for match in _BIB_ENTRY_RE.finditer(text):
        entry_type = match.group(1).lower()
        cite_key = match.group(2).strip()
        body = match.group(3)

        fields: dict[str, str] = {}
        for fm in _BIB_FIELD_RE.finditer(body):
            key = fm.group(1).lower().strip()
            val = fm.group(2).strip()
            # Clean up LaTeX artifacts
            val = re.sub(r"[{}]", "", val).strip()
            fields[key] = val

        venue = fields.get("journal") or fields.get("booktitle") or fields.get("publisher", "")
        entries.append(BibEntry(
            cite_key=cite_key,
            entry_type=entry_type,
            title=fields.get("title", ""),
            authors=fields.get("author", ""),
            year=fields.get("year", ""),
            venue=venue,
            doi=fields.get("doi", ""),
        ))
    return entries


# ---------------------------------------------------------------------------
# TeX section extraction
# ---------------------------------------------------------------------------

_TEX_TITLE_RE = re.compile(r"\\title\s*(?:\[.*?\])?\s*\{(.+?)\}", re.DOTALL)
_TEX_ABSTRACT_RE = re.compile(
    r"\\begin\{abstract\}(.+?)\\end\{abstract\}",
    re.DOTALL,
)
_TEX_SECTION_RE = re.compile(r"\\(?:section|subsection)\s*\{(.+?)\}")
_TEX_PREAMBLE_END_RE = re.compile(r"\\begin\{document\}")


def extract_tex_metadata(text: str) -> tuple[str, str, list[str], str]:
    """Extract title, abstract, section headings, and body from a .tex file.

    Returns (title, abstract, section_headings, body_text).
    The body_text excludes the preamble.
    """
    title = ""
    title_match = _TEX_TITLE_RE.search(text)
    if title_match:
        title = _clean_latex(title_match.group(1))

    abstract = ""
    abstract_match = _TEX_ABSTRACT_RE.search(text)
    if abstract_match:
        abstract = _clean_latex(abstract_match.group(1))

    sections = [_clean_latex(m.group(1)) for m in _TEX_SECTION_RE.finditer(text)]

    # Strip preamble for the body text sent to Claude
    body = text
    preamble_end = _TEX_PREAMBLE_END_RE.search(text)
    if preamble_end:
        body = text[preamble_end.end():]

    return title, abstract, sections, body.strip()


def _clean_latex(text: str) -> str:
    """Remove common LaTeX commands from extracted text."""
    text = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", text)
    text = re.sub(r"[{}\\]", "", text)
    return " ".join(text.split()).strip()


# ---------------------------------------------------------------------------
# Corpus scanning (enhanced)
# ---------------------------------------------------------------------------


def scan_corpus(corpus_path: Path) -> CorpusManifest:
    """Scan a directory for paper-related files with structured extraction.

    Returns a CorpusManifest with per-paper metadata and pre-parsed bibliography.
    """
    corpus_path = corpus_path.expanduser().resolve()
    if not corpus_path.exists():
        raise FileNotFoundError(f"Paper corpus path not found: {corpus_path}")
    if not corpus_path.is_dir():
        raise NotADirectoryError(f"Paper corpus path is not a directory: {corpus_path}")

    all_files: list[Path] = []
    for suffix in _CORPUS_SUFFIXES:
        all_files.extend(corpus_path.rglob(f"*{suffix}"))
    all_files = sorted(set(all_files))

    manifest = CorpusManifest(
        corpus_path=str(corpus_path),
        scanned_at=datetime.now().isoformat(timespec="seconds"),
        total_files_found=len(all_files),
        files_processed=0,
        files_skipped=0,
    )

    for fpath in all_files[:_MAX_FILES]:
        paper = _process_file(fpath)
        if paper is None:
            manifest.files_skipped += 1
            manifest.skipped_reasons.append(f"{fpath.name}: empty or unreadable")
            continue
        manifest.papers.append(paper)
        manifest.files_processed += 1

    if len(all_files) > _MAX_FILES:
        manifest.files_skipped += len(all_files) - _MAX_FILES
        manifest.skipped_reasons.append(
            f"Corpus exceeds {_MAX_FILES} file limit; {len(all_files) - _MAX_FILES} file(s) skipped."
        )

    return manifest


def _process_file(path: Path) -> PaperMetadata | None:
    """Extract metadata and text from a single corpus file."""
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        text = _extract_pdf_text(path)
        if not text.strip():
            return None
        return PaperMetadata(
            source_path=str(path),
            file_type="pdf",
            extracted_text=text[:_MAX_CHARS_PER_FILE],
            char_count=len(text),
        )

    if suffix == ".tex":
        raw = _read_text_safe(path)
        if not raw.strip():
            return None
        title, abstract, sections, body = extract_tex_metadata(raw)
        return PaperMetadata(
            source_path=str(path),
            file_type="tex",
            title=title,
            abstract=abstract,
            sections=sections,
            extracted_text=body[:_MAX_CHARS_PER_FILE],
            char_count=len(body),
        )

    if suffix in {".bib", ".bibtex"}:
        raw = _read_text_safe(path)
        if not raw.strip():
            return None
        bib_entries = parse_bibtex(raw)
        return PaperMetadata(
            source_path=str(path),
            file_type="bib",
            bib_entries=bib_entries,
            extracted_text=raw[:_MAX_CHARS_PER_FILE],
            char_count=len(raw),
        )

    # notes (md, txt)
    raw = _read_text_safe(path)
    if not raw.strip():
        return None
    return PaperMetadata(
        source_path=str(path),
        file_type="notes",
        extracted_text=raw[:_MAX_CHARS_PER_FILE],
        char_count=len(raw),
    )


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF using PyMuPDF (fitz). Returns empty string if unavailable."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return f"[PDF file: {path.name} — install PyMuPDF (`pip install pymupdf`) for text extraction]"

    try:
        doc = fitz.open(str(path))
        pages = []
        for page in doc:
            pages.append(page.get_text())
        doc.close()
        return "\n\n".join(pages)
    except Exception as exc:
        return f"[PDF extraction failed for {path.name}: {exc}]"


# ---------------------------------------------------------------------------
# Prompt formatting for Claude (structured, not raw dump)
# ---------------------------------------------------------------------------


def format_corpus_for_prompt(manifest: CorpusManifest) -> str:
    """Format the scanned corpus as structured prompt sections for Claude."""
    if not manifest.papers:
        return "_No corpus files found._"

    parts: list[str] = []

    # Corpus overview
    stats = manifest.stats
    overview_lines = [
        "## Corpus Overview",
        f"- **Papers scanned:** {stats['total_papers']}",
        f"- **File types:** {', '.join(f'{k}: {v}' for k, v in stats['by_type'].items())}",
        f"- **Unique references (from .bib):** {stats['unique_references']}",
        f"- **Year range:** {stats['year_range']}",
    ]
    parts.append("\n".join(overview_lines))

    # Pre-parsed bibliography (structured, not raw text)
    bib_entries = manifest.unique_bib_entries
    if bib_entries:
        bib_lines = ["## Pre-Parsed Bibliography", ""]
        for entry in bib_entries[:80]:
            line = f"- [{entry.cite_key}] "
            if entry.authors:
                line += f"{entry.authors}. "
            if entry.title:
                line += f'"{entry.title}" '
            if entry.venue:
                line += f"*{entry.venue}* "
            if entry.year:
                line += f"({entry.year})"
            bib_lines.append(line.strip())
        if len(bib_entries) > 80:
            bib_lines.append(f"- ... and {len(bib_entries) - 80} more entries")
        parts.append("\n".join(bib_lines))

    # Per-paper content (with metadata headers, not just raw dump)
    for i, paper in enumerate(manifest.papers, 1):
        if paper.file_type == "bib":
            continue  # already shown above as structured data
        header_lines = [f"### Paper {i}: {Path(paper.source_path).name} ({paper.file_type})"]
        if paper.title:
            header_lines.append(f"**Title:** {paper.title}")
        if paper.abstract:
            header_lines.append(f"**Abstract:** {paper.abstract}")
        if paper.sections:
            header_lines.append(f"**Sections:** {' → '.join(paper.sections)}")
        header = "\n".join(header_lines)
        parts.append(f"{header}\n\n```\n{paper.extracted_text}\n```")

    return "\n\n".join(parts)


def format_corpus_stats_for_log(manifest: CorpusManifest) -> str:
    """Format corpus scan results for log entries."""
    lines = [
        f"Corpus path: {manifest.corpus_path}",
        f"Scanned at: {manifest.scanned_at}",
        f"Total files found: {manifest.total_files_found}",
        f"Files processed: {manifest.files_processed}",
        f"Files skipped: {manifest.files_skipped}",
    ]
    if manifest.skipped_reasons:
        lines.append("Skip reasons:")
        lines.extend(f"  - {r}" for r in manifest.skipped_reasons)
    lines.append("Papers:")
    for p in manifest.papers:
        title = f" ({p.title})" if p.title else ""
        lines.append(f"  - {Path(p.source_path).name} [{p.file_type}]{title} ({p.char_count} chars)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Profile artifact I/O
# ---------------------------------------------------------------------------


def save_bootstrap_result(paths: RunPaths, result: BootstrapResult) -> None:
    """Write all bootstrap profile artifacts to workspace/profile/."""
    profile_dir = paths.profile_dir
    profile_dir.mkdir(parents=True, exist_ok=True)

    # research_profile.json
    _write_json(profile_dir / "research_profile.json", asdict(result.profile))

    # citation_neighborhood.json
    _write_json(profile_dir / "citation_neighborhood.json", asdict(result.citation_neighborhood))

    # style_profile.json (structured)
    _write_json(profile_dir / "style_profile.json", asdict(result.style_profile))

    # style_notes.md (human-readable rendering of style_profile)
    _write_style_notes_md(profile_dir / "style_notes.md", result.style_profile)

    # bootstrap_summary.md
    (profile_dir / "bootstrap_summary.md").write_text(
        result.summary.rstrip() + "\n", encoding="utf-8",
    )

    # corpus_manifest.json (what was scanned)
    _write_json(profile_dir / "corpus_manifest.json", asdict(result.corpus_manifest))


def _write_style_notes_md(path: Path, style: StyleProfile) -> None:
    """Render a StyleProfile as human-readable markdown."""
    lines = ["# Writing Style Profile", ""]
    if style.voice:
        lines.append(f"- **Voice:** {style.voice}")
    if style.person:
        lines.append(f"- **Person:** {style.person}")
    if style.formality:
        lines.append(f"- **Formality:** {style.formality}")
    if style.section_ordering:
        lines.append(f"- **Typical section order:** {' → '.join(style.section_ordering)}")
    if style.avg_section_count:
        lines.append(f"- **Avg section count:** {style.avg_section_count}")
    if style.abstract_pattern:
        lines.append(f"- **Abstract pattern:** {style.abstract_pattern}")
    if style.paragraph_style:
        lines.append(f"- **Paragraph style:** {style.paragraph_style}")
    if style.notation_conventions:
        lines.append("- **Notation conventions:**")
        for conv in style.notation_conventions:
            lines.append(f"  - {conv}")
    if style.notes:
        lines.extend(["", "## Additional Observations", "", style.notes])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def load_bootstrap_summary(paths: RunPaths) -> str | None:
    summary_path = paths.profile_dir / "bootstrap_summary.md"
    if not summary_path.exists():
        return None
    return summary_path.read_text(encoding="utf-8").strip()


def load_research_profile(paths: RunPaths) -> ResearchProfile | None:
    profile_path = paths.profile_dir / "research_profile.json"
    if not profile_path.exists():
        return None
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        return ResearchProfile(**data)
    except (json.JSONDecodeError, TypeError):
        return None


def load_citation_neighborhood(paths: RunPaths) -> CitationNeighborhood | None:
    cn_path = paths.profile_dir / "citation_neighborhood.json"
    if not cn_path.exists():
        return None
    try:
        data = json.loads(cn_path.read_text(encoding="utf-8"))
        return CitationNeighborhood(**data)
    except (json.JSONDecodeError, TypeError):
        return None


def load_style_profile(paths: RunPaths) -> StyleProfile | None:
    style_path = paths.profile_dir / "style_profile.json"
    if not style_path.exists():
        return None
    try:
        data = json.loads(style_path.read_text(encoding="utf-8"))
        return StyleProfile(**data)
    except (json.JSONDecodeError, TypeError):
        return None


def load_corpus_manifest(paths: RunPaths) -> CorpusManifest | None:
    manifest_path = paths.profile_dir / "corpus_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        papers = [PaperMetadata(**p) for p in data.pop("papers", [])]
        for p in papers:
            p.bib_entries = [BibEntry(**b) if isinstance(b, dict) else b for b in p.bib_entries]
        manifest = CorpusManifest(**data, papers=papers)
        return manifest
    except (json.JSONDecodeError, TypeError):
        return None


def bootstrap_profile_exists(paths: RunPaths) -> bool:
    return (paths.profile_dir / "bootstrap_summary.md").exists()


# ---------------------------------------------------------------------------
# Stage-specific profile formatting
# ---------------------------------------------------------------------------


def format_profile_for_prompt(paths: RunPaths, stage_slug: str | None = None) -> str | None:
    """Format the bootstrap profile for injection into stage prompts.

    Different stages get different emphasis:
    - Stage 01 (literature_survey): citation neighborhood + seed papers
    - Stage 07 (writing): full style profile + writing conventions
    - Other stages: general research profile + summary
    """
    if not bootstrap_profile_exists(paths):
        return None

    parts: list[str] = []

    # Always include the summary
    summary = load_bootstrap_summary(paths)
    if summary:
        parts.append(f"## Researcher Profile Summary\n\n{summary}")

    # Always include the general profile
    profile = load_research_profile(paths)
    if profile:
        lines = ["## Research Profile"]
        if profile.themes:
            lines.append(f"- **Themes:** {', '.join(profile.themes)}")
        if profile.terminology:
            lines.append(f"- **Key terminology:** {', '.join(profile.terminology)}")
        if profile.methods:
            lines.append(f"- **Methods:** {', '.join(profile.methods)}")
        if profile.venues:
            lines.append(f"- **Venues:** {', '.join(profile.venues)}")
        if profile.confidence:
            lines.append(f"- **Profile confidence:** {profile.confidence}")
        parts.append("\n".join(lines))

    # Stage-specific sections
    if stage_slug == "01_literature_survey":
        parts.extend(_format_citation_context(paths, expanded=True))
    elif stage_slug == "07_writing":
        parts.extend(_format_style_context(paths, expanded=True))
        parts.extend(_format_citation_context(paths, expanded=False))
    else:
        parts.extend(_format_citation_context(paths, expanded=False))
        parts.extend(_format_style_context(paths, expanded=False))

    return "\n\n".join(parts) if parts else None


def _format_citation_context(paths: RunPaths, expanded: bool) -> list[str]:
    """Format citation neighborhood. Expanded mode shows seed papers and full details."""
    cn = load_citation_neighborhood(paths)
    if not cn:
        return []

    lines = ["## Citation Neighborhood"]
    if cn.seed_papers and expanded:
        lines.append("\n**Seed papers for literature search** (high-priority starting points):")
        for ref in cn.seed_papers:
            title = ref.get("title", "Unknown")
            authors = ref.get("authors", "")
            year = ref.get("year", "")
            line = f"- {title}"
            if authors:
                line += f" — {authors}"
            if year:
                line += f" ({year})"
            lines.append(line)

    if cn.frequently_cited:
        limit = 25 if expanded else 10
        lines.append(f"\n**Frequently cited** (top {min(limit, len(cn.frequently_cited))}):")
        for ref in cn.frequently_cited[:limit]:
            title = ref.get("title", "Unknown")
            authors = ref.get("authors", "")
            year = ref.get("year", "")
            line = f"- {title}"
            if authors:
                line += f" ({authors}"
                if year:
                    line += f", {year}"
                line += ")"
            elif year:
                line += f" ({year})"
            lines.append(line)

    if cn.related_authors:
        limit = 20 if expanded else 10
        lines.append(f"\n**Related authors:** {', '.join(cn.related_authors[:limit])}")
    if cn.key_venues:
        lines.append(f"**Key venues:** {', '.join(cn.key_venues)}")

    return ["\n".join(lines)]


def _format_style_context(paths: RunPaths, expanded: bool) -> list[str]:
    """Format writing style profile. Expanded mode includes full detail for Stage 07."""
    style = load_style_profile(paths)
    if not style:
        # Fall back to reading style_notes.md directly
        style_path = paths.profile_dir / "style_notes.md"
        if style_path.exists():
            text = style_path.read_text(encoding="utf-8").strip()
            if text:
                return [f"## Writing Style Notes\n\n{text}"]
        return []

    if not expanded:
        # Compact: just the key facts
        lines = ["## Writing Style (compact)"]
        attrs = []
        if style.voice:
            attrs.append(f"voice: {style.voice}")
        if style.person:
            attrs.append(f"person: {style.person}")
        if style.formality:
            attrs.append(f"formality: {style.formality}")
        if attrs:
            lines.append(f"- {', '.join(attrs)}")
        if style.section_ordering:
            lines.append(f"- Typical sections: {' → '.join(style.section_ordering)}")
        return ["\n".join(lines)]

    # Expanded: full detail for writing stage
    lines = ["## Writing Style Profile (detailed)"]
    if style.voice:
        lines.append(f"- **Voice:** {style.voice}")
    if style.person:
        lines.append(f"- **Person:** {style.person}")
    if style.formality:
        lines.append(f"- **Formality:** {style.formality}")
    if style.section_ordering:
        lines.append(f"- **Section ordering:** {' → '.join(style.section_ordering)}")
    if style.avg_section_count:
        lines.append(f"- **Average section count:** {style.avg_section_count}")
    if style.abstract_pattern:
        lines.append(f"- **Abstract pattern:** {style.abstract_pattern}")
    if style.paragraph_style:
        lines.append(f"- **Paragraph style:** {style.paragraph_style}")
    if style.notation_conventions:
        lines.append("- **Notation conventions:**")
        for conv in style.notation_conventions:
            lines.append(f"  - {conv}")
    if style.notes:
        lines.extend(["", "### Additional Style Observations", "", style.notes])

    return ["\n".join(lines)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
