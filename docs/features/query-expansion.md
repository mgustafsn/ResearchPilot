# Query expansion

*Formerly Phase 10.*

This phase adds the first query-expansion slice. The original research question is always
searched; a structured LLM response may add up to five related scholarly queries. Retrieval
fans out across those queries, divides the configured paper limit between them, then uses the
existing deduplication and ranking pipeline. The exact queries are persisted on each search run
and shown in the UI.

Query expansion is best-effort. Provider, timeout, and malformed-output failures fall back to
the original question so search availability does not depend on the optional LLM step.
Before a search, users can regenerate saved suggestions and enable or disable each one. The
original research question remains mandatory and is always included in retrieval.
