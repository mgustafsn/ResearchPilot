"""Provider-neutral contract for LLM interpretation of clusters."""

from typing import Protocol

from pydantic import BaseModel, Field, field_validator

NAME_MAX = 80
DESCRIPTION_MAX = 500
KEYWORDS_MAX = 8
EXPLANATION_MAX = 400
QUERY_MAX = 160
QUERY_WORDS_MAX = 8
QUERIES_MAX = 6


class PaperBrief(BaseModel):
    title: str | None = None
    abstract: str | None = None


class ClusterNaming(BaseModel):
    """Validated LLM output for one cluster. Trims rather than rejects overlong fields."""

    name: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)

    @field_validator("name", "description", mode="before")
    @classmethod
    def _collapse(cls, value):
        return " ".join(str(value).split()) if value is not None else ""

    @field_validator("name")
    @classmethod
    def _name(cls, value):
        if not value:
            raise ValueError("empty name")
        return value[:NAME_MAX]

    @field_validator("description")
    @classmethod
    def _description(cls, value):
        return value[:DESCRIPTION_MAX]

    @field_validator("keywords", mode="before")
    @classmethod
    def _keywords(cls, value):
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            keyword = " ".join(str(item).split())
            if keyword and keyword.casefold() not in {other.casefold() for other in cleaned}:
                cleaned.append(keyword)
        return cleaned[:KEYWORDS_MAX]


class PaperExplanation(BaseModel):
    """Validated LLM output for one paper's subtopic membership. Trims, never rejects for length."""

    explanation: str

    @field_validator("explanation", mode="before")
    @classmethod
    def _collapse(cls, value):
        return " ".join(str(value).split()) if value is not None else ""

    @field_validator("explanation")
    @classmethod
    def _require(cls, value):
        if not value:
            raise ValueError("empty explanation")
        return value[:EXPLANATION_MAX]


class QueryExpansion(BaseModel):
    """Validated search terms proposed by an LLM."""

    queries: list[str] = Field(default_factory=list)

    @field_validator("queries", mode="before")
    @classmethod
    def _queries(cls, value):
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            query = " ".join(str(item).split())[:QUERY_MAX]
            if len(query.split()) > QUERY_WORDS_MAX:
                continue
            if query and query.casefold() not in {other.casefold() for other in cleaned}:
                cleaned.append(query)
        return cleaned[:QUERIES_MAX]


class AbstractSummary(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)

    @field_validator("summary", mode="before")
    @classmethod
    def _clean(cls, value):
        return " ".join(value.split()) if isinstance(value, str) else value


class LlmProvider(Protocol):
    name: str
    model: str

    async def expand_queries(self, question: str, keywords: list[str]) -> QueryExpansion: ...

    async def name_cluster(self, question: str, papers: list[PaperBrief]) -> ClusterNaming: ...

    async def explain_paper(self, question: str, subtopic: str, paper: PaperBrief) -> str: ...

    async def summarize_abstract(self, title: str | None, abstract: str) -> AbstractSummary: ...
