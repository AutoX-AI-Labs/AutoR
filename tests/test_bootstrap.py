from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.bootstrap import (
    BibEntry,
    BootstrapResult,
    CitationNeighborhood,
    CorpusManifest,
    PaperMetadata,
    ResearchProfile,
    StyleProfile,
    bootstrap_profile_exists,
    extract_tex_metadata,
    format_corpus_for_prompt,
    format_profile_for_prompt,
    load_bootstrap_summary,
    load_citation_neighborhood,
    load_corpus_manifest,
    load_research_profile,
    load_style_profile,
    parse_bibtex,
    save_bootstrap_result,
    scan_corpus,
)
from src.utils import build_run_paths, ensure_run_layout


def _make_run(tmp: Path) -> "src.utils.RunPaths":
    from src.utils import build_run_paths, ensure_run_layout
    run_root = tmp / "test_run"
    paths = build_run_paths(run_root)
    ensure_run_layout(paths)
    return paths


# ---------------------------------------------------------------------------
# BibTeX parsing
# ---------------------------------------------------------------------------


class ParseBibtexTests(unittest.TestCase):
    def test_parse_single_entry(self) -> None:
        bib = """@article{vaswani2017attention,
  title={Attention Is All You Need},
  author={Vaswani, Ashish and Shazeer, Noam},
  journal={NeurIPS},
  year={2017}
}"""
        entries = parse_bibtex(bib)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].cite_key, "vaswani2017attention")
        self.assertEqual(entries[0].entry_type, "article")
        self.assertIn("Attention", entries[0].title)
        self.assertIn("Vaswani", entries[0].authors)
        self.assertEqual(entries[0].year, "2017")
        self.assertEqual(entries[0].venue, "NeurIPS")

    def test_parse_inproceedings(self) -> None:
        bib = """@inproceedings{brown2020gpt3,
  title={Language Models are Few-Shot Learners},
  author={Brown, Tom and Mann, Benjamin},
  booktitle={NeurIPS},
  year={2020}
}"""
        entries = parse_bibtex(bib)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].venue, "NeurIPS")

    def test_parse_multiple_entries(self) -> None:
        bib = """@article{a, title={Paper A}, author={Alice}, year={2020}, journal={ICML}
}
@article{b, title={Paper B}, author={Bob}, year={2021}, journal={NeurIPS}
}"""
        entries = parse_bibtex(bib)
        self.assertEqual(len(entries), 2)

    def test_parse_empty_returns_empty(self) -> None:
        self.assertEqual(parse_bibtex(""), [])
        self.assertEqual(parse_bibtex("no bibtex here"), [])

    def test_parse_with_doi(self) -> None:
        bib = """@article{foo,
  title={Foo},
  author={Bar},
  doi={10.1234/foo},
  year={2022},
  journal={Nature}
}"""
        entries = parse_bibtex(bib)
        self.assertEqual(entries[0].doi, "10.1234/foo")


# ---------------------------------------------------------------------------
# TeX extraction
# ---------------------------------------------------------------------------


class ExtractTexMetadataTests(unittest.TestCase):
    def test_extract_title_and_abstract(self) -> None:
        tex = r"""
\documentclass{article}
\title{My Great Paper}
\begin{document}
\begin{abstract}
This paper does great things.
\end{abstract}
\section{Introduction}
Hello world.
\section{Method}
We do stuff.
\end{document}
"""
        title, abstract, sections, body = extract_tex_metadata(tex)
        self.assertEqual(title, "My Great Paper")
        self.assertIn("great things", abstract)
        self.assertEqual(sections, ["Introduction", "Method"])
        self.assertNotIn("documentclass", body)

    def test_no_abstract(self) -> None:
        tex = r"\title{Simple}\begin{document}\section{Intro}Content\end{document}"
        title, abstract, sections, body = extract_tex_metadata(tex)
        self.assertEqual(title, "Simple")
        self.assertEqual(abstract, "")

    def test_empty_tex(self) -> None:
        title, abstract, sections, body = extract_tex_metadata("")
        self.assertEqual(title, "")
        self.assertEqual(abstract, "")
        self.assertEqual(sections, [])


# ---------------------------------------------------------------------------
# Corpus scanning
# ---------------------------------------------------------------------------


