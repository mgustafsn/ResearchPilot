from contextlib import asynccontextmanager
import os
from pathlib import Path
from uuid import UUID

import httpx

from fastapi import Depends, FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .config import database_url, openai_headers, openalex_headers
from .domain import (
    PaperPatch,
    Project,
    ProjectInput,
    QueryInput,
    QueryPatch,
    SubtopicInput,
    SubtopicMerge,
    SubtopicPatch,
)
from .persistence import ProjectRepository
from .service import ProjectNotFound, ProjectService
from .papers import ProjectPaper, ProviderError, SearchQuery, SearchRun, Subtopic
from .providers.openai import OpenAIEmbeddingProvider, OpenAILlmProvider
from .providers.openalex import OpenAlexProvider
from .search import DuplicateQuery, InvalidQuery, NoEnabledQueries, SearchService
from .search_persistence import (
    ExplanationUnavailable,
    ManualEditsPresent,
    SearchConflict,
    UnknownCluster,
)
from .references import (
    ManualReferenceInput,
    ReferenceConflict,
    ReferenceMissing,
    ReferencePatch,
    ReferenceService,
)

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def create_app(engine=None, provider=None, embedding_provider=None, llm_provider=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = (
            engine if engine is not None else create_engine(database_url(), pool_pre_ping=True)
        )
        async with (
            httpx.AsyncClient(headers=openalex_headers(), timeout=15.0) as client,
            httpx.AsyncClient(headers=openai_headers(), timeout=30.0) as openai_client,
        ):
            app.state.search = SearchService(
                app.state.engine,
                provider or OpenAlexProvider(client),
                embedding_provider or OpenAIEmbeddingProvider(openai_client),
                llm_provider or OpenAILlmProvider(openai_client),
            )
            try:
                yield
            finally:
                if engine is None:
                    app.state.engine.dispose()

    app = FastAPI(title="ResearchPilot", lifespan=lifespan)

    def service():
        with Session(app.state.engine) as session, session.begin():
            yield ProjectService(ProjectRepository(session))

    def references():
        with Session(app.state.engine) as session, session.begin():
            yield ReferenceService(session)

    @app.exception_handler(ReferenceMissing)
    async def reference_missing(request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ReferenceConflict)
    async def reference_conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(IntegrityError)
    async def reference_integrity(request, exc):
        return JSONResponse(
            status_code=409, content={"detail": "Reference number or DOI already used"}
        )

    @app.exception_handler(ProjectNotFound)
    async def not_found(request, exc):
        return JSONResponse(status_code=404, content={"detail": "Project not found"})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Database unavailable. Try again."})

    @app.get("/api/projects", response_model=list[Project])
    def list_projects(svc=Depends(service, scope="function")):
        return svc.list()

    @app.post("/api/projects", response_model=Project, status_code=201)
    def create_project(
        data: ProjectInput, response: Response, svc=Depends(service, scope="function")
    ):
        project = svc.create(data)
        response.headers["Location"] = f"/api/projects/{project.id}"
        return project

    @app.get("/api/projects/{project_id}", response_model=Project)
    def get_project(project_id: UUID, svc=Depends(service, scope="function")):
        return svc.get(project_id)

    @app.put("/api/projects/{project_id}", response_model=Project)
    def update_project(
        project_id: UUID, data: ProjectInput, svc=Depends(service, scope="function")
    ):
        return svc.update(project_id, data)

    @app.delete("/api/projects/{project_id}", status_code=204)
    def delete_project(project_id: UUID, svc=Depends(service, scope="function")):
        svc.delete(project_id)
        return Response(status_code=204)

    @app.get("/api/settings/status")
    def settings_status():
        return {
            "scholarlyProvider": "OpenAlex",
            "openAlexApiKeyConfigured": bool(os.environ.get("OPENALEX_API_KEY", "").strip()),
            "openAlexEmailConfigured": bool(os.environ.get("OPENALEX_EMAIL", "").strip()),
            "llmProvider": "OpenAI",
            "openAiApiKeyConfigured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
            "customOpenAiEndpointConfigured": bool(os.environ.get("OPENAI_BASE_URL", "").strip()),
        }

    @app.get("/api/projects/{project_id}/references")
    def list_references(project_id: UUID, svc=Depends(references, scope="function")):
        return svc.list(project_id)

    @app.post("/api/projects/{project_id}/references", status_code=201)
    def add_reference(
        project_id: UUID, data: ManualReferenceInput, svc=Depends(references, scope="function")
    ):
        return svc.add_manual(project_id, data)

    @app.post("/api/projects/{project_id}/references/from-paper/{paper_id}")
    def save_paper_reference(
        project_id: UUID, paper_id: UUID, svc=Depends(references, scope="function")
    ):
        return svc.save_paper(project_id, paper_id)

    @app.patch("/api/projects/{project_id}/references/{reference_id}")
    def update_reference(
        project_id: UUID,
        reference_id: UUID,
        data: ReferencePatch,
        svc=Depends(references, scope="function"),
    ):
        return svc.update(project_id, reference_id, data)

    @app.delete("/api/projects/{project_id}/references/{reference_id}", status_code=204)
    def delete_reference(
        project_id: UUID, reference_id: UUID, svc=Depends(references, scope="function")
    ):
        svc.delete(project_id, reference_id)
        return Response(status_code=204)

    @app.exception_handler(SearchConflict)
    async def search_conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ExplanationUnavailable)
    async def explanation_unavailable(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(UnknownCluster)
    async def unknown_cluster(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(InvalidQuery)
    async def invalid_query(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(DuplicateQuery)
    async def duplicate_query(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(NoEnabledQueries)
    async def no_enabled_queries(request, exc):
        return JSONResponse(
            status_code=422, content={"detail": str(exc), "code": "NO_ENABLED_QUERIES"}
        )

    @app.exception_handler(ManualEditsPresent)
    async def manual_edits_present(request, exc):
        return JSONResponse(
            status_code=409, content={"detail": str(exc), "code": "MANUAL_EDITS_PRESENT"}
        )

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        status = (
            504
            if exc.code in {"TIMEOUT", "EXPLANATION_TIMEOUT"}
            else 503
            if exc.code
            in {
                "RATE_LIMITED",
                "AUTHENTICATION",
                "UNAVAILABLE",
                "EMBEDDING_UNAUTHORIZED",
                "EMBEDDING_RATE_LIMITED",
                "EMBEDDING_UNAVAILABLE",
                "LLM_UNAUTHORIZED",
                "LLM_RATE_LIMITED",
                "LLM_UNAVAILABLE",
            }
            else 502
        )
        return JSONResponse(status_code=status, content={"detail": str(exc), "code": exc.code})

    @app.post("/api/projects/{project_id}/search", response_model=SearchRun)
    async def search_project(project_id: UUID, force: bool = False):
        return await app.state.search.search(project_id, force)

    @app.get("/api/projects/{project_id}/searches", response_model=list[SearchRun])
    def search_history(project_id: UUID):
        return app.state.search.history(project_id)

    @app.get("/api/projects/{project_id}/papers", response_model=list[ProjectPaper])
    def project_papers(project_id: UUID):
        return app.state.search.papers(project_id)

    @app.get("/api/projects/{project_id}/subtopics", response_model=list[Subtopic])
    def project_subtopics(project_id: UUID):
        return app.state.search.subtopics(project_id)

    @app.get("/api/projects/{project_id}/queries", response_model=list[SearchQuery])
    def project_queries(project_id: UUID):
        return app.state.search.project_queries(project_id)

    @app.post("/api/projects/{project_id}/queries", response_model=list[SearchQuery])
    async def expand_project_queries(project_id: UUID):
        return await app.state.search.expand_project_queries(project_id)

    @app.post(
        "/api/projects/{project_id}/queries/custom", response_model=SearchQuery, status_code=201
    )
    def add_query(project_id: UUID, body: QueryInput):
        return app.state.search.add_query(project_id, body.query)

    @app.patch("/api/projects/{project_id}/queries/{query_id}", response_model=SearchQuery)
    def update_query(project_id: UUID, query_id: UUID, patch: QueryPatch):
        return app.state.search.update_query(project_id, query_id, patch)

    @app.delete("/api/projects/{project_id}/queries/{query_id}", status_code=204)
    def delete_query(project_id: UUID, query_id: UUID):
        app.state.search.delete_query(project_id, query_id)
        return Response(status_code=204)

    @app.post("/api/projects/{project_id}/papers/{paper_id}/explanation")
    async def paper_explanation(project_id: UUID, paper_id: UUID):
        return {"explanation": await app.state.search.explain(project_id, paper_id)}

    @app.patch("/api/projects/{project_id}/subtopics/{cluster_id}", response_model=Subtopic)
    def rename_subtopic(project_id: UUID, cluster_id: int, patch: SubtopicPatch):
        return app.state.search.rename_subtopic(project_id, cluster_id, patch)

    @app.post("/api/projects/{project_id}/subtopics", response_model=Subtopic, status_code=201)
    def create_subtopic(project_id: UUID, patch: SubtopicInput):
        return app.state.search.create_subtopic(project_id, patch)

    @app.delete("/api/projects/{project_id}/subtopics/{cluster_id}", status_code=204)
    def delete_subtopic(project_id: UUID, cluster_id: int):
        app.state.search.delete_subtopic(project_id, cluster_id)
        return Response(status_code=204)

    @app.post("/api/projects/{project_id}/subtopics/{cluster_id}/merge", response_model=Subtopic)
    def merge_subtopics(project_id: UUID, cluster_id: int, patch: SubtopicMerge):
        return app.state.search.merge_subtopics(project_id, cluster_id, patch.targetClusterId)

    @app.patch("/api/projects/{project_id}/papers/{paper_id}", response_model=ProjectPaper)
    def update_paper(project_id: UUID, paper_id: UUID, patch: PaperPatch):
        return app.state.search.update_paper(project_id, paper_id, patch)

    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/projects/new", include_in_schema=False)
    @app.get("/settings", include_in_schema=False)
    @app.get("/projects/{project_id}", include_in_schema=False)
    @app.get("/projects/{project_id}/edit", include_in_schema=False)
    def frontend():
        return FileResponse(FRONTEND / "index.html")

    return app


app = create_app()
