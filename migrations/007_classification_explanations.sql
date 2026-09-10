BEGIN;
ALTER TABLE project_papers ADD COLUMN "classificationExplanation" TEXT;
COMMIT;
