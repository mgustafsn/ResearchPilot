from datetime import UTC, datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    # Shown as "Research description": LLM context and relevance anchor, never searched.
    researchQuestion: str | None = Field(default=None, min_length=1, max_length=5000)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    yearFrom: StrictInt | None = Field(default=None, ge=1, le=9999)
    yearTo: StrictInt | None = Field(default=None, ge=1, le=9999)
    maxPaperCount: StrictInt | None = Field(default=None, ge=1, le=1000)

    @field_validator("researchQuestion", mode="before")
    @classmethod
    def empty_description(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values):
        result = []
        for value in values:
            value = value.strip()
            if not value or len(value) > 100:
                raise ValueError("Keywords must contain 1–100 characters")
            if value.casefold() not in {item.casefold() for item in result}:
                result.append(value)
        return result

    @model_validator(mode="after")
    def valid_range(self):
        if self.yearFrom is not None and self.yearTo is not None and self.yearFrom > self.yearTo:
            raise ValueError("Start year must not exceed end year")
        return self


class SubtopicPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)


class SubtopicInput(SubtopicPatch):
    pass


class SubtopicMerge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    targetClusterId: StrictInt = Field(ge=0)


def _collapse_whitespace(value):
    return " ".join(value.split()) if isinstance(value, str) else value


class QueryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=160)

    _collapse = field_validator("query", mode="before")(_collapse_whitespace)


class QueryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str | None = Field(default=None, min_length=1, max_length=160)
    enabled: StrictBool | None = None

    _collapse = field_validator("query", mode="before")(_collapse_whitespace)

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.query is None and self.enabled is None:
            raise ValueError("Provide query and/or enabled")
        return self


class PaperPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clusterId: StrictInt | None = Field(default=None, ge=0)
    isRelevant: StrictBool = True

    @model_validator(mode="after")
    def at_least_one_field(self):
        if "clusterId" not in self.model_fields_set and "isRelevant" not in self.model_fields_set:
            raise ValueError("Provide clusterId or isRelevant")
        return self


class Project(ProjectInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    createdAt: datetime
    updatedAt: datetime

    @field_validator("createdAt", "updatedAt")
    @classmethod
    def utc_timestamps(cls, value):
        # SQLite test storage omits timezone information; all stored times are UTC.
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
