# Reference reading status

Saved references now track **To read**, **Reading**, or **Read** independently of
publication status. The References tab saves status changes immediately and filters
locally with matching/total counts. Filters survive refreshes and tab switches but
reset to All when reopening the project. Failed saves keep the previous status and
show an error. Existing notes remain available.

`readingStatus` is returned by reference endpoints and accepted by manual creation
and PATCH: `TO_READ`, `READING`, or `READ`. Invalid values and null return 422.
An omitted PATCH field is unchanged. Scholarly metadata remains protected.

Migration 016 adds a non-null column with a database default of `TO_READ` and an
allowed-value constraint, backfilling existing references. The migration launcher
recognizes the new schema. Reading progress is project-owned and survives duplicate
saves, DOI linking, metadata updates, and replacement searches.

No bulk actions, cross-project queue, AI calls, or new dependencies are included.
API tests cover transitions, validation, ownership, and preservation. Chromium tests
cover filtering, refreshes, persistence, and failed saves. PostgreSQL tests cover
migration backfill and constraints as well as the API scenarios.
