import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from researchpilot.api import create_app
from researchpilot.llm import ClusterNaming, QueryExpansion
from researchpilot.papers import ProviderError, SearchResult
from researchpilot.providers.openalex import normalize_work
from researchpilot.search_persistence import PaperRow, ProjectPaperRow, SearchRunRow

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


@pytest.fixture
def search_client(engine):
    provider = RecordingProvider()
    with TestClient(
        create_app(engine, provider, RecordingEmbeddingProvider(), RecordingLlmProvider())
    ) as client:
        project = client.post("/api/projects", json=DATA).json()
        yield client, provider, f"/api/projects/{project['id']}"


@pytest.fixture
def search_client_with_embedder(engine):
    provider = RecordingProvider()
    embedder = RecordingEmbeddingProvider()
    with TestClient(create_app(engine, provider, embedder, RecordingLlmProvider())) as client:
        project = client.post("/api/projects", json=DATA).json()
        yield client, provider, embedder, f"/api/projects/{project['id']}"


@pytest.fixture
def search_client_named(engine):
    provider = RecordingProvider()
    embedder = RecordingEmbeddingProvider()
    llm = RecordingLlmProvider()
    with TestClient(create_app(engine, provider, embedder, llm)) as client:
        project = client.post("/api/projects", json=DATA).json()
        yield client, provider, embedder, llm, f"/api/projects/{project['id']}"


def test_search_persists_real_metadata_and_snapshot(search_client, engine):
    client, provider, url = search_client
    response = client.post(url + "/search")
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "COMPLETED"
    assert run["parameters"] == {
        "query": DATA["researchQuestion"],
        "yearFrom": 2021,
        "yearTo": 2026,
        "maxPaperCount": 25,
    }
    assert run["keywords"] == DATA["keywords"]
    assert run["paperCount"] == 1
    assert run["duplicateCount"] == 0
    assert run["filteredCount"] == 0
    assert run["clusterCount"] == 1
    assert run["startedAt"] and run["finishedAt"]
    papers = client.get(url + "/papers").json()
    assert papers[0]["title"] == WORK["title"]
    assert papers[0]["sourceId"] == WORK["id"]
    assert papers[0]["clusterId"] == 0
    assert client.get(url).json()["status"] == "COMPLETED"
    assert client.get(url + "/searches").json()[0] == run
    with TestClient(create_app(engine, provider)) as restarted:
        assert restarted.get(url + "/papers").json() == papers
    assert 0 <= papers[0]["relevanceScore"] <= 1


def test_reference_library_survives_search_and_merges_matching_manual_doi(search_client):
    client, provider, url = search_client
    paper = provider.papers[0]
    manual = client.post(
        url + "/references",
        json={
            "title": "My annotated citation",
            "doi": paper.doi,
            "authors": ["Researcher One"],
            "status": "Draft",
            "notes": "Keep this version",
        },
    )
    assert manual.status_code == 201
    reference = manual.json()
    assert reference["number"] == 1
    assert reference["url"] is None
    assert (
        client.post(url + "/references", json={"title": "Duplicate", "doi": paper.doi}).status_code
        == 409
    )
    assert (
        client.post(url + "/references", json={"title": "Second", "number": 1}).status_code == 409
    )
    assert client.post(url + "/search").status_code == 200
    paper_id = client.get(url + "/papers").json()[0]["id"]
    saved = client.post(url + "/references/from-paper/" + paper_id)
    assert saved.status_code == 200
    assert saved.json()["id"] == reference["id"]
    assert saved.json()["title"] == "My annotated citation"
    assert saved.json()["sourceUrl"]
    assert client.post(url + "/references/from-paper/" + paper_id).json()["id"] == reference["id"]
    provider.papers = []
    client.post(url + "/search")
    assert client.get(url + "/references").json()[0]["id"] == reference["id"]


def test_reference_edit_is_project_scoped_and_scholarly_metadata_is_immutable(search_client):
    client, _, url = search_client
    client.post(url + "/search")
    paper_id = client.get(url + "/papers").json()[0]["id"]
    reference = client.post(url + "/references/from-paper/" + paper_id).json()
    path = url + "/references/" + reference["id"]
    assert client.patch(path, json={"title": "Invented title"}).status_code == 409
    changed = client.patch(path, json={"number": 3, "notes": "Read later"})
    assert changed.status_code == 200
    assert changed.json()["number"] == 3
    other = client.post("/api/projects", json=DATA).json()
    other_path = f"/api/projects/{other['id']}/references/{reference['id']}"
    assert client.patch(other_path, json={"notes": "No"}).status_code == 404
    assert client.delete(other_path).status_code == 404
    assert client.delete(path).status_code == 204
    assert client.get(url + "/references").json() == []
    assert client.post(url + "/references", json={"title": "Unlinked draft"}).status_code == 201
    assert client.delete(url).status_code == 204
    assert client.get(url + "/references").status_code == 404


