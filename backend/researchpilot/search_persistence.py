from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    delete,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from .analysis import RankedPaper
from .llm import ClusterNaming
from .papers import ProjectPaper, ProviderError, SearchRun, Subtopic
from .persistence import Base


class PaperRow(Base):
    __tablename__ = "papers"
    __table_args__ = (UniqueConstraint("source", "sourceId"),)
    id: Mapped[UUID] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    sourceId: Mapped[str] = mapped_column(Text)
    sourceUrl: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(Text)
    doiUrl: Mapped[str | None] = mapped_column(Text)
    abstract: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list] = mapped_column(JSON)
    publicationYear: Mapped[int | None]
    publicationDate: Mapped[date | None] = mapped_column(Date)
    journal: Mapped[str | None] = mapped_column(Text)
    venue: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    citationCount: Mapped[int | None]
    publicationUrl: Mapped[str | None] = mapped_column(Text)
    openAccessUrl: Mapped[str | None] = mapped_column(Text)
    isOpenAccess: Mapped[bool | None]
    embedding: Mapped[list | None] = mapped_column(JSON)
    embeddingModel: Mapped[str | None] = mapped_column(Text)


class SearchRunRow(Base):
    __tablename__ = "search_runs"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    projectId: Mapped[UUID] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(100))
    parameters: Mapped[dict] = mapped_column(JSON)
    researchQuestion: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    startedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finishedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totalFound: Mapped[int | None]
    paperCount: Mapped[int]
    skippedCount: Mapped[int]
    duplicateCount: Mapped[int]
    clusterCount: Mapped[int]
    stage: Mapped[str | None] = mapped_column(String(20))
    namingError: Mapped[str | None] = mapped_column(String(32))
    errorCode: Mapped[str | None] = mapped_column(String(32))
    errorMessage: Mapped[str | None] = mapped_column(Text)


class SubtopicRow(Base):
    __tablename__ = "subtopics"
    projectId: Mapped[UUID] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), primary_key=True
    )
    clusterId: Mapped[int] = mapped_column(primary_key=True)
    searchRunId: Mapped[UUID] = mapped_column(ForeignKey("search_runs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON)
    userModified: Mapped[bool] = mapped_column(default=False)


class ProjectPaperRow(Base):
    __tablename__ = "project_papers"
    projectId: Mapped[UUID] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), primary_key=True
    )
    paperId: Mapped[UUID] = mapped_column(ForeignKey("papers.id"), primary_key=True)
    searchRunId: Mapped[UUID] = mapped_column(ForeignKey("search_runs.id", ondelete="CASCADE"))
    position: Mapped[int]
    relevanceScore: Mapped[float]
    clusterId: Mapped[int | None]
    classificationExplanation: Mapped[str | None] = mapped_column(Text)
    isRelevant: Mapped[bool] = mapped_column(default=True)
    userModified: Mapped[bool] = mapped_column(default=False)


