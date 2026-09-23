# ResearchPilot — Full Prompt Log

This is the complete, unabridged prompt log referenced by `docs/report.md` §§3.2,
3.3, and 4.5. It covers every phase of construction (SDD) and every vibe-coding
iteration chain, in chronological order, cross-referenced to the commit that landed
each one.

**On authenticity:** no per-session chat transcript was archived for this project, so
the entries below are reconstructed from the artifacts that *do* exist for every
phase — the commit history, each `docs/phase-N.md`, `docs/requirements.md`, and the
project's memory notes — rather than pasted verbatim from a saved conversation. Where
a phase's implementation matched its specification on the first pass, that is stated
plainly rather than invented as a struggle; where the phase doc or commit sequence
shows real friction (a validation rule added after the fact, a guard added because an
edit case was missed, a multi-commit UI chain), that friction is reported as it
actually shows up in the repository. This distinction matters for §7 of the report,
which draws its bottleneck analysis from the entries marked **Friction** below.

Each entry gives: the original prompt (reconstructed), its purpose, the reasoning for
issuing it, what was expected, what actually happened, and — where applicable — how
the prompt or specification was refined afterward.

---

## Part A — SDD Phase Prompts

### Phase 1 — Project CRUD and PostgreSQL foundation

> "Implement Phase 1 per `docs/roadmap.md`: project creation, listing, update, and
> delete, backed by PostgreSQL, with a first SQL migration. Follow the domain model
> in `docs/requirements.md` §25 for `ResearchProject`. Set up the git worktree/branch/
> verification-gate workflow described for this repo before merging."

- **Purpose:** establish the foundation every later phase builds on — persistence,
  API scaffolding, and the phase-cycle process itself (Section 4.4 of the report).
- **Reasoning:** nothing else in the roadmap can be built or tested without a
  project to attach it to; this had to be Phase 1 by dependency, not preference.
- **Expected:** basic CRUD routes, a `ResearchProject` table, and the first numbered
  migration, verified by a green test suite.
- **Actual — matched expectations.** The requirement was concrete (§3.1's example
  fields, §25's model) and had no ambiguous UI or algorithmic component, so this
  phase needed no refinement round.
- **Commit:** `a41a932` "Implement Phase 1 project CRUD and PostgreSQL foundation."

### Standalone — Workspace restyle (not part of any cluster-UI chain)

> "Restyle the project workspace to match this reference design." (screenshot
> attached)

- **Purpose:** bring the freshly-scaffolded Phase 1 UI in line with an intended visual
  direction before building further screens on top of it.
- **Reasoning:** cheaper to fix the visual baseline once, early, than to restyle every
  screen built on top of it later.
- **Expected:** a closer match to the provided reference image.
- **Actual — matched expectations.** This was a single-shot vibe-coding request with
  no further iteration needed; it is unrelated to the later cluster-tab chain
  (Part B) even though both are UI work — this one predates clustering entirely
  (Phase 4 had not yet been built).
- **Commit:** `9f0b8b3` "Restyle project workspace to match the reference design."

### Phase 2 — OpenAlex retrieval and normalized paper persistence

> "Implement Phase 2: a `PaperProvider` protocol and an OpenAlex implementation, per
> `docs/requirements.md` §5. Normalize results to the `Paper` shape in §5, using
> cursor pagination, and persist a `SearchRun` snapshot per attempt per §23/§26."

- **Purpose:** the first real external data source — replacing nothing (there was no
  prior provider), but establishing the "facts only from providers" boundary that
  every later phase depends on.
- **Reasoning:** requirements §22 forbids LLM-invented citations; the provider
  abstraction is the mechanism that makes that enforceable rather than aspirational.
- **Expected:** normalized papers with title, authors, DOI, etc., retrieved and
  displayed with basic provenance.
- **Actual — friction found and resolved within the phase, before merge.** Two
  judgment calls were not fully specified and had to be tightened during review
  rather than left to the agent's first guess: (1) whether to label a venue a
  "journal" whenever OpenAlex supplied *any* venue name, versus only when OpenAlex's
  own source-type field says `journal` — the looser reading would have mislabeled
  conference proceedings and preprint servers as journals; (2) how many pages to
  pull before giving up on a slow or huge result set, since the requirement said
  "at least several dozen papers" but not an upper bound — an unbounded loop against
  a live API was judged unacceptable, so a fixed cap (100 results per page, at most
  ten pages) was added.
- **Refined instruction:** "Only call it a journal when the source's own type is
  `journal`; call the host organization a publisher only when its OpenAlex ID
  identifies one. Cap retrieval at 100 results per page, at most 10 pages, and skip
  — not fail on — an individual record with no usable identifier."
- **Resulting quality:** both rules are now stated as explicit boundaries in
  `docs/features/openalex-retrieval.md` rather than left implicit in code, specifically so a later phase
  touching this file does not reintroduce the looser reading.
- **Commit:** `6b62b9a` "Implement Phase 2 OpenAlex retrieval and normalized paper
  persistence."

### Phase 3 — Deduplication and relevance ranking

> "Implement Phase 3: deterministic deduplication (DOI, then identifier, then
> normalized title, per §6) and a lexical relevance score (§8), as pure functions
> with no I/O. Persist `relevanceScore` per `ProjectPaper` and `duplicateCount` per
> `SearchRun`."

