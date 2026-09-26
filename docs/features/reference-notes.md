# Reference notes

Every saved reference has an **Add notes** or **Edit notes** action. It opens an inline
plain-text editor with a character counter (up to 5,000), **Save notes**, and **Cancel**. Saving
sends only `{notes}` through the existing reference PATCH, so metadata, citation state and
numbers, and reading status stay the same. Cancel restores the saved text without a request.

Drafts live in page memory, keyed by reference ID, never in browser storage. The list
rebuilds editors from them, so filters, tab switches, reading-status changes, and background
refreshes keep the text, focus, and caret. A failed save keeps the draft and shows the
error for a retry. Leaving the page with an unsaved or pending draft triggers the browser's
unload warning. Removing a reference with an unsaved draft says so in the confirmation.

The `window.prompt` notes dialog is gone. **Edit** opens the metadata form, and only manual
references have it. When editing an existing reference, that form hides and leaves out notes,
so it cannot overwrite a newer note. New references may still start with notes. Saved notes
render as inert text with line breaks. Library search matches saved notes, not drafts.

No backend, schema, or dependency changes. API tests pin notes-only PATCH preservation and
the length limit. Chromium tests cover the editor workflow, failure and retry, the unload
guard, and the metadata form.
