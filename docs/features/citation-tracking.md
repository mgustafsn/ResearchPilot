# Citation tracking

Saved references no longer receive automatic numbers. Each reference records whether it
is cited in the project's own writing (`isCited`) and, optionally, the number it has
there (`citationNumber`). Numbers are unique within a project and must be positive. A
number requires the reference to be cited; saving or creating a reference starts it
uncited and unnumbered unless the request says otherwise.

Unciting a numbered reference clears `citationNumber` and keeps the old value in the
read-only `previousCitationNumber`, so the References tab can offer to restore it.
Citing again does not reuse a number automatically. A number already used in the
project returns 409, and a number on an uncited reference returns 422.

The library lists references by title, A to Z. The References tab adds cited controls,
number entry and restore, and local filters for citation state, reading status, text,
and publication year. Filters run in the browser without extra requests.

Migration 018 renames `number` to `citationNumber`, makes it nullable, and adds `isCited`
and `previousCitationNumber` with their constraints. Existing references start uncited;
their old numbers move to `previousCitationNumber` so nothing is lost. The migration
launcher recognizes the new schema.

API tests cover transitions, validation, uniqueness, ownership, and preservation across
searches. Chromium tests cover the library workflow and filters, and PostgreSQL tests
cover the upgrade backfill. No new dependencies.
