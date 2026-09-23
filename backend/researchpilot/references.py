"""Project-owned citations, independent of replaceable search results."""

from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import JSON, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .persistence import Base, ProjectRow
from .search_persistence import PaperRow, ProjectPaperRow


class ReferenceRow(Base):
    __tablename__ = "project_references"
    __table_args__ = (
        UniqueConstraint("projectId", "number"),
        UniqueConstraint("projectId", "doiNormalized"),
        UniqueConstraint("projectId", "paperId"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    projectId: Mapped[UUID] = mapped_column(ForeignKey("research_projects.id", ondelete="CASCADE"))
    paperId: Mapped[UUID | None] = mapped_column(ForeignKey("papers.id"))
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list] = mapped_column(JSON)
    year: Mapped[int | None] = mapped_column(Integer)
    venue: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(Text)
    doiNormalized: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20))
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
    number: int | None = Field(default=None, ge=1)

    @field_validator("authors")
    @classmethod
    def valid_authors(cls, values):
        if any(not name.strip() or len(name.strip()) > 200 for name in values):
            raise ValueError("Each author must contain 1–200 characters")
        return [name.strip() for name in values]


class ReferencePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    number: int = Field(default=None, ge=1)
    notes: str = Field(default=None, max_length=5000)
    title: str = Field(default=None, min_length=1, max_length=500)
    authors: list[str] = Field(default=None, max_length=50)
    year: int | None = Field(default=None, ge=1, le=9999)
    venue: str | None = Field(default=None, max_length=300)
    doi: str | None = Field(default=None, max_length=300)
    url: HttpUrl | None = None
    status: str = Field(default=None, pattern="^(Draft|Submitted|Accepted|Published)$")

    @field_validator("authors")
    @classmethod
    def valid_authors(cls, values):
        return ManualReferenceInput.valid_authors(values) if values is not None else None


class ReferenceConflict(Exception):
    pass


class ReferenceMissing(Exception):
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

    def _number(self, project_id, requested, current_id=None):
        if requested is None:
            return (
                self.session.scalar(
                    select(func.max(ReferenceRow.number)).where(
                        ReferenceRow.projectId == project_id
                    )
                )
                or 0
            ) + 1
        existing = self.session.scalar(
            select(ReferenceRow.id).where(
                ReferenceRow.projectId == project_id, ReferenceRow.number == requested
            )
        )
        if existing is not None and existing != current_id:
            raise ReferenceConflict("Reference number already used in this project")
        return requested

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
            "number": row.number,
            "manual": row.manual,
            "title": row.title if row.manual else paper.title,
            "authors": row.authors if row.manual else [a.get("name", "") for a in paper.authors],
            "year": row.year if row.manual else paper.publicationYear,
            "venue": row.venue if row.manual else (paper.venue or paper.journal),
            "doi": row.doi if row.manual else paper.doi,
            "url": row.url if row.manual else (paper.publicationUrl or paper.sourceUrl),
            "sourceUrl": paper.sourceUrl if paper else None,
            "notes": row.notes,
            "status": row.status if row.manual else "Published",
        }

    def list(self, project_id):
        self._project(project_id)
        rows = self.session.scalars(
            select(ReferenceRow)
            .where(ReferenceRow.projectId == project_id)
            .order_by(ReferenceRow.number)
        ).all()
        return [self._output(row) for row in rows]

    def add_manual(self, project_id, data):
        self._project(project_id)
        values = data.model_dump()
        number = self._number(project_id, values.pop("number"))
        doi_key = self._doi(project_id, values["doi"])
        values["url"] = str(values["url"]) if values["url"] else None
        row = ReferenceRow(
            id=uuid4(),
            projectId=project_id,
            paperId=None,
            manual=True,
            number=number,
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
            number=self._number(project_id, None),
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
        if "number" in changes:
            if changes["number"] is None:
                raise ReferenceConflict("Reference number is required")
            row.number = self._number(project_id, changes.pop("number"), row.id)
        if not row.manual and set(changes) - {"notes"}:
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
        self.session.flush()
        return self._output(row)

    def delete(self, project_id, reference_id):
        row = self._row(project_id, reference_id)
        self.session.delete(row)
        self.session.flush()
