"""Paper metadata adapters for exact Crossref and DataCite DOI records."""

import html
import re
from urllib.parse import quote

import httpx

from ..doi_lookup import DoiLookupUnavailable, InvalidDoi, canonical_doi
from ..papers import DoiPaperMetadata


def _text(value, limit):
    return value.strip()[:limit] or None if isinstance(value, str) else None


def _first_text(values, limit):
    if isinstance(values, list):
        return next((text for value in values if (text := _text(value, limit))), None)
    return None


def _year(value):
    return value if type(value) is int and 1 <= value <= 9999 else None


def _doi_url(doi):
    return f"https://doi.org/{quote(doi, safe='/')}"


def _abstract(value):
    if not isinstance(value, str):
        return None
    plain = " ".join(html.unescape(re.sub(r"<[^>]*>", " ", value)).split())
    return plain[:12000] or None


def _verified_record_doi(value, expected):
    try:
        return isinstance(value, str) and canonical_doi(value) == expected
    except InvalidDoi:
        return False


class _DoiApiProvider:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def _get(self, url):
        try:
            response = await self.client.get(url, timeout=8.0, follow_redirects=False)
        except httpx.RequestError as exc:
            raise DoiLookupUnavailable("DOI metadata source unavailable") from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise DoiLookupUnavailable("DOI metadata source unavailable")
        try:
            return response.json()
        except ValueError as exc:
            raise DoiLookupUnavailable("DOI metadata source returned invalid data") from exc


class CrossrefDoiPaperProvider(_DoiApiProvider):
    name = "Crossref"

    async def lookup_doi(self, doi):
        payload = await self._get(f"https://api.crossref.org/works/{quote(doi, safe='')}")
        if payload is None:
            return None
        record = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(record, dict) or not _verified_record_doi(record.get("DOI"), doi):
            raise DoiLookupUnavailable("Crossref returned invalid DOI metadata")
        authors = []
        for author in record.get("author") if isinstance(record.get("author"), list) else []:
            if not isinstance(author, dict):
                continue
            name = _text(author.get("name"), 200) or _text(
                " ".join(
                    filter(
                        None, [_text(author.get("given"), 100), _text(author.get("family"), 100)]
                    )
                ),
                200,
            )
            if name:
                authors.append(name)
        date = record.get("published") or record.get("issued") or {}
        date_parts = date.get("date-parts") if isinstance(date, dict) else None
        year = (
            _year(date_parts[0][0])
            if isinstance(date_parts, list)
            and date_parts
            and isinstance(date_parts[0], list)
            and date_parts[0]
            else None
        )
        return DoiPaperMetadata(
            source=self.name,
            doi=doi,
            title=_first_text(record.get("title"), 500),
            authors=authors[:50],
            year=year,
            venue=_first_text(record.get("container-title"), 300)
            or _text(record.get("publisher"), 300),
            url=_doi_url(doi),
            abstract=_abstract(record.get("abstract")),
        )


class DataCiteDoiPaperProvider(_DoiApiProvider):
    name = "DataCite"

    async def lookup_doi(self, doi):
        payload = await self._get(f"https://api.datacite.org/dois/{quote(doi, safe='')}")
        data = payload.get("data") if isinstance(payload, dict) else None
        record = data.get("attributes") if isinstance(data, dict) else None
        if payload is None:
            return None
        if not isinstance(record, dict) or not _verified_record_doi(record.get("doi"), doi):
            raise DoiLookupUnavailable("DataCite returned invalid DOI metadata")
        titles = record.get("titles") if isinstance(record.get("titles"), list) else []
        title = next(
            (
                _text(item.get("title"), 500)
                for item in titles
                if isinstance(item, dict) and _text(item.get("title"), 500)
            ),
            None,
        )
        authors = []
        for creator in record.get("creators") if isinstance(record.get("creators"), list) else []:
            if isinstance(creator, dict) and (name := _text(creator.get("name"), 200)):
                authors.append(name)
        container = record.get("container") or {}
        descriptions = (
            record.get("descriptions") if isinstance(record.get("descriptions"), list) else []
        )
        abstract = next(
            (
                _abstract(item.get("description"))
                for item in descriptions
                if isinstance(item, dict)
                and item.get("descriptionType") == "Abstract"
                and _abstract(item.get("description"))
            ),
            None,
        )
        return DoiPaperMetadata(
            source=self.name,
            doi=doi,
            title=title,
            authors=authors[:50],
            year=_year(record.get("publicationYear")),
            venue=(_text(container.get("title"), 300) if isinstance(container, dict) else None)
            or _text(record.get("publisher"), 300),
            url=_doi_url(doi),
            abstract=abstract,
        )
