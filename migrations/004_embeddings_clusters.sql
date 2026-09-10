BEGIN;
ALTER TABLE papers
    ADD COLUMN "embedding" JSONB,
    ADD COLUMN "embeddingModel" TEXT;
ALTER TABLE project_papers
    ADD COLUMN "clusterId" INTEGER
    CHECK ("clusterId" >= 0);
ALTER TABLE search_runs
    ADD COLUMN "clusterCount" INTEGER NOT NULL DEFAULT 0
    CHECK ("clusterCount" >= 0);
ALTER TABLE search_runs ALTER COLUMN "clusterCount" DROP DEFAULT;
COMMIT;
