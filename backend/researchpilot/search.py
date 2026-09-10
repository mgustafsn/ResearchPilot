"""Search orchestration: short database transactions around bounded network calls."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from .analysis import RankedPaper, deduplicate, rank_papers
from .clustering import cluster_papers
from .embeddings import EmbeddingProvider
from .papers import Paper, PaperProvider, ProviderError, SearchParameters, SearchRun
from .persistence import ProjectRepository
from .search_persistence import SearchConflict, SearchRepository, SearchRunRow, expire_search
from .service import ProjectNotFound

logger = logging.getLogger(__name__)
SEARCH_TIMEOUT_SECONDS = 60
EMBEDDING_TIMEOUT_SECONDS = 60


@dataclass
class CompletedSearch:
    ranked: list[RankedPaper]
    total_found: int
    skipped_count: int
    duplicate_count: int
    fresh_vectors: dict[UUID, list[float]]
    model: str
    clusters: dict[UUID, int | None]
    cluster_count: int


def _embedding_text(paper: Paper) -> str:
    text = " ".join(filter(None, [paper.title, paper.abstract])).strip()
    return text or "untitled paper"


class SearchService:
    def __init__(self, engine, provider: PaperProvider, embedding_provider: EmbeddingProvider):
        self.engine = engine
        self.provider = provider
        self.embedding_provider = embedding_provider

    def _project(self, session, project_id):
        project = ProjectRepository(session).get(project_id, for_update=True)
        if project is None:
            raise ProjectNotFound()
        return project

    def start(self, project_id):
        with Session(self.engine) as session, session.begin():
            project = self._project(session, project_id)
            latest = expire_search(project, SearchRepository(session))
            if latest and latest.status == "SEARCHING":
                raise SearchConflict("A search is already running for this project.")
            params = SearchParameters(
                query=project.researchQuestion,
                yearFrom=project.yearFrom,
                yearTo=project.yearTo,
                maxPaperCount=project.maxPaperCount or 100,
            )
            run = SearchRunRow(
                id=uuid4(),
                projectId=project.id,
                provider=self.provider.name,
                parameters=params.model_dump(),
                researchQuestion=project.researchQuestion,
                keywords=project.keywords,
                status="SEARCHING",
                startedAt=datetime.now(UTC),
                paperCount=0,
                skippedCount=0,
                duplicateCount=0,
                clusterCount=0,
            )
            session.add(run)
            project.status = "SEARCHING"
            session.flush()
            return SearchRun.model_validate(run)

    def _existing_embeddings(self, paper_ids, model):
        with Session(self.engine) as session:
            return SearchRepository(session).existing_embeddings(paper_ids, model)

    async def _prepare(self, run, result) -> CompletedSearch:
        """Deduplicate, rank, embed the newcomers, and cluster — all outside a transaction."""
        deduplicated, duplicate_count = deduplicate(result.papers)
        ranked = rank_papers(deduplicated, run.researchQuestion, run.keywords)
        model = self.embedding_provider.model
        existing = await asyncio.to_thread(
            self._existing_embeddings, [item.paper.id for item in ranked], model
        )
        missing = [item for item in ranked if item.paper.id not in existing]
        fresh_vectors: dict[UUID, list[float]] = {}
        if missing:
            vectors = await asyncio.wait_for(
                self.embedding_provider.embed([_embedding_text(item.paper) for item in missing]),
                EMBEDDING_TIMEOUT_SECONDS,
            )
            fresh_vectors = {
                item.paper.id: vector for item, vector in zip(missing, vectors, strict=True)
            }
        by_id = {**existing, **fresh_vectors}
        ordered = [by_id[item.paper.id] for item in ranked]
        labels = await asyncio.to_thread(cluster_papers, ordered) if ordered else []
        clusters = {item.paper.id: label for item, label in zip(ranked, labels, strict=True)}
        return CompletedSearch(
            ranked=ranked,
            total_found=result.totalFound,
            skipped_count=result.skippedCount,
            duplicate_count=duplicate_count,
            fresh_vectors=fresh_vectors,
            model=model,
            clusters=clusters,
            cluster_count=len({label for label in labels if label is not None}),
        )

    def finish(self, run, completed: CompletedSearch | None = None, error=None):
        with Session(self.engine) as session, session.begin():
            project = self._project(session, run.projectId)
            repository = SearchRepository(session)
            latest = expire_search(project, repository)
            if not latest or latest.id != run.id or latest.status != "SEARCHING":
                raise SearchConflict("This search was superseded. Refresh the project.")
            if error:
                latest.status = "FAILED"
                latest.errorCode = error.code
                latest.errorMessage = str(error)
            else:
                latest.paperCount = repository.replace_papers(
                    project.id,
                    run.id,
                    completed.ranked,
                    fresh_vectors=completed.fresh_vectors,
                    model=completed.model,
                    clusters=completed.clusters,
                )
                latest.totalFound = completed.total_found
                latest.skippedCount = completed.skipped_count
                latest.duplicateCount = completed.duplicate_count
                latest.clusterCount = completed.cluster_count
                latest.status = "COMPLETED"
            latest.finishedAt = datetime.now(UTC)
            project.status = latest.status
            project.updatedAt = latest.finishedAt
            session.flush()
            return SearchRun.model_validate(latest)

    async def search(self, project_id):
        run = await asyncio.to_thread(self.start, project_id)
        logger.info(
            "Search started project=%s run=%s provider=%s", project_id, run.id, self.provider.name
        )
        try:
            result = await asyncio.wait_for(
                self.provider.search(run.parameters), SEARCH_TIMEOUT_SECONDS
            )
            completed = await self._prepare(run, result)
            finished = await asyncio.to_thread(self.finish, run, completed=completed)
        except (TimeoutError, ProviderError) as exc:
            error = exc if isinstance(exc, ProviderError) else ProviderError("TIMEOUT")
            await asyncio.to_thread(self.finish, run, error=error)
            logger.warning("Search failed run=%s code=%s", run.id, error.code)
            raise error from None
        except SearchConflict:
            raise
        except Exception:
            # Do not log provider payloads, request URLs, or arbitrary exception text.
            logger.error("Search failed run=%s code=INTERNAL", run.id)
            await asyncio.to_thread(self.finish, run, error=ProviderError("INTERNAL"))
            raise ProviderError("INTERNAL") from None
        logger.info(
            "Search completed run=%s papers=%s clusters=%s",
            run.id,
            finished.paperCount,
            finished.clusterCount,
        )
        return finished

    def history(self, project_id):
        with Session(self.engine) as session, session.begin():
            project = self._project(session, project_id)
            repository = SearchRepository(session)
            expire_search(project, repository)
            session.flush()
            return repository.history(project_id)

    def papers(self, project_id):
        with Session(self.engine) as session:
            if ProjectRepository(session).get(project_id) is None:
                raise ProjectNotFound()
            return SearchRepository(session).papers(project_id)
