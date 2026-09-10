# Phase 7 implementation

This document describes implemented behavior without changing the roadmap scope.

## Boundaries

- `llm.py`: `LlmProvider.explain_paper` and the `PaperExplanation` output model
  (validated, trimmed to `EXPLANATION_MAX`, blank rejected).
- `prompts.py`: `PAPER_EXPLANATION_SYSTEM` and `paper_explanation_messages`.
- `providers/openai.py`: `OpenAILlmProvider.explain_paper`, sharing the new
  `_completion` helper with `name_cluster` (request, status mapping, JSON parse).
- `search.py`: `SearchService.explain` plus its two session helpers
  (`_explanation_input`, `_store_explanation`).
- `search_persistence.py`: `project_papers.classificationExplanation`,
  `explanation_target` / `store_explanation`, and the `ExplanationUnavailable`
  exception.
- `api.py`: `POST /api/projects/{uuid}/papers/{paperId}/explanation` and a `422`
  handler for `ExplanationUnavailable`.
- `frontend/app.js`: the drawer's "Why it's in {subtopic}" section.

No change to retrieval, ranking, embedding, clustering, or naming.

## On-demand generation

The explanation for a paper's subtopic membership is generated the first time the
drawer opens for that paper, never at search time.

`SearchService.explain(project_id, paper_id)`:

1. `_explanation_input` (one read session) loads the project, the `project_papers`
   row, the joined `papers` row, and the `subtopics` row for the paper's
   `clusterId`. It raises `ProjectNotFound` (→ `404`) when the paper is not
   associated with the project, `ExplanationUnavailable` (→ `422`) when the paper is
   Uncategorized or its cluster has no subtopic, and returns the stored text
   immediately when the row already has one.
2. Otherwise `llm_provider.explain_paper(question, subtopic.name, PaperBrief(...))`
   runs outside any transaction, bounded at `NAMING_TIMEOUT_SECONDS`. The prompt
   carries the research question, the subtopic name, and the paper's title and
   abstract (abstract capped at 1200 characters); the model returns
   `{explanation}`, which is whitespace-collapsed and cut to 400 characters.
3. `_store_explanation` writes it to `project_papers.classificationExplanation` in a
   short transaction.

The endpoint is idempotent: a second call returns the stored value without touching
the model. An LLM failure raises `ProviderError` and, because this is a direct
request rather than a background pipeline step, it maps to `502`/`503` in the API.

## Storage

`007_classification_explanations.sql` adds the nullable
`project_papers.classificationExplanation` (`TEXT`). `GET .../papers` now returns
the field on each `ProjectPaper`. `replace_papers` deletes and recreates the
associations on every successful search, so a re-search clears all stored
explanations without extra code.

## Frontend

When the drawer opens for a paper in a named cluster it renders a
"Why it's in {name}" heading. If the paper already carries
`classificationExplanation` (from `GET .../papers` or an earlier drawer open in this
session) it is shown directly. Otherwise the section shows "Generating an
explanation…", POSTs the endpoint, and replaces the placeholder with the text or
with an error message and a Retry button. The returned text is cached back onto the
in-memory paper object. Uncategorized or unnamed clusters get no section.

## Deliberate omissions

No card-level "why it belongs here" line (drawer only), no batch or search-time
precompute, nothing for Uncategorized papers, no regenerate control beyond
retry-on-error, and the prompt receives the subtopic name but not its description.

## References

- https://platform.openai.com/docs/guides/structured-outputs
