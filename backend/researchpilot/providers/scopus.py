"""Scopus Search adapter for provider-authored scholarly metadata."""

import re
from datetime import date
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx

from ..papers import Author, Paper, ProviderError, SearchParameters, SearchResult
from .openalex import integer, object_value, optional_text, safe_url

SEARCH_URL = "https://api.elsevier.com/content/search/scopus"


def normalize_entry(entry):
    if not isinstance(entry, dict):
        raise ValueError("Missing Scopus identity")
    eid = optional_text(entry.get("eid"))
    if not eid or not re.fullmatch(r"2-s2\.0-\d+", eid):
        raise ValueError("Missing Scopus identity")
    source_url = f"https://www.scopus.com/record/display.uri?eid={quote(eid)}"
    for link in entry.get("link") or []:
        link = object_value(link)
        if link.get("@ref") == "scopus":
            source_url = safe_url(link.get("@href")) or source_url
            break
    doi = optional_text(entry.get("prism:doi"))
    if doi and not re.fullmatch(r"10\.\d{4,9}/\S+", doi, re.IGNORECASE):
        doi = None
    doi = doi.lower() if doi else None
    cover_date = None
    try:
        if isinstance(entry.get("prism:coverDate"), str):
            cover_date = date.fromisoformat(entry["prism:coverDate"])
    except ValueError:
        pass
    authors = []
    for item in entry.get("author") or []:
        item = object_value(item)
        if item:
            authors.append(
                Author(
                    name=optional_text(item.get("authname")),
                    sourceId=optional_text(item.get("authid")),
                    orcid=safe_url(item.get("orcid")),
                )
            )
    if not authors and optional_text(entry.get("dc:creator")):
        authors = [Author(name=optional_text(entry["dc:creator"]))]
    open_access = object_value(entry.get("openaccess"))
    flag = open_access.get("openaccessFlag", entry.get("openaccessFlag"))
    if flag in (True, "true", "1", 1):
        is_open_access = True
    elif flag in (False, "false", "0", 0):
        is_open_access = False
    else:
        is_open_access = None
    venue = optional_text(entry.get("prism:publicationName"))
    return Paper(
        id=uuid5(NAMESPACE_URL, f"scopus:{eid}"),
        source="Scopus",
        sourceId=eid,
        sourceUrl=source_url,
        title=optional_text(entry.get("dc:title")),
        doi=doi,
        doiUrl=f"https://doi.org/{doi}" if doi else None,
        abstract=optional_text(entry.get("dc:description")),
        authors=authors,
        publicationYear=cover_date.year if cover_date else None,
        publicationDate=cover_date,
        journal=venue if entry.get("prism:aggregationType") == "Journal" else None,
        venue=venue,
        citationCount=integer_value(entry.get("citedby-count")),
        publicationUrl=source_url,
        isOpenAccess=is_open_access,
    )


def integer_value(value):
    if isinstance(value, str) and value.isdecimal():
        return integer(int(value))
    return integer(value)


class ScopusProvider:
    name = "Scopus"

    def __init__(self, client: httpx.AsyncClient, view: str = "STANDARD"):
        self.client = client
        self.view = view

    async def search(self, parameters: SearchParameters) -> SearchResult:
        query = f"TITLE-ABS-KEY({parameters.query})"
        if parameters.yearFrom:
            query += f" AND PUBYEAR > {parameters.yearFrom - 1}"
        if parameters.yearTo:
            query += f" AND PUBYEAR < {parameters.yearTo + 1}"
        papers, skipped, start, total = [], 0, 0, 0
        while start < parameters.maxPaperCount:
            count = min(25 if self.view == "COMPLETE" else 200, parameters.maxPaperCount - start)
            try:
                response = await self.client.get(
                    SEARCH_URL,
                    params={
                        "query": query,
                        "view": self.view,
                        "sort": "relevancy",
                        "start": start,
                        "count": count,
                    },
                )
                if response.status_code == 429:
                    raise ProviderError("RATE_LIMITED")
                if response.status_code in {401, 403}:
                    raise ProviderError("AUTHENTICATION")
                if response.status_code in {400, 414, 422}:
                    raise ProviderError("QUERY_REJECTED")
                if response.status_code != 200:
                    raise ProviderError("UNAVAILABLE")
                payload = response.json()
            except httpx.TimeoutException:
                raise ProviderError("TIMEOUT") from None
            except httpx.HTTPError:
                raise ProviderError("UNAVAILABLE") from None
            except ValueError:
                raise ProviderError("INVALID_RESPONSE") from None
            result = object_value(object_value(payload).get("search-results"))
            entries = result.get("entry")
            total_value = integer_value(result.get("opensearch:totalResults"))
            if not isinstance(entries, list) or total_value is None:
                raise ProviderError("INVALID_RESPONSE")
            total = total_value
            for entry in entries[:count]:
                try:
                    papers.append(normalize_entry(entry))
                except (ValueError, TypeError):
                    skipped += 1
            received = len(entries[:count])
            start += received
            if not received or start >= total:
                break
        if start and not papers:
            raise ProviderError("INVALID_RESPONSE")
        return SearchResult(papers=papers, totalFound=total, skippedCount=skipped)
