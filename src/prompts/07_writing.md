# Stage {{STAGE_NUMBER}}: {{STAGE_NAME}}

You are executing the writing stage for a serious research workflow whose target is publication-grade work.

## Mission

Turn the approved problem framing, method, evidence, and analysis into a **submission-ready paper package**. You are responsible for the entire pipeline: writing LaTeX, compiling to PDF, verifying citations, polishing prose, and packaging the submission bundle.

## Your Responsibilities

- Draft paper-ready LaTeX section files grounded in the actual approved outputs.
- Set up the venue template (download or copy official .sty/.cls files).
- Compile the paper to PDF and fix any compilation errors.
- Verify all citations and figure references are consistent.
- Polish prose to remove AI writing artifacts.
- Package the final submission bundle.
- Produce structured verification artifacts (build_log, citation_verification).

## TeX Environment

The TeX toolchain is available via conda. Before running any LaTeX commands, ensure the PATH includes the TeX binaries:

```bash
export PATH="/Users/yifanzhou/miniconda3/envs/autor_tex/bin:$PATH"
```

Verify availability: `which pdflatex && which bibtex && which chktex`

## Template Setup

A template registry is available at the repo root: `templates/registry.yaml`. It lists supported venues with their official URLs, style packages, citation styles, and page limits.

**To set up a template:**

1. Read `templates/registry.yaml` to find the target venue configuration.
2. Download the official style package from the `official_url`, OR copy pre-downloaded templates if available.
3. Generate `main.tex` that uses the correct `\usepackage{...}` and `\input{sections/...}` structure.
4. Generate `math_commands.tex` with paper-specific notation macros.

If the official URL is unreachable, check for fallback templates under `workspace/agent_systems/Auto-claude-code-research-in-sleep/skills/paper-write/templates/`.

**Default venue: NeurIPS 2025** (unless the run configuration specifies otherwise).

## File Convention

All your output must go under `{{WORKSPACE_WRITING_DIR}}`. The expected structure:

```
writing/
├── main.tex                    ← YOU create this (based on venue template)
├── math_commands.tex           ← YOU create this (shared math macros)
├── references.bib              ← YOU create this (all BibTeX entries)
├── sections/
│   ├── abstract.tex            ← YOU create this
│   ├── introduction.tex        ← YOU create this
│   ├── related_work.tex        ← YOU create this
│   ├── method.tex              ← YOU create this
│   ├── experiments.tex         ← YOU create this
│   ├── results.tex             ← YOU create this
│   ├── conclusion.tex          ← YOU create this
│   └── appendix.tex            ← YOU create this (optional)
└── tables/
    └── main_results.tex        ← YOU create this (optional)
```

## Available Workspace Artifacts

Before writing, read `{{WORKSPACE_WRITING_DIR}}/manifest.json` if it exists. It lists:
- Available figures under `{{WORKSPACE_FIGURES_DIR}}`
- Available result files under `{{WORKSPACE_RESULTS_DIR}}`
- Stage summaries from prior stages

Use these real artifacts in your paper. **Do not fabricate data, figures, or results.**

## Workflow — Step by Step

Complete all steps in this order within a single session:

### Phase 1: Outline

1. Read `manifest.json` to understand available figures, results, and data.
2. Read prior stage summaries to understand the research narrative.
3. Set up the venue template (download/copy .sty + generate `main.tex`).
4. Generate `math_commands.tex` with paper-specific notation.

### Phase 2: Drafting

5. Write `sections/*.tex` files — each is a pure LaTeX fragment (no `\documentclass`, no `\begin{document}`, no preamble). Just section content starting with `\section{...}`.
   - `abstract.tex`: only the abstract text (no `\begin{abstract}` — the template handles that).
   - Each section should meet its page target (intro ~1.5pp, related work ≥1pp, method ~2pp, experiments ~2.5pp, conclusion ~0.5pp).
   - Figure references: `\includegraphics[width=\columnwidth]{filename.png}` — set `\graphicspath{{../figures/}}` in `main.tex`.
   - Every `\cite{}` / `\citep{}` key must have a matching entry in `references.bib`.

6. Write `references.bib` — **NEVER fabricate BibTeX entries from memory**. Use this verification chain:
   - **Step A — DBLP** (best quality): `curl -s "https://dblp.org/search/publ/api?q=TITLE+AUTHOR&format=json&h=3"` → extract key → `curl -s "https://dblp.org/rec/{key}.bib"`
   - **Step B — CrossRef DOI** (fallback): `curl -sLH "Accept: application/x-bibtex" "https://doi.org/{doi}"`
   - **Step C — Mark [VERIFY]** (last resort): add `% [VERIFY]` comment. Do NOT fabricate.
   - Only include entries that are actually `\cite`d in the paper (no bloat).

### Phase 3: Quality Polish

