BEGIN;
ALTER TABLE research_projects ALTER COLUMN "researchQuestion" DROP NOT NULL;
COMMIT;
