# Phase 9 implementation

This document describes implemented behavior without changing the roadmap scope.

## Boundaries

- `papers.py`: `access_status()` and the `Paper.accessStatus` computed field.
- `search_persistence.py`: `replace_papers` now writes only real `papers` columns,
  so the computed field never reaches the insert.
- `frontend/app.js`: the access pill, the drawer's "Access & links" block, the
  "Open access only" filter, and the open-access count in the summary.
- `frontend/styles.css`: pill and filter styles.

No migration, no new endpoint, no pipeline change. Retrieval and normalization are
untouched; the status is read off fields OpenAlex already provides.

## Deriving the status

`access_status(is_open_access, open_access_url, abstract)` returns:

- `OPEN_ACCESS` when `is_open_access` is truthy **or** an `open_access_url` is
  present — a free full-text copy exists or is linked.
- `ABSTRACT_ONLY` when neither holds but an `abstract` is present.
- `UNKNOWN` otherwise.

`INSTITUTIONAL_ACCESS` from requirements §17 is reserved for future authenticated
access and is never returned.

`Paper.accessStatus` is a Pydantic `@computed_field` calling that function, so it
appears on every `Paper` / `ProjectPaper` response — including `GET .../papers` —
without being stored. Because `model_dump()` now includes computed fields,
`replace_papers` filters its values to the columns actually on `PaperRow` before the
upsert; this also guards any computed field added later.

## Why no resolver

OpenAlex's `open_access` block is itself aggregated from Unpaywall and other open
sources, so calling Unpaywall directly would mostly duplicate data we already have.
Requirements §19 explicitly allows an independent resolver to be added later; the
`Paper` fields (`isOpenAccess`, `openAccessUrl`) are the seam where one would write.

## Frontend

Each paper card shows an `OPEN ACCESS` / `ABSTRACT ONLY` / `UNKNOWN` pill next to its
title, and the drawer shows the same pill with a one-line explanation under a new
"Access & links" heading, followed by the DOI, source, publication-page, and
free-full-text links (the §16 transparency set). A **Open access only** button sits
beside the "Show N set aside" toggle and filters the visible list to
`OPEN_ACCESS` papers; the results summary now reads
`N papers · M subtopics · K open access · <years>`.

## Deliberate omissions

No Unpaywall or other independent open-access resolver. No `INSTITUTIONAL_ACCESS` or
library authentication (§18). No PDF downloading or storage (§36). No per-paper
manual access override.

## References

- https://help.openalex.org/hc/en-us/articles/24319977845015-Works#open-access
- https://docs.pydantic.dev/latest/concepts/fields/#the-computed-field-decorator
