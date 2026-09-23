"""NFR-OBS-1..2 and NFR-TRACE-1..2 (docs/requirements.md §16, §22, §29, §31)."""

import logging
import re

import pytest
from fastapi.testclient import TestClient

from fakes import DATA, grouped_papers
from researchpilot import search as search_module
from researchpilot.api import create_app
from researchpilot.llm import ClusterNaming, QueryExpansion

pytestmark = pytest.mark.nfr

REQUIRED_EVENTS = {
    "provider request": r"OpenAlex request page=\d+",
    "papers returned": r"OpenAlex results received=\d+",
    "duplicates removed": r"Search analyzed .*duplicates=\d+",
    "relevance duration": r"Search analyzed .*duration_ms=\d+",
    "clustering duration": r"Search clustering .*duration_ms=\d+",
    "LLM query expansion": r"OpenAI query expansion",
    "LLM cluster naming": r"OpenAI cluster naming",
    "LLM embeddings": r"OpenAI embeddings batch=\d+",
    "token usage": r"OpenAI completion usage .*total_tokens=\d+",
    "total duration": r"Search completed .*duration_ms=\d+",
}


def test_nfr_obs_1_search_logs_every_required_event(real_adapter_app, caplog):
    caplog.set_level(logging.INFO)
    response = real_adapter_app.client.post(real_adapter_app.url + "/search")
    assert response.status_code == 200
    run = response.json()
    logged = "\n".join(r.getMessage() for r in caplog.records)
    missing = [name for name, pattern in REQUIRED_EVENTS.items() if not re.search(pattern, logged)]
    assert not missing, f"§29 events not logged: {missing}"
    # Each provider request is logged: at least one "page=" record per generated query.
    page_requests = len(re.findall(r"OpenAlex request page=\d+", logged))
    assert page_requests >= len(run["generatedQueries"])


def test_nfr_obs_2_failures_log_codes_not_payloads(real_adapter_app, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    real_adapter_app.fail["openalex"] = (500, "MARKER-PAYLOAD-5a1e")
    response = real_adapter_app.client.post(real_adapter_app.url + "/search")
    assert response.json()["code"] == "UNAVAILABLE"
    del real_adapter_app.fail["openalex"]

    real_adapter_app.fail["openai"] = (500, "MARKER-LLM-PAYLOAD-7d21")
    response = real_adapter_app.client.post(real_adapter_app.url + "/search")
    # Query expansion and cluster naming both fall back on an LLM failure; the search
    # still completes.
    assert response.status_code == 200
    del real_adapter_app.fail["openai"]

    def explode(*args, **kwargs):
        raise RuntimeError("MARKER-EXCEPTION-9c3b")

    monkeypatch.setattr(search_module, "cluster_papers", explode)
    assert (
        real_adapter_app.client.post(real_adapter_app.url + "/search").json()["code"] == "INTERNAL"
    )
    # The app's own loggers; httpx's INFO request log is not enabled in production.
    records = "\n".join(
        f"{r.getMessage()} {r.exc_text or ''}"
        for r in caplog.records
        if r.name.startswith("researchpilot")
    )
    assert "UNAVAILABLE" in records and "INTERNAL" in records and "LLM_UNAVAILABLE" in records
    for marker in (
        "MARKER-PAYLOAD-5a1e",
        "MARKER-LLM-PAYLOAD-7d21",
        "MARKER-EXCEPTION-9c3b",
        "api.openalex.org",
        "/chat/completions",
    ):
        assert marker not in records, marker


def test_nfr_trace_1_completed_run_is_reproducible(search_client_named, engine):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    llm.expansion = ["llm testing", "llm code generation"]
    client.post(url + "/search")
    with TestClient(create_app(engine, provider)) as restarted:
        run = restarted.get(url + "/searches").json()[0]
    assert run["parameters"]["query"] == DATA["researchQuestion"]
    assert run["keywords"] == DATA["keywords"]
    assert run["generatedQueries"] == ["llm code generation", "llm testing"]
    assert run["failedQueries"] == []
    assert (run["parameters"]["yearFrom"], run["parameters"]["yearTo"]) == (2021, 2026)
    assert run["parameters"]["maxPaperCount"] == DATA["maxPaperCount"]
    assert run["provider"] == provider.name
    assert run["startedAt"] and run["finishedAt"] and run["finishedAt"] >= run["startedAt"]
    for field in ("totalFound", "duplicateCount", "filteredCount", "paperCount"):
        assert isinstance(run[field], int), field


METADATA_FIELDS = (
    "title",
    "authors",
    "doi",
    "doiUrl",
    "venue",
    "journal",
    "publisher",
    "publicationYear",
    "publicationDate",
    "citationCount",
    "sourceUrl",
    "publicationUrl",
    "openAccessUrl",
    "isOpenAccess",
    "abstract",
)


def test_nfr_trace_2_llm_output_never_becomes_metadata(search_client_named):
    client, provider, _, llm, url = search_client_named
    provider.papers = grouped_papers()
    fake = "Invented Title by A. Hallucination, doi 10.9999/fake"

    async def name_cluster(question, papers):
        return ClusterNaming(name=fake[:80], description=fake, keywords=["10.9999/fake"])

    async def expand_queries(question, keywords):
        return QueryExpansion(queries=["10.9999/fake invented"])

    async def explain_paper(question, subtopic, paper):
        return fake

    llm.name_cluster, llm.expand_queries, llm.explain_paper = (
        name_cluster,
        expand_queries,
        explain_paper,
    )
    client.post(url + "/search")
    served = client.get(url + "/papers").json()
    named_clusters = {s["clusterId"] for s in client.get(url + "/subtopics").json()}
    target = next(p for p in served if p["clusterId"] in named_clusters)
    client.post(f"{url}/papers/{target['id']}/explanation")
    served = {p["sourceId"]: p for p in client.get(url + "/papers").json()}
    for original in provider.papers:
        expected = original.model_dump(mode="json")
        actual = served[original.sourceId]
        for field in METADATA_FIELDS:
            if field in expected:
                assert actual[field] == expected[field], (original.sourceId, field)