7. **De-AI polish** — scan all section files and fix AI writing patterns. The goal is natural academic prose, not mechanical word substitution. Only change text that genuinely reads as machine-generated.

    **Words to replace** (when they add no precision over simpler alternatives):
    delve, pivotal, landscape, tapestry, underscore, noteworthy, intriguingly, leverage, elucidate, utilize, facilitate, aforementioned, paradigm, synergy, holistic, novel (when overused), comprehensive (when vague), robust (when imprecise), seamless, cutting-edge, state-of-the-art (prefer "recent" or cite the actual method)

    **Phrases to remove** (low-information fillers):
    "It is worth noting that", "Importantly,", "Notably,", "It should be noted that", "First and foremost,", "In recent years,", "has attracted significant attention", "plays a crucial role"

    **Structural patterns to fix**:
    - Consecutive sentences starting with "This" or "We" — vary sentence openings
    - Repetitive three-item lists ("X, Y, and Z") in consecutive paragraphs
    - Generic field-background openings in the abstract (delete and start with the specific contribution)
    - Bullet/list formatting in prose sections — convert to flowing paragraphs
    - Excessive dash (—) usage — replace with commas, parentheses, or subordinate clauses

    **修改阈值**: If a sentence already reads naturally and precisely, leave it alone. Do not change for the sake of changing. The goal is removing obvious machine artifacts, not rewriting everything.

8. **Reverse outline test** — extract the first sentence of every paragraph, read them in sequence. They should form a coherent narrative. Fix any paragraph whose topic sentence doesn't advance the story.

9. **Logic consistency check** — read the full paper and verify:
    - No contradictory claims between sections (e.g., intro claims X, experiments show not-X)
    - Core terminology is consistent throughout (do not rename the same concept across sections)
    - Every experiment in the Experiments section maps to a claim stated in the Introduction
    - Contribution bullets in the Introduction are specific and falsifiable (not "we study X" or "we perform experiments")

10. **Pre-compilation citation & reference check** — verify before compiling:
    - Every `\cite{key}` / `\citep{key}` / `\citet{key}` has a corresponding `@type{key,` entry in `references.bib`
    - Every `\includegraphics{file}` references a file that exists under `{{WORKSPACE_FIGURES_DIR}}`
    - Every `\ref{label}` has a corresponding `\label{label}` in some `.tex` file
    - Fix any inconsistencies found

11. Clean up stale files — check that every `.tex` file in `sections/` is `\input`ed by `main.tex`. Remove orphans.

12. Clean up bib bloat — remove entries from `references.bib` that are not `\cite`d anywhere.

### Phase 4: Self-Review Scoring Loop

**After polishing, score your own paper before compiling.** This is a structured self-assessment — not a rewrite. Run up to 2 rounds. If the first round scores ≥ 7.0 overall with no CRITICAL issues, skip round 2 and proceed to compilation.

13. **Score the paper** on these 8 dimensions (1-10 each):

    | Dimension | What to evaluate | Score |
    |-----------|-----------------|-------|
    | **Narrative clarity** | Can the contribution be stated in one sentence? Is the What/Why/So What clear by end of Introduction? | _ /10 |
    | **Claims-evidence alignment** | Does every claim in the abstract/intro have supporting evidence in experiments? Any overclaims? | _ /10 |
    | **Technical rigor** | Are methods described precisely enough to reproduce? Are assumptions stated? Are proofs/derivations correct? | _ /10 |
    | **Experiment design** | Are baselines fair and sufficient? Are ablations present for key design choices? Error bars? | _ /10 |
    | **Writing quality** | Is prose clear, precise, and free of AI artifacts? Is terminology consistent? | _ /10 |
    | **Structure & flow** | Does the paper follow a logical progression? Is the Introduction ≤1.5pp? Does the method start by page 2-3? | _ /10 |
    | **References & figures** | Are citations real and relevant? Are figure captions self-contained? Are all refs/labels resolved? | _ /10 |
    | **Completeness** | Are all sections substantively filled? No placeholder text? No [TODO] markers? | _ /10 |

    Compute the **overall score** = average of 8 dimensions.

14. **Classify issues by severity**:
    - **CRITICAL** (must fix): contradictions, fabricated data/citations, missing key evidence, anonymity breach, placeholder text remaining
    - **MAJOR** (should fix): overclaims, missing ablations, inconsistent terminology, weak related work, structural problems
    - **MINOR** (fix if time permits): wording improvements, minor formatting, non-essential warnings

