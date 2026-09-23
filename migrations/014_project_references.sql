CREATE TABLE project_references (
    id UUID PRIMARY KEY,
    "projectId" UUID NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    "paperId" UUID REFERENCES papers(id),
    number INTEGER NOT NULL CHECK (number > 0),
    title TEXT,
    authors JSON NOT NULL,
    year INTEGER,
    venue TEXT,
    doi TEXT,
    "doiNormalized" TEXT,
    url TEXT,
    notes TEXT NOT NULL,
    status VARCHAR(20),
    manual BOOLEAN NOT NULL,
    UNIQUE ("projectId", number),
    UNIQUE ("projectId", "doiNormalized"),
    UNIQUE ("projectId", "paperId")
);
CREATE INDEX "ix_project_references_projectId" ON project_references ("projectId");
