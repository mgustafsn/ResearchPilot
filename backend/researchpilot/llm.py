"""Provider-neutral contract for LLM interpretation of clusters."""

from typing import Protocol

from pydantic import BaseModel, Field, field_validator

NAME_MAX = 80
DESCRIPTION_MAX = 500
KEYWORDS_MAX = 8


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


class LlmProvider(Protocol):
    name: str
    model: str

    async def name_cluster(self, question: str, papers: list[PaperBrief]) -> ClusterNaming: ...
