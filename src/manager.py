from __future__ import annotations

from datetime import datetime
import shutil
import sys
from pathlib import Path
from typing import TextIO

from .manifest import (
    ensure_run_manifest,
    format_manifest_status,
    initialize_run_manifest,
    load_run_manifest,
    mark_stage_approved_manifest,
    mark_stage_failed_manifest,
    mark_stage_human_review_manifest,
    mark_stage_running_manifest,
    sync_stage_session_id,
    update_manifest_run_status,
)
from .operator import ClaudeOperator
from .terminal_ui import TerminalUI
from .writing_manifest import build_writing_manifest, format_manifest_for_prompt
from .utils import (
    STAGES,
    RunPaths,
    StageSpec,
    append_approved_stage_summary,
    approved_stage_numbers,
    append_log_entry,
    build_continuation_prompt,
    build_prompt,
    build_run_paths,
    canonicalize_stage_markdown,
    create_run_root,
    ensure_run_config,
    ensure_run_layout,
    format_stage_template,
    format_venue_for_prompt,
    filtered_approved_memory,
    initialize_memory,
    initialize_run_config,
    load_prompt_template,
    mark_stage_execution_started,
    parse_refinement_suggestions,
    read_text,
    truncate_text,
    validate_stage_artifacts,
    validate_stage_markdown,
    write_text,
)


