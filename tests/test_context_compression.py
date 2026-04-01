from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.utils import (
    STAGES,
    RunPaths,
    StageSpec,
    append_approved_stage_summary,
    build_continuation_prompt,
    build_run_paths,
    ensure_run_layout,
    initialize_memory,
    read_text,
    render_approved_stage_entry,
    render_compact_stage_entry,
    write_text,
    _truncate_section,
)


STAGE_01 = next(s for s in STAGES if s.slug == "01_literature_survey")
STAGE_04 = next(s for s in STAGES if s.slug == "04_implementation")
STAGE_05 = next(s for s in STAGES if s.slug == "05_experimentation")
STAGE_06 = next(s for s in STAGES if s.slug == "06_analysis")


def _make_stage_markdown(stage: StageSpec, key_results_lines: int = 5) -> str:
    key_results = "\n".join(f"- Result line {i}" for i in range(1, key_results_lines + 1))
    return (
        f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
        "## Objective\n"
        f"Test objective for {stage.display_name}.\n\n"
        "## Previously Approved Stage Summaries\n"
        "_None yet._\n\n"
        "## What I Did\n"
        f"Implemented {stage.display_name} with care.\n\n"
        "## Key Results\n"
        f"{key_results}\n\n"
        "## Files Produced\n"
        "- `workspace/test.txt`\n\n"
        "## Suggestions for Refinement\n"
        "1. Suggestion A\n"
        "2. Suggestion B\n"
        "3. Suggestion C\n\n"
        "## Your Options\n"
        "1. Use suggestion 1\n"
        "2. Use suggestion 2\n"
        "3. Use suggestion 3\n"
        "4. Refine with your own feedback\n"
        "5. Approve and continue\n"
        "6. Abort\n"
    )


class TestTruncateSection(unittest.TestCase):
    def test_short_text_unchanged(self) -> None:
        text = "Short text."
        self.assertEqual(_truncate_section(text, 100), text)

    def test_long_text_truncated(self) -> None:
        text = "A" * 500
        result = _truncate_section(text, 100)
        self.assertIn("...(see workspace files for full details)", result)
        self.assertLess(len(result), 200)

    def test_truncates_at_paragraph_boundary(self) -> None:
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three is very long " + "x" * 200
        result = _truncate_section(text, 50)
        self.assertIn("...(see workspace files", result)


class TestCompactStageEntry(unittest.TestCase):
    def test_short_content_not_truncated(self) -> None:
        md = _make_stage_markdown(STAGE_01, key_results_lines=3)
        full = render_approved_stage_entry(STAGE_01, md)
        compact = render_compact_stage_entry(STAGE_01, md)
        self.assertEqual(full, compact)

    def test_long_key_results_truncated(self) -> None:
        md = _make_stage_markdown(STAGE_04, key_results_lines=200)
        compact = render_compact_stage_entry(STAGE_04, md, max_section_chars=500)
        self.assertIn("...(see workspace files for full details)", compact)
        self.assertLess(len(compact), len(render_approved_stage_entry(STAGE_04, md)))

    def test_compact_preserves_objective_and_files(self) -> None:
        md = _make_stage_markdown(STAGE_05, key_results_lines=200)
        compact = render_compact_stage_entry(STAGE_05, md, max_section_chars=500)
        self.assertIn("Test objective for", compact)
        self.assertIn("workspace/test.txt", compact)


class TestDuplicatePrevention(unittest.TestCase):
    def test_same_stage_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "test goal")
            initialize_memory(paths, "test goal")

            md = _make_stage_markdown(STAGE_01)
            append_approved_stage_summary(paths.memory, STAGE_01, md)
            append_approved_stage_summary(paths.memory, STAGE_01, md)

            memory = read_text(paths.memory)
            count = memory.count(f"### {STAGE_01.stage_title}")
            self.assertEqual(count, 1, f"Stage heading appeared {count} times, expected 1")

    def test_replace_updates_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "test goal")
            initialize_memory(paths, "test goal")

            md_v1 = _make_stage_markdown(STAGE_01, key_results_lines=2)
            append_approved_stage_summary(paths.memory, STAGE_01, md_v1)

            md_v2 = md_v1.replace("Result line 1", "Updated result")
            append_approved_stage_summary(paths.memory, STAGE_01, md_v2)

            memory = read_text(paths.memory)
            self.assertIn("Updated result", memory)
            self.assertEqual(memory.count(f"### {STAGE_01.stage_title}"), 1)

    def test_multiple_stages_coexist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "test goal")
            initialize_memory(paths, "test goal")

            for stage in [STAGE_01, STAGE_04, STAGE_05]:
                md = _make_stage_markdown(stage)
                append_approved_stage_summary(paths.memory, stage, md)

            memory = read_text(paths.memory)
            self.assertIn(f"### {STAGE_01.stage_title}", memory)
            self.assertIn(f"### {STAGE_04.stage_title}", memory)
            self.assertIn(f"### {STAGE_05.stage_title}", memory)


class TestInlineContext(unittest.TestCase):
    def test_continuation_prompt_contains_user_goal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "My research goal about GNN")
            initialize_memory(paths, "My research goal about GNN")

            prompt = build_continuation_prompt(STAGE_01, "template", paths, "fix it")
            self.assertIn("My research goal about GNN", prompt)

    def test_continuation_prompt_contains_current_objective(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "test goal")
            initialize_memory(paths, "test goal")

            md = _make_stage_markdown(STAGE_05)
            write_text(paths.stage_file(STAGE_05), md)

            prompt = build_continuation_prompt(STAGE_05, "template", paths, "improve")
            self.assertIn("Current Stage Objective", prompt)
            self.assertIn("Test objective for", prompt)

    def test_continuation_prompt_contains_recent_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "test goal")
            initialize_memory(paths, "test goal")

            for stage in [STAGE_01, STAGE_04, STAGE_05]:
                md = _make_stage_markdown(stage)
                append_approved_stage_summary(paths.memory, stage, md)

            prompt = build_continuation_prompt(STAGE_06, "template", paths, "analyze")
            self.assertIn("Recent Approved Context", prompt)
            # Should contain the 2 most recent stages before 06 (04 and 05)
            self.assertIn(STAGE_04.stage_title, prompt)
            self.assertIn(STAGE_05.stage_title, prompt)


class TestMemorySizeReduction(unittest.TestCase):
    def test_compact_memory_smaller_than_full(self) -> None:
        """Using compact entries should produce a smaller memory.md."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "test goal")
            initialize_memory(paths, "test goal")

            # Append stages with large key_results
            for stage in STAGES[:6]:
                md = _make_stage_markdown(stage, key_results_lines=150)
                append_approved_stage_summary(paths.memory, stage, md)

            compact_size = len(read_text(paths.memory))

            # Compare to what full entries would produce
            initialize_memory(paths, "test goal")
            for stage in STAGES[:6]:
                md = _make_stage_markdown(stage, key_results_lines=150)
                current = read_text(paths.memory)
                entry = render_approved_stage_entry(stage, md)
                if "_None yet._" in current:
                    updated = current.replace("_None yet._", entry, 1)
                else:
                    updated = current.rstrip() + "\n\n" + entry + "\n"
                write_text(paths.memory, updated)

            full_size = len(read_text(paths.memory))

            self.assertLess(compact_size, full_size)


if __name__ == "__main__":
    unittest.main()
