"""Search orchestration: short database transactions around bounded network calls."""

import asyncio
import logging
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.orm import Session

from .analysis import (
    RankedPaper,
    deduplicate,
    filter_relevant,
    rank_papers,
    rank_semantically,
)
from .clustering import cluster_papers
from .embeddings import EmbeddingProvider
from .llm import QUERY_MAX, ClusterNaming, LlmProvider, PaperBrief
from .papers import (
    Paper,
    PaperProvider,
    ProviderError,
    SearchParameters,
    SearchResult,
    SearchRun,
)
from .persistence import ProjectRepository
from .search_persistence import (
    SAVED_QUERIES_MAX,
    ExplanationUnavailable,
    ManualEditsPresent,
    SearchConflict,
    SearchRepository,
    SearchRunRow,
    UnknownCluster,
    expire_search,
)
from .service import ProjectNotFound


class InvalidQuery(Exception):
    """A query change that breaks the saved-query rules (e.g. the per-project cap)."""


class DuplicateQuery(Exception):
    """The query text already exists in the project's list (case-insensitive)."""


class NoEnabledQueries(Exception):
    """Saved queries exist but every one is disabled, so there is nothing to search."""


class DescriptionRequired(Exception):
    """Optional discovery needs a research description before it can run."""


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
    filtered_count: int
    vectors: dict[UUID, list[float]]
    model: str
    hashes: dict[UUID, str]
    provider: str
    dimension: int
    clusters: dict[UUID, int | None]
    cluster_count: int
    subtopics: dict[int, ClusterNaming]
    naming_error: str | None
    failed_queries: list[str]
    failed_sources: list[str]


