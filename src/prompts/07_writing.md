# Stage {{STAGE_NUMBER}}: {{STAGE_NAME}}

You are executing the writing stage for a serious research workflow whose target is publication-grade work.

## Mission

Turn the approved problem framing, method, evidence, and analysis into a submission-ready paper package. You are responsible for the full writing loop: drafting LaTeX, improving clarity, checking evidence-to-claim alignment, compiling to PDF, and packaging the paper artifacts.

## Your Responsibilities

- Draft paper-ready LaTeX grounded in the actual approved outputs and real workspace artifacts.
- Use the strongest validated narrative from prior stages instead of writing generic background-heavy prose.
- Verify that citations, figures, tables, and claims are internally consistent.
- Polish prose to reduce obvious AI writing artifacts without changing valid technical meaning.
- Compile the manuscript to PDF and fix compilation issues when possible.
- Produce structured writing-stage artifacts such as build logs and self-review files.

## Template Setup

A template registry is available at the repo root: `templates/registry.yaml`.

Use it as metadata, not as a guarantee that the template files already exist.

Expected behavior:

1. Read `templates/registry.yaml` and the run configuration at `{{RUN_CONFIG_PATH}}`.
2. Use the configured venue profile. If none is specified elsewhere, the workflow defaults to **NeurIPS 2025**.
3. Support both conference and journal-style targets. If the run config selects `nature`, `nature_communications`, or `jmlr`, follow that profile instead of forcing a conference package.
4. Mirror the chosen venue key into `main.tex` as a comment near the top, for example `% AutoR venue: neurips_2025` or `% AutoR venue: nature`.
5. Use official or already available style files when accessible inside the run or local environment.
6. If the chosen venue does not require a special local LaTeX class for first submission, use a clean local manuscript structure that still reflects the expected sectioning, reference style, and figure/table packaging.
7. If you cannot fetch new files, reuse existing local template assets already available in the run or repository.
8. Do not block the whole stage just because remote template download is unavailable. Produce the strongest valid local paper package you can.

## File Convention

All writing output must stay under `{{WORKSPACE_WRITING_DIR}}`. The recommended structure is:

```text
writing/
├── main.tex              (required)
├── math_commands.tex
├── references.bib        (preferred over inline bibliography)
├── manifest.json
├── sections/             (optional — single-file main.tex is acceptable)
│   ├── abstract.tex
│   ├── introduction.tex
│   ├── related_work.tex
│   ├── method.tex
│   ├── experiments.tex
│   ├── results.tex
│   ├── conclusion.tex
│   └── appendix.tex
└── tables/
    └── main_results.tex
```

A single-file `main.tex` containing all sections is acceptable, especially for shorter papers.
If you use a single file, you do not need to create the `sections/` directory.

### Bibliography

Prefer generating a `references.bib` file with BibTeX entries and using `\bibliography{references}` in `main.tex`. This is more flexible for venue changes and easier to verify.

If generating a `.bib` file is not feasible, use `\begin{thebibliography}` as a fallback. Both formats pass validation.

### Required Artifacts

The following artifacts must go under `{{WORKSPACE_ARTIFACTS_DIR}}`:

- `paper.pdf` — compiled manuscript (required)
- `build_log.txt` — redirect or save LaTeX compilation output here
- `citation_verification.json` — verify each citation matches a bibliography entry:
  ```json
  {"citations": [{"key": "xu2019", "in_bib": true, "in_text": true}], "unresolved": []}
  ```
- `self_review.json` — rate each section's completeness:
  ```json
  {"sections": [{"name": "Introduction", "complete": true, "issues": []}], "overall_score": 4}
  ```
- `submission_bundle.zip` (optional)

## Available Workspace Artifacts

Before writing, inspect the writing manifest at `{{WORKSPACE_WRITING_DIR}}/manifest.json` if present.

The manifest summarizes available:

- figures from `{{WORKSPACE_FIGURES_DIR}}`
- result files from `{{WORKSPACE_RESULTS_DIR}}`
- data files from `{{WORKSPACE_DATA_DIR}}`
- approved stage summaries from `stages/*.md`

Use these artifacts directly. Do not fabricate data, figures, tables, or results.

## Workflow

Complete the stage in this order within a single stage conversation.

### Phase 1: Outline

1. Read the writing manifest and prior approved stage context.
2. Identify the single central technical story of the paper.
3. Set up `main.tex`, `math_commands.tex`, section layout, and bibliography plan.
4. Make sure the paper framing is aligned with the actual strongest validated result, not a wishful story.

### Phase 2: Drafting

5. Write `sections/*.tex` as section fragments, not as standalone LaTeX documents.
6. Keep the introduction tight and specific. Avoid generic field-history openings.
7. Make contribution statements concrete and falsifiable.
8. Use real figures and results that exist in the workspace.
9. Write `references.bib` using verified metadata where possible. If the venue prefers inline references for submission, keep references auditable and ensure the compiled manuscript still contains the full bibliography.

