"""Deterministic local providers shared by the API, browser and NFR tests."""

import json
from pathlib import Path

from researchpilot.llm import ClusterNaming, QueryExpansion
from researchpilot.papers import SearchResult
from researchpilot.providers.openalex import normalize_work

WORK = json.loads((Path(__file__).parent / "fixtures/openalex_work.json").read_text())
DATA = {
    "title": "Research",
    "researchQuestion": "large language models",
    "keywords": ["software engineering"],
    "yearFrom": 2021,
    "yearTo": 2026,
    "maxPaperCount": 25,
}


class RecordingProvider:
    name = "Test scholarly provider"

    def __init__(self):
        self.calls = []
        self.error = None
        self.papers = [normalize_work(WORK)]

    async def search(self, parameters):
        self.calls.append(parameters)
        if self.error:
            raise self.error
        return SearchResult(papers=self.papers, totalFound=len(self.papers))


class RecordingEmbeddingProvider:
    name = "Test embedding provider"
    model = "test-embed"
    dimension = 8

    def __init__(self):
        self.batches = []
        self.error = None

    async def embed(self, texts):
        self.batches.append(list(texts))
        if self.error:
            raise self.error
        return [self._vector(text) for text in texts]

    @property
    def paper_batches(self):
        """Batches that embedded papers; each call leads with the research question."""
        return [batch[1:] for batch in self.batches if len(batch) > 1]

    def _vector(self, text):
        # Index 7 is a shared "on topic" axis; marine texts are off topic.
        vector = [0.0] * self.dimension
        if "marine" in text.casefold():
            vector[6] = 10.0
            return vector
        for index, marker in enumerate(("alpha", "bravo", "charlie")):
            if marker in text:
                vector[index] = 10.0
                vector[7] = 10.0
                return vector
        return [1.0] * self.dimension


class RecordingLlmProvider:
    name = "Test LLM provider"
    model = "test-llm"

    def __init__(self):
        self.calls = []
        self.error = None
        self.explain_calls = []
        self.explain_error = None
        self.expansion = []
        self.expansion_error = None

    async def name_cluster(self, question, papers):
        self.calls.append((question, list(papers)))
        if self.error:
            raise self.error
        marker = (papers[0].title or "topic").split()[0]
        return ClusterNaming(
            name=f"Topic {marker}", description=f"Papers about {marker}.", keywords=[marker.lower()]
        )

    async def expand_queries(self, question, keywords):
        if self.expansion_error:
            raise self.expansion_error
        return QueryExpansion(queries=self.expansion)

    async def explain_paper(self, question, subtopic, paper):
        self.explain_calls.append((question, subtopic, paper))
        if self.explain_error:
            raise self.explain_error
        return f"{paper.title} fits {subtopic}."


def grouped_papers(groups=("alpha", "bravo", "charlie"), per_group=5):
    return [
        normalize_work(
            WORK
            | {
                "id": f"https://openalex.org/W1{groups.index(group)}{n}",
                "doi": f"https://doi.org/10.5000/{group}-{n}",
                "title": f"{group} paper {n} about large language models",
                "abstract_inverted_index": None,
            }
        )
        for group in groups
        for n in range(per_group)
    ]


_grouped_papers = grouped_papers
