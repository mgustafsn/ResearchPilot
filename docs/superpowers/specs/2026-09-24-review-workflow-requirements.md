# Plan: search within results, bulk actions, and reference notes

Status: proposed requirements. Each part gets its own design spec and implementation plan
before any code. Delivery order: reference notes, search within results, bulk actions.

## Goal and scope

Help a researcher find relevant items in an existing project, organize several papers
at once, and record reading notes without leaving the reference list.

Confirmed choices:

- Local search covers both discovered papers and saved references.
- Bulk selection is limited to the visible list and clears when filters or subtopics change.
- Notes use explicit Save and Cancel.

Keep the current vanilla frontend, provider interfaces, and single-user application.
These features must not invoke scholarly providers or LLMs. Exports, PDF searching,
semantic local search, rich-text notes, collaboration, and bulk deletion are excluded.
Bulk actions apply to discovered papers; bulk reference editing is a later feature.

## Functional requirements

### Search within results

Citation tracking (v0.22.0) already added a first version to the References tab: a
"Search library" box, a single exact "Year" field, and citation and reading filters. It
matches the whole query as one substring over all fields joined together, without Unicode
normalization. This part keeps those controls where possible, replaces the matching with
one shared function that implements FR-S03 for both tabs, and turns the year field into
the FR-S04 range.

| ID | Requirement |
| --- | --- |
| FR-S01 | Add a labeled “Search these papers” input above discovered papers and “Search references” above saved references. Describe them as searching existing items, distinct from “Find papers.” |
| FR-S02 | Paper search covers title, author names, abstract, venue, and DOI. Reference search covers displayed title, authors, venue, DOI, and saved notes; it does not fetch abstracts. Missing values behave as empty strings. |
| FR-S03 | Normalize text with Unicode NFKC and lowercase; trim and split the query on whitespace. Every term must occur as a literal substring in at least one searchable field, with terms allowed to match different fields. No regex, fuzzy matching, stemming, or query operators. Empty input matches all items. |
| FR-S04 | Add inclusive publication-year from/to filters in both tabs. Missing years remain visible without a year constraint and are excluded when either bound is set. Accept integer years 1–9999; show an inline error for invalid or reversed ranges and retain the last valid result set. |
| FR-S05 | Removed. Multi-source search (v0.21.0) shipped without per-paper provenance, so a source filter would reflect only each merged paper's primary source. Revisit if provenance is added. |
| FR-S06 | Combine text, year, open-access, set-aside, and subtopic filters with AND. Reference filters combine text/year with the existing reading-status filter. Sorting orders only matching items. |
| FR-S07 | Show matching and total counts, retain subtopic tabs with zero matches, and distinguish an empty project from no matches. A “Clear filters” action resets search/filter controls, selects All subtopics, and retains the chosen sort. |
| FR-S08 | Filter cached data in the browser without network requests per keystroke or filter change. Preserve input focus/caret. Debounce text entry by 150 ms; apply other valid filters immediately. Preserve separate tab filter states during refreshes and tab switches; reset them when reopening the project. |

### Bulk paper actions

| ID | Requirement |
| --- | --- |
| FR-B01 | Add a labeled checkbox to each paper and a tri-state “Select all visible” checkbox. Checkbox interaction must not open the paper drawer. Display the selection count and a Clear selection action. “Visible” means every rendered match in the active subtopic, including rows below the viewport. |
| FR-B02 | Clear selection immediately when search/filter values or subtopic change, on project/tab departure, and when starting a new literature search. Retain selection when sorting or refreshing the same completed result set; prune IDs no longer visible and clear it if the completed search ID changes. |
| FR-B03 | Support Save to references, Move to subtopic, Set aside, and Restore. Move choices include every saved subtopic and Uncategorized, independent of filters. Show Restore when selected papers include set-aside items. |
| FR-B04 | Apply an explicit action to exactly the submitted selection. Moving preserves relevance; setting aside/restoring preserves category. Reuse existing manual-override marking and explanation invalidation rules. Already-matching rows are harmless no-ops. |
| FR-B05 | Saving skips references already represented by paper ID or normalized DOI, using existing save/link behavior. Preserve their notes, reading status, citation state, and citation numbers. New references are uncited and unnumbered with To read status. Report newly saved versus already present counts. |
| FR-B06 | Execute each batch in one database transaction. Invalid membership, invalid destination, stale search identity, or persistence failure changes none of the selected items. Reject every bulk action while a literature search is active. |
| FR-B07 | While a request is pending, disable repeated submission and selection changes. On success, announce changed/unchanged counts, clear selection, and refresh affected views once. On failure, retain the selection for retry when the result set is still current, and show a specific inline error. Never report success before the response confirms it. |
| FR-B08 | Support 1–1,000 distinct paper IDs per request, matching the current project paper limit. Reject duplicates, empty/oversized lists, unsupported actions, and unknown request fields. Setting a target state and duplicate-aware saving must be safe to retry after a lost response. |