def test_settings_status_exposes_only_configuration_flags(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-test-key")
    response = client.get("/api/settings/status")
    assert response.status_code == 200
    assert response.json()["openAiApiKeyConfigured"] is True
    assert "secret-test-key" not in response.text


def _retrieved(provider):
    return [parameters.query for parameters in provider.calls]


def test_search_uses_generated_queries_never_the_description(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion = ["generative AI software development", "LLM code generation"]
    run = client.post(url + "/search").json()
    # Saved queries are listed case-insensitively alphabetical.
    assert run["generatedQueries"] == ["generative AI software development", "LLM code generation"]
    assert _retrieved(provider) == run["generatedQueries"]
    assert DATA["researchQuestion"] not in _retrieved(provider)
    saved = client.get(url + "/queries").json()
    assert [(q["query"], q["userAdded"]) for q in saved] == [
        ("generative AI software development", False),
        ("LLM code generation", False),
    ]


def test_disabled_queries_are_not_retrieved(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion = ["alternate query", "second query"]
    first = client.post(url + "/queries").json()[0]
    client.patch(f"{url}/queries/{first['id']}", json={"enabled": False})
    client.post(url + "/search")
    assert _retrieved(provider) == ["second query"]


def test_search_with_no_enabled_query_is_rejected_without_a_run(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion = ["only query"]
    only = client.post(url + "/queries").json()[0]
    client.patch(f"{url}/queries/{only['id']}", json={"enabled": False})
    response = client.post(url + "/search")
    assert response.status_code == 422
    assert response.json()["code"] == "NO_ENABLED_QUERIES"
    assert provider.calls == []
    assert client.get(url + "/searches").json() == []
    assert client.get(url).json()["status"] != "SEARCHING"


def test_expand_queries_raises_when_all_saved_queries_become_disabled(search_client_named, engine):
    """Only reachable via an expired-lease race: start() already blocks this at request time."""
    from researchpilot.search import NoEnabledQueries
    from researchpilot.search_persistence import SearchQueryRow

    client, provider, _, llm, url = search_client_named
    project_id = UUID(url.split("/")[-1])
    _add(client, url, "only query")
    service = client.app.state.search
    run = service.start(project_id)
    with Session(engine) as session, session.begin():
        row = session.scalar(select(SearchQueryRow).where(SearchQueryRow.projectId == project_id))
        row.enabled = False
    with pytest.raises(NoEnabledQueries):
        asyncio.run(service._expand_queries(run))


def test_empty_expansion_falls_back_to_keywords(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion = []
    client.post(url + "/search")
    assert _retrieved(provider) == DATA["keywords"]


def test_expansion_failure_falls_back_to_keywords(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion_error = ProviderError("LLM_UNAVAILABLE")
    client.post(url + "/search")
    assert _retrieved(provider) == DATA["keywords"]


def test_no_keywords_falls_back_to_project_title(search_client_named):
    client, provider, _, llm, url = search_client_named
    client.put(url, json={**DATA, "keywords": []})
    llm.expansion = []
    client.post(url + "/search")
    assert _retrieved(provider) == [DATA["title"]]


def test_fallback_query_from_title_is_truncated_to_query_max(search_client_named):
    client, provider, _, llm, url = search_client_named
    long_title = "T" * 200
    client.put(url, json={**DATA, "title": long_title, "keywords": []})
    llm.expansion = []
    client.post(url + "/search")
    retrieved = _retrieved(provider)
    assert retrieved == [long_title[:160]]
    saved = client.get(url + "/queries").json()
    assert len(saved[0]["query"]) == 160


def _add(client, url, text):
    return client.post(url + "/queries/custom", json={"query": text})


def test_user_can_add_edit_toggle_and_delete_queries(search_client_named):
    client, _, _, _, url = search_client_named
    added = _add(client, url, "  terraform   provisioning ")
    assert added.status_code == 201
    query = added.json()
    assert query["query"] == "terraform provisioning"
    assert query["userAdded"] is True and query["enabled"] is True
    toggled = client.patch(f"{url}/queries/{query['id']}", json={"enabled": False})
    assert toggled.status_code == 200 and toggled.json()["enabled"] is False
    edited = client.patch(f"{url}/queries/{query['id']}", json={"query": "terraform modules"})
    assert edited.json()["query"] == "terraform modules"
    assert client.delete(f"{url}/queries/{query['id']}").status_code == 204
    assert client.get(url + "/queries").json() == []


def test_editing_a_generated_query_makes_it_the_users(search_client_named):
    client, _, _, llm, url = search_client_named
    llm.expansion = ["infrastructure as code"]
    generated = client.post(url + "/queries").json()[0]
    assert generated["userAdded"] is False
    edited = client.patch(f"{url}/queries/{generated['id']}", json={"query": "iac tooling"})
    assert edited.json()["userAdded"] is True


def test_query_validation_duplicates_and_cap(search_client_named):
    client, _, _, _, url = search_client_named
    assert _add(client, url, "   ").status_code == 422
    assert _add(client, url, "x" * 161).status_code == 422
    assert _add(client, url, "Cloud Automation").status_code == 201
    assert _add(client, url, "cloud automation").status_code == 409
    for n in range(9):
        assert _add(client, url, f"query {n}").status_code == 201
    assert _add(client, url, "one too many").status_code == 422
    assert client.patch(f"{url}/queries/{uuid4()}", json={"enabled": False}).status_code == 404
    first = client.get(url + "/queries").json()[0]
    assert client.patch(f"{url}/queries/{first['id']}", json={}).status_code == 422


def test_regenerate_keeps_user_queries_and_skips_duplicates(search_client_named):
    client, _, _, llm, url = search_client_named
    _add(client, url, "terraform")
    llm.expansion = ["Terraform", "policy as code"]
    queries = client.post(url + "/queries").json()
    assert [(q["query"], q["userAdded"]) for q in queries] == [
        ("policy as code", False),
        ("terraform", True),
    ]
    llm.expansion = ["cloud provisioning"]
    queries = client.post(url + "/queries").json()
    assert [q["query"] for q in queries] == ["cloud provisioning", "terraform"]


def test_project_edit_clears_generated_queries_only(search_client_named):
    client, _, _, llm, url = search_client_named
    llm.expansion = ["alternate query"]
    client.post(url + "/queries")
    _add(client, url, "my own query")
    changed = {**DATA, "researchQuestion": "new research description"}
    assert client.put(url, json=changed).status_code == 200
    assert [q["query"] for q in client.get(url + "/queries").json()] == ["my own query"]


def test_query_edits_are_blocked_during_a_search(search_client_named):
    client, _, _, _, url = search_client_named
    query = _add(client, url, "terraform").json()
    # Opens a real active run, as test_organization_search_lease does.
    client.app.state.search.start(UUID(url.split("/")[-1]))
    assert _add(client, url, "another").status_code == 409
    assert client.patch(f"{url}/queries/{query['id']}", json={"enabled": False}).status_code == 409
    assert client.delete(f"{url}/queries/{query['id']}").status_code == 409


def test_repeated_search_and_shared_papers(search_client, engine):
    client, provider, url = search_client
    for _ in range(2):
        assert client.post(url + "/search").status_code == 200
    other = client.post("/api/projects", json=DATA).json()["id"]
    assert client.post(f"/api/projects/{other}/search").status_code == 200
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(PaperRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProjectPaperRow)) == 2
    assert len(client.get(url + "/searches").json()) == 2
    assert client.delete(url).status_code == 204
    assert len(client.get(f"/api/projects/{other}/papers").json()) == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(SearchRunRow)) == 1
        assert session.scalar(select(func.count()).select_from(ProjectPaperRow)) == 1


def test_search_deduplicates_ranks_and_persists_counts(search_client):
    client, provider, url = search_client
    relevant = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W100",
            "doi": "https://doi.org/10.1000/shared",
            "title": "Large language models for software engineering",
        }
    )
    duplicate = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W101",
            "doi": "https://doi.org/10.1000/SHARED",
            "title": "A less complete duplicate",
            "abstract_inverted_index": None,
        }
    )
    unrelated = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W102",
            "doi": "https://doi.org/10.1000/other",
            "title": "Marine biology observations",
            "abstract_inverted_index": None,
            "cited_by_count": 0,
        }
    )
    provider.papers = [unrelated, duplicate, relevant]
    response = client.post(url + "/search")
    assert response.status_code == 200
    assert response.json()["duplicateCount"] == 1
    assert response.json()["paperCount"] == 1
    assert response.json()["filteredCount"] == 1
    papers = client.get(url + "/papers").json()
    assert [item["doi"] for item in papers] == ["10.1000/shared"]


