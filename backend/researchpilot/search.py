"""Search orchestration: short database transactions around bounded network calls."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from .analysis import RankedPaper, deduplicate, rank_papers
from .clustering import cluster_papers
from .embeddings import EmbeddingProvider
from .llm import ClusterNaming, LlmProvider, PaperBrief
from .papers import Paper, PaperProvider, ProviderError, SearchParameters, SearchRun
from .persistence import ProjectRepository
from .search_persistence import SearchConflict, SearchRepository, SearchRunRow, expire_search
from .service import ProjectNotFound

logger = logging.getLogger(__name__)
SEARCH_TIMEOUT_SECONDS = 60
EMBEDDING_TIMEOUT_SECONDS = 60
NAMING_TIMEOUT_SECONDS = 30
NAMING_SAMPLE = 6


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
    subtopics: dict[int, ClusterNaming]
    naming_error: str | None


def _embedding_text(paper: Paper) -> str:
    text = " ".join(filter(None, [paper.title, paper.abstract])).strip()
    return text or "untitled paper"


class SearchService:
    def __init__(
        self,
        engine,
        provider: PaperProvider,
        embedding_provider: EmbeddingProvider,
        llm_provider: LlmProvider,
    ):
        self.engine = engine
        self.provider = provider
        self.embedding_provider = embedding_provider
        self.llm_provider = llm_provider

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
                stage="RETRIEVING",
            )
            session.add(run)
            project.status = "SEARCHING"
            session.flush()
            return SearchRun.model_validate(run)

    def _existing_embeddings(self, paper_ids, model):
        with Session(self.engine) as session:
            return SearchRepository(session).existing_embeddings(paper_ids, model)

    def _set_stage(self, run_id, stage):
        """Record pipeline progress for a running search; a no-op once superseded."""
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(SearchRunRow)
                .where(SearchRunRow.id == run_id, SearchRunRow.status == "SEARCHING")
                .values(stage=stage)
            )

    async def _prepare(self, run, result) -> CompletedSearch:
        """Deduplicate, rank, embed the newcomers, and cluster — all outside a transaction."""
        await asyncio.to_thread(self._set_stage, run.id, "ANALYZING")
        deduplicated, duplicate_count = deduplicate(result.papers)
        ranked = rank_papers(deduplicated, run.researchQuestion, run.keywords)
        model = self.embedding_provider.model
        existing = await asyncio.to_thread(
            self._existing_embeddings, [item.paper.id for item in ranked], model
        )
        missing = [item for item in ranked if item.paper.id not in existing]
        fresh_vectors: dict[UUID, list[float]] = {}
        await asyncio.to_thread(self._set_stage, run.id, "EMBEDDING")
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
        await asyncio.to_thread(self._set_stage, run.id, "CLUSTERING")
        labels = await asyncio.to_thread(cluster_papers, ordered) if ordered else []
        clusters = {item.paper.id: label for item, label in zip(ranked, labels, strict=True)}
        cluster_count = len({label for label in labels if label is not None})
        if cluster_count >= 2:
            await asyncio.to_thread(self._set_stage, run.id, "NAMING")
        subtopics, naming_error = await self._name_clusters(run, ranked, clusters, cluster_count)
        return CompletedSearch(
            ranked=ranked,
            total_found=result.totalFound,
            skipped_count=result.skippedCount,
            duplicate_count=duplicate_count,
            fresh_vectors=fresh_vectors,
            model=model,
            clusters=clusters,
            cluster_count=cluster_count,
            subtopics=subtopics,
            naming_error=naming_error,
        )

    async def _name_clusters(self, run, ranked, clusters, cluster_count):
        """Best-effort LLM naming: one bounded call per cluster, failures are non-fatal."""
        if cluster_count < 2:
            return {}, None
        samples: dict[int, list[PaperBrief]] = {}
        for item in ranked:
            label = clusters.get(item.paper.id)
            if label is None or len(samples.setdefault(label, [])) >= NAMING_SAMPLE:
                continue
            samples[label].append(PaperBrief(title=item.paper.title, abstract=item.paper.abstract))
        cluster_ids = sorted(samples)

        async def name(briefs):
            return await asyncio.wait_for(
                self.llm_provider.name_cluster(run.researchQuestion, briefs), NAMING_TIMEOUT_SECONDS
            )

        outcomes = await asyncio.gather(
            *(name(samples[cluster_id]) for cluster_id in cluster_ids), return_exceptions=True
        )
        namings: dict[int, ClusterNaming] = {}
        naming_error = None
        for cluster_id, outcome in zip(cluster_ids, outcomes):
            if isinstance(outcome, ClusterNaming):
                namings[cluster_id] = outcome
            else:
                code = outcome.code if isinstance(outcome, ProviderError) else "LLM_UNAVAILABLE"
                naming_error = naming_error or code
                logger.warning(
                    "Cluster naming failed run=%s cluster=%s code=%s", run.id, cluster_id, code
                )
        return namings, naming_error

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
                repository.replace_subtopics(project.id, run.id, completed.subtopics)
                latest.totalFound = completed.total_found
                latest.skippedCount = completed.skipped_count
                latest.duplicateCount = completed.duplicate_count
                latest.clusterCount = completed.cluster_count
                latest.namingError = completed.naming_error
                latest.status = "COMPLETED"
            latest.stage = None
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

    def subtopics(self, project_id):
        with Session(self.engine) as session:
            if ProjectRepository(session).get(project_id) is None:
                raise ProjectNotFound()
            return SearchRepository(session).subtopics(project_id)
