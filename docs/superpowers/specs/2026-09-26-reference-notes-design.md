# Design: reference notes

Implements FR-N01–N06 from
[the review-workflow requirements](2026-09-24-review-workflow-requirements.md).

## Decisions

- No backend or schema change. Notes are saved with
  `PATCH /api/projects/{projectId}/references/{referenceId}` and the body `{notes}`, which
  already accepts at most 5,000 characters for both manual and provider references. The
  server trims surrounding whitespace, and the client uses the notes it gets back.
- Every reference row has an **Add notes** or **Edit notes** button. It opens an inline
  labeled textarea with a character counter, **Save notes**, **Cancel**, and a status line.
- Drafts are held in page memory in a `Map` from reference ID to text, save state, and error.
  They are never written to browser storage. `render()` builds editors from the map, so a
  filter change, a tab switch, a reading-status change, or a refresh keeps the draft. When a
  rerender replaces a focused editor, it gets its focus and caret back.
- Saving updates the cached reference and reapplies the filters. The save may remove the
  row, so the "Notes saved" confirmation goes in a live region in the toolbar. A failed save
  keeps the draft and shows the error, and the user can save again.
- A `beforeunload` guard is active while any draft is unsaved or still saving. Removing a
  reference that has a draft asks for confirmation that names the draft.
- `window.prompt` is no longer used for notes. **Edit** opens the metadata form and appears
  only on manual references. When that form edits an existing reference, it hides its notes
  field and leaves notes out of the PATCH, so it cannot overwrite a newer note. Creating a
  reference can still include initial notes.
- Saved notes are rendered as text with `white-space: pre-wrap`. Library search matches
  saved notes, never drafts.
