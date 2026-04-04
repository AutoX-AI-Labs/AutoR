from __future__ import annotations

from datetime import datetime
import shutil
import sys
from pathlib import Path
from typing import TextIO

from .bootstrap import (
    bootstrap_profile_exists,
    format_corpus_for_prompt,
    format_corpus_stats_for_log,
    format_profile_for_prompt,
    save_bootstrap_result,
    scan_corpus,
)
from .intake import (
    IntakeContext,
    ResourceEntry,
    format_intake_for_prompt,
    format_resources_for_intake_prompt,
    ingest_resources,
    load_intake_context,
    save_intake_context
)
from .artifact_index import format_artifact_index_for_prompt, write_artifact_index
from .experiment_manifest import format_experiment_manifest_for_prompt, write_experiment_manifest
from .manifest import (
    ensure_run_manifest,
    format_manifest_status,
    initialize_run_manifest,
    load_run_manifest,
    mark_stage_approved_manifest,
    mark_stage_failed_manifest,
    mark_stage_human_review_manifest,
    mark_stage_running_manifest,
    rebuild_memory_from_manifest,
    rollback_to_stage,
    sync_stage_session_id,
    update_manifest_run_status,
)
from .operator import ClaudeOperator
from .platform.foundry import generate_paper_package, generate_release_package
from .writing_manifest import build_writing_manifest, format_manifest_for_prompt
from .utils import (
    INTAKE_STAGE,
    STAGES,
    RunPaths,
    StageSpec,
    append_approved_stage_summary,
    approved_stage_numbers,
    append_log_entry,
    build_handoff_context,
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
    required_stage_output_template,
    truncate_text,
    validate_stage_artifacts,
    validate_stage_markdown,
    write_stage_handoff,
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

    def run(
        self,
        user_goal: str,
        venue: str | None = None,
        resources: list[ResourceEntry] | None = None,
        skip_intake: bool = False,
        paper_corpus: Path | None = None,
    ) -> bool:
        paths = self._create_run(user_goal, venue=venue, resources=resources)
        self.ui.show_run_started(paths.run_root.as_posix(), self.operator.model, venue or "default")

        # Run Claude-driven intake stage unless skipped
        if not skip_intake:
            intake_approved = self._run_intake(paths)
            if not intake_approved:
                append_log_entry(paths.logs, "run_aborted", "Run aborted during intake.")
                self.ui.show_status("Run aborted.", level="warn")
                return False

        # Run bootstrap from paper corpus if provided
        if paper_corpus is not None:
            bootstrap_approved = self._run_bootstrap(paths, paper_corpus)
            if not bootstrap_approved:
                append_log_entry(paths.logs, "run_aborted", "Run aborted during bootstrap.")
                self.ui.show_status("Run aborted.", level="warn")
                return False

        return self._run_from_paths(paths)

    def resume_run(
        self,
        run_root: Path,
        start_stage: StageSpec | None = None,
        rollback_stage: StageSpec | None = None,
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

        if rollback_stage is not None:
            self._print(self._format_rollback_preview(paths, rollback_stage))
            rollback_to_stage(paths, rollback_stage)
            start_stage = rollback_stage

        append_log_entry(
            paths.logs,
            "run_resume",
            f"Resumed run at: {paths.run_root}"
            + (f"\nRequested start stage: {start_stage.stage_title}" if start_stage else "")
            + (f"\nRequested rollback stage: {rollback_stage.stage_title}" if rollback_stage else "")
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

    def _create_run(
        self,
        user_goal: str,
        venue: str | None = None,
        resources: list[ResourceEntry] | None = None,
    ) -> RunPaths:
        run_root = create_run_root(self.runs_dir)
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        write_text(paths.user_input, user_goal)

        # Ingest any pre-provided resources into workspace
        intake_summary: str | None = None
        if resources:
            updated = ingest_resources(resources, paths)
            ctx = IntakeContext(goal=user_goal, original_goal=user_goal, resources=updated)
            save_intake_context(paths, ctx)
            intake_summary = format_intake_for_prompt(ctx)

        initialize_memory(paths, user_goal, intake_summary=intake_summary)
        config = initialize_run_config(paths, model=self.operator.model, venue=venue)
        initialize_run_manifest(paths)
        write_artifact_index(paths)
        write_experiment_manifest(paths)
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

    # ------------------------------------------------------------------
    # Intake stage (Claude-driven Socratic Q&A, runs before Stage 01)
    # ------------------------------------------------------------------

    def _run_intake(self, paths: RunPaths) -> bool:
        """Run the Claude-driven intake stage.

        Uses the same operator + approval loop pattern as ``_run_stage``
        so that Claude generates Socratic questions and the user refines
        via the standard suggestion / custom-feedback / approve mechanism.

        On approval the intake summary is saved to ``intake_context.json``
        and appended to run memory so all downstream stages can see it.
        """
        stage = INTAKE_STAGE

        # Skip if intake was already approved (e.g. on resume)
        intake_stage_file = paths.stage_file(stage)
        if intake_stage_file.exists():
            self.ui.show_status("Intake already approved, skipping.", level="info")
            return True

        attempt_no = 1
        revision_feedback: str | None = None
        continue_session = False
        mark_stage_execution_started(paths, stage)

        while True:
            self.ui.show_stage_start(stage.stage_title, attempt_no, continue_session)
            prompt = self._build_stage_prompt(paths, stage, revision_feedback, continue_session)
            append_log_entry(paths.logs, f"{stage.slug} attempt {attempt_no} prompt", prompt)

            result = self.operator.run_stage(stage, prompt, paths, attempt_no, continue_session=continue_session)
            append_log_entry(
                paths.logs,
                f"{stage.slug} attempt {attempt_no} result",
                (
                    f"success: {result.success}\n"
                    f"exit_code: {result.exit_code}\n"
                    f"session_id: {result.session_id or '(unknown)'}\n"
                    f"stage_file_path: {result.stage_file_path}\n\n"
                    "stdout:\n"
                    f"{result.stdout or '(empty)'}\n\n"
                    "stderr:\n"
                    f"{result.stderr or '(empty)'}"
                ),
            )

            # If no stage file was produced, try repair (same as regular stages)
            if not result.stage_file_path.exists():
                self.ui.show_status(
                    f"Stage summary draft missing for {stage.stage_title}. Running repair attempt...",
                    level="warn",
                )
                repair_result = self.operator.repair_stage_summary(
                    stage=stage, original_prompt=prompt,
                    original_result=result, paths=paths, attempt_no=attempt_no,
                )
                result = repair_result

            if not result.stage_file_path.exists():
                fallback_text = "\n\n".join(
                    part for part in [result.stdout, result.stderr] if part
                )
                result = self._materialize_missing_stage_draft(
                    paths=paths, stage=stage, attempt_no=attempt_no,
                    source="intake attempt and repair", fallback_text=fallback_text,
                )

            stage_markdown = read_text(result.stage_file_path)

            # Show output and let user choose (same approval loop as _run_stage)
            suggestions = parse_refinement_suggestions(stage_markdown)
            self._display_stage_output(stage, stage_markdown)
            choice = self._ask_choice(suggestions)
            append_log_entry(paths.logs, f"{stage.slug} attempt {attempt_no} user_choice", f"choice: {choice}")

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
                append_log_entry(paths.logs, f"{stage.slug} attempt {attempt_no} custom_feedback", custom_feedback)
                continue_session = True
                attempt_no += 1
                continue

            if choice == "5":
                # Promote and save intake context
                final_path = paths.stage_file(stage)
                shutil.copyfile(result.stage_file_path, final_path)
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} attempt {attempt_no} promoted",
                    f"Promoted intake summary.\ndraft: {result.stage_file_path}\nfinal: {final_path}",
                )
                self._save_intake_from_approved_stage(paths, stage_markdown)
                self.ui.show_status(f"Approved {stage.stage_title}.", level="success")
                return True

            if choice == "6":
                return False

    def _save_intake_from_approved_stage(self, paths: RunPaths, stage_markdown: str) -> None:
        """Persist the approved intake stage output into intake_context.json and memory."""
        existing_ctx = load_intake_context(paths)
        goal = read_text(paths.user_input).strip()

        # Merge: keep any pre-ingested resources, store the stage output as notes
        ctx = IntakeContext(
            goal=goal,
            original_goal=existing_ctx.original_goal if existing_ctx else goal,
            resources=existing_ctx.resources if existing_ctx else [],
            notes=stage_markdown,
        )
        save_intake_context(paths, ctx)

        # Append intake summary to memory so downstream stages see it
        intake_text = format_intake_for_prompt(ctx)
        if intake_text:
            append_approved_stage_summary(paths.memory, INTAKE_STAGE, stage_markdown)

    # ------------------------------------------------------------------
    # Bootstrap stage (paper corpus → researcher profile)
    # ------------------------------------------------------------------

    BOOTSTRAP_STAGE = StageSpec(number=-1, slug="bootstrap", display_name="Paper Corpus Bootstrap")

    def _run_bootstrap(self, paths: RunPaths, corpus_path: Path) -> bool:
        """Scan the user's paper corpus and run Claude to extract a researcher profile.

        Uses the same operator + approval loop so the user can review and refine
        the extracted profile before downstream stages use it as context.
        """
        stage = self.BOOTSTRAP_STAGE

        if bootstrap_profile_exists(paths):
            self.ui.show_status("Bootstrap profile already exists, skipping.", level="info")
            return True

        self.ui.show_status(f"Scanning paper corpus: {corpus_path}", level="info")
        try:
            corpus_manifest = scan_corpus(corpus_path)
        except (FileNotFoundError, NotADirectoryError) as exc:
            self.ui.show_status(f"Bootstrap error: {exc}", level="error")
            return False

        if not corpus_manifest.papers:
            self.ui.show_status("No extractable files found in paper corpus. Skipping bootstrap.", level="warn")
            return True

        stats = corpus_manifest.stats
        self.ui.show_status(
            f"Found {stats['total_papers']} paper(s), {stats['unique_references']} unique references. "
            f"Running profile extraction...",
            level="info",
        )
        append_log_entry(paths.logs, "bootstrap_start", format_corpus_stats_for_log(corpus_manifest))

        corpus_prompt_section = format_corpus_for_prompt(corpus_manifest)

        attempt_no = 1
        revision_feedback: str | None = None
        continue_session = False

        while True:
            self.ui.show_stage_start(stage.stage_title, attempt_no, continue_session)
            prompt = self._build_bootstrap_prompt(paths, stage, corpus_prompt_section, revision_feedback, continue_session)
            append_log_entry(paths.logs, f"bootstrap attempt {attempt_no} prompt", prompt)

            result = self.operator.run_stage(stage, prompt, paths, attempt_no, continue_session=continue_session)
            append_log_entry(
                paths.logs,
                f"bootstrap attempt {attempt_no} result",
                (
                    f"success: {result.success}\n"
                    f"session_id: {result.session_id or '(unknown)'}\n"
                    f"stage_file_path: {result.stage_file_path}\n\n"
                    "stdout:\n"
                    f"{result.stdout or '(empty)'}\n\n"
                    "stderr:\n"
                    f"{result.stderr or '(empty)'}"
                ),
            )

            if not result.stage_file_path.exists():
                self.ui.show_status(
                    "Bootstrap summary draft missing. Running repair attempt...",
                    level="warn",
                )
                repair_result = self.operator.repair_stage_summary(
                    stage=stage, original_prompt=prompt,
                    original_result=result, paths=paths, attempt_no=attempt_no,
                )
                result = repair_result

            if not result.stage_file_path.exists():
                fallback_text = "\n\n".join(
                    part for part in [result.stdout, result.stderr] if part
                )
                result = self._materialize_missing_stage_draft(
                    paths=paths, stage=stage, attempt_no=attempt_no,
                    source="bootstrap attempt and repair", fallback_text=fallback_text,
                )

            stage_markdown = read_text(result.stage_file_path)

            suggestions = parse_refinement_suggestions(stage_markdown)
            self._display_stage_output(stage, stage_markdown)
            choice = self._ask_choice(suggestions)
            append_log_entry(paths.logs, f"bootstrap attempt {attempt_no} user_choice", f"choice: {choice}")

            if choice in {"1", "2", "3"}:
                selected = suggestions[int(choice) - 1]
                revision_feedback = (
                    "Continue the bootstrap conversation and improve the researcher profile. "
                    "Do not discard correct completed parts. Address this refinement request:\n"
                    f"{selected}"
                )
                continue_session = True
                attempt_no += 1
                continue

            if choice == "4":
                custom_feedback = self._read_multiline_feedback()
                revision_feedback = (
                    "Continue the bootstrap conversation and improve the researcher profile. "
                    "Preserve correct parts unless the feedback requires changing them. "
                    "Address this user feedback:\n"
                    f"{custom_feedback}"
                )
                append_log_entry(paths.logs, f"bootstrap attempt {attempt_no} custom_feedback", custom_feedback)
                continue_session = True
                attempt_no += 1
                continue

            if choice == "5":
                # Approve: profile artifacts should already be in workspace/profile/
                # Append bootstrap summary to memory for downstream stages
                summary = format_profile_for_prompt(paths)
                if summary:
                    append_approved_stage_summary(paths.memory, stage, stage_markdown)
                append_log_entry(paths.logs, "bootstrap_approved", "Bootstrap profile approved.")
                self.ui.show_status("Approved bootstrap profile.", level="success")
                return True

            if choice == "6":
                return False

    def _build_bootstrap_prompt(
        self,
        paths: RunPaths,
        stage: StageSpec,
        corpus_text: str,
        revision_feedback: str | None,
        continue_session: bool,
    ) -> str:
        """Build the prompt for the bootstrap stage."""
        template = load_prompt_template(self.prompt_dir, stage)
        stage_template = format_stage_template(template, stage, paths)

        if continue_session:
            return build_continuation_prompt(
                stage, stage_template, paths,
                handoff_context="",
                revision_feedback=revision_feedback,
            )

        user_request = read_text(paths.user_input)
        corpus_section = f"# User's Paper Corpus\n\n{corpus_text}"

        sections = [
            "# Stage Instructions",
            stage_template.strip(),
            "# Required Stage Summary Format",
            (
                "You must create or overwrite the stage summary markdown file using exactly the "
                "top-level heading order below. Do not omit any section. Use exactly 3 numbered "
                "refinement suggestions and exactly the fixed 6 option lines."
            ),
            "```md\n" + required_stage_output_template(stage).strip() + "\n```",
            "# Original User Request",
            user_request.strip(),
            corpus_section,
            "# Revision Feedback",
            revision_feedback.strip() if revision_feedback else "None.",
        ]
        return "\n\n".join(sections).strip() + "\n"

    # ------------------------------------------------------------------
    # Regular stages (01–08)
    # ------------------------------------------------------------------

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
                if stage.slug == "07_writing":
                    package = generate_paper_package(paths.run_root)
                    append_log_entry(
                        paths.logs,
                        f"{stage.slug} paper_package",
                        package.summary,
                    )
                elif stage.slug == "08_dissemination":
                    package = generate_release_package(paths.run_root)
                    append_log_entry(
                        paths.logs,
                        f"{stage.slug} release_package",
                        package.summary,
                    )
                write_stage_handoff(paths, stage, stage_markdown)
                write_artifact_index(paths)
                write_experiment_manifest(paths)
                append_log_entry(
                    paths.logs,
                    f"{stage.slug} approved",
                    (
                        "Stage approved and appended to memory.\n"
                        f"Updated artifact index: {paths.artifact_index}\n"
                        f"Updated experiment manifest: {paths.experiment_manifest}"
                    ),
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

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_stage_prompt(
        self,
        paths: RunPaths,
        stage: StageSpec,
        revision_feedback: str | None,
        continue_session: bool,
    ) -> str:
        template = load_prompt_template(self.prompt_dir, stage)
        stage_template = format_stage_template(template, stage, paths)
        handoff_context = build_handoff_context(paths, upto_stage=stage)
        stage_template = (
            stage_template.rstrip()
            + "\n\n## Run Configuration\n\n"
            + format_venue_for_prompt(paths)
            + "\n"
        )
        artifact_index = write_artifact_index(paths)
        stage_template = (
            stage_template.rstrip()
            + "\n\n## Structured Artifact Index\n\n"
            + f"Run-wide artifact index: `{paths.artifact_index.resolve()}`\n\n"
            + format_artifact_index_for_prompt(artifact_index)
            + "\n"
        )
        if stage.number >= 5:
            experiment_manifest = write_experiment_manifest(paths)
            stage_template = (
                stage_template.rstrip()
                + "\n\n## Experiment Bundle Manifest\n\n"
                + f"Standard experiment manifest: `{paths.experiment_manifest.resolve()}`\n\n"
                + format_experiment_manifest_for_prompt(experiment_manifest)
                + "\n"
            )
        if stage.slug == "00_intake":
            ctx = load_intake_context(paths)
            if ctx and ctx.resources:
                stage_template = (
                    stage_template.rstrip()
                    + "\n\n## Pre-Loaded Resources (already in workspace)\n\n"
                    + format_resources_for_intake_prompt(ctx.resources)
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

        # Inject bootstrap researcher profile if available (stage-specific)
        profile_text = format_profile_for_prompt(paths, stage_slug=stage.slug)
        if profile_text and stage.number >= 1:
            stage_template = (
                stage_template.rstrip()
                + "\n\n# Researcher Profile (from paper corpus bootstrap)\n\n"
                + profile_text
                + "\n"
            )

        approved_memory = read_text(paths.memory)
        if self._redo_start_stage is not None and stage.number >= self._redo_start_stage.number:
            approved_memory = filtered_approved_memory(approved_memory, max_stage_number=stage.number - 1)

        # Inject intake context for regular stages (01+)
        intake_context_text: str | None = None
        if stage.number > 0:
            ctx = load_intake_context(paths)
            if ctx:
                intake_context_text = format_intake_for_prompt(ctx)

        if continue_session:
            return build_continuation_prompt(
                stage, stage_template, paths, handoff_context, revision_feedback,
                intake_context_text=intake_context_text,
            )

        user_request = read_text(paths.user_input)
        return build_prompt(
            stage, stage_template, user_request, approved_memory, handoff_context, revision_feedback,
            intake_context_text=intake_context_text,
        )

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

    def _format_rollback_preview(self, paths: RunPaths, rollback_stage: StageSpec) -> str:
        manifest = ensure_run_manifest(paths)
        stale_candidates = [
            entry.slug
            for entry in manifest.stages
            if entry.number > rollback_stage.number and (entry.approved or entry.status != "pending")
        ]
        lines = [
            f"Rolling back to {rollback_stage.stage_title}.",
            f"Stage {rollback_stage.slug} will be marked pending/dirty.",
        ]
        if stale_candidates:
            lines.append("Downstream stages that will be marked stale:")
            lines.extend(f"- {slug}" for slug in stale_candidates)
        else:
            lines.append("No downstream stages currently need invalidation.")
        return "\n".join(lines)

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
