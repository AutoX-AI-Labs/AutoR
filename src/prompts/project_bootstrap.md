# Bootstrap: Project State Inference

You are analyzing an existing project repository to infer the current research state and determine the best re-entry point for the AutoR pipeline.

The repository has already been scanned: files are classified, code/experiment/writing states are assessed with heuristic rules, and a preliminary stage assessment is provided. Your job is to **review, correct, and enrich** these heuristic assessments using the actual file content and your understanding of research workflows.

## Mission

From the pre-scanned repository data, produce four bootstrap artifacts that map the existing project onto AutoR's 8-stage research pipeline:

1. A **project state summary** with corrected stage assessments
2. An **experiment inventory** of what has been run and what remains
3. A **writing state assessment** of the current manuscript progress
4. A **recommended re-entry stage** with justification

## Your Responsibilities

### 1. Review and Correct Stage Assessments

The heuristic scanner provides automated assessments. You should:
- Read key files (entry points, configs, .tex files) to verify the heuristics
- Upgrade or downgrade stage statuses based on actual content
- Add evidence you find that the scanner missed
- Pay attention to README, notes, and documentation that describe project status

Write corrected assessments to `{{WORKSPACE_BOOTSTRAP_DIR}}/stage_assessments.json`:
```json
[
  {
    "stage_number": 1,
    "stage_name": "Literature Survey",
    "status": "complete|partial|not_started",
    "confidence": "high|medium|low",
    "evidence": ["specific evidence from repo"]
  }
]
```

### 2. Experiment Inventory → `{{WORKSPACE_BOOTSTRAP_DIR}}/experiment_inventory.json`

If experiments exist, catalog them:
```json
{
  "config_files": ["path/to/config1.yaml"],
  "result_files": ["results/exp1.json"],
  "checkpoint_files": ["checkpoints/best.pt"],
  "log_files": ["logs/train.log"],
  "figure_files": ["figures/accuracy.png"],
  "total_experiments_configured": 5,
  "total_experiments_with_results": 3,
  "status": "partial",
  "evidence": ["5 configs found, 3 with matching result files", "2 experiments appear incomplete"]
}
```

### 3. Writing State → `{{WORKSPACE_BOOTSTRAP_DIR}}/writing_state.json`

If .tex files exist, assess manuscript completeness:
- Which sections have substantive content vs. placeholders?
- How complete is each section (rough percentage)?
- Are figures referenced in the text?

### 4. Bootstrap Summary → `{{WORKSPACE_BOOTSTRAP_DIR}}/bootstrap_summary.md`

A human-readable summary (300-500 words) covering:
- What this project is about (inferred from code, README, paper)
- Current state of implementation, experiments, and writing
- What's done, what's in progress, what's missing
- Recommended re-entry stage with justification
- Risks or gaps (e.g., "data loading code exists but no dataset found in repo")

## Filesystem Requirements

- All bootstrap artifacts go under `{{WORKSPACE_BOOTSTRAP_DIR}}/`.
- The stage summary draft must be written to `{{STAGE_OUTPUT_PATH}}`.
- You may read files from the project repo to verify heuristic assessments, but do NOT modify the original repo.

## Quality Bar

- Stage assessments must be evidence-based. Cite specific files.
- "complete" means genuinely done, not "some files exist." A stage with boilerplate or placeholder content is "partial."
- The recommended entry stage should be the earliest stage that needs real work, not just the first incomplete one. If Stage 04 is complete but Stage 03 was skipped, recommend Stage 03.
- If the heuristic assessments are wrong, override them with explanation.
- If the repo is ambiguous (e.g., multiple sub-projects), flag this and focus on the part most aligned with the user's goal.

## Stage Output Requirements

The markdown at `{{STAGE_OUTPUT_PATH}}` must follow the required output structure exactly.

- **Objective**: Infer the current project state from an existing repository.
- **What I Did**: Describe which files you inspected and what you found.
- **Key Results**: Corrected stage assessments with evidence, recommended entry stage.
- **Files Produced**: List all bootstrap artifacts with their paths.
- **Suggestions for Refinement**: Offer to re-examine specific stages, adjust assessments, or scan additional directories.