- **Purpose:** turn a raw, possibly-duplicated result list into a ranked, deduplicated
  one before anything gets embedded or clustered — cheaper to fix here than to
  cluster near-duplicate papers separately.
- **Reasoning:** the requirements explicitly prefer deterministic algorithms over LLM
  calls for anything that is really pattern-matching, per §39's core principle.
- **Expected:** a merged list with no obvious duplicates and a plausible relevance
  ordering.
- **Actual — one edge case caught during review, addressed before merge.** Merging
  purely by normalized title risked collapsing two genuinely different papers that
  happen to share a title (a known occurrence in scholarly literature — reprints,
  translated titles, unrelated papers with generic names) whenever one of them also
  happened to carry an explicit, different DOI. The initial title-matching rule
  would have merged them anyway.
- **Refined instruction:** "Don't let a normalized-title match override two distinct,
  explicit DOIs — treat that as two different papers, not a duplicate."
- **Resulting quality:** `docs/features/deduplication-and-ranking.md` states this rule explicitly ("An identical
  normalized title does not merge two records that carry different explicit DOIs").
- **Commit:** `50b1493` "Implement Phase 3 deduplication and relevance ranking."

### Phase 4 — Embedding generation and clustering

> "Implement Phase 4: an `EmbeddingProvider` protocol backed by OpenAI
> `text-embedding-3-small`, and deterministic k-means clustering with an outlier
> rule, per §9. Make the clustering algorithm replaceable. Reuse stored embeddings
> when the paper, provider, model, and input already match."

- **Purpose:** move from a flat ranked list to semantically grouped subtopics —
  the point of the whole product.
- **Reasoning:** §9 is explicit that the LLM must not own clustering end-to-end;
  embeddings-plus-a-real-algorithm was specified, not optional.
- **Expected:** papers grouped into a sensible number of clusters without a fixed,
  hardcoded cluster count.
- **Actual — matched the algorithmic specification on the first pass**, including
  the harder pieces (picking `k` by silhouette score, demoting outliers, canonical
  cluster relabeling) — because §9 and the accompanying pipeline diagram left very
  little open to interpretation. **The one place this phase did leave something
  open was presentation:** it shipped a plain dropdown as the cluster selector,
  since no UI mock existed for this screen yet. That gap became the seed of the
  Part B vibe-coding chain immediately afterward.
- **Commit:** `b8c40fc` "Implement Phase 4 embedding generation and clustering."
  (UI iteration continues in Part B.)

### Phase 5 — LLM cluster naming and descriptions

> "Implement Phase 5: for each cluster with ≥2 members, send its top papers by
> relevance to an LLM and get back a structured `{name, description, keywords}`
> using a strict JSON schema, per §10. Naming must be best-effort — a failure on one
> cluster must not fail the whole search."

- **Purpose:** turn anonymous cluster numbers into the human-readable subtopics the
  product is named for.
- **Reasoning:** §21 requires structured LLM output, validated before storage —
  free-text parsing was ruled out from the start, not discovered as a problem later.
- **Expected:** plausible, grounded cluster names generated concurrently, one call
  per cluster.
- **Actual — the specification anticipated the main risk, so the "fix" is built into
  the first version rather than a later patch.** An LLM asked to name a cluster can
  return non-JSON text, an empty name, or an overlong description; rather than
  discover this via a production failure, the response schema was written strict
  from the outset (`temperature=0`, a JSON schema, explicit caps: name ≤80 chars,
  description ≤500, keywords deduplicated and capped at 8, a blank name rejected
  outright as `LLM_INVALID_RESPONSE`). The one thing that *did* require a real
  decision during implementation was what "best-effort" means operationally: it was
  specified as "don't fail the search," but not whether a partially-named result set
  should still show a warning.
- **Refined instruction:** "Collect all per-cluster naming outcomes with
  `asyncio.gather(..., return_exceptions=True)`; store every success, keep failed
  clusters as `Cluster N`, and record the first failure's error code on the search
  run so the UI can show a soft warning without failing the request."
- **Resulting quality:** naming failures are visible to the user (a note in the UI)
  without ever surfacing as an HTTP error, satisfying both "best-effort" and
  "search transparency" (§16) at once.
- **Commit:** `041e817` "Implement Phase 5 LLM cluster naming."

### Phase 6 — Research map UI, staged progress, and paper detail drawer

> "Implement Phase 6: a `search_runs.stage` column reflecting pipeline progress
> (`RETRIEVING`/`ANALYZING`/`EMBEDDING`/`CLUSTERING`/`NAMING`), a research-map summary
> line, an 'All' tab, and a paper-detail drawer per §12, showing every field already
> returned by `GET .../papers` with no extra request."

- **Purpose:** replace an opaque, frozen-looking wait with visible progress, and give
  the user a way to inspect one paper in depth.
- **Reasoning:** §27 explicitly calls out that literature searches "may take several
  seconds" and the UI must show progress rather than appear frozen — a stated
  non-functional expectation, not a nice-to-have.
- **Expected:** a progress line that advances through pipeline stages, and a
  drawer that opens/closes cleanly.
- **Actual — one omission caught during review, added before merge, not before the
  first draft.** The first drawer implementation opened and closed correctly but had
  no explicit accessibility semantics or focus management — clicking a paper row
  opened a panel, but keyboard-only navigation and screen readers had no signal that
  a dialog had appeared.
- **Refined instruction:** "Give the drawer `role=\"dialog\"` and `aria-modal`, move
  focus into it on open and back to the triggering row on close, and make it
  dismissible by Escape and backdrop click, not only its Close button."
- **Resulting quality:** the drawer is keyboard- and screen-reader-navigable, which
  `docs/features/research-map.md` documents as a explicit requirement of the implementation, not an
  afterthought bolted on outside the phase.
- **Commit:** `ee3e6e5` "Implement Phase 6 research map UI."

### Phase 7 — Classification explanations

> "Implement Phase 7: generate a per-paper explanation of subtopic membership only
> when the drawer opens for that paper (never at search time), using the research
> question, subtopic name, and the paper's own title/abstract. Cache it; a second
> request for the same paper must not call the model again."

- **Purpose:** satisfy §11's explainability requirement without paying an LLM call
  per paper per search, most of which a user will never open.
- **Reasoning:** an eager, search-time explanation for every paper would multiply
  LLM calls by paper count for no guaranteed benefit; on-demand generation ties cost
  to actual user interest.
- **Expected:** a short, grounded explanation appearing under a "Why it's in
  {subtopic}" heading, generated once and reused after.
- **Actual — matched expectations,** including the caching behavior on the first
  pass, because the requirement ("generate once, reuse after," "grounded only in
  title/abstract, do not restate the abstract") was specific enough to implement
  directly against. The one real design decision left to the agent — how an LLM
  failure at this on-demand call site should surface, since it is a *direct* request
  rather than a background pipeline step other phases could fail silently in — was
  resolved by mapping it to a `502`/`503` with a Retry control in the UI, rather than
  the best-effort fallback Phase 5 used for search-time naming.
- **Commit:** `717bc97` "Implement Phase 7 classification explanations."

### Phase 8 — Manual organization

> "Implement Phase 8: let a user rename a subtopic, move a paper between subtopics,
> or set a paper aside, per §14. These edits must never be silently overwritten —
> a subsequent automatic search over edited data needs explicit confirmation."

- **Purpose:** requirements §14 is unambiguous that AI organization must always be
  user-editable, and §14's closing line — "the user's manual changes should never be
  silently overwritten" — is a correctness requirement, not a UI nicety.
- **Reasoning:** without a guard, a user who renamed a subtopic and then ran a new
  search (e.g. to add more papers) would have that rename silently discarded when
  `replace_subtopics` deleted and recreated every row — a bug, not a feature,
  relative to the stated requirement.
- **Expected:** rename/move/set-aside endpoints that work, plus *some* protection
  against re-search clobbering them.
- **Actual — the most significant friction of any SDD phase in this project.** The
  first working version implemented the edit endpoints correctly but treated
  re-search as an ordinary operation: running a new search over a project with
  manual edits would proceed and replace everything, exactly the silent-overwrite
  the requirement forbids. This was caught in review against the requirement text,
  not by a failing test (no test yet existed for the interaction, since it spans two
  features written in different phases).
- **Refined instruction:** "Before starting a search, check whether the project has
  any user-modified subtopic or paper association; if so, refuse with a `409` and a
  distinct error code unless the caller explicitly passes `force=true`. The UI must
  surface this as an explicit 'this project has manual changes — Run anyway?'
  confirmation, not a silent retry."
- **Resulting quality:** `has_manual_edits` is now a cheap existence check run inside
  the same locked transaction that creates a search run, and the concurrency-focused
  Postgres-only test suite added a dedicated case for it. This is the single clearest
  example in the project of a requirement that was correctly *stated* from Phase 1
  but not correctly *implemented* until a second pass caught the gap — the kind of
  bottleneck Section 7.2 of the report generalizes from.
- **Commit:** `67da48a` "Implement Phase 8 manual organization."

### Phase 9 — Open-access status and links

> "Implement Phase 9: add `Paper.accessStatus` as a computed field —
> `OPEN_ACCESS`/`ABSTRACT_ONLY`/`UNKNOWN`, `INSTITUTIONAL_ACCESS` reserved and never
> emitted — derived from fields OpenAlex already supplies. No migration, no new
> resolver."

- **Purpose:** satisfy §17's access-status requirement using data already available,
  deferring the independent-resolver option in §19 rather than building it
  speculatively.
- **Reasoning:** OpenAlex's own open-access data already aggregates Unpaywall, so a
  separate resolver call would mostly duplicate information already on hand — an
  explicit reason recorded in `docs/features/open-access.md`, not an oversight.
- **Expected:** an access pill on each paper card and its drawer, with no schema
  change since the value is derived, not stored.
- **Actual — a real, concrete bug was introduced and caught in the same phase.**
  Because Pydantic's `@computed_field` shows up in `model_dump()` by default, the
  new `accessStatus` field started appearing in the dictionary that
  `replace_papers` fed directly into building its SQL insert — and `accessStatus` is
  not a real `papers` table column, so the insert would have referenced a
  nonexistent column the first time this code path actually ran against a
  populated result set. This was caught during human-in-the-loop review against
  `AGENTS.md`'s persistence conventions, not by an existing test (no test yet
  exercised a computed field reaching this path).
- **Refined instruction:** "Filter `model_dump()` down to columns that actually
  exist on `PaperRow` before building the insert in `replace_papers` — and keep that
  filter in place so any *future* computed field is safe by construction, not just
  this one."
- **Resulting quality:** the fix is structural (a filter at the persistence
  boundary) rather than a one-off patch naming `accessStatus` specifically, which is
  why it is documented in `docs/features/open-access.md` as guarding "any computed field added
  later." This is the flagship example in `docs/report.md` §5.2's Code Audit Log.
- **Commit:** `86f9b42` "Implement Phase 9 open-access status and links." (UI
  iteration continues in Part B.)

### Phase 10 — Structured query expansion

> "Implement Phase 10: let an LLM propose up to five additional scholarly queries
> from the research question and keywords, per §7, using a strict JSON schema. The
> original question is always searched regardless of what the LLM returns. On any
> provider, timeout, or malformed-output failure, fall back to the original question
> alone — search must never depend on this step succeeding."

- **Purpose:** widen retrieval beyond a possibly-too-narrow user query, per §7's
  stated rationale, while keeping the mandatory original query as a floor.
- **Reasoning:** requirements explicitly frame query expansion as an enhancement, not
  a dependency — "if query expansion fails, the original question is used" is stated
  as a requirement, not left to be discovered as good practice later.
- **Expected:** 2–5 additional grounded queries shown to the user, individually
  enabled/disabled, with retrieval fanning out across whichever are enabled.
- **Actual — matched expectations.** Because the fallback behavior was specified
  up front rather than added reactively, there was no failure mode to discover
  during implementation — the "what if this LLM call fails" case was designed in
  from the start, unlike Phase 8's re-search guard, which was retrofitted.
- **Commit:** part of the current (not yet merged to `main`) working-tree changes;
  documented in `docs/features/query-expansion.md`. See §7.2 of the report for why this and the two
  phases below are implemented and verified but not yet through the full
  merge/version-bump ritual.

### Phase 11 — Deterministic relevance filtering

> "Implement Phase 11: filter out papers scoring below a 0.10 relevance threshold
> before embedding and clustering, per §8. Filtered papers must not be saved as
> project papers, but the search run must record and display how many were
> filtered, and manual relevance overrides on retained papers must never be
> overwritten by this step."

- **Purpose:** stop irrelevant retrieval noise from consuming a cluster slot or
  diluting a subtopic's LLM-generated description.
- **Reasoning:** clustering an unfiltered set risks a whole "cluster" forming around
  loosely-related noise papers, which would then get a plausible-sounding but
  misleading LLM-generated name — filtering upstream of clustering is cheaper than
  trying to detect a bad cluster after the fact.
- **Expected:** a visibly smaller, more relevant paper set with a transparent
  filtered-count shown in the UI (§16's transparency requirement).
- **Actual — matched expectations,** with the one implementation decision being
  where in the pipeline the filter should sit relative to the existing manual
  relevance-override machinery from Phase 8; the answer (filter runs before
  clustering, and only on the automatic pipeline's candidates, never touching an
  already-retained project paper's manual override) followed directly from Phase
  8's existing "manual edits are never overwritten" rule, so no new rule had to be
  invented.
- **Commit:** part of the current working-tree changes; documented in
  `docs/features/relevance-filtering.md`.

### Phase 13 — On-demand explanations on paper cards

> "Extend Phase 7's on-demand explanation to the paper card itself, not only the
> drawer: support loading and retry states inline on the card, reuse the cached
> explanation when present, and refresh if the explanation's context (search run,
> question, or category) changes while a request is in flight."

- **Purpose:** surface the same trust-building explanation Phase 7 built for the
  drawer at the point a user is actually scanning cards, without a click first.
- **Reasoning:** Phase 7 deliberately scoped explanations to the drawer only
  (`docs/features/classification-explanations.md`'s "Deliberate omissions" names "no card-level ... line"
  explicitly); Phase 13 lifts that scope once the drawer version had already proven
  the caching and generation logic correct.
- **Expected:** the same explanation text and caching behavior as the drawer, now
  also inline on the card.
- **Actual — matched expectations,** reusing Phase 7's service-layer logic
  unchanged; the only new behavior needed was a race-condition guard for the case
  where the underlying context changes (e.g. a re-search completes) while an
  explanation request for the old context is still in flight — resolved by having
  the card refresh from the project rather than trust a stale in-flight response.
- **Commit:** part of the current working-tree changes; documented in
  `docs/features/card-explanations.md`.

---

## Part B — Vibe-Coding Iteration Chains

### B.1 — Cluster selector, after Phase 4

Phase 4's SDD implementation (`b8c40fc`) shipped a plain `<select>` dropdown as the
cluster selector, since no visual specification existed for this screen. Four
short, reactive rounds followed:

| # | Prompt | Expected | Actual | Why it needed another round |
| - | --- | --- | --- | --- |
| 1 | "Render each cluster as a collapsible section instead of a dropdown." | A clearer, one-cluster-at-a-time view. | Functionally fine, but every section rendered open on the page simultaneously — nothing was actually filtered, and long result sets became unwieldy. | "Collapsible section" was read as "always-visible, individually-foldable section," not "one exclusive view" — the prompt didn't say sections were mutually exclusive. |
| 2 | "Switch the cluster view to a tab bar instead." | Only one cluster's papers visible at a time. | Correct exclusivity, but the tab bar defaulted to the first cluster, so a fresh page load showed an arbitrary subset instead of everything retrieved. | The prompt specified the control type but not its default state. |
| 3 | "Make the cluster tabs act as filter pills, with none selected by default." | An "all papers" default, with optional filtering by tapping a pill. | Correct behavior, but inactive pills used the same filled visual style as active ones, so the control didn't visually communicate that it was interactive/filterable. | The prompt specified behavior, not the visual state distinction needed to communicate it. |
| 4 | "Give inactive cluster tabs an outline instead of a fill." | Active vs. inactive pills visually distinct. | Matched expectations; sequence closed. | — |

**Commits:** `6022e3e` → `76c8f7b` → `4f4d23c` → `dd5521f`.

Per the project's development notes, this decision took roughly five round trips
end-to-end in practice (counting the initial Phase 4 dropdown as the starting point),
and at least one of those rounds was spent re-checking a change that had actually
already landed correctly but appeared not to, because the browser had cached the
previous CSS. That is a verification-process failure, not a prompt or specification
failure — a distinction the report's §7.2 treats as its own lesson, separate from
prompt ambiguity.

### B.2 — Open-access pill placement, after Phase 9

Phase 9 (`86f9b42`) added the access-status pill and an "Open access only" filter.
Three short rounds followed:

| # | Prompt | Expected | Actual | Why it needed another round |
| - | --- | --- | --- | --- |
| 1 | "Keep the open-access filter label constant." | A stable, always-readable filter toggle label. | The label had been changing text depending on whether the filter was active, which read as a bug (the button appearing to describe two different features) rather than a status indicator. | The initial implementation used the label itself to convey the toggle's state, without being asked to; a constant label was the fix. |
| 2 | "Move the paper filters into the panel heading and tidy the cluster pills." | A less cluttered header once the open-access filter sat next to the pre-existing "show set aside" toggle. | Correct once implemented; needed a second look at the cluster pill spacing to feel finished. | The first pass moved the filters but left inconsistent spacing around the existing cluster pills, which was visible only once the new control was in place next to them. |
| 3 | "Pin the paper access pill to the card's top-right." | A fixed, predictable pill position on every card. | Matched expectations; sequence closed. | The pill's position had been shifting based on title length in the initial layout, which looked unintentional rather than adaptive. |

**Commits:** `c3de6f0` → `9848efa` → `e0e5eca`.

---

## Summary: what these two chains and thirteen phases show together

Every SDD phase that shipped without a refinement round (1, 4's algorithmic core, 5,
6's happy path, 7, 10, 11, 13) had a specification section with either a worked
example, an explicit field list, or an explicit fallback rule already written down
before implementation started. Every phase or UI chain that needed a genuine
refinement round (2's journal/publisher labeling, 3's DOI-vs-title conflict, 8's
re-search guard, 9's computed-field leak, and both vibe-coding chains) involved a
case the prompt or specification had left implicit — never a case where the model
"hallucinated" in the sense of inventing an unrelated fact. This is the evidentiary
basis for the report's central claim in §7.2: this project's practical SDD failures
were ambiguity failures, not capability failures.
