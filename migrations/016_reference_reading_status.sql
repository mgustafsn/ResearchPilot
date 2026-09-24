ALTER TABLE project_references
ADD COLUMN "readingStatus" VARCHAR(20) NOT NULL DEFAULT 'TO_READ'
CONSTRAINT ck_reference_reading_status CHECK ("readingStatus" IN ('TO_READ', 'READING', 'READ'));
