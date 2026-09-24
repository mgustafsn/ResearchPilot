import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from researchpilot.api import create_app
from researchpilot.config import scholarly_providers, scopus_headers
from researchpilot.papers import ProviderError, SearchParameters
from researchpilot.providers.scopus import ScopusProvider, normalize_entry

ENTRY = {
    "eid": "2-s2.0-123456789",
    "dc:title": "Research on infrastructure as code",
    "dc:description": "An abstract supplied by Scopus.",
    "prism:doi": "10.1234/EXAMPLE.5",
    "prism:coverDate": "2024-02-03",
    "prism:publicationName": "Software Journal",
    "prism:aggregationType": "Journal",
    "citedby-count": "12",
    "openaccess": {"openaccessFlag": True},
    "author": [{"authid": "123", "authname": "A. Researcher"}],
    "link": [
        {
            "@ref": "scopus",
            "@href": "https://www.scopus.com/record/display.uri?eid=2-s2.0-123456789",
        }
    ],
}


def retrieve(handler, parameters=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ScopusProvider(client).search(parameters or SearchParameters(query="IaC"))

    return asyncio.run(run())


def test_normalize_entry_uses_only_provider_fields():
    paper = normalize_entry(ENTRY)
    assert paper.source == "Scopus"
    assert paper.id == normalize_entry(ENTRY).id
    assert paper.abstract == ENTRY["dc:description"]
    assert paper.doi == "10.1234/example.5"
    assert paper.citationCount == 12
    assert paper.isOpenAccess is True
    assert paper.authors[0].name == "A. Researcher"
    assert paper.journal == "Software Journal"
    sparse = normalize_entry({"eid": ENTRY["eid"]})
    assert sparse.abstract is None
    assert sparse.isOpenAccess is None
    assert sparse.citationCount is None


def test_scopus_paginates_standard_view_and_applies_years():
    calls = []

    def handler(request):
        calls.append(request)
        start = int(request.url.params["start"])
        count = int(request.url.params["count"])
        return httpx.Response(
            200,
            json={
                "search-results": {
                    "opensearch:totalResults": "205",
                    "entry": [
                        ENTRY | {"eid": f"2-s2.0-{i + 100}"} for i in range(start, start + count)
                    ],
                }
            },
        )

    result = retrieve(
        handler, SearchParameters(query="IaC", yearFrom=2020, yearTo=2024, maxPaperCount=205)
    )
    assert len(result.papers) == 205
    assert len(calls) == 2
    assert calls[0].url.params["view"] == "STANDARD"
    assert calls[0].url.params["sort"] == "relevancy"
    assert (
        calls[0].url.params["query"] == "TITLE-ABS-KEY(IaC) AND PUBYEAR > 2019 AND PUBYEAR < 2025"
    )
    assert [call.url.params["count"] for call in calls] == ["200", "5"]


def test_scopus_rejects_invalid_results_and_maps_authentication():
    with pytest.raises(ProviderError) as error:
        retrieve(lambda request: httpx.Response(401))
    assert error.value.code == "AUTHENTICATION"
    with pytest.raises(ProviderError) as error:
        retrieve(lambda request: httpx.Response(200, json={"search-results": {"entry": []}}))
    assert error.value.code == "INVALID_RESPONSE"


def test_scopus_configuration(monkeypatch):
    monkeypatch.setenv("SCHOLARLY_PROVIDER", "scopus")
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-secret")
    assert scholarly_providers() == ["scopus"]
    assert scopus_headers()["X-ELS-APIKey"] == "test-secret"
    monkeypatch.delenv("ELSEVIER_API_KEY")
    with pytest.raises(RuntimeError, match="ELSEVIER_API_KEY"):
        scholarly_providers()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ["openalex"]),
        ("openalex,scopus", ["openalex", "scopus"]),
        (" OpenAlex , SCOPUS ", ["openalex", "scopus"]),
        ("scopus,openalex", ["scopus", "openalex"]),
        ("openalex,openalex", ["openalex"]),
        ("openalex,,scopus", ["openalex", "scopus"]),
    ],
)
def test_scholarly_provider_lists(monkeypatch, value, expected):
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-secret")
    if value is None:
        monkeypatch.delenv("SCHOLARLY_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("SCHOLARLY_PROVIDER", value)
    assert scholarly_providers() == expected


@pytest.mark.parametrize("value", ["", " , ", "pubmed", "openalex,pubmed"])
def test_scholarly_provider_rejects_invalid_lists(monkeypatch, value):
    monkeypatch.setenv("SCHOLARLY_PROVIDER", value)
    with pytest.raises(RuntimeError, match="SCHOLARLY_PROVIDER"):
        scholarly_providers()


def test_scopus_in_a_list_still_requires_its_key(monkeypatch):
    monkeypatch.setenv("SCHOLARLY_PROVIDER", "openalex,scopus")
    monkeypatch.delenv("ELSEVIER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ELSEVIER_API_KEY"):
        scholarly_providers()


def test_app_selects_scopus_without_exposing_key(engine, monkeypatch):
    monkeypatch.setenv("SCHOLARLY_PROVIDER", "scopus")
    monkeypatch.setenv("ELSEVIER_API_KEY", "test-secret")
    with TestClient(create_app(engine)) as client:
        response = client.get("/api/settings/status")
    assert response.status_code == 200
    assert response.json()["scholarlyProvider"] == "Scopus"
    assert response.json()["elsevierApiKeyConfigured"] is True
    assert "test-secret" not in response.text
