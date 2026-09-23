# OpenAlex retrieval

*Formerly Phase 2.*

This document describes implemented behavior without changing the roadmap scope.

## Boundaries

- `papers.py`: normalized metadata, search parameters/results, provider protocol.
- `providers/openalex.py`: HTTP calls and deterministic OpenAlex normalization.
- `search_persistence.py`: paper/run/association records and database operations.
- `search.py`: search lifecycle, timeout, transaction boundaries, and orchestration.
- `api.py`: dependency wiring, REST routes, and HTTP error mapping.
- `frontend/app.js`: a search action, basic results, and provenance in the existing UI.

Authoritative fields originate only from OpenAlex. Missing values stay missing;
UI fallbacks such as “Title unavailable” are display labels, not persisted metadata.
The paper UUID is derived from the validated provider identity, not title or DOI.
A venue is called a journal only when its supplied source type is `journal`; a host
organization is called a publisher only when its OpenAlex ID identifies a publisher.
Source links are validated HTTP(S) URLs. The frontend inserts metadata as text.

## Storage

`ResearchProject -> SearchRun` retains a snapshot for each attempt. `ProjectPaper`
links projects to globally reusable `Paper` records, records provider result order,
and references the successful search that produced the association. Project deletion
cascades to associations and search records; shared paper metadata remains reusable.
The second migration adds these tables without rewriting Phase 1 project data.

A short project-row lock claims each search. The claim is committed before network
I/O. Another short transaction verifies the run is still current, upserts provider
identities, replaces project associations, and commits completion atomically.
Failures record a safe error while retaining prior results. An interrupted worker's
lease expires after two minutes and can be reclaimed; this is not a persistent job
queue. Deployment with multiple processes requires PostgreSQL, as configured.

Search uses the research question verbatim, with inclusive year filters and a
100-paper default. Cursor pagination uses at most 100 results per request and at
most ten requests. Invalid identities are skipped and counted; a nonempty response
with no usable identities fails instead of erasing existing results. There are no
automatic retries. Provider ordering is preserved, with no local relevance claims.

## Deliberate omissions

No LLM/query expansion, DOI/title deduplication, relevance ranking, embeddings,
clustering, subtopics, classification explanations, research map, institutional
access, or independent open-access resolution. The basic list lets users verify
retrieval now, without introducing later-phase UI or fabricated metadata.

## References

- https://help.openalex.org/api/authentication/
- https://help.openalex.org/api/paging/
- https://help.openalex.org/api/filtering/
- https://help.openalex.org/data/works/attributes/
- https://help.openalex.org/data/sources/attributes/
