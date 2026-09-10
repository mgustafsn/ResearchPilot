BEGIN;
CREATE TABLE papers (
    id UUID PRIMARY KEY,
    source VARCHAR(100) NOT NULL,
    "sourceId" TEXT NOT NULL,
    "sourceUrl" TEXT NOT NULL,
    title TEXT,
    doi TEXT,
    "doiUrl" TEXT,
    abstract TEXT,
    authors JSON NOT NULL,
    "publicationYear" INTEGER,
    "publicationDate" DATE,
    journal TEXT,
    venue TEXT,
    publisher TEXT,
    "citationCount" INTEGER,
    "publicationUrl" TEXT,
    "openAccessUrl" TEXT,
    "isOpenAccess" BOOLEAN,
    UNIQUE (source, "sourceId")
);
CREATE TABLE search_runs (
    id UUID PRIMARY KEY,
    "projectId" UUID NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    provider VARCHAR(100) NOT NULL,
    parameters JSON NOT NULL,
    "researchQuestion" TEXT NOT NULL,
    keywords JSON NOT NULL,
    status VARCHAR(32) NOT NULL,
    "startedAt" TIMESTAMPTZ NOT NULL,
    "finishedAt" TIMESTAMPTZ,
    "totalFound" INTEGER,
    "paperCount" INTEGER NOT NULL,
    "skippedCount" INTEGER NOT NULL,
    "errorCode" VARCHAR(32),
    "errorMessage" TEXT
);
CREATE INDEX "ix_search_runs_projectId" ON search_runs ("projectId");
CREATE TABLE project_papers (
    "projectId" UUID NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    "paperId" UUID NOT NULL REFERENCES papers(id),
    "searchRunId" UUID NOT NULL REFERENCES search_runs(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    PRIMARY KEY ("projectId", "paperId")
);
COMMIT;
