# Implementation plan: reference notes

Design: [2026-09-26-reference-notes-design.md](../specs/2026-09-26-reference-notes-design.md).

1. API tests in `backend/tests/test_references.py` that pin the current PATCH behaviour. A
   notes-only update keeps metadata, citation state and numbers, and reading status. Empty,
   multiline, and 5,000-character notes are accepted. 5,001 characters returns 422. Notes
   that look like HTML come back unchanged.
2. Browser tests in `backend/tests/test_browser.py`: save and reload, Cancel sends no request,
   drafts survive filters, tab switches, status changes, and refreshes, a failed save keeps the
   text and can be retried, the counter and the length limit, inert HTML, the unload guard,
   the Remove confirmation, and the metadata form leaving notes alone.
3. Frontend: a `noteDrafts` map, an inline editor, a toolbar live region, a `beforeunload`
   guard, and no more `window.prompt`. The metadata form leaves out notes when editing.
4. Feature note, roadmap row, and version bump to 0.23.0.