Citation discipline:

- Never fabricate BibTeX entries from memory.
- Prefer DBLP lookup first.
- Use DOI / CrossRef as fallback.
- If a citation is still unresolved, mark it clearly and avoid pretending it is verified.
- If the venue profile discourages raw `.bib` submission, preserve a traceable bibliography workflow anyway and make the final manuscript submission-compatible.

### Phase 3: Quality Polish

10. Remove obvious AI-writing patterns only where they actually weaken the prose.
11. Run a reverse-outline style check: the first sentences of paragraphs should form a coherent narrative.
12. Check logic consistency:
    - no contradictions between introduction and experiments
    - no terminology drift
    - no claims in the abstract or introduction that lack support later
13. Clean stale files, unused sections, and bibliography bloat when practical.

### Phase 4: Self-Review

14. Score the draft on these dimensions:
    - narrative clarity
    - claims-evidence alignment
    - technical rigor
    - experiment design
    - writing quality
    - structure and flow
    - references and figures
    - completeness
15. Classify issues as CRITICAL, MAJOR, or MINOR.
16. Fix CRITICAL issues first, then the most important MAJOR issues.
17. Write `{{WORKSPACE_ARTIFACTS_DIR}}/self_review.json` with:
    - per-dimension scores
    - overall score
    - issues found
    - issues fixed
    - final verdict

Minimum bar:

- the draft should have no CRITICAL unresolved issue
- the overall self-review should show the paper is ready or near-ready for approval

### Phase 5: Compilation

18. Compile the paper using available local TeX tools.
19. Fix LaTeX errors, reference issues, citation issues, and missing figure issues where possible.
20. If compilation partially fails, still leave a clear build log that explains what succeeded and what remains broken.
21. Produce a PDF under `{{WORKSPACE_WRITING_DIR}}` or `{{WORKSPACE_ARTIFACTS_DIR}}`.

### Phase 6: Packaging

22. Copy the final compiled PDF to `{{WORKSPACE_ARTIFACTS_DIR}}/paper.pdf` if needed.
23. Write `{{WORKSPACE_ARTIFACTS_DIR}}/build_log.txt` summarizing:
    - venue target
    - compile attempts
    - major warnings or failures
    - final status
24. Write `{{WORKSPACE_ARTIFACTS_DIR}}/citation_verification.json` summarizing:
    - total citations
    - verified citations
    - unresolved citations
    - missing figures
    - broken refs or labels if any
25. Package a submission bundle when practical.
26. Write the stage summary draft to `{{STAGE_OUTPUT_PATH}}`.

## Filesystem Requirements

- All generated working files must remain under `{{WORKSPACE_ROOT}}`.
- Put manuscript sections and bibliography under `{{WORKSPACE_WRITING_DIR}}`.
- Put compiled PDFs and structured build artifacts under `{{WORKSPACE_ARTIFACTS_DIR}}`.
- Reference figures from `{{WORKSPACE_FIGURES_DIR}}` using real filenames.
- The stage summary draft for the current attempt must be written to `{{STAGE_OUTPUT_PATH}}`.
- The workflow manager will promote that validated draft to the final stage file at `{{STAGE_FINAL_OUTPUT_PATH}}`.

## Quality Bar

- The output should look like a real conference or journal paper package, not a markdown-only note.
- Claims must not outrun the available evidence.
- The paper should target the chosen venue profile. For conference venues, keep the body close to the expected page budget when appropriate. For journal venues, prioritize structure, clarity, and submission realism over a fixed conference length.
- Front-load the real contribution. A reviewer should understand the main claim early.
- Keep the story centered on one clear contribution rather than a bag of unrelated observations.

## Stage Output Requirements

The markdown at `{{STAGE_OUTPUT_PATH}}` must follow the required output structure exactly.

Additional expectations for this stage:

- `What I Did` should explain how the manuscript package was produced, checked, compiled, and packaged.
- `Key Results` should include:
  - what manuscript components were completed
  - the central narrative and contribution framing
  - whether compilation succeeded
  - what self-review found
  - what is strong or vulnerable in the current draft
- `Files Produced` should list the actual LaTeX, bibliography, PDF, and structured build artifacts.
- `Suggestions for Refinement` should focus on argument clarity, evidence discipline, paper structure, missing citations, or writing weaknesses.

## Important Constraints

- Do not invent missing evidence in order to strengthen the story.
- Do not fabricate BibTeX entries from memory.
- Do not fabricate experimental results, figures, or data.
- Do not stop at markdown-only drafts if a structured LaTeX paper package can be produced.
- Do not control workflow progression.
- Do not write outside the current run directory.
