# AutoR

AutoR is a terminal-first research workflow runner for long-form AI-assisted research. It takes a research goal, runs a fixed 8-stage pipeline with Claude Code, and requires explicit human approval after every stage before the workflow can continue.

Each run is isolated under `runs/<run_id>/`. AutoR is intentionally file-based: prompts, logs, stage outputs, and research artifacts are all written into the run directory so the workflow is inspectable, resumable, and auditable.

## Overview

AutoR uses a fixed stage order:

1. `01_literature_survey`
2. `02_hypothesis_generation`
3. `03_study_design`
4. `04_implementation`
5. `05_experimentation`
6. `06_analysis`
7. `07_writing`
8. `08_dissemination`

Core constraints:

- One Claude invocation per stage attempt.
- Every stage writes a draft summary to `stages/<stage>.tmp.md`.
- AutoR validates the draft, then promotes it to `stages/<stage>.md`.
- Human approval is mandatory after every validated stage.
- Each stage keeps its own Claude conversation state.
- `1/2/3/4` continue the current stage conversation with refinement feedback. Only `5` advances. `6` aborts.
- Approved stage summaries are appended to `memory.md`.

The main code lives in:

- [main.py](main.py)
- [src/manager.py](src/manager.py)
- [src/operator.py](src/operator.py)
- [src/utils.py](src/utils.py)
- [src/prompts/](src/prompts)

## Code Structure

```mermaid
flowchart LR
    A[main.py] --> B[src/manager.py]
    B --> C[src/operator.py]
    B --> D[src/utils.py]
    B --> E[src/prompts/*]
    C --> D
```

File boundaries:

- [main.py](main.py): CLI entry point. Starts a new run or resumes an existing run.
- [src/manager.py](src/manager.py): Owns the 8-stage loop, approval flow, repair flow, resume, redo-stage logic, and stage-level continuation policy.
- [src/operator.py](src/operator.py): Invokes Claude CLI, streams output live, persists stage session IDs, resumes the same stage conversation for refinement, and falls back to a fresh session if resume fails.
- [src/utils.py](src/utils.py): Stage metadata, prompt assembly, run paths, markdown validation, and artifact validation.
- [src/prompts/](src/prompts): Per-stage prompt templates.

## Workspace Structure

Each run contains `user_input.txt`, `memory.md`, `knowledge_base/`, `run_manifest.json`, `prompt_cache/`, `operator_state/`, `stages/`, `workspace/`, `logs.txt`, and `logs_raw.jsonl`. The substantive research payload lives in `workspace/`.

```mermaid
flowchart TD
    A[workspace/] --> B[literature/]
    A --> C[code/]
    A --> D[data/]
    A --> E[results/]
    A --> F[writing/]
    A --> G[figures/]
    A --> H[artifacts/]
    A --> I[notes/]
    A --> J[reviews/]
```

Directory boundaries:

- `literature/`: papers, benchmark notes, survey tables, reading artifacts.
- `code/`: runnable pipeline code, scripts, configs, and method implementations.
- `data/`: machine-readable datasets, manifests, processed splits, caches, and loaders.
- `results/`: machine-readable metrics, predictions, ablations, tables, and evaluation outputs.
- `writing/`: manuscript sources, LaTeX, section drafts, tables, and bibliography.
- `figures/`: plots, diagrams, charts, and paper figures.
- `artifacts/`: compiled PDFs and packaged deliverables.
- `notes/`: temporary notes and setup material.
- `reviews/`: critique notes, threat-to-validity notes, and readiness reviews.

## Workflow

```mermaid
flowchart TD
    A[Start or resume run] --> S1[01 Literature Survey]
    S1 --> H1{Human approval}
    H1 -- Refine --> S1
    H1 -- Approve --> S2[02 Hypothesis Generation]
    H1 -- Abort --> X[Abort]

    S2 --> H2{Human approval}
    H2 -- Refine --> S2
    H2 -- Approve --> S3[03 Study Design]
    H2 -- Abort --> X

    S3 --> H3{Human approval}
    H3 -- Refine --> S3
    H3 -- Approve --> S4[04 Implementation]
    H3 -- Abort --> X

    S4 --> H4{Human approval}
    H4 -- Refine --> S4
    H4 -- Approve --> S5[05 Experimentation]
    H4 -- Abort --> X

    S5 --> H5{Human approval}
    H5 -- Refine --> S5
    H5 -- Approve --> S6[06 Analysis]
    H5 -- Abort --> X

    S6 --> H6{Human approval}
    H6 -- Refine --> S6
    H6 -- Approve --> S7[07 Writing]
    H6 -- Abort --> X

    S7 --> H7{Human approval}
    H7 -- Refine --> S7
    H7 -- Approve --> S8[08 Dissemination]
    H7 -- Abort --> X

    S8 --> H8{Human approval}
    H8 -- Refine --> S8
    H8 -- Approve --> Z[Run complete]
    H8 -- Abort --> X
```

## Stage Attempt Loop

```mermaid
flowchart TD
    A[Build prompt from template + goal + memory + optional feedback] --> B[Run Claude Code once]
    B --> C[Write draft stage summary]
    C --> D[Validate markdown and required artifacts]
    D --> E{Valid?}
    E -- No --> F[Repair, normalize, or rerun current stage]
    F --> A
    E -- Yes --> G[Promote draft to final stage summary]
    G --> H{Human choice}
    H -- 1 or 2 or 3 --> I[Continue current stage conversation with AI refinement]
    I --> A
    H -- 4 --> J[Continue current stage conversation with custom feedback]
    J --> A
    H -- 5 --> K[Append approved summary to memory.md]
    K --> L[Continue to next stage]
    H -- 6 --> X[Abort]
```

