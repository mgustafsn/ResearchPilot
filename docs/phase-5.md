# Phase 5 implementation

This document describes implemented behavior without changing the roadmap scope.

## Boundaries

- `llm.py`: the `LlmProvider` protocol (`name`, `model`, `name_cluster`) and the
  `PaperBrief` input and `ClusterNaming` output models. `ClusterNaming` trims rather
  than rejects overlong output. No I/O.
- `prompts.py`: the system prompt and the user-message builder, kept apart from the
  pipeline.
- `providers/openai.py`: `OpenAILlmProvider` calls the chat-completions endpoint
  with a strict JSON schema and maps failures to `LLM_*` `ProviderError` codes. It
  shares the OpenAI key, base URL, and HTTP client with the embedding provider.
- `search.py`: `_name_clusters` runs after clustering, one bounded call per cluster
  via `asyncio.gather`, and folds the result into `CompletedSearch`. `finish`
  persists subtopics and the naming error inside the existing transaction.
- `search_persistence.py`: the `SubtopicRow`, `search_runs.namingError`, and the
  `subtopics` / `replace_subtopics` repository methods.
- `papers.py`: the `Subtopic` response model and `SearchRun.namingError`.
- `api.py`: an `llm_provider` parameter and `GET /api/projects/{uuid}/subtopics`.
- `frontend/app.js`: the cluster tab shows the generated name; its description and
  keywords appear above that cluster's papers; a note is shown when naming failed.

Retrieval, ranking, embedding, and clustering are unchanged. Naming is the last
stage before a run is marked `COMPLETED`.

## Naming

Clusters are named only when `clusterCount >= 2` (a single cluster needs no label,
and the frontend shows no tabs for it). For each non-Uncategorized cluster, its top
six papers by relevance become `PaperBrief`s (title plus abstract, abstract capped
at 1200 characters). Each cluster is one `POST /chat/completions` with
`model=gpt-4o-mini`, `temperature=0`, and `response_format` a strict JSON schema for
`{name, description, keywords}`. The calls run concurrently, each bounded at 30
seconds.

The response content is parsed as JSON and validated into `ClusterNaming`:
whitespace is collapsed, the name is capped at 80 characters (a blank name is
rejected), the description at 500, and keywords are de-duplicated case-insensitively
and capped at eight. A blank name, non-JSON content, missing `choices`, or a schema
mismatch all raise `LLM_INVALID_RESPONSE`.

Naming is best-effort. `asyncio.gather(return_exceptions=True)` collects per-cluster
outcomes; successes are stored, and the first failure's code is recorded on
`search_runs.namingError`. The run still completes, and unnamed clusters keep their
`Cluster N` label. HTTP `401`/`403` → `LLM_UNAUTHORIZED`, `429` →
`LLM_RATE_LIMITED`, other non-`200` and transport errors → `LLM_UNAVAILABLE`. These
codes map to `503` in the API for completeness, but a naming failure never reaches
the HTTP response because it does not fail the search.

## Storage

`005_subtopics.sql` creates `subtopics` — `(projectId, clusterId)` primary key, a
`searchRunId` reference, `name`, `description`, and `keywords` (JSONB) — and adds
`search_runs.namingError`. On each successful search `replace_subtopics` deletes the
project's rows and inserts the current ones inside the same transaction as the paper
associations, so subtopics and clusters never disagree. A failed search leaves the
previous subtopics untouched. Deleting a project or a search run cascades.

## Deliberate omissions

No LLM query expansion, no per-paper classification explanations (Phase 7), no
research map (Phase 6), no manual rename or subtopic editing (Phase 8), no
`SubtopicPaper` table (`project_papers.clusterId` already maps papers to clusters),
no name reuse across searches, no streaming, and one vendor. The `LlmProvider`
interface and `prompts.py` leave room for the later LLM features.

## References

- https://platform.openai.com/docs/guides/structured-outputs
- https://platform.openai.com/docs/api-reference/chat/create
- https://platform.openai.com/docs/models/gpt-4o-mini
