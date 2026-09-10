from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import httpx

from fastapi import Depends, FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import database_url, openai_headers, openalex_headers
from .domain import PaperPatch, Project, ProjectInput, SubtopicPatch
from .persistence import ProjectRepository
from .service import ProjectNotFound, ProjectService
from .papers import ProjectPaper, ProviderError, SearchRun, Subtopic
from .providers.openai import OpenAIEmbeddingProvider, OpenAILlmProvider
from .providers.openalex import OpenAlexProvider
from .search import SearchService
from .search_persistence import (
    ExplanationUnavailable,
    ManualEditsPresent,
    SearchConflict,
    UnknownCluster,
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

    @app.exception_handler(SearchConflict)
    async def search_conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ExplanationUnavailable)
    async def explanation_unavailable(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(UnknownCluster)
    async def unknown_cluster(request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ManualEditsPresent)
    async def manual_edits_present(request, exc):
        return JSONResponse(
            status_code=409, content={"detail": str(exc), "code": "MANUAL_EDITS_PRESENT"}
        )

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        status = (
            504
            if exc.code == "TIMEOUT"
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

    @app.post("/api/projects/{project_id}/papers/{paper_id}/explanation")
    async def paper_explanation(project_id: UUID, paper_id: UUID):
        return {"explanation": await app.state.search.explain(project_id, paper_id)}

    @app.patch("/api/projects/{project_id}/subtopics/{cluster_id}", response_model=Subtopic)
    def rename_subtopic(project_id: UUID, cluster_id: int, patch: SubtopicPatch):
        return app.state.search.rename_subtopic(project_id, cluster_id, patch)

    @app.patch("/api/projects/{project_id}/papers/{paper_id}", response_model=ProjectPaper)
    def update_paper(project_id: UUID, paper_id: UUID, patch: PaperPatch):
        return app.state.search.update_paper(project_id, paper_id, patch)

    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/projects/new", include_in_schema=False)
    @app.get("/projects/{project_id}", include_in_schema=False)
    @app.get("/projects/{project_id}/edit", include_in_schema=False)
    def frontend():
        return FileResponse(FRONTEND / "index.html")

    return app


app = create_app()