def _grouped_papers():
    return [
        normalize_work(
            WORK
            | {
                "id": f"https://openalex.org/W1{['alpha', 'bravo', 'charlie'].index(group)}{n}",
                "doi": f"https://doi.org/10.5000/{group}-{n}",
                "title": f"{group} paper {n} about large language models",
                "abstract_inverted_index": None,
            }
        )
        for group in ("alpha", "bravo", "charlie")
        for n in range(5)
    ]


def test_search_embeds_and_clusters_papers(search_client_with_embedder):
    client, provider, embedder, url = search_client_with_embedder
    provider.papers = _grouped_papers()
    run = client.post(url + "/search").json()
    assert run["clusterCount"] == 3
    papers = client.get(url + "/papers").json()
    assert {paper["clusterId"] for paper in papers} == {0, 1, 2}
    # One batch: the research question plus the 15 papers.
    assert [len(batch) for batch in embedder.batches] == [16]
    assert embedder.batches[0][0] == DATA["researchQuestion"] + " " + " ".join(DATA["keywords"])


def test_embeddings_are_reused_on_a_second_search(search_client_with_embedder):
    client, provider, embedder, url = search_client_with_embedder
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    client.post(url + "/search")
    # Paper vectors are reused; only the research question is embedded again.
    assert [len(batch) for batch in embedder.batches] == [16, 1]


