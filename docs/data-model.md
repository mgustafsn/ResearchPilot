ResearchProject
  id
  title
  researchQuestion
  status
  createdAt
  updatedAt

Paper
  id
  doi
  title
  abstract
  publicationYear
  citationCount
  ...

ProjectPaper
  projectId
  paperId
  relevanceScore
  classificationExplanation
  isRelevant

Subtopic
  id
  projectId
  name
  description
  generatedByAi
  userModified

SubtopicPaper
  subtopicId
  projectPaperId
