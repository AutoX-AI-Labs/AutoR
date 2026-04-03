from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .terminal_ui import TerminalUI
from .utils import (
    DEFAULT_REFINEMENT_SUGGESTIONS,
    FIXED_STAGE_OPTIONS,
    OperatorResult,
    RunPaths,
    StageSpec,
    append_jsonl,
    approved_stage_summaries,
    extract_stream_text_fragments,
    read_text,
    relative_to_run,
    write_text,
)


class ClaudeOperator:
    def __init__(
        self,
        command: str = "claude",
        model: str = "sonnet",
        fake_mode: bool = False,
        output_stream: TextIO = sys.stdout,
        ui: TerminalUI | None = None,
    ) -> None:
        self.command = command
        self.model = model
        self.fake_mode = fake_mode
        self.output_stream = output_stream
        self.ui = ui or TerminalUI(output_stream=output_stream)

    def run_stage(
        self,
        stage: StageSpec,
        prompt: str,
        paths: RunPaths,
        attempt_no: int,
        continue_session: bool = False,
    ) -> OperatorResult:
        if self.fake_mode:
            return self._run_fake(stage, prompt, paths, attempt_no, continue_session=continue_session)
        return self._run_real(stage, prompt, paths, attempt_no, continue_session=continue_session)

    def _run_real(
        self,
        stage: StageSpec,
        prompt: str,
        paths: RunPaths,
        attempt_no: int,
        continue_session: bool = False,
    ) -> OperatorResult:
        if shutil.which(self.command) is None:
            raise FileNotFoundError(
                f"Claude CLI not found: {self.command}. Install it or use --fake-operator."
            )

        prompt_path = paths.prompt_cache_dir / f"{stage.slug}_attempt_{attempt_no:02d}.prompt.md"
        write_text(prompt_path, prompt)
        session_id = self._resolve_stage_session_id(paths, stage, continue_session)
        command = self._build_cli_command(prompt_path, session_id, resume=continue_session)
        self._write_attempt_state(
            paths,
            stage,
            attempt_no,
            {
                "status": "starting",
                "mode": "resume" if continue_session else "start",
                "session_id": session_id,
                "prompt_path": str(prompt_path),
                "command": command,
                "started_at": self._now(),
            },
        )

        append_jsonl(
            paths.logs_raw,
            {
                "_meta": {
                    "stage": stage.slug,
                    "attempt": attempt_no,
                    "mode": "real_continue" if continue_session else "real_start",
                    "command": command,
                    "prompt_path": str(prompt_path),
                    "session_id": session_id,
                }
            },
        )

        exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = self._run_streaming_command(
            command=command,
            cwd=paths.run_root,
            stage=stage,
            attempt_no=attempt_no,
            paths=paths,
            mode="real_continue" if continue_session else "real_start",
        )
        stage_file = paths.stage_tmp_file(stage)

        if (
            continue_session
            and exit_code != 0
            and not stage_file.exists()
            and self._looks_like_resume_failure(stdout_text, stderr_text)
        ):
            fallback_session_id = str(uuid.uuid4())
            fallback_command = self._build_cli_command(prompt_path, fallback_session_id, resume=False)
            append_jsonl(
                paths.logs_raw,
                {
                    "_meta": {
                        "stage": stage.slug,
                        "attempt": attempt_no,
                        "mode": "real_continue_fallback_start",
                        "previous_session_id": session_id,
                        "fallback_session_id": fallback_session_id,
                        "command": fallback_command,
                        "prompt_path": str(prompt_path),
                    }
                },
            )
            self._mark_session_broken(paths, stage, session_id, reason="resume_failure")
            exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = self._run_streaming_command(
                command=fallback_command,
                cwd=paths.run_root,
                stage=stage,
                attempt_no=attempt_no,
                paths=paths,
                mode="real_continue_fallback_start",
            )
            session_id = fallback_session_id

        effective_session_id = observed_session_id or session_id
        self._persist_stage_session_id(paths, stage, effective_session_id)
        success = exit_code == 0 and stage_file.exists()
        self._update_session_state(
            paths,
            stage,
            effective_session_id,
            {
                "broken": not success and continue_session,
                "last_exit_code": exit_code,
                "last_mode": "resume" if continue_session else "start",
                "updated_at": self._now(),
            },
        )
        self._write_attempt_state(
            paths,
            stage,
            attempt_no,
            {
                "status": "completed" if success else "failed",
                "mode": "resume" if continue_session else "start",
                "session_id": effective_session_id,
                "prompt_path": str(prompt_path),
                "command": command,
                "exit_code": exit_code,
                "stdout_excerpt": stdout_text[-2000:] if stdout_text else "",
                "stderr_excerpt": stderr_text[-1000:] if stderr_text else "",
                "stream_meta": stream_meta,
                "finished_at": self._now(),
            },
        )

        return OperatorResult(
            success=success,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            stage_file_path=stage_file,
            session_id=effective_session_id,
        )

    def repair_stage_summary(
        self,
        stage: StageSpec,
        original_prompt: str,
        original_result: OperatorResult,
        paths: RunPaths,
        attempt_no: int,
    ) -> OperatorResult:
        if self.fake_mode:
            return self._run_fake(stage, original_prompt, paths, attempt_no, continue_session=False)

        stage_file = paths.stage_tmp_file(stage)
        current_draft_text = read_text(stage_file) if stage_file.exists() else "(missing)"
        current_final_path = paths.stage_file(stage)
        current_final_text = read_text(current_final_path) if current_final_path.exists() else "(missing)"
        recovery_prompt = f"""
You are performing failure recovery for {stage.stage_title}.

The previous attempt either failed before producing a valid stage summary file, or produced a file with missing required sections.
Your only task now is to overwrite the stage summary file at:
{stage_file}

Rules:
- Do not browse the web.
- Do not use WebSearch or WebFetch.
- Do not try to continue the full research workflow.
- Use only the information already available in the prompt below and the run directory if needed.
- If the earlier attempt failed or produced incomplete evidence, state that clearly in the summary.
- You must still produce a valid markdown file in the required format.
- Treat `{stage_file}` as the final deliverable, not as a scratchpad.
- Do not write half-finished, placeholder, outline-only, pending, or in-progress content to `{stage_file}`.
- If you need scratch notes while repairing, write them somewhere else in the run directory, not to `{stage_file}`.
- Do not describe, summarize, or comment on the repair prompt itself.
- Do not ask the user what to do next.
- Do not say that the stage "already completed successfully" unless the written stage file itself contains the full required structure.
- You must directly write the repaired markdown file, then stop.

Required markdown structure:
# Stage X: <name>
## Objective
## Previously Approved Stage Summaries
## What I Did
## Key Results
## Files Produced
## Suggestions for Refinement
1. {DEFAULT_REFINEMENT_SUGGESTIONS[0]}
2. {DEFAULT_REFINEMENT_SUGGESTIONS[1]}
3. {DEFAULT_REFINEMENT_SUGGESTIONS[2]}
## Your Options
{chr(10).join(FIXED_STAGE_OPTIONS)}

Required completion behavior:
1. Read the current stage file if it exists.
2. Overwrite it with a complete markdown document in the exact structure above.
3. Ensure both `## Previously Approved Stage Summaries` and `## Your Options` are present.
4. Ensure there is no `[In progress]`, `[Pending]`, `[TODO]`, `[TBD]`, or similar unfinished marker anywhere in the file.
5. After writing, respond only with a short confirmation that you rewrote the file.

Current draft stage file contents:
{current_draft_text}

Current promoted stage file contents:
{current_final_text}

Original prompt:
{original_prompt}

Original stdout:
{original_result.stdout or "(empty)"}

Original stderr:
{original_result.stderr or "(empty)"}
""".strip()

        recovery_prompt_path = paths.prompt_cache_dir / f"{stage.slug}_attempt_{attempt_no:02d}_repair.prompt.md"
        write_text(recovery_prompt_path, recovery_prompt)
        session_id = self._resolve_stage_session_id(paths, stage, continue_session=True, allow_create=False)
        if session_id:
            command = self._build_cli_command(
                recovery_prompt_path,
                session_id,
                resume=True,
                tools="Write,Read,Glob,Grep",
            )
        else:
            session_id = self._resolve_stage_session_id(paths, stage, continue_session=False)
            command = self._build_cli_command(
                recovery_prompt_path,
                session_id,
                resume=False,
                tools="Write,Read,Glob,Grep",
            )

        append_jsonl(
            paths.logs_raw,
            {
                "_meta": {
                    "stage": stage.slug,
                    "attempt": attempt_no,
                    "mode": "repair",
                    "command": command,
                    "prompt_path": str(recovery_prompt_path),
                    "session_id": session_id,
                }
            },
        )

        self._write_attempt_state(
            paths,
            stage,
            attempt_no,
            {
                "status": "repair_starting",
                "mode": "repair",
                "session_id": session_id,
                "prompt_path": str(recovery_prompt_path),
                "command": command,
                "started_at": self._now(),
            },
        )

        exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = self._run_streaming_command(
            command=command,
            cwd=paths.run_root,
            stage=stage,
            attempt_no=attempt_no,
            paths=paths,
            mode="repair",
        )
        if (
            session_id
            and exit_code != 0
            and not stage_file.exists()
            and self._looks_like_resume_failure(stdout_text, stderr_text)
        ):
            fallback_session_id = str(uuid.uuid4())
            fallback_command = self._build_cli_command(
                recovery_prompt_path,
                fallback_session_id,
                resume=False,
                tools="Write,Read,Glob,Grep",
            )
            append_jsonl(
                paths.logs_raw,
                {
                    "_meta": {
                        "stage": stage.slug,
                        "attempt": attempt_no,
                        "mode": "repair_fallback_start",
                        "previous_session_id": session_id,
                        "fallback_session_id": fallback_session_id,
                        "command": fallback_command,
                        "prompt_path": str(recovery_prompt_path),
                    }
                },
            )
            self._mark_session_broken(paths, stage, session_id, reason="repair_resume_failure")
            exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = self._run_streaming_command(
                command=fallback_command,
                cwd=paths.run_root,
                stage=stage,
                attempt_no=attempt_no,
                paths=paths,
                mode="repair_fallback_start",
            )
            session_id = fallback_session_id

        effective_session_id = observed_session_id or session_id
        self._persist_stage_session_id(paths, stage, effective_session_id)
        self._update_session_state(
            paths,
            stage,
            effective_session_id,
            {
                "broken": exit_code != 0 and not stage_file.exists(),
                "last_exit_code": exit_code,
                "last_mode": "repair",
                "updated_at": self._now(),
            },
        )
        self._write_attempt_state(
            paths,
            stage,
            attempt_no,
            {
                "status": "repair_completed" if exit_code == 0 and stage_file.exists() else "repair_failed",
                "mode": "repair",
                "session_id": effective_session_id,
                "prompt_path": str(recovery_prompt_path),
                "command": command,
                "exit_code": exit_code,
                "stdout_excerpt": stdout_text[-2000:] if stdout_text else "",
                "stderr_excerpt": stderr_text[-1000:] if stderr_text else "",
                "stream_meta": stream_meta,
                "finished_at": self._now(),
            },
        )

        return OperatorResult(
            success=exit_code == 0 and stage_file.exists(),
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            stage_file_path=stage_file,
            session_id=effective_session_id,
        )

    def _run_streaming_command(
        self,
        command: list[str],
        cwd: Path,
        stage: StageSpec,
        attempt_no: int,
        paths: RunPaths,
        mode: str,
    ) -> tuple[int, str, str, str | None, dict[str, object]]:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if process.stdout is None:
            raise RuntimeError("Failed to capture Claude output stream.")

        extracted_fragments: list[str] = []
        raw_lines: list[str] = []
        non_json_lines: list[str] = []
        ended_with_newline = True
        observed_session_id: str | None = None
        malformed_json_count = 0

        try:
            for raw_line in process.stdout:
                ended_with_newline = raw_line.endswith("\n")
                line = raw_line.rstrip("\n")
                raw_lines.append(line)
                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    malformed_json_count += 1
                    append_jsonl(
                        paths.logs_raw,
                        {
                            "_meta": {
                                "stage": stage.slug,
                                "attempt": attempt_no,
                                "mode": mode,
                                "non_json_output": stripped,
                            }
                        },
                    )
                    non_json_lines.append(stripped)
                    self.ui.show_raw_stream_line(stripped)
                    continue

                append_jsonl(paths.logs_raw, payload)
                if observed_session_id is None:
                    observed_session_id = self._extract_session_id(payload)
                extracted_fragments.extend(extract_stream_text_fragments(payload))
                self.ui.show_stream_event(payload, tool_names)
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        finally:
            process.stdout.close()

        exit_code = process.wait()
        if raw_lines and not ended_with_newline:
            self.output_stream.write("\n")
            self.output_stream.flush()

        stdout_text = self._compose_stdout_text(
            extracted_fragments=extracted_fragments,
            non_json_lines=non_json_lines,
            raw_lines=raw_lines,
        )
        return exit_code, stdout_text, "", observed_session_id, {
            "raw_line_count": len(raw_lines),
            "non_json_line_count": len(non_json_lines),
            "malformed_json_count": malformed_json_count,
            "observed_session_id": observed_session_id,
        }

    def _compose_stdout_text(
        self,
        extracted_fragments: list[str],
        non_json_lines: list[str],
        raw_lines: list[str],
    ) -> str:
        fragment_text = "\n".join(fragment for fragment in extracted_fragments if fragment).strip()
        non_json_text = "\n".join(line for line in non_json_lines if line).strip()
        raw_text = "\n".join(line for line in raw_lines if line).strip()

        parts: list[str] = []
        if fragment_text:
            parts.append(fragment_text)
        if non_json_text:
            parts.append(non_json_text)
        if not parts and raw_text:
            parts.append(raw_text)

        return "\n\n".join(parts).strip()

    def _run_fake(
        self,
        stage: StageSpec,
        prompt: str,
        paths: RunPaths,
        attempt_no: int,
        continue_session: bool = False,
    ) -> OperatorResult:
        session_id = self._resolve_stage_session_id(paths, stage, continue_session=continue_session)
        self._persist_stage_session_id(paths, stage, session_id)
        approved_memory = self._extract_approved_memory_from_prompt(prompt) or read_text(paths.memory)
        previous_summaries = approved_stage_summaries(approved_memory)
        note_path = paths.notes_dir / f"{stage.slug}_fake_operator_note.md"
        stage_tmp_path = paths.stage_tmp_file(stage)
        user_goal = read_text(paths.user_input).strip()
        write_text(
            note_path,
            (
                f"# Fake Operator Note: {stage.stage_title}\n\n"
                "This file was produced by fake-operator mode to validate the workflow, "
                "directory layout, stage summary handling, and approval loop without "
                "calling Claude."
            ),
        )

        if stage.number == 1 and "smoke test" in user_goal.lower():
            intro_path = paths.notes_dir / "autor_intro.md"
            write_text(
                intro_path,
                (
                    "# AutoR Overview\n\n"
                    "AutoR is a terminal-first, file-based, human-in-the-loop research workflow runner.\n\n"
                    "It executes a fixed 8-stage pipeline:\n"
                    "1. Literature survey\n"
                    "2. Hypothesis generation\n"
                    "3. Study design\n"
                    "4. Implementation\n"
                    "5. Experimentation\n"
                    "6. Analysis\n"
                    "7. Writing\n"
                    "8. Dissemination\n\n"
                    "Every stage writes artifacts into an isolated run directory and must be explicitly approved by the user.\n"
                ),
            )
            stage_markdown = (
                f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
                "## Objective\n"
                "Introduce AutoR during a fake-mode smoke test while demonstrating the terminal UI, "
                "stage summary contract, and approval loop.\n\n"
                "## Previously Approved Stage Summaries\n"
                f"{previous_summaries}\n\n"
                "## What I Did\n"
                "- Entered fake-operator mode so the full terminal workflow could be demonstrated without calling Claude.\n"
                "- Generated a short markdown introduction to AutoR for recording and smoke-test purposes.\n"
                f"- Wrote overview material to `{relative_to_run(intro_path, paths.run_root)}` and preserved the fake operator note at `{relative_to_run(note_path, paths.run_root)}`.\n"
                f"- Produced a valid stage summary draft at `{relative_to_run(stage_tmp_path, paths.run_root)}`.\n\n"
                "## Key Results\n"
                "- AutoR is a terminal-first, file-based, human-in-the-loop research workflow runner.\n"
                "- The workflow is fixed into 8 stages: literature, hypothesis, design, implementation, experimentation, analysis, writing, and dissemination.\n"
                "- Every run is isolated under `runs/<run_id>/`, with prompts, logs, stage summaries, and workspace artifacts written to disk.\n"
                "- The UI smoke test confirms the current terminal interface, menu interaction, and stage-summary rendering path are working.\n"
                "- This output is a product demo and workflow intro, not a real research result.\n\n"
                "## Files Produced\n"
                f"- `{relative_to_run(intro_path, paths.run_root)}`\n"
                f"- `{relative_to_run(note_path, paths.run_root)}`\n"
                f"- `{relative_to_run(stage_tmp_path, paths.run_root)}`\n\n"
                "## Suggestions for Refinement\n"
                "1. Switch from fake mode to the real Claude operator and record a live stage execution.\n"
                "2. Tune the terminal theme, colors, and screen layout for recording aesthetics.\n"
                "3. Expand the intro note with a concrete example run and artifact tour before moving on.\n\n"
                "## Your Options\n"
                "1. Use suggestion 1\n"
                "2. Use suggestion 2\n"
                "3. Use suggestion 3\n"
                "4. Refine with your own feedback\n"
                "5. Approve and continue\n"
                "6. Abort\n"
            )
        else:
            stage_markdown = (
                f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
                "## Objective\n"
                f"Validate the workflow path for {stage.display_name} and confirm that the "
                "manager, operator, and filesystem contracts are functioning.\n\n"
                "## Previously Approved Stage Summaries\n"
                f"{previous_summaries}\n\n"
                "## What I Did\n"
                "- Executed fake-operator mode instead of invoking Claude.\n"
                f"- Created a placeholder artifact at `{relative_to_run(note_path, paths.run_root)}`.\n"
                f"- Simulated a complete stage attempt for `{stage.slug}`.\n\n"
                "## Key Results\n"
                "- The orchestration loop, run layout, and stage-summary validation path are active.\n"
                f"- Prompt length for this attempt was {len(prompt.split())} words.\n"
                "- No research claim from this stage should be treated as real output.\n\n"
                "## Files Produced\n"
                f"- `{relative_to_run(note_path, paths.run_root)}`\n"
                f"- `{relative_to_run(stage_tmp_path, paths.run_root)}`\n\n"
                "## Suggestions for Refinement\n"
                "1. Replace fake mode with the real Claude operator and inspect the resulting artifacts.\n"
                "2. Tighten the stage prompt to better reflect the target of actual publication-grade work.\n"
                "3. Add stronger expectations for the concrete artifacts and files outputs from this stage.\n\n"
                "## Your Options\n"
                "1. Use suggestion 1\n"
                "2. Use suggestion 2\n"
                "3. Use suggestion 3\n"
                "4. Refine with your own feedback\n"
                "5. Approve and continue\n"
                "6. Abort\n"
            )
        write_text(stage_tmp_path, stage_markdown)
        append_jsonl(
            paths.logs_raw,
            {
                "_meta": {
                    "stage": stage.slug,
                    "attempt": attempt_no,
                    "mode": "fake_continue" if continue_session else "fake_start",
                    "session_id": session_id,
                }
            },
        )

        return OperatorResult(
            success=True,
            exit_code=0,
            stdout="Fake operator completed successfully.",
            stderr="",
            stage_file_path=stage_tmp_path,
            session_id=session_id,
        )

    def _extract_approved_memory_from_prompt(self, prompt: str) -> str | None:
        match = re.search(
            r"^# Approved Memory\s*$\n?(.*?)(?=^# [^\n]+\s*$|\Z)",
            prompt,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not match:
            return None
        extracted = match.group(1).strip()
        return extracted or None

    def _resolve_stage_session_id(
        self,
        paths: RunPaths,
        stage: StageSpec,
        continue_session: bool,
        allow_create: bool = True,
    ) -> str | None:
        session_state_path = paths.stage_session_state_file(stage)
        if session_state_path.exists():
            payload = json.loads(read_text(session_state_path))
            session_id = str(payload.get("session_id") or "").strip()
            broken = bool(payload.get("broken", False))
            if session_id and not broken:
                return session_id

        session_file = paths.stage_session_file(stage)
        if session_file.exists():
            session_id = read_text(session_file).strip()
            if session_id:
                return session_id

        if continue_session and not allow_create:
            return None

        return str(uuid.uuid4())

    def _persist_stage_session_id(self, paths: RunPaths, stage: StageSpec, session_id: str | None) -> None:
        if not session_id:
            return
        write_text(paths.stage_session_file(stage), session_id)
        self._update_session_state(
            paths,
            stage,
            session_id,
            {
                "broken": False,
                "updated_at": self._now(),
            },
        )

    def _extract_session_id(self, payload: dict[str, object]) -> str | None:
        value = payload.get("session_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _build_cli_command(
        self,
        prompt_path: Path,
        session_id: str,
        *,
        resume: bool,
        tools: str | None = None,
    ) -> list[str]:
        command = [
            self.command,
            "--model",
            self.model,
            "--permission-mode",
            "bypassPermissions",
            "--dangerously-skip-permissions",
        ]
        if tools:
            command.extend(["--tools", tools])
        if resume:
            command.extend(["--resume", session_id])
        else:
            command.extend(["--session-id", session_id])
        command.extend(
            [
                "-p",
                f"@{prompt_path}",
                "--output-format",
                "stream-json",
                "--verbose",
            ]
        )
        return command

    def _looks_like_resume_failure(self, stdout_text: str, stderr_text: str) -> bool:
        combined = "\n".join(part for part in [stdout_text, stderr_text] if part).lower()
        return "no conversation found with session id" in combined or "resume" in combined and "not found" in combined

    def _write_attempt_state(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        payload: dict[str, object],
    ) -> None:
        write_text(paths.stage_attempt_state_file(stage, attempt_no), json.dumps(payload, indent=2, ensure_ascii=True))

    def _update_session_state(
        self,
        paths: RunPaths,
        stage: StageSpec,
        session_id: str | None,
        changes: dict[str, object],
    ) -> None:
        path = paths.stage_session_state_file(stage)
        payload: dict[str, object] = {}
        if path.exists():
            try:
                payload = json.loads(read_text(path))
            except json.JSONDecodeError:
                payload = {}
        payload.update(changes)
        if session_id:
            payload["session_id"] = session_id
        write_text(path, json.dumps(payload, indent=2, ensure_ascii=True))

    def _mark_session_broken(self, paths: RunPaths, stage: StageSpec, session_id: str | None, reason: str) -> None:
        self._update_session_state(
            paths,
            stage,
            session_id,
            {
                "broken": True,
                "broken_reason": reason,
                "updated_at": self._now(),
            },
        )

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")