Stage-loop rules:

- Claude never writes directly to the final stage file.
- The final stage file exists only after validation succeeds.
- The first attempt of a stage starts a fresh Claude session; later refinements continue that same stage session.
- If validation still fails after repair and normalization, AutoR keeps working inside the same stage and can fall back to a fresh session only if resume fails.
- The stage loop is controlled by AutoR, not by Claude.

## Prompt and Execution

For each stage attempt, AutoR assembles a prompt from:

1. the stage template from [src/prompts/](src/prompts)
2. the required stage summary contract
3. execution discipline and output-path constraints
4. `user_input.txt`
5. approved `memory.md`
6. optional refinement feedback
7. for continuation attempts, the current stage draft/final files and existing workspace state

AutoR writes the assembled prompt to `runs/<run_id>/prompt_cache/`, stores per-stage session IDs in `runs/<run_id>/operator_state/`, and invokes Claude in streaming mode through [src/operator.py](src/operator.py):

```bash
claude --model <model> \
  --permission-mode bypassPermissions \
  --dangerously-skip-permissions \
  --session-id <stage_session_id> \
  -p @runs/<run_id>/prompt_cache/<stage>_attempt_<nn>.prompt.md \
  --output-format stream-json \
  --verbose
```

Refinement attempts on the same stage reuse the same `stage_session_id` and call Claude with `--resume <stage_session_id>` instead of opening a new stage conversation.

The streamed Claude output is shown live in the terminal and also captured in `logs_raw.jsonl`.

## Validation

AutoR validates both the stage markdown and the stage artifacts.

Required stage markdown shape:

```md
# Stage X: <name>

## Objective
## Previously Approved Stage Summaries
## What I Did
## Key Results
## Files Produced
## Suggestions for Refinement
## Your Options
```

Additional markdown requirements:

- Exactly 3 numbered refinement suggestions.
- The fixed 6 user options.
- No unfinished placeholders such as `[In progress]`, `[Pending]`, `[TODO]`, or `[TBD]`.
- Concrete file paths in `Files Produced`.

Artifact requirements by stage:

- Stage 03+: machine-readable data under `workspace/data/`
- Stage 05+: machine-readable results under `workspace/results/`
- Stage 06+: figure files under `workspace/figures/`
- Stage 07+: NeurIPS-style LaTeX sources plus a compiled PDF under `workspace/writing/` or `workspace/artifacts/`
- Stage 08+: review and readiness artifacts under `workspace/reviews/`

A run with only markdown notes does not pass validation.

## CLI

Start a new run:

```bash
python main.py
```

Start a new run with an inline goal:

```bash
python main.py --goal "Your research goal here"
```

Run fake mode:

```bash
python main.py --fake-operator --goal "Smoke test"
```

Resume the latest run:

```bash
python main.py --resume-run latest
```

Resume a specific run:

```bash
python main.py --resume-run 20260329_210252
```

Redo from a specific stage inside the same run:

```bash
python main.py --resume-run 20260329_210252 --redo-stage 03
```

Roll back to a specific stage and mark downstream stages stale:

```bash
python main.py --resume-run 20260329_210252 --rollback-stage 03
```

`--resume-run ... --redo-stage ...` continues inside the existing run directory. It does not create a new run.

Valid stage identifiers include `03`, `3`, and `03_study_design`.

Inspect structured run state:

```bash
python main.py --resume-run latest --show-status
```

Search the per-run knowledge base:

```bash
python main.py --resume-run latest --kb-search "hypothesis evidence" --kb-limit 8
```

Platform-alignment layer under `src/platform/` now includes:

- orchestration patterns: sequential, parallel, hierarchical, swarm
- research pipeline router and stage-specific workflow engines
- literature-source adapters plus citation validation
- multi-agent hypothesis debate workflow
- overnight playbook execution with self-monitoring primitives
- A2A/MCP-style protocol bridge primitives
- agent runtime manager and command-style research agents
- semantic retrieval for Knowledge Base ranking
- Foundry document generation for paper/poster/slides/social bundles
- observability collectors for spans and metrics
- RBAC scope checks for API access
- sandbox execution policy and runner abstractions
- messaging outbox integration
- retry/fallback/classification/checkpoint primitives

## Scope

Included:

- fixed 8-stage workflow
- one Claude invocation per stage attempt
- mandatory human approval after every stage
- stage-local Claude conversation continuation within a stage
- AI refine, custom refine, approve, and abort
- isolated run directories
- live Claude streaming output
- repair passes and rerun fallback
- draft-to-final stage promotion
- resume and redo-stage support
- artifact-level validation
- manifest-first lifecycle tracking via `run_manifest.json`
- per-run Knowledge Base with prompt injection and CLI search
- stage-pattern metadata aligned with the ClawDock research design
- platform-alignment modules for orchestration, protocols, runtimes, Foundry, observability, security, sandboxing, messaging, and deployment
- machine-readable `run_manifest.json` stage state tracking
- stage handoff summaries under `handoff/`
- cross-stage rollback with downstream stale invalidation
- operator attempt/session recovery state under `operator_state/`
- Stage 07 paper package generation with LaTeX/bib/table/checklist/PDF artifacts
- Stage 08 review and dissemination package generation with readiness/release materials

Out of scope:

- true multi-agent orchestration execution
- database-backed state
- web UI
- concurrent stage execution
- automatic reviewer scoring

## Notes

- `runs/` is gitignored.
- AutoR implements the workflow control layer. Submission-grade output still depends on the environment, available tools, data access, model access, and the quality of the stage attempts.
