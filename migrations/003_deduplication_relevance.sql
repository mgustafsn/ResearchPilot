BEGIN;
ALTER TABLE project_papers
    ADD COLUMN "relevanceScore" DOUBLE PRECISION NOT NULL DEFAULT 0
    CHECK ("relevanceScore" BETWEEN 0 AND 1);
ALTER TABLE search_runs
    ADD COLUMN "duplicateCount" INTEGER NOT NULL DEFAULT 0
    CHECK ("duplicateCount" >= 0);
ALTER TABLE project_papers ALTER COLUMN "relevanceScore" DROP DEFAULT;
ALTER TABLE search_runs ALTER COLUMN "duplicateCount" DROP DEFAULT;
COMMIT;
