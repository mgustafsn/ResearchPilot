from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .config import database_url
from .domain import Project, ProjectInput
from .persistence import ProjectRepository
from .service import ProjectNotFound, ProjectService

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def create_app(engine=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.engine = (
            engine if engine is not None else create_engine(database_url(), pool_pre_ping=True)
        )
        yield
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

    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/", include_in_schema=False)
    @app.get("/projects/new", include_in_schema=False)
    @app.get("/projects/{project_id}", include_in_schema=False)
    @app.get("/projects/{project_id}/edit", include_in_schema=False)
    def frontend():
        return FileResponse(FRONTEND / "index.html")

    return app


app = create_app()
