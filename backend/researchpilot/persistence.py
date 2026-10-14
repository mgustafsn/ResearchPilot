from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, String, Uuid, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    pass


class ProjectRow(Base):
    __tablename__ = "research_projects"
    __table_args__ = (
        CheckConstraint("length(trim(title)) BETWEEN 1 AND 200"),
        CheckConstraint('length(trim("researchQuestion")) BETWEEN 1 AND 5000'),
        CheckConstraint('"yearFrom" BETWEEN 1 AND 9999'),
        CheckConstraint('"yearTo" BETWEEN 1 AND 9999'),
        CheckConstraint('"yearFrom" <= "yearTo"'),
        CheckConstraint('"maxPaperCount" BETWEEN 1 AND 1000'),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    researchQuestion: Mapped[str | None] = mapped_column(String(5000))
    keywords: Mapped[list[str]] = mapped_column(JSON)
    yearFrom: Mapped[int | None]
    yearTo: Mapped[int | None]
    maxPaperCount: Mapped[int | None]
    status: Mapped[str] = mapped_column(String(32))
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updatedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ProjectRepository:
    def __init__(self, session: Session):
        self.session = session

    def list(self):
        return self.session.scalars(
            select(ProjectRow).order_by(ProjectRow.updatedAt.desc(), ProjectRow.id)
        ).all()

    def get(self, project_id, for_update=False):
        statement = select(ProjectRow).where(ProjectRow.id == project_id)
        if for_update:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def save(self, row):
        self.session.add(row)
        self.session.flush()
        return row

    def delete(self, row):
        self.session.delete(row)
        self.session.flush()
