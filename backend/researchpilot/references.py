"""Project-owned citations, independent of replaceable search results."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StrictBool,
    field_validator,
    model_validator,
)
from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from .persistence import Base, ProjectRow
from .search_persistence import PaperRow, ProjectPaperRow


ReadingStatus = Literal["TO_READ", "READING", "READ"]


class ReferenceRow(Base):
    __tablename__ = "project_references"
    __table_args__ = (
        CheckConstraint(
            "\"readingStatus\" IN ('TO_READ', 'READING', 'READ')",
            name="ck_reference_reading_status",
        ),
        CheckConstraint(
            '"citationNumber" IS NULL OR "citationNumber" > 0',
            name="ck_reference_citation_number_positive",
        ),
        CheckConstraint(
            '"previousCitationNumber" IS NULL OR "previousCitationNumber" > 0',
            name="ck_reference_previous_citation_number_positive",
        ),
        CheckConstraint(
            '"isCited" OR "citationNumber" IS NULL',
            name="ck_reference_uncited_has_no_number",
        ),
        UniqueConstraint("projectId", "citationNumber"),
        UniqueConstraint("projectId", "doiNormalized"),
        UniqueConstraint("projectId", "paperId"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    projectId: Mapped[UUID] = mapped_column(ForeignKey("research_projects.id", ondelete="CASCADE"))
    paperId: Mapped[UUID | None] = mapped_column(ForeignKey("papers.id"))
    citationNumber: Mapped[int | None] = mapped_column(Integer)
    isCited: Mapped[bool] = mapped_column(default=False, server_default="false")
    previousCitationNumber: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list] = mapped_column(JSON)
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(Text)
    doiNormalized: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20))
    readingStatus: Mapped[str] = mapped_column(
        String(20), default="TO_READ", server_default="TO_READ"
    )
    manual: Mapped[bool]


def normalized_doi(value):
    if not value:
        return None
    value = value.strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    return value or None


class ManualReferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=500)
    authors: list[str] = Field(default_factory=list, max_length=50)
    year: int | None = Field(default=None, ge=1, le=9999)
    venue: str | None = Field(default=None, max_length=300)
    doi: str | None = Field(default=None, max_length=300)
    url: HttpUrl | None = None
    notes: str = Field(default="", max_length=5000)
    status: str = Field(default="Draft", pattern="^(Draft|Submitted|Accepted|Published)$")
    readingStatus: ReadingStatus = "TO_READ"
    isCited: StrictBool = False
    citationNumber: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def citation_is_consistent(self):
        if self.citationNumber is not None and not self.isCited:
            raise ValueError("citationNumber requires isCited to be true")
        return self

    @field_validator("authors")
    @classmethod
    def valid_authors(cls, values):
        if any(not name.strip() or len(name.strip()) > 200 for name in values):
            raise ValueError("Each author must contain 1–200 characters")
        return [name.strip() for name in values]


class ReferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    readingStatus: ReadingStatus = Field(default=None)
    isCited: StrictBool = Field(default=None)
    citationNumber: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=5000)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    authors: list[str] | None = Field(default=None, max_length=50)
    year: int | None = Field(default=None, ge=1, le=9999)
    venue: str | None = Field(default=None, max_length=300)
    doi: str | None = Field(default=None, max_length=300)
    url: HttpUrl | None = None
    status: str = Field(default=None, pattern="^(Draft|Submitted|Accepted|Published)$")

    @model_validator(mode="after")
    def citation_is_consistent(self):
        if self.isCited is False and self.citationNumber is not None:
            raise ValueError("citationNumber requires isCited to be true")
        return self

    @field_validator("authors")
    @classmethod
    def valid_authors(cls, values):
        return ManualReferenceInput.valid_authors(values) if values is not None else None


class ReferenceConflict(Exception):
    pass


class ReferenceMissing(Exception):
    pass


class ReferenceValidation(Exception):
    pass


class ReferenceService:
    def __init__(self, session):
        self.session = session

    def _project(self, project_id):
        if self.session.get(ProjectRow, project_id) is None:
            raise ReferenceMissing("Project not found")

    def _row(self, project_id, reference_id):
        row = self.session.get(ReferenceRow, reference_id)
        if row is None or row.projectId != project_id:
            raise ReferenceMissing("Reference not found")
        return row

    def _doi(self, project_id, doi, current_id=None):
        key = normalized_doi(doi)
        if key:
            existing = self.session.scalar(
                select(ReferenceRow.id).where(
                    ReferenceRow.projectId == project_id, ReferenceRow.doiNormalized == key
                )
            )
            if existing is not None and existing != current_id:
                raise ReferenceConflict("This DOI is already in the reference library")
        return key

    def _output(self, row):
        paper = self.session.get(PaperRow, row.paperId) if row.paperId else None
        return {
            "id": row.id,
            "projectId": row.projectId,
            "paperId": row.paperId,
            "citationNumber": row.citationNumber,
            "isCited": row.isCited,
            "previousCitationNumber": row.previousCitationNumber,
            "manual": row.manual,
            "title": row.title if row.manual else paper.title,
            "authors": row.authors if row.manual else [a.get("name", "") for a in paper.authors],
            "year": row.year if row.manual else paper.publicationYear,
            "venue": row.venue if row.manual else (paper.venue or paper.journal),
            "doi": row.doi if row.manual else paper.doi,
            "url": row.url if row.manual else (paper.publicationUrl or paper.sourceUrl),
            "sourceUrl": paper.sourceUrl if paper else None,
            "notes": row.notes,
            "readingStatus": row.readingStatus,
            "status": row.status if row.manual else "Published",
        }

    def list(self, project_id):
        self._project(project_id)
        rows = self.session.scalars(
            select(ReferenceRow).where(ReferenceRow.projectId == project_id)
        ).all()
        output = [self._output(row) for row in rows]
        return sorted(output, key=lambda item: ((item["title"] or "").casefold(), str(item["id"])))

    def add_manual(self, project_id, data):
        self._project(project_id)
        values = data.model_dump()
        doi_key = self._doi(project_id, values["doi"])
        values["url"] = str(values["url"]) if values["url"] else None
        row = ReferenceRow(
            id=uuid4(),
            projectId=project_id,
            paperId=None,
            manual=True,
            previousCitationNumber=None,
            doiNormalized=doi_key,
            **values,
        )
        self.session.add(row)
        self.session.flush()
        return self._output(row)

    def save_paper(self, project_id, paper_id):
        self._project(project_id)
        paper = self.session.get(PaperRow, paper_id)
        in_results = self.session.get(ProjectPaperRow, (project_id, paper_id))
        if paper is None or in_results is None:
            raise ReferenceMissing("Paper not found in this project")
        existing = self.session.scalar(
            select(ReferenceRow).where(
                ReferenceRow.projectId == project_id, ReferenceRow.paperId == paper_id
            )
        )
        key = normalized_doi(paper.doi)
        if existing is None and key:
            existing = self.session.scalar(
                select(ReferenceRow).where(
                    ReferenceRow.projectId == project_id, ReferenceRow.doiNormalized == key
                )
            )
        if existing:
            if existing.paperId is None:
                existing.paperId = paper_id
                self.session.flush()
            return self._output(existing)
        row = ReferenceRow(
            id=uuid4(),
            projectId=project_id,
            paperId=paper_id,
            citationNumber=None,
            isCited=False,
            previousCitationNumber=None,
            title=None,
            authors=[],
            year=None,
            venue=None,
            doi=None,
            doiNormalized=key,
            url=None,
            notes="",
            status=None,
            manual=False,
        )
        self.session.add(row)
        self.session.flush()
        return self._output(row)

    def update(self, project_id, reference_id, patch):
        row = self._row(project_id, reference_id)
        changes = patch.model_dump(exclude_unset=True)
        if not changes:
            return self._output(row)
        requested_cited = changes.pop("isCited", None)
        citation_supplied = "citationNumber" in changes
        requested_number = changes.pop("citationNumber", None) if citation_supplied else None
        resulting_cited = row.isCited if requested_cited is None else requested_cited
        if citation_supplied and requested_number is not None and not resulting_cited:
            raise ReferenceValidation("citationNumber requires the reference to be cited")
        if not row.manual and set(changes) - {"notes", "readingStatus"}:
            raise ReferenceConflict("Scholarly metadata cannot be edited")
        if row.manual:
            if "doi" in changes:
                row.doiNormalized = self._doi(project_id, changes["doi"], row.id)
                if row.paperId and row.doiNormalized != normalized_doi(
                    self.session.get(PaperRow, row.paperId).doi
                ):
                    row.paperId = None
            if "url" in changes and changes["url"]:
                changes["url"] = str(changes["url"])
        for name, value in changes.items():
            setattr(row, name, value)
        if requested_cited is False:
            if row.isCited and row.citationNumber is not None:
                row.previousCitationNumber = row.citationNumber
            row.isCited = False
            row.citationNumber = None
        else:
            if requested_cited is True:
                row.isCited = True
            if citation_supplied:
                row.citationNumber = requested_number
        self.session.flush()
        return self._output(row)

    def delete(self, project_id, reference_id):
        row = self._row(project_id, reference_id)
        self.session.delete(row)
        self.session.flush()
