# DOI lookup

The reference form can look up a DOI and fill an editable citation draft. Crossref is
queried first, then DataCite if Crossref has no record or is unavailable. The lookup
returns the provider, DOI, title, authors, year, venue, and DOI link when available.
Missing fields stay available for manual entry. The DOI in the returned record must
match the requested DOI.

Lookup is a read-only preview. The user reviews and edits fields before saving with
the existing reference endpoint. Invalid DOIs return 422, unfound records 404, and
provider failures 503. A failed lookup leaves the form usable for manual entry.
No OpenAI key or LLM call is needed; scholarly metadata remains provider-supplied.
When the provider record has an abstract, the user may request an AI summary. The
server re-fetches that abstract, sends only its title and text to the structured LLM
summary method, and returns the summary for review in the reference Notes field.
The summary is never used as citation metadata and is not saved automatically.
