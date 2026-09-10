import logging
import re
from datetime import date
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import httpx

from ..papers import Author, Paper, ProviderError, SearchParameters, SearchResult

logger = logging.getLogger(__name__)


def optional_text(value):
    return value.strip() or None if isinstance(value, str) else None


def object_value(value):
    return value if isinstance(value, dict) else {}


def safe_url(value):
    value = optional_text(value)
    if not value or any(ord(char) < 32 for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def integer(value, minimum=0, maximum=None):
    if type(value) is int and value >= minimum and (maximum is None or value <= maximum):
        return value
    return None


def reconstruct_abstract(index):
    if not isinstance(index, dict) or not index:
        return None
    words = {}
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            return None
        for position in positions:
            if type(position) is not int or position < 0 or position >= 100000 or position in words:
                return None
            words[position] = word
    # A corrupt index must not become a misleading, partial abstract.
    if not words or set(words) != set(range(len(words))):
        return None
    return " ".join(words[position] for position in range(len(words)))


def normalize_work(work):
    if not isinstance(work, dict):
        raise ValueError("Missing provider identity")
    source_id = optional_text(work.get("id"))
    if not source_id or not re.fullmatch(r"https://openalex\.org/W\d+", source_id):
        raise ValueError("Missing provider identity")
    location = object_value(work.get("primary_location"))
    source = object_value(location.get("source"))
    access = object_value(work.get("open_access"))
    doi_url = safe_url(work.get("doi"))
    doi = None
    if doi_url:
        parsed = urlsplit(doi_url)
        if parsed.hostname in {"doi.org", "dx.doi.org"} and parsed.path.startswith("/10."):
            doi = parsed.path[1:].lower()
        else:
            doi_url = None
    authors = []
    for authorship in work.get("authorships") or []:
        author = object_value(object_value(authorship).get("author"))
        if author:
            authors.append(
                Author(
                    name=optional_text(author.get("display_name")),
                    sourceId=safe_url(author.get("id")),
                    orcid=safe_url(author.get("orcid")),
                )
            )
    publication_date = None
    try:
        if isinstance(work.get("publication_date"), str):
            publication_date = date.fromisoformat(work["publication_date"])
    except ValueError:
        pass
    host = optional_text(source.get("host_organization")) or ""
    return Paper(
        id=uuid5(NAMESPACE_URL, source_id),
        source="OpenAlex",
        sourceId=source_id,
        sourceUrl=source_id,
        title=optional_text(work.get("title")),
        doi=doi,
        doiUrl=doi_url,
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        authors=authors,
        publicationYear=integer(work.get("publication_year"), 1, 9999),
        publicationDate=publication_date,
        venue=optional_text(source.get("display_name")),
        journal=optional_text(source.get("display_name"))
        if source.get("type") == "journal"
        else None,
        publisher=optional_text(source.get("host_organization_name"))
        if re.fullmatch(r"https://openalex\.org/P\d+", host)
        else None,
        citationCount=integer(work.get("cited_by_count")),
        publicationUrl=safe_url(location.get("landing_page_url")),
        openAccessUrl=safe_url(access.get("oa_url")),
        isOpenAccess=access.get("is_oa") if type(access.get("is_oa")) is bool else None,
    )


class OpenAlexProvider:
    name = "OpenAlex"

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def search(self, parameters: SearchParameters):
        params = {
            "search": parameters.query,
            "per_page": min(100, parameters.maxPaperCount),
            "cursor": "*",
        }
        if parameters.yearFrom or parameters.yearTo:
            params["filter"] = (
                f"publication_year:{parameters.yearFrom or 1}-{parameters.yearTo or 9999}"
            )
        papers, skipped, received = [], 0, 0
        total = 0
        # Bound calls even if a provider returns repeated cursors or malformed records.
        for page in range((parameters.maxPaperCount + 99) // 100):
            logger.info("OpenAlex request page=%s", page + 1)
            try:
                response = await self.client.get("https://api.openalex.org/works", params=params)
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
            if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
                raise ProviderError("INVALID_RESPONSE")
            meta = object_value(payload.get("meta"))
            if integer(meta.get("count")) is None:
                raise ProviderError("INVALID_RESPONSE")
            total = meta["count"]
            works = payload["results"][: parameters.maxPaperCount - received]
            for work in works:
                received += 1
                try:
                    papers.append(normalize_work(work))
                except (ValueError, TypeError):
                    skipped += 1
            cursor = meta.get("next_cursor")
            if received >= parameters.maxPaperCount or not works or cursor is None:
                break
            if not isinstance(cursor, str) or cursor == params["cursor"]:
                raise ProviderError("INVALID_RESPONSE")
            params["cursor"] = cursor
        if received and not papers:
            raise ProviderError("INVALID_RESPONSE")
        logger.info(
            "OpenAlex results received=%s normalized=%s skipped=%s", received, len(papers), skipped
        )
        return SearchResult(papers=papers, totalFound=total, skippedCount=skipped)
