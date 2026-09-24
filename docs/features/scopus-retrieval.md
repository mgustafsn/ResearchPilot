# Scopus retrieval

Scopus is an optional scholarly paper source behind the existing `PaperProvider`
contract. Set `SCHOLARLY_PROVIDER=scopus` and `ELSEVIER_API_KEY` in the backend
environment. OpenAlex remains the default. The API key is sent to Elsevier as an
`X-ELS-APIKey` header and is never returned to the browser.

The adapter calls Scopus Search with the `STANDARD` view, applies publication-year
limits, and normalizes Scopus EIDs, titles, DOIs, dates, authors, venues, citation
counts, and provider-reported open-access flags. It explicitly requests relevance
ordering so result limits do not fill with the newest, mostly uncited papers.
It uses the same search,
deduplication, ranking, clustering, and persistence pipeline as OpenAlex. Records
without a valid EID are skipped; provider errors are mapped to the existing safe
error codes.

On the developer key used for this feature, Elsevier returned HTTP 200 for
`STANDARD` search and HTTP 401 for `COMPLETE` search and `META_ABS` abstract
retrieval. Consequently, this configuration does not supply Scopus abstracts;
relevance and clustering use paper titles. Broader abstract access depends on the
institution's Elsevier API entitlement. The live smoke check requested only one
search result and did not expose the API key.

The paper list offers local ordering by relevance, citation count, newest, oldest,
and title. This changes presentation within the selected subtopic without replacing
search results or changing paper metadata.
