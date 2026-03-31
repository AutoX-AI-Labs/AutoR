# `_legacy/` — Deprecated Stage 07 Pipeline Modules

These modules implemented the original Python-driven writing pipeline for Stage 07.
They have been replaced by the prompt-driven architecture where Claude handles
LaTeX compilation, citation verification, and submission packaging directly
(same pattern as all other AutoR stages).

## Contents

| Module | Original Purpose |
|---|---|
| `writing_pipeline.py` | Orchestrated the multi-step writing pipeline |
| `latex_build.py` | Called `pdflatex`/`bibtex` from Python |
| `citation_verifier.py` | Verified BibTeX entries via DBLP/CrossRef |
| `submission_packager.py` | Bundled submission files into a zip |

## Why deprecated

The "Claude does everything, Python only validates" principle means Stage 07
now works like Stages 1-6 and 8: the prompt template (`prompts/07_writing.md`)
instructs Claude to perform all writing, compilation, and packaging steps.
Python code only validates the final artifacts via `validate_stage_artifacts()`.

## Safe to delete

These files have zero imports from the active codebase (`manager.py`,
`operator.py`, `utils.py`). They can be removed entirely once confidence
in the new pipeline is established.