def test_relevance_comes_from_semantic_similarity(search_client_with_embedder):
    client, provider, embedder, url = search_client_with_embedder
    wordy = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W201",
            "doi": "https://doi.org/10.1000/wordy",
            "title": DATA["researchQuestion"] + " in marine ecosystems",
        }
    )
    related = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W202",
            "doi": "https://doi.org/10.1000/related",
            "title": "A study of alpha systems",
            "abstract_inverted_index": None,
        }
    )
    provider.papers = [wordy, related]
    run = client.post(url + "/search").json()
    assert run["filteredCount"] == 1
    papers = client.get(url + "/papers").json()
    assert [paper["doi"] for paper in papers] == ["10.1000/related"]
    assert papers[0]["relevanceScore"] > 0.4


def test_embedding_failure_preserves_previous_results(search_client_with_embedder):
    client, provider, embedder, url = search_client_with_embedder
    client.post(url + "/search")
    original = client.get(url + "/papers").json()
    embedder.error = ProviderError("EMBEDDING_UNAVAILABLE")
    provider.papers = [normalize_work(WORK | {"id": "https://openalex.org/W999"})]
    assert client.post(url + "/search").status_code == 503
    assert client.get(url + "/papers").json() == original
    history = client.get(url + "/searches").json()
    assert history[0]["status"] == "FAILED"
    assert history[0]["errorCode"] == "EMBEDDING_UNAVAILABLE"