class ScanCorpusTests(unittest.TestCase):
    def test_scan_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = scan_corpus(Path(tmp))
            self.assertEqual(len(manifest.papers), 0)
            self.assertEqual(manifest.files_processed, 0)

    def test_scan_with_tex_and_bib(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "paper.tex").write_text(
                r"\title{Test}\begin{document}\section{Intro}Hello\end{document}",
                encoding="utf-8",
            )
            (tmp_path / "refs.bib").write_text(
                '@article{foo, title={Foo}, author={Alice}, year={2020}, journal={ICML}\n}',
                encoding="utf-8",
            )
            manifest = scan_corpus(tmp_path)
            types = {p.file_type for p in manifest.papers}
            self.assertIn("tex", types)
            self.assertIn("bib", types)
            # .tex paper should have extracted title
            tex_paper = next(p for p in manifest.papers if p.file_type == "tex")
            self.assertEqual(tex_paper.title, "Test")

    def test_scan_bib_has_parsed_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "refs.bib").write_text(
                '@article{a, title={Paper A}, author={Alice}, year={2020}, journal={ICML}\n}\n'
                '@article{b, title={Paper B}, author={Bob}, year={2021}, journal={NeurIPS}\n}',
                encoding="utf-8",
            )
            manifest = scan_corpus(tmp_path)
            bib_paper = manifest.papers[0]
            self.assertEqual(len(bib_paper.bib_entries), 2)
            self.assertEqual(manifest.stats["unique_references"], 2)

    def test_scan_nonexistent_dir_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            scan_corpus(Path("/nonexistent/path"))

    def test_scan_file_instead_of_dir_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "file.txt"
            f.write_text("hello", encoding="utf-8")
            with self.assertRaises(NotADirectoryError):
                scan_corpus(f)

    def test_scan_nested_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "subdir"
            sub.mkdir()
            (sub / "paper.tex").write_text(
                r"\begin{document}Content\end{document}", encoding="utf-8",
            )
            manifest = scan_corpus(Path(tmp))
            self.assertEqual(len(manifest.papers), 1)

    def test_manifest_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "a.tex").write_text(r"\begin{document}A\end{document}", encoding="utf-8")
            (tmp_path / "b.md").write_text("# Notes", encoding="utf-8")
            manifest = scan_corpus(tmp_path)
            stats = manifest.stats
            self.assertEqual(stats["total_papers"], 2)
            self.assertIn("tex", stats["by_type"])
            self.assertIn("notes", stats["by_type"])


# ---------------------------------------------------------------------------
# Corpus prompt formatting
# ---------------------------------------------------------------------------


class FormatCorpusTests(unittest.TestCase):
    def test_empty_manifest(self) -> None:
        manifest = CorpusManifest(
            corpus_path="/tmp", scanned_at="now",
            total_files_found=0, files_processed=0, files_skipped=0,
        )
        result = format_corpus_for_prompt(manifest)
        self.assertIn("No corpus files", result)

    def test_format_includes_overview(self) -> None:
        manifest = CorpusManifest(
            corpus_path="/tmp", scanned_at="now",
            total_files_found=2, files_processed=2, files_skipped=0,
            papers=[
                PaperMetadata(
                    source_path="/tmp/a.tex", file_type="tex",
                    title="Paper A", abstract="Abstract A",
                    sections=["Intro", "Method"], extracted_text="body", char_count=100,
                ),
                PaperMetadata(
                    source_path="/tmp/refs.bib", file_type="bib",
                    bib_entries=[BibEntry(cite_key="x", entry_type="article", title="X", authors="Y", year="2020", venue="ICML")],
                    extracted_text="@article{...}", char_count=50,
                ),
            ],
        )
        result = format_corpus_for_prompt(manifest)
        self.assertIn("Corpus Overview", result)
        self.assertIn("Paper A", result)
        self.assertIn("Pre-Parsed Bibliography", result)

    def test_bib_entries_shown_structured(self) -> None:
        manifest = CorpusManifest(
            corpus_path="/tmp", scanned_at="now",
            total_files_found=1, files_processed=1, files_skipped=0,
            papers=[
                PaperMetadata(
                    source_path="/tmp/refs.bib", file_type="bib",
                    bib_entries=[BibEntry(cite_key="key1", entry_type="article", title="Title One", authors="Author A", year="2021", venue="NeurIPS")],
                    extracted_text="raw", char_count=10,
                ),
            ],
        )
        result = format_corpus_for_prompt(manifest)
        self.assertIn("[key1]", result)
        self.assertIn("Title One", result)
        self.assertIn("Author A", result)


# ---------------------------------------------------------------------------
# Save / Load profile
# ---------------------------------------------------------------------------


