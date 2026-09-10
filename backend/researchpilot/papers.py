"""Provider-neutral scholarly metadata and retrieval contracts."""

from datetime import UTC, date, datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Author(BaseModel):
    name: str | None = None
    sourceId: str | None = None
    orcid: str | None = None


class Paper(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source: str
    sourceId: str
    sourceUrl: str
    title: str | None = None
    doi: str | None = None
    doiUrl: str | None = None
    abstract: str | None = None
    authors: list[Author] = Field(default_factory=list)
    publicationYear: int | None = None
    publicationDate: date | None = None
    journal: str | None = None
    venue: str | None = None
    publisher: str | None = None
    citationCount: int | None = None
    publicationUrl: str | None = None
    openAccessUrl: str | None = None
    isOpenAccess: bool | None = None


class ProjectPaper(Paper):
    relevanceScore: float = Field(ge=0, le=1)
    clusterId: int | None = None
    classificationExplanation: str | None = None
    isRelevant: bool = True
    userModified: bool = False


class Subtopic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    clusterId: int
    name: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    userModified: bool = False


class SearchParameters(BaseModel):
    query: str
    yearFrom: int | None = None
    yearTo: int | None = None
    maxPaperCount: int = 100


class SearchResult(BaseModel):
    papers: list[Paper]
    totalFound: int
    skippedCount: int = 0


class SearchRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    projectId: UUID
    provider: str
    parameters: SearchParameters
    researchQuestion: str
    keywords: list[str]
    status: Literal["SEARCHING", "COMPLETED", "FAILED"]
    stage: str | None = None
    startedAt: datetime
    finishedAt: datetime | None = None
    totalFound: int | None = None
    paperCount: int = 0
    skippedCount: int = 0
    duplicateCount: int = 0
    clusterCount: int = 0
    namingError: str | None = None
    errorCode: str | None = None
    errorMessage: str | None = None

    @field_validator("startedAt", "finishedAt")
    @classmethod
    def utc_timestamps(cls, value):
        if value is None:
            return value
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ProviderError(Exception):
    """Only predefined, credential-free error messages cross the provider boundary."""

    MESSAGES = {
        "RATE_LIMITED": "The scholarly provider is rate limited. Please try again later.",
        "AUTHENTICATION": "The scholarly provider rejected authentication. Check the server API key.",
        "UNAVAILABLE": "The scholarly provider is unavailable. Please try again later.",
        "TIMEOUT": "The scholarly search timed out. Try a smaller paper limit.",
        "INVALID_RESPONSE": "The scholarly provider returned an invalid response. Please try again.",
        "QUERY_REJECTED": "The scholarly provider rejected this query. Try a shorter research topic.",
        "INTERRUPTED": "The search was interrupted. Please run it again.",
        "INTERNAL": "The search could not be completed. Please try again.",
        "EMBEDDING_UNAUTHORIZED": "The embedding service rejected authentication. Check the server API key.",
        "EMBEDDING_RATE_LIMITED": "The embedding service is rate limited. Please try again later.",
        "EMBEDDING_UNAVAILABLE": "The embedding service is unavailable. Please try again later.",
        "EMBEDDING_INVALID_RESPONSE": "The embedding service returned an invalid response. Please try again.",
        "LLM_UNAUTHORIZED": "The language model rejected authentication. Check the server API key.",
        "LLM_RATE_LIMITED": "The language model is rate limited. Please try again later.",
        "LLM_UNAVAILABLE": "The language model is unavailable. Please try again later.",
        "LLM_INVALID_RESPONSE": "The language model returned an invalid response. Please try again.",
    }

    def __init__(self, code):
        self.code = code
        super().__init__(self.MESSAGES[code])


class PaperProvider(Protocol):
    name: str

    async def search(self, parameters: SearchParameters) -> SearchResult: ...
