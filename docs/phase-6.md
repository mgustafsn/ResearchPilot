# Phase 6 implementation

This document describes implemented behavior without changing the roadmap scope.

## Boundaries

- `search.py`: `_set_stage` writes the current pipeline stage in its own short
  transaction; `_prepare` calls it before each step; `start` seeds `RETRIEVING` and
  `finish` (and an expired lease) clears it.
- `search_persistence.py`: the `search_runs.stage` column.
- `papers.py`: `SearchRun.stage`.
- `frontend/app.js`: staged search status text, the research-summary line, the
  leading **All** cluster tab, and the paper-detail drawer.
- `frontend/styles.css`: drawer and summary styles.

No new endpoints. Retrieval, ranking, embedding, clustering, and naming are
unchanged. This phase is presentation plus progress reporting.

## Staged progress

`search_runs.stage` (`VARCHAR(20)`, nullable, added by `006_search_stage.sql`) holds
one of `RETRIEVING`, `ANALYZING`, `EMBEDDING`, `CLUSTERING`, `NAMING` while a search
runs, and `NULL` otherwise. `start` sets `RETRIEVING` inside the row insert.
`_prepare` advances it — `ANALYZING` before dedup and ranking, `EMBEDDING` before
the embedding call, `CLUSTERING` before k-means, and `NAMING` before the LLM calls
but only when `clusterCount >= 2`. Each write is
`UPDATE search_runs SET stage = ? WHERE id = ? AND status = 'SEARCHING'`, so a
superseded or already-finished run is left untouched. `finish` sets `stage = NULL`
on both the completed and failed paths; an expired lease does the same.

The frontend polls `GET .../searches` every two seconds while a search is running
(unchanged) and maps the reported stage to a sentence. Progress is coarse: one
stage at a time, with no per-item counts.

## Research map

For a completed search the Papers panel shows a summary line — paper count, subtopic
count, and publication-year range — above the cluster tab bar. The tab bar gains a
leading **All** tab (selected on load) that clears the cluster filter; selecting a
cluster tab filters the list and shows that cluster's description and keyword chips.
A single cluster, or an all-uncategorized result, still renders as a plain list.

## Paper detail drawer

Each paper row is a `role="button"` element; clicking it (or Enter/Space) opens a
right-side panel. The panel is `role="dialog"` with `aria-modal`, closes on the
backdrop click, the Escape key, or its Close button, moves focus to itself on open,
and restores focus to the row on close. It shows the full author list, publication
date and venue, publisher, citation count, relevance percentage, the paper's cluster
or subtopic name, linked DOI, source, publication, and open-access URLs, and the
complete abstract. Every value comes from the `ProjectPaper` already returned by
`GET .../papers`; the drawer makes no request.

## Deliberate omissions

No left-rail redesign or three-pane layout, no access-status labels (Phase 9), no
per-paper classification explanations (Phase 7), no manual rename, move, or "mark
irrelevant" (Phase 8), no settings page, and no research-coverage analysis. The
stage field is advisory UI state, not a job queue.

## References

- https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Roles/dialog_role
- https://html.spec.whatwg.org/multipage/interactive-elements.html
