# Phase 14 implementation

The primary navigation now covers all pages from requirements §32: New project,
Library, and Settings. The `/settings` route is served by the same frontend shell and
shows which providers supply scholarly metadata, embeddings, cluster naming, and
explanations. It explains that credentials are configured with backend environment
variables. The page is read-only: API keys are never sent to or edited from the
browser.
