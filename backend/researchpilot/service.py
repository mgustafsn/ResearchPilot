from datetime import datetime, timezone
from uuid import uuid4

from .domain import Project, ProjectInput
from .persistence import ProjectRepository, ProjectRow


class ProjectNotFound(Exception):
    pass


class ProjectService:
    def __init__(self, repository: ProjectRepository):
        self.repository = repository

    def list(self):
        return [Project.model_validate(row) for row in self.repository.list()]

    def _get(self, project_id):
        row = self.repository.get(project_id)
        if row is None:
            raise ProjectNotFound()
        return row

    def get(self, project_id):
        return Project.model_validate(self._get(project_id))

    def create(self, data: ProjectInput):
        now = datetime.now(timezone.utc)
        row = ProjectRow(
            id=uuid4(), **data.model_dump(), status="CREATED", createdAt=now, updatedAt=now
        )
        return Project.model_validate(self.repository.save(row))

    def update(self, project_id, data: ProjectInput):
        row = self._get(project_id)
        for key, value in data.model_dump().items():
            setattr(row, key, value)
        row.updatedAt = datetime.now(timezone.utc)
        return Project.model_validate(self.repository.save(row))

    def delete(self, project_id):
        self.repository.delete(self._get(project_id))
