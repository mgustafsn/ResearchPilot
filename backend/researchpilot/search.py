"""Search orchestration: short database transactions around a bounded provider call."""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from .papers import PaperProvider, ProviderError, SearchParameters, SearchRun
from .persistence import ProjectRepository
from .search_persistence import SearchRepository, SearchRunRow, SearchConflict, expire_search
from .service import ProjectNotFound

logger = logging.getLogger(__name__)
SEARCH_TIMEOUT_SECONDS = 60


class SearchService:
    def __init__(self, engine, provider: PaperProvider):
        self.engine = engine
        self.provider = provider

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
            )
            session.add(run)
            project.status = "SEARCHING"
            session.flush()
            return SearchRun.model_validate(run)

    def finish(self, run, result=None, error=None):
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
                latest.paperCount = repository.replace_papers(project.id, run.id, result.papers)
                latest.totalFound = result.totalFound
                latest.skippedCount = result.skippedCount
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
            finished = await asyncio.to_thread(self.finish, run, result=result)
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
        logger.info("Search completed run=%s papers=%s", run.id, finished.paperCount)
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
