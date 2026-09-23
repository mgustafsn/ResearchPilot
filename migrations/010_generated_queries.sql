ALTER TABLE search_runs ADD COLUMN "generatedQueries" JSONB NOT NULL DEFAULT '[]'::jsonb;
