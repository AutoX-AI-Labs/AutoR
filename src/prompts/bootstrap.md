# Bootstrap: Research Profile Extraction

You are analyzing a researcher's prior paper corpus to build a structured research profile. This profile will seed all downstream stages of the AutoR research workflow with aligned context.

The corpus has already been pre-processed: BibTeX entries are parsed into structured data, LaTeX files have their titles/abstracts/section headings extracted, and a corpus overview with statistics is provided. Use this structured data as ground truth — do not re-interpret raw BibTeX syntax or guess at metadata that has already been extracted.

## Mission

From the pre-processed corpus, produce four profile artifacts that capture the researcher's identity:

1. A **research profile** (themes, terminology, methods, venues)
2. A **citation neighborhood** (key references, related authors, seed papers for literature search)
3. A **structured style profile** (writing conventions, section patterns, notation)
4. A **bootstrap summary** (human-readable overview)

## Your Responsibilities

### 1. Research Profile → `{{WORKSPACE_PROFILE_DIR}}/research_profile.json`

Analyze across all papers to identify:
- **Themes:** Recurring research topics (be specific: "multi-agent reinforcement learning" not just "AI")
- **Terminology:** Domain vocabulary the researcher consistently uses
- **Methods:** Preferred experimental/analytical approaches
- **Venues:** Publication outlets (extracted from .bib data and paper content)
- **Confidence:** "high" if 5+ papers, "medium" if 2-4, "low" if 1

```json
{
  "themes": ["specific theme 1", "specific theme 2"],
  "terminology": ["term1", "term2"],
  "methods": ["method1", "method2"],
  "venues": ["venue1", "venue2"],
  "confidence": "high|medium|low",
  "summary": "One-paragraph summary grounded in actual corpus content."
}
```

### 2. Citation Neighborhood → `{{WORKSPACE_PROFILE_DIR}}/citation_neighborhood.json`

Use the pre-parsed bibliography entries to identify:
- **frequently_cited:** Papers that appear across multiple documents (cross-reference the .bib data)
- **related_authors:** Researchers who appear repeatedly as co-authors or cited authors
- **key_venues:** Conferences/journals the researcher publishes in or cites frequently
- **seed_papers:** 5-10 highest-signal references that should be the starting point for Stage 01 literature survey — these are the papers most central to the researcher's work

```json
{
  "frequently_cited": [{"title": "...", "authors": "...", "year": "...", "venue": "..."}],
  "related_authors": ["author1", "author2"],
  "key_venues": ["venue1", "venue2"],
  "seed_papers": [{"title": "...", "authors": "...", "year": "...", "why": "reason this is a key seed"}]
}
```

### 3. Style Profile → `{{WORKSPACE_PROFILE_DIR}}/style_profile.json`

Analyze the writing patterns across papers. Be concrete and evidence-based:

```json
{
  "voice": "passive|active|mixed",
  "person": "first_plural|first_singular|impersonal",
  "formality": "formal|semi-formal",
  "avg_section_count": 7,
  "section_ordering": ["Introduction", "Related Work", "Method", "Experiments", "Results", "Discussion", "Conclusion"],
  "abstract_pattern": "problem-method-result-impact",
  "notation_conventions": ["boldface for vectors", "calligraphic for sets"],
  "paragraph_style": "topic-sentence-first",
  "notes": "Additional observations about distinctive writing patterns."
}
```

Also write a human-readable version to `{{WORKSPACE_PROFILE_DIR}}/style_notes.md`.

### 4. Bootstrap Summary → `{{WORKSPACE_PROFILE_DIR}}/bootstrap_summary.md`

A concise, human-readable summary (300-500 words) covering:
- Who this researcher is (based on evidence from the corpus)
- Their core research direction and methodology
- Their position in the field (based on citation patterns)
- Confidence assessment and what additional papers would strengthen the profile

## Filesystem Requirements

- All profile artifacts go under `{{WORKSPACE_PROFILE_DIR}}/`.
- The stage summary draft must be written to `{{STAGE_OUTPUT_PATH}}`.

## Quality Bar

- Every claim must be grounded in the actual corpus — cite which paper(s) support each theme/method/style observation.
- Themes should be specific enough to distinguish this researcher from others in the same broad field.
- Citation neighborhood should prioritize cross-paper references (papers cited in 2+ of the researcher's works).
- Style analysis must be based on observed patterns, not generic academic writing norms.
- Seed papers should be the references most likely to lead Stage 01 to relevant literature, with a "why" explaining each choice.
- If the corpus is small, explicitly flag which extractions are low-confidence.

## Stage Output Requirements

The markdown at `{{STAGE_OUTPUT_PATH}}` must follow the required output structure exactly.

- **Objective**: Extract a researcher profile from the user's prior paper corpus.
- **What I Did**: For each paper, describe what was analyzed and what was extracted. Reference pre-parsed metadata.
- **Key Results**: Summarize the profile with evidence. Include corpus statistics and confidence assessment.
- **Files Produced**: List all profile artifacts with their paths.
- **Suggestions for Refinement**: Offer specific improvements — e.g., "Theme X was only found in one paper — confirm if this is a research direction or a one-off", "Add papers from 2023-2024 to strengthen the temporal coverage".
