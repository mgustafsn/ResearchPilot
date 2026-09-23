"""NFR-REL-1..4 (docs/requirements.md §28, §31): failures degrade, never corrupt."""

import asyncio
import logging

import pytest

from fakes import grouped_papers
from researchpilot import search as search_module
from researchpilot.papers import ProviderError, SearchResult

pytestmark = pytest.mark.nfr


def _searched_with_edit(client, provider, url):
    provider.papers = grouped_papers()
    assert client.post(url + "/search").status_code == 200
    topic = client.get(url + "/subtopics").json()[0]
    client.patch(f"{url}/subtopics/{topic['clusterId']}", json={"name": "Kept by the user"})
    return client.get(url + "/papers").json(), client.get(url + "/subtopics").json()


@pytest.mark.parametrize(
    "stage,code,status",
    [
        ("provider", "UNAVAILABLE", 503),
        ("provider", "RATE_LIMITED", 503),
        ("provider", "TIMEOUT", 504),
        ("provider", "INVALID_RESPONSE", 502),
        ("embedding", "EMBEDDING_UNAVAILABLE", 503),
        ("clustering", "INTERNAL", 502),
    ],
)
def test_nfr_rel_1_failures_return_codes_and_preserve_results(
    search_client_named, monkeypatch, stage, code, status
):
    client, provider, embedder, _, url = search_client_named
    papers, subtopics = _searched_with_edit(client, provider, url)
    if stage == "provider":
        provider.error = ProviderError(code)
    elif stage == "embedding":
        embedder.error = ProviderError(code)
        embedder.model = "force-new-vectors"  # bypass the embedding cache
    else:
        monkeypatch.setattr(search_module, "cluster_papers", _raise_runtime_error)
        embedder.model = "force-new-vectors"
    response = client.post(url + "/search?force=true")
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert client.get(url + "/papers").json() == papers
    assert client.get(url + "/subtopics").json() == subtopics


def _raise_runtime_error(*args, **kwargs):
    raise RuntimeError("clustering blew up")


def test_nfr_rel_1_no_papers_completes_empty(search_client_named):
    client, provider, _, _, url = search_client_named
    provider.papers = []
    response = client.post(url + "/search")
    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED" and response.json()["paperCount"] == 0
    assert client.get(url + "/papers").json() == []


def test_nfr_rel_2_expansion_failure_falls_back_to_keywords(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion_error = ProviderError("LLM_INVALID_RESPONSE")
    run = client.post(url + "/search").json()
    assert run["status"] == "COMPLETED"
    assert [p.query for p in provider.calls] == ["software engineering"]


@pytest.mark.parametrize("code", ["LLM_UNAVAILABLE", "LLM_INVALID_RESPONSE"])
def test_nfr_rel_2_naming_failure_keeps_numbered_clusters(search_client_named, code):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    llm.error = ProviderError(code)
    run = client.post(url + "/search").json()
    assert run["status"] == "COMPLETED" and run["clusterCount"] >= 2
    assert run["namingError"] == code
    assert client.get(url + "/subtopics").json() == []


def test_nfr_rel_2_explanation_timeout_is_504(search_client_named):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    client.post(url + "/search")
    subtopics = client.get(url + "/subtopics").json()
    named_clusters = {topic["clusterId"] for topic in subtopics}
    paper = next(p for p in client.get(url + "/papers").json() if p["clusterId"] in named_clusters)
    llm.explain_error = ProviderError("TIMEOUT")
    response = client.post(f"{url}/papers/{paper['id']}/explanation")
    assert (response.status_code, response.json()["code"]) == (504, "EXPLANATION_TIMEOUT")


def _fail_query(provider, bad_query, code):
    original = provider.search

    async def search(parameters):
        if parameters.query == bad_query:
            provider.calls.append(parameters)
            raise ProviderError(code)
        return await original(parameters)

    provider.search = search


def test_nfr_rel_3_partial_query_failure_keeps_surviving_results(search_client_named, caplog):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    llm.expansion = ["good query", "secret bad query"]
    _fail_query(provider, "secret bad query", "RATE_LIMITED")
    caplog.set_level(logging.INFO)
    response = client.post(url + "/search")
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "COMPLETED" and run["paperCount"] == 15
    assert run["failedQueries"] == ["secret bad query"]
    assert client.get(url + "/searches").json()[0]["failedQueries"] == ["secret bad query"]
    messages = [record.getMessage() for record in caplog.records]
    assert any("RATE_LIMITED" in m for m in messages)
    assert not any("secret bad query" in m for m in messages)


def test_nfr_rel_3_all_queries_failing_fails_with_first_code(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion = ["first query", "second query"]
    provider.error = ProviderError("RATE_LIMITED")
    response = client.post(url + "/search")
    assert (response.status_code, response.json()["code"]) == (503, "RATE_LIMITED")


def _empty_query(provider, query):
    original = provider.search

    async def search(parameters):
        if parameters.query == query:
            provider.calls.append(parameters)
            return SearchResult(papers=[], totalFound=0)
        return await original(parameters)

    provider.search = search


def test_nfr_rel_3_partial_failure_with_no_surviving_papers_keeps_results(search_client_named):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    first = client.post(url + "/search").json()
    assert first["status"] == "COMPLETED" and first["paperCount"] == 15
    papers = client.get(url + "/papers").json()
    subtopics = client.get(url + "/subtopics").json()

    llm.expansion = ["good query", "bad query"]
    assert {q["query"] for q in client.post(url + "/queries").json()} == {"good query", "bad query"}
    _empty_query(provider, "good query")
    _fail_query(provider, "bad query", "RATE_LIMITED")
    response = client.post(url + "/search?force=true")
    assert (response.status_code, response.json()["code"]) == (503, "RATE_LIMITED")
    assert client.get(url + "/papers").json() == papers
    assert client.get(url + "/subtopics").json() == subtopics


def test_nfr_rel_3_non_provider_errors_still_propagate(search_client_named):
    client, provider, _, llm, url = search_client_named
    llm.expansion = ["first query", "second query"]
    original = provider.search

    async def search(parameters):
        if parameters.query == "first query":
            provider.calls.append(parameters)
            raise ProviderError("RATE_LIMITED")
        if parameters.query == "second query":
            provider.calls.append(parameters)
            raise RuntimeError("boom")
        return await original(parameters)

    provider.search = search
    response = client.post(url + "/search")
    assert (response.status_code, response.json()["code"]) == (502, "INTERNAL")


async def _hang(*args, **kwargs):
    await asyncio.sleep(3600)


def test_nfr_rel_4_hanging_retrieval_times_out(search_client_named, monkeypatch):
    client, provider, _, _, url = search_client_named
    monkeypatch.setattr(search_module, "SEARCH_TIMEOUT_SECONDS", 0.2)
    provider.search = _hang
    response = client.post(url + "/search")
    assert (response.status_code, response.json()["code"]) == (504, "TIMEOUT")


def test_nfr_rel_4_hanging_embedding_times_out(search_client_named, monkeypatch):
    client, provider, embedder, _, url = search_client_named
    monkeypatch.setattr(search_module, "EMBEDDING_TIMEOUT_SECONDS", 0.2)
    embedder.embed = _hang
    response = client.post(url + "/search")
    assert (response.status_code, response.json()["code"]) == (504, "TIMEOUT")


def test_nfr_rel_4_hanging_naming_falls_back(search_client_named, monkeypatch):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    monkeypatch.setattr(search_module, "NAMING_TIMEOUT_SECONDS", 0.2)
    llm.name_cluster = _hang
    run = client.post(url + "/search").json()
    assert run["status"] == "COMPLETED" and run["namingError"]
