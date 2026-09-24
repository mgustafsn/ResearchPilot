ALTER TABLE project_references
DROP CONSTRAINT "project_references_projectId_number_key";

ALTER TABLE project_references
RENAME COLUMN number TO "citationNumber";

ALTER TABLE project_references
ALTER COLUMN "citationNumber" DROP NOT NULL,
ADD COLUMN "isCited" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN "previousCitationNumber" INTEGER;

-- Start every reference uncited, but keep its old number so it can be restored.
UPDATE project_references
SET "previousCitationNumber" = "citationNumber", "citationNumber" = NULL, "isCited" = false;

ALTER TABLE project_references
ADD CONSTRAINT ck_reference_previous_citation_number_positive
    CHECK ("previousCitationNumber" IS NULL OR "previousCitationNumber" > 0),
ADD CONSTRAINT ck_reference_uncited_has_no_number
    CHECK ("isCited" OR "citationNumber" IS NULL),
ADD CONSTRAINT uq_reference_project_citation_number
    UNIQUE ("projectId", "citationNumber");
