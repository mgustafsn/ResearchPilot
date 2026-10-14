# Library first

Each project is a reference library. A title is enough to create one and add manual
citations, links, notes, reading status, and citation tracking. The References tab opens
first. Existing saved references and discovery results remain available.

The Discover papers tab keeps the current scholarly search and research map as an
optional way to find and save references. Search settings are grouped in the project
form. A research description is required only for discovery; without one, the tab
prompts the user to edit the project. Search and query suggestion requests return
`422` with `DESCRIPTION_REQUIRED` and do not create a search run. Discovery keeps its
existing provider, ranking, clustering, and explanation behavior once configured.

Migration 019 permits a null project research description. No new external integration,
reference categories, import format, or PDF storage is part of this release.