### Better reference notes

| ID | Requirement |
| --- | --- |
| FR-N01 | Provide Add notes / Edit notes on every saved reference, including manually created citations. Open an inline labeled plain-text textarea with Save notes, Cancel, and a character counter. Support empty notes and multiline text up to the existing 5,000-character API limit. |
| FR-N02 | Save only the notes field through the existing reference PATCH endpoint. Preserve metadata, citation state, current and previous citation numbers, and reading status. Cancel restores the last saved text and sends no request. Display Unsaved changes, Saving, Saved, and an actionable save error as appropriate. |
| FR-N03 | Keep drafts in page memory keyed by reference ID, independent of rendered rows. Filter changes, tab switches, background refreshes, and reading-status changes must not discard drafts. Failed saves retain the text and allow retry. Do not write drafts to browser storage. |
| FR-N04 | Warn on page navigation/reload when drafts are dirty or saves are pending, using the browser's unload protection. An explicit Cancel discards that draft; deleting a reference with a draft explicitly confirms that both the reference and its draft will be removed. Browser/process crashes are outside the draft-persistence guarantee. |
| FR-N05 | Render saved notes as inert text with preserved line breaks. Search matches saved notes, not uncommitted drafts; saving reapplies reference filters and may remove a no-longer-matching row, with success feedback outside that row. |
| FR-N06 | Use the library's cited controls for optional manual citation-number editing and provide a dedicated notes action. Keep the existing manual reference form for metadata. Existing references edit notes only through the dedicated notes editor so a metadata form cannot overwrite a newer note; new-reference creation may still include initial notes. |

## Non-functional requirements

These are proposed acceptance targets, not measurements of an implementation.
Use deterministic local fixtures, Chromium, and the existing JUnit measurement approach.
Performance tests use a CI ceiling of three times the target, consistent with the current suite.

| ID | Requirement and verification |
| --- | --- |
| NFR-P01 | With 1,000 papers or 1,000 references loaded, local filtering completes within 300 ms after the debounce expires; CI ceiling 900 ms. Record the slowest of ten representative queries/filter changes, including no-match and all-match cases. |
| NFR-P02 | Select-all and clear-selection update 1,000 rows within 200 ms; CI ceiling 600 ms. Typing and selection generate zero application API/provider/LLM calls. |
| NFR-P03 | On local PostgreSQL, each 250-paper bulk action completes within 1 s; CI ceiling 3 s, measured at the API boundary. Verify 1,000-item correctness separately. Use one mutation request per user action, rather than one per paper. |
| NFR-P04 | A notes PATCH completes within 300 ms on local PostgreSQL; CI ceiling 900 ms. Saving feedback appears by the next rendered frame, without blocking typing elsewhere. |
| NFR-R01 | Inject a failure after part of a batch has been processed and verify full rollback. Concurrent search/bulk operations serialize on the project lock; a stale batch returns 409 without changes. Test on PostgreSQL as well as basic SQLite coverage. |
| NFR-R02 | Duplicate retries never create duplicate references or overwrite existing notes/status. Concurrent citation-number changes preserve project uniqueness, while manual and bulk saves allocate no numbers; controlled conflicts return 409 without partial commits. |
| NFR-R03 | Simulated timeout, 422, 409, and 503 responses preserve notes drafts and appropriate selections. Refreshes cannot replace dirty editor content. Late responses cannot modify a different project or reference's editor. |
| NFR-A01 | Every control works with keyboard alone and has an accessible label. Selection checkboxes expose checked/mixed state; save/result feedback uses a polite live region. Focus remains predictable after filtering, saving, canceling, and removing rows. Verify with Playwright plus manual keyboard review. |
| NFR-A02 | At 390, 768, and 1440 px widths, and at 200% zoom, controls remain usable without horizontal page overflow. Test long titles, author lists, notes, DOI strings, and empty states. Text contrast must meet 4.5:1 for normal text, with visible focus indicators and no color-only status. |
| NFR-S01 | Search text, notes, and metadata render as inert text; test HTML/script-shaped payloads. Validate batch project membership and destinations server-side, reject unknown fields and invalid types, and retain the 5,000-character notes limit. |
| NFR-M01 | No new runtime dependencies or external integrations. Preserve single-item endpoints and existing browser workflows. Keep filtering, selection state, and notes drafts separate from DOM rebuilding; backend bulk logic reuses domain rules within one shared transaction. |
| NFR-O01 | Log bulk action type, project ID, requested/changed counts, duration, and outcome code. Do not log notes, local search terms, provider payloads, or secrets. Emit performance measurements through the existing test reporting setup. |

