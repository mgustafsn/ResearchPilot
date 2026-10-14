"""Exact DOI metadata is previewed from providers before a reference is saved."""

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import DATA
from researchpilot.api import create_app
from researchpilot.doi_lookup import DoiLookupUnavailable, canonical_doi
from researchpilot.papers import DoiPaperMetadata
from researchpilot.providers.doi import CrossrefDoiPaperProvider, DataCiteDoiPaperProvider


def test_canonical_doi():
    assert canonical_doi(" DOI:10.1234/ABC.1 ") == "10.1234/abc.1"
    assert canonical_doi("https://doi.org/10.1234/ABC.1") == "10.1234/abc.1"
    for value in ["", "10.1/a", "https://doi.org/10.1234/a?x=1", "https://other.test/10.1234/a"]:
        with pytest.raises(Exception):
            canonical_doi(value)


def test_crossref_and_datacite_records():
    seen = []

    def respond(request):
        seen.append(str(request.url))
        if request.url.host == "api.crossref.org":
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "data": {
                    "attributes": {
                        "doi": "10.1234/abc",
                        "titles": [{"title": "Verified title"}],
                        "creators": [{"name": "A. Author"}],
                        "publicationYear": 2024,
                        "container": {"title": "Example Journal"},
                        "descriptions": [
                            {
                                "descriptionType": "Abstract",
                                "description": "<p>Data &amp; methods</p>",
                            }
                        ],
                    }
                }
            },
        )

    async def lookup():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            from researchpilot.doi_lookup import DoiLookupService

            return await DoiLookupService(
                [CrossrefDoiPaperProvider(client), DataCiteDoiPaperProvider(client)]
            ).lookup("https://doi.org/10.1234/ABC")

    result = asyncio.run(lookup())
    assert result.model_dump() == {
        "source": "DataCite",
        "doi": "10.1234/abc",
        "title": "Verified title",
        "authors": ["A. Author"],
        "year": 2024,
        "venue": "Example Journal",
        "url": "https://doi.org/10.1234/abc",
        "abstract": "Data & methods",
    }
    assert seen == [
        "https://api.crossref.org/works/10.1234%2Fabc",
        "https://api.datacite.org/dois/10.1234%2Fabc",
    ]


def test_crossref_parses_authors_and_rejects_mismatched_record():
    body = {
        "message": {
            "DOI": "10.1234/ABC",
            "title": ["A paper"],
            "author": [{"given": "Ada", "family": "Lovelace"}],
            "published": {"date-parts": [[2023, 1, 1]]},
            "container-title": ["Journal"],
            "abstract": "<jats:p>Findings &amp; context.</jats:p>",
        }
    }

    async def lookup():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        ) as client:
            provider = CrossrefDoiPaperProvider(client)
            result = await provider.lookup_doi("10.1234/abc")
            body["message"]["DOI"] = "10.1234/other"
            with pytest.raises(DoiLookupUnavailable):
                await provider.lookup_doi("10.1234/abc")
            return result

    result = asyncio.run(lookup())
    assert (result.title, result.authors, result.year, result.venue) == (
        "A paper",
        ["Ada Lovelace"],
        2023,
        "Journal",
    )
    assert result.abstract == "Findings & context."


class StubProvider:
    name = "Stub"

    async def lookup_doi(self, doi):
        if doi == "10.1234/missing":
            return None
        if doi == "10.1234/down":
            raise DoiLookupUnavailable("source down")
        return DoiPaperMetadata(
            source=self.name,
            doi=doi,
            title="Provider title",
            authors=["A. Author"],
            year=2024,
            venue="Journal",
            url=f"https://doi.org/{doi}",
            abstract=None if doi == "10.1234/noabstract" else "Provider supplied findings.",
        )


class StubLlm:
    name = "Stub LLM"
    model = "stub"

    def __init__(self):
        self.calls = []

    async def summarize_abstract(self, title, abstract):
        from researchpilot.llm import AbstractSummary

        self.calls.append((title, abstract))
        return AbstractSummary(summary="The provider abstract reports findings.")


def test_lookup_preview_does_not_save_and_manual_edits_win(engine):
    llm = StubLlm()
    with TestClient(create_app(engine, doi_providers=[StubProvider()], llm_provider=llm)) as client:
        project = client.post("/api/projects", json=DATA).json()
        refs = f"/api/projects/{project['id']}/references"
        preview = client.get(refs + "/lookup", params={"doi": "DOI:10.1234/ABC"})
        assert preview.status_code == 200
        assert preview.json()["title"] == "Provider title"
        assert preview.json()["doi"] == "10.1234/abc"
        assert client.get(refs).json() == []
        summary = client.post(refs + "/summary", json={"doi": "10.1234/abc"})
        assert summary.json() == {"summary": "The provider abstract reports findings."}
        assert llm.calls == [("Provider title", "Provider supplied findings.")]
        assert client.get(refs).json() == []
        assert client.post(refs + "/summary", json={"doi": "10.1234/noabstract"}).status_code == 422
        saved = client.post(
            refs,
            json={
                "title": "Corrected title",
                "authors": preview.json()["authors"],
                "year": preview.json()["year"],
                "venue": preview.json()["venue"],
                "doi": preview.json()["doi"],
                "url": preview.json()["url"],
            },
        )
        assert saved.status_code == 201
        assert saved.json()["title"] == "Corrected title"
        assert saved.json()["authors"] == ["A. Author"]
        assert client.get(refs + "/lookup", params={"doi": "bad"}).status_code == 422
        assert client.get(refs + "/lookup", params={"doi": "10.1234/missing"}).status_code == 404
        assert client.get(refs + "/lookup", params={"doi": "10.1234/down"}).status_code == 503
        assert (
            client.get(
                "/api/projects/00000000-0000-0000-0000-000000000000/references/lookup",
                params={"doi": "10.1234/abc"},
            ).status_code
            == 404
        )


def test_summary_requires_configured_llm(engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with TestClient(create_app(engine, doi_providers=[StubProvider()])) as client:
        project = client.post("/api/projects", json=DATA).json()
        url = f"/api/projects/{project['id']}/references/summary"
        response = client.post(url, json={"doi": "10.1234/abc"})
        assert response.status_code == 503
        assert response.json()["code"] == "LLM_UNAVAILABLE"
