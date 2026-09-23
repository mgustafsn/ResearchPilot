ALTER TABLE papers ADD COLUMN "embeddingProvider" TEXT;
ALTER TABLE papers ADD COLUMN "embeddingDimension" INTEGER;
ALTER TABLE papers ADD COLUMN "embeddingInputHash" TEXT;
ALTER TABLE project_papers ADD COLUMN "explanationContextHash" TEXT;