class ResearchManager:
    def __init__(
        self,
        project_root: Path,
        runs_dir: Path,
        operator: ClaudeOperator,
        output_stream: TextIO = sys.stdout,
        ui: TerminalUI | None = None,
    ) -> None:
        self.project_root = project_root
        self.runs_dir = runs_dir
        self.operator = operator
        self.prompt_dir = self.project_root / "src" / "prompts"
        self.output_stream = output_stream
        self.ui = ui or TerminalUI(output_stream=output_stream)
        self._redo_start_stage: StageSpec | None = None

    def run(self, user_goal: str, venue: str | None = None) -> bool:
        paths = self._create_run(user_goal, venue=venue)
        self.ui.show_run_started(paths.run_root.as_posix(), self.operator.model, venue or "default")
        return self._run_from_paths(paths)

    def resume_run(
        self,
        run_root: Path,
        start_stage: StageSpec | None = None,
        venue: str | None = None,
    ) -> bool:
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        config = ensure_run_config(paths, model=self.operator.model, venue=venue)
        ensure_run_manifest(paths)
        if not paths.user_input.exists():
            raise FileNotFoundError(f"Missing user_input.txt in run: {run_root}")
        if not paths.memory.exists():
            raise FileNotFoundError(f"Missing memory.md in run: {run_root}")

        append_log_entry(
            paths.logs,
            "run_resume",
            f"Resumed run at: {paths.run_root}"
            + (f"\nRequested start stage: {start_stage.stage_title}" if start_stage else "")
            + f"\nVenue: {config['venue']}",
        )
        self.ui.show_run_started(
            paths.run_root.as_posix(),
            self.operator.model,
            config["venue"],
            resumed=True,
        )
        if start_stage:
            self.ui.show_status(f"Restarting from {start_stage.stage_title}", level="warn")
        return self._run_from_paths(paths, start_stage=start_stage)

    def _run_from_paths(self, paths: RunPaths, start_stage: StageSpec | None = None) -> bool:
        stages_to_run = self._select_stages_for_run(paths, start_stage)

        for stage in stages_to_run:
            approved = self._run_stage(paths, stage)
            if not approved:
                append_log_entry(
                    paths.logs,
                    "run_aborted",
                    f"Run aborted during {stage.stage_title}.",
                )
                update_manifest_run_status(
                    paths,
                    run_status="cancelled",
                    last_event="run.cancelled",
                    current_stage_slug=stage.slug,
                )
                self._print("Run aborted.")
                return False

        append_log_entry(paths.logs, "run_complete", "All stages approved.")
        update_manifest_run_status(
            paths,
            run_status="completed",
            last_event="run.completed",
            current_stage_slug=None,
            completed_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._print("All stages approved. Run complete.")
        return True

    def _create_run(self, user_goal: str, venue: str | None = None) -> RunPaths:
        run_root = create_run_root(self.runs_dir)
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        write_text(paths.user_input, user_goal)
        initialize_memory(paths, user_goal)
        config = initialize_run_config(paths, model=self.operator.model, venue=venue)
        initialize_run_manifest(paths)
        append_log_entry(paths.logs, "run_start", f"Run root: {paths.run_root}")
        append_log_entry(
            paths.logs,
            "run_config",
            f"Model: {config['model']}\nVenue: {config['venue']}",
        )
        return paths

    def _select_stages_for_run(
        self,
        paths: RunPaths,
        start_stage: StageSpec | None,
    ) -> list[StageSpec]:
        if start_stage is not None:
            return [stage for stage in STAGES if stage.number >= start_stage.number]

        manifest = ensure_run_manifest(paths)
        pending: list[StageSpec] = []
        for stage in STAGES:
            entry = next(entry for entry in manifest.stages if entry.slug == stage.slug)
            if entry.approved and entry.status == "approved":
                continue
            pending.append(stage)

        return pending

    def _run_stage(self, paths: RunPaths, stage: StageSpec) -> bool:
        attempt_no = 1
        revision_feedback: str | None = None
        continue_session = False
        mark_stage_execution_started(paths, stage)

        while True:
            mark_stage_running_manifest(paths, stage, attempt_no)
            self._print(f"\nRunning {stage.stage_title} (attempt {attempt_no})...")
            prompt = self._build_stage_prompt(paths, stage, revision_feedback, continue_session)
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} prompt",
                prompt,
            )

            result = self.operator.run_stage(
                stage,
                prompt,
                paths,
                attempt_no,
                continue_session=continue_session,
            )
            if result.session_id:
                sync_stage_session_id(paths, stage, result.session_id)
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} result",
                (
                    f"success: {result.success}\n"
                    f"exit_code: {result.exit_code}\n"
                    f"session_id: {result.session_id or '(unknown)'}\n"
                    f"stage_file_path: {result.stage_file_path}\n"
                    f"final_stage_file_path: {paths.stage_file(stage)}\n\n"
                    "stdout:\n"
                    f"{result.stdout or '(empty)'}\n\n"
                    "stderr:\n"
                    f"{result.stderr or '(empty)'}"
                ),
            )

            if not result.stage_file_path.exists():
                self.ui.show_status(
                    f"Stage summary draft missing for {stage.stage_title}. Running repair attempt...",
                    level="warn",
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} repair_triggered",
                    "Primary attempt did not produce stage summary draft. Triggering repair pass.",
                )
                repair_result = self.operator.repair_stage_summary(
                    stage=stage,
                    original_prompt=prompt,
                    original_result=result,
                    paths=paths,
                    attempt_no=attempt_no,
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} repair_result",
                    (
                        f"success: {repair_result.success}\n"
                        f"exit_code: {repair_result.exit_code}\n"
                        f"stage_file_path: {repair_result.stage_file_path}\n\n"
                        "stdout:\n"
                        f"{repair_result.stdout or '(empty)'}\n\n"
                        "stderr:\n"
                        f"{repair_result.stderr or '(empty)'}"
                    ),
                )
                result = repair_result

            if not result.stage_file_path.exists():
                mark_stage_failed_manifest(paths, stage, "stage_summary_missing")
                fallback_text = "\n\n".join(
                    part for part in [result.stdout, result.stderr] if part
                )
                result = self._materialize_missing_stage_draft(
                    paths=paths,
                    stage=stage,
                    attempt_no=attempt_no,
                    source="primary attempt and repair",
                    fallback_text=fallback_text,
                )

            stage_markdown = read_text(result.stage_file_path)
            validation_errors = validate_stage_markdown(stage_markdown, stage=stage, paths=paths) + validate_stage_artifacts(stage, paths)
            if validation_errors:
                mark_stage_failed_manifest(paths, stage, "; ".join(validation_errors))
                self._print(
                    f"Stage summary for {stage.stage_title} was incomplete. Running repair attempt..."
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} validation_failed",
                    "\n".join(validation_errors),
                )
                repair_result = self.operator.repair_stage_summary(
                    stage=stage,
                    original_prompt=prompt,
                    original_result=result,
                    paths=paths,
                    attempt_no=attempt_no,
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} repair_result",
                    (
                        f"success: {repair_result.success}\n"
                        f"exit_code: {repair_result.exit_code}\n"
                        f"stage_file_path: {repair_result.stage_file_path}\n\n"
                        "stdout:\n"
                        f"{repair_result.stdout or '(empty)'}\n\n"
                        "stderr:\n"
                        f"{repair_result.stderr or '(empty)'}"
                    ),
                )

                if not repair_result.stage_file_path.exists():
                    fallback_text = "\n\n".join(
                        part
                        for part in [result.stdout, result.stderr, repair_result.stdout, repair_result.stderr]
                        if part
                    )
                    repair_result = self._materialize_missing_stage_draft(
                        paths=paths,
                        stage=stage,
                        attempt_no=attempt_no,
                        source="validation repair",
                        fallback_text=fallback_text,
                    )

                stage_markdown = read_text(repair_result.stage_file_path)
                validation_errors = validate_stage_markdown(stage_markdown, stage=stage, paths=paths) + validate_stage_artifacts(stage, paths)
                if validation_errors:
                    self.ui.show_status(
                        f"Repair output for {stage.stage_title} is still incomplete. Normalizing locally...",
                        level="warn",
                    )
                    normalized_markdown = canonicalize_stage_markdown(
                        stage=stage,
                        memory_text=read_text(paths.memory),
                        markdown=stage_markdown,
                        fallback_text="\n\n".join(
                            part for part in [result.stdout, result.stderr, repair_result.stdout, repair_result.stderr] if part
                        ),
                    )
                    write_text(repair_result.stage_file_path, normalized_markdown)
                    append_log_entry(
                        paths.logs,
                        f"{stage.slug} attempt {attempt_no} local_normalization",
                        (
                            "Applied local stage markdown normalization after repair remained invalid.\n\n"
                            "Previous validation errors:\n"
                            + "\n".join(f"- {problem}" for problem in validation_errors)
                            + "\n\nNormalized markdown preview:\n"
                            + truncate_text(normalized_markdown, max_chars=6000)
                        ),
                    )

                    stage_markdown = read_text(repair_result.stage_file_path)
                    validation_errors = validate_stage_markdown(stage_markdown, stage=stage, paths=paths) + validate_stage_artifacts(stage, paths)
                    if validation_errors:
                        append_log_entry(
                            paths.logs,
                            f"{stage.slug} attempt {attempt_no} local_normalization_failed",
                            (
                                "Local normalization remained invalid. Re-running current stage from scratch.\n\n"
                                + "\n".join(f"- {problem}" for problem in validation_errors)
                            ),
                        )
                        self._print(
                            f"Local normalization for {stage.stage_title} is still incomplete. Re-running the stage..."
                        )
                        revision_feedback = (
                            "Continue the current stage conversation and fix the invalid stage summary. "
                            "Keep all correct work already completed, but produce a fully complete stage summary "
                            "with no placeholder markers and ensure every required section is substantively filled."
                        )
                        continue_session = True
                        attempt_no += 1
                        continue

                result = repair_result

            final_stage_path = paths.stage_file(stage)
            shutil.copyfile(result.stage_file_path, final_stage_path)
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} promoted",
                (
                    "Promoted validated stage summary draft to final stage file.\n"
                    f"draft: {result.stage_file_path}\n"
                    f"final: {final_stage_path}"
                ),
            )
            stage_markdown = read_text(final_stage_path)
            mark_stage_human_review_manifest(
                paths,
                stage,
                attempt_no,
                self._stage_file_paths(stage_markdown),
            )

            suggestions = parse_refinement_suggestions(stage_markdown)
            self._display_stage_output(stage, stage_markdown)
            choice = self._ask_choice(suggestions)
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} user_choice",
                f"choice: {choice}",
            )

            if choice in {"1", "2", "3"}:
                selected = suggestions[int(choice) - 1]
                revision_feedback = (
                    "Continue the current stage conversation and improve the existing work. "
                    "Do not discard correct completed parts. Address this refinement request:\n"
                    f"{selected}"
                )
                continue_session = True
                attempt_no += 1
                continue

            if choice == "4":
                custom_feedback = self._read_multiline_feedback()
                revision_feedback = (
                    "Continue the current stage conversation and improve the existing work. "
                    "Preserve correct completed parts unless the feedback requires changing them. "
                    "Address this user feedback:\n"
                    f"{custom_feedback}"
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} custom_feedback",
                    custom_feedback,
                )
                continue_session = True
                attempt_no += 1
                continue

            if choice == "5":
                final_stage_path = paths.stage_file(stage)
                shutil.copyfile(result.stage_file_path, final_stage_path)
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} promoted",
                    (
                        "Promoted validated stage summary draft to final stage file after approval.\n"
                        f"draft: {result.stage_file_path}\n"
                        f"final: {final_stage_path}"
                    ),
                )
                append_approved_stage_summary(paths.memory, stage, stage_markdown)
                mark_stage_approved_manifest(
                    paths,
                    stage,
                    attempt_no,
                    self._stage_file_paths(stage_markdown),
                )
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} approved",
                    "Stage approved and appended to memory.",
                )
                self.ui.show_status(f"Approved {stage.stage_title}.", level="success")
                return True

            if choice == "6":
                update_manifest_run_status(
                    paths,
                    run_status="cancelled",
                    last_event="run.cancelled",
                    current_stage_slug=stage.slug,
                )
                return False

    def _build_stage_prompt(
        self,
        paths: RunPaths,
        stage: StageSpec,
        revision_feedback: str | None,
        continue_session: bool,
    ) -> str:
        template = load_prompt_template(self.prompt_dir, stage)
        stage_template = format_stage_template(template, stage, paths)
        stage_template = (
            stage_template.rstrip()
            + "\n\n## Run Configuration\n\n"
            + format_venue_for_prompt(paths)
            + "\n"
        )
        if stage.slug == "07_writing":
            manifest = build_writing_manifest(paths)
            stage_template = (
                stage_template.rstrip()
                + "\n\n## Writing Manifest\n\n"
                + format_manifest_for_prompt(manifest)
                + "\n"
            )
        approved_memory = read_text(paths.memory)
        if self._redo_start_stage is not None and stage.number >= self._redo_start_stage.number:
            approved_memory = filtered_approved_memory(approved_memory, max_stage_number=stage.number - 1)
        if continue_session:
            return build_continuation_prompt(stage, stage_template, paths, approved_memory, revision_feedback)

        user_request = read_text(paths.user_input)
        return build_prompt(stage, stage_template, user_request, approved_memory, revision_feedback)

    def _display_stage_output(self, stage: StageSpec, markdown: str) -> None:
        self.ui.show_stage_document(stage.stage_title, markdown)

    def _ask_choice(self, suggestions: list[str]) -> str:
        return self.ui.choose_action(suggestions)

    def _read_multiline_feedback(self) -> str:
        return self.ui.read_multiline_feedback()

    def _materialize_missing_stage_draft(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        source: str,
        fallback_text: str,
    ):
        draft_path = paths.stage_tmp_file(stage)
        normalized_markdown = canonicalize_stage_markdown(
            stage=stage,
            memory_text=read_text(paths.memory),
            markdown="",
            fallback_text=(
                f"AutoR generated this local fallback stage draft because the {source} "
                "did not produce a stage summary file.\n\n"
                + (fallback_text.strip() if fallback_text.strip() else "No stdout or stderr was captured.")
            ),
        )
        write_text(draft_path, normalized_markdown)
        append_log_entry(
            paths.logs,
            f"{stage.slug} attempt {attempt_no} local_fallback_draft",
            (
                f"Generated a local fallback stage draft after missing stage summary during {source}.\n"
                f"draft: {draft_path}\n\n"
                "Fallback markdown preview:\n"
                f"{truncate_text(normalized_markdown, max_chars=4000)}"
            ),
        )
        self.ui.show_status(
            f"{stage.stage_title} did not produce a stage summary file during {source}. "
            "Generated a local fallback draft and continuing recovery...",
            level="warn",
        )
        return type("FallbackResult", (), {"stage_file_path": draft_path, "stdout": fallback_text, "stderr": ""})()

    def describe_run_status(self, run_root: Path) -> str:
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        manifest = load_run_manifest(paths.run_manifest)
        if manifest is None:
            raise RuntimeError(f"Could not load run manifest from {paths.run_manifest}")
        return format_manifest_status(manifest)

    def _stage_file_paths(self, stage_markdown: str) -> list[str]:
        from .utils import extract_path_references

        return extract_path_references(stage_markdown)

    def _print(self, text: str) -> None:
        self.ui.write(text.rstrip() + "\n")