def test_search_names_each_cluster(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    run = client.post(url + "/search").json()
    assert run["clusterCount"] == 3
    assert run["namingError"] is None
    assert len(llm.calls) == 3
    subtopics = client.get(url + "/subtopics").json()
    assert {s["clusterId"] for s in subtopics} == {0, 1, 2}
    by_cluster = {s["clusterId"]: s for s in subtopics}
    for topic in by_cluster.values():
        assert topic["name"].startswith("Topic ")
        assert topic["description"]
        assert topic["keywords"]


def test_naming_failure_completes_search_with_fallback(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    llm.error = ProviderError("LLM_RATE_LIMITED")
    run = client.post(url + "/search").json()
    assert run["status"] == "COMPLETED"
    assert run["clusterCount"] == 3
    assert run["namingError"] == "LLM_RATE_LIMITED"
    assert client.get(url + "/subtopics").json() == []
    assert {p["clusterId"] for p in client.get(url + "/papers").json()} == {0, 1, 2}


def test_subtopics_are_replaced_on_a_new_search(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    assert len(client.get(url + "/subtopics").json()) == 3
    provider.papers = [normalize_work(WORK)]
    client.post(url + "/search")
    assert client.get(url + "/subtopics").json() == []  # single cluster, not named


def test_explanation_is_generated_then_cached(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper = client.get(url + "/papers").json()[0]
    assert paper["classificationExplanation"] is None

    first = client.post(f"{url}/papers/{paper['id']}/explanation")
    assert first.status_code == 200
    assert (
        first.json()["explanation"] == f"{paper['title']} fits Topic {paper['title'].split()[0]}."
    )
    assert len(llm.explain_calls) == 1
    assert (
        client.get(url + "/papers").json()[0]["classificationExplanation"]
        == first.json()["explanation"]
    )

    second = client.post(f"{url}/papers/{paper['id']}/explanation")
    assert second.json() == first.json()
    assert len(llm.explain_calls) == 1  # served from cache, no second LLM call


def test_explanation_requires_a_named_subtopic(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = [normalize_work(WORK)]  # single cluster, no subtopic
    client.post(url + "/search")
    paper_id = client.get(url + "/papers").json()[0]["id"]
    assert client.post(f"{url}/papers/{paper_id}/explanation").status_code == 422
    assert llm.explain_calls == []


def test_explanation_unknown_paper_is_404(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    assert client.post(f"{url}/papers/{uuid4()}/explanation").status_code == 404


def test_explanation_llm_failure_propagates(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper_id = client.get(url + "/papers").json()[0]["id"]
    llm.explain_error = ProviderError("LLM_RATE_LIMITED")
    assert client.post(f"{url}/papers/{paper_id}/explanation").status_code == 503


def test_new_search_clears_stored_explanations(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper_id = client.get(url + "/papers").json()[0]["id"]
    client.post(f"{url}/papers/{paper_id}/explanation")
    client.post(url + "/search")
    assert all(p["classificationExplanation"] is None for p in client.get(url + "/papers").json())


def _named_search(client, provider, url):
    provider.papers = _grouped_papers()
    client.post(url + "/search")


def test_rename_subtopic_marks_it_modified(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    _named_search(client, provider, url)
    cluster_id = client.get(url + "/subtopics").json()[0]["clusterId"]
    response = client.patch(
        f"{url}/subtopics/{cluster_id}", json={"name": "  My Topic  ", "description": "Edited."}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "My Topic"
    assert response.json()["description"] == "Edited."
    assert response.json()["userModified"] is True
    fetched = client.get(url + "/subtopics").json()
    assert fetched[0]["name"] == "My Topic"
    assert fetched[0]["userModified"] is True


def test_rename_unknown_subtopic_is_404(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    _named_search(client, provider, url)
    assert client.patch(f"{url}/subtopics/99", json={"name": "x"}).status_code == 404


def test_move_paper_between_clusters(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    _named_search(client, provider, url)
    papers = client.get(url + "/papers").json()
    paper = papers[0]
    target = next(p["clusterId"] for p in papers if p["clusterId"] != paper["clusterId"])
    response = client.patch(f"{url}/papers/{paper['id']}", json={"clusterId": target})
    assert response.status_code == 200
    assert response.json()["clusterId"] == target
    assert response.json()["userModified"] is True
    moved = next(p for p in client.get(url + "/papers").json() if p["id"] == paper["id"])
    assert moved["clusterId"] == target


def test_move_paper_to_uncategorized_and_reject_unknown_cluster(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    _named_search(client, provider, url)
    paper_id = client.get(url + "/papers").json()[0]["id"]
    assert (
        client.patch(f"{url}/papers/{paper_id}", json={"clusterId": None}).json()["clusterId"]
        is None
    )
    assert client.patch(f"{url}/papers/{paper_id}", json={"clusterId": 99}).status_code == 422


def test_mark_paper_irrelevant(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    _named_search(client, provider, url)
    paper_id = client.get(url + "/papers").json()[0]["id"]
    response = client.patch(f"{url}/papers/{paper_id}", json={"isRelevant": False})
    assert response.json()["isRelevant"] is False
    assert response.json()["userModified"] is True
    fetched = next(p for p in client.get(url + "/papers").json() if p["id"] == paper_id)
    assert fetched["isRelevant"] is False


def test_patch_paper_validation(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    _named_search(client, provider, url)
    paper_id = client.get(url + "/papers").json()[0]["id"]
    assert client.patch(f"{url}/papers/{paper_id}", json={}).status_code == 422
    assert client.patch(f"{url}/papers/{uuid4()}", json={"isRelevant": False}).status_code == 404


def test_papers_and_subtopics_carry_manual_fields(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    _named_search(client, provider, url)
    paper = client.get(url + "/papers").json()[0]
    assert paper["isRelevant"] is True and paper["userModified"] is False
    assert client.get(url + "/subtopics").json()[0]["userModified"] is False


def test_subtopics_can_be_created_and_deleted(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    _named_search(client, provider, url)
    created = client.post(url + "/subtopics", json={"name": "Later", "description": "Manual"})
    assert created.status_code == 201
    cluster_id = created.json()["clusterId"]
    paper_id = client.get(url + "/papers").json()[0]["id"]
    assert (
        client.patch(f"{url}/papers/{paper_id}", json={"clusterId": cluster_id}).status_code == 200
    )
    assert client.delete(f"{url}/subtopics/{cluster_id}").status_code == 204
    assert client.get(url + "/papers").json()[0]["clusterId"] is None


def test_subtopics_can_be_merged(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    _named_search(client, provider, url)
    topics = client.get(url + "/subtopics").json()
    source, target = topics[0]["clusterId"], topics[1]["clusterId"]
    paper_id = next(
        paper["id"] for paper in client.get(url + "/papers").json() if paper["clusterId"] == source
    )
    merged = client.post(f"{url}/subtopics/{source}/merge", json={"targetClusterId": target})
    assert merged.status_code == 200 and merged.json()["clusterId"] == target
    assert client.get(url + "/subtopics").json() and all(
        topic["clusterId"] != source for topic in client.get(url + "/subtopics").json()
    )
    assert (
        next(p for p in client.get(url + "/papers").json() if p["id"] == paper_id)["clusterId"]
        == target
    )


def test_papers_carry_access_status(search_client):
    client, provider, url = search_client
    open_access = normalize_work(
        WORK
        | {
            "id": "https://openalex.org/W7777",
            "doi": "https://doi.org/10.1/oa",
            "open_access": {"is_oa": True, "oa_url": "https://repo.example/w.pdf"},
        }
    )
    provider.papers = [open_access, normalize_work(WORK)]
    client.post(url + "/search")
    statuses = {p["accessStatus"] for p in client.get(url + "/papers").json()}
    assert statuses == {"OPEN_ACCESS", "ABSTRACT_ONLY"}


def test_new_search_is_blocked_until_forced_when_edits_exist(search_client_named):
    client, provider, embedder, llm, url = search_client_named
    _named_search(client, provider, url)
    cluster_id = client.get(url + "/subtopics").json()[0]["clusterId"]
    client.patch(f"{url}/subtopics/{cluster_id}", json={"name": "Renamed"})
    blocked = client.post(url + "/search")
    assert blocked.status_code == 409
    assert client.post(url + "/search?force=true").status_code == 200
    assert all(not s["userModified"] for s in client.get(url + "/subtopics").json())
    assert all(not p["userModified"] for p in client.get(url + "/papers").json())


def test_search_reports_pipeline_stages(search_client_named, monkeypatch):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    seen = []
    original = client.app.state.search._set_stage

    def spy(run_id, stage):
        seen.append(stage)
        return original(run_id, stage)

    monkeypatch.setattr(client.app.state.search, "_set_stage", spy)
    client.post(url + "/search")
    assert seen == ["ANALYZING", "EMBEDDING", "CLUSTERING", "NAMING"]
    assert client.get(url + "/searches").json()[0]["stage"] is None


def test_stage_is_retrieving_while_a_search_runs(search_client_named):
    client, *_, url = search_client_named
    project_id = UUID(client.get(url).json()["id"])
    run = client.app.state.search.start(project_id)
    assert run.stage == "RETRIEVING"
    assert client.get(url + "/searches").json()[0]["stage"] == "RETRIEVING"


def test_failure_preserves_previous_results(search_client):
    client, provider, url = search_client
    client.post(url + "/search")
    original = client.get(url + "/papers").json()
    provider.error = ProviderError("RATE_LIMITED")
    assert client.post(url + "/search").status_code == 503
    assert client.get(url + "/papers").json() == original
    history = client.get(url + "/searches").json()
    assert history[0]["status"] == "FAILED"
    assert history[0]["errorCode"] == "RATE_LIMITED"
    assert history[1]["status"] == "COMPLETED"
    assert client.get(url).json()["status"] == "FAILED"
    provider.error = None
    assert client.post(url + "/search").status_code == 200


def test_successful_empty_search_replaces_previous_results(search_client):
    client, provider, url = search_client
    client.post(url + "/search")
    provider.papers = []
    response = client.post(url + "/search")
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["paperCount"] == 0
    assert client.get(url + "/papers").json() == []


def test_search_in_progress_blocks_mutations_and_recovers(search_client, engine):
    client, provider, url = search_client
    project_id = client.get(url).json()["id"]
    from uuid import UUID

    run = client.app.state.search.start(UUID(project_id))
    assert client.get(url).json()["status"] == "SEARCHING"
    assert client.get(url + "/searches").json()[0]["status"] == "SEARCHING"
    assert client.post(url + "/search").status_code == 409
    assert client.put(url, json=DATA).status_code == 409
    assert client.delete(url).status_code == 409
    assert provider.calls == []
    with Session(engine) as session, session.begin():
        row = session.get(SearchRunRow, run.id)
        row.startedAt = datetime.now(UTC) - timedelta(minutes=5)
    history = client.get(url + "/searches").json()
    assert history[0]["errorCode"] == "INTERRUPTED"
    assert client.get(url).json()["status"] == "FAILED"
    assert client.post(url + "/search").status_code == 200
    from researchpilot.search_persistence import SearchConflict

    with pytest.raises(SearchConflict):
        client.app.state.search.finish(run, error=ProviderError("INTERRUPTED"))
    assert len(client.get(url + "/papers").json()) == 1


def test_missing_project_never_calls_provider(search_client):
    client, provider, _ = search_client
    url = f"/api/projects/{uuid4()}"
    for method, suffix in [("post", "/search"), ("get", "/papers"), ("get", "/searches")]:
        assert getattr(client, method)(url + suffix).status_code == 404
        assert getattr(client, method)("/api/projects/bad-id" + suffix).status_code == 422
    assert provider.calls == []


def test_default_limit_and_snapshot_survives_edit(search_client):
    client, provider, url = search_client
    client.put(url, json={"title": "A", "researchQuestion": "B"})
    assert client.post(url + "/search").status_code == 200
    assert provider.calls[0].maxPaperCount == 100
    assert provider.calls[0].yearFrom is None
    client.put(url, json={"title": "A", "researchQuestion": "Changed"})
    assert client.get(url + "/searches").json()[0]["researchQuestion"] == "B"


def test_timeout_persists_failure(search_client, monkeypatch):
    client, provider, url = search_client

    async def slow(parameters):
        await asyncio.sleep(1)

    provider.search = slow
    monkeypatch.setattr("researchpilot.search.SEARCH_TIMEOUT_SECONDS", 0.01)
    assert client.post(url + "/search").status_code == 504
    assert client.get(url).json()["status"] == "FAILED"
    assert client.get(url + "/searches").json()[0]["errorCode"] == "TIMEOUT"


def test_unexpected_error_is_sanitized(search_client):
    client, provider, url = search_client
    provider.error = RuntimeError("secret-key-should-not-leak")
    response = client.post(url + "/search")
    assert response.status_code == 502
    assert "secret-key" not in response.text
    assert "secret-key" not in client.get(url + "/searches").text


def test_postgres_concurrent_search_start(search_client, engine):
    if engine.dialect.name != "postgresql":
        pytest.skip("Production row locking requires PostgreSQL")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import UUID
    from researchpilot.search_persistence import SearchConflict

    client, provider, url = search_client
    project_id = UUID(client.get(url).json()["id"])
    barrier = Barrier(2)

    def start():
        barrier.wait()
        try:
            client.app.state.search.start(project_id)
            return "started"
        except SearchConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(start) for _ in range(2)]
        assert sorted(future.result() for future in futures) == ["conflict", "started"]


@pytest.mark.parametrize("field,value", [("title", "Updated title"), ("abstract", "New abstract")])
def test_embedding_input_changes(search_client_with_embedder, field, value):
    client, provider, embedder, url = search_client_with_embedder
    assert client.post(url + "/search").status_code == 200
    provider.papers = [provider.papers[0].model_copy(update={field: value})]
    assert client.post(url + "/search").status_code == 200
    assert len(embedder.paper_batches) == 2
    assert client.post(url + "/search").status_code == 200
    assert len(embedder.paper_batches) == 2


@pytest.mark.parametrize(
    "field,value", [("model", "new-model"), ("dimension", 12), ("name", "Other")]
)
def test_embedding_identity_changes(search_client_with_embedder, field, value):
    client, provider, embedder, url = search_client_with_embedder
    client.post(url + "/search")
    setattr(embedder, field, value)
    assert client.post(url + "/search").status_code == 200
    assert len(embedder.paper_batches) == 2


@pytest.mark.parametrize("expired", [False, True])
def test_organization_search_lease(search_client_named, engine, expired):
    client, provider, _, _, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper = client.get(url + "/papers").json()[0]
    run = client.app.state.search.start(UUID(url.split("/")[-1]))
    if expired:
        with Session(engine) as session, session.begin():
            session.get(SearchRunRow, run.id).startedAt = datetime.now(UTC) - timedelta(seconds=300)
    expected = 200 if expired else 409
    assert client.patch(url + "/subtopics/0", json={"name": "Edited"}).status_code == expected
    assert (
        client.patch(url + "/papers/" + paper["id"], json={"isRelevant": False}).status_code
        == expected
    )


def test_empty_destinations_and_patch_validation(search_client_named):
    client, provider, _, _, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    topic = client.get(url + "/subtopics").json()[0]
    path = url + "/subtopics/" + str(topic["clusterId"])
    assert (
        client.patch(path, json={"name": "Renamed"}).json()["description"] == topic["description"]
    )
    members = [
        p for p in client.get(url + "/papers").json() if p["clusterId"] == topic["clusterId"]
    ]
    for paper in members:
        assert (
            client.patch(url + "/papers/" + paper["id"], json={"clusterId": None}).status_code
            == 200
        )
    path = url + "/papers/" + members[0]["id"]
    assert client.patch(path, json={"clusterId": topic["clusterId"]}).status_code == 200
    for value in (None, 0, "false"):
        assert client.patch(path, json={"isRelevant": value}).status_code == 422


@pytest.mark.parametrize(
    "change", ["move", "rename", "search", "question", "title", "abstract", "description"]
)
def test_delayed_explanation_context(search_client_named, engine, change):
    from researchpilot.search_persistence import SearchConflict, SubtopicRow

    client, provider, _, _, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper = client.get(url + "/papers").json()[0]
    project_id, paper_id = UUID(url.split("/")[-1]), UUID(paper["id"])
    service = client.app.state.search
    prepared = service._explanation_input(project_id, paper_id)
    if change == "move":
        client.patch(url + "/papers/" + paper["id"], json={"clusterId": None})
    elif change == "rename":
        client.patch(url + "/subtopics/" + str(paper["clusterId"]), json={"name": "Changed"})
    elif change == "search":
        client.post(url + "/search")
    elif change == "question":
        client.put(url, json={**DATA, "researchQuestion": "Different question"})
    else:
        with Session(engine) as session, session.begin():
            if change == "description":
                session.get(SubtopicRow, (project_id, paper["clusterId"])).description = "Changed"
            else:
                setattr(session.get(PaperRow, paper_id), change, "Changed")
    with pytest.raises(SearchConflict):
        service._store_explanation(project_id, paper_id, "Stale", prepared["fingerprint"])
    assert client.get(url + "/papers").json()[0]["classificationExplanation"] is None


def test_first_explanation_wins_and_rename_invalidates(search_client_named):
    client, provider, _, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper = client.get(url + "/papers").json()[0]
    project_id, paper_id = UUID(url.split("/")[-1]), UUID(paper["id"])
    service = client.app.state.search
    prepared = service._explanation_input(project_id, paper_id)
    assert (
        service._store_explanation(project_id, paper_id, "First", prepared["fingerprint"])
        == "First"
    )
    assert (
        service._store_explanation(project_id, paper_id, "Second", prepared["fingerprint"])
        == "First"
    )
    client.patch(url + "/subtopics/" + str(paper["clusterId"]), json={"name": "Changed"})
    assert client.get(url + "/papers").json()[0]["classificationExplanation"] is None
    assert client.post(url + "/papers/" + paper["id"] + "/explanation").status_code == 200
    assert len(llm.explain_calls) == 1


@pytest.mark.parametrize("outer", [False, True])
def test_explanation_timeouts(search_client_named, monkeypatch, outer):
    client, provider, _, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper = client.get(url + "/papers").json()[0]
    if outer:

        async def slow(*args):
            await asyncio.sleep(1)

        monkeypatch.setattr(llm, "explain_paper", slow)
        monkeypatch.setattr("researchpilot.search.NAMING_TIMEOUT_SECONDS", 0.001)
    else:
        llm.explain_error = ProviderError("TIMEOUT")
    response = client.post(url + "/papers/" + paper["id"] + "/explanation")
    assert response.status_code == 504
    assert response.json()["code"] == "EXPLANATION_TIMEOUT"


def test_shared_paper_interleaved_searches_keep_vector_metadata(engine):
    from researchpilot.search import SearchService
    from researchpilot.domain import ProjectInput
    from researchpilot.persistence import ProjectRepository
    from researchpilot.service import ProjectService

    provider = RecordingProvider()
    embedder = RecordingEmbeddingProvider()
    service = SearchService(engine, provider, embedder, RecordingLlmProvider())
    with Session(engine) as session, session.begin():
        projects = [
            ProjectService(ProjectRepository(session)).create(ProjectInput(**DATA))
            for _ in range(2)
        ]
    asyncio.run(service.search(projects[0].id))
    first = service.start(projects[0].id)
    reused = asyncio.run(
        service._prepare(first, SearchResult(papers=provider.papers, totalFound=1))
    )
    provider.papers = [provider.papers[0].model_copy(update={"title": "alpha changed"})]
    asyncio.run(service.search(projects[1].id))
    service.finish(first, reused)
    with Session(engine) as session:
        paper = session.get(PaperRow, provider.papers[0].id)
        assert paper.title == reused.ranked[0].paper.title
        assert paper.embedding == reused.vectors[paper.id]
        assert paper.embeddingInputHash == reused.hashes[paper.id]
    asyncio.run(service.search(projects[1].id))
    assert len(embedder.paper_batches) == 3


def test_legacy_cache_hashes_are_misses(search_client_named, engine):
    client, provider, embedder, llm, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper = client.get(url + "/papers").json()[0]
    with Session(engine) as session, session.begin():
        row = session.get(PaperRow, UUID(paper["id"]))
        row.embeddingInputHash = None
        association = session.get(ProjectPaperRow, (UUID(url.split("/")[-1]), row.id))
        association.classificationExplanation = "Legacy text"
    result = client.post(url + "/papers/" + paper["id"] + "/explanation")
    assert result.json()["explanation"] != "Legacy text"
    client.post(url + "/search")
    assert len(embedder.paper_batches[-1]) == 1


def test_postgres_concurrent_explanations_return_first_result(search_client_named, engine):
    if engine.dialect.name != "postgresql":
        pytest.skip("Production row locking requires PostgreSQL")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    client, provider, _, _, url = search_client_named
    provider.papers = _grouped_papers()
    client.post(url + "/search")
    paper = client.get(url + "/papers").json()[0]
    project_id, paper_id = UUID(url.split("/")[-1]), UUID(paper["id"])
    service = client.app.state.search
    prepared = service._explanation_input(project_id, paper_id)
    barrier = Barrier(2)

    def store(text):
        barrier.wait(timeout=5)
        return service._store_explanation(project_id, paper_id, text, prepared["fingerprint"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store, text) for text in ["One", "Two"]]
        results = [future.result(timeout=10) for future in futures]
    assert results[0] == results[1]