def _embedding_text(paper: Paper) -> str:
    text = " ".join(filter(None, [paper.title, paper.abstract])).strip()
    return " ".join(text.split()) or "untitled paper"


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

    def start(self, project_id, force=False):
        with Session(self.engine) as session, session.begin():
            project = self._project(session, project_id)
            if not project.researchQuestion:
                raise DescriptionRequired("Add a research description before discovering papers.")
            repository = SearchRepository(session)
            latest = expire_search(project, repository)
            if latest and latest.status == "SEARCHING":
                raise SearchConflict("A search is already running for this project.")
            saved = repository.queries(project.id)
            if saved and not any(item.enabled for item in saved):
                raise NoEnabledQueries("Enable at least one search query.")
            if not force and repository.has_manual_edits(project.id):
                raise ManualEditsPresent(
                    "This project has manual changes. Run the search again to replace them."
                )
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
                filteredCount=0,
                clusterCount=0,
                stage="RETRIEVING",
            )
            session.add(run)
            project.status = "SEARCHING"
            session.flush()
            return SearchRun.model_validate(run)

    def _existing_embeddings(self, hashes, model, provider, dimension):
        with Session(self.engine) as session:
            return SearchRepository(session).existing_embeddings(hashes, model, provider, dimension)

    def _saved_queries(self, project_id):
        with Session(self.engine) as session:
            project = self._project(session, project_id)
            return SearchRepository(session).queries(project_id), project.title

    def _save_generated_queries(self, project_id, queries):
        with Session(self.engine) as session, session.begin():
            repository = SearchRepository(session)
            repository.replace_generated_queries(project_id, queries)
            return repository.queries(project_id)

    async def expand_project_queries(self, project_id):
        with Session(self.engine) as session:
            project = self._editable(session, project_id)
            if not project.researchQuestion:
                raise DescriptionRequired("Add a research description before suggesting queries.")
            question, keywords, title = project.researchQuestion, project.keywords, project.title
        queries = await self._expand_text(question, keywords, title)
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            SearchRepository(session).replace_generated_queries(project_id, queries)
            return SearchRepository(session).queries(project_id)

    def project_queries(self, project_id):
        with Session(self.engine) as session:
            self._project(session, project_id)
            return SearchRepository(session).queries(project_id)

    def add_query(self, project_id, text):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            repository = SearchRepository(session)
            saved = repository.queries(project_id)
            if any(item.query.casefold() == text.casefold() for item in saved):
                raise DuplicateQuery("That query is already in the list.")
            if len(saved) >= SAVED_QUERIES_MAX:
                raise InvalidQuery(
                    f"A project can have at most {SAVED_QUERIES_MAX} search queries."
                )
            return repository.add_query(project_id, text)

    def update_query(self, project_id, query_id, patch):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            repository = SearchRepository(session)
            if patch.query is not None and any(
                item.id != query_id and item.query.casefold() == patch.query.casefold()
                for item in repository.queries(project_id)
            ):
                raise DuplicateQuery("That query is already in the list.")
            updated = repository.update_query(project_id, query_id, patch.query, patch.enabled)
            if updated is None:
                raise ProjectNotFound()
            return updated

    def delete_query(self, project_id, query_id):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            if not SearchRepository(session).delete_query(project_id, query_id):
                raise ProjectNotFound()

    def _set_stage(self, run_id, stage):
        """Record pipeline progress for a running search; a no-op once superseded."""
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(SearchRunRow)
                .where(SearchRunRow.id == run_id, SearchRunRow.status == "SEARCHING")
                .values(stage=stage)
            )

    async def _prepare(self, run, result, failed_queries) -> CompletedSearch:
        """Deduplicate, embed, rank by similarity, filter, and cluster — outside a transaction."""
        analysis_started = time.perf_counter()
        await asyncio.to_thread(self._set_stage, run.id, "ANALYZING")
        deduplicated, duplicate_count = deduplicate(result.papers)
        lexical = rank_papers(deduplicated, run.researchQuestion, run.keywords)
        model = self.embedding_provider.model
        provider = self.embedding_provider.name
        dimension = self.embedding_provider.dimension
        hashes = {
            item.paper.id: hashlib.sha256(_embedding_text(item.paper).encode()).hexdigest()
            for item in lexical
        }
        existing = await asyncio.to_thread(
            self._existing_embeddings, hashes, model, provider, dimension
        )
        missing = [item for item in lexical if item.paper.id not in existing]
        await asyncio.to_thread(self._set_stage, run.id, "EMBEDDING")
        # The question shares the batch so relevance and clustering use one embedding space.
        question = " ".join([run.researchQuestion, *run.keywords])
        question_vector, *vectors = await asyncio.wait_for(
            self.embedding_provider.embed(
                [question, *(_embedding_text(item.paper) for item in missing)]
            ),
            EMBEDDING_TIMEOUT_SECONDS,
        )
        fresh_vectors: dict[UUID, list[float]] = {
            item.paper.id: vector for item, vector in zip(missing, vectors, strict=True)
        }
        by_id = {**existing, **fresh_vectors}
        # Several sources may return more unique papers than the limit; keep the most relevant.
        ranked_all = rank_semantically(lexical, question_vector, by_id)[
            : run.parameters.maxPaperCount
        ]
        ranked = filter_relevant(ranked_all)
        logger.info(
            "Search analyzed run=%s retrieved=%s unique=%s duplicates=%s filtered=%s duration_ms=%s",
            run.id,
            len(result.papers),
            len(ranked_all),
            duplicate_count,
            len(ranked_all) - len(ranked),
            round((time.perf_counter() - analysis_started) * 1000),
        )
        ordered = [by_id[item.paper.id] for item in ranked]
        await asyncio.to_thread(self._set_stage, run.id, "CLUSTERING")
        clustering_started = time.perf_counter()
        labels = await asyncio.to_thread(cluster_papers, ordered) if ordered else []
        logger.info(
            "Search clustering run=%s duration_ms=%s",
            run.id,
            round((time.perf_counter() - clustering_started) * 1000),
        )
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
            filtered_count=len(ranked_all) - len(ranked),
            vectors=by_id,
            hashes=hashes,
            provider=provider,
            dimension=dimension,
            model=model,
            clusters=clusters,
            cluster_count=cluster_count,
            subtopics=subtopics,
            naming_error=naming_error,
            failed_queries=failed_queries,
            failed_sources=result.failedSources,
        )

    async def _expand_queries(self, run):
        saved, title = await asyncio.to_thread(self._saved_queries, run.projectId)
        if not saved:
            generated = await self._expand_text(run.researchQuestion, run.keywords, title)
            saved = await asyncio.to_thread(self._save_generated_queries, run.projectId, generated)
            logger.info("Search generated queries run=%s count=%s", run.id, len(saved))
        selected = [item.query for item in saved if item.enabled]
        logger.info("Search using saved queries run=%s selected=%s", run.id, len(selected))
        if not selected:
            raise NoEnabledQueries("Enable at least one search query.")
        return selected

    async def _expand_text(self, question, keywords, title):
        """Short keyword queries for the description; never the description itself."""
        fallback = [item[:QUERY_MAX] for item in (list(keywords) or [title])]
        expand = getattr(self.llm_provider, "expand_queries", None)
        if expand is None:
            return fallback
        try:
            expansion = await asyncio.wait_for(expand(question, keywords), NAMING_TIMEOUT_SECONDS)
        except (TimeoutError, ProviderError, TypeError, AttributeError):
            logger.warning("Query expansion unavailable; using keywords or project title")
            return fallback
        return expansion.queries or fallback

    async def _retrieve(self, run, queries):
        """Retrieve every query; keep survivors, fail when no papers survived a failure."""
        per_query = max(1, (run.parameters.maxPaperCount + len(queries) - 1) // len(queries))
        parameters = [
            run.parameters.model_copy(update={"query": query, "maxPaperCount": per_query})
            for query in queries
        ]
        outcomes = await asyncio.gather(
            *(self.provider.search(item) for item in parameters), return_exceptions=True
        )
        results, failed, first_error = [], [], None
        for query, outcome in zip(queries, outcomes, strict=True):
            if isinstance(outcome, ProviderError):
                # Never log the query text: it can contain the user's own words.
                logger.warning("Search query failed run=%s code=%s", run.id, outcome.code)
                failed.append(query)
                first_error = first_error or outcome
            elif isinstance(outcome, BaseException):
                raise outcome
            else:
                results.append(outcome)
        # Every query failed, or some failed and the survivors found nothing: fail the
        # run and keep the project's previous results rather than completing empty.
        if failed and sum(len(result.papers) for result in results) == 0:
            raise first_error
        return (
            SearchResult(
                papers=[paper for result in results for paper in result.papers],
                totalFound=sum(result.totalFound for result in results),
                skippedCount=sum(result.skippedCount for result in results),
                failedSources=list(
                    dict.fromkeys(name for result in results for name in result.failedSources)
                ),
            ),
            failed,
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
                    vectors=completed.vectors,
                    model=completed.model,
                    clusters=completed.clusters,
                    hashes=completed.hashes,
                    provider=completed.provider,
                    dimension=completed.dimension,
                )
                repository.replace_subtopics(project.id, run.id, completed.subtopics)
                latest.totalFound = completed.total_found
                latest.skippedCount = completed.skipped_count
                latest.duplicateCount = completed.duplicate_count
                latest.filteredCount = completed.filtered_count
                latest.failedQueries = completed.failed_queries
                latest.failedSources = completed.failed_sources
                latest.clusterCount = completed.cluster_count
                latest.namingError = completed.naming_error
                latest.status = "COMPLETED"
            latest.stage = None
            latest.finishedAt = datetime.now(UTC)
            project.status = latest.status
            project.updatedAt = latest.finishedAt
            session.flush()
            return SearchRun.model_validate(latest)

    async def search(self, project_id, force=False):
        run = await asyncio.to_thread(self.start, project_id, force)
        return await self.execute(run)

    async def execute(self, run):
        search_started = time.perf_counter()
        logger.info(
            "Search started project=%s run=%s provider=%s",
            run.projectId,
            run.id,
            self.provider.name,
        )
        try:
            queries = await self._expand_queries(run)
            await asyncio.to_thread(self._set_generated_queries, run.id, queries)
            result, failed_queries = await asyncio.wait_for(
                self._retrieve(run, queries), SEARCH_TIMEOUT_SECONDS
            )
            completed = await self._prepare(run, result, failed_queries)
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
            "Search completed run=%s papers=%s clusters=%s duration_ms=%s",
            run.id,
            finished.paperCount,
            finished.clusterCount,
            round((time.perf_counter() - search_started) * 1000),
        )
        return finished

    def _set_generated_queries(self, run_id, queries):
        with Session(self.engine) as session, session.begin():
            SearchRepository(session).set_generated_queries(run_id, queries)

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

    def _editable(self, session, project_id):
        project = self._project(session, project_id)
        run = expire_search(project, SearchRepository(session))
        if run and run.status == "SEARCHING":
            raise SearchConflict("Wait for the current search to finish before organizing papers.")
        return project

    def rename_subtopic(self, project_id, cluster_id, patch):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            renamed = SearchRepository(session).rename_subtopic(
                project_id,
                cluster_id,
                patch.name,
                patch.description if "description" in patch.model_fields_set else None,
            )
            if renamed is None:
                raise ProjectNotFound()
            return renamed

    def create_subtopic(self, project_id, patch):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            created = SearchRepository(session).create_subtopic(
                project_id, patch.name, patch.description
            )
            if created is None:
                raise ProjectNotFound()
            return created

    def delete_subtopic(self, project_id, cluster_id):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            if not SearchRepository(session).delete_subtopic(project_id, cluster_id):
                raise ProjectNotFound()

    def merge_subtopics(self, project_id, cluster_id, target_cluster_id):
        if cluster_id == target_cluster_id:
            raise UnknownCluster("Choose a different destination subtopic.")
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            merged = SearchRepository(session).merge_subtopics(
                project_id, cluster_id, target_cluster_id
            )
            if merged is None:
                raise ProjectNotFound()
            return merged

    def update_paper(self, project_id, paper_id, patch):
        with Session(self.engine) as session, session.begin():
            self._editable(session, project_id)
            repository = SearchRepository(session)
            changes = patch.model_dump(exclude_unset=True)
            if "clusterId" in changes and changes["clusterId"] is not None:
                if changes["clusterId"] not in repository.cluster_ids(project_id):
                    raise UnknownCluster(f"Cluster {changes['clusterId']} is not in this project.")
            updated = repository.update_paper_association(project_id, paper_id, changes)
            if updated is None:
                raise ProjectNotFound()
            return next(p for p in repository.papers(project_id) if p.id == updated.paperId)

    def _explanation_context(self, session, project_id, paper_id):
        project = self._project(session, project_id)
        target = SearchRepository(session).explanation_target(project_id, paper_id)
        if target is None:
            raise ProjectNotFound()
        association, paper, subtopic = target
        context = [
            str(association.searchRunId),
            project.researchQuestion,
            paper.title,
            paper.abstract,
            association.clusterId,
            subtopic.name if subtopic else None,
            subtopic.description if subtopic else None,
        ]
        fingerprint = hashlib.sha256(json.dumps(context).encode()).hexdigest()
        return association, paper, subtopic, project, fingerprint

    def _explanation_input(self, project_id, paper_id):
        with Session(self.engine) as session, session.begin():
            association, paper, subtopic, project, fingerprint = self._explanation_context(
                session, project_id, paper_id
            )
            if subtopic is None:
                raise ExplanationUnavailable("This paper has no named subtopic to explain.")
            return {
                "cached": association.classificationExplanation
                if association.explanationContextHash == fingerprint
                else None,
                "fingerprint": fingerprint,
                "question": project.researchQuestion,
                "subtopic": subtopic.name,
                "paper": PaperBrief(title=paper.title, abstract=paper.abstract),
            }

    def _store_explanation(self, project_id, paper_id, text, fingerprint):
        with Session(self.engine) as session, session.begin():
            try:
                association, _, _, _, current = self._explanation_context(
                    session, project_id, paper_id
                )
            except ProjectNotFound:
                raise SearchConflict("Explanation context changed. Refresh the project.") from None
            if current != fingerprint:
                raise SearchConflict("Explanation context changed. Refresh the project.")
            if (
                association.explanationContextHash == current
                and association.classificationExplanation
            ):
                return association.classificationExplanation
            association.classificationExplanation = text
            association.explanationContextHash = current
            return text

    async def explain(self, project_id, paper_id):
        prepared = await asyncio.to_thread(self._explanation_input, project_id, paper_id)
        if prepared["cached"] is not None:
            return prepared["cached"]
        try:
            text = await asyncio.wait_for(
                self.llm_provider.explain_paper(
                    prepared["question"], prepared["subtopic"], prepared["paper"]
                ),
                NAMING_TIMEOUT_SECONDS,
            )
        except (TimeoutError, ProviderError) as exc:
            if isinstance(exc, TimeoutError) or exc.code == "TIMEOUT":
                raise ProviderError("EXPLANATION_TIMEOUT") from None
            raise
        return await asyncio.to_thread(
            self._store_explanation, project_id, paper_id, text, prepared["fingerprint"]
        )
