BEGIN;
CREATE TABLE subtopics (
    "projectId" UUID NOT NULL REFERENCES research_projects (id) ON DELETE CASCADE,
    "clusterId" INTEGER NOT NULL CHECK ("clusterId" >= 0),
    "searchRunId" UUID NOT NULL REFERENCES search_runs (id) ON DELETE CASCADE,
    "name" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "keywords" JSONB NOT NULL,
    PRIMARY KEY ("projectId", "clusterId")
);
ALTER TABLE search_runs ADD COLUMN "namingError" VARCHAR(32);
COMMIT;
