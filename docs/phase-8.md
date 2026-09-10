# Phase 8 implementation

This document describes implemented behavior without changing the roadmap scope.

## Boundaries

- `domain.py`: `SubtopicPatch` and `PaperPatch` request models.
- `search_persistence.py`: the `isRelevant` / `userModified` columns,
  `rename_subtopic`, `update_paper_association`, `cluster_ids`, `has_manual_edits`,
  and the `ManualEditsPresent` / `UnknownCluster` exceptions.
- `search.py`: `SearchService.rename_subtopic` and `update_paper`, and the
  `has_manual_edits` guard added to `start(force=False)`.
- `papers.py`: `ProjectPaper` gains `isRelevant` and `userModified`; `Subtopic`
  gains `userModified`.
- `api.py`: the two `PATCH` routes, the `?force` query parameter on the search
  route, and `409` / `422` handlers.
- `frontend/app.js`: the rename control, the drawer's move `<select>` and set-aside
  button, the "Show N set aside" toggle, and the re-search confirmation.

Retrieval, ranking, embedding, clustering, and naming are untouched. Manual edits
only rewrite rows the user chose.

## Edits

**Rename a subtopic.** `PATCH /api/projects/{uuid}/subtopics/{clusterId}` with
`{name, description?}` sets the row's `name`, `description`, and `userModified` and
returns the updated `Subtopic`. A missing subtopic row is `404`.

**Move a paper.** `PATCH /api/projects/{uuid}/papers/{paperId}` with `clusterId` set
to an existing cluster id in the project, or `null` for Uncategorized. A cluster id
not present in `project_papers` raises `UnknownCluster` (`422`).

**Set a paper aside.** The same `PATCH` with `isRelevant: false` (or `true` to
restore). At least one of `clusterId` / `isRelevant` must be supplied, enforced by
`PaperPatch`.

Any successful `PATCH` on an association sets `project_papers.userModified`. The
updated `ProjectPaper` is returned by re-reading the project's papers so the
response matches `GET .../papers` exactly.

## Re-search guard

Manual edits are not reconciled against a fresh clustering. `start(force=False)`
calls `has_manual_edits(project_id)` — a cheap `EXISTS` over `userModified`
subtopics and associations — and raises `ManualEditsPresent` (`409`,
`code: MANUAL_EDITS_PRESENT`) unless `force` is passed. `POST .../search?force=true`
proceeds; `replace_papers` and `replace_subtopics` then delete and recreate every
row, so the edits are dropped as part of the normal replacement. The check runs
inside the same locked transaction that creates the run, after the
already-searching and lease checks.

## Storage

`008_manual_edits.sql` adds `project_papers.isRelevant BOOLEAN NOT NULL`,
`project_papers.userModified BOOLEAN NOT NULL`, and
`subtopics.userModified BOOLEAN NOT NULL`, each created with a default so existing
rows backfill and then the default dropped. The SQLAlchemy columns carry
`default=True` / `default=False`, so `replace_papers` and `replace_subtopics` write
correct values without listing them.

## Frontend

A **Rename subtopic** button under the selected cluster's description swaps it for a
name input and description textarea; Save issues the `PATCH` and refreshes, Cancel
restores the view. A renamed subtopic shows an "edited" tag.

The paper drawer gains an organize row: a `<select>` of every cluster name plus
Uncategorized (change → `PATCH {clusterId}`), and a Set aside / Restore button
(→ `PATCH {isRelevant}`). Both close the drawer and refresh.

Set-aside papers are removed from the list and the tab counts; a
"Show N set aside" button reveals them dimmed. The state is per-project-view and
resets on a full refresh.

`api()` now attaches `code` and `status` from the error body, which the search
button uses to show "this project has manual changes" with a **Run anyway** button
that retries with `?force=true`.

## Deliberate omissions

No create / delete / merge subtopics — those need subtopics to have identities
independent of the k-means labels, a change to the persistence model deferred to a
later phase. No undo, no edit history, no per-edit attribution or timestamps, and
edits are discarded (after confirmation) on re-search rather than carried across.

## References

- https://developer.mozilla.org/en-US/docs/Web/HTTP/Methods/PATCH
