BEGIN;
CREATE TABLE research_projects (
    id UUID PRIMARY KEY,
    title VARCHAR(200) NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
    "researchQuestion" VARCHAR(5000) NOT NULL CHECK (length(trim("researchQuestion")) BETWEEN 1 AND 5000),
    keywords JSON NOT NULL,
    "yearFrom" INTEGER CHECK ("yearFrom" BETWEEN 1 AND 9999),
    "yearTo" INTEGER CHECK ("yearTo" BETWEEN 1 AND 9999),
    "maxPaperCount" INTEGER CHECK ("maxPaperCount" BETWEEN 1 AND 1000),
    status VARCHAR(32) NOT NULL,
    "createdAt" TIMESTAMPTZ NOT NULL,
    "updatedAt" TIMESTAMPTZ NOT NULL,
    CHECK ("yearFrom" <= "yearTo")
);
CREATE INDEX "ix_research_projects_updatedAt" ON research_projects ("updatedAt");
COMMIT;
