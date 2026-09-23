# Project references and interface cleanup

Each project has a References tab independent of its current search results. Users can
save individual retrieved papers or enter their own citations, including drafts with
no external link. Manual entries hold title, authors, year, venue, DOI, URL, notes,
publication status, and an editable project-unique reference number. Numbers default
to the current maximum plus one and do not change when an entry is removed.

Saved provider papers retain provider metadata; only their project number and notes
are editable. Saving a paper again returns its existing reference. Matching normalized
DOIs attach the scholarly source to an existing manual entry while preserving the
manual citation. References survive subsequent searches and are removed with their
project. `GET/POST /api/projects/{id}/references`,
`POST /api/projects/{id}/references/from-paper/{paperId}`, and
`PATCH/DELETE /api/projects/{id}/references/{referenceId}` expose the library.

The Settings page now opens correctly and reads safe provider configuration flags from
`GET /api/settings/status`; it never returns keys or makes provider test calls. Search
query checkboxes have fixed sizing, and subtopic actions live in a Manage menu with
consistent spacing. The dashboard New project button has a stable hover background.
