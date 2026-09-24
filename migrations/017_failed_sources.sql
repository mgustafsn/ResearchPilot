ALTER TABLE search_runs ADD COLUMN "failedSources" JSONB NOT NULL DEFAULT '[]'::jsonb;