class SaveLoadProfileTests(unittest.TestCase):
    def _sample_result(self) -> BootstrapResult:
        return BootstrapResult(
            profile=ResearchProfile(
                themes=["NLP", "reasoning"],
                terminology=["chain-of-thought", "in-context learning"],
                methods=["fine-tuning", "prompting"],
                venues=["NeurIPS", "ACL"],
                confidence="high",
                summary="Researcher focused on NLP reasoning.",
            ),
            citation_neighborhood=CitationNeighborhood(
                frequently_cited=[{"title": "Attention Is All You Need", "authors": "Vaswani et al.", "year": "2017"}],
                related_authors=["Wei et al.", "Brown et al."],
                key_venues=["NeurIPS", "ICML"],
                seed_papers=[{"title": "Chain-of-Thought Prompting", "authors": "Wei et al.", "year": "2022", "why": "foundational to their method"}],
            ),
            style_profile=StyleProfile(
                voice="passive",
                person="first_plural",
                formality="formal",
                avg_section_count=7,
                section_ordering=["Introduction", "Related Work", "Method", "Experiments", "Conclusion"],
                abstract_pattern="problem-method-result",
                notation_conventions=["boldface for vectors"],
                paragraph_style="topic-sentence-first",
                notes="Uses formal academic tone throughout.",
            ),
            summary="NLP researcher focused on reasoning with LLMs.",
            corpus_manifest=CorpusManifest(
                corpus_path="/tmp/papers", scanned_at="2026-04-04T10:00:00",
                total_files_found=5, files_processed=5, files_skipped=0,
            ),
        )

    def test_save_and_load_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_run(Path(tmp))
            save_bootstrap_result(paths, self._sample_result())

            self.assertTrue((paths.profile_dir / "research_profile.json").exists())
            self.assertTrue((paths.profile_dir / "citation_neighborhood.json").exists())
            self.assertTrue((paths.profile_dir / "style_profile.json").exists())
            self.assertTrue((paths.profile_dir / "style_notes.md").exists())
            self.assertTrue((paths.profile_dir / "bootstrap_summary.md").exists())
            self.assertTrue((paths.profile_dir / "corpus_manifest.json").exists())

            profile = load_research_profile(paths)
            self.assertIn("NLP", profile.themes)
            self.assertEqual(profile.confidence, "high")

            cn = load_citation_neighborhood(paths)
            self.assertEqual(len(cn.seed_papers), 1)

            style = load_style_profile(paths)
            self.assertEqual(style.voice, "passive")
            self.assertEqual(style.person, "first_plural")

            summary = load_bootstrap_summary(paths)
            self.assertIn("NLP", summary)

            cm = load_corpus_manifest(paths)
            self.assertEqual(cm.files_processed, 5)

    def test_bootstrap_profile_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_run(Path(tmp))
            self.assertFalse(bootstrap_profile_exists(paths))
            save_bootstrap_result(paths, self._sample_result())
            self.assertTrue(bootstrap_profile_exists(paths))

    def test_load_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_run(Path(tmp))
            self.assertIsNone(load_research_profile(paths))
            self.assertIsNone(load_citation_neighborhood(paths))
            self.assertIsNone(load_style_profile(paths))
            self.assertIsNone(load_bootstrap_summary(paths))
            self.assertIsNone(load_corpus_manifest(paths))


# ---------------------------------------------------------------------------
# Stage-specific prompt formatting
# ---------------------------------------------------------------------------


class FormatProfileForPromptTests(unittest.TestCase):
    def _setup(self, tmp: Path) -> "src.utils.RunPaths":
        paths = _make_run(tmp)
        save_bootstrap_result(paths, SaveLoadProfileTests._sample_result(self))
        return paths

    def test_no_profile_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_run(Path(tmp))
            self.assertIsNone(format_profile_for_prompt(paths))

    def test_default_includes_all_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._setup(Path(tmp))
            text = format_profile_for_prompt(paths)
            self.assertIn("Researcher Profile Summary", text)
            self.assertIn("Research Profile", text)

    def test_stage01_gets_expanded_citations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._setup(Path(tmp))
            text = format_profile_for_prompt(paths, stage_slug="01_literature_survey")
            self.assertIn("Seed papers for literature search", text)
            self.assertIn("Chain-of-Thought Prompting", text)

    def test_stage07_gets_expanded_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._setup(Path(tmp))
            text = format_profile_for_prompt(paths, stage_slug="07_writing")
            self.assertIn("Writing Style Profile (detailed)", text)
            self.assertIn("passive", text)
            self.assertIn("first_plural", text)
            self.assertIn("topic-sentence-first", text)

    def test_other_stage_gets_compact_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._setup(Path(tmp))
            text = format_profile_for_prompt(paths, stage_slug="03_study_design")
            self.assertIn("Writing Style (compact)", text)
            self.assertNotIn("Writing Style Profile (detailed)", text)


if __name__ == "__main__":
    unittest.main()
