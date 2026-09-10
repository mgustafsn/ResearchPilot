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
)
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from .analysis import RankedPaper
from .papers import ProjectPaper, ProviderError, SearchRun
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
    errorCode: Mapped[str | None] = mapped_column(String(32))
    errorMessage: Mapped[str | None] = mapped_column(Text)


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
            ProjectPaper.model_validate(
                {**paper.__dict__, "relevanceScore": relevance_score, "clusterId": cluster_id}
            )
            for paper, relevance_score, cluster_id in self.session.execute(
                select(PaperRow, ProjectPaperRow.relevanceScore, ProjectPaperRow.clusterId)
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
        # Stable ordering prevents deadlocks when projects share works.
        for paper_id in sorted(unique):
            values = unique[paper_id].paper.model_dump()
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


SEARCH_LEASE_SECONDS = 240


class SearchConflict(Exception):
    pass


def expire_search(project, repository):
    """Release a crashed worker's lease; late workers cannot publish expired results."""
    latest = repository.latest(project.id)
    if latest and latest.status == "SEARCHING":
        started = SearchRun.model_validate(latest).startedAt
        if datetime.now(UTC) - started > timedelta(seconds=SEARCH_LEASE_SECONDS):
            latest.status = "FAILED"
            latest.finishedAt = datetime.now(UTC)
            latest.errorCode = "INTERRUPTED"
            latest.errorMessage = str(ProviderError("INTERRUPTED"))
            project.status = "FAILED"
    return latest