15. **Fix issues** — apply fixes in severity order (CRITICAL → MAJOR → MINOR). Common fix patterns:

    | Issue | Fix Pattern |
    |-------|-------------|
    | Overclaim | Soften: "validates" → "demonstrates", "achieves state-of-the-art" → "achieves competitive results" |
    | Claim without evidence | Either add evidence reference or remove/weaken the claim |
    | Inconsistent terminology | Pick the best term, search-and-replace globally across all .tex files |
    | Missing experiment-claim link | Add a sentence in Experiments stating what claim this experiment tests |
    | Weak contribution bullets | Rewrite as specific, falsifiable statements with quantitative results |
    | Abstract starts with generic background | Delete generic opening, start with the paper's specific contribution |
    | Related Work is paper-by-paper | Reorganize by method family or research question |

    If fixes were applied, re-score and check whether another round is needed.

16. **Log the self-review** — write `{{WORKSPACE_ARTIFACTS_DIR}}/self_review.json`:
    ```json
    {
      "rounds": 1,
      "scores": {
        "narrative_clarity": 8,
        "claims_evidence": 7,
        "technical_rigor": 8,
        "experiment_design": 7,
        "writing_quality": 8,
        "structure_flow": 8,
        "references_figures": 9,
        "completeness": 9
      },
      "overall_score": 8.0,
      "critical_issues_found": 0,
      "major_issues_found": 2,
      "issues_fixed": ["softened overclaim in abstract", "added ablation reference in experiments"],
      "final_verdict": "ready"
    }
    ```

    **Verdict**: `"ready"` if overall ≥ 7.0 and 0 CRITICAL issues; `"needs_revision"` otherwise.

### Phase 5: Compilation

All text changes are now finalized. Compile the paper.

17. Compile using the four-step sequence:
    ```bash
    cd {{WORKSPACE_WRITING_DIR}}
    pdflatex -interaction=nonstopmode main.tex
    bibtex main
    pdflatex -interaction=nonstopmode main.tex
    pdflatex -interaction=nonstopmode main.tex
    ```

18. **Self-repair loop** (up to 3 attempts): If compilation fails, read the error log and fix issues:
    - Missing packages → install via `tlmgr` or remove unused `\usepackage`
    - Undefined references → check `\label{}` exists in the correct environment
    - Missing figures → check filename/extension, update `\includegraphics` path
    - Citation undefined → add missing entry to `references.bib` or fix key
    - BibTeX syntax errors → fix comma, braces, special characters
    - Overfull hbox (>20pt) → rephrase text or adjust figure width
    - After fixing, recompile with the full four-step sequence.
    - **Success criterion**: PDF file exists and is > 100KB (not empty/corrupt). Do not rely on exit codes — pdflatex often returns non-zero but still produces usable PDFs.

19. **Post-compilation checks**:
    - Run `chktex main.tex -q -n2 -n24 -n13 -n1` — address significant warnings
    - No "??" in PDF (undefined references — check compile log)
    - No "[?]" in PDF (undefined citations — check compile log)
    - No `[VERIFY]` markers left in text
    - Page count within venue limit (main body to Conclusion end, excluding refs/appendix for ML venues)
    - Anonymous mode: no author names, affiliations, or self-citations revealing identity
    - All fonts embedded in PDF (`pdffonts main.pdf | grep -v "yes"` should return nothing)
    - File size reasonable (< 50MB, preferred < 10MB)
    - Self-review overall score ≥ 7.0
    - Zero CRITICAL issues remaining

### Phase 6: Packaging

20. Copy the compiled PDF to `{{WORKSPACE_ARTIFACTS_DIR}}/paper.pdf`.

21. Package `submission_bundle.zip` containing only submission files:
    - **Include**: `.tex`, `.sty`, `.bst`, `.bib`, `.cls`, `.pdf`, `.png`, `.jpg`, `.jpeg`, `.eps`, `.svg`
    - **Exclude**: `.aux`, `.log`, `.out`, `.fls`, `.fdb_latexmk`, `.synctex.gz`, `.blg`, `.bbl`, `.toc`

22. Write `{{WORKSPACE_ARTIFACTS_DIR}}/build_log.txt` — structured build log:
    ```
    === Build Log ===
    Timestamp: ...
    Venue: ...
    Compilation attempts: N
    Self-review rounds: N
    Self-review score: X.X/10
    Final status: SUCCESS / FAILED
    PDF pages: X (main body) + Y (references) + Z (appendix)
    Warnings remaining: [list]
    Errors fixed: [list]
    ```

23. Write `{{WORKSPACE_ARTIFACTS_DIR}}/citation_verification.json`:
    ```json
    {
      "overall_status": "pass" | "fail",
      "total_citations": N,
      "verified_citations": N,
      "unverified_citations": ["key1", "key2"],
      "missing_figures": [],
      "orphan_labels": [],
      "orphan_refs": [],
      "verify_markers_remaining": 0
    }
    ```

24. Write `{{WORKSPACE_ARTIFACTS_DIR}}/build_manifest.json` with pipeline metadata.

25. Write the stage summary markdown to `{{STAGE_OUTPUT_PATH}}`.

## Filesystem Requirements