class SearchRepository:
    def __init__(self, session):
        self.session = session

    def latest(self, project_id):
        return self.session.scalar(
            select(SearchRunRow)
            .where(SearchRunRow.projectId == project_id)
            .order_by(SearchRunRow.startedAt.desc(), SearchRunRow.id.desc())
            .limit(1)
        )

    def history(self, project_id):
        return [
            SearchRun.model_validate(row)
            for row in self.session.scalars(
                select(SearchRunRow)
                .where(SearchRunRow.projectId == project_id)
                .order_by(SearchRunRow.startedAt.desc(), SearchRunRow.id.desc())
                .limit(20)
            )
        ]

    def papers(self, project_id):
        return [
            ProjectPaper.model_validate({**paper.__dict__, **association.__dict__})
            for paper, association in self.session.execute(
                select(PaperRow, ProjectPaperRow)
                .join(ProjectPaperRow, ProjectPaperRow.paperId == PaperRow.id)
                .where(ProjectPaperRow.projectId == project_id)
                .order_by(ProjectPaperRow.position)
            )
        ]

    def existing_embeddings(self, paper_ids, model):
        ids = list(paper_ids)
        if not ids:
            return {}
        rows = self.session.execute(
            select(PaperRow.id, PaperRow.embedding).where(
                PaperRow.id.in_(ids),
                PaperRow.embeddingModel == model,
                PaperRow.embedding.is_not(None),
            )
        )
        return {paper_id: vector for paper_id, vector in rows}

    def replace_papers(
        self,
        project_id,
        run_id,
        ranked_papers: list[RankedPaper],
        *,
        fresh_vectors,
        model,
        clusters,
    ):
        self.session.execute(delete(ProjectPaperRow).where(ProjectPaperRow.projectId == project_id))
        unique = {item.paper.id: item for item in ranked_papers}
        insert = (
            postgres_insert if self.session.bind.dialect.name == "postgresql" else sqlite_insert
        )
        columns = {column.name for column in PaperRow.__table__.columns}
        # Stable ordering prevents deadlocks when projects share works.
        for paper_id in sorted(unique):
            values = {
                key: value
                for key, value in unique[paper_id].paper.model_dump().items()
                if key in columns
            }
            if paper_id in fresh_vectors:
                values["embedding"] = fresh_vectors[paper_id]
                values["embeddingModel"] = model
            statement = insert(PaperRow).values(**values)
            # Reused papers omit the embedding columns, so a stored vector is left intact.
            self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=["id"],
                    set_={key: getattr(statement.excluded, key) for key in values if key != "id"},
                )
            )
        self.session.add_all(
            ProjectPaperRow(
                projectId=project_id,
                paperId=item.paper.id,
                searchRunId=run_id,
                position=position,
                relevanceScore=item.relevance_score,
                clusterId=clusters.get(item.paper.id),
            )
            for position, item in enumerate(unique.values())
        )
        return len(unique)

    def subtopics(self, project_id):
        return [
            Subtopic.model_validate(row)
            for row in self.session.scalars(
                select(SubtopicRow)
                .where(SubtopicRow.projectId == project_id)
                .order_by(SubtopicRow.clusterId)
            )
        ]

    def cluster_ids(self, project_id):
        return set(
            self.session.scalars(
                select(ProjectPaperRow.clusterId)
                .where(
                    ProjectPaperRow.projectId == project_id,
                    ProjectPaperRow.clusterId.is_not(None),
                )
                .distinct()
            )
        )

    def rename_subtopic(self, project_id, cluster_id, name, description):
        row = self.session.get(SubtopicRow, (project_id, cluster_id))
        if row is None:
            return None
        row.name = name
        row.description = description
        row.userModified = True
        self.session.flush()
        return Subtopic.model_validate(row)

    def update_paper_association(self, project_id, paper_id, changes):
        row = self.session.get(ProjectPaperRow, (project_id, paper_id))
        if row is None:
            return None
        for field, value in changes.items():
            setattr(row, field, value)
        row.userModified = True
        self.session.flush()
        return row

    def has_manual_edits(self, project_id):
        return bool(
            self.session.scalar(
                select(SubtopicRow.projectId)
                .where(SubtopicRow.projectId == project_id, SubtopicRow.userModified)
                .limit(1)
            )
            or self.session.scalar(
                select(ProjectPaperRow.paperId)
                .where(ProjectPaperRow.projectId == project_id, ProjectPaperRow.userModified)
                .limit(1)
            )
        )

    def explanation_target(self, project_id, paper_id):
        row = self.session.execute(
            select(ProjectPaperRow, PaperRow)
            .join(PaperRow, PaperRow.id == ProjectPaperRow.paperId)
            .where(
                ProjectPaperRow.projectId == project_id,
                ProjectPaperRow.paperId == paper_id,
            )
        ).first()
        if row is None:
            return None
        project_paper, paper = row
        subtopic = None
        if project_paper.clusterId is not None:
            subtopic = self.session.scalar(
                select(SubtopicRow).where(
                    SubtopicRow.projectId == project_id,
                    SubtopicRow.clusterId == project_paper.clusterId,
                )
            )
        return project_paper, paper, subtopic

    def store_explanation(self, project_id, paper_id, text):
        self.session.execute(
            update(ProjectPaperRow)
            .where(
                ProjectPaperRow.projectId == project_id,
                ProjectPaperRow.paperId == paper_id,
            )
            .values(classificationExplanation=text)
        )

    def replace_subtopics(self, project_id, run_id, namings: dict[int, ClusterNaming]):
        self.session.execute(delete(SubtopicRow).where(SubtopicRow.projectId == project_id))
        self.session.add_all(
            SubtopicRow(
                projectId=project_id,
                clusterId=cluster_id,
                searchRunId=run_id,
                name=naming.name,
                description=naming.description,
                keywords=naming.keywords,
            )
            for cluster_id, naming in sorted(namings.items())
        )


SEARCH_LEASE_SECONDS = 240


class SearchConflict(Exception):
    pass


class ExplanationUnavailable(Exception):
    """The requested paper has no named subtopic to explain membership in."""


class ManualEditsPresent(Exception):
    """A new search would replace the project's manual organization; pass force to proceed."""


class UnknownCluster(Exception):
    """A paper was asked to move to a cluster that does not exist in the project."""


def expire_search(project, repository):
    """Release a crashed worker's lease; late workers cannot publish expired results."""
    latest = repository.latest(project.id)
    if latest and latest.status == "SEARCHING":
        started = SearchRun.model_validate(latest).startedAt
        if datetime.now(UTC) - started > timedelta(seconds=SEARCH_LEASE_SECONDS):
            latest.status = "FAILED"
            latest.stage = None
            latest.finishedAt = datetime.now(UTC)
            latest.errorCode = "INTERRUPTED"
            latest.errorMessage = str(ProviderError("INTERRUPTED"))
            project.status = "FAILED"
    return latest
