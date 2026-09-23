ALTER TABLE search_runs ADD COLUMN "failedQueries" JSONB NOT NULL DEFAULT '[]'::jsonb;