- All generated working files must remain under `{{WORKSPACE_ROOT}}`.
- Put manuscript sections and bibliography under `{{WORKSPACE_WRITING_DIR}}`.
- Put compiled PDF, build log, and verification artifacts under `{{WORKSPACE_ARTIFACTS_DIR}}`.
- Reference figures from `{{WORKSPACE_FIGURES_DIR}}` by filename only.
- The stage summary draft for the current attempt must be written to `{{STAGE_OUTPUT_PATH}}`.
- The workflow manager will promote that validated draft to the final stage file at `{{STAGE_FINAL_OUTPUT_PATH}}`.

## Writing Quality Rules

### The Narrative Principle

A paper is a **short, rigorous, evidence-backed technical story** — not a pile of experiments.

- If the core contribution cannot be stated in one sentence, the framing has not converged.
- Every section should serve the same story. Experiments, related work, and discussion support the main claim — they are not independent mini-papers.
- Front-load the contribution: title, abstract, introduction, and Figure 1 should make the main claim clear before the reader reaches the method.

### Abstract (Five-Sentence Formula)

Write a compact abstract following this structure:
1. What you achieved (the specific contribution)
2. Why the problem is important and difficult
3. How you approached it
4. What evidence supports the claim
5. What number, result, or guarantee the reader should remember

**Do not** open with generic field background ("Large language models have achieved remarkable success..."). If the first sentence could fit any ML paper, delete it and start with the paper's specific contribution.

### Introduction Structure

- Keep the Introduction to ~1.5 pages. The method should start by page 2-3.
- Include 2-4 contribution bullets that are **specific and falsifiable**:
  - Good: "We prove that X converges in O(n log n) under assumption Y."
  - Bad: "We study problem X." / "We perform extensive experiments."
- Surface the strongest result early — tell the reader what is worth remembering.

### Sentence-Level Clarity

- **Keep subject and verb close** — do not separate them with long subordinate clauses.
- **Put context at the start, new information at the end** — readers parse better when sentences move from familiar to new.
- **Put actions in verbs** — "We analyzed the results" not "We performed an analysis of the results."
- **One paragraph, one job** — if a paragraph tries to do two things, split it.
- **Reduce ambiguous pronouns** — when "this", "it", "these" could refer to multiple things, replace with a specific noun.

### Word Choice

- Use precise terms: "accuracy" not "performance", "3x faster" not "fast", "92% F1" not "good results".
- Claims must match the evidence — do not overclaim. Use hedging ("suggests", "indicates") only where uncertainty is genuine. But do not over-hedge — excessive "may", "might", "potentially" reads as self-doubt, not rigor.
- Maintain consistent terminology — do not rename concepts across sections (e.g., do not mix "model" / "network" / "architecture" for the same thing).
- Prefer verbs that signal contribution: "develop", "propose", "introduce", "characterize" over "combine", "modify", "extend".
- Avoid possessive forms for method/model names: write "the performance of METHOD" not "METHOD's performance".
- Never use contractions in academic writing (write "does not", not "doesn't").

### Structure Targets

- The target is a roughly 9-page conference paper body (for ML venues) with rich figures and tables.
- Section page budgets: intro ~1.5pp, related work ≥1pp, method ~2pp, experiments ~2.5pp, conclusion ~0.5pp.
- Keep related work ≥ 1 full page, organized by method family, not paper-by-paper.
- Figure captions must be self-contained — a reader should understand the figure from its caption alone.

### Mathematical Writing

- State assumptions formally before any theorem.
- Pair proofs with intuition — do not leave only bare statements in the main text.
- Keep notation consistent: scalars ($x$), vectors ($\mathbf{x}$), matrices ($\mathbf{W}$), sets ($\mathcal{X}$).
- Define every symbol at first use.

## Stage Output Requirements

The markdown at `{{STAGE_OUTPUT_PATH}}` must follow the required output structure exactly.

Additional expectations for this stage:

- `Key Results` should include:
  - what manuscript components were drafted
  - the central narrative and contribution framing
  - compilation status and any remaining issues
  - citation verification summary
  - places where the paper is currently strong or vulnerable
- `Files Produced` should list all .tex files, references.bib, paper.pdf, build_log.txt, citation_verification.json, self_review.json, and submission_bundle.zip.
- `Key Results` should also include the self-review score breakdown and any issues fixed during the self-review loop.
- `Suggestions for Refinement` should focus on argument clarity, claim discipline, paper structure, remaining [VERIFY] markers, or dimensions that scored below 7 in self-review.

## Important Constraints

- **Do not invent missing evidence** in order to strengthen the story.
- **Do not fabricate BibTeX entries** from memory — always verify via DBLP/CrossRef or mark with [VERIFY].
- **Do not fabricate experimental results, figures, or data.**
- Do not control workflow progression.
- Do not write outside the current run directory.
