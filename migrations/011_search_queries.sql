CREATE TABLE search_queries (
    id UUID PRIMARY KEY,
    "projectId" UUID NOT NULL REFERENCES research_projects(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX search_queries_project_id_idx ON search_queries ("projectId");
