# AutoR ACP Refactor

## What This Is

A major architectural refactor of AutoR's operator layer, replacing subprocess-based `claude -p` invocations with a JSON-RPC 2.0 communication protocol. AutoR is a terminal-first, file-based, human-in-the-loop research workflow runner that orchestrates an 8-stage research pipeline using Claude Code as the AI operator. This refactor targets the communication layer between the ResearchManager and ClaudeOperator, adding structured bidirectional IPC, real-time observability, and liveness detection — while preserving all existing behavior behind an opt-in `--acp` flag.

## Core Value

External processes can observe, query, and control running Claude operator invocations in real time — eliminating the black-box problem of subprocess-based execution.

## Requirements

### Validated

- Existing 8-stage research pipeline works end-to-end (existing code)
- File-based artifact system (runs/, stages/, workspace/) (existing code)
- Human-in-the-loop approval after every stage (existing code)
- Session persistence and resume across attempts (existing code)
- Streaming output display via TerminalUI (existing code)
- Fake operator mode for local validation (existing code)

### Active

- [ ] Extract subprocess logic from ClaudeOperator into standalone ClaudeSubprocessRunner
- [ ] Extract session management into standalone SessionManager
- [ ] Define OperatorProtocol interface that both old and new operators conform to
- [ ] Implement JSON-RPC 2.0 protocol layer (message types, methods, serialization)
- [ ] Implement transport layer (Named Pipe on Windows, Unix Socket on POSIX)
- [ ] Implement OperatorServer wrapping ClaudeSubprocessRunner with JSON-RPC methods
- [ ] Implement OperatorClient conforming to OperatorProtocol
- [ ] Integrate into main.py with `--acp` opt-in flag
- [ ] Real-time status queries on running invocations
- [ ] Heartbeat-based liveness detection for stuck processes
- [ ] External monitoring capability (second process can connect to same pipe)
- [ ] Cancel running invocations via RPC

### Out of Scope

- Replacing the file-based artifact system with RPC-based artifact transfer — artifacts stay on disk
- Changing the 8-stage pipeline structure or ResearchManager orchestration logic — only the operator communication changes
- Web-based monitoring dashboard — Named Pipe transport enables it but building it is future work
- Multi-agent parallel execution — current sequential stage execution model is preserved
- Changing Claude CLI invocation flags or prompt format — ClaudeSubprocessRunner preserves exact same CLI behavior

## Context

- AutoR currently uses `subprocess.Popen` to run `claude --model X -p @prompt.md --output-format stream-json` and parses stdout line-by-line
- The operator has resume-failure-fallback logic (try `--resume`, detect failure, fall back to fresh `--session-id`) that must be preserved
- Session IDs are stored as UUID files in `operator_state/` directory per stage
- TerminalUI.show_stream_event() renders streaming JSON events — the ACP layer must produce identical payloads
- The project runs primarily on Windows 11 with bash shell
- origin/main branch is the base (not the user's unmerged development branches)
- Each change must be submitted as a separate PR with detailed description for review

## Constraints

- **Platform**: Windows 11 primary, must also work on POSIX — Named Pipe / Unix Socket transport abstraction required
- **Language**: Python 3.11+ (matching existing codebase)
- **Backward Compatibility**: Default behavior (no `--acp` flag) must be identical to current behavior — zero regression
- **PR Strategy**: Each logical change point as a separate, independently reviewable PR
- **Branch Base**: All work based on origin/main, not unmerged feature branches
- **No New Dependencies**: Prefer stdlib where possible; JSON-RPC 2.0 and Named Pipe APIs available in Python stdlib

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Named Pipe (Win) / Unix Socket (POSIX) over TCP | No port conflicts, filesystem-discoverable, multi-client capable, no network stack overhead | -- Pending |
| Server-per-run, not server-per-stage | Avoids spawn overhead, stable pipe path, cross-stage state | -- Pending |
| OperatorProtocol (structural typing) over base class | Cleaner, more Pythonic, no inheritance hierarchy needed | -- Pending |
| Async server, sync client | Server handles multiple connections; client blocks because ResearchManager._run_stage() is inherently synchronous | -- Pending |
| JSON-RPC 2.0 as wire protocol | Lightweight, well-specified, good Python stdlib support, matches user's explicit request | -- Pending |
| Opt-in `--acp` flag | Zero-risk migration path, existing users unaffected | -- Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? Move to Out of Scope with reason
2. Requirements validated? Move to Validated with phase reference
3. New requirements emerged? Add to Active
4. Decisions to log? Add to Key Decisions
5. "What This Is" still accurate? Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check -- still the right priority?
3. Audit Out of Scope -- reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-02 after initialization*