## Interfaces and implementation

### Local state and rendering

Maintain cached paper/reference arrays and separate filter state for each tab. Extract
small pure matching functions rather than introducing a framework. Build search controls
once; update counts and list contents without replacing the focused search input.
Keep selected paper IDs and note drafts outside render functions. All eligible paper
rows remain rendered; pagination and virtualization are not needed for this release.

### Bulk endpoint

Add `POST /api/projects/{projectId}/papers/bulk-actions` with a validated discriminated
request shape:

```json
{
  "action": "MOVE",
  "paperIds": ["paper-uuid"],
  "expectedSearchRunId": "completed-search-uuid",
  "targetClusterId": 3
}
```

Allowed actions: `SAVE_REFERENCES`, `MOVE`, `SET_ASIDE`, `RESTORE`.
`targetClusterId` is required only for MOVE; null means Uncategorized and other actions
reject this field. Require the completed search ID that supplied the rendered results,
not the newest failed attempt. Under the project lock, validate the entire request
before changing rows. Reuse the existing search lease/active-search checks.

Return `{action, requestedCount, changedCount, unchangedCount}` on success. For saving,
changed means newly created references; existing references count as unchanged even
when linked using existing DOI behavior. The frontend reloads the affected collections
after success. Use 422 for malformed requests or invalid target categories, 404 for
missing projects or papers outside the project, 409 for active/stale searches or
concurrent-write conflicts, and the existing 503 database-failure handling.

Refactor transaction boundaries where needed so a batch does not call independently
committing single-item services. Manual citation-number writes rely on the project-scoped
database uniqueness constraint; bulk saving never allocates numbers. Maintain stable paper
ordering when locking shared records.

### Notes and compatibility

Reuse `PATCH /api/projects/{projectId}/references/{referenceId}` with `{notes: text}`.
No new notes schema or database migration is expected. Multiple browser tabs retain
the current last-successful-save-wins behavior; cross-tab conflict detection is outside
this single-user release. In-page drafts must nevertheless survive all normal rerenders.

Multi-source search shipped without per-paper provenance: a merged paper keeps one
`source`. This plan therefore has no source filter and defines no provider model.

## Delivery and acceptance

1. **Notes editing:** implement independent drafts, explicit save/cancel, feedback,
   navigation protection, and removal of prompts. Test manual/provider references,
   empty/multiline/5,000-character notes, rejection above the limit, failed saves,
   filtering and tab switching with drafts, and metadata/status preservation.
2. **Search within results:** implement the shared pure matching function and cached
   rendering, upgrade the existing reference controls, then add the paper controls, counts,
   and empty states. Test mixed-case/Unicode text, multiple terms, missing metadata,
   inclusive years, invalid ranges, composed filters, sorting, and zero network calls
   during local filtering.
3. **Bulk actions:** implement validation, project locking, shared transactions, and API
   tests before the selection toolbar. Test select-all scope, filter clearing, sort
   preservation, retries, existing references, invalid IDs, wrong-project categories,
   stale search IDs, active searches, rollback, and concurrent manual citation numbering
   on PostgreSQL.
4. **Integrated acceptance:** filter a populated project, select matching papers, save
   them once, move a subset, set aside and restore another subset, find saved references,
   edit/cancel/save notes, and reload to verify persisted data. Include duplicate-save
   retries and a simulated failed notes save. Run responsive and keyboard checks plus
   all new NFR tests and the existing suite.

Each feature ships separately using the repository's feature branch, feature note, and
minor-version convention. Update the roadmap and README when implementation ships,
not to mark this plan as already delivered. Run lint, formatting checks, JavaScript syntax
checks, package build, and the full suite before sign-off; use a separate disposable
PostgreSQL database for integration and concurrency tests. Never point tests at the
user's project database. No production feature flags or additional monitoring service
are required for this local application.
