"""Exact DOI lookup using provider-supplied citation metadata."""

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

from .llm import LlmProvider
from .papers import DoiPaperProvider


class InvalidDoi(Exception):
    pass


class DoiNotFound(Exception):
    pass


class DoiLookupUnavailable(Exception):
    pass


class NoAbstract(Exception):
    pass


class DoiSummaryInput(BaseModel):
    doi: str = Field(min_length=1, max_length=300)


def canonical_doi(value: str) -> str:
    value = value.strip()
    if value.lower().startswith("doi:"):
        value = value[4:].strip()
    elif value.lower().startswith(("https://doi.org/", "http://doi.org/", "https://dx.doi.org/")):
        parts = urlsplit(value)
        if parts.query or parts.fragment:
            raise InvalidDoi("Enter a DOI without a query or fragment.")
        value = parts.path.lstrip("/")
    value = value.lower()
    if len(value) > 300 or not re.fullmatch(r"10\.\d{4,9}/[^\s/?#][^\s?#]*", value):
        raise InvalidDoi("Enter a valid DOI, such as 10.1234/example.")
    return value


class DoiLookupService:
    def __init__(self, providers: list[DoiPaperProvider]):
        self.providers = providers

    async def lookup(self, value: str):
        doi = canonical_doi(value)
        unavailable = False
        for provider in self.providers:
            try:
                result = await provider.lookup_doi(doi)
            except DoiLookupUnavailable:
                unavailable = True
                continue
            if result is not None:
                return result
        if unavailable:
            raise DoiLookupUnavailable(
                "DOI lookup is unavailable. Try again or enter details manually."
            )
        raise DoiNotFound("No metadata was found for this DOI. Enter the reference manually.")

    async def summarize(self, value: str, llm: LlmProvider):
        paper = await self.lookup(value)
        if not paper.abstract:
            raise NoAbstract("This DOI record has no abstract to summarize.")
        return await llm.summarize_abstract(paper.title, paper.abstract)
